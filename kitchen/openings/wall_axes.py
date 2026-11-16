"""Wall axes: the centreline of a whole straight wall, the line every room opening is measured along (ADR 0005, plan §2.1).

* Floorplan (room frame, mm): one axis per run of collinear edges of the room outline. The centreline lies half the wall's thickness
  behind the inner face. An end that meets another wall is the crossing of the two centrelines (the way drawings place their grid
  axes); the room outline is closed, so every end meets a wall.
* A wall that runs on straight past the room's corner, into another room (the floorplan's wall elements), carries its axis with it
  (``extend``): collinear wall pieces (within 1 degree, centrelines apart by at most half the thinner wall) that touch, or are apart by
  at most 2400 mm with an opening element in the gap or with the same thickness, join the axis. Its new end is the crossing with the
  wall it runs into, else the end of the last piece. The axis keeps its id (the room edges it holds); only ``start`` and ``length``
  move, and records placed on the shorter axis follow it (``moved_along``).
* Walls of the floorplan that no room axis holds (other rooms' walls, picked to put a door in them) get axes of their own, after the
  room's: each runs along a chain of collinear wall pieces joined the same way (``other_axes``); its id is ``WA-`` + its first
  piece, its ``inward`` is 0 (no kitchen side).
* Direction: the unit vector ``dir`` points along +x, or along +z when the axis runs along z; the start is the end it points away
  from. The normal ``(-dir.z, dir.x)`` names the ``+`` side.
* No floorplan (kitchen frame): the three walls ``back``, ``right``, ``left`` start at the back-right corner (the kitchen origin),
  because their lengths may follow the cabinets: the back axis runs towards -x, the side axes towards +z.

Pure plane math (rule R1).
"""
from __future__ import annotations

from ..numeric import round_half_away

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..jsonview import as_dict, as_list
from .contract import AxisRef, Pt

COLLINEAR_DEG = 1.0          # edges turning less than this form one straight wall
DIR_EPS = math.sin(math.radians(0.5))
FINGERPRINT_MM = 20.0        # a stored axis whose start or length moved more than this no longer matches
FINGERPRINT_DEG = 0.5
JOIN_GAP_MM = 2400.0         # the widest gap between two collinear wall pieces that still makes one wall
TOUCH_MM = 5.0
EXTEND_MIN_MM = 300.0        # an axis reaching less than this past the room's corner is only the corner wall's thickness: kept as it is
SAME_THICKNESS_MM = 1.0


@dataclass(frozen=True)
class Segment:
    s0: float
    s1: float
    thickness: float
    source: str              # floorplan wall element (or the WALL-FP id when the edge has none), or back / right / left
    wall: str = ""           # the floorplan wall record (WALL-FP-n) or back / right / left
    face_start: Pt = (0.0, 0.0)   # inner face: where its own offsets start (the room edge's first point; a default wall's inner corner)
    face_dir: Pt = (1.0, 0.0)     # inner face: the way its own offsets grow


@dataclass(frozen=True)
class WallAxis:
    id: str
    start: Pt
    dir: Pt
    length: float
    segments: tuple[Segment, ...]
    inward: int                  # +1: the + side faces the kitchen; -1: the - side does; 0: unknown
    frame: str                   # "room" (floorplan) | "kitchen" (the three default walls)

    @property
    def normal(self) -> Pt:
        return (-self.dir[1] + 0.0, self.dir[0] + 0.0)

    def point(self, s: float, d: float = 0.0) -> Pt:
        n = self.normal
        return (self.start[0] + self.dir[0] * s + n[0] * d, self.start[1] + self.dir[1] * s + n[1] * d)

    def s_of(self, p: Pt) -> float:
        return (p[0] - self.start[0]) * self.dir[0] + (p[1] - self.start[1]) * self.dir[1]

    def d_of(self, p: Pt) -> float:
        n = self.normal
        return (p[0] - self.start[0]) * n[0] + (p[1] - self.start[1]) * n[1]

    def thickness_at(self, s: float) -> float:
        """Thickness of the wall segment holding ``s`` (the nearest segment when ``s`` falls between two)."""
        best = min(self.segments, key=lambda g: 0.0 if g.s0 - 1e-6 <= s <= g.s1 + 1e-6 else min(abs(s - g.s0), abs(s - g.s1)))
        return best.thickness

    def sources(self) -> tuple[str, ...]:
        return tuple(g.source for g in self.segments)

    def ref(self) -> AxisRef:
        if self.frame != "room":
            return AxisRef(self.id)
        return AxisRef(self.id, (_r(self.start[0], 1), _r(self.start[1], 1)), (_r(self.dir[0], 6), _r(self.dir[1], 6)), _r(self.length, 1))

    def in_kitchen(self, to_kitchen: Any) -> "WallAxis":
        """The same axis in the kitchen frame (``to_kitchen(x, z) -> (x, z)``: a rotation and a shift, never a mirror)."""
        if self.frame == "kitchen":
            return self
        a = to_kitchen(self.start[0], self.start[1])
        b = to_kitchen(self.start[0] + self.dir[0], self.start[1] + self.dir[1])
        return WallAxis(self.id, (float(a[0]), float(a[1])), (float(b[0]) - float(a[0]), float(b[1]) - float(a[1])), self.length, self.segments,
                        self.inward, "kitchen")


