"""Wall surfaces: every flat face of every wall, with a stable id, the room it looks into and the holes the design's openings cut in it.

A wall is a prism: its floor outline (a box's four corners, or any polygon a floorplan draws) between two heights. Its faces are one side
per outline edge, the top and the bottom. Ids (``<wall>#<face>``) come from the wall's own data, so they stay the same from revision to
revision while the floorplan does not change, whatever the openings cut out of the wall:

* a four-sided wall (long sides clearly longer than the ends): ``inside`` / ``outside`` when exactly one long side looks into the kitchen
  room, else ``side-a`` (the long side whose outward normal points along +x, or +z) / ``side-b``; ``start`` / ``end`` for the short sides,
  ``start`` lying first along the long sides (towards -x, or -z); ``top``, ``bottom``;
* any other outline: ``e<k>`` for the side on edge k of the outline as given; ``top``, ``bottom``;
* ``reveal-<opening>``: the inside of the hole an opening of the design cuts through the wall (its jambs, its head and, above the floor,
  its sill), one face per hole, so the reveal can be finished on its own. It is drawn as ``quads`` (each four corners facing into the
  hole) and found in a picture by ``span`` (the hole's box: along the opening's axis, its heights and half the wall's thickness).

``room``: the room a side looks into: where most of ten points 50 mm in front of it, spread along it, fall; ``None`` when none falls in a
room (the top, the bottom and the ends of a wall too). Rooms come from the data only, nothing is guessed (plan ``claude/ke-hoach-chon-mat-tuong``).

Pure plane math (rule R1); frame and units are the caller's (mm, x / z on the floor, y up).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .numeric import round_half_away

Pt = tuple[float, float]
Pt3 = tuple[float, float, float]
LOOK_MM = 50.0              # how far in front of a side its room is looked for
DIR_EPS = math.sin(math.radians(0.5))
END_RATIO = 1.5             # a four-sided wall is a "box" when its long sides are at least this much longer than its ends
COLLINEAR_DEG = 1.0
HOLE_REACH_MM = 60.0        # a hole cuts a side lying within half the wall's thickness plus this of the opening's wall axis


@dataclass(frozen=True)
class Hole:
    """An opening's hole: ``s`` from ``e0`` to ``e1`` along the line through ``start`` with unit direction ``dir``, heights ``y0``-``y1``;
    it cuts the sides parallel to the line lying within ``reach`` of it."""
    start: Pt
    dir: Pt
    e0: float
    e1: float
    y0: float
    y1: float
    reach: float
    id: str = ""                    # the opening's id: names its reveal face


@dataclass(frozen=True)
class Span:
    """The box of a hole (a reveal face): ``s`` from ``e0`` to ``e1`` along the line through ``start`` with unit direction ``dir``, heights
    ``y0``-``y1``, ``half`` of the wall's thickness on each side of the line."""
    start: Pt
    dir: Pt
    e0: float
    e1: float
    y0: float
    y1: float
    half: float

    def to_data(self) -> dict[str, Any]:
        return {"start": list(self.start), "dir": list(self.dir), "e0": self.e0, "e1": self.e1, "y0": self.y0, "y1": self.y1, "half": self.half}


@dataclass(frozen=True)
class Surface:
    id: str
    wall: str                       # the wall's own id (floorplan element, or WALL-BACK / WALL-RIGHT / WALL-LEFT)
    structure: str | None           # the scene structure drawing it (STRUCT-...), None for a default wall
    face: str
    normal: Pt3
    origin: Pt3                     # sides: the bottom-left corner seen from in front of the face; top / bottom: (0, y, 0)
    u: Pt                           # sides: unit direction along the floor, to the right seen from in front; caps: (1, 0)
    width: float                    # sides only
    height: float                   # sides only
    outline: tuple[Pt, ...]         # caps only: the floor outline at height origin.y
    holes: tuple[tuple[float, float, float, float], ...]     # sides only: (u0, u1, v0, v1), v up from the bottom of the face
    room: str | None
    opening: str | None = None      # reveals only: the opening whose hole it lines
    span: Span | None = None        # reveals only
    quads: tuple[tuple[Pt3, Pt3, Pt3, Pt3], ...] = ()       # reveals only: each piece, corners counter-clockwise seen from inside the hole

    def to_data(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "wall": self.wall, "face": self.face, "normal": list(self.normal), "room": self.room}
        if self.structure:
            out["structure"] = self.structure
        if self.span is not None:
            out.update(opening=self.opening, span=self.span.to_data(), quads=[[list(p) for p in q] for q in self.quads])
        elif self.outline:
            out.update(y=self.origin[1], outline=[{"x": p[0], "z": p[1]} for p in self.outline])
        else:
            out.update(origin=list(self.origin), u=list(self.u), width=self.width, height=self.height,
                       holes=[list(h) for h in self.holes])
        return out


