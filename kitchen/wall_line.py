"""Walls and the lines cabinets stand on (pure plane math, rule R1; KITCHEN frame, mm).

Rule (10/11/2026): a run of cabinets always stands on a line and, where there is a wall, turns its BACK to the wall. A floorplan object
(``furniture``) that is replaced by cabinets gives one line per edge lying against a wall: the back on that edge, the doors looking into the
object (towards the room), the run as deep as the object. An object with no edge against a wall asks the user which edge is the back.
"""
from __future__ import annotations

import math
from typing import Any
from dataclasses import dataclass

from .floorplan.geom import point_in_poly
from .numeric import round_int

Pt = tuple[float, float]
Segment = tuple[Pt, Pt]

WALL_NEAR = 150.0          # mm: an edge this close to a wall (and parallel to it) lies against it
PARALLEL_DEG = 2.0         # degrees an edge may turn away from the wall and still lie against it
MIN_OVERLAP = 0.5          # share of the edge's length that must run alongside the wall
MIN_EDGE = 600.0           # mm: shorter edges are not offered as the back of a run
DEPTH_SAMPLES = (0.2, 0.35, 0.5, 0.65, 0.8)


@dataclass(frozen=True)
class Edge:
    """Edge ``index`` of an outline (from vertex ``index`` to the next): ``a`` -> ``b``; ``inward`` the unit normal pointing into the object;
    ``gap`` the distance to the wall it lies against (None: no wall)."""
    index: int
    a: Pt
    b: Pt
    inward: Pt
    gap: float | None

    @property
    def length(self) -> float:
        return math.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1])


def segments(poly: list[Pt]) -> list[Segment]:
    """The closed outline's edges (zero-length ones left out)."""
    out: list[Segment] = []
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-6:
            out.append((a, b))
    return out


def _unit(a: Pt, b: Pt) -> Pt:
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    return ((b[0] - a[0]) / length, (b[1] - a[1]) / length)


def inward_normal(poly: list[Pt], a: Pt, b: Pt) -> Pt | None:
    """Unit normal of edge a->b pointing into the polygon; None when neither side is inside (a sliver)."""
    ux, uz = _unit(a, b)
    nx, nz = -uz, ux
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    for sx, sz in ((nx, nz), (-nx, -nz)):
        if point_in_poly((mid[0] + sx * 5.0, mid[1] + sz * 5.0), poly):
            return sx, sz
    return None


def wall_gap(a: Pt, b: Pt, inward: Pt, walls: list[Segment]) -> float | None:
    """Distance from edge a->b to the nearest wall it lies against: parallel within ``PARALLEL_DEG``, on the edge's outer side, running
    alongside at least ``MIN_OVERLAP`` of it. None when no wall qualifies."""
    ux, uz = _unit(a, b)
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    best: float | None = None
    for c, d in walls:
        wl = math.hypot(d[0] - c[0], d[1] - c[1])
        if wl < 1e-6:
            continue
        wx, wz = (d[0] - c[0]) / wl, (d[1] - c[1]) / wl
        if abs(ux * wz - uz * wx) > math.sin(math.radians(PARALLEL_DEG)):
            continue
        out = (mid[0] - c[0]) * inward[0] + (mid[1] - c[1]) * inward[1]        # > 0: the wall lies on the edge's outer side
        if out < -1.0:
            continue
        gap = abs((mid[0] - c[0]) * (-wz) + (mid[1] - c[1]) * wx)            # distance from the edge's middle to the wall's line
        s0 = (a[0] - c[0]) * wx + (a[1] - c[1]) * wz
        s1 = (b[0] - c[0]) * wx + (b[1] - c[1]) * wz
        overlap = min(max(s0, s1), wl) - max(min(s0, s1), 0.0)
        if overlap < MIN_OVERLAP * length:
            continue
        if best is None or gap < best:
            best = gap
    return best


def edges(poly: list[Pt], walls: list[Segment]) -> list[Edge]:
    """Every edge of the outline with its inward normal and its gap to a wall (None: none)."""
    out: list[Edge] = []
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 1.0:
            continue
        n = inward_normal(poly, a, b)
        if n is None:
            continue
        out.append(Edge(i, a, b, n, wall_gap(a, b, n, walls)))
    return out


def wall_edges(poly: list[Pt], walls: list[Segment]) -> list[Edge]:
    """The edges lying against a wall (gap <= ``WALL_NEAR``), longest first (ties: outline order)."""
    near = [e for e in edges(poly, walls) if e.gap is not None and e.gap <= WALL_NEAR]
    return sorted(near, key=lambda e: (-round_int(e.length), e.index))


def _ray_exit(poly: list[Pt], p: Pt, d: Pt) -> float | None:
    """Distance from ``p`` (on the outline) along ``d`` to where the ray leaves the polygon (the first crossing beyond 1 mm)."""
    best = None
    for a, b in segments(poly):
        ex, ez = b[0] - a[0], b[1] - a[1]
        den = d[0] * ez - d[1] * ex
        if abs(den) < 1e-9:
            continue
        t = ((a[0] - p[0]) * ez - (a[1] - p[1]) * ex) / den
        u = ((a[0] - p[0]) * d[1] - (a[1] - p[1]) * d[0]) / den
        if t > 1.0 and -1e-9 <= u <= 1 + 1e-9 and (best is None or t < best):
            best = t
    return best