def _r(v: float, digits: int) -> float:
    out = round_half_away(v, digits)
    return out + 0.0 if out != 0 else 0.0


def _unit(a: Pt, b: Pt) -> Pt:
    dx, dz = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dz)
    return (dx / ln, dz / ln) if ln > 0 else (1.0, 0.0)


def canonical(d: Pt) -> bool:
    """Is ``d`` already the direction an axis runs (towards +x, or +z when it runs along z)?"""
    return d[0] > DIR_EPS or (abs(d[0]) <= DIR_EPS and d[1] > 0)


def _cross_lines(p: Pt, d: Pt, q: Pt, e: Pt) -> Pt | None:
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return (p[0] + d[0] * t, p[1] + d[1] * t)


def _angle(d: Pt, e: Pt) -> float:
    c = max(-1.0, min(1.0, d[0] * e[0] + d[1] * e[1]))
    return math.degrees(math.acos(c))


@dataclass(frozen=True)
class Piece:
    """A floorplan element as a straight box: centreline from ``a`` to ``b`` (unit ``d``), ``thickness`` across."""
    id: str
    a: Pt
    b: Pt
    d: Pt
    thickness: float


def _piece(e: Mapping[str, Any], turned: bool = False) -> Piece | None:
    """The element as a straight box along its longest side (``turned``: along the side square to it, for a stub as thick as long)."""
    pts = [(float(p["x"]), float(p["z"])) for p in (as_dict(q) or {} for q in as_list(e.get("outline")) or []) if "x" in p and "z" in p]
    if len(pts) < 3:
        return None
    k = max(range(len(pts)), key=lambda i: math.hypot(pts[(i + 1) % len(pts)][0] - pts[i][0], pts[(i + 1) % len(pts)][1] - pts[i][1]))
    d = _unit(pts[k], pts[(k + 1) % len(pts)])
    if turned:
        d = (-d[1] + 0.0, d[0] + 0.0)
    if not canonical(d):
        d = (-d[0] + 0.0, -d[1] + 0.0)
    n = (-d[1], d[0])
    along = [p[0] * d[0] + p[1] * d[1] for p in pts]
    across = [p[0] * n[0] + p[1] * n[1] for p in pts]
    mid = (min(across) + max(across)) / 2
    t = max(across) - min(across)

    def at(s: float) -> Pt:
        return (d[0] * s + n[0] * mid, d[1] * s + n[1] * mid)
    return Piece(str(e.get("id") or ""), at(min(along)), at(max(along)), d, t)


STUB_RATIO = 2.0              # a wall piece less than this many times longer than thick is a stub: which way it runs is not plain


def _length(p: Piece) -> float:
    return math.hypot(p.b[0] - p.a[0], p.b[1] - p.a[1])


def _lines_up(p: Piece, q: Piece) -> bool:
    """Does ``p`` run on along ``q``'s centreline and touch its end (a stub beside a door: the wall the door is in)?"""
    if _angle(p.d, q.d) > COLLINEAR_DEG or _offset(p, q.a, q.d) > max(p.thickness, q.thickness) / 2 + TOUCH_MM:
        return False
    s0, s1 = _span(p, q.a, q.d)
    q0, q1 = _span(q, q.a, q.d)
    return s0 <= q1 + TOUCH_MM and s1 >= q0 - TOUCH_MM


