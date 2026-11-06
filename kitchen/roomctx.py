"""What an imported floorplan gives a design: the binding of the kitchen to a wall, the placement, and the room's structures.

Computed once per (floorplan, binding, run lengths) and shared by the 3D export and the Python scene, so the binding is
resolved a single time and both agree on the transform. ``geometry`` depends on this module, not on ``floorplan``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import floorplan as fpmod
from .placement import IDENTITY, Placement

_CACHE: dict[tuple, "RoomContext"] = {}
_MAX = 32


@dataclass(frozen=True)
class RoomContext:
    floorplan: dict
    binding: dict | None
    placement: Placement
    structures: list


def need_for(spec: Any, back: float, side: float) -> dict | None:
    """Run lengths the kitchen needs from the room: back wall, and each side wall it uses; None for a design without cabinets."""
    mods = spec.module
    if not mods:
        return None
    return {"back": back, "right": side if any(m.wall == "right" for m in mods) else 0, "left": side if any(m.wall == "left" for m in mods) else 0}


def for_spec(spec: Any, back: float, side: float) -> RoomContext | None:
    """None without a floorplan. Raises ValueError when the kitchen fits no wall (a wrong scene is never produced)."""
    fp = getattr(spec, "floorplan", None)
    if not isinstance(fp, dict):
        return None
    need = need_for(spec, back, side)
    key = (fp.get("ref"), fp.get("roomId"), json.dumps(fp.get("binding"), sort_keys=True, default=str), tuple(sorted(need.items())) if need else None,
           len(fp.get("elements") or ()))
    hit = _CACHE.get(key)
    if hit is not None and hit.floorplan is fp:
        return hit
    binding = fpmod.resolve_binding(fp, need)
    placement = Placement.from_transform(binding.get("transform") or fpmod.kitchen_transform(fp, binding)) if binding else IDENTITY
    ctx = RoomContext(fp, binding, placement, fpmod.structures(fp))
    if len(_CACHE) >= _MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = ctx
    return ctx
