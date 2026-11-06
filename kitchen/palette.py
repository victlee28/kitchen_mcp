"""Fixed colours of the semantic masks and the per-module identification colour. Shared by render.py and threejs_export.py."""
from __future__ import annotations

import colorsys
import hashlib

SEGMENT_COLORS = {  # semantic mask colours (fixed between renders)
    "carcass": (230, 159, 0), "plinth": (86, 180, 233), "door": (0, 158, 115), "glass-door": (0, 114, 178),
    "drawer": (213, 94, 0), "side-panel": (204, 121, 167), "shelf": (240, 228, 66), "countertop": (255, 255, 255),
    "fridge": (120, 120, 200), "sink": (40, 40, 40), "faucet": (160, 160, 160), "cooktop": (90, 0, 90),
    "hood": (0, 90, 90), "oven": (120, 60, 20), "wall": (180, 170, 150), "floor": (110, 100, 90),
    "molding": (168, 117, 66), "handle": (255, 0, 140),
    "structure-wall": (231, 226, 213), "structure-column": (242, 182, 93), "structure-opening": (85, 198, 169),
    "structure-furniture": (211, 134, 98), "structure-shaft": (140, 131, 214), "structure-stair": (207, 174, 82),
    "structure-area": (125, 158, 170), "structure-swing": (154, 217, 198),
}


def module_color(id: str) -> tuple[int, int, int]:
    """Stable RGB for an id: md5 of the id picks the hue (so it is the same in every process and language)."""
    h = int(hashlib.md5(id.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hsv_to_rgb(h, 0.75, 0.95)
    return int(r * 255), int(g * 255), int(b * 255)
