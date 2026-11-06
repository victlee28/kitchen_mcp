"""Reading a floorplan document: frame, points, fields, hash, element boxes."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from ..errors import InvalidInput

from .constants import AXIS


# ---------------------------------------------------------------- reading the document
def frame_vectors(data: dict[str, Any]) -> tuple[Any, Any]:
    frame = data.get("frame")
    if not isinstance(frame, dict):
        raise InvalidInput("Floorplan has no 'frame'; axis directions would have to be guessed")
    names = [frame.get(k) for k in ("x", "y", "z")]
    if any(n not in AXIS for n in names):
        raise InvalidInput(f"Unsupported frame axes {names}; known names: {', '.join(AXIS)}")
    vx, vy, vz = (AXIS[str(n)] for n in names)
    if vx[2] or vy[2] or not vz[2]:
        raise InvalidInput("Frame must have horizontal x and y axes and a vertical z axis")
    det = (vx[0] * (vy[1] * vz[2] - vy[2] * vz[1]) - vx[1] * (vy[0] * vz[2] - vy[2] * vz[0]) + vx[2] * (vy[0] * vz[1] - vy[1] * vz[0]))
    declared = frame.get("handed")
    if declared in ("trai", "phai"):
        expected = -1 if declared == "trai" else 1
        if det != expected:
            raise InvalidInput(f"Frame axes {names} are {'left' if det < 0 else 'right'}-handed but the file declares '{declared}'")
    return vx, vy


def read_points(value: Any, element_id: str, what: str = "outline") -> list[tuple[float, float]]:
    outline = value.get(what) if isinstance(value, dict) else None
    if not isinstance(outline, list) or len(outline) < 3:
        raise InvalidInput(f"{element_id}: geometry.{what} must contain at least three points")
    pts = []
    for index, point in enumerate(outline):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise InvalidInput(f"{element_id}: {what} point {index} must be [x, y]")
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError) as error:
            raise InvalidInput(f"{element_id}: {what} point {index} must be numeric") from error
        if not (math.isfinite(x) and math.isfinite(y)):
            raise InvalidInput(f"{element_id}: {what} point {index} must be finite")
        pts.append((x, y))
    return pts


def element_field(element: dict[str, Any], name: str) -> dict[str, Any]:
    f = (element.get("fields") or {}).get(name)
    return f if isinstance(f, dict) else {}


def field_value(element: dict[str, Any], name: str) -> Any:
    return element_field(element, name).get("value")


def document_hash(data: dict[str, Any]) -> str:
    """Stable id of a floorplan document (the key it is stored under)."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


KITCHEN_WORDS = ("kitchen", "bếp", "bep")
REGION_COVER = 0.2          # a wall bounds a side of the region when it covers this share of the seed's width
REGION_MARGIN_MM = 600.0    # how far an open side (no wall found) reaches beyond the seed


def element_bbox(e: dict[str, Any]) -> list[float] | None:
    g = field_value(e, "geometry")
    if not isinstance(g, dict):
        return None
    if isinstance(g.get("bbox"), list) and len(g["bbox"]) == 4:
        return [float(v) for v in g["bbox"]]
    try:
        pts = read_points(g, str(e.get("id")))
    except ValueError:
        return None
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]


def is_kitchen_unit(e: dict[str, Any]) -> bool:
    if e.get("kind") != "furniture":
        return False
    text = f"{field_value(e, 'tag') or ''} {field_value(e, 'label') or ''}".lower()
    return any(w in text for w in KITCHEN_WORDS)
