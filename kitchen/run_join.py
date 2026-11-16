"""Joining two explicit runs that meet in a corner at any angle (``spec.runs``): the cabinets near the corner are trimmed, moved or
stretched so that neither run pokes through the other run's wall or into its cabinets, and the small gaps are closed. Pure (rule R1).

The corner is where the two back lines cross. Each run is measured by ``t``, the distance from the corner along its back line (so it
does not matter which way its ``s`` runs). One run OWNS the corner: its cabinets go as close to the corner as the other wall lets them
(at a sharp corner its last cabinet stops where its front corner touches the other wall). The other run starts where its cabinets clear
the owner's: past the owner's front line, and past its wall. Floor-standing cabinets (base, tall) and wall cabinets (upper, top) are
joined each with their own depths; a tall cabinet of the owner near the corner also keeps the other run's wall cabinets away.

Edits: a cabinet that reaches into the forbidden part is shortened from the corner side when what is left is at least the narrowest
cabinet, else removed; a cabinet that stops short of its limit by no more than ``CLOSE_GAP_MM`` is stretched to it when it stays within
the widest cabinet. The worktop wedge and the moldings round the corner follow from where the runs then stand (``geometry``,
``moldings``).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from . import builtin, defaults
from . import runs as runmod
from .catalog import Catalog
from .errors import InvalidInput
from .numeric import round_half_away
from .spec import KitchenSpec, Module

Pt = tuple[float, float]
CLOSE_GAP_MM = 300.0           # a gap at the corner up to this is closed by stretching the cabinet next to it
MAX_WIDTH_MM = 1200.0          # ...as long as it stays this wide at most
FAR_MM = 6000.0                # the owner's cabinets are a strip this long from its limit (longer than any run near a corner)
FLOOR = ("base", "tall")
WALL = ("upper", "loft")


@dataclass(frozen=True)
class Side:
    """One run seen from the corner: its frame, where the corner is along it (``p``) and which way its cabinets lie (``sign``: +1 when
    they are at s > p, -1 when at s < p)."""
    frame: runmod.RunFrame
    p: float
    sign: int

    def t_of(self, m: Module) -> tuple[float, float]:
        """(near, far) distance of a cabinet from the corner."""
        a, b = (m.fromCorner - self.p, m.endAt - self.p) if self.sign > 0 else (self.p - m.endAt, self.p - m.fromCorner)
        return a, b

    def world(self, t: float, d: float) -> Pt:
        return self.frame.to_world(self.p + self.sign * t, d)

    def box(self, t0: float, t1: float, depth: float) -> list[Pt]:
        pts = [self.world(t0, 0.0), self.world(t1, 0.0), self.world(t1, depth), self.world(t0, depth)]
        return pts if self.sign > 0 else pts[::-1]

    def d_of(self, x: float, z: float) -> float:
        """Distance in front of this run's back line (its wall); negative behind it."""
        return self.frame.to_local(x, z)[1]

    def module_change(self, m: Module, near: float, far: float) -> dict[str, float]:
        start = self.p + near if self.sign > 0 else self.p - far
        return {"fromCorner": _mm(start), "width": _mm(far - near)}


def _mm(v: float) -> float:
    return float(round_half_away(v, 1))


def _corner(fa: runmod.RunFrame, fb: runmod.RunFrame) -> Pt:
    ax, az = fa.to_world(1.0, 0.0)
    bx, bz = fb.to_world(1.0, 0.0)
    ua, ub = (ax - fa.x, az - fa.z), (bx - fb.x, bz - fb.z)
    den = ua[0] * ub[1] - ua[1] * ub[0]
    if abs(den) < 1e-6:
        raise InvalidInput("The two runs are parallel, so they never meet in a corner", code="runs-parallel")
    t = ((fb.x - fa.x) * ub[1] - (fb.z - fa.z) * ub[0]) / den
    return fa.x + t * ua[0], fa.z + t * ua[1]


def _side(frame: runmod.RunFrame, corner: Pt, mods: Sequence[Module]) -> Side:
    p = frame.to_local(*corner)[0]
    before = sum(1 for m in mods if m.endAt <= p + 1.0)
    after = sum(1 for m in mods if m.fromCorner >= p - 1.0)
    if not before and not after:
        raise InvalidInput(f"Run {frame.id} runs across the corner: its cabinets lie on both sides of it", code="run-across-corner",
                           params={"run": frame.id})
    return Side(frame, p, 1 if after >= before else -1)


def _wall_limit(me: Side, other: Side, depth: float) -> float:
    """The smallest t at which a box of ``depth`` of ``me`` stays in front of the other run's wall (its back line)."""
    f00 = other.d_of(*me.world(0.0, 0.0))
    alpha = other.d_of(*me.world(1.0, 0.0)) - f00
    beta = other.d_of(*me.world(0.0, 1.0)) - f00
    if alpha <= 1e-9:
        return 0.0
    return max(0.0, max((-beta * d - f00) / alpha for d in (0.0, depth)))


def _clear_of(me: Side, start: float, depth: float, obstacles: Sequence[list[Pt]]) -> float:
    """The smallest t >= ``start`` at which a box of ``me`` of ``depth`` (100 mm long is enough: its near face decides) touches none of the
    obstacles (convex polygons)."""
    def free(t: float) -> bool:
        box = me.box(t, t + 100.0, depth)
        return all(runmod.penetration(box, o) <= 0.5 for o in obstacles)
    if free(start):
        return start
    lo, hi = start, start + 100.0
    while not free(hi):
        lo, hi = hi, hi * 2 + 100.0
        if hi > FAR_MM:
            return hi
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if free(mid) else (mid, hi)
    return float(math.ceil(hi))