@dataclass(frozen=True)
class FaceRef:
    """A wall face as the render splits it out of its wall (id ``<wall>#<face>``): the parts it lies on (a default wall's box by its
    ``wall``, a floorplan wall's meshes by their structure id), its outward normal and a point of its plane (kitchen frame, mm)."""
    id: str
    face: str
    wall: str | None
    structure: str | None
    normal: Pt3
    point: Pt3
    room: str | None = None
    span: tuple[float, float, float, float, float, float, float, float, float] | None = None
    """A reveal: its hole's box (start x, start z, dir x, dir z, e0, e1, y0, y1, half; kitchen frame, mm); the face is then found by
    that box, not by a plane."""


def face_part_id(part_id: str, face: str) -> str:
    """The instance (and layer part) id of one wall part's share of a face."""
    return f"{part_id}#{face}"


def face_owner(p: Any, fc: Any) -> bool:
    """Does part ``p`` (a scene part or mesh: ``type``, ``module``, ``wall``) draw the wall ``fc`` (``wall`` / ``structure``) is a face of."""
    return bool((fc.wall is not None and p.type == "wall" and getattr(p, "wall", None) == fc.wall)
                or (fc.structure is not None and p.module == fc.structure and str(p.type).startswith("structure-")))


def _r(v: float) -> float:
    out = round_half_away(v, 1)
    return out + 0.0 if out != 0 else 0.0


def _signed_area(poly: Sequence[Pt]) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, [*poly[1:], poly[0]])) / 2


def inside(p: Pt, poly: Sequence[Pt]) -> bool:
    """Even-odd test (a point on the boundary may fall either way)."""
    hit = False
    for a, b in zip(poly, [*poly[1:], poly[0]]):
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if p[0] < x:
                hit = not hit
    return hit


def room_at(p: Pt, rooms: Sequence[tuple[str, Sequence[Pt]]]) -> str | None:
    """The first room (``(id, outline)``, in the order given) holding ``p``."""
    return next((rid for rid, poly in rooms if len(poly) >= 3 and inside(p, poly)), None)


SAMPLES = 10


def _facing(a: Pt, u: Pt, n: Pt, length: float, rooms: Sequence[tuple[str, Sequence[Pt]]]) -> str | None:
    """The room a side looks into: of ``SAMPLES`` points ``LOOK_MM`` in front of it, spread along it, the room most of them fall in (a long
    wall may look into a room along part of its length only); ties go to the room listed first."""
    count: dict[str, int] = {}
    for i in range(SAMPLES):
        t = length * (i + 0.5) / SAMPLES
        rid = room_at((a[0] + u[0] * t + n[0] * LOOK_MM, a[1] + u[1] * t + n[1] * LOOK_MM), rooms)
        if rid is not None:
            count[rid] = count.get(rid, 0) + 1
    order = [rid for rid, _ in rooms]
    return max(count, key=lambda r: (count[r], -order.index(r)), default=None)


def _canonical(d: Pt) -> bool:
    return d[0] > DIR_EPS or (abs(d[0]) <= DIR_EPS and d[1] > 0)