def wall_pieces(fp: Mapping[str, Any]) -> list[Piece]:
    """The floorplan's wall elements as straight boxes (an element clearly longer than thick). A stub (about as long as thick, e.g. the
    short bit of wall beside a door) runs the way of the door it touches, even when it is thicker than long; a stub touching no door
    keeps its longest side, as any wall piece."""
    elements = [e for e in (as_dict(x) or {} for x in as_list(fp.get("elements")) or [])]
    doors = opening_pieces(fp)
    out: list[Piece] = []
    for e in elements:
        if e.get("kind") != "wall":
            continue
        p = _piece(e)
        if p is None:
            continue
        if _length(p) < STUB_RATIO * p.thickness:
            turned = _piece(e, turned=True)
            if turned is not None and any(_lines_up(turned, o) for o in doors):
                out.append(turned)
                continue
        if _length(p) > p.thickness:
            out.append(p)
    return out


def opening_pieces(fp: Mapping[str, Any]) -> list[Piece]:
    return [p for p in (_piece(e) for e in (as_dict(x) or {} for x in as_list(fp.get("elements")) or []) if e.get("kind") == "opening")
            if p is not None]


def _span(p: Piece, start: Pt, d: Pt) -> tuple[float, float]:
    s0 = (p.a[0] - start[0]) * d[0] + (p.a[1] - start[1]) * d[1]
    s1 = (p.b[0] - start[0]) * d[0] + (p.b[1] - start[1]) * d[1]
    return (min(s0, s1), max(s0, s1))


def _offset(p: Piece, start: Pt, d: Pt) -> float:
    mid = ((p.a[0] + p.b[0]) / 2, (p.a[1] + p.b[1]) / 2)
    return abs((mid[0] - start[0]) * -d[1] + (mid[1] - start[1]) * d[0])


def extend(a: Pt, b: Pt, d: Pt, thickness: float, pieces: Sequence[Piece], gaps: Sequence[Piece] = ()) -> tuple[Pt, Pt]:
    """The ends of an axis (``a`` -> ``b`` along ``d``, the room's own extent) once the collinear wall pieces of the floorplan that
    continue it have joined: ``(a, b)`` unchanged when the wall stops at the room's corners."""
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    along = [(p, *_span(p, a, d)) for p in pieces
             if _angle(p.d, d) <= COLLINEAR_DEG and _offset(p, a, d) <= min(p.thickness, thickness) / 2 + TOUCH_MM]
    holes = [_span(o, a, d) for o in gaps if _offset(o, a, d) <= thickness / 2 + max(o.thickness, thickness)]
    lo, hi = 0.0, length
    joined: list[Piece] = []
    grew = True
    while grew:
        grew = False
        for p, s0, s1 in along:
            if p in joined:
                continue
            gap = max(s0 - hi, lo - s1, 0.0)
            if gap > TOUCH_MM:
                gap_lo, gap_hi = (hi, s0) if s0 > hi else (s1, lo)
                door = any(h0 < gap_hi and h1 > gap_lo for h0, h1 in holes)
                if gap > JOIN_GAP_MM or not (door or abs(p.thickness - thickness) <= SAME_THICKNESS_MM):
                    continue
            joined.append(p)
            if s0 < lo or s1 > hi:
                lo, hi, grew = min(lo, s0), max(hi, s1), True
    new_lo = lo if lo < -EXTEND_MIN_MM else 0.0
    new_hi = hi if hi > length + EXTEND_MIN_MM else length

    def end(s: float) -> Pt:
        """The far end at ``s``: the crossing with the centreline of the wall it runs into, else the end of its last piece."""
        p = (a[0] + d[0] * s, a[1] + d[1] * s)
        best: tuple[float, Pt] | None = None
        for q in pieces:
            if _angle(q.d, d) <= COLLINEAR_DEG or not _near_box(q, p, thickness / 2 + TOUCH_MM):
                continue
            c = _cross_lines(a, d, q.a, q.d)
            if c is None:
                continue
            gap = abs((c[0] - a[0]) * d[0] + (c[1] - a[1]) * d[1] - s)
            if gap <= q.thickness / 2 + thickness and (best is None or gap < best[0]):
                best = (gap, c)
        return best[1] if best is not None else p
    return (end(new_lo) if new_lo != 0.0 else a), (end(new_hi) if new_hi != length else b)


