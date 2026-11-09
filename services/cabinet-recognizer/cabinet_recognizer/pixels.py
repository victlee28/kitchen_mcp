"""Vùng điểm ảnh (numpy/PIL): tìm đường ứng viên và vẽ ảnh đánh số cho AI.

Đầu ra là dữ liệu JSON được (dict/list/int/float). Kết quả so theo dung sai,
không đòi trùng từng bit khi port sang ngôn ngữ khác.
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

MARGIN = 0.03          # nới vùng tìm quanh hộp AI đưa ra (tỉ lệ kích thước ảnh)
REL_THRESHOLD = 0.15   # đỉnh phải >= 15% đỉnh mạnh nhất
ABS_THRESHOLD = 6.0    # và >= 6 mức xám trung bình mỗi dòng/cột
NMS_WINDOW = 3
MAX_LINES = 30


def load_gray(image: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(image)).convert("L")).astype(np.float64)


def _peaks(profile: np.ndarray, offset: int, rel: float = REL_THRESHOLD,
           absolute: float = ABS_THRESHOLD) -> list[tuple[int, float]]:
    if profile.size == 0:
        return []
    top = float(profile.max())
    thr = max(absolute, rel * top)
    out: list[tuple[int, float]] = []
    for i, v in enumerate(profile):
        lo, hi = max(0, i - NMS_WINDOW), i + NMS_WINDOW + 1
        if v >= thr and v >= profile[lo:hi].max():
            if not out or i + offset - out[-1][0] > 1:
                out.append((i + offset, float(v)))
    out.sort(key=lambda p: -p[1])
    return sorted(out[:MAX_LINES])


def _box_px(box: dict[str, float], w: int, h: int) -> tuple[int, int, int, int]:
    mx, my = int(MARGIN * w), int(MARGIN * h)
    return (max(0, int(box["left"] * w) - mx), min(w - 1, int(box["right"] * w) + mx),
            max(0, int(box["top"] * h) - my), min(h - 1, int(box["bottom"] * h) + my))


def _vertical(gray: np.ndarray, box: dict[str, float], rows: tuple[float, float]) -> list[tuple[int, float]]:
    h, w = gray.shape
    x0, x1, _, _ = _box_px(box, w, h)
    y0 = int((box["top"] + rows[0] * (box["bottom"] - box["top"])) * h)
    y1 = int((box["top"] + rows[1] * (box["bottom"] - box["top"])) * h)
    gx = np.abs(np.diff(gray[y0:y1, x0:x1 + 1], axis=1))
    return _peaks(gx.mean(axis=0), x0)


def _horizontal(gray: np.ndarray, box: dict[str, float]) -> list[tuple[int, float]]:
    h, w = gray.shape
    _, _, y0, y1 = _box_px(box, w, h)
    xl = int((box["left"] + 0.05 * (box["right"] - box["left"])) * w)
    xr = int((box["right"] - 0.05 * (box["right"] - box["left"])) * w)
    gy = np.abs(np.diff(gray[y0:y1 + 1, xl:xr], axis=0))
    return _peaks(gy.mean(axis=1), y0)


END_TOLERANCE = 0.012      # an edge detected within this fraction of the width of a run end is that end


def _with_ends(found: list[tuple[int, float]], box: dict[str, float], width: int) -> list[tuple[int, float]]:
    """The run's own left and right ends as extra candidates (strength 0, numbered after the detected lines) when no edge was detected there:
    a white door against a white wall has no edge, yet the run still starts there and a module boundary must be able to name it."""
    tol = END_TOLERANCE * width
    extra = [(x, 0.0) for x in (int(box["left"] * width), int(box["right"] * width)) if all(abs(p - x) > tol for p, _ in found)]
    return found + extra


def measure(image: bytes, layout: dict[str, Any]) -> dict[str, Any]:
    """Tìm đường ứng viên trong hai dải tủ. Tủ trên đo ở 20-65% chiều cao dải
    (tránh máy hút mùi ở đáy), tủ dưới ở 25-85% (vùng cánh, tránh mặt đá và chân)."""
    gray = load_gray(image)
    h, w = gray.shape
    up = _with_ends(_vertical(gray, layout["upper"], (0.20, 0.65)), layout["upper"], w)
    base = _with_ends(_vertical(gray, layout["base"], (0.25, 0.85)), layout["base"], w)
    rows = sorted(_horizontal(gray, layout["upper"]) + _horizontal(gray, layout["base"]))
    merged: list[tuple[int, float]] = []
    for y, s in rows:
        if merged and y - merged[-1][0] <= 1:
            if s > merged[-1][1]:
                merged[-1] = (y, s)
        else:
            merged.append((y, s))

    def lines(prefix: str, pts: list[tuple[int, float]]) -> list[dict[str, Any]]:
        return [{"id": f"{prefix}{i + 1}", "pos": p, "strength": round(s, 1)} for i, (p, s) in enumerate(pts)]

    return {
        "imageSize": [w, h],
        "bandsPx": {k: list(_box_px(layout[k], w, h)) for k in ("upper", "base")},
        "vlines": {"upper": lines("U", up), "base": lines("B", base)},
        "hlines": lines("H", merged),
    }


def refine_cells(image: bytes, meas: dict[str, Any], seg: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Tìm đường ngang bên trong từng ô theo phán đoán của AI:
    tủ có máy hút mùi -> 1 đường đáy cánh; tủ n ngăn kéo -> n-1 đường chia."""
    gray = load_gray(image)
    hpos = {ln["id"]: ln["pos"] for ln in meas["hlines"]}
    out: dict[str, list[dict[str, Any]]] = {}
    for band in ("upper", "base"):
        vpos = {ln["id"]: ln["pos"] for ln in meas["vlines"][band]}
        xs = [vpos[b] for b in seg[band]["boundaries"]]
        if band == "upper":
            y0, y1 = hpos[seg["rows"].get("upperSplit", seg["rows"]["upperTop"])], hpos[seg["rows"]["upperBottom"]]   # under the loft row
        else:
            y0, y1 = hpos[seg["rows"]["frontsTop"]], hpos[seg["rows"]["plinthTop"]]
        cells: list[dict[str, Any]] = []
        for i, mod in enumerate(seg[band]["modules"]):
            want = 1 if mod.get("applianceBelow") == "hood" else max(0, int(mod.get("drawers", 0)) - 1)
            found: list[int] = []
            if want:
                xa, xb = xs[i] + 3, xs[i + 1] - 3
                lo = y0 + int(0.15 * (y1 - y0))
                hi = y1 - int(0.08 * (y1 - y0))
                prof = np.abs(np.diff(gray[lo:hi, xa:xb], axis=0)).mean(axis=1)
                cand = sorted(_peaks(prof, lo), key=lambda p: -p[1])[:want]
                found = sorted(p for p, _ in cand)
            cells.append({"innerRows": found})
        out[band] = cells
    return out


