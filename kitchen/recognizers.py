"""Real recognizers (shell zone: network). ``GeminiRecognizer`` sends the photo/drawing to a Gemini vision model and returns the raw draft
that ``recognition.build_draft`` then checks; nothing it says is trusted."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .backends import BackendError, gemini_config
from .config import Config
from .recognition import Deferred, RecognitionInput, gemini_wire, recognizer_wire

DEFAULT_VISION_MODEL = "gemini-2.5-flash"


class GeminiRecognizer:
    def __init__(self, config: Config):
        self.cfg = gemini_config(config)
        self.model = config.gemini_vision_model or DEFAULT_VISION_MODEL

    def body(self, source: RecognitionInput) -> dict:
        media = gemini_wire.sniff_media_type(source.data, source.media_type)
        if not media:
            raise BackendError("unsupported", "Image must be PNG, JPEG or WebP")
        return gemini_wire.request_body(source.kind, source.data, media, source.note)

    def recognize(self, source: RecognitionInput) -> dict:
        body = self.body(source)
        url = f"{self.cfg['base']}/models/{urllib.parse.quote(self.model)}:generateContent"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": self.cfg["key"]})
        try:
            with urllib.request.urlopen(req, timeout=min(self.cfg["timeout"], 120)) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise BackendError("overloaded" if e.code in (429, 503) else "generation-failed",
                               f"Gemini returned {e.code}: {e.read()[:300].decode('utf-8', 'replace')}")
        except TimeoutError:
            raise BackendError("timeout", "Gemini did not answer in time")
        except (urllib.error.URLError, ConnectionError) as e:
            raise BackendError("overloaded", f"Cannot reach Gemini: {getattr(e, 'reason', e)}")
        raw = gemini_wire.parse_draft(gemini_wire.answer_text(data))
        if raw is None:
            raise BackendError("generation-failed", "Gemini did not return a JSON object")
        return raw


def _post_json(url: str, body: dict, timeout: float) -> object:
    """POST a JSON body to the cabinet-recognizer service and return its JSON answer; failures become ``BackendError`` codes."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = recognizer_wire.response_error(_json_or_none(e.read())) or f"HTTP {e.code}"
        raise BackendError("overloaded" if e.code in (429, 502, 503) else "generation-failed", f"cabinet-recognizer: {detail}")
    except TimeoutError:
        raise BackendError("timeout", "cabinet-recognizer did not answer in time")
    except (urllib.error.URLError, ConnectionError) as e:
        raise BackendError("overloaded", f"Cannot reach cabinet-recognizer at {url}: {getattr(e, 'reason', e)}")
    except ValueError:
        raise BackendError("generation-failed", "cabinet-recognizer did not answer with JSON")


def _service_url(config: Config) -> str:
    if not config.cabinet_recognizer_url or not config.cabinet_recognizer_url.startswith(("http://", "https://")):
        raise BackendError("unsupported", "CABINET_RECOGNIZER_URL must be an http(s) URL")
    return config.cabinet_recognizer_url                       # fixed by configuration, never taken from a request


def _draft(payload: object) -> dict:
    raw = recognizer_wire.draft_from_kitchen_spec(payload)
    if raw is None:
        raise BackendError("generation-failed", f"cabinet-recognizer: {recognizer_wire.response_error(payload) or 'no kitchen in the answer'}")
    layout = recognizer_wire.layout_from_runs(payload)
    if layout is not None:
        raw["layout"] = layout                     # the kitchen by runs; build_layout checks it, an anchored recognition places it
    return raw


class CabinetRecognizerHttp:
    """The stand-alone cabinet-recognizer service (services/cabinet-recognizer) over HTTP. Its model keys never reach this process: it only
    sends the picture and the user's hint and reads back the cabinets (``recognizer_wire`` does the format work, ``build_draft`` the checking)."""

    def __init__(self, config: Config):
        self.url = _service_url(config) + "/recognize"
        self.timeout = config.cabinet_recognizer_timeout

    def recognize(self, source: RecognitionInput) -> dict:
        return _draft(_post_json(self.url, recognizer_wire.request_body(source.kind, source.data, source.note), self.timeout))


class CabinetInboxHttp:
    """The same service WITHOUT a model API: ``recognize`` opens a job (``POST /jobs``) and raises ``Deferred`` until someone (Claude Desktop, by
    chat) has answered the job's questions; ``collect(job)`` asks the service to continue and returns the draft once the job is done."""

    def __init__(self, config: Config):
        self.base = _service_url(config)
        self.timeout = config.cabinet_recognizer_timeout

    def recognize(self, source: RecognitionInput) -> dict:
        return self._read(_post_json(self.base + "/jobs", recognizer_wire.request_body(source.kind, source.data, source.note), self.timeout))

    def collect(self, job: str) -> dict:
        job = recognizer_wire.clean_job_id(job)
        if not job:
            raise BackendError("unsupported", "not a job id")
        return self._read(_post_json(f"{self.base}/jobs/{job}/resume", {}, self.timeout))

    def _read(self, payload: object) -> dict:
        progress = recognizer_wire.job_progress(payload)
        job = payload.get("id") if isinstance(payload, dict) else None
        if progress["state"] == "waiting":
            raise Deferred(job if isinstance(job, str) else "", progress["step"])
        if progress["state"] == "error":
            raise BackendError("generation-failed", f"cabinet-recognizer: {progress['message']}")
        return _draft(payload)


def _json_or_none(data: bytes):
    try:
        return json.loads(data)
    except ValueError:
        return None