def _near_box(q: Piece, p: Pt, reach: float) -> bool:
    """Is ``p`` inside the piece's box grown by ``reach``?"""
    s0, s1 = _span(q, q.a, q.d)
    s = (p[0] - q.a[0]) * q.d[0] + (p[1] - q.a[1]) * q.d[1]
    off = abs((p[0] - q.a[0]) * -q.d[1] + (p[1] - q.a[1]) * q.d[0])
    return s0 - reach <= s <= s1 + reach and off <= q.thickness / 2 + reach


def moved_along(ref: AxisRef, axis: WallAxis) -> float | None:
    """When a stored fingerprint describes a stretch of ``axis`` (same direction, its start on the same centreline, the old axis lying
    within the new one: the wall now runs on into another room), how far the old start lies along the new axis; else None."""
    if ref.start is None or ref.dir is None or axis.frame != "room":
        return None
    if _angle(_unit((0.0, 0.0), ref.dir), axis.dir) > FINGERPRINT_DEG or abs(axis.d_of(ref.start)) > FINGERPRINT_MM:
        return None
    shift = axis.s_of(ref.start)
    old_length = ref.length if ref.length is not None else 0.0
    if shift < -FINGERPRINT_MM or shift + old_length > axis.length + FINGERPRINT_MM:
        return None
    return shift


def from_floorplan(fp: Mapping[str, Any]) -> list[WallAxis]:
    """The wall axes around the imported room (``spec.floorplan``: its ``outline`` and per-edge ``walls``), room frame."""
    outline = [(float(p["x"]), float(p["z"])) for p in (as_dict(q) or {} for q in as_list(fp.get("outline")) or []) if "x" in p and "z" in p]
    n = len(outline)
    if n < 3:
        return []
    walls = {int(w.get("edge", i)): w for i, w in enumerate(as_dict(x) or {} for x in as_list(fp.get("walls")) or [])}
    edges: list[dict[str, Any]] = []
    for i in range(n):
        a, b = outline[i], outline[(i + 1) % n]
        w = walls.get(i, {})
        nrm = as_dict(w.get("interiorNormal")) or {}
        d = _unit(a, b)
        ni = (float(nrm.get("x", -d[1])), float(nrm.get("z", d[0])))
        t = float(w.get("thickness") or 100.0)
        src = str(w.get("sourceElement") or w.get("id") or f"edge-{i}")
        edges.append({"a": a, "b": b, "d": d, "n": ni, "t": t, "len": math.hypot(b[0] - a[0], b[1] - a[1]), "src": src,
                      "wall": str(w.get("id") or f"edge-{i}")})
    # group consecutive collinear edges, starting after a turn so a run never wraps through index 0 split in two
    first = next((i for i in range(n) if _angle(edges[i - 1]["d"], edges[i]["d"]) > COLLINEAR_DEG), 0)
    groups: list[list[int]] = []
    for k in range(n):
        i = (first + k) % n
        if groups and _angle(edges[groups[-1][-1]]["d"], edges[i]["d"]) <= COLLINEAR_DEG:
            groups[-1].append(i)
        else:
            groups.append([i])
    lines: list[tuple[Pt, Pt]] = []                  # centreline (point, dir) of each group, from its longest edge
    for g in groups:
        e = max((edges[i] for i in g), key=lambda x: x["len"])
        lines.append(((e["a"][0] - e["n"][0] * e["t"] / 2, e["a"][1] - e["n"][1] * e["t"] / 2), e["d"]))
    pieces, gaps = wall_pieces(fp), opening_pieces(fp)
    out: list[WallAxis] = []
    used: dict[str, int] = {}
    m = len(groups)
    for gi, g in enumerate(groups):
        p, d = lines[gi]
        prev_p, prev_d = lines[gi - 1]
        next_p, next_d = lines[(gi + 1) % m]
        a = _cross_lines(p, d, prev_p, prev_d) if m > 1 else None
        b = _cross_lines(p, d, next_p, next_d) if m > 1 else None
        first_e, last_e = edges[g[0]], edges[g[-1]]
        if a is None:
            a = (first_e["a"][0] - first_e["n"][0] * first_e["t"] / 2, first_e["a"][1] - first_e["n"][1] * first_e["t"] / 2)
        if b is None:
            b = (last_e["b"][0] - last_e["n"][0] * last_e["t"] / 2, last_e["b"][1] - last_e["n"][1] * last_e["t"] / 2)
        dd = _unit(a, b)
        if not canonical(dd):
            a, b, dd = b, a, (-dd[0] + 0.0, -dd[1] + 0.0)
        if pieces:
            a, b = extend(a, b, dd, max(edges[i]["t"] for i in g), pieces, gaps)
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        ax = WallAxis("", a, dd, length, (), 0, "room")
        segs = sorted((Segment(min(ax.s_of(edges[i]["a"]), ax.s_of(edges[i]["b"])), max(ax.s_of(edges[i]["a"]), ax.s_of(edges[i]["b"])),
                               edges[i]["t"], edges[i]["src"], edges[i]["wall"], edges[i]["a"], edges[i]["d"]) for i in g), key=lambda s: s.s0)
        main = max((edges[i] for i in g), key=lambda x: x["len"])
        nrm = ax.normal
        inward = 1 if nrm[0] * main["n"][0] + nrm[1] * main["n"][1] > 0 else -1
        base = "WA-" + segs[0].source
        used[base] = used.get(base, 0) + 1
        out.append(WallAxis(base if used[base] == 1 else f"{base}-{used[base]}", (_r(a[0], 3), _r(a[1], 3)), (_r(dd[0], 9), _r(dd[1], 9)),
                            _r(length, 3), tuple(Segment(_r(s.s0, 3), _r(s.s1, 3), s.thickness, s.source, s.wall, s.face_start, s.face_dir) for s in segs), inward, "room"))
    out.extend(other_axes(pieces, gaps, out, {a.id for a in out}))
    return out


