"""Image-generation adapters. The image-job orchestrator does not depend on a specific model API.

- `recolor`: change the target region's color while preserving shading, without an AI model.
- `job-package`: export prompts and images for a person or external chat model; import the result with `submit_image_result`.
- `gemini`: call the Gemini image API. Credentials and model settings use `GEMINI_API_KEY`, `GEMINI_IMAGE_MODEL`,
  or a separate environment file via `GEMINI_ENV_FILE`.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from pathlib import Path

from .config import Config

class BackendError(ValueError):
    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code  # thieu-anh | khong-ho-tro | qua-tai | het-gio | sinh-that-bai


BACKENDS = {
    "recolor": {"name": "Đổi màu giữ sáng tối (không AI)", "kind": ["edit", "geometry_edit"], "async": False,
               "supported": ["mask"], "needsConfig": []},
    "job-package": {"name": "Xuất gói job, nộp ảnh kết quả sau", "kind": ["edit", "gen0", "geometry_edit"], "async": False,
                "supported": ["reference-image", "mask-illustration"], "needsConfig": []},
    "gemini": {"name": "Gemini API (ảnh + chỉ dẫn)", "kind": ["edit", "gen0", "geometry_edit"], "async": True,
               "supported": ["reference-image", "mask-illustration"], "needsConfig": ["GEMINI_API_KEY | GEMINI_ENV_FILE", "GEMINI_IMAGE_MODEL"]},
}


# ------------------------------------------------------------------ Gemini
_RATIO = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]


def _read_env_file(path: str) -> dict:
    out = {}
    p = Path(path).expanduser()
    if not p.is_file():
        raise BackendError("unsupported", f"GEMINI_ENV_FILE trỏ tới file không tồn tại: {p}")
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
        raise BackendError("unsupported", "Chưa có GEMINI_API_KEY (đặt trong .env hoặc trỏ GEMINI_ENV_FILE tới .env của mcp-image)")
    return {"key": key, "model": config.gemini_model or f.get("GEMINI_IMAGE_MODEL") or "gemini-3-pro-image",
            "base": config.gemini_base_url, "timeout": config.gemini_timeout, "imageSize": config.gemini_image_size}


def ratio(w: int, h: int) -> str:
    r = w / h
    return min(_RATIO, key=lambda t: abs(int(t.split(":")[0]) / int(t.split(":")[1]) - r))


def gemini_body(text: str, images: list[Path], size: tuple[int, int], image_size: str = "") -> dict:
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

    def generate(self, text: str, images: list[Path], out_path: Path, size: tuple[int, int]) -> dict:
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
                raise BackendError("overloaded", f"Gemini bận/hết hạn mức ({e.code}): {msg}")
            raise BackendError("generation-failed", f"Gemini trả {e.code}: {msg}")
        except TimeoutError:
            raise BackendError("timeout", f"Gemini quá {self.cfg['timeout']:.0f}s chưa trả")
        except (urllib.error.URLError, ConnectionError) as e:
            raise BackendError("overloaded", f"Không kết nối được Gemini: {getattr(e, 'reason', e)}")
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
        raise BackendError("generation-failed", f"Gemini không trả ảnh (lý do: {reason or 'không rõ'}) {text_out}".strip())
