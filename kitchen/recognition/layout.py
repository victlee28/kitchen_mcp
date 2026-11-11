"""A recognised kitchen given BY RUNS (the cabinet-recognizer's ``recognized-runs/1``), checked. Nothing is trusted.

A run is a straight row of cabinets; each cabinet has ``s`` = its distance from the LEFT end of the run as seen by someone standing in front of
the doors (the same ``s`` as ``runs.RunFrame`` and ``run_line``). A joint ``(a, b)`` says: the END of run ``a`` meets the START of run ``b`` in an
inside corner of the room. That is all a line needs: put the main run on a line and the others follow (``run_line.plan_runs``); no wall names,
no origin, no mirroring. Unlike the flat ``Draft`` this keeps what the photo showed of each cabinet: doors, drawers, the blind part in a corner,
glass, the appliances standing in it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..jsonview import as_dict, as_list
from ..numeric import round_half_away
from ..spec import MODULE_TYPES
from .draft import MAX_MODULES, MIN_CONFIDENCE, DraftModule, confidence_of, number
from .operation import fridge_bay

SCHEMA = "recognized-runs/1"
RUN_IDS = ("left", "back", "right")
MIN_WIDTH, MAX_WIDTH = 150.0, 2000.0          # a blind-corner cabinet runs into the corner, so it may be wider than a free-standing one
MAX_LENGTH = 12000.0
SECTION_TYPES = ("niche", "drawer", "door")
DOOR_STYLES = ("flat", "frame", "glass")
APPLIANCE_TYPES = ("fridge", "sink", "faucet", "cooktop", "hood", "oven", "light", "other")
MAX_APPLIANCES = 4
RIGHT_ANGLE_TOLERANCE = 1.0


@dataclass(frozen=True)
class LayoutRun:
    id: str
    length: float
    modules: tuple[dict[str, Any], ...]       # each ready for ``run_line.plan_on_line``: type, width, s, y, height, depth + what the cabinet carries


@dataclass(frozen=True)
class Layout:
    runs: tuple[LayoutRun, ...]
    joints: tuple[tuple[str, str], ...]       # (a, b): the end of run a meets the start of run b at a right angle
    rejected: tuple[dict[str, Any], ...]      # [{"run", "index", "reason"}]
    notes: tuple[str, ...]
    levels: tuple[tuple[str, float], ...] = ()   # the recognised kitchen's own levels (``LEVELS`` of spec.Common), when the recognizer gives them

    @property
    def count(self) -> int:
        return sum(len(r.modules) for r in self.runs)

    def to_data(self) -> dict[str, Any]:
        return {"runs": [{"id": r.id, "length": r.length, "modules": [dict(m) for m in r.modules]} for r in self.runs],
                "joints": [list(j) for j in self.joints], "rejected": list(self.rejected), "notes": list(self.notes),
                **({"levels": dict(self.levels)} if self.levels else {})}


def _positive_list(value: Any, limit: int) -> list[float] | None:
    items = as_list(value)
    if not items or len(items) > limit:
        return None
    nums = [number(v) for v in items]
    return None if any(n is None or n <= 0 for n in nums) else [float(n) for n in nums if n is not None]


def _sections(value: Any) -> list[dict[str, Any]] | None:
    items = as_list(value)
    if not items or len(items) > 8:
        return None
    out: list[dict[str, Any]] = []
    for each in items:
        item = as_dict(each)
        height = number(item.get("height")) if item is not None else None
        if item is None or item.get("type") not in SECTION_TYPES or height is None or height <= 0:
            return None
        out.append({"type": item["type"], "height": height})
    return out


OVEN_NICHE_WIDTH = 560.0            # knowledge APPLIANCE-OVEN-60 / -45: recess of a built-in oven, 60 cm single and 45 cm compact
OVEN_NICHE_HEIGHTS = (590.0, 450.0)
PANEL = 18.0                        # the default board thickness (spec.Common.doorThickness): an appliance needs one board of air on each side
HOOD_MAX_WIDTH, HOOD_HEIGHT = 730.0, 165.0     # the built-in hood ``intent`` gives a new kitchen (no source: this project's own convention)


LEVELS = ("plinthHeight", "baseTop", "countertop", "countertopThickness", "baseDepth", "upperBottom", "upperTierSplit", "cabinetTop", "upperDepth")
CEILING_GAP = 30.0                  # air between the top of the cabinets and the ceiling when the ceiling was not seen


def _levels(raw: Any) -> tuple[tuple[str, float], ...]:
    """The numeric levels of a recognised ``common`` that are plausible on their own (0 < v <= 4000 mm); the spec's own validation judges the set."""
    obj = as_dict(raw)
    if obj is None:
        return ()
    out: list[tuple[str, float]] = []
    for key in LEVELS:
        v = number(obj.get(key))
        if v is not None and 0 < v <= 4000:
            out.append((key, float(v)))
    return tuple(out)


