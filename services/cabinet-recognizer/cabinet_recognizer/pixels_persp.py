"""Vùng điểm ảnh cho nhánh phối cảnh: dò đường xiên, đường ứng viên theo dải xiên, ảnh đánh số từng dãy."""
from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .compute_persp import band_lines
from .errors import RecognizerError
from .pixels import load_gray, _peaks

PREFIX = {"back": "B", "left": "L", "right": "R"}
STOREY_LETTER = {"base": "D", "upper": "U", "upper-top": "T"}
BAND_ROWS = {"base": (0.20, 0.85), "upper": (0.15, 0.75), "upper-top": (0.20, 0.80)}


def trace_line(gray: np.ndarray, p: tuple[float, float], q: tuple[float, float]) -> list[float]:
    """Bám mép mạnh nhất quanh đoạn gợi ý (pixel), khớp v = m u + c có loại ngoại lệ.
    Trả [m, c, sai_số_trung_vị_px, số_điểm, x_đầu, x_cuối]."""
    h, w = gray.shape
    gy = np.zeros_like(gray)
    gy[1:-1] = (gray[2:] - gray[:-2]) / 2
    win = max(6, int(0.012 * h))
    x0, x1 = int(max(2, p[0])), int(min(w - 3, q[0]))
    step = max(2, (x1 - x0) // 80)
    pts = []
    for x in range(x0, x1, step):
        yp = p[1] + (q[1] - p[1]) * (x - p[0]) / (q[0] - p[0])
        lo, hi = int(max(1, yp - win)), int(min(h - 2, yp + win)) + 1
        if hi - lo < 3:
            continue
        col = np.abs(gy[lo:hi, max(0, x - 1):x + 2].mean(axis=1))
        i = int(col.argmax())
        pts.append((x, lo + i, float(col[i])))
    if len(pts) < 6:
        raise RecognizerError("validation", "line-not-found", f"không bám được đường quanh {p}-{q}")
    P = np.array(pts)
    for _ in range(4):
        m, c = np.polyfit(P[:, 0], P[:, 1], 1)
        r = np.abs(P[:, 1] - (m * P[:, 0] + c))
        keep = r <= max(1.5, 2.5 * float(np.median(r)))
        if keep.sum() < 6:
            break
        P = P[keep]
    m, c = np.polyfit(P[:, 0], P[:, 1], 1)
    res = float(np.median(np.abs(P[:, 1] - (m * P[:, 0] + c))))
    return [float(m), float(c), round(res, 2), int(len(P)), int(P[:, 0].min()), int(P[:, 0].max())]


def _y(line: list[float], x: float) -> float:
    return line[0] * x + line[1]


def _band_candidates(gray: np.ndarray, top: list[float], bot: list[float], x0: int, x1: int,
                     rows: tuple[float, float]) -> list[tuple[int, float]]:
    gx = np.abs(np.diff(gray, axis=1))
    h = gray.shape[0]
    prof = np.zeros(max(0, x1 - x0))
    for i, x in enumerate(range(x0, x1)):
        yt, yb = _y(top, x), _y(bot, x)
        a, b = int(yt + rows[0] * (yb - yt)), int(yt + rows[1] * (yb - yt))
        a, b = max(0, a), min(h - 1, b)
        if b > a:
            prof[i] = gx[a:b, x].mean()
    return _peaks(prof, x0, rel=0.06, absolute=3.0)


def measure_runs(image: bytes, scene: dict[str, Any]) -> dict[str, Any]:
    gray = load_gray(image)
    h, w = gray.shape
    runs: dict[str, Any] = {}
    for run in scene["runs"]:
        wall = run["wall"]
        lines = {}
        for key, (a, b) in run["lines"].items():
            lines[key] = trace_line(gray, (a[0] * w, a[1] * h), (b[0] * w, b[1] * h))
        box = run["box"]
        x0, x1 = int(box["left"] * w), int(box["right"] * w)
        cand: dict[str, list[dict[str, Any]]] = {}
        for storey in ("base", "upper", "upper-top"):
            keys = band_lines(lines, storey)
            if keys is None or (storey == "upper-top" and "upperSplit" not in lines):
                continue
            pts = _band_candidates(gray, lines[keys[0]], lines[keys[1]], max(1, x0 - 6), min(w - 2, x1 + 6),
                                   BAND_ROWS[storey])
            pre = PREFIX[wall] + STOREY_LETTER[storey]
            cand[storey] = [{"id": f"{pre}{i + 1}", "pos": p, "strength": round(s, 1)} for i, (p, s) in enumerate(pts)]
        runs[wall] = {"lines": lines, "xRange": [x0, x1], "cand": cand}
    return {"imageSize": [w, h], "runs": runs}


def snap_height_refs(image: bytes, scene_runs: list[dict[str, Any]], refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Đưa điểm trên/dưới của vật chuẩn chiều cao về mép ngang mạnh nhất gần đó (±1.2% chiều cao ảnh)."""
    gray = load_gray(image)
    h, w = gray.shape
    gy = np.abs(np.diff(gray, axis=0))
    win = max(5, int(0.012 * h))
    out = []
    for r in refs:
        pts = []
        for key in ("top", "bottom"):
            u, v = r[key][0] * w, r[key][1] * h
            x = int(min(w - 3, max(2, u)))
            lo, hi = int(max(0, v - win)), int(min(h - 2, v + win))
            col = gy[lo:hi, x - 2:x + 3].mean(axis=1)
            pts.append((u, float(lo + int(col.argmax()) + 0.5)))
        out.append({"wall": r["wall"], "plane": r["plane"], "mm": r["mm"], "top": pts[0], "bottom": pts[1],
                    "what": r.get("what", "")})
    return out


def annotate_run(image: bytes, meas: dict[str, Any], wall: str, box: dict[str, float], target: int = 1500) -> bytes:
    img = Image.open(io.BytesIO(image)).convert("RGB")
    W, H = img.size
    m = 0.04
    cx0, cx1 = int(max(0, (box["left"] - m) * W)), int(min(W, (box["right"] + m) * W))
    cy0, cy1 = int(max(0, (box["top"] - m) * H)), int(min(H, (box["bottom"] + m) * H))
    crop = img.crop((cx0, cy0, cx1, cy1))
    k = max(1.0, min(4.0, target / crop.width))
    pad = 80
    big = crop.resize((int(crop.width * k), int(crop.height * k)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (big.width + pad, big.height + 2 * pad), "white")
    canvas.paste(big, (pad, pad))
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=15)
    except TypeError:
        font = ImageFont.load_default()

    def X(x: float) -> float:
        return pad + (x - cx0) * k

    def Y(y: float) -> float:
        return pad + (y - cy0) * k

    def label(x: float, y: float, text: str, color: tuple[int, int, int]) -> None:
        bb = d.textbbox((x, y), text, font=font)
        d.rectangle((bb[0] - 2, bb[1] - 1, bb[2] + 2, bb[3] + 1), fill="white", outline=color)
        d.text((x, y), text, fill=color, font=font)

    run = meas["runs"][wall]
    for key, ln in run["lines"].items():
        d.line([(X(cx0), Y(_y(ln, cx0))), (X(cx1), Y(_y(ln, cx1)))], fill=(20, 160, 60), width=1)
        label(X(cx1) - 110, Y(_y(ln, cx1)) - 18, key, (20, 140, 50))
    colors = {"base": (30, 80, 220), "upper": (220, 30, 30), "upper-top": (150, 40, 190)}
    for storey, lines in run["cand"].items():
        keys = band_lines(run["lines"], storey)
        if keys is None:
            continue
        for n, ln in enumerate(lines):
            x = ln["pos"] + 0.5
            yt, yb = _y(run["lines"][keys[0]], x), _y(run["lines"][keys[1]], x)
            d.line([(X(x), Y(yt)), (X(x), Y(yb))], fill=colors[storey], width=2)
            ly = Y(yt) + 4 + 18 * (n % 3) if storey != "base" else Y(yb) - 22 - 18 * (n % 3)
            label(X(x) + 2, ly, ln["id"], colors[storey])
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()