def annotate(image: bytes, meas: dict[str, Any], target_width: int = 1400) -> bytes:
    """Ảnh phóng to có đường ứng viên đánh số (U* đỏ, B* xanh dương, H* xanh lá)."""
    img = Image.open(io.BytesIO(image)).convert("RGB")
    w, h = img.size
    k = max(1.0, target_width / w)
    pad = 70
    big = img.resize((int(w * k), int(h * k)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (big.width + pad, big.height + 2 * pad), "white")
    canvas.paste(big, (pad, pad))
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=max(12, int(9 * k / 2)))
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()

    def X(x: float) -> float:
        return pad + x * k

    def Y(y: float) -> float:
        return pad + y * k

    def label(x: float, y: float, text: str, color: tuple[int, int, int]) -> None:
        box = d.textbbox((x, y), text, font=font)
        d.rectangle((box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 1), fill="white", outline=color)
        d.text((x, y), text, fill=color, font=font)

    for band, color in (("upper", (220, 30, 30)), ("base", (30, 80, 220))):
        x0, x1, y0, y1 = meas["bandsPx"][band]
        for n, ln in enumerate(meas["vlines"][band]):
            x = X(ln["pos"] + 0.5)
            d.line([(x, Y(y0)), (x, Y(y1))], fill=color, width=2)
            if band == "upper":
                ty = Y(y0) - 20 - 18 * (n % 2)
            else:
                ty = Y(y1) + 4 + 18 * (n % 2)
            label(x - 8, ty, ln["id"], color)
    xmin = min(meas["bandsPx"]["upper"][0], meas["bandsPx"]["base"][0])
    xmax = max(meas["bandsPx"]["upper"][1], meas["bandsPx"]["base"][1])
    for n, ln in enumerate(meas["hlines"]):
        y = Y(ln["pos"] + 0.5)
        d.line([(X(xmin), y), (X(xmax), y)], fill=(20, 160, 60), width=1)
        label(4 + 30 * (n % 2), y - 7, ln["id"], (20, 140, 50))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()