def _hole_rects(a: Pt, u: Pt, n: Pt, length: float, y0: float, y1: float, holes: Sequence[Hole]) -> tuple[tuple[float, float, float, float], ...]:
    out: list[tuple[float, float, float, float]] = []
    for h in holes:
        if abs(u[0] * h.dir[1] - u[1] * h.dir[0]) > math.sin(math.radians(COLLINEAR_DEG)):
            continue
        off = (a[0] - h.start[0]) * -h.dir[1] + (a[1] - h.start[1]) * h.dir[0]       # the side's distance from the hole's line
        if abs(off) > h.reach:
            continue
        ends = [(h.start[0] + h.dir[0] * e - a[0]) * u[0] + (h.start[1] + h.dir[1] * e - a[1]) * u[1] for e in (h.e0, h.e1)]
        u0, u1 = max(0.0, min(ends)), min(length, max(ends))
        v0, v1 = max(0.0, h.y0 - y0), min(y1 - y0, h.y1 - y0)
        if u1 - u0 > 1.0 and v1 - v0 > 1.0:
            out.append((_r(u0), _r(u1), _r(v0), _r(v1)))
    return tuple(sorted(out))


def of_wall(wall: str, outline: Sequence[Pt], y0: float, y1: float, rooms: Sequence[tuple[str, Sequence[Pt]]] = (),
            kitchen: str | None = None, holes: Sequence[Hole] = (), structure: str | None = None) -> list[Surface]:
    """The faces of one wall (see the module notes)."""
    poly = [(float(x), float(z)) for x, z in outline]
    if len(poly) > 1 and poly[0] == poly[-1]:
        poly = poly[:-1]
    if len(poly) < 3 or y1 <= y0 or abs(_signed_area(poly)) < 1.0:
        return []
    n_pts = len(poly)
    sides: list[dict[str, Any]] = []
    for k in range(n_pts):
        a, b = poly[k], poly[(k + 1) % n_pts]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length < 1.0:
            continue
        u = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
        n = (u[1], -u[0])
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if inside((mid[0] + n[0], mid[1] + n[1]), poly):
            n = (-n[0], -n[1])                                   # outward
        if u[0] * n[1] - u[1] * n[0] < 0:                        # u runs to the right of someone facing the side: (n.z, -n.x)
            a, u = b, (-u[0], -u[1])
        sides.append({"k": k, "a": a, "u": u, "n": n, "len": length, "mid": mid, "room": _facing(a, u, n, length, rooms)})
    names = {s["k"]: f"e{s['k']}" for s in sides}
    if n_pts == 4 and len(sides) == 4:
        by_len = sorted(sides, key=lambda s: -s["len"])
        longs, ends = by_len[:2], by_len[2:]
        parallel = abs(longs[0]["u"][0] * longs[1]["u"][1] - longs[0]["u"][1] * longs[1]["u"][0]) < math.sin(math.radians(COLLINEAR_DEG))
        if parallel and longs[1]["len"] >= END_RATIO * ends[0]["len"]:
            facing = [s for s in longs if kitchen is not None and s["room"] == kitchen]
            if len(facing) == 1:
                names[facing[0]["k"]] = "inside"
                names[next(s for s in longs if s is not facing[0])["k"]] = "outside"
            else:
                first = next((s for s in longs if _canonical(s["n"])), longs[0])
                names[first["k"]] = "side-a"
                names[next(s for s in longs if s is not first)["k"]] = "side-b"
            d = longs[0]["u"] if _canonical(longs[0]["u"]) else (-longs[0]["u"][0], -longs[0]["u"][1])
            ends_sorted = sorted(ends, key=lambda s: s["mid"][0] * d[0] + s["mid"][1] * d[1])
            names[ends_sorted[0]["k"]], names[ends_sorted[1]["k"]] = "start", "end"
    out: list[Surface] = []
    for s in sides:
        face = names[s["k"]]
        is_end = face in ("start", "end")
        out.append(Surface(f"{wall}#{face}", wall, structure, face, (round_half_away(s["n"][0], 6) + 0.0, 0.0, round_half_away(s["n"][1], 6) + 0.0),
                           (_r(s["a"][0]), _r(y0), _r(s["a"][1])), (round_half_away(s["u"][0], 6) + 0.0, round_half_away(s["u"][1], 6) + 0.0),
                           _r(s["len"]), _r(y1 - y0), (), _hole_rects(s["a"], s["u"], s["n"], s["len"], y0, y1, holes),
                           None if is_end else s["room"]))
    for k, h in enumerate(holes):                                # the inside of each hole that cuts a side of this wall
        if any(_hole_rects(s["a"], s["u"], s["n"], s["len"], y0, y1, [h]) for s in sides):
            rv = reveal(wall, structure, h, y0, y1, k)
            if rv is not None:
                out.append(rv)
    caps = tuple((_r(x), _r(z)) for x, z in poly)
    out.append(Surface(f"{wall}#top", wall, structure, "top", (0.0, 1.0, 0.0), (0.0, _r(y1), 0.0), (1.0, 0.0), 0.0, 0.0, caps, (), None))
    out.append(Surface(f"{wall}#bottom", wall, structure, "bottom", (0.0, -1.0, 0.0), (0.0, _r(y0), 0.0), (1.0, 0.0), 0.0, 0.0, caps, (), None))
    return out


