"""Phụ kiện mặt trước: bản lề từng cánh và vị trí/kích thước tay nắm.

Một nguồn duy nhất cho cả bộ biên dịch hình học (render, mask) và bộ xuất three.js, để tay nắm trong ảnh
điều khiển, trong mask sửa ảnh và trong cảnh three.js luôn trùng nhau.

Hệ toạ độ cánh: x từ mép trái (nhìn từ phía trước) sang phải, y từ mép dưới lên, z nhô ra phía phòng.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .numeric import round_int
from .spec import Module, Handle

TIER = {"base": "base", "upper": "wall", "loft": "top", "tall": "tall", "corner": "corner"}
_OPEN = {"left": "Left", "right": "Right", "upper": "Top", "base": "Bottom"}


def hinges(m: Module, doors: list[tuple[float, float, float, float]]) -> list[str]:
    """Bản lề (Left/Right/Top/Bottom) cho từng cánh, theo thứ tự đầu vào. doors: (x0, x1, y0, y1) trong hệ module.
    Thứ tự đánh số cánh (để khớp m.moCanh): theo hàng từ dưới lên, trong hàng từ trái sang phải."""
    storey = m.storey
    rows: dict[int, list[int]] = defaultdict(list)
    for i in sorted(range(len(doors)), key=lambda i: (doors[i][2], doors[i][0])):
        rows[round_int(doors[i][2])].append(i)
    out: dict[int, str] = {}
    k = 0
    for _, idx in sorted(rows.items()):
        idx.sort(key=lambda i: doors[i][0])
        cnt = len(idx)
        for pos, i in enumerate(idx):
            x0, x1, y0, y1 = doors[i]
            w, h = x1 - x0, y1 - y0
            if k < len(m.hingeSides):
                hg = _OPEN[m.hingeSides[k]]
            elif storey == "loft" and w > h * 1.2:
                hg = "Top"
            elif cnt >= 2:
                hg = "Left" if pos < cnt / 2 else "Right"
            else:
                hg = "Right" if (m.blindCorner or m.wall == "right") else "Left"
            out[i] = hg
            k += 1
    return [out[i] for i in range(len(doors))]


def handle(tn: Handle, w: float, h: float, tier: str, hinge: str | None, horizontal: bool = False) -> dict[str, Any] | None:
    """Tay nắm trên một cánh/ngăn kéo rộng w, cao h. None nếu không có tay nhô ra (âm / nhấn mở)."""
    if tn.variant in ("none", "concealed"):
        return None
    if tn.variant == "knob":
        size, asset, kind = (30.0, 30.0, 25.0), "ASSET-HANDLE-KNOB", "Knob"
    else:
        L = min(tn.length, (w if horizontal else h) - 60)
        if L <= 0:
            return None
        size, asset, kind = ((L, 12.0, 30.0) if horizontal else (12.0, L, 30.0)), "ASSET-HANDLE-BAR", "Pull_Handle"
    hw, hh, _ = size
    if horizontal:  # ngăn kéo: tay ở trên; cánh lật lên (bản lề trên): tay ở mép dưới
        x, y = (w - hw) / 2, (30 if hinge == "Top" else h - 40 - hh)
    else:
        x = 40 if hinge == "Right" else w - 40 - hw
        y = h - 60 - hh if tier == "base" else 60 if tier in ("wall", "top") else max(60, min(h - hh - 60, 1100 - hh / 2))
    return {"type": kind, "assetId": asset, "x": x, "y": y, "size": size}