def _edits(side: Side, mods: Sequence[Module], limit: float, narrowest: float) -> tuple[list[dict[str, Any]], list[str]]:
    """Operations that bring ``side``'s cabinets (one storey band) to ``limit``: trim or remove what reaches into it, stretch the nearest one
    over a small gap. Returns (ops, ids touched)."""
    ops: list[dict[str, Any]] = []
    touched: list[str] = []
    ordered = sorted(mods, key=lambda m: side.t_of(m)[0])
    for m in ordered:
        near, far = side.t_of(m)
        if near >= limit - 0.5:
            continue
        if far - limit >= narrowest:
            ops.append({"op": "update", "id": m.id, "changes": side.module_change(m, limit, far)})
        else:
            ops.append({"op": "remove", "id": m.id, "closeGap": False})
        touched.append(m.id)
    kept = [m for m in ordered if not any(o["op"] == "remove" and o["id"] == m.id for o in ops)]
    if kept:                          # the nearest cabinet left: stretched over a small gap to the limit
        first = kept[0]
        near, far = side.t_of(first)
        trimmed = next((o for o in ops if o["op"] == "update" and o["id"] == first.id), None)
        if trimmed is None and 0.5 < near - limit <= CLOSE_GAP_MM and far - limit <= MAX_WIDTH_MM:
            ops.append({"op": "update", "id": first.id, "changes": side.module_change(first, limit, far)})
            touched.append(first.id)
    return ops, touched


def plan_join(spec: KitchenSpec, run_a: str, run_b: str, catalog: Catalog = builtin.CATALOG) -> dict[str, Any]:
    """Join runs ``run_a`` and ``run_b`` where their back lines cross. ``run_a`` owns the corner. Returns ``{"operation": multi op | None,
    "angle": the corner's angle in the room (degrees), "owner", "limits": {run: {"floor": t, "wall": t}}, "touched": [ids]}``. Raises
    InvalidInput when the runs are parallel, missing or a run lies across the corner."""
    frames = runmod.frames(spec)
    if run_a not in frames or run_b not in frames or run_a == run_b:
        raise InvalidInput("Two different runs are needed", code="run-not-found")
    corner = _corner(frames[run_a], frames[run_b])
    mods = {r: [m for m in spec.module if m.run == r] for r in (run_a, run_b)}
    a = _side(frames[run_a], corner, mods[run_a])
    b = _side(frames[run_b], corner, mods[run_b])
    ua = (a.world(1.0, 0.0)[0] - corner[0], a.world(1.0, 0.0)[1] - corner[1])
    ub = (b.world(1.0, 0.0)[0] - corner[0], b.world(1.0, 0.0)[1] - corner[1])
    angle = math.degrees(math.acos(max(-1.0, min(1.0, ua[0] * ub[0] + ua[1] * ub[1]))))
    narrowest = defaults.of(catalog).min_width
    ops: list[dict[str, Any]] = []
    touched: list[str] = []
    limits: dict[str, dict[str, float]] = {run_a: {}, run_b: {}}
    for band, storeys in (("floor", FLOOR), ("wall", WALL)):
        own = [m for m in mods[run_a] if m.storey in storeys]
        theirs = [m for m in mods[run_b] if m.storey in storeys]
        if not own and not theirs:
            continue
        over = spec.common.countertopOverhang if band == "floor" else 0.0      # the worktop reaches past the base cabinets: it must not cross a wall
        depth_a = max((m.depth for m in own), default=0.0)
        depth_b = max((m.depth for m in theirs), default=0.0)
        limit_a = _wall_limit(a, b, depth_a + over) if own else 0.0
        obstacles = [a.box(limit_a, FAR_MM, depth_a)] if own else []
        if band == "wall":                                  # the owner's tall cabinets by the corner keep wall cabinets away too
            obstacles += [a.box(max(limit_a, a.t_of(m)[0]), a.t_of(m)[1], m.depth) for m in mods[run_a] if m.storey == "tall"]
        limit_b = _clear_of(b, _wall_limit(b, a, depth_b + over), depth_b, obstacles) if theirs else 0.0
        limits[run_a][band], limits[run_b][band] = _mm(limit_a), _mm(limit_b)
        for side, group, limit in ((a, own, limit_a), (b, theirs, limit_b)):
            o, t = _edits(side, group, limit, narrowest)
            ops += o
            touched += t
    return {"operation": {"op": "multi", "ops": ops} if ops else None, "angle": _mm(angle), "owner": run_a, "limits": limits, "touched": touched}


def meeting_run(spec: KitchenSpec, run: str) -> str | None:
    """The run that meets ``run`` in a corner nearest to its cabinets (the other end of its nearest end), None when no run does."""
    frames = runmod.frames(spec)
    if run not in frames:
        return None
    mine = [m for m in spec.module if m.run == run]
    if not mine:
        return None
    lo, hi = min(m.fromCorner for m in mine), max(m.endAt for m in mine)
    best: tuple[float, str] | None = None
    for other, fr in frames.items():
        if other == run:
            continue
        try:
            corner = _corner(frames[run], fr)
        except InvalidInput:
            continue
        s = frames[run].to_local(*corner)[0]
        far = min(abs(s - lo), abs(s - hi))
        theirs = [m for m in spec.module if m.run == other]
        if not theirs:
            continue
        s_other = fr.to_local(*corner)[0]
        far_other = min(abs(s_other - min(m.fromCorner for m in theirs)), abs(s_other - max(m.endAt for m in theirs)))
        gap = far + far_other
        if gap <= 2000.0 and (best is None or gap < best[0]):
            best = (gap, other)
    return best[1] if best else None