def reveal_face(opening_id: str, k: int = 0) -> str:
    """The face name of a hole's reveal: ``reveal-<opening id>`` (lower case, as surface ids are), ``reveal-<k>`` for a hole with no id."""
    tail = "".join(c if c.isascii() and c.isalnum() else "-" for c in opening_id.lower())[:13] if opening_id else str(k)
    return f"reveal-{tail}"


def reveal(wall: str, structure: str | None, h: Hole, y0: float, y1: float, k: int = 0) -> Surface | None:
    """The reveal of hole ``h`` in a wall standing from ``y0`` to ``y1``: its two jambs, its head (below the top of the wall) and its sill
    (above the bottom), each a quad facing into the hole; None for a hole with no height or width left."""
    half = max(1.0, h.reach - HOLE_REACH_MM)
    ya, yb = max(h.y0, y0), min(h.y1, y1)
    if yb - ya <= 1.0 or h.e1 - h.e0 <= 1.0:
        return None
    d, n = h.dir, (-h.dir[1], h.dir[0])

    def at(s: float, c: float, y: float) -> Pt3:
        return (_r(h.start[0] + d[0] * s + n[0] * c), _r(y), _r(h.start[1] + d[1] * s + n[1] * c))

    def quad(pts: tuple[Pt3, Pt3, Pt3, Pt3], facing: Pt3) -> tuple[Pt3, Pt3, Pt3, Pt3]:
        a, b, c = pts[0], pts[1], pts[2]
        e1, e2 = (b[0] - a[0], b[1] - a[1], b[2] - a[2]), (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        cross = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
        return pts if sum(x * f for x, f in zip(cross, facing)) >= 0 else (pts[0], pts[3], pts[2], pts[1])

    quads: list[tuple[Pt3, Pt3, Pt3, Pt3]] = []
    for s_, sign in ((h.e0, 1.0), (h.e1, -1.0)):          # jambs: facing along the axis, into the hole
        quads.append(quad((at(s_, -half, ya), at(s_, half, ya), at(s_, half, yb), at(s_, -half, yb)), (d[0] * sign, 0.0, d[1] * sign)))
    if yb < y1 - 1.0:                                     # head: facing down
        quads.append(quad((at(h.e0, -half, yb), at(h.e1, -half, yb), at(h.e1, half, yb), at(h.e0, half, yb)), (0.0, -1.0, 0.0)))
    if ya > y0 + 1.0:                                     # sill: facing up
        quads.append(quad((at(h.e0, -half, ya), at(h.e1, -half, ya), at(h.e1, half, ya), at(h.e0, half, ya)), (0.0, 1.0, 0.0)))
    face = reveal_face(h.id, k)
    normal = (round_half_away(n[0], 6) + 0.0, 0.0, round_half_away(n[1], 6) + 0.0)
    span = Span((_r(h.start[0]), _r(h.start[1])), (round_half_away(d[0], 6) + 0.0, round_half_away(d[1], 6) + 0.0), _r(h.e0), _r(h.e1),
                _r(ya), _r(yb), _r(half))
    return Surface(f"{wall}#{face}", wall, structure, face, normal, (0.0, _r(ya), 0.0), (1.0, 0.0), 0.0, 0.0, (), (), None,
                   h.id or None, span, tuple(quads))


def box_outline(start: Pt, end: Pt, inward: Pt, thickness: float) -> list[Pt]:
    """The floor outline of a default wall: its inner face from ``start`` to ``end``, ``thickness`` away from the room (``inward``)."""
    back = (-inward[0] * thickness, -inward[1] * thickness)
    return [start, end, (end[0] + back[0], end[1] + back[1]), (start[0] + back[0], start[1] + back[1])]
