"""Structures of an imported floorplan (walls, columns, stairs, doors, furniture...) as triangle meshes for the Python renderer.

The three.js export draws these as ``room.structures``; this module gives the control-map renderer (``kitchen.render``) the same
solids, in the kitchen frame, so every view has a seg mask for them. Part type is ``structure-<kind>`` and ``module`` is the
structure id, so ``seg.png`` (by kind), ``seg_module.png`` (by element) and ``instance.png`` all separate them from the cabinets.
"""
from __future__ import annotations

from typing import Any

import math
from collections.abc import Callable

from .jsonview import as_list
from .moldings import MeshPart, ear_clip

Pt = tuple[float, float]
ToKitchen = Callable[[float, float], Pt]   # room scene (x, z) -> kitchen frame (x, z)

KINDS = ("wall", "column", "opening", "furniture", "shaft", "stair", "area")
SWING = "swing"          # type structure-swing: the floor area a door sweeps, drawn as a flat sheet next to the door
TYPE_PREFIX = "structure-"


def is_structure(part_type: str) -> bool:
    return part_type.startswith(TYPE_PREFIX)


def _signed_area(poly: list[tuple[float, float]]) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1])) / 2


def prism(poly: list[tuple[float, float]], y0: float, y1: float) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Vertices (x, y, z) and triangles of the solid whose floor is ``poly`` (x, z) between heights y0 and y1; y1 == y0 gives a flat sheet."""
    if len(poly) > 1 and poly[0] == poly[-1]:
        poly = poly[:-1]
    if _signed_area(poly) < 0:
        poly = poly[::-1]
    n = len(poly)
    verts = [(x, y0, z) for x, z in poly]
    faces: list[tuple[int, int, int]] = [(a, b, c) for a, b, c in ear_clip(poly)]
    if y1 > y0:
        verts += [(x, y1, z) for x, z in poly]
        faces += [(n + a, n + b, n + c) for a, b, c in ear_clip(poly)]
        for i in range(n):
            j = (i + 1) % n
            faces += [(i, j, n + j), (i, n + j, n + i)]
    return verts, faces


def _clip_halfplane(poly: list[tuple[float, float]], d: tuple[float, float], t0: float) -> list[tuple[float, float]]:
    """Part of ``poly`` where dot(p, d) >= t0 (Sutherland-Hodgman against one line)."""
    out: list[tuple[float, float]] = []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        da, db = a[0] * d[0] + a[1] * d[1] - t0, b[0] * d[0] + b[1] * d[1] - t0
        if da >= 0:
            out.append(a)
        if (da >= 0) != (db >= 0):
            k = da / (da - db)
            out.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
    return out


def _stair_steps(st: dict[str, Any], poly: list[tuple[float, float]]) -> list[tuple[list[tuple[float, float]], float]]:
    """(footprint, top height above base) per step; step i covers the stair from its start to the far end and is (i+1)/n of the rise."""
    xs, zs = [p[0] for p in poly], [p[1] for p in poly]
    arrow = st.get("arrow")
    if arrow and len(arrow) >= 2:
        d = (arrow[1]["x"] - arrow[0]["x"], arrow[1]["z"] - arrow[0]["z"])
    else:
        d = (0.0, 1.0) if max(zs) - min(zs) >= max(xs) - min(xs) else (1.0, 0.0)
    ln = math.hypot(*d) or 1.0
    d = (d[0] / ln, d[1] / ln)
    al = [p[0] * d[0] + p[1] * d[1] for p in poly]
    a0, run = min(al), (max(al) - min(al)) / st["steps"]
    out: list[tuple[list[tuple[float, float]], float]] = []
    for i in range(st["steps"]):
        part = _clip_halfplane(poly, d, a0 + run * i)
        if len(part) >= 3:
            out.append((part, st["height"] * (i + 1) / st["steps"]))
    return out


def swing_sheet(st: dict[str, Any], to_kitchen: ToKitchen) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]] | None:
    """Flat fan from the hinge across the arc a door sweeps (``swing`` points, ``hinge``), 2 mm above the floor; None without both."""
    arc = as_list(st.get("swing")) or []
    hinge = st.get("hinge")
    if len(arc) < 2 or not hinge:
        return None
    pts = [to_kitchen(hinge["x"], hinge["z"])] + [to_kitchen(p["x"], p["z"]) for p in arc]
    y = float(st.get("base") or 0.0) + 2.0
    return [(x, y, z) for x, z in pts], [(0, i, i + 1) for i in range(1, len(pts) - 1)]


def meshes(structures: list[dict[str, Any]], to_kitchen: ToKitchen) -> list[MeshPart]:
    """``structures``: floorplan.structures() records (scene outline in mm). ``to_kitchen(x, z) -> (x, z)`` maps room-scene to kitchen frame."""
    out: list[MeshPart] = []
    for st in structures:
        kind = st["kind"] if st["kind"] in KINDS else "area"
        poly: list[Pt] = [to_kitchen(p["x"], p["z"]) for p in st["outline"]]
        if len(poly) < 3:
            continue
        base = float(st.get("base") or 0.0)
        solids: list[tuple[list[Pt], float, float]]
        if st["kind"] == "stair" and st.get("steps") and st.get("height", 0) > 0:
            solids = [(pp, base, base + h) for pp, h in _stair_steps({**st, "arrow": _map_arrow(st.get("arrow"), to_kitchen)}, poly)]
        elif st.get("height", 0) > 0:
            solids = [(poly, base, base + float(st["height"]))]
        else:
            solids = [(poly, base + 1.0, base + 1.0)]
        for k, (pp, y0, y1) in enumerate(solids):
            v, f = prism(pp, y0, y1)
            out.append(MeshPart(st["id"] if len(solids) == 1 else f"{st['id']}-{k + 1}", st["id"], TYPE_PREFIX + kind, v, f))
        sheet = swing_sheet(st, to_kitchen) if st["kind"] == "opening" else None
        if sheet:
            out.append(MeshPart(f"{st['id']}-swing", st["id"], TYPE_PREFIX + SWING, sheet[0], sheet[1]))
    return out


def _map_arrow(value: Any, to_kitchen: ToKitchen) -> list[dict[str, float]] | None:
    arrow = as_list(value)
    if not arrow or len(arrow) < 2:
        return None
    pts = [to_kitchen(p["x"], p["z"]) for p in arrow[:2]]
    return [{"x": x, "z": z} for x, z in pts]
