"""Two-point perspective for the design's cameras: vertical edges stay vertical in the picture.

A camera that looks up or down tilts its picture plane, so cabinet sides and wall corners converge towards a third vanishing point. Here
the camera is kept level (its view direction loses its pitch) and the picture is shifted vertically instead (an off-centre principal point,
the "lens shift" of a view camera), so the point it was aimed at stays in the middle of the frame. Views that look down steeply (the plan,
the overhead view) keep their tilt: two-point perspective is for eye-level pictures.

The web viewer does the same with ``PerspectiveCamera.setViewOffset`` (``web/two-point.js`` mirrors ``MAX_PITCH_DEG``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MAX_PITCH_DEG = 30.0       # views tilted more than this (plan, overhead) stay three-point
PROJECTION = "two-point"   # part of the render key: a picture taken before the cameras were levelled is taken again


@dataclass(frozen=True)
class Level:
    forward: tuple[float, float, float]   # the level view direction (unit, y = 0)
    shift: float                          # tan(pitch) of the aim it replaces: the aimed point is at y/z = shift in the level camera


def level(position: tuple[float, float, float], look_at: tuple[float, float, float], max_pitch_deg: float = MAX_PITCH_DEG) -> Level | None:
    """The level camera for a view from ``position`` to ``look_at``, or None when the view looks down (or up) more steeply than
    ``max_pitch_deg`` or straight along the vertical."""
    dx, dy, dz = (look_at[i] - position[i] for i in range(3))
    flat = math.hypot(dx, dz)
    if flat < 1e-9:
        return None
    if abs(math.degrees(math.atan2(dy, flat))) > max_pitch_deg:
        return None
    return Level((dx / flat, 0.0, dz / flat), dy / flat)
