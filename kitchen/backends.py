"""Image-generation adapters. The image-job orchestrator does not depend on a specific model API.

- `recolor`: change the target region's color while preserving shading, without an AI model.
- `job-package`: export prompts and images for a person or external chat model; import the result with `submit_image_result`.
- `gemini`: call the Gemini image API. Credentials and model settings use `GEMINI_API_KEY`, `GEMINI_IMAGE_MODEL`,
  or a separate environment file via `GEMINI_ENV_FILE`.
- `openai`: call the OpenAI image edit API (the reference image + instruction): `OPENAI_API_KEY`, `OPENAI_IMAGE_MODEL`.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from pathlib import Path

from typing import Any

from . import builtin
from .catalog import Catalog
from .config import Config
from .i18n import pick
from .words import say

class BackendError(ValueError):
    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code  # thieu-anh | khong-ho-tro | qua-tai | het-gio | sinh-that-bai


ASYNC = frozenset({"gemini", "openai"})      # backends that answer later (a worker thread waits for the model)
CODED = ("recolor", "job-package", "gemini", "openai")      # the adapters this module implements (catalog kind ``backend`` is closed to others)


def _rank(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else float("inf")


def table(catalog: Catalog = builtin.CATALOG, lang: str = "vi") -> dict[str, dict[str, Any]]:
    """The image backends offered, best first: catalog kind ``backend`` (the workshop renames, reorders by ``rank`` or hides them; API keys
    stay in the environment). Only backends this module implements are listed."""
    items = [it for it in catalog.all("backend") if it.id in CODED]
    items.sort(key=lambda it: _rank(it.data.get("rank")))      # stable: catalog order breaks ties
    return {it.id: {"name": pick(it.data.get("name"), lang), "kind": list(it.data.get("kind") or []), "async": it.id in ASYNC,
                    "supported": list(it.data.get("supported") or []), "needsConfig": list(it.data.get("needsConfig") or [])} for it in items}



# ------------------------------------------------------------------ Gemini
_RATIO = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]


def _read_env_file(path: str) -> dict:
    out = {}
    p = Path(path).expanduser()
    if not p.is_file():
        raise BackendError("unsupported", say("backend.gemini.env-missing", path=p))
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def gemini_config(config: Config) -> dict:
    """Khóa/model: giá trị trong Config (từ biến môi trường) ưu tiên, sau đó file ``config.gemini_env_file``. Không bao giờ trả khóa ra ngoài log."""
    f = _read_env_file(config.gemini_env_file) if config.gemini_env_file else {}
    key = config.gemini_api_key or f.get("GEMINI_API_KEY", "")
    if not key:
        raise BackendError("unsupported", say("backend.gemini.no-key"))
    return {"key": key, "model": config.gemini_model or f.get("GEMINI_IMAGE_MODEL") or "gemini-3-pro-image",
            "base": config.gemini_base_url, "timeout": config.gemini_timeout, "imageSize": config.gemini_image_size}


def ratio(w: int, h: int) -> str:
    r = w / h
    return min(_RATIO, key=lambda t: abs(int(t.split(":")[0]) / int(t.split(":")[1]) - r))


def gemini_body(text: str, images: list[Path], size: tuple[int, int], image_size: str = "") -> dict[str, Any]:
    """Thân request generateContent của Gemini API. Ảnh nằm trong phần inline_data (mime_type + base64):
    máy chủ Gemini tự giải mã và đưa ảnh vào model như ảnh đính kèm — đây là cách duy nhất để model 'thấy' ảnh base64."""
    parts: list[dict] = [{"text": text}]
    for p in images:
        parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(Path(p).read_bytes()).decode()}})
    img_cfg = {"aspectRatio": ratio(*size)}
    if image_size:
        img_cfg["imageSize"] = image_size
    return {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": img_cfg}}


class Gemini:
    def __init__(self, config: Config):
        self.cfg = gemini_config(config)

    def generate(self, text: str, images: list[Path], out_path: Path, size: tuple[int, int]) -> dict[str, Any]:
        body = gemini_body(text, images, size, self.cfg["imageSize"])
        img_cfg = body["generationConfig"]["imageConfig"]
        url = f"{self.cfg['base']}/models/{urllib.parse.quote(self.cfg['model'])}:generateContent"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": self.cfg["key"]})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.cfg["timeout"]) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read()[:600].decode("utf-8", "replace")
            if e.code in (429, 503):
                raise BackendError("overloaded", say("backend.gemini.busy", code=e.code, msg=msg))
            raise BackendError("generation-failed", say("backend.gemini.http", code=e.code, msg=msg))
        except TimeoutError:
            raise BackendError("timeout", say("backend.gemini.timeout", seconds=f"{self.cfg['timeout']:.0f}"))
        except (urllib.error.URLError, ConnectionError) as e:
            raise BackendError("overloaded", say("backend.gemini.unreachable", reason=getattr(e, 'reason', e)))
        cands = data.get("candidates") or []
        for c in cands:
            for part in (c.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    out_path.write_bytes(base64.b64decode(inline["data"]))
                    return {"model": self.cfg["model"], "aspectRatio": img_cfg["aspectRatio"], "giay": round(time.monotonic() - t0, 1),
                            "mime": inline.get("mimeType") or inline.get("mime_type")}
        reason = (cands[0].get("finishReason") if cands else None) or (data.get("promptFeedback") or {}).get("blockReason")
        text_out = " ".join(p.get("text", "") for c in cands for p in (c.get("content") or {}).get("parts") or [])[:300]
        raise BackendError("generation-failed", say("backend.gemini.no-image", reason=reason or say("backend.gemini.unknown-reason"), text=text_out).strip())


# ------------------------------------------------------------------ OpenAI images
OPENAI_SIZES = {"1:1": "1024x1024", "3:2": "1536x1024", "2:3": "1024x1536"}      # the sizes the image API makes; the result is fitted later
OPENAI_DEFAULT_MODEL = "gpt-image-1"


def openai_size(w: int, h: int) -> str:
    r = w / h
    return OPENAI_SIZES["3:2"] if r >= 1.2 else OPENAI_SIZES["2:3"] if r <= 1 / 1.2 else OPENAI_SIZES["1:1"]


def multipart(fields: list[tuple[str, str]], files: list[tuple[str, str, bytes, str]], boundary: str) -> bytes:
    """A multipart/form-data body: text ``fields`` (name, value) and ``files`` (name, filename, bytes, content type)."""
    out = bytearray()
    for name, value in fields:
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    for name, filename, data, ctype in files:
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out)


class OpenAIImages:
    """The OpenAI image edit endpoint: the job's images (reference first) and the same instruction text as Gemini get."""

    def __init__(self, config: Config, opener=urllib.request.urlopen):
        if not config.openai_api_key:
            raise BackendError("unsupported", "No OPENAI_API_KEY (set it in .env)")
        self.key, self.model = config.openai_api_key, config.openai_image_model or OPENAI_DEFAULT_MODEL
        self.base, self.timeout, self.opener = "https://api.openai.com/v1", config.gemini_timeout, opener

    def generate(self, text: str, images: list[Path], out_path: Path, size: tuple[int, int]) -> dict[str, Any]:
        boundary = "kitchen" + base64.b16encode(Path(images[0]).name.encode()[:8]).decode() if images else "kitchenboundary"
        body = multipart([("model", self.model), ("prompt", text), ("size", openai_size(*size)), ("n", "1")],
                         [("image[]", Path(p).name, Path(p).read_bytes(), "image/png") for p in images], boundary)
        req = urllib.request.Request(f"{self.base}/images/edits", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
        t0 = time.monotonic()
        try:
            with self.opener(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read()[:600].decode("utf-8", "replace")
            if e.code in (429, 503):
                raise BackendError("overloaded", f"OpenAI is busy or over quota ({e.code}): {msg}")
            raise BackendError("generation-failed", f"OpenAI answered {e.code}: {msg}")
        except TimeoutError:
            raise BackendError("timeout", f"OpenAI did not answer within {self.timeout:.0f} s")
        except (urllib.error.URLError, ConnectionError) as e:
            raise BackendError("overloaded", f"Cannot reach OpenAI: {getattr(e, 'reason', e)}")
        items = data.get("data") or []
        if items and items[0].get("b64_json"):
            out_path.write_bytes(base64.b64decode(items[0]["b64_json"]))
            usage = data.get("usage") or {}
            return {"model": self.model, "size": openai_size(*size), "seconds": round(time.monotonic() - t0, 1),
                    **({"tokens": usage.get("total_tokens")} if usage.get("total_tokens") else {})}
        raise BackendError("generation-failed", f"OpenAI returned no image: {json.dumps(data)[:300]}")
