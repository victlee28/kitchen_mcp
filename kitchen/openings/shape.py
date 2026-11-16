"""Geometry of a normalized opening on its wall axis (plan §4). Pure; nothing here is ever stored.

Local coordinates of a box: ``s`` along the axis (mm from its start), ``y`` above the floor of the level, ``d`` across the axis
(``+`` = the axis normal; 0 = the wall's centreline). World points (``hole``, ``sweeps``) are in the axis's own frame.
"""
from __future__ import annotations

from ..numeric import round_half_away

import math
from collections.abc import Mapping
from typing import Any, TypedDict

from .contract import Opening, Pt
from .types import casing_width, grid, num, obj
from .wall_axes import WallAxis

ARC_STEPS = 12


class Box(TypedDict):
    part: str
    s0: float
    s1: float
    y0: float
    y1: float
    d0: float
    d1: float


class LeafShape(TypedDict):
    index: int
    operation: str
    s0: float
    s1: float
    y0: float
    y1: float
    d0: float
    d1: float
    hingeS: float | None
    side: str | None
    active: bool


class OpeningShape(TypedDict):
    hole: list[Pt]
    center: Pt
    along: Pt
    normal: Pt
    thickness: float
    edges: tuple[float, float]
    vAxes: list[float]
    hAxes: list[float]
    frame: list[Box]
    leaves: list[LeafShape]
    sweeps: list[list[Pt]]
    clear: tuple[float, float] | None


def _r(v: float) -> float:
    out = round_half_away(v, 3)
    return out + 0.0 if out != 0 else 0.0


def _pt(axis: WallAxis, s: float, d: float) -> Pt:
    p = axis.point(s, d)
    return (_r(p[0]), _r(p[1]))


