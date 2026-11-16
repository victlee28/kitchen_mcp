"""The one place positions are turned into ``s`` along a wall axis (plan §2.2). Pure.

* a point (room or kitchen frame, the axis's own frame): its projection on the axis;
* a cabinet-style wall seat (``fromCorner`` / ``offset`` from the inner corner, the back wall measured from the right): the point on the
  inner face, projected;
* a recognizer measurement: along the inner face from an inner corner (``at = "start" | "end"`` of the axis). The inner corner lies
  half the adjoining wall's thickness inside the axis end, so forgetting this shifts every recognized opening by 50-110 mm.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from .contract import Pt
from .wall_axes import WallAxis

JOIN_MM = 1.0


def s_of_point(axis: WallAxis, p: Pt) -> float:
    return axis.s_of(p)


def _end(axis: WallAxis, at: str) -> Pt:
    return axis.start if at == "start" else axis.point(axis.length)


def adjoining(axis: WallAxis, axes: Sequence[WallAxis], at: str) -> WallAxis | None:
    """The axis that meets ``axis`` at its start or end (shares that end point), if any."""
    p = _end(axis, at)
    for other in axes:
        if other.id == axis.id:
            continue
        for q in (other.start, other.point(other.length)):
            if math.hypot(p[0] - q[0], p[1] - q[1]) <= JOIN_MM:
                return other
    return None


def inner_corner_s(axis: WallAxis, axes: Sequence[WallAxis], at: str) -> float:
    """``s`` of the inner corner at one end of the axis: half the adjoining wall's thickness in from the end (0 at a free end).
    A floorplan axis knows its room's corners itself (the ends of the room edges it holds), also when the wall runs on past them."""
    if axis.frame == "room" and axis.segments:
        return axis.segments[0].s0 if at == "start" else axis.segments[-1].s1
    other = adjoining(axis, axes, at)
    if other is None:
        return 0.0 if at == "start" else axis.length
    p = _end(axis, at)
    half = other.thickness_at(other.s_of(p)) / 2
    return half if at == "start" else axis.length - half


def from_inner_corner(axis: WallAxis, axes: Sequence[WallAxis], s_face: float, at: str = "start") -> float:
    """A distance measured along the inner face from the inner corner at ``at`` -> ``s`` on the axis."""
    corner = inner_corner_s(axis, axes, at)
    return corner + s_face if at == "start" else corner - s_face
