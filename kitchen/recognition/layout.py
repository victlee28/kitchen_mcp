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

from ..numeric import round_half_away
from ..spec import MODULE_TYPES
from .draft import MAX_MODULES, MIN_CONFIDENCE, DraftModule, _conf, _num
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

    @property
    def count(self) -> int:
        return sum(len(r.modules) for r in self.runs)

    def to_data(self) -> dict[str, Any]:
        return {"runs": [{"id": r.id, "length": r.length, "modules": [dict(m) for m in r.modules]} for r in self.runs],
                "joints": [list(j) for j in self.joints], "rejected": list(self.rejected), "notes": list(self.notes)}


def _positive_list(value: Any, limit: int) -> list[float] | None:
    if not isinstance(value, list) or not value or len(value) > limit:
        return None
    nums = [_num(v) for v in value]
    return None if any(n is None or n <= 0 for n in nums) else [float(n) for n in nums if n is not None]


def _sections(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or not value or len(value) > 8:
        return None
    out: list[dict[str, Any]] = []
    for item in value:
        height = _num(item.get("height")) if isinstance(item, dict) else None
        if not isinstance(item, dict) or item.get("type") not in SECTION_TYPES or height is None or height <= 0:
            return None
        out.append({"type": item["type"], "height": height})
    return out


def _appliances(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict) and item.get("type") in APPLIANCE_TYPES and len(out) < MAX_APPLIANCES:
            out.append({"type": item["type"], "name": str(item.get("name") or "")[:60]})
    return out


def _module(raw: Any, length: float) -> tuple[dict[str, Any] | None, str]:
    """``(module, "")`` or ``(None, reason)``."""
    if not isinstance(raw, dict):
        return None, "not an object"
    mtype = raw.get("type")
    if mtype not in MODULE_TYPES or mtype == "corner-shelf":
        return None, f"unknown or unsupported module type {mtype!r}"
    nums = {k: _num(raw.get(k)) for k in ("s", "width", "y", "height", "depth")}
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
    blind = _num(raw.get("blindCorner"))
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
    devices = _appliances(raw.get("appliances"))
    if mtype == "tall-fridge":
        niche = _num(raw.get("niche"))
        extra, fridge = fridge_bay(DraftModule(type=mtype, wall="back", width=out["width"], niche=niche if niche and niche > 0 else None), height, depth)
        out.update(extra)
        devices = [fridge, *[d for d in devices if d["type"] != "fridge"]]
    if devices:
        out["appliances"] = devices
    confidence = _conf(raw.get("confidence"))
    out["confidence"] = confidence
    out["needsReview"] = confidence < MIN_CONFIDENCE
    return out, ""


def build_layout(raw: Any) -> Layout | None:
    """A ``recognized-runs/1`` document -> ``Layout``; None when ``raw`` is not such a document or no cabinet in it is usable.
    Never raises on bad content: unusable cabinets and joints are listed in ``rejected`` / ``notes``."""
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA or not isinstance(raw.get("runs"), list):
        return None
    runs: list[LayoutRun] = []
    rejected: list[dict[str, Any]] = []
    notes: list[str] = []
    budget = MAX_MODULES
    for item in raw["runs"]:
        rid = item.get("id") if isinstance(item, dict) else None
        length = _num(item.get("length")) if isinstance(item, dict) else None
        if rid not in RUN_IDS or any(r.id == rid for r in runs) or length is None or not 0 < length <= MAX_LENGTH:
            notes.append(f"run {rid!r} was ignored (unknown id, repeated, or no usable length)")
            continue
        modules: list[dict[str, Any]] = []
        raw_modules = item.get("modules")
        for index, entry in enumerate(raw_modules if isinstance(raw_modules, list) else []):
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
    raw_joints = raw.get("joints")
    for joint in raw_joints if isinstance(raw_joints, list) else []:
        a, b = (joint.get("a"), joint.get("b")) if isinstance(joint, dict) else (None, None)
        angle = _num(joint.get("angle")) if isinstance(joint, dict) else None
        if a not in have or b not in have or a == b or (str(a), str(b)) in joints:
            continue
        if angle is None or abs(angle - 90.0) > RIGHT_ANGLE_TOLERANCE:
            notes.append(f"the corner between {a} and {b} is not a right angle ({angle!r}); the two runs are not joined")
            continue
        joints.append((str(a), str(b)))
    return Layout(tuple(runs), tuple(joints), tuple(rejected), tuple(notes))
