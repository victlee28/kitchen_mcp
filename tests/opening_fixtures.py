"""Small imported-floorplan data (the ``spec.floorplan`` shape: room frame, mm) for the opening tests and golden cases.

A 3600 x 3000 room. Its first wall (z = 0, interior +z) is drawn as two collinear edges with two wall elements and a door hole between
x = 1000 and 1900; the right wall (x = 3600) is 200 mm thick, the others 100.
"""
from __future__ import annotations

import math
from typing import Any


def _wall(i: int, a: tuple[float, float], b: tuple[float, float], n: tuple[float, float], t: float, element: str) -> dict[str, Any]:
    return {"id": f"WALL-FP-{i + 1}", "edge": i, "thickness": t, "thicknessSource": "measured", "sourceElement": element, "height": 3000,
            "start": {"x": a[0], "y": 0, "z": a[1]}, "end": {"x": b[0], "y": 0, "z": b[1]}, "interiorNormal": {"x": n[0], "y": 0, "z": n[1]},
            "openings": []}


def _rect(x0: float, z0: float, x1: float, z1: float) -> list[dict[str, float]]:
    return [{"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1}, {"x": x0, "z": z1}]


def arc(hinge: tuple[float, float], radius: float, start_deg: float, end_deg: float, steps: int = 6) -> list[dict[str, float]]:
    """Swing polyline as the floorplan stores it: the hinge, then points on the arc."""
    pts = [{"x": hinge[0], "z": hinge[1]}]
    for k in range(steps + 1):
        a = math.radians(start_deg + (end_deg - start_deg) * k / steps)
        pts.append({"x": round(hinge[0] + radius * math.cos(a), 3), "z": round(hinge[1] + radius * math.sin(a), 3)})
    return pts


def room(door: dict[str, Any] | None = None, gap: tuple[float, float] = (1000.0, 1900.0)) -> dict[str, Any]:
    outline = [(0.0, 0.0), (1800.0, 0.0), (3600.0, 0.0), (3600.0, 3000.0), (0.0, 3000.0)]
    normals = [(0.0, 1.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (1.0, 0.0)]
    thick = [100.0, 100.0, 200.0, 100.0, 100.0]
    names = ["wall_001", "wall_002", "wall_003", "wall_004", "wall_005"]
    walls = [_wall(i, outline[i], outline[(i + 1) % 5], normals[i], thick[i], names[i]) for i in range(5)]
    elements: list[dict[str, Any]] = [
        {"id": "wall_001", "kind": "wall", "tag": "wall", "outline": _rect(-100.0, -100.0, gap[0], 0.0)},
        {"id": "wall_002", "kind": "wall", "tag": "wall", "outline": _rect(gap[1], -100.0, 3800.0, 0.0)},
    ]
    if door is not None:
        elements.append(door)
    return {"outline": [{"x": x, "z": z} for x, z in outline], "walls": walls, "elements": elements, "binding": None}


def door(offset: float = 1000.0, width: float = 900.0, radius: float = 840.0, height: float | None = 2100.0, hinge_at_start: bool = True,
         into_room: bool = True, element: str = "opening_001", tag: str = "door", wall: str = "WALL-FP-1") -> dict[str, Any]:
    """A door on the first edge (z = 0): hinge at the hole's start (x = offset) or end, sweeping into the room (+z) or out."""
    hx = offset if hinge_at_start else offset + width
    sign = 1.0 if into_room else -1.0
    start, end = (0.0, 90.0 * sign) if hinge_at_start else (180.0, 180.0 - 90.0 * sign)
    rec: dict[str, Any] = {"id": element, "kind": "opening", "tag": tag, "attached": {"wall": wall, "edge": 0, "offset": offset, "width": width},
                           "outline": _rect(offset, -100.0, offset + width, 0.0)}
    if tag == "door" and radius > 0:
        rec["hinge"] = {"x": hx, "z": 0.0}
        rec["swing"] = arc((hx, 0.0), radius, start, end)
    if height is not None:
        rec["elev"] = {"base": 0.0, "height": height}
    return rec
