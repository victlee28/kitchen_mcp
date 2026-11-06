"""Constants of the floorplan contract and the tolerances used by every step."""
from __future__ import annotations


DEFAULT_WALL_THICKNESS = 140.0   # mm, used only for edges without a measured wall element
DEFAULT_WALL_HEIGHT = 3000.0     # mm
TOL = 30.0                       # mm, drawing/pick tolerance for "touching"
PARALLEL_DEG = 8.0
SUPPORTED_CONTRACT = "2."

# axis name used by the floorplan contract -> unit vector in (right, forward, up)
AXIS = {"toi": (0, 1, 0), "lui": (0, -1, 0), "phai": (1, 0, 0), "trai": (-1, 0, 0), "len": (0, 0, 1), "xuong": (0, 0, -1)}
UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}
