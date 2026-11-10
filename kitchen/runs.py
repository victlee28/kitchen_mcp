"""Explicit runs: straight rows of cabinets at any angle, and the plane geometry that goes with them.

A run has its own frame (``spec.Run``): s along the row, d from the back of the cabinets to their door face, world
(x, z) = origin + s * u + d * n with u = (cos yaw, -sin yaw) and n = (sin yaw, cos yaw), yaw as in three.js ``rotation.y``.
Rows that follow the walls or a legacy free run are axis-aligned and may be mirrored: ``Seat``. Everything here is pure plane math in mm.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .numeric import round_half_away
from .spec import Appliance, KitchenSpec, Module

Point = tuple[float, float]
EPS = 1e-9


def trig(yaw: float) -> tuple[float, float]:
    """(cos, sin) of a yaw in degrees; exact for multiples of 90 so right-angle runs reproduce axis-aligned numbers."""
    q = yaw / 90.0
    if abs(q - round_half_away(q, 0)) < EPS:
        k = int(round_half_away(q, 0)) % 4
        return ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[k]
    t = math.radians(yaw)
    return math.cos(t), math.sin(t)


@dataclass(frozen=True)
class RunFrame:
    id: str
    x: float
    z: float
    yaw: float

    def to_world(self, s: float, d: float) -> Point:
        c, sn = trig(self.yaw)
        return (self.x + s * c + d * sn, self.z - s * sn + d * c)

    def to_local(self, x: float, z: float) -> Point:
        c, sn = trig(self.yaw)
        dx, dz = x - self.x, z - self.z
        return (dx * c - dz * sn, dx * sn + dz * c)

    def normal(self) -> Point:
        """Unit vector the doors look along (world x, z)."""
        c, sn = trig(self.yaw)
        return (sn, c)

    def footprint(self, s0: float, s1: float, d0: float, d1: float) -> list[Point]:
        return [self.to_world(s0, d0), self.to_world(s1, d0), self.to_world(s1, d1), self.to_world(s0, d1)]

    def corners(self, lmin: tuple[float, float, float], lmax: tuple[float, float, float]) -> list[tuple[float, float, float]]:
        """The 8 world corners of a local box (s, y, d); bit 0 = s, bit 1 = y, bit 2 = d (same order as min / max boxes)."""
        out = []
        for i in range(8):
            s = lmax[0] if i & 1 else lmin[0]
            y = lmax[1] if i & 2 else lmin[1]
            d = lmax[2] if i & 4 else lmin[2]
            x, z = self.to_world(s, d)
            out.append((x, y, z))
        return out


@dataclass(frozen=True)
class Seat:
    """Where an axis-aligned row of cabinets stands, whatever placed it there (a wall, a legacy free run): the row's own (s, d)
    plane laid on the world. s runs along the row and d from the back of the cabinets to their door face, each along one world
    axis (x = 0, z = 2), forwards or backwards from an offset. A seat may be MIRRORED (the walls measure s from the back-right
    corner, so s on the back wall runs to the viewer's left), which a ``RunFrame`` (a pure rotation) cannot say.

    ``front`` names the way the doors look, in the words the exporters already use: ``back`` (+z), ``island`` (-z),
    ``right`` (-x), ``left`` (+x). An offset of None means "no offset": the value is only negated, never added to, so the
    numbers are bit-for-bit those of the wall-keyed code this replaces."""
    front: str
    s_axis: int
    s_sign: int
    s_from: float | None
    d_sign: int
    d_from: float | None

    @staticmethod
    def _at(origin: float | None, sign: int, v: float) -> float:
        return sign * v if origin is None else origin + sign * v

    def to_world(self, s: float, d: float) -> Point:
        a, b = self._at(self.s_from, self.s_sign, s), self._at(self.d_from, self.d_sign, d)
        return (a, b) if self.s_axis == 0 else (b, a)

    def normal(self) -> Point:
        """Unit vector the doors look along (world x, z)."""
        return (0.0, float(self.d_sign)) if self.s_axis == 0 else (float(self.d_sign), 0.0)

    @property
    def yaw(self) -> float:
        """three.js ``rotation.y`` of a frame whose local +z is the door normal."""
        return FRONT_YAW[self.front]

    def left_end(self, s0: float, s1: float) -> float:
        """Which end of [s0, s1] is on the left of someone looking at the doors (where the exporters anchor a cabinet)."""
        return s1 if self.s_sign != FRONT_AXES[self.front][1] else s0

    def box(self, s0: float, s1: float, d0: float, d1: float, y0: float, y1: float) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """World (min, max) of the box [s0, s1] x [d0, d1] x [y0, y1] of the row."""
        sa, sb = (s0, s1) if self.s_sign > 0 else (s1, s0)
        da, db = (d0, d1) if self.d_sign > 0 else (d1, d0)
        s_lo, s_hi = self._at(self.s_from, self.s_sign, sa), self._at(self.s_from, self.s_sign, sb)
        d_lo, d_hi = self._at(self.d_from, self.d_sign, da), self._at(self.d_from, self.d_sign, db)
        if self.s_axis == 0:
            return (s_lo, y0, d_lo), (s_hi, y1, d_hi)
        return (d_lo, y0, s_lo), (d_hi, y1, s_hi)


WALL_SEATS = {"back": Seat("back", 0, -1, None, 1, None), "right": Seat("right", 2, 1, None, -1, None)}


def wall_seat(wall: str, back_length: float) -> Seat | None:
    """Seat of a wall's row in the kitchen frame (origin at the back-right corner); None for a name that is not a wall."""
    if wall == "left":
        return Seat("left", 2, 1, None, 1, -back_length)
    return WALL_SEATS.get(wall)


def free_seat(offset: float, depth: float, facing: str) -> Seat:
    """Seat of a legacy free run (``wall = "island"``): its door face at ``offset`` from the wall it looks away from or at."""
    if facing == "-z":      # doors look at the back wall
        return Seat("island", 0, -1, None, -1, offset + depth)
    if facing == "+z":      # like the back wall, standing at z = offset - depth
        return Seat("back", 0, -1, None, 1, offset - depth)
    if facing == "-x":      # like the right wall, door face at x = -offset
        return Seat("right", 2, 1, None, -1, -offset + depth)
    return Seat("left", 2, 1, None, 1, -offset - depth)   # "+x": like the left wall


# The way the doors look -> (axis the row is seen along from the front, its sign, axis of the door normal, its sign); x = 0, z = 2.
FRONT_AXES = {"back": (0, 1, 2, 1), "island": (0, -1, 2, -1), "right": (2, 1, 0, -1), "left": (2, -1, 0, 1)}


FRONT_YAW = {"back": 0.0, "island": 180.0, "right": -90.0, "left": 90.0}


def seat_of(m: Module, back_length: float) -> Seat | None:
    """Seat of a cabinet that follows a wall or stands in a legacy free run; None for anything else (explicit runs have a ``RunFrame``)."""
    if m.run:
        return None
    if m.wall == "island":
        return free_seat(m.offset, m.depth, m.facing or "-z")
    return wall_seat(m.wall, back_length)


def front_span(front: str, mn: tuple[float, float, float], mx: tuple[float, float, float]) -> tuple[float, float, float]:
    """An axis-aligned front panel seen from the front: (u0, u1, f) with u growing to the viewer's right and f the world
    coordinate of its outer face."""
    u_axis, u_sign, n_axis, n_sign = FRONT_AXES[front]
    u0, u1 = (mn[u_axis], mx[u_axis]) if u_sign > 0 else (-mx[u_axis], -mn[u_axis])
    return u0, u1, (mx[n_axis] if n_sign > 0 else mn[n_axis])


def front_box(front: str, u0: float, u1: float, v0: float, v1: float, f: float, out: float) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """World (min, max) of a box standing ``out`` proud of a front face at ``f`` (the inverse of ``front_span``)."""
    u_axis, u_sign, n_axis, n_sign = FRONT_AXES[front]
    ua, ub = (u0, u1) if u_sign > 0 else (-u1, -u0)
    na, nb = (f, f + out) if n_sign > 0 else (f - out, f)
    mn, mx = [0.0, v0, 0.0], [0.0, v1, 0.0]
    mn[u_axis], mx[u_axis], mn[n_axis], mx[n_axis] = ua, ub, na, nb
    return (mn[0], mn[1], mn[2]), (mx[0], mx[1], mx[2])


def frame_of(spec: KitchenSpec, module: Module) -> RunFrame | None:
    """Frame of the explicit run a module stands in (None for wall modules and legacy free runs)."""
    if not module.run:
        return None
    for r in spec.runs:
        if r.id == module.run:
            return RunFrame(r.id, r.x, r.z, r.yaw)
    return None


def row_of(m: Module) -> str:
    """Key of the row a cabinet stands in: ``run:<id>`` in an explicit run, else the name of its wall (``island`` for a legacy free run).
    Rules and edits compare ROWS, not walls, so cabinets of two different runs never count as neighbours."""
    return f"run:{m.run}" if m.run else m.wall


@dataclass(frozen=True)
class Spot:
    """Where an appliance stands along a row: the row key (``row_of``), the position of its centre along the row (mm), its module if any."""
    row: str
    center: float
    module: str | None


def spot(spec: KitchenSpec, tb: Appliance) -> Spot | None:
    """Where a worktop appliance (sink, hob, tap) stands. One whose module stands in an explicit run stands in that run (at its ``center`` along
    the run, else at the middle of the module); one given by wall + centre stands there; one given only by its module, at the middle of it. None when it has no place."""
    m = next((x for x in spec.module if x.id == tb.module), None) if tb.module else None
    if m is not None and m.run:                 # in an explicit run the centre is measured along the run, whatever ``wall`` says
        return Spot(row_of(m), tb.center if tb.center is not None else m.fromCorner + m.width / 2, m.id)
    if tb.wall and tb.center is not None:
        return Spot(tb.wall, tb.center, tb.module)
    if m is None or m.wall == "corner":
        return None
    return Spot(row_of(m), m.fromCorner + m.width / 2, m.id)


@dataclass(frozen=True)
class Joint:
    """Two explicit runs meeting in an inside corner: the END of run ``a`` meets the START of run ``b``. ``at`` is where b's back line starts,
    measured along a (mm); ``angle`` is the corner's angle in the room, in degrees (90 for a square corner, more for an open one)."""
    a: str
    b: str
    at: float
    angle: float = 90.0

    @property
    def square(self) -> bool:
        return abs(self.angle - 90.0) <= 0.5


JOINT_ANGLES = (30.0, 150.0)        # corners sharper or flatter than this are not joined (a flat one is one run, a sharp one has no room for doors)


def corner_joints(spec: KitchenSpec) -> list[Joint]:
    """The inside corners between explicit runs, found from where the runs stand (nothing is stored): b is turned clockwise from a by less
    than a half turn (yaw_b = yaw_a - 180 + angle) and b's origin lies on a's back line, at or just beyond a's cabinets."""
    out: list[Joint] = []
    reach = {r.id: max((m.endAt for m in spec.module if m.run == r.id), default=None) for r in spec.runs}
    for ra in spec.runs:
        for rb in spec.runs:
            if ra.id == rb.id or reach[ra.id] is None or reach[rb.id] is None:
                continue
            angle = 180.0 - (ra.yaw - rb.yaw) % 360.0
            if not JOINT_ANGLES[0] <= angle <= JOINT_ANGLES[1]:
                continue
            s, d = RunFrame(ra.id, ra.x, ra.z, ra.yaw).to_local(rb.x, rb.z)
            deepest = max((m.depth for m in spec.module if m.run == rb.id), default=0.0)
            limit = deepest / math.sin(math.radians(angle)) + 100.0
            if abs(d) <= 1.0 and s >= 0 and -1.0 <= s - float(reach[ra.id] or 0.0) <= limit:
                out.append(Joint(ra.id, rb.id, s, 90.0 if abs(angle - 90.0) < 1e-6 else angle))
    return out


def front_cross(fa: RunFrame, da: float, fb: RunFrame, db: float) -> tuple[float, float, Point] | None:
    """Where the line d = ``da`` of run a crosses the line d = ``db`` of run b: ``(s along a, s along b, world point)``; None when parallel."""
    (ax, az), (bx, bz) = fa.to_world(0.0, da), fb.to_world(0.0, db)
    (ux, uz), (vx, vz) = fa.to_world(1.0, da), fb.to_world(1.0, db)
    ux, uz, vx, vz = ux - ax, uz - az, vx - bx, vz - bz
    det = ux * (-vz) - (-vx) * uz
    if abs(det) < EPS:
        return None
    rx, rz = bx - ax, bz - az
    s = (rx * (-vz) - (-vx) * rz) / det
    t = (ux * rz - uz * rx) / det
    return s, t, (ax + s * ux, az + s * uz)


def run_wall(fr: RunFrame, back_length: float) -> str | None:
    """The wall of the kitchen frame (back / right / left) an explicit run has its back against, None when it stands free."""
    nx, nz = fr.normal()
    if abs(nx) < 1e-6 and nz > 0 and abs(fr.z) < 1.0:
        return "back"
    if abs(nz) < 1e-6 and nx < 0 and abs(fr.x) < 1.0:
        return "right"
    if abs(nz) < 1e-6 and nx > 0 and abs(fr.x + back_length) < 1.0:
        return "left"
    return None


def walls_used(spec: KitchenSpec, back_length: float) -> set[str]:
    """The walls of the kitchen frame that have cabinets: those that follow the wall and explicit runs standing against it."""
    out = {m.wall for m in spec.module if not m.run and m.wall in ("back", "right", "left")}
    for r in spec.runs:
        wall = run_wall(RunFrame(r.id, r.x, r.z, r.yaw), back_length)
        if wall is not None and any(m.run == r.id for m in spec.module):
            out.add(wall)
    return out


def along_wall(fr: RunFrame, wall: str, s0: float, s1: float) -> tuple[float, float]:
    """The stretch [s0, s1] of a run standing against ``wall``, measured the way that wall is (from the back corner; the back wall from its
    right-hand end)."""
    pts = [fr.to_world(s0, 0.0), fr.to_world(s1, 0.0)]
    vals = [-x for x, _ in pts] if wall == "back" else [z for _, z in pts]
    return min(vals), max(vals)


def frames(spec: KitchenSpec) -> dict[str, RunFrame]:
    return {r.id: RunFrame(r.id, r.x, r.z, r.yaw) for r in spec.runs}


def aabb(points: list[Point]) -> tuple[Point, Point]:
    return (min(p[0] for p in points), min(p[1] for p in points)), (max(p[0] for p in points), max(p[1] for p in points))


def _axes(poly: list[Point]) -> list[Point]:
    out = []
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        ex, ez = b[0] - a[0], b[1] - a[1]
        n = math.hypot(ex, ez)
        if n > EPS:
            out.append((-ez / n, ex / n))
    return out


def penetration(a: list[Point], b: list[Point]) -> float:
    """Depth (mm) by which two convex polygons overlap along their shallowest separating axis; 0 when they only touch or are apart."""
    best = math.inf
    for ax, az in _axes(a) + _axes(b):
        pa = [p[0] * ax + p[1] * az for p in a]
        pb = [p[0] * ax + p[1] * az for p in b]
        lap = min(max(pa), max(pb)) - max(min(pa), min(pb))
        if lap <= 0:
            return 0.0
        best = min(best, lap)
    return 0.0 if best is math.inf else best


def module_footprint(frame: RunFrame, m: Module) -> list[Point]:
    return frame.footprint(m.fromCorner, m.endAt, 0.0, m.depth)


def strip_extent(poly: list[Point], frame: RunFrame, d_max: float) -> tuple[float, float] | None:
    """(smallest, largest) s, in ``frame``, of the part of a convex polygon inside the strip 0 <= d <= d_max; None when it misses the strip."""
    pts = [frame.to_local(x, z) for x, z in poly]
    for keep in (lambda p: p[1] >= 0.0, lambda p: p[1] <= d_max):
        edge = 0.0 if keep(( 0.0, 0.0)) and not keep((0.0, -1.0)) else d_max
        out: list[Point] = []
        for i, a in enumerate(pts):
            b = pts[(i + 1) % len(pts)]
            if keep(a):
                out.append(a)
            if keep(a) != keep(b):
                t = (edge - a[1]) / (b[1] - a[1])
                out.append((a[0] + t * (b[0] - a[0]), edge))
        pts = out
        if not pts:
            return None
    return min(p[0] for p in pts), max(p[0] for p in pts)
