"""Explicit runs: straight rows of cabinets at any angle, and the plane geometry that goes with them.

A run has its own frame (``spec.Run``): s along the row, d from the back of the cabinets to their door face, world
(x, z) = origin + s * u + d * n with u = (cos yaw, -sin yaw) and n = (sin yaw, cos yaw), yaw as in three.js ``rotation.y``.
Everything here is pure plane math in mm; the wall-keyed code paths (back / right / left / island facings) are untouched.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .numeric import round_half_away
from .spec import KitchenSpec, Module

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


def frame_of(spec: KitchenSpec, module: Module) -> RunFrame | None:
    """Frame of the explicit run a module stands in (None for wall modules and legacy free runs)."""
    if not module.run:
        return None
    for r in spec.runs:
        if r.id == module.run:
            return RunFrame(r.id, r.x, r.z, r.yaw)
    return None


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
