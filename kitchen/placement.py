"""Rigid map between the kitchen frame and the room (scene) frame of an imported floorplan. Pure; the only place this math lives.

Kitchen frame: origin at the right-hand corner of the back wall, +z into the room. Rotation is about +Y with the three.js
convention (x' = x cos + z sin, z' = -x sin + z cos), yaw in degrees.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Placement:
    yaw: float = 0.0
    ox: float = 0.0
    oz: float = 0.0

    @classmethod
    def from_transform(cls, t: dict) -> "Placement":
        """From floorplan.kitchen_transform(): {"yaw": deg, "origin": {"x", "z"}, ...}."""
        return cls(float(t["yaw"]), float(t["origin"]["x"]), float(t["origin"]["z"]))

    def _cs(self) -> tuple[float, float]:
        a = math.radians(self.yaw)
        return math.cos(a), math.sin(a)

    def dir_to_room(self, x: float, z: float) -> tuple[float, float]:
        """A direction (no translation) from the kitchen frame to the room frame."""
        c, s = self._cs()
        return x * c + z * s, -x * s + z * c

    def to_room(self, x: float, z: float) -> tuple[float, float]:
        dx, dz = self.dir_to_room(x, z)
        return dx + self.ox, dz + self.oz

    def to_kitchen(self, x: float, z: float) -> tuple[float, float]:
        c, s = self._cs()
        ux, uz = x - self.ox, z - self.oz
        return ux * c - uz * s, ux * s + uz * c


IDENTITY = Placement()
