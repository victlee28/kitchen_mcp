"""Kiểm tra request gửi AI trước khi gửi (và kiểm tra một file request bất kỳ người dùng mang tới).

Lỗi hay gặp khi gửi tay qua Gemini web: dán nguyên JSON vào khung chat (bị cắt, base64 hỏng, AI không thấy ảnh),
thiếu ảnh mask, ảnh sai kích thước. Mọi kiểm tra trả {"ok", "errors": [...], "warning": [...], "image": [...]}.
"""
from __future__ import annotations

import base64
import binascii
import io
import json

import numpy as np
from PIL import Image

MIN_PIXELS = 400  # vùng nhỏ hơn: model dễ bỏ sót


def _decode(data_url: str) -> tuple[Image.Image | None, str | None]:
    if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
        return None, "không phải data:image/…"
    try:
        head, b64 = data_url.split(",", 1)
    except ValueError:
        return None, "thiếu dấu ',' sau phần đầu data URL"
    if len(b64) % 4:
        return None, f"chuỗi base64 bị cắt ({len(b64)} ký tự, không chia hết cho 4)"
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as e:
        return None, f"base64 hỏng ({e})"
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        return im, None
    except Exception as e:  # noqa: BLE001
        return None, f"không mở được ảnh ({type(e).__name__}) — có thể file bị cắt"


def check_lean(lean: dict) -> dict:
    """Kiểm tra request.json bản gọn (kitchen-ai-edit-request/2.x) — dùng ngay khi xuất và khi người dùng nạp file."""
    errors: list[str] = []
    doors: list[str] = []
    info = []
    size = tuple(lean.get("dimensions") or ())
    imgs = lean.get("attachedImages") or []
    task = lean.get("task") or []
    decoded = {}
    for a in imgs:
        im, err = _decode(a.get("dataUrl", ""))
        tag = f"Ảnh {a.get('order')} ({a.get('role')})"
        if err:
            errors.append(f"{tag}: {err}")
            info.append({"order": a.get("order"), "role": a.get("role"), "ok": False})
            continue
        decoded[a.get("role")] = im
        info.append({"order": a.get("order"), "role": a.get("role"), "ok": True, "dimensions": list(im.size)})
        if size and im.size != size:
            errors.append(f"{tag}: kích thước {im.size[0]}×{im.size[1]} khác request {size[0]}×{size[1]}")
    if task:  # job sửa: cần ảnh gốc + mask
        if not any(r in decoded for r in ("base-image", "marked-base-image")):
            errors.append("Thiếu ảnh gốc cần sửa")
        mk = decoded.get("mask") or decoded.get("color-mask")
        if mk is None:
            errors.append("Thiếu ảnh mask — AI sẽ không biết sửa vùng nào")
        else:
            arr = np.array(mk.convert("RGB"))
            on = arr.max(-1) > 127
            if not on.any():
                errors.append("Mask trống (không có vùng nào cần sửa)")
            elif len(task) > 1:
                colors = {tuple(c) for c in arr[on].reshape(-1, 3)[:: max(1, int(on.sum()) // 20000)]}
                if len(colors) < len(task):
                    errors.append(f"Mask màu chỉ có {len(colors)} màu cho {len(task)} việc")
        if lean.get("type") == "geometry_edit" and "new-geometry" not in decoded:
            errors.append("Thiếu ảnh hình mẫu thiết kế mới (sửa hình cần 3 ảnh)")
        if "marked-base-image" not in decoded and "base-image" in decoded:
            doors.append("Ảnh gốc chưa đánh dấu viền vùng sửa — AI dễ nhận nhầm đối tượng")
        txt = lean.get("instruction") or ""
        for v in task:
            if len(task) > 1 and f"Region {v.get('task')}" not in txt:
                errors.append(f"Chỉ dẫn không nhắc việc {v.get('task')}")
            if not v.get("position"):
                doors.append(f"Việc {v.get('task')}: chưa có mô tả vị trí")
    if not (lean.get("instruction") or "").strip():
        errors.append("Thiếu chỉ dẫn (chiDan)")
    return {"ok": not errors, "errors": errors, "warning": doors, "image": info}


def check_text(text: str) -> dict:
    """Kiểm tra một file/chuỗi request người dùng dán hoặc nạp lên (phát hiện file bị cắt, base64 hỏng, thiếu ảnh)."""
    errors: list[str] = []
    doors: list[str] = []
    t = text or ""
    if " " in t:
        doors.append("Có ký tự khoảng trắng đặc biệt (NBSP) — dấu hiệu file được chép qua khung chat/trình soạn thảo")
        t = t.replace(" ", " ")
    try:
        obj = json.loads(t)
    except json.JSONDecodeError as e:
        cut = e.pos >= len(t.rstrip()) - 1 or e.msg.startswith("Unterminated string")
        msg = ("File bị CẮT giữa chừng (JSON kết thúc đột ngột)" if cut else f"JSON hỏng ở dòng {e.lineno}, cột {e.colno}: {e.msg}")
        return {"ok": False, "errors": [msg + f" — dài {len(text)} ký tự."], "warning": doors, "image": []}
    if not isinstance(obj, dict):
        return {"ok": False, "errors": ["Không phải object JSON"], "warning": doors, "image": []}
    sch = str(obj.get("schema", ""))
    if sch.startswith("kitchen-ai-edit-request/"):
        rep = check_lean(obj)
    elif "contents" in obj:  # thân Gemini API
        rep = {"ok": True, "errors": [], "warning": [], "image": []}
        parts = [p for c in obj.get("contents", []) for p in c.get("parts", [])]
        n = 0
        for p in parts:
            d = p.get("inline_data") or p.get("inlineData")
            if d:
                n += 1
                im, err = _decode(f"data:{d.get('mime_type') or d.get('mimeType')};base64,{d.get('data', '')}")
                rep["image"].append({"order": n, "ok": not err, **({"dimensions": list(im.size)} if im else {})})
                if err:
                    rep["errors"].append(f"Ảnh {n}: {err}")
        if not any(p.get("text") for p in parts):
            rep["errors"].append("Thiếu phần chỉ dẫn (text)")
        if n == 0:
            rep["errors"].append("Không có ảnh inline_data")
        rep["ok"] = not rep["errors"]
    else:
        rep = {"ok": False, "errors": [f"Không nhận ra loại file (schema '{sch or '—'}')"], "warning": [], "image": []}
    rep["warning"] = doors + rep["warning"]
    return rep