def common_changes(common: dict[str, Any], layout: Layout, ceiling: float | None, materials: dict[str, str]) -> dict[str, Any]:
    """What a recognised kitchen changes in the design's ``common`` when it REPLACES the cabinets: its own levels (so the worktop sits on the
    cabinets that were seen), the ceiling (the one seen, else kept, but never lower than the cabinets plus a gap) and the materials seen.
    Only real differences are returned; {} when nothing changes."""
    out: dict[str, Any] = {k: v for k, v in layout.levels if common.get(k) != v}
    seen = dict(layout.levels)
    top = seen["cabinetTop"] if "cabinetTop" in seen else float(common["cabinetTop"])
    height = max(ceiling if ceiling is not None else float(common["ceiling"]), top + CEILING_GAP)
    if height != common["ceiling"]:
        out["ceiling"] = height
    merged = {**common.get("material", {}), **materials}
    if merged != common.get("material", {}):
        out["material"] = merged
    return out


def appliance_size(kind: str, width: float, niche: float | None = None) -> str | None:
    """Stock size of an appliance fitted into a cabinet ``width`` wide (``niche``: height of the cabinet's open section, for an oven); None
    for kinds that need none. A photo gives no reliable size for these, and without one they are neither drawn nor checked.

    Sink, hob, tap, hood: the sizes ``intent`` gives a new kitchen. Oven: the recess a built-in oven is made for (560 wide; 590 high for a
    60 cm single oven, 450 for a compact one), the largest that fits the niche; a lower niche gets what fits (a microwave)."""
    if kind == "sink":
        return f"{min(780.0, width - 40.0):g} × 430"
    if kind == "cooktop":
        return f"{min(730.0, width - 10.0):g} × 430"
    if kind == "faucet":
        return "cao 300"
    if kind == "hood":
        return f"{min(HOOD_MAX_WIDTH, width - 40.0):g} × {HOOD_HEIGHT:g}"
    if kind == "oven":
        room = niche - 2 * PANEL if niche else OVEN_NICHE_HEIGHTS[0]
        height = next((h for h in OVEN_NICHE_HEIGHTS if h <= room + 0.5), room)
        return f"{min(OVEN_NICHE_WIDTH, width - 2 * PANEL):g} × {height:g}"
    return None


