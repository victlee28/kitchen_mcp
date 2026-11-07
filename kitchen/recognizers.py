"""Real recognizers (shell zone: network). ``GeminiRecognizer`` sends the photo/drawing to a Gemini vision model and returns the raw draft
that ``recognition.build_draft`` then checks; nothing it says is trusted."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .backends import BackendError, gemini_config
from .config import Config
from .recognition import RecognitionInput, gemini_wire

DEFAULT_VISION_MODEL = "gemini-2.5-flash"


class GeminiRecognizer:
    def __init__(self, config: Config):
        self.cfg = gemini_config(config)
        self.model = config.gemini_vision_model or DEFAULT_VISION_MODEL

    def body(self, source: RecognitionInput) -> dict:
        media = gemini_wire.sniff_media_type(source.data, source.media_type)
        if not media:
            raise BackendError("unsupported", "Image must be PNG, JPEG or WebP")
        return gemini_wire.request_body(source.kind, source.data, media)

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