def _held(p: Piece, axis: WallAxis) -> bool:
    """Does a room axis already run along wall piece ``p``?"""
    if _angle(p.d, axis.dir) > COLLINEAR_DEG:
        return False
    mid = ((p.a[0] + p.b[0]) / 2, (p.a[1] + p.b[1]) / 2)
    if abs(axis.d_of(mid)) > min(min(g.thickness for g in axis.segments), p.thickness) / 2 + TOUCH_MM:
        return False
    s0, s1 = sorted((axis.s_of(p.a), axis.s_of(p.b)))
    return s1 > TOUCH_MM and s0 < axis.length - TOUCH_MM


def other_axes(pieces: Sequence[Piece], gaps: Sequence[Piece], room: Sequence[WallAxis], taken: set[str] | None = None) -> list[WallAxis]:
    """Axes of the floorplan's wall pieces that no room axis holds: one per chain of collinear pieces (``extend``'s joining rules),
    in the order of the pieces; ``inward`` 0."""
    free = [p for p in pieces if p.id and not any(_held(p, a) for a in room if a.segments)]
    used: set[str] = set(taken or ())
    done: set[str] = set()
    out: list[WallAxis] = []
    for seed in free:
        if seed.id in done:
            continue
        a, b = extend(seed.a, seed.b, seed.d, seed.thickness, [p for p in free if p.id not in done], gaps)
        dd = _unit(a, b)
        if not canonical(dd):
            a, b, dd = b, a, (-dd[0] + 0.0, -dd[1] + 0.0)
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length <= 0:
            continue
        probe = WallAxis("", a, dd, length, (Segment(0.0, length, seed.thickness, seed.id),), 0, "room")
        chain = [p for p in free if p.id not in done and (p is seed or _held(p, probe))]
        done.update(p.id for p in chain)
        segs = sorted((Segment(_r(max(0.0, min(probe.s_of(p.a), probe.s_of(p.b))), 3), _r(min(length, max(probe.s_of(p.a), probe.s_of(p.b))), 3),
                               p.thickness, p.id, p.id, p.a, p.d) for p in chain), key=lambda g: g.s0)
        base = "WA-" + seed.id
        name, k = base, 1
        while name in used:
            k += 1
            name = f"{base}-{k}"
        used.add(name)
        out.append(WallAxis(name, (_r(a[0], 3), _r(a[1], 3)), (_r(dd[0], 9), _r(dd[1], 9)), _r(length, 3), tuple(segs), 0, "room"))
    return out


