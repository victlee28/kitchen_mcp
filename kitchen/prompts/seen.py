"""What one camera view shows, for its prompt: a prompt describes the cabinets, worktop, windows and lights the picture holds, not the
whole design (a view of the wine cabinet must not be told about the TV unit or the kitchen's under-cabinet LEDs).

``Seen`` comes from the view's ``instances.json`` (written by the renderer; read by the caller): the modules with enough pixels in the
picture and the part types each shows. ``None`` everywhere means "the whole design" (a package for every view, an old job).
Pure (rule R1).
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .. import tv_system
from ..jsonview import as_dict, as_list
from ..spec import KitchenSpec

MIN_SHARE = 0.002          # a module covering less than this share of the picture is a sliver at the edge: not described
TOP_DOWN_SHARE = 0.1      # ... a tenth of that in a picture from above
TOP_DOWN_DEG = 60.0        # a camera looking down more steeply than this sees the room from above (the overview, the plan)
Box = tuple[float, float, float, float]
WORKTOP_TYPES = ("worktop", "countertop")


@dataclass(frozen=True)
class Seen:
    modules: frozenset[str]          # module ids (cabinets, openings OPn, STRUCT-<floorplan element>) seen in the picture
    parts: frozenset[tuple[str, str]]  # (module, part type) pairs seen
    boxes: Mapping[str, Box] = field(default_factory=lambda: {})   # module -> its pixels' box (x0, y0, x1, y1) in the picture
    size: tuple[float, float] = (0.0, 0.0)                          # the picture's width, height (px)
    top_down: bool = False         # the camera looks down on the room from above (``TOP_DOWN_DEG``)
    ortho: bool = False            # ... orthographically (the plan)

    def has(self, module: str) -> bool:
        return module in self.modules

    def shows(self, module: str, types: Iterable[str]) -> bool:
        return any((module, t) in self.parts for t in types)


def from_instances(doc: Mapping[str, Any] | None, min_share: float = MIN_SHARE, camera: Mapping[str, Any] | None = None) -> Seen | None:
    """The modules of a view's ``instances.json`` document seen with at least ``min_share`` of its pixels (None: no document), with
    where each lies in the picture; ``camera``: the view's ``camera.json`` (whether it looks down on the room, orthographically)."""
    d = as_dict(doc)
    if d is None:
        return None
    w, h = float(d.get("width") or 0), float(d.get("height") or 0)
    total = max(1.0, w * h)
    per: dict[str, float] = {}
    parts: set[tuple[str, str]] = set()
    boxes: dict[str, Box] = {}
    for x in (as_dict(i) for i in as_list(d.get("instances")) or []):
        if x is None or not x.get("module"):
            continue
        m = str(x["module"])
        per[m] = per.get(m, 0.0) + float(x.get("pixels") or 0)
        parts.add((m, str(x.get("type") or "")))
        b = [float(v) for v in as_list(x.get("bbox")) or []]
        if len(b) == 4:
            o = boxes.get(m)
            boxes[m] = (b[0], b[1], b[2], b[3]) if o is None else (min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3]))
    top_down, ortho = _looks_down(camera)
    share = min_share * TOP_DOWN_SHARE if top_down else min_share     # from above the whole room is in the picture: every cabinet is small
    keep = {m for m, n in per.items() if n / total >= share}
    return Seen(frozenset(keep), frozenset(p for p in parts if p[0] in keep), {m: b for m, b in boxes.items() if m in keep}, (w, h),
                top_down, ortho)


def _looks_down(camera: Mapping[str, Any] | None) -> tuple[bool, bool]:
    """(looks down on the room, orthographically) from a view's ``camera.json``."""
    view = as_dict((as_dict(camera) or {}).get("view")) or {}
    if view.get("orthoHeight"):
        return True, True
    pos, look = as_list(view.get("position")) or [], as_list(view.get("lookAt")) or []
    if len(pos) != 3 or len(look) != 3:
        return False, False
    dx, dy, dz = (float(look[i]) - float(pos[i]) for i in range(3))
    return math.degrees(math.atan2(-dy, math.hypot(dx, dz))) > TOP_DOWN_DEG, False


def where(box: Box, size: tuple[float, float]) -> str:
    """Where a box lies in the picture, in words for the prompt ("in the top left of the image", "in the middle of the image")."""
    w, h = max(size[0], 1.0), max(size[1], 1.0)
    fx, fy = (box[0] + box[2]) / 2 / w, (box[1] + box[3]) / 2 / h
    col = "left" if fx < 0.36 else "right" if fx > 0.64 else ""
    row = "top" if fy < 0.36 else "bottom" if fy > 0.64 else ""
    spot = " ".join(x for x in (row, col) if x)
    return f"in the {spot} of the image" if spot else "in the middle of the image"


def kitchen_modules(spec: KitchenSpec) -> set[str]:
    """Ids of the kitchen cabinets: those not standing in a furniture run (TV unit, wine cabinet...)."""
    furniture = {r.id for r in spec.runs if r.purpose in tv_system.NOT_KITCHEN}
    return {m.id for m in spec.module if m.run not in furniture}


def shown(spec: KitchenSpec, seen: Seen | None) -> list[Any]:
    """The modules of ``spec`` the view shows (all of them when ``seen`` is None)."""
    return list(spec.module) if seen is None else [m for m in spec.module if seen.has(m.id)]


def worktop_seen(spec: KitchenSpec, seen: Seen | None) -> bool:
    """Whether the picture holds a kitchen worktop: kitchen base cabinets (the worktop is theirs) seen, or a worktop part seen."""
    kitchen = kitchen_modules(spec)
    if seen is not None and any(t in WORKTOP_TYPES for _, t in seen.parts):
        return True
    return any(m.id in kitchen and m.storey == "base" for m in shown(spec, seen))


def kitchen_uppers_seen(spec: KitchenSpec, seen: Seen | None) -> bool:
    """Whether the picture holds wall cabinets of the kitchen (not the shelves or display cabinets of a TV or wine unit)."""
    kitchen = kitchen_modules(spec)
    return any(m.id in kitchen and m.storey in ("upper", "loft") for m in shown(spec, seen))


def runs_seen(spec: KitchenSpec, seen: Seen | None, purpose: str) -> list[str]:
    """Ids of the runs of ``purpose`` (``tv``, ``unit``) with a cabinet in the picture, in the design's order."""
    ids = [r.id for r in spec.runs if r.purpose == purpose]
    if seen is None:
        return ids
    with_cabinet = {m.run for m in spec.module if seen.has(m.id)}
    return [r for r in ids if r in with_cabinet]


def window_seen(spec: KitchenSpec, seen: Seen | None, design_has_window: bool) -> bool:
    """Whether a window is in the picture: one the design places (``OPn``) or one of the floorplan's (``STRUCT-<element>``)."""
    if seen is None:
        return design_has_window
    if any(o.kind == "window" and not o.removed and seen.has(o.id) for o in spec.openings):
        return True
    fp = as_dict(spec.floorplan) or {}
    removed = {o.sourceElement for o in spec.openings if o.removed}
    for e in (as_dict(x) for x in as_list(fp.get("elements")) or []):
        if e is not None and e.get("tag") == "window" and e.get("kind") == "opening" and e.get("id") not in removed \
                and seen.has(f"STRUCT-{e.get('id')}"):
            return True
    return False
