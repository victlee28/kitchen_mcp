"""Solids of the openings a design places, for the control-map renderer and the layer catalogue (plan §4, slice 2). Pure.

Part types: ``opening-frame`` (jambs, head, sill, transoms, mullions, casings), ``opening-leaf`` (a door leaf), ``opening-glass`` (a
window leaf, fixed glazing) and ``opening-sweep`` (the floor a turning leaf sweeps, a flat sheet 2 mm up, like the floorplan's doors).
``module`` is the opening id, so every opening has its own masks. The wall around the hole is cut by ``cut_polygon`` / ``cut_box``.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..moldings import MeshPart
from ..structure_mesh import prism
from .contract import Opening, Pt
from .shape import OpeningShape, shape
from .wall_axes import WallAxis

SWEEP_Y = 2.0


@dataclass(frozen=True)
class Hole:
    """The hole an opening cuts, in the frame of the axis it is given with: ``s`` from ``e0`` to ``e1`` along ``axis``, heights
    ``y0`` (sill) to ``y1`` (head)."""
    id: str
    axis: WallAxis
    e0: float
    e1: float
    y0: float
    y1: float


def _quad(axis: WallAxis, s0: float, s1: float, d0: float, d1: float) -> list[Pt]:
    return [axis.point(s0, d0), axis.point(s1, d0), axis.point(s1, d1), axis.point(s0, d1)]


def leaf_type(opening: Opening, operation: str) -> str:
    return "opening-glass" if opening.kind == "window" or operation == "fixed" else "opening-leaf"


def meshes(opening: Opening, axis: WallAxis, type_data: Mapping[str, Any], sh: OpeningShape | None = None) -> list[MeshPart]:
    """Frame, leaves (closed) and sweep sheets of one opening on ``axis`` (kitchen frame)."""
    sh = sh if sh is not None else shape(opening, axis, type_data)
    out: list[MeshPart] = []
    for b in sh["frame"]:
        v, f = prism(_quad(axis, b["s0"], b["s1"], b["d0"], b["d1"]), b["y0"], b["y1"])
        out.append(MeshPart(f"{opening.id}-frame-{b['part']}", opening.id, "opening-frame", v, f))
    for lf in sh["leaves"]:
        v, f = prism(_quad(axis, lf["s0"], lf["s1"], lf["d0"], lf["d1"]), lf["y0"], lf["y1"])
        out.append(MeshPart(f"{opening.id}-leaf-{lf['index'] + 1}", opening.id, leaf_type(opening, lf["operation"]), v, f))
    for k, poly in enumerate(sh["sweeps"], 1):
        if len(poly) >= 3:
            v, f = prism(list(poly), SWEEP_Y, SWEEP_Y)
            out.append(MeshPart(f"{opening.id}-sweep-{k}", opening.id, "opening-sweep", v, f))
    return out


def hole(opening: Opening, axis: WallAxis) -> Hole:
    return Hole(opening.id, axis, opening.center - opening.width / 2, opening.center + opening.width / 2, opening.sill,
                opening.sill + opening.height)


def _clip(poly: list[Pt], d: Pt, t0: float) -> list[Pt]:
    """Part of ``poly`` where dot(p, d) >= t0."""
    out: list[Pt] = []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        da, db = a[0] * d[0] + a[1] * d[1] - t0, b[0] * d[0] + b[1] * d[1] - t0
        if da >= 0:
            out.append(a)
        if (da >= 0) != (db >= 0):
            k = da / (da - db)
            out.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
    return out


def _area(poly: list[Pt]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))) / 2


def cut_polygon(poly: list[Pt], y0: float, y1: float, h: Hole, near: float) -> list[tuple[list[Pt], float, float]] | None:
    """A wall solid (floor outline ``poly`` from ``y0`` to ``y1``) with the hole taken out, as solids; None when the hole does not
    pass through it (the outline does not reach the hole's span, or lies further than ``near`` from the axis)."""
    a = h.axis
    base = a.start[0] * a.dir[0] + a.start[1] * a.dir[1]
    if not poly or min(abs(a.d_of(p)) for p in poly) > near:
        return None
    mid = _clip(_clip(poly, a.dir, base + h.e0), (-a.dir[0], -a.dir[1]), -(base + h.e1))
    if len(mid) < 3 or _area(mid) < 1.0 or h.y1 <= y0 or h.y0 >= y1:
        return None
    out: list[tuple[list[Pt], float, float]] = []
    for part in (_clip(poly, (-a.dir[0], -a.dir[1]), -(base + h.e0)), _clip(poly, a.dir, base + h.e1)):
        if len(part) >= 3 and _area(part) >= 1.0:
            out.append((part, y0, y1))
    if h.y0 > y0:
        out.append((mid, y0, h.y0))
    if h.y1 < y1:
        out.append((mid, h.y1, y1))
    return out


def cut_box(lo: tuple[float, float, float], hi: tuple[float, float, float], h: Hole
            ) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]] | None:
    """An axis-aligned wall box with the hole taken out (the axis runs along x or z), as boxes; None when the hole misses it."""
    a = h.axis
    along = 0 if abs(a.dir[0]) > abs(a.dir[1]) else 2
    p0, p1 = a.point(h.e0), a.point(h.e1)
    c0, c1 = sorted((p0[0], p1[0]) if along == 0 else (p0[1], p1[1]))
    across = 2 if along == 0 else 0
    line = p0[1] if along == 0 else p0[0]
    if not (lo[across] - 1 <= line <= hi[across] + 1) or c1 <= lo[along] or c0 >= hi[along] or h.y1 <= lo[1] or h.y0 >= hi[1]:
        return None
    def with_range(axis_i: int, v0: float, v1: float, y0: float, y1: float) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        l, u = list(lo), list(hi)
        l[axis_i], u[axis_i], l[1], u[1] = v0, v1, y0, y1
        return (l[0], l[1], l[2]), (u[0], u[1], u[2])
    out: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    if c0 > lo[along]:
        out.append(with_range(along, lo[along], c0, lo[1], hi[1]))
    if c1 < hi[along]:
        out.append(with_range(along, c1, hi[along], lo[1], hi[1]))
    m0, m1 = max(c0, lo[along]), min(c1, hi[along])
    if h.y0 > lo[1]:
        out.append(with_range(along, m0, m1, lo[1], h.y0))
    if h.y1 < hi[1]:
        out.append(with_range(along, m0, m1, h.y1, hi[1]))
    return out
