"""The fixed colours (semantic masks, display colours, structures, edit zones) and the per-module identification colour.

The tables are data: the locked catalog kind ``palette`` (``data/items/palette.json``). No layer may override it, so the builtin catalog
is the truth and these constants are read once. Shared by render.py, threejs_export.py, geometry.py, floorplan and the image jobs.
"""
from __future__ import annotations

import colorsys
import hashlib
from typing import Any

from . import builtin

Rgb = tuple[int, int, int]


def _colors(id: str) -> Any:
    return builtin.CATALOG.data("palette", id)["colors"]


def _rgb(v: Any) -> Rgb:
    return int(v[0]), int(v[1]), int(v[2])


SEGMENT_COLORS: dict[str, Rgb] = {str(k): _rgb(v) for k, v in _colors("segment").items()}   # semantic mask colours (fixed between renders)
STRUCTURE_COLORS: dict[str, str] = {str(k): str(v) for k, v in _colors("structure").items()}   # floor-plan structures
STRUCTURE_FALLBACK: str = str(builtin.CATALOG.data("palette", "structure").get("fallback", "#9BA8B5"))
DISPLAY_COLORS: dict[str, str] = {**{str(k): str(v) for k, v in _colors("display").items()},
                                  **{f"structure-{k}": v for k, v in STRUCTURE_COLORS.items()}}   # display colour per part type
ZONE_COLORS: list[tuple[str, Rgb]] = [(str(z["name"]), _rgb(z["rgb"])) for z in _colors("zone")]   # numbered edit zones


def module_color(id: str) -> tuple[int, int, int]:
    """Stable RGB for an id: md5 of the id picks the hue (so it is the same in every process and language)."""
    h = int(hashlib.md5(id.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hsv_to_rgb(h, 0.75, 0.95)
    return int(r * 255), int(g * 255), int(b * 255)
