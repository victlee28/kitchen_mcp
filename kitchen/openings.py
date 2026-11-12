"""The doors and windows of a kitchen's room in the kitchen frame (mm), for the checks that look at them (``rules_openings``).

Two sources: the openings of an imported floorplan (``floorplan.structures`` records of kind ``opening``, tag ``door`` / ``window``,
with the arc a door sweeps when the drawing has one) and the openings written on the walls of a design (``room.wall[].openings``).
An opening is a convex outline in the wall: ``along`` is the wall's direction, ``normal`` points across it.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .jsonview import as_dict, as_list
from .runs import Point, Seat

ToKitchen = Callable[[float, float], Point]


@dataclass(frozen=True)
class Opening:
    id: str
    tag: str                          # "door" | "window"
    outline: tuple[Point, ...]        # the opening in the wall, kitchen frame
    center: Point
    along: Point                      # unit vector along the wall
    normal: Point                     # unit vector across the wall
    width: float                      # along the wall, mm
    thick: float                      # across the wall, mm
    base: float                       # bottom (sill of a window, 0 for a door), mm above the floor
    height: float
    measured: bool                    # the height was drawn (False: the importer assumed one)
    swing: tuple[Point, ...] = ()     # a door: the floor area it sweeps (hinge, then the arc), kitchen frame

    def zone(self, depth: float, extra: float = 0.0) -> list[Point]:
        """The rectangle in front of and behind the opening: its width (plus ``extra`` each side) by the wall thickness plus ``depth``
        each side."""
        (cx, cz), (ax, az), (nx, nz) = self.center, self.along, self.normal
        a, n = self.width / 2 + extra, self.thick / 2 + depth
        return [(cx + sa * a * ax + sn * n * nx, cz + sa * a * az + sn * n * nz) for sa, sn in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def _frame(poly: list[Point]) -> tuple[Point, Point, Point, float, float]:
    """(center, along, normal, width, thick) of a roughly rectangular outline: ``along`` is its longest edge."""
    best = (0.0, (1.0, 0.0))
    for i, (x0, z0) in enumerate(poly):
        x1, z1 = poly[(i + 1) % len(poly)]
        ln = ((x1 - x0) ** 2 + (z1 - z0) ** 2) ** 0.5
        if ln > best[0]:
            best = (ln, ((x1 - x0) / ln, (z1 - z0) / ln))
    ax, az = best[1]
    nx, nz = -az + 0.0, ax + 0.0           # + 0.0: no negative zero
    ss = [x * ax + z * az for x, z in poly]
    dd = [x * nx + z * nz for x, z in poly]
    s, d = (min(ss) + max(ss)) / 2, (min(dd) + max(dd)) / 2
    return (s * ax + d * nx, s * az + d * nz), (ax, az), (nx, nz), max(ss) - min(ss), max(dd) - min(dd)


def from_structures(structures: Iterable[Mapping[str, Any]], to_kitchen: ToKitchen) -> list[Opening]:
    """The doors and windows of an imported floorplan (``floorplan.structures`` records; outlines in the room frame)."""
    out: list[Opening] = []
    for st in structures:
        tag = str(st.get("tag") or "")
        if st.get("kind") != "opening" or tag not in ("door", "window"):
            continue
        poly = [to_kitchen(float(p["x"]), float(p["z"])) for p in (as_dict(q) or {} for q in as_list(st.get("outline")) or [])]
        if len(poly) < 3:
            continue
        center, along, normal, width, thick = _frame(poly)
        hinge = as_dict(st.get("hinge"))
        arc = [as_dict(q) or {} for q in as_list(st.get("swing")) or []]
        swing = (tuple([to_kitchen(float(hinge["x"]), float(hinge["z"]))] + [to_kitchen(float(p["x"]), float(p["z"])) for p in arc])
                 if hinge is not None and len(arc) >= 2 and tag == "door" else ())
        out.append(Opening(str(st.get("sourceElement") or st.get("id") or ""), tag, tuple(poly), center, along, normal, width, thick,
                           float(st.get("base") or 0.0), float(st.get("height") or 0.0), st.get("heightSource") == "measured", swing))
    return out


def from_room(room: Mapping[str, Any], seat_of: Callable[[str], Seat | None]) -> list[Opening]:
    """The openings written on the walls of a design (``room`` as JSON; ``seat_of(wall)`` its seat in the kitchen frame). An
    ``entrance`` is a door; the wall's thickness is the opening's."""
    out: list[Opening] = []
    for w in (as_dict(x) or {} for x in as_list(room.get("wall")) or []):
        seat = seat_of(str(w.get("id")))
        if seat is None:
            continue
        thick = float(w.get("thickness") or 100.0)
        for i, o in enumerate(as_dict(x) or {} for x in as_list(w.get("openings")) or []):
            s0 = float(o.get("fromCorner") or 0.0)
            s1 = s0 + float(o.get("width") or 0.0)
            poly = [seat.to_world(s0, -thick), seat.to_world(s1, -thick), seat.to_world(s1, 0.0), seat.to_world(s0, 0.0)]
            center, along, normal, width, depth = _frame(poly)
            door = o.get("type") == "entrance"
            out.append(Opening(f"{w.get('id')}-O{i + 1}", "door" if door else "window", tuple(poly), center, along, normal, width, depth,
                               0.0 if door else float(o.get("sillHeight") or 0.0), float(o.get("height") or 0.0), True))
    return out


def hull(points: Iterable[Point]) -> list[Point]:
    """Convex hull, counter-clockwise (monotone chain); fewer than three distinct points: those points."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts
    def turn(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]