def _appliances(value: Any, width: float, niche: float | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in (as_dict(x) for x in as_list(value) or []):
        if item is not None and item.get("type") in APPLIANCE_TYPES and len(out) < MAX_APPLIANCES:
            entry: dict[str, Any] = {"type": item["type"], "name": str(item.get("name") or "")[:60]}
            size = appliance_size(item["type"], width, niche)
            if size:
                entry["dimensions"] = size
            out.append(entry)
    return out


def _module(value: Any, length: float) -> tuple[dict[str, Any] | None, str]:
    """``(module, "")`` or ``(None, reason)``."""
    raw = as_dict(value)
    if raw is None:
        return None, "not an object"
    mtype = raw.get("type")
    if mtype not in MODULE_TYPES or mtype == "corner-shelf":
        return None, f"unknown or unsupported module type {mtype!r}"
    nums = {k: number(raw.get(k)) for k in ("s", "width", "y", "height", "depth")}
    if any(v is None for v in nums.values()):
        return None, "s, width, y, height and depth must be numbers"
    s, width, y, height, depth = (float(nums[k] or 0.0) for k in ("s", "width", "y", "height", "depth"))
    if not MIN_WIDTH <= width <= MAX_WIDTH:
        return None, f"width must be {MIN_WIDTH:g}-{MAX_WIDTH:g} mm, got {width:g}"
    if s < 0 or s + width > length + 1.0:
        return None, f"the cabinet ({s:g}..{s + width:g}) is outside its run (0..{length:g})"
    if y < 0 or height <= 0 or depth <= 0 or y + height > 4000 or depth > 1200:
        return None, "y, height or depth is out of range"
    out: dict[str, Any] = {"type": mtype, "width": round_half_away(width, 0), "s": round_half_away(s, 0), "y": y, "height": height, "depth": depth}
    name = raw.get("name")
    if isinstance(name, str) and name.strip():
        out["name"] = name.strip()[:60]
    blind = number(raw.get("blindCorner"))
    if blind is not None and 0 < blind < width:
        out["blindCorner"] = blind
    doors = _positive_list(raw.get("doors"), 6)
    if doors is not None and abs(sum(doors) + out.get("blindCorner", 0.0) - width) <= 2.0:      # doors that do not fill the front are dropped, not guessed
        out["doors"] = doors
    sections = _sections(raw.get("frontSections"))
    if sections is not None and sum(t["height"] for t in sections) <= height + 1.0:
        out["frontSections"] = sections
    if raw.get("doorStyle") in DOOR_STYLES:
        out["doorStyle"] = raw["doorStyle"]
    shelves = raw.get("shelfCount")
    if isinstance(shelves, int) and not isinstance(shelves, bool) and 1 <= shelves <= 8:
        out["shelfCount"] = shelves
    fronts: list[dict[str, Any]] = out.get("frontSections") or []
    niches = [float(t["height"]) for t in fronts if t.get("type") == "niche"]
    devices = _appliances(raw.get("appliances"), out["width"], niches[0] if niches else None)
    if mtype == "tall-fridge":
        niche = number(raw.get("niche"))
        extra, fridge = fridge_bay(DraftModule(type=mtype, wall="back", width=out["width"], niche=niche if niche and niche > 0 else None), height, depth)
        out.update(extra)
        devices = [fridge, *[d for d in devices if d["type"] != "fridge"]]
    if devices:
        out["appliances"] = devices
    confidence = confidence_of(raw.get("confidence"))
    out["confidence"] = confidence
    out["needsReview"] = confidence < MIN_CONFIDENCE
    return out, ""


def build_layout(raw: Any) -> Layout | None:
    """A ``recognized-runs/1`` document -> ``Layout``; None when ``raw`` is not such a document or no cabinet in it is usable.
    Never raises on bad content: unusable cabinets and joints are listed in ``rejected`` / ``notes``."""
    doc = as_dict(raw)
    runs_raw = as_list(doc.get("runs")) if doc is not None else None
    if doc is None or doc.get("schema") != SCHEMA or runs_raw is None:
        return None
    runs: list[LayoutRun] = []
    rejected: list[dict[str, Any]] = []
    notes: list[str] = []
    budget = MAX_MODULES
    for value in runs_raw:
        item = as_dict(value) or {}
        rid = item.get("id")
        length = number(item.get("length"))
        if rid not in RUN_IDS or any(r.id == rid for r in runs) or length is None or not 0 < length <= MAX_LENGTH:
            notes.append(f"run {rid!r} was ignored (unknown id, repeated, or no usable length)")
            continue
        modules: list[dict[str, Any]] = []
        for index, entry in enumerate(as_list(item.get("modules")) or []):
            if budget <= 0:
                notes.append(f"cabinets beyond the first {MAX_MODULES} were ignored")
                break
            module, reason = _module(entry, float(length))
            if module is None:
                rejected.append({"run": rid, "index": index, "reason": reason})
            else:
                modules.append(module)
                budget -= 1
        if modules:
            runs.append(LayoutRun(str(rid), float(length), tuple(sorted(modules, key=lambda m: (m["y"], m["s"])))))
    if not runs:
        return None
    have = {r.id for r in runs}
    joints: list[tuple[str, str]] = []
    for jv in as_list(doc.get("joints")) or []:
        joint = as_dict(jv) or {}
        a, b = joint.get("a"), joint.get("b")
        angle = number(joint.get("angle"))
        if a not in have or b not in have or a == b or (str(a), str(b)) in joints:
            continue
        if angle is None or abs(angle - 90.0) > RIGHT_ANGLE_TOLERANCE:
            notes.append(f"the corner between {a} and {b} is not a right angle ({angle!r}); the two runs are not joined")
            continue
        joints.append((str(a), str(b)))
    return Layout(tuple(runs), tuple(joints), tuple(rejected), tuple(notes), _levels(doc.get("common")))
