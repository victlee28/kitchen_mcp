"""Xử lý ảnh cho sửa theo lớp: mask từ instance, mask inpaint, ghép ảnh (strict) và kiểm tra kết quả.

Strict compositing: alpha chỉ khác 0 bên trong mask đích (viền mềm vào trong), nên mọi pixel ngoài mask
bằng đúng ảnh gốc theo cấu tạo. Đo thay đổi ngoài mask trên ảnh AI thô chỉ để chẩn đoán model.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def read(path: Path, mode: str = "RGB") -> np.ndarray:
    with Image.open(path) as im:
        return np.array(im.convert(mode))


def load_instances(render_dir: Path) -> tuple[np.ndarray, dict]:
    d = Path(render_dir)
    if not (d / "instance.png").exists():
        raise FileNotFoundError(f"Chưa có instance.png trong {d.name}; hãy render lại góc nhìn này")
    with Image.open(d / "instance.png") as im:
        inst = np.array(im).astype(np.int32)
    meta = json.loads((d / "instances.json").read_text(encoding="utf-8"))
    return inst, meta


def mask_of(render_dir: Path, part_ids: list[str]) -> np.ndarray:
    inst, meta = load_instances(render_dir)
    want = {x["value"] for x in meta["instances"] if x["id"] in set(part_ids)}
    return np.isin(inst, list(want)) if want else np.zeros(inst.shape, bool)


def pick(render_dir: Path, x: int, y: int, radius: int = 0) -> dict | None:
    """Instance at a pixel. With radius > 0 a handle within that many pixels wins over a non-handle hit: handles are only a few pixels wide."""
    inst, meta = load_instances(render_dir)
    if not (0 <= y < inst.shape[0] and 0 <= x < inst.shape[1]):
        raise ValueError("Toạ độ ngoài ảnh")
    by_value = {i["value"]: i for i in meta["instances"]}
    v = int(inst[y, x])
    hit = by_value.get(v) if v else None
    if radius > 0 and not (hit and "-handle-" in hit["id"]):
        y0, x0 = max(0, y - radius), max(0, x - radius)
        win = inst[y0:y + radius + 1, x0:x + radius + 1]
        best, best_d = None, None
        for val in np.unique(win):
            item = by_value.get(int(val))
            if not item or "-handle-" not in item["id"]:
                continue
            ys, xs = np.nonzero(win == val)
            d = int(((ys + y0 - y) ** 2 + (xs + x0 - x) ** 2).min())
            if best_d is None or d < best_d:
                best, best_d = item, d
        if best is not None:
            return best
    return hit


def _pil(mask: np.ndarray) -> Image.Image:
    return Image.fromarray((mask.astype(np.uint8) * 255), "L")


def _dilate(mask: np.ndarray, px: int) -> np.ndarray:
    """Giãn vuông (2px+1)² tách theo hai trục — O(px) phép OR trên mảng, nhanh hơn MaxFilter lớn của PIL nhiều lần."""
    m = mask.astype(bool)
    ys, xs = np.nonzero(m)
    if not len(xs):
        return m.copy()
    H, W = m.shape
    y0, y1, x0, x1 = max(0, ys.min() - px), min(H, ys.max() + px + 1), max(0, xs.min() - px), min(W, xs.max() + px + 1)
    sub = m[y0:y1, x0:x1]
    h, w = sub.shape
    a = sub.copy()
    for d in range(1, px + 1):
        a[:, d:] |= sub[:, :w - d] if d < w else False
        a[:, :w - d] |= sub[:, d:] if d < w else False
    b = a.copy()
    for d in range(1, px + 1):
        b[d:, :] |= a[:h - d, :] if d < h else False
        b[:h - d, :] |= a[d:, :] if d < h else False
    out = np.zeros_like(m)
    out[y0:y1, x0:x1] = b
    return out


def grow(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask.copy()
    return _dilate(mask, px)


def shrink(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask.copy()
    # co = phần bù của giãn phần bù; ngoài ảnh coi như nền (giống MinFilter của PIL ở biên: lặp mép) -> đệm mép bằng chính mask
    pad = np.pad(mask.astype(bool), px, mode="edge")
    return ~_dilate(~pad, px)[px:-px, px:-px]


def alpha(target: np.ndarray, feather: int = 2) -> np.ndarray:
    """Alpha ghép: 1 trong lõi mask, mềm dần về mép, 0 ngoài mask (không lấn sang chi tiết bên cạnh)."""
    if feather <= 0:
        return target.astype(np.float32)
    core = shrink(target, feather)
    if core.sum() < 0.5 * target.sum():  # vùng mảnh (tay nắm, nẹp): viền mềm sẽ xoá mất chi tiết -> ghép cứng
        return target.astype(np.float32)
    a = np.array(_pil(core).filter(ImageFilter.GaussianBlur(feather)), np.float32) / 255
    a = np.maximum(a, core.astype(np.float32))
    a = np.clip(a * 2, 0, 1)  # mép mask ~ 1/2 -> 1, vùng gần mép vẫn mềm
    return a * target


def save_mask(mask: np.ndarray, path: Path) -> None:
    _pil(mask).convert("RGB").save(path)


def load_rgb(path: Path, size: tuple[int, int] | None = None) -> tuple[np.ndarray, bool]:
    with Image.open(path) as f:
        im = f.convert("RGB")
    resized = False
    if size and im.size != size:
        im = im.resize(size, Image.Resampling.LANCZOS)
        resized = True
    return np.array(im), resized


def composite(ref: np.ndarray, raw: np.ndarray, a: np.ndarray) -> np.ndarray:
    out = ref.astype(np.float32) * (1 - a[..., None]) + raw.astype(np.float32) * a[..., None]
    out = np.rint(out).astype(np.uint8)
    out[a <= 0] = ref[a <= 0]  # bảo đảm tuyệt đối ngoài mask
    return out


def recolor(ref: np.ndarray, target: np.ndarray, rgb: tuple[int, int, int]) -> np.ndarray:
    """Backend 'to-mau': đổi màu vùng đích, giữ sáng tối/nét của ảnh gốc (không cần AI)."""
    out = ref.copy()
    if not target.any():
        return out
    f = ref.astype(np.float32)
    lum = 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]
    med = float(np.median(lum[target])) or 1.0
    k = np.clip(lum / med, 0.35, 1.6)
    col = np.array(rgb, np.float32)
    out[target] = np.clip(k[target][:, None] * col, 0, 255).astype(np.uint8)
    return out


def _grad(img: np.ndarray) -> np.ndarray:
    g = img.astype(np.float32).mean(-1)
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:-1] = np.abs(g[:, 2:] - g[:, :-2])
    gy[1:-1, :] = np.abs(g[2:, :] - g[:-2, :])
    return np.maximum(gx, gy)


def edge_alignment(img: np.ndarray, lines: np.ndarray) -> dict:
    """Ảnh AI có giữ đúng hình học không: tỷ lệ pixel nét (lines.png) có cạnh trong ảnh, so với vùng cách nét 6-10 px.
    Ảnh khớp: tyLeTrenNet cao hơn hẳn tyLeNgoaiNet. Ảnh bị lệch/vẽ lại: hai số gần nhau."""
    if img.shape[:2] != lines.shape[:2]:
        return {"khop": None, "note": "khác kích thước"}
    edge = np.array(Image.fromarray((_grad(img) > 14).astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(5))) > 0
    on = lines < 128
    far = grow(on, 10) & ~grow(on, 6)
    if not on.any() or not far.any():
        return {"khop": None}
    a, b = float(edge[on].mean()), float(edge[far].mean())
    return {"onLineRatio": round(a, 3), "outsideLineRatio": round(b, 3), "score": round(a - b, 3), "khop": (a - b) >= 0.15}


def check(ref: np.ndarray, raw: np.ndarray, comp: np.ndarray, target: np.ndarray, edit_region: np.ndarray,
          lines: np.ndarray | None) -> dict:
    """Ba nhóm kiểm tra: vùng ảnh (trong/ngoài mask), biên (so với lines.png), chẩn đoán ảnh thô."""
    rep: dict = {}
    outside = ~target
    d_out = np.abs(comp.astype(np.int16) - ref.astype(np.int16)).max(-1)
    rep["outsideMask"] = {"pixelsChanged": int((d_out[outside] > 0).sum()), "setPreserve": bool((d_out[outside] == 0).all())}
    d_in = np.abs(comp.astype(np.int16) - ref.astype(np.int16)).mean(-1)
    tin = float(d_in[target].mean()) if target.any() else 0.0
    rep["insideMask"] = {"meanChange": round(tin, 2), "changed": tin >= 3.0,
                        "meanColor": [int(v) for v in comp[target].mean(0)] if target.any() else None}
    far = ~grow(edit_region, 8)
    d_raw = np.abs(raw.astype(np.int16) - ref.astype(np.int16)).mean(-1)
    rep["rawImage"] = {"changesOutsideEditZone": round(float(d_raw[far].mean()), 2) if far.any() else 0.0,
                     "note": "chỉ để chẩn đoán model; ảnh cuối luôn lấy pixel gốc ngoài mask"}
    if lines is not None:
        band = grow(target, 3) & ~shrink(target, 3)
        ln = (lines < 128) & band
        if ln.any():
            def ratio(img):
                g = np.array(Image.fromarray((_grad(img) > 12).astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0
                return float(g[ln].mean())
            r_ref, r_comp = ratio(ref), ratio(comp)
            rep["bien"] = {"baseLineRatio": round(r_ref, 3), "resultLineRatio": round(r_comp, 3),
                           "setEdge": r_comp >= 0.8 * r_ref - 1e-9}
    return rep


def bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) bao vùng True, x1/y1 loại trừ."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def mark_regions(ref: np.ndarray, regions: list[tuple[np.ndarray, tuple[int, int, int], str]], gap: int = 14,
                 width: int = 3) -> np.ndarray:
    """Ảnh gốc có ĐÁNH DẤU cho model nhận chỉ dẫn (Gemini web/API): viền màu bao NGOÀI từng vùng cần sửa + nhãn số.

    Viền cách mép vùng `gap` px (> độ nở mask gửi model) nên nằm hẳn ngoài mask đích: khi ghép strict, mọi pixel viền
    model trả về đều bị thay bằng ảnh gốc; ảnh cuối không bao giờ dính viền. regions: (mask đích, màu RGB, nhãn)."""
    from PIL import ImageDraw, ImageFont
    out = ref.copy()
    H, W = ref.shape[:2]
    allm = np.zeros((H, W), bool)
    for m, _, _ in regions:
        allm |= m
    keep = grow(allm, gap)  # viền/nhãn không được đè lên vùng sửa NÀO (vd tay nắm nằm trên cánh cũng đang sửa)
    labels = []
    for m, rgb, lab in regions:
        if not m.any():
            continue
        ring = grow(m, gap + width) & ~keep
        out[ring] = rgb
        labels.append((bbox(m), rgb, lab))
    im = Image.fromarray(out)
    dr = ImageDraw.Draw(im)
    size = max(14, min(W, H) // 30)
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:  # Pillow cũ
        font = ImageFont.load_default()
    r = size // 2 + 5
    o = gap + width + r
    for (x0, y0, x1, y1), rgb, lab in labels:
        # thử 4 góc ngoài khung vùng, rồi điểm giữa cạnh trên/dưới; chọn chỗ đầu tiên nằm trong ảnh và không đè vùng sửa
        cands = [(x0 - o, y0 - o), (x1 + o, y0 - o), (x0 - o, y1 + o), (x1 + o, y1 + o), ((x0 + x1) // 2, y0 - o),
                 ((x0 + x1) // 2, y1 + o)]
        best = None
        for cx, cy in cands:
            cx, cy = min(max(cx, r + 1), W - r - 2), min(max(cy, r + 1), H - r - 2)
            if not keep[cy - r:cy + r + 1, cx - r:cx + r + 1].any():
                best = (cx, cy)
                break
        cx, cy = best or (min(max(cands[0][0], r + 1), W - r - 2), min(max(cands[0][1], r + 1), H - r - 2))
        dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(rgb), outline=(255, 255, 255), width=2)
        dr.text((cx, cy), lab, fill=(255, 255, 255) if sum(rgb) < 560 else (0, 0, 0), font=font, anchor="mm")
    return np.array(im)
