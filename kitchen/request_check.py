"""Kiểm tra request gửi AI trước khi gửi (và kiểm tra một file request bất kỳ người dùng mang tới).

Lỗi hay gặp khi gửi tay qua Gemini web: dán nguyên JSON vào khung chat (bị cắt, base64 hỏng, AI không thấy ảnh),
thiếu ảnh mask, ảnh sai kích thước. Mọi kiểm tra trả {"ok", "loi": [...], "canhBao": [...], "anh": [...]}.
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
    loi: list[str] = []
    canh: list[str] = []
    info = []
    size = tuple(lean.get("kichThuoc") or ())
    imgs = lean.get("anhDinhKem") or []
    viec = lean.get("viec") or []
    decoded = {}
    for a in imgs:
        im, err = _decode(a.get("dataUrl", ""))
        tag = f"Ảnh {a.get('thuTu')} ({a.get('vaiTro')})"
        if err:
            loi.append(f"{tag}: {err}")
            info.append({"thuTu": a.get("thuTu"), "vaiTro": a.get("vaiTro"), "ok": False})
            continue
        decoded[a.get("vaiTro")] = im
        info.append({"thuTu": a.get("thuTu"), "vaiTro": a.get("vaiTro"), "ok": True, "kichThuoc": list(im.size)})
        if size and im.size != size:
            loi.append(f"{tag}: kích thước {im.size[0]}×{im.size[1]} khác request {size[0]}×{size[1]}")
    if viec:  # job sửa: cần ảnh gốc + mask
        if not any(r in decoded for r in ("anh-goc", "anh-goc-danh-dau")):
            loi.append("Thiếu ảnh gốc cần sửa")
        mk = decoded.get("mask") or decoded.get("mask-mau")
        if mk is None:
            loi.append("Thiếu ảnh mask — AI sẽ không biết sửa vùng nào")
        else:
            arr = np.array(mk.convert("RGB"))
            on = arr.max(-1) > 127
            if not on.any():
                loi.append("Mask trống (không có vùng nào cần sửa)")
            elif len(viec) > 1:
                colors = {tuple(c) for c in arr[on].reshape(-1, 3)[:: max(1, int(on.sum()) // 20000)]}
                if len(colors) < len(viec):
                    loi.append(f"Mask màu chỉ có {len(colors)} màu cho {len(viec)} việc")
        if lean.get("loai") == "hinh" and "hinh-moi" not in decoded:
            loi.append("Thiếu ảnh hình mẫu thiết kế mới (sửa hình cần 3 ảnh)")
        if "anh-goc-danh-dau" not in decoded and "anh-goc" in decoded:
            canh.append("Ảnh gốc chưa đánh dấu viền vùng sửa — AI dễ nhận nhầm đối tượng")
        txt = lean.get("chiDan") or ""
        for v in viec:
            if len(viec) > 1 and f"Region {v.get('viec')}" not in txt:
                loi.append(f"Chỉ dẫn không nhắc việc {v.get('viec')}")
            if not v.get("viTri"):
                canh.append(f"Việc {v.get('viec')}: chưa có mô tả vị trí")
    if not (lean.get("chiDan") or "").strip():
        loi.append("Thiếu chỉ dẫn (chiDan)")
    return {"ok": not loi, "loi": loi, "canhBao": canh, "anh": info}


def check_text(text: str) -> dict:
    """Kiểm tra một file/chuỗi request người dùng dán hoặc nạp lên (phát hiện file bị cắt, base64 hỏng, thiếu ảnh)."""
    loi: list[str] = []
    canh: list[str] = []
    t = text or ""
    if " " in t:
        canh.append("Có ký tự khoảng trắng đặc biệt (NBSP) — dấu hiệu file được chép qua khung chat/trình soạn thảo")
        t = t.replace(" ", " ")
    try:
        obj = json.loads(t)
    except json.JSONDecodeError as e:
        cut = e.pos >= len(t.rstrip()) - 1 or e.msg.startswith("Unterminated string")
        msg = ("File bị CẮT giữa chừng (JSON kết thúc đột ngột)" if cut else f"JSON hỏng ở dòng {e.lineno}, cột {e.colno}: {e.msg}")
        return {"ok": False, "loi": [msg + f" — dài {len(text)} ký tự."], "canhBao": canh, "anh": []}
    if not isinstance(obj, dict):
        return {"ok": False, "loi": ["Không phải object JSON"], "canhBao": canh, "anh": []}
    sch = str(obj.get("schema", ""))
    if sch.startswith("kitchen-ai-edit-request/"):
        rep = check_lean(obj)
    elif "contents" in obj:  # thân Gemini API
        rep = {"ok": True, "loi": [], "canhBao": [], "anh": []}
        parts = [p for c in obj.get("contents", []) for p in c.get("parts", [])]
        n = 0
        for p in parts:
            d = p.get("inline_data") or p.get("inlineData")
            if d:
                n += 1
                im, err = _decode(f"data:{d.get('mime_type') or d.get('mimeType')};base64,{d.get('data', '')}")
                rep["anh"].append({"thuTu": n, "ok": not err, **({"kichThuoc": list(im.size)} if im else {})})
                if err:
                    rep["loi"].append(f"Ảnh {n}: {err}")
        if not any(p.get("text") for p in parts):
            rep["loi"].append("Thiếu phần chỉ dẫn (text)")
        if n == 0:
            rep["loi"].append("Không có ảnh inline_data")
        rep["ok"] = not rep["loi"]
    else:
        rep = {"ok": False, "loi": [f"Không nhận ra loại file (schema '{sch or '—'}')"], "canhBao": [], "anh": []}
    rep["canhBao"] = canh + rep["canhBao"]
    return rep