def shape(opening: Opening, axis: WallAxis, type_data: Mapping[str, Any]) -> OpeningShape:
    t = axis.thickness_at(opening.center)
    w, hgt, sill = opening.width, opening.height, opening.sill
    e0, e1 = opening.center - w / 2, opening.center + w / 2
    v_rel, h_rel = grid(type_data, w, hgt, opening.axes, opening.h_axes)
    v = [opening.center + x for x in v_rel]
    h = [sill + y for y in h_rel]
    top = sill + hgt
    ff = num(type_data, "frameFace")
    fd = type_data.get("frameDepth")
    depth = float(fd) if isinstance(fd, (int, float)) and not isinstance(fd, bool) else t
    tr = num(type_data, "transom", ff)
    gap = num(type_data, "gap")
    lt = num(type_data, "leafThickness")
    cw = casing_width(type_data)
    casing = obj(type_data.get("casing"))
    ct = num(casing, "thickness") if casing is not None else 0.0
    threshold = num(type_data, "threshold")
    frame: list[Box] = []

    def box(part: str, s0: float, s1: float, y0: float, y1: float, d0: float, d1: float) -> None:
        if s1 - s0 > 1e-6 and y1 - y0 > 1e-6 and d1 - d0 > 1e-6:
            frame.append({"part": part, "s0": _r(s0), "s1": _r(s1), "y0": _r(y0), "y1": _r(y1), "d0": _r(d0), "d1": _r(d1)})

    if ff > 0:
        box("jamb-start", e0, e0 + ff, sill, top, -depth / 2, depth / 2)
        box("jamb-end", e1 - ff, e1, sill, top, -depth / 2, depth / 2)
        box("head", e0 + ff, e1 - ff, top - ff, top, -depth / 2, depth / 2)
        if opening.kind == "window":
            box("sill", e0 + ff, e1 - ff, sill, sill + ff, -depth / 2, depth / 2)
    if opening.kind == "door" and threshold > 0:
        box("threshold", e0 + ff, e1 - ff, sill, sill + threshold, -depth / 2, depth / 2)
    for k, y in enumerate(h[1:-1], 1):
        box(f"transom-{k}", e0 + ff, e1 - ff, y - tr / 2, y + tr / 2, -depth / 2, depth / 2)
    for k, s in enumerate(v[1:-1], 1):
        touching = [lf for lf in opening.leaves if k in lf.cols]
        if any(lf.operation == "fixed" for lf in touching):
            box(f"mullion-{k}", s - ff / 2, s + ff / 2, sill + (ff if opening.kind == "window" else 0.0), top - ff, -depth / 2, depth / 2)
    if cw > 0 and ct > 0:
        for sign, face in ((1, "plus"), (-1, "minus")):
            d0, d1 = (t / 2, t / 2 + ct) if sign > 0 else (-t / 2 - ct, -t / 2)
            box(f"casing-{face}-start", e0 - cw, e0, sill, top + cw, d0, d1)
            box(f"casing-{face}-end", e1, e1 + cw, sill, top + cw, d0, d1)
            box(f"casing-{face}-head", e0, e1, top, top + cw, d0, d1)

    leaves: list[LeafShape] = []
    sweeps: list[list[Pt]] = []
    nv, nh = len(v), len(h)
    clear: tuple[float, float] | None = None
    for i, lf in enumerate(opening.leaves):
        (c0, c1), (r0, r1) = lf.cols, lf.rows
        s0 = v[c0] + (ff if c0 == 0 else gap / 2)
        s1 = v[c1] - (ff if c1 == nv - 1 else gap / 2)
        y0 = h[r0] + ((ff if opening.kind == "window" else threshold) if r0 == 0 else tr / 2)
        y1 = h[r1] - (ff if r1 == nh - 1 else tr / 2)
        if r0 == 0 or opening.kind != "door":
            y0 += gap
        y1 -= gap
        hinge_s = None
        if lf.hinge is not None and lf.hinge.axis == "v":
            hinge_s = s0 if lf.hinge.index == c0 else s1
        leaves.append({"index": i, "operation": lf.operation, "s0": _r(s0), "s1": _r(s1), "y0": _r(y0), "y1": _r(y1),
                       "d0": _r(-lt / 2), "d1": _r(lt / 2), "hingeS": _r(hinge_s) if hinge_s is not None else None, "side": lf.side,
                       "active": lf.active})
        sign = 1.0 if lf.side == "+" else -1.0
        angle = math.radians(num(type_data, "openingAngle", 90.0))
        if lf.operation in ("swing", "tilt-turn") and hinge_s is not None and lf.side is not None:
            length = s1 - s0
            toward = 1.0 if hinge_s == s0 else -1.0             # from the hinge into the closed leaf, along s
            pivot_d = sign * t / 2
            arc = [_pt(axis, hinge_s, pivot_d)]
            for k in range(ARC_STEPS + 1):
                a = angle * k / ARC_STEPS
                arc.append(_pt(axis, hinge_s + toward * length * math.cos(a), pivot_d + sign * length * math.sin(a)))
            sweeps.append(arc)
        elif lf.operation in ("top-hung", "bottom-hung") and lf.side is not None:
            reach = (y1 - y0) * math.sin(angle)
            face = sign * t / 2
            sweeps.append([_pt(axis, s0, face), _pt(axis, s1, face), _pt(axis, s1, face + sign * reach), _pt(axis, s0, face + sign * reach)])
        if lf.active and opening.kind in ("door", "passage") and opening.clear_width is not None:
            b0 = v[c0] + (ff if c0 == 0 else 0.0)
            b1 = v[c1] - (ff if c1 == nv - 1 else 0.0)
            lost = (b1 - b0) - opening.clear_width
            clear = (_r(b0 + lost), _r(b1)) if hinge_s is not None and hinge_s == s0 else (_r(b0), _r(b1 - lost))
    if opening.kind == "passage" and opening.clear_width is not None:
        clear = (_r(e0), _r(e1))
    n = axis.normal
    return {"hole": [_pt(axis, e0, -t / 2), _pt(axis, e1, -t / 2), _pt(axis, e1, t / 2), _pt(axis, e0, t / 2)],
            "center": _pt(axis, opening.center, 0.0), "along": (axis.dir[0], axis.dir[1]), "normal": (n[0], n[1]), "thickness": t,
            "edges": (_r(e0), _r(e1)), "vAxes": [_r(x) for x in v], "hAxes": [_r(y) for y in h], "frame": frame, "leaves": leaves,
            "sweeps": sweeps, "clear": clear}


def world_opening(opening: Opening, axis: WallAxis, type_data: Mapping[str, Any]) -> Any:
    """The checks' view (``legacy.Opening``) of a contract opening on an axis in the kitchen frame."""
    from .legacy import Opening as WorldOpening, hull
    sh = shape(opening, axis, type_data)
    sweep_points = [p for poly in sh["sweeps"] for p in poly]
    tag = opening.kind
    return WorldOpening(opening.id, tag, tuple(sh["hole"]), sh["center"], sh["along"], sh["normal"], opening.width, sh["thickness"],
                        opening.sill, opening.height, opening.source in ("drawn", "human") and "height" not in opening.unsure,
                        tuple(hull(sweep_points)) if sweep_points else (), opening.clear_width,
                        any(lf.operation != "fixed" for lf in opening.leaves))
