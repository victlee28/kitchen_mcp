"""Adapter backend sinh ảnh. Orchestrator (kitchen.images) không phụ thuộc cách gọi model cụ thể.

- `to-mau`  : đổi màu vùng đích giữ sáng tối (không AI, chạy ngay) — kiểm chứng mask/ghép ảnh, xem nhanh màu.
- `job-package` : xuất gói job (ảnh gốc, mask, nét, depth, prompt, workflow ComfyUI dạng API) để chạy ở nơi khác,
              rồi nộp ảnh kết quả về bằng `submit_image_result`.
- `comfyui` : gọi ComfyUI HTTP (/upload/image, /prompt, /history, /view). Cấu hình qua biến môi trường:
              COMFYUI_URL (mặc định http://127.0.0.1:8188), COMFYUI_CKPT, COMFYUI_CN_LINEART, COMFYUI_CN_DEPTH,
              COMFYUI_TIMEOUT (giây, mặc định 600).
- `gemini`  : gọi thẳng Gemini API (generateContent, trả ảnh). Khóa và model lấy từ biến môi trường
              GEMINI_API_KEY / GEMINI_IMAGE_MODEL, hoặc đọc từ file .env khác qua GEMINI_ENV_FILE
              (vd .env của dự án mcp-image) để không phải chép khóa. GEMINI_BASE_URL, GEMINI_TIMEOUT (mặc định 300).
              Gemini không nhận mask như inpaint: ảnh gốc + ảnh mask được gửi kèm chỉ dẫn, còn việc giữ nguyên
              vùng ngoài mask do bước ghép strict bảo đảm.
"""
from __future__ import annotations

import base64
import copy
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from pathlib import Path

from . import legacy
from .config import Config

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / "workflows"


class BackendError(ValueError):
    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code  # thieu-anh | khong-ho-tro | qua-tai | het-gio | sinh-that-bai


BACKENDS = {
    "recolor": {"name": "Đổi màu giữ sáng tối (không AI)", "kind": ["edit", "geometry_edit"], "async": False,
               "supported": ["mask"], "needsConfig": []},
    "job-package": {"name": "Xuất gói job, nộp ảnh kết quả sau", "kind": ["edit", "gen0", "geometry_edit"], "async": False,
                "supported": ["mask", "lineart", "depth"], "needsConfig": []},
    "comfyui": {"name": "ComfyUI qua HTTP", "kind": ["edit", "gen0", "geometry_edit"], "async": True,
                "supported": ["mask", "lineart", "depth"], "needsConfig": ["COMFYUI_URL", "COMFYUI_CKPT"]},
    "gemini": {"name": "Gemini API (ảnh + chỉ dẫn)", "kind": ["edit", "gen0", "geometry_edit"], "async": True,
               "supported": ["reference-image", "mask-illustration"], "needsConfig": ["GEMINI_API_KEY | GEMINI_ENV_FILE", "GEMINI_IMAGE_MODEL"]},
}


def _read_workflow(path) -> dict:
    """Read a workflow file; the ``kitchen`` metadata block of old files (Vietnamese keys) is converted on the fly."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data.get("kitchen"), dict):
        data["kitchen"] = legacy.convert(data["kitchen"])
    return data


def workflow_names() -> dict:
    out = {}
    for p in sorted(WORKFLOWS.glob("*.json")):
        out[p.stem] = _read_workflow(p).get("kitchen", {})
    return out


def load_workflow(name: str) -> dict:
    p = WORKFLOWS / f"{name}.json"
    if not p.is_file() or p.parent.resolve() != WORKFLOWS.resolve():
        raise BackendError("unsupported", f"Không có workflow '{name}'. Có: {', '.join(workflow_names())}")
    return _read_workflow(p)


def fill(template, values: dict):
    """Thay chuỗi '{{khoa}}' bằng giá trị (giữ kiểu: seed là số)."""
    if isinstance(template, dict):
        return {k: fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [fill(v, values) for v in template]
    if isinstance(template, str) and template.startswith("{{") and template.endswith("}}"):
        key = template[2:-2]
        if key not in values:
            raise BackendError("unsupported", f"Workflow cần '{key}' nhưng job không có")
        return values[key]
    return template


def model_defaults(config: Config) -> dict:
    return {"ckpt": config.comfyui_ckpt, "controlnet_lineart": config.comfyui_cn_lineart, "controlnet_depth": config.comfyui_cn_depth}


# ------------------------------------------------------------------ ComfyUI
class ComfyUI:
    def __init__(self, config: Config, url: str | None = None, timeout: float | None = None, poll: float = 1.0):
        self.url = (url or config.comfyui_url).rstrip("/")
        self.timeout = float(timeout or config.comfyui_timeout)
        self.poll = poll

    def _req(self, path: str, data: bytes | None = None, headers: dict | None = None, t: float = 30):
        req = urllib.request.Request(self.url + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=t) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            body = e.read()[:500].decode("utf-8", "replace")
            if e.code in (429, 503):
                raise BackendError("overloaded", f"ComfyUI bận ({e.code})")
            raise BackendError("generation-failed", f"ComfyUI trả {e.code}: {body}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise BackendError("overloaded", f"Không kết nối được ComfyUI tại {self.url}: {e}")

    def upload(self, path: Path, name: str) -> str:
        boundary = uuid.uuid4().hex
        body = b"".join([
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n".encode(), Path(path).read_bytes(), f"\r\n--{boundary}--\r\n".encode()])
        r = json.loads(self._req("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}))
        return (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]

    def run(self, prompt: dict, out_path: Path) -> dict:
        r = json.loads(self._req("/prompt", json.dumps({"prompt": prompt, "client_id": "kitchen-design"}).encode(),
                                 {"Content-Type": "application/json"}))
        if r.get("node_errors"):
            raise BackendError("generation-failed", f"Workflow lỗi node: {json.dumps(r['node_errors'], ensure_ascii=False)[:400]}")
        pid = r["prompt_id"]
        t0 = time.monotonic()
        while True:
            h = json.loads(self._req(f"/history/{pid}")).get(pid)
            if h:
                st = h.get("status", {})
                if st.get("status_str") == "error":
                    raise BackendError("generation-failed", f"ComfyUI báo lỗi: {json.dumps(st.get('messages', []), ensure_ascii=False)[:400]}")
                imgs = [im for o in h.get("outputs", {}).values() for im in o.get("images", []) if im.get("type") == "output"]
                if imgs:
                    im = imgs[0]
                    q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": "output"})
                    out_path.write_bytes(self._req(f"/view?{q}", t=120))
                    return {"promptId": pid, "file": im["filename"], "giay": round(time.monotonic() - t0, 1)}
                if st.get("completed"):
                    raise BackendError("generation-failed", "ComfyUI chạy xong nhưng không có ảnh output (thiếu node SaveImage?)")
            if time.monotonic() - t0 > self.timeout:
                raise BackendError("timeout", f"Quá {self.timeout:.0f}s chưa có kết quả (prompt {pid})")
            time.sleep(self.poll)


def build_prompt(workflow: dict, images: dict[str, str], values: dict, models: dict) -> dict:
    """workflow = {"kitchen": {...}, "prompt": {...}}; images: khóa ảnh -> tên file đã upload."""
    return fill(copy.deepcopy(workflow["prompt"]), {**models, **values, **images})


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
