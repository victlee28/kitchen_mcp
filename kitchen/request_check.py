"""Kiểm tra request gửi AI trước khi gửi (và kiểm tra một file request bất kỳ người dùng mang tới).

Lỗi hay gặp khi gửi tay qua Gemini web: dán nguyên JSON vào khung chat (bị cắt, base64 hỏng, AI không thấy ảnh),
thiếu ảnh mask, ảnh sai kích thước. Mọi kiểm tra trả {"ok", "errors": [...], "warning": [...], "image": [...]}.
"""
from __future__ import annotations

from typing import Any

import base64
import binascii
import io
import json

import numpy as np
from PIL import Image

from .words import say



def _decode(data_url: str) -> tuple[Image.Image | None, str | None]:
    if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
        return None, say("check.not-data-url")
    try:
        head, b64 = data_url.split(",", 1)
    except ValueError:
        return None, say("check.no-comma")
    if len(b64) % 4:
        return None, say("check.b64-cut", n=len(b64))
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as e:
        return None, say("check.b64-bad", error=e)
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        return im, None
    except Exception as e:  # noqa: BLE001
        return None, say("check.cannot-open", error=type(e).__name__)


def check_lean(lean: dict[str, Any]) -> dict[str, Any]:
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
        tag = say("check.image-tag", order=a.get('order'), role=a.get('role'))
        if err or im is None:
            errors.append(f"{tag}: {err or 'unreadable image'}")
            info.append({"order": a.get("order"), "role": a.get("role"), "ok": False})
            continue
        decoded[a.get("role")] = im
        info.append({"order": a.get("order"), "role": a.get("role"), "ok": True, "dimensions": list(im.size)})
        if size and im.size != size:
            errors.append(say("check.size", tag=tag, w=im.size[0], h=im.size[1], rw=size[0], rh=size[1]))
    if task:  # job sửa: cần ảnh gốc + mask
        if not any(r in decoded for r in ("base-image", "marked-base-image")):
            errors.append(say("check.no-base"))
        mk = decoded.get("mask") or decoded.get("color-mask")
        if mk is None:
            errors.append(say("check.no-mask"))
        else:
            arr = np.array(mk.convert("RGB"))
            on = arr.max(-1) > 127
            if not on.any():
                errors.append(say("check.empty-mask"))
            elif len(task) > 1:
                colors = {tuple(c) for c in arr[on].reshape(-1, 3)[:: max(1, int(on.sum()) // 20000)]}
                if len(colors) < len(task):
                    errors.append(say("check.mask-colours", colours=len(colors), tasks=len(task)))
        if lean.get("type") == "geometry_edit" and "new-geometry" not in decoded:
            errors.append(say("check.no-new-geometry"))
        if "marked-base-image" not in decoded and "base-image" in decoded:
            doors.append(say("check.unmarked"))
        txt = lean.get("instruction") or ""
        for v in task:
            if len(task) > 1 and f"Region {v.get('task')}" not in txt:
                errors.append(say("check.task-not-named", n=v.get('task')))
            if not v.get("position"):
                doors.append(say("check.no-position", n=v.get('task')))
    if not (lean.get("instruction") or "").strip():
        errors.append(say("check.no-instruction"))
    return {"ok": not errors, "errors": errors, "warning": doors, "image": info}


def check_text(text: str) -> dict:
    """Kiểm tra một file/chuỗi request người dùng dán hoặc nạp lên (phát hiện file bị cắt, base64 hỏng, thiếu ảnh)."""
    errors: list[str] = []
    doors: list[str] = []
    t = text or ""
    if " " in t:
        doors.append(say("check.nbsp"))
        t = t.replace(" ", " ")
    try:
        obj = json.loads(t)
    except json.JSONDecodeError as e:
        cut = e.pos >= len(t.rstrip()) - 1 or e.msg.startswith("Unterminated string")
        msg = (say("check.json-cut") if cut else say("check.json-bad", line=e.lineno, col=e.colno, msg=e.msg))
        return {"ok": False, "errors": [msg + say("check.length", n=len(text))], "warning": doors, "image": []}
    if not isinstance(obj, dict):
        return {"ok": False, "errors": [say("check.not-object")], "warning": doors, "image": []}
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
                    rep["errors"].append(say("check.image-n", n=n, error=err))
        if not any(p.get("text") for p in parts):
            rep["errors"].append(say("check.no-text"))
        if n == 0:
            rep["errors"].append(say("check.no-inline"))
        rep["ok"] = not rep["errors"]
    else:
        rep = {"ok": False, "errors": [say("check.unknown-file", schema=sch or '—')], "warning": [], "image": []}
    rep["warning"] = doors + rep["warning"]
    return rep
