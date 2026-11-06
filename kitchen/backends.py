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


def gemini_text(kind: str, prompt: str, instruction: str, style_prompt: str, role: str = "", realism: str = "") -> str:
    """Chỉ dẫn dạng câu cho Gemini (model hiểu ngôn ngữ tự nhiên tốt hơn danh sách tag)."""
    if kind == "gen0":
        return ("The image is a flat-shaded 3D render of a kitchen design with black construction lines. "
                "Turn it into a photorealistic interior photograph. Keep EXACTLY the same camera, perspective, framing, "
                "layout, cabinet sizes, door and drawer divisions, appliance positions, wall and floor edges. "
                "Do not add, remove, move or resize anything; do not crop. Replace flat colors with realistic materials "
                f"of the same hue. Scene: {style_prompt}. {realism} {instruction}".strip().replace("  ", " "))
    return ("Edit the FIRST image. The SECOND image is a mask: change only the region that is white in the mask "
            f"({role}). Make it: {prompt}. {instruction} "
            "Keep the exact shape, edges, panel gaps, perspective and lighting; leave every other pixel of the first "
            "image unchanged; return the full image at the same framing.").strip()


def gemini_text_edit(regions: list[dict], instruction: str = "", realism: str = "") -> str:
    """Chỉ dẫn sửa ảnh cho Gemini khi ảnh 1 đã ĐÁNH DẤU (viền màu + số quanh từng vùng) và ảnh 2 là mask.

    Mỗi region: color (RED…), n (số nhãn), role, mat, extra, where (vị trí bằng chữ), others (số vật cùng loại khác giữ nguyên).
    Ba lớp chỉ định vùng cùng lúc — viền trên ảnh, mask, vị trí bằng chữ — để model không đoán sai đối tượng."""
    multi = len(regions) > 1
    head = ("You are given two images. IMAGE 1 is the kitchen photo to edit; the area"
            + ("s to change are" if multi else " to change is")
            + " surrounded by a thin colored OUTLINE with a number label. IMAGE 2 is the "
            + ("color-coded mask: each colored area is exactly the region of the same-colored outline in image 1."
               if multi else "mask: the white area is exactly the region inside the outline in image 1."))
    lines = []
    for r in regions:
        what = f"the {r['role']}" + (f" in the {r['where']}" if r.get("where") else "")
        n, kind = r.get("others") or 0, r.get("kind") or r["role"]
        keep = ("" if not n else f" The other {kind} in the photo is NOT outlined — leave it unchanged." if n == 1
                else f" The {n} other {kind}s in the photo are NOT outlined — leave them unchanged.")
        lines.append(f"- Region {r['n']} ({r['color']} outline): {what}. Make it {r['material_text']}. {r.get('extra') or ''}".rstrip()
                     + keep)
    return (head + "\nChanges:\n" + "\n".join(lines) + "\n"
            + (f"{instruction}\n" if instruction else "")
            + (f"{realism}\n" if realism else "")
            + "Change ONLY the pixels inside the outlined region(s); everything outside them must stay identical to image 1. "
              "Keep the exact shape, edges, panel gaps, perspective and lighting of the edited parts. "
              "REMOVE the colored outlines and number labels in your result (draw what is really behind them). "
              "Return the full image at the same size and framing.")


_SHAPE_DIRECTION = {
    "remove-item": ("Where an object is removed, image 3 shows what is behind it (wall, floor, the side of the neighbouring cabinet, "
                "the countertop end, the plinth): paint those surfaces with the same materials, colors and lighting as the matching "
                "surfaces elsewhere in image 1, so nothing of the removed object remains."),
    "add-item": ("Paint the new object(s) shown in image 3 with realistic materials that match the existing cabinets of image 1 "
                 "(same finish, color and hardware style unless stated)."),
    "replace-item": ("Keep the materials, colors and finish that image 1 has in this region; change only the shape / style so it "
                 "matches image 3."),
}


def gemini_text_geometry(operation: str, changes: list[str], where: str | None, instruction: str = "", realism: str = "") -> str:
    """Sửa hình: ảnh 1 có viền, ảnh 2 mask, ảnh 3 hình mẫu thiết kế mới (màu phẳng + nét) cùng camera."""
    return ("You are given three images of the same kitchen from the same camera. IMAGE 1 is the photo to edit; the area to "
            "change is surrounded by a thin RED outline with the label 1. IMAGE 2 is the mask: white = exactly the region inside "
            "the outline. IMAGE 3 is a flat-colored technical drawing (black lines) of how the kitchen must look AFTER the change, "
            "same camera and framing: inside the outlined region, follow image 3 exactly for which objects exist and for their "
            "shapes, edges and positions.\n"
            "Changes:\n" + "\n".join(f"- {c}" for c in changes) + "\n"
            + (f"The region is in the {where}.\n" if where else "")
            + _SHAPE_DIRECTION.get(operation, _SHAPE_DIRECTION["replace-item"]) + "\n"
            + (f"{instruction}\n" if instruction else "")
            + (f"{realism}\n" if realism else "")
            + "Image 3 is only a shape guide: do NOT copy its flat colors or black lines — the result must look like the photograph "
              "in image 1, with consistent perspective, shadows and lighting. Everything outside the outline must stay identical "
              "to image 1. REMOVE the red outline and number label. Return the full image at the same size and framing.")


def gemini_text_multi(regions: list[tuple[str, str, str, str]], instruction: str = "") -> str:
    """Nhiều vùng trong một lần gọi: ảnh thứ hai tô mỗi vùng một màu. regions: (màu, vai trò, vật liệu, yêu cầu)."""
    lines = [f"- {color} region ({role}): make it {material_text}. {extra}".strip() for color, role, material_text, extra in regions]
    return ("Edit the FIRST image. The SECOND image is a color-coded mask; apply each change only inside its colored region:\n"
            + "\n".join(lines) + "\n"
            + (f"{instruction}\n" if instruction else "")
            + "Keep the exact shape, edges, panel gaps, perspective and lighting; leave all black (unmasked) areas of the first "
              "image unchanged; return the full image at the same framing.")