def depth_from(poly: list[Pt], edge: Edge) -> float:
    """How deep the object is behind ``edge`` (mm): the shortest of the inward rays from points along the edge (an L's leg, not its body)."""
    ux, uz = _unit(edge.a, edge.b)
    found: list[float] = []
    for f in DEPTH_SAMPLES:
        p = (edge.a[0] + ux * edge.length * f, edge.a[1] + uz * edge.length * f)
        t = _ray_exit(poly, p, edge.inward)
        if t is not None:
            found.append(t)
    return min(found) if found else 0.0


def back_to_wall(a: Pt, b: Pt, normal: Pt, walls: list[Segment]) -> tuple[Pt, bool]:
    """``(normal, against)``: the door direction of a run whose back is the line a->b, turned so the back faces a wall when one lies along
    the line within ``WALL_NEAR`` on either side; ``against`` says whether a wall was found (else ``normal`` is returned unchanged)."""
    for sign in (1.0, -1.0):
        doors = (normal[0] * sign, normal[1] * sign)
        g = wall_gap(a, b, doors, walls)
        if g is not None and g <= WALL_NEAR:
            other = wall_gap(a, b, (-doors[0], -doors[1]), walls)
            if other is not None and other < g:
                return (-doors[0], -doors[1]), True
            return doors, True
    return normal, False


@dataclass(frozen=True)
class Placed:
    """One run replacing (part of) an object: its back from ``a`` to ``b``, doors along ``doors``, ``depth`` deep; ``edge`` the outline edge."""
    a: Pt
    b: Pt
    doors: Pt
    depth: float
    edge: int

    @property
    def length(self) -> float:
        return math.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1])


def _rect(p: Placed) -> list[Pt]:
    return [p.a, p.b, (p.b[0] + p.doors[0] * p.depth, p.b[1] + p.doors[1] * p.depth), (p.a[0] + p.doors[0] * p.depth, p.a[1] + p.doors[1] * p.depth)]


def _trim(p: Placed, other: Placed) -> Placed | None:
    """``p`` shortened at the end where ``other`` (a run placed before it, e.g. the other leg of an L) already stands; None when nothing is left."""
    ux, uz = _unit(p.a, p.b)
    local = [((x - p.a[0]) * ux + (z - p.a[1]) * uz, (x - p.a[0]) * p.doors[0] + (z - p.a[1]) * p.doors[1]) for x, z in _rect(other)]
    inside = [s for s, d in local if -1.0 <= d <= p.depth + 1.0]
    for i, (s0, d0) in enumerate(local):                         # where the other rectangle's sides cross this run's strip
        s1, d1 = local[(i + 1) % len(local)]
        for edge in (0.0, p.depth):
            if (d0 - edge) * (d1 - edge) < 0:
                inside.append(s0 + (edge - d0) / (d1 - d0) * (s1 - s0))
    if not inside:
        return p
    lo, hi = max(min(inside), 0.0), min(max(inside), p.length)
    if hi - lo <= 1.0:
        return p
    if lo <= 1.0:                                                 # the other run stands at this run's start
        start = hi
        end = p.length
    elif hi >= p.length - 1.0:
        start, end = 0.0, lo
    else:
        return p                                                  # in the middle: leave it, the preview shows the overlap
    if end - start < MIN_EDGE:
        return None
    return Placed((p.a[0] + ux * start, p.a[1] + uz * start), (p.a[0] + ux * end, p.a[1] + uz * end), p.doors, p.depth, p.edge)


def replace_lines(poly: list[Pt], walls: list[Segment], back_edge: int | None = None) -> dict[str, Any]:
    """Where the runs replacing an object stand. ``{"status": "ok", "runs": [Placed]}``: one run per edge against a wall (longest first, later
    ones shortened where an earlier one already stands: an L or an object in a corner gives two runs meeting in the corner), the back on the
    edge, the doors into the object, as deep as the object behind that edge. With no edge against a wall and no ``back_edge`` chosen:
    ``{"status": "choose-edge", "edges": [Edge]}`` (edges at least ``MIN_EDGE`` long, longest first) for the user to pick the back."""
    every = edges(poly, walls)
    if back_edge is not None:
        chosen = [e for e in every if e.index == back_edge]
        if not chosen:
            return {"status": "choose-edge", "edges": _offer(every)}
        picked = chosen
    else:
        picked = wall_edges(poly, walls)
        if not picked:
            return {"status": "choose-edge", "edges": _offer(every)}
    out: list[Placed] = []
    for e in picked:
        p: Placed | None = Placed(e.a, e.b, e.inward, depth_from(poly, e), e.index)
        for q in out:
            if p is None:
                break
            p = _trim(p, q)
        if p is not None and p.length >= MIN_EDGE and p.depth > 0:
            out.append(p)
    return {"status": "ok", "runs": out}


def _offer(every: list[Edge]) -> list[Edge]:
    return sorted((e for e in every if e.length >= MIN_EDGE), key=lambda e: (-round_int(e.length), e.index))
