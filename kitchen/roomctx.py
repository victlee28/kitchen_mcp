"""What an imported floorplan gives a design: the binding of the kitchen to a wall, the placement, and the room's structures.

Computed once per (floorplan, binding, run lengths) and shared by the 3D export and the Python scene, so the binding is
resolved a single time and both agree on the transform. ``geometry`` depends on this module, not on ``floorplan``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from . import floorplan as fpmod
from .placement import IDENTITY, Placement

# A memo, not state the result depends on: the key is the full content of the floorplan (digest) + binding + run lengths, so a hit is
# always what a fresh computation would give. (In a Rust port this is an LRU in the shell.)
_CACHE: dict[tuple, "RoomContext"] = {}
_MAX = 32


@dataclass(frozen=True)
class RoomContext:
    floorplan: dict
    binding: dict | None
    placement: Placement
    structures: list


def replaced(fp: dict) -> list[str]:
    """Ids of the floorplan elements the design has replaced with cabinets (``floorplan.replaced``): they are no longer built, drawn or
    rendered. The imported floorplan itself is never changed; going back a revision brings them back."""
    raw = fp.get("replaced") or []
    return [str(x) for x in raw] if isinstance(raw, list) else []


def need_for(spec: Any, back: float, side: float) -> dict | None:
    """Run lengths the kitchen needs from the room: back wall, and each side wall it uses; None for a design without cabinets."""
    mods = spec.module
    if not mods:
        return None
    from . import runs
    used = runs.walls_used(spec, back)             # cabinets that follow a side wall, or a run standing against it
    return {"back": back, "right": side if "right" in used else 0, "left": side if "left" in used else 0}


def for_spec(spec: Any, back: float, side: float) -> RoomContext | None:
    """None without a floorplan. Raises ValueError when the kitchen fits no wall (a wrong scene is never produced)."""
    fp = getattr(spec, "floorplan", None)
    if not isinstance(fp, dict):
        return None
    need = need_for(spec, back, side)
    digest = hashlib.sha256(json.dumps(fp, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()
    key = (digest, tuple(sorted(need.items())) if need else None)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    binding = fpmod.resolve_binding(fp, need)
    placement = Placement.from_transform(binding.get("transform") or fpmod.kitchen_transform(fp, binding)) if binding else IDENTITY
    gone = set(replaced(fp))
    ctx = RoomContext(fp, binding, placement, [st for st in fpmod.structures(fp) if st["sourceElement"] not in gone])   # replaced by cabinets: not built
    if len(_CACHE) >= _MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = ctx
    return ctx
