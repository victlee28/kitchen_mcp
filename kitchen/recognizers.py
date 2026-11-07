"""Real recognizers (shell zone: network). ``GeminiRecognizer`` sends the photo/drawing to a Gemini vision model and returns the raw draft
that ``recognition.build_draft`` then checks; nothing it says is trusted."""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from .backends import BackendError, gemini_config
from .config import Config
from .prompts import RECOGNITION_SCHEMA, recognition_text
from .recognition import RecognitionInput
from .spec import MODULE_TYPES

DEFAULT_VISION_MODEL = "gemini-2.5-flash"
SUPPORTED_MEDIA = ("image/png", "image/jpeg", "image/webp")


def sniff_media_type(data: bytes, declared: str = "") -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return declared if declared in SUPPORTED_MEDIA else ""


class GeminiRecognizer:
    def __init__(self, config: Config):
        self.cfg = gemini_config(config)
        self.model = config.gemini_vision_model or DEFAULT_VISION_MODEL

    def body(self, source: RecognitionInput) -> dict:
        media = sniff_media_type(source.data, source.media_type)
        if not media:
            raise BackendError("unsupported", "Image must be PNG, JPEG or WebP")
        types = tuple(t for t in MODULE_TYPES if t != "corner-shelf")
        return {"contents": [{"role": "user", "parts": [
            {"text": recognition_text(source.kind, types)},
            {"inline_data": {"mime_type": media, "data": base64.b64encode(source.data).decode()}}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": RECOGNITION_SCHEMA, "temperature": 0.1}}

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
        text = "".join(p.get("text", "") for c in (data.get("candidates") or [])[:1]
                       for p in (c.get("content") or {}).get("parts") or [])
        try:
            raw = json.loads(text)
        except ValueError:
            raise BackendError("generation-failed", "Gemini did not return JSON")
        return raw if isinstance(raw, dict) else {"modules": []}
