"""Check and normalise a raw recognizer draft. Nothing is trusted: unknown types, walls and silly sizes are rejected WITH a reason."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..jsonview import as_dict, as_list
from ..numeric import round_half_away
from ..spec import MODULE_TYPES

WALLS = ("back", "left", "right")
MIN_WIDTH, MAX_WIDTH = 150.0, 1500.0
MIN_CONFIDENCE = 0.5          # below this a module is kept but flagged for review
MAX_MODULES = 60
MATERIAL_SLOTS = ("base", "upper", "tall", "countertop", "wall", "floor")


@dataclass
class DraftModule:
    type: str
    wall: str
    width: float
    fromCorner: float | None = None
    height: float | None = None
    depth: float | None = None
    y: float | None = None
    niche: float | None = None
    confidence: float = 1.0
    label: str = ""

    @property
    def needs_review(self) -> bool:
        return self.confidence < MIN_CONFIDENCE


@dataclass
class Draft:
    modules: list[DraftModule] = field(default_factory=list[DraftModule])
    ceiling: float | None = None
    materials: dict[str, str] = field(default_factory=dict[str, str])
    confidence: float = 1.0
    rejected: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])     # [{"index", "reason", "raw"}]
    notes: list[str] = field(default_factory=list[str])

    def to_data(self) -> dict[str, Any]:
        return {"modules": [{"type": m.type, "wall": m.wall, "width": m.width, "fromCorner": m.fromCorner, "height": m.height, "depth": m.depth,
                             "confidence": m.confidence, "label": m.label, "needsReview": m.needs_review} for m in self.modules],
                "ceiling": self.ceiling, "materials": self.materials, "confidence": self.confidence, "rejected": self.rejected, "notes": self.notes}


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and abs(value) != float("inf") else None


def confidence_of(value: Any) -> float:
    n = number(value)
    return 1.0 if n is None else round_half_away(min(1.0, max(0.0, n)), 2)


def _module(index: int, value: Any, rejected: list[dict[str, Any]]) -> DraftModule | None:
    obj = as_dict(value)

    def reject(reason: str) -> None:
        rejected.append({"index": index, "reason": reason, "raw": obj if obj is not None else str(value)[:80]})
    if obj is None:
        return reject("not an object") or None
    raw = obj
    mtype = raw.get("type")
    if mtype not in MODULE_TYPES or mtype == "corner-shelf":
        return reject(f"unknown or unsupported module type {mtype!r}") or None
    wall = raw.get("wall", "back")
    if wall not in WALLS:
        return reject(f"wall {wall!r} is not one of {', '.join(WALLS)}") or None
    width = number(raw.get("width"))
    if width is None or not MIN_WIDTH <= width <= MAX_WIDTH:
        return reject(f"width must be {MIN_WIDTH:g}-{MAX_WIDTH:g} mm, got {raw.get('width')!r}") or None
    start = number(raw.get("fromCorner"))
    if raw.get("fromCorner") is not None and (start is None or start < 0):
        return reject("fromCorner must be >= 0") or None
    level = number(raw.get("y"))
    if raw.get("y") is not None and (level is None or level < 0):
        return reject("y must be >= 0") or None
    niche = number(raw.get("niche"))
    if raw.get("niche") is not None and (niche is None or niche <= 0):
        return reject("niche must be positive") or None
    sizes = {k: number(raw.get(k)) for k in ("height", "depth")}
    if any(raw.get(k) is not None and (v is None or v <= 0) for k, v in sizes.items()):
        return reject("height and depth must be positive") or None
    return DraftModule(type=mtype, wall=wall, width=round_half_away(width, 0), fromCorner=None if start is None else round_half_away(start, 0),
                       height=sizes["height"], depth=sizes["depth"], y=level, niche=niche, confidence=confidence_of(raw.get("confidence")), label=str(raw.get("label") or "")[:60])


def build_draft(value: Any) -> Draft:
    """Raw recognizer output -> Draft. Never raises on bad content: whatever is unusable is listed in ``rejected``."""
    draft = Draft()
    raw = as_dict(value)
    if raw is None:
        draft.notes.append("recognizer returned something other than an object")
        return draft
    items = as_list(raw.get("modules")) or []
    if len(items) > MAX_MODULES:
        draft.notes.append(f"{len(items) - MAX_MODULES} modules beyond the first {MAX_MODULES} were ignored")
        items = items[:MAX_MODULES]
    for i, item in enumerate(items):
        got = _module(i, item, draft.rejected)
        if got:
            draft.modules.append(got)
    room = as_dict(raw.get("room")) or {}
    ceiling = number(room.get("ceiling"))
    draft.ceiling = ceiling if ceiling is not None and 2000 <= ceiling <= 4000 else None
    mats = as_dict(raw.get("materials")) or {}
    draft.materials = {k: v.strip() for k, v in mats.items() if k in MATERIAL_SLOTS and isinstance(v, str) and v.strip()}
    draft.confidence = confidence_of(raw.get("confidence")) if raw.get("confidence") is not None else (
        round_half_away(sum(m.confidence for m in draft.modules) / len(draft.modules), 2) if draft.modules else 0.0)
    draft.notes += [n for n in as_list(raw.get("notes")) or [] if isinstance(n, str)][:10]
    return draft
