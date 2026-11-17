"""Cửa trong ảnh -> cửa đo bằng mm, dọc tường theo cùng hệ toạ độ với tủ (lõi thuần, xác định).

``project(wall, u_px, v_px) -> (x_mm, h_mm)``: điểm ảnh nằm TRÊN MẶT TƯỜNG -> vị trí dọc tường (cùng gốc với ``x`` của module) và độ cao
từ sàn. Nhánh phối cảnh dựng nó từ camera; nhánh chính diện từ tỉ lệ mm/px của tủ trên (gần mặt tường nhất).

Mỗi cửa ra::

    {"id": "CS1", "kind", "wall", "x", "width", "axes"?: [x giữa], "sill"?, "head"?, "hAxes"?: [h], "edgesSeen", "style", "leaves",
     "transomPanes"?, "panels"?: [{"row", "operation", "handle", "front"}], "confidence", "unsure"?: ["start" | "end" | "sill" | "head"],
     "note"?}

``x``/``width`` là mép thấy được (``edgesSeen``: ngoài nẹp hay mép lỗ); bên nhận trừ nẹp. Một mép bị che (``hidden``) vẫn được đo nhưng
ghi vào ``unsure``; chân cửa bị che thì không có ``sill`` (bên nhận dùng mặc định của loại cửa).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .contract_openings import OpeningAnswer
from .errors import RecognizerError
from .numeric import round_half_away, round_int

Project = Callable[[str, float, float], tuple[float, float]]
STEP_MM = 10
MIN_WIDTH_MM, MAX_WIDTH_MM = 300, 4000
MIN_HEIGHT_MM, MAX_HEIGHT_MM = 200, 3200


def place(answers: list[OpeningAnswer], project: Project, image_size: tuple[int, int],
          warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    w, h = image_size
    out: list[dict[str, Any]] = []
    for i, ans in enumerate(answers):
        wall = ans["wall"]

        def at(p: tuple[float, float]) -> tuple[float, float]:
            return project(wall, p[0] * w, p[1] * h)

        try:
            c = {k: at(p) for k, p in ans["corners"].items()}
            mids_raw = [at(p)[0] for p in ans["verticals"]]
            lows_raw = [at(p)[1] for p in ans["horizontals"]]
        except RecognizerError as e:          # một góc không nằm trên mặt tường (trên đường chân trời, sau camera)
            warnings.append({"code": "opening-off-wall", "index": i, "reason": e.code})
            continue
        left = (c["topLeft"][0] + c["bottomLeft"][0]) / 2
        right = (c["topRight"][0] + c["bottomRight"][0]) / 2
        x0, x1 = sorted((left, right))
        flipped = left > right                     # tường trái: x tăng ngược chiều ảnh
        sill = (c["bottomLeft"][1] + c["bottomRight"][1]) / 2
        head = (c["topLeft"][1] + c["topRight"][1]) / 2
        width, height = x1 - x0, head - sill
        if not (MIN_WIDTH_MM <= width <= MAX_WIDTH_MM and MIN_HEIGHT_MM <= height <= MAX_HEIGHT_MM and sill > -100):
            warnings.append({"code": "opening-implausible", "index": i, "widthMm": round_int(width), "heightMm": round_int(height)})
            continue
        item: dict[str, Any] = {"id": f"CS{len(out) + 1}", "kind": ans["kind"], "wall": wall,
                                "x": round_int(x0, STEP_MM), "width": round_int(x1, STEP_MM) - round_int(x0, STEP_MM)}
        mids = sorted(mids_raw)
        mids = [round_int(m, STEP_MM) for m in mids if x0 < m < x1]
        if mids:
            item["axes"] = mids
        if "bottom" not in ans["hidden"]:
            item["sill"] = max(0, round_int(sill, STEP_MM))
        item["head"] = round_int(head, STEP_MM)
        lows = sorted(lows_raw)
        lows = [round_int(v, STEP_MM) for v in lows if sill < v < head]
        if lows:
            item["hAxes"] = lows
        item.update(edgesSeen=ans["edgesSeen"], style=ans["style"], leaves=ans["leaves"], confidence=ans["confidence"])
        item.update(_detail(ans))
        # "start" = mép x nhỏ: bên trái ảnh, trừ khi tường lật chiều
        side_of = {"left": "end" if flipped else "start", "right": "start" if flipped else "end", "top": "head", "bottom": "sill"}
        unsure = sorted({side_of[s] for s in ans["hidden"]})
        if unsure:
            item["unsure"] = unsure
        if ans["note"]:
            item["note"] = ans["note"]
        out.append(item)
    return out


# ---------------- ảnh không có tủ: chỉ có tỉ lệ ----------------

def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Khử Gauss có chọn trụ (hệ nhỏ 8x8)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise ValueError("singular")
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def _to_unit(quad: list[tuple[float, float]]) -> Callable[[float, float], tuple[float, float]]:
    """Phép chiếu đưa tứ giác ảnh (trên-trái, trên-phải, dưới-phải, dưới-trái) về ô vuông đơn vị (u: trái -> phải, v: bậu -> đỉnh)."""
    target = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    a: list[list[float]] = []
    b: list[float] = []
    for (x, y), (u, v) in zip(quad, target):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    h = _solve(a, b)

    def f(x: float, y: float) -> tuple[float, float]:
        w = h[6] * x + h[7] * y + 1.0
        return ((h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w)
    return f


RATIO_STEP = 0.001


def _ratio(x: float) -> float:
    return float(f"{round_half_away(x, RATIO_STEP):.3f}")      # 0.818, không phải 0.8180000000000001


def photo(answers: list[OpeningAnswer], image_size: tuple[int, int], warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cửa trong ảnh không có tủ: không có vật chuẩn nên không có mm. Ra loại, cánh, tỉ lệ cao/rộng (gần đúng: theo cạnh trong ảnh) và vị
    trí các trục giữa theo tỉ lệ của mép (đúng cả khi chụp xiên: chiếu tứ giác về hình chữ nhật)::

        {"id": "CS1", "kind", "style", "leaves", "edgesSeen", "aspect": cao/rộng, "axesRatio": [0..1 từ mép trái], "hAxesRatio": [0..1 từ bậu],
         "transomPanes"?, "panels"?, "confidence", "hidden"?, "note"?}
    """
    w, h = image_size
    out: list[dict[str, Any]] = []
    for i, ans in enumerate(answers):
        c = ans["corners"]
        quad = [(c[k][0] * w, c[k][1] * h) for k in ("topLeft", "topRight", "bottomRight", "bottomLeft")]
        try:
            unit = _to_unit(quad)
        except ValueError:
            warnings.append({"code": "opening-implausible", "index": i})
            continue

        def length(p: tuple[float, float], q: tuple[float, float]) -> float:
            return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5
        wide = (length(quad[0], quad[1]) + length(quad[3], quad[2])) / 2
        tall = (length(quad[0], quad[3]) + length(quad[1], quad[2])) / 2
        if wide <= 0 or tall <= 0:
            warnings.append({"code": "opening-implausible", "index": i})
            continue
        mids = sorted(_ratio(unit(p[0] * w, p[1] * h)[0]) for p in ans["verticals"])
        lows = sorted(_ratio(unit(p[0] * w, p[1] * h)[1]) for p in ans["horizontals"])
        item: dict[str, Any] = {"id": f"CS{len(out) + 1}", "kind": ans["kind"], "style": ans["style"], "leaves": ans["leaves"],
                                "edgesSeen": ans["edgesSeen"], "aspect": _ratio(tall / wide),
                                "axesRatio": [m for m in mids if 0.02 < m < 0.98], "hAxesRatio": [v for v in lows if 0.02 < v < 0.98],
                                "confidence": ans["confidence"]}
        item.update(_detail(ans))
        if ans["hidden"]:
            item["hidden"] = ans["hidden"]
        if ans["note"]:
            item["note"] = ans["note"]
        out.append(item)
    return out


def _detail(ans: OpeningAnswer) -> dict[str, Any]:
    """Số ô của ô thoáng (khi AI nói thanh đứng của hàng trên) và các ô (kiểu mở, tay nắm, ray trước), chuyển nguyên cho bên nhận."""
    out: dict[str, Any] = {}
    if ans["upperVerticals"] is not None and ans["horizontals"]:
        out["transomPanes"] = len(ans["upperVerticals"]) + 1
    if ans["panels"] is not None:
        out["panels"] = [dict(p) for p in ans["panels"]]
    return out