def for_room(back_length: float, side_length: float, thickness: Mapping[str, float] | None = None) -> list[WallAxis]:
    """The three default walls of a design without a floorplan, kitchen frame (origin: inner back-right corner; the room is at
    x < 0, z > 0)."""
    t = {"back": 100.0, "right": 100.0, "left": 100.0, **{k: float(v) for k, v in (thickness or {}).items()}}
    tb, tr, tl = t["back"], t["right"], t["left"]
    back_len = back_length + tr / 2 + tl / 2
    side_len = side_length + tb / 2
    return [
        WallAxis("back", (tr / 2, -tb / 2), (-1.0, 0.0), back_len, (Segment(0.0, back_len, tb, "back", "back", (0.0, 0.0), (-1.0, 0.0)),), -1, "kitchen"),
        WallAxis("right", (tr / 2, -tb / 2), (0.0, 1.0), side_len, (Segment(0.0, side_len, tr, "right", "right", (0.0, 0.0), (0.0, 1.0)),), 1, "kitchen"),
        WallAxis("left", (-back_length - tl / 2, -tb / 2), (0.0, 1.0), side_len,
                 (Segment(0.0, side_len, tl, "left", "left", (-back_length, 0.0), (0.0, 1.0)),), -1, "kitchen"),
    ]


def for_spec(spec: Mapping[str, Any], back_length: float, side_length: float) -> list[WallAxis]:
    """Wall axes of a design (plain spec data): the floorplan's (room frame) when one is imported, else the three default walls
    (kitchen frame) with the thicknesses of ``room.wall``."""
    fp = as_dict(spec.get("floorplan"))
    if fp and as_list(fp.get("outline")):
        return from_floorplan(fp)
    room = as_dict(spec.get("room")) or {}
    thick = {str(w.get("id")): float(w.get("thickness") or 100.0) for w in (as_dict(x) or {} for x in as_list(room.get("wall")) or [])
             if w.get("id") in ("back", "right", "left")}
    return for_room(back_length, side_length, thick)


def segments_of(wall: str, axes: Sequence[WallAxis]) -> list[tuple[WallAxis, Segment]]:
    """Every axis segment of a floorplan wall record or wall element (``WALL-FP-n`` / its source element: one element may bound
    several room edges) or a default wall."""
    return [(a, g) for a in axes for g in a.segments if wall in (g.wall, g.source)]


def segment_of(wall: str, axes: Sequence[WallAxis]) -> tuple[WallAxis, Segment] | None:
    found = segments_of(wall, axes)
    return found[0] if found else None


def find(ref: AxisRef | Mapping[str, Any] | str, axes: Sequence[WallAxis]) -> WallAxis | None:
    rid = ref if isinstance(ref, str) else (ref.id if isinstance(ref, AxisRef) else str(ref.get("id") or ""))
    return next((a for a in axes if a.id == rid), None)


def matches(ref: AxisRef, axis: WallAxis) -> bool:
    """Does the stored fingerprint still describe ``axis``? (No fingerprint: yes.)"""
    if ref.start is not None and math.hypot(ref.start[0] - axis.start[0], ref.start[1] - axis.start[1]) > FINGERPRINT_MM:
        return False
    if ref.dir is not None and _angle(_unit((0.0, 0.0), ref.dir), axis.dir) > FINGERPRINT_DEG:
        return False
    if ref.length is not None and abs(ref.length - axis.length) > FINGERPRINT_MM:
        return False
    return True


def nearest(p: Pt, axes: Sequence[WallAxis], reach: float = 900.0) -> tuple[WallAxis, float] | None:
    """The axis closest to ``p`` (same frame), with ``p``'s position along it clamped to the axis; None beyond ``reach`` mm."""
    best: tuple[float, WallAxis, float] | None = None
    for a in axes:
        s = max(0.0, min(a.length, a.s_of(p)))
        q = a.point(s)
        dist = math.hypot(p[0] - q[0], p[1] - q[1])
        if best is None or dist < best[0]:
            best = (dist, a, s)
    if best is None or best[0] > reach:
        return None
    return best[1], best[2]
