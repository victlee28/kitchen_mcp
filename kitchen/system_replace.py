"""Replacing a whole cabinet system (``runs.systems``) with a new one (pure, rule R1).

Two ways, both one operation the page previews before it is saved, and both touching that system only (never ``common``):

* **restyle** (``style_ops``): the cabinets stay; every one of them takes a style preset (front material, door style, handle).
* **relayout** (``relayout_ops``): the runs of the system stay where they are (place, angle, length); their cabinets are removed and new
  ones laid along them. The caller builds the new cabinets (from a sentence, in the shell: ``intent`` + ``run_template``) for the lengths
  ``run_slots`` gives; here they are placed, storeys the system never had are left out (no wall cabinets over an island), and what the sentence
  did not say about the fronts is taken from the old cabinets.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from . import runs
from .errors import InvalidInput
from .spec import KitchenSpec, Module

FRONTLESS = ("corner-shelf", "upper-open")            # no doors or drawer fronts: no front material, door style or handle
OWN_DOOR = ("upper-glass",)                           # the door style is the cabinet's own (glass): left as it is


@dataclass(frozen=True)
class Style:
    """A style preset for a whole cabinet system. ``front``: front material (the same names the design uses, see ``vocab``)."""
    id: str
    name: str
    front: str
    door: str               # flat | frame | glass
    handle: str             # bar | knob | concealed | none
    handle_material: str


STYLES: tuple[Style, ...] = (
    Style("modern-white", "Hiện đại trắng bóng", "Acrylic trắng bóng", "flat", "concealed", "Nhôm"),
    Style("warm-oak", "Gỗ sồi ấm", "Laminate vân gỗ sồi sáng", "flat", "bar", "Nhôm đen mờ"),
    Style("classic-sage", "Cổ điển xanh rêu", "Sơn xanh rêu mờ", "frame", "knob", "Đồng thau"),
    Style("minimal-grey", "Tối giản xám đậm", "Acrylic xám đậm", "flat", "concealed", "Nhôm"),
    Style("shaker-cream", "Shaker kem", "Sơn kem mờ", "frame", "bar", "Đồng thau xước"),
    Style("walnut-luxe", "Gỗ óc chó sang trọng", "Veneer gỗ óc chó", "flat", "bar", "Đồng vàng"),
)
STYLE_BY_ID = {s.id: s for s in STYLES}
AUTO = "auto"


def members(spec: KitchenSpec, system: str) -> list[Module]:
    """The cabinets of a system, in design order; InvalidInput when it has none."""
    by_module = runs.systems(spec)
    mods = [m for m in spec.module if by_module.get(m.id) == system]
    if not mods:
        raise InvalidInput(f"No cabinet belongs to system {system}", code="system-not-found")
    return mods


def _front_of(spec: KitchenSpec, m: Module) -> str | None:
    return m.material or spec.common.material.get(m.storey) or spec.common.material.get("base")


def current_front(spec: KitchenSpec, mods: list[Module]) -> str | None:
    """The front material most of the system's cabinets show (their own, else the design's for their storey)."""
    fronts = Counter(f for m in mods if m.type not in FRONTLESS and (f := _front_of(spec, m)))
    return fronts.most_common(1)[0][0] if fronts else None


def pick_style(spec: KitchenSpec, mods: list[Module], wanted: str | None) -> Style:
    """The preset ``wanted`` names; ``auto`` / None: the first preset whose front differs from what the system shows now."""
    if wanted and wanted != AUTO:
        if wanted not in STYLE_BY_ID:
            raise InvalidInput(f"Unknown style {wanted}; use one of {', '.join(STYLE_BY_ID)}", code="bad-style")
        return STYLE_BY_ID[wanted]
    now = current_front(spec, mods)
    return next((s for s in STYLES if s.front != now), STYLES[0])


def style_ops(spec: KitchenSpec, mods: list[Module], style: Style) -> list[dict[str, Any]]:
    """One ``update`` per cabinet with a front: the preset's front material, door style (not on glass-door cabinets) and handle."""
    ops: list[dict[str, Any]] = []
    for m in mods:
        if m.type in FRONTLESS:
            continue
        handle = {**dict(_handle_of(m)), "variant": style.handle, "material": style.handle_material}     # its own handle length stays
        changes: dict[str, Any] = {"material": style.front, "handle": handle}
        if m.type not in OWN_DOOR:
            changes["doorStyle"] = style.door
        ops.append({"op": "update", "id": m.id, "changes": changes})
    if not ops:
        raise InvalidInput("The system has no cabinet with doors or drawer fronts to restyle", code="nothing-to-restyle")
    return ops


@dataclass(frozen=True)
class Slot:
    """A run of the system to lay again: from ``start`` (s, mm) over ``length``; ``storeys``: the storeys it had (base, upper, loft, tall)."""
    run: str
    start: float
    length: float
    storeys: frozenset[str]


def run_slots(spec: KitchenSpec, mods: list[Module]) -> list[Slot]:
    """The runs of the system, longest first (ties: run order). InvalidInput when its cabinets stand in no run (nothing to lay along)."""
    by_run: dict[str, list[Module]] = {}
    for m in mods:
        if m.run:
            by_run.setdefault(m.run, []).append(m)
    if not by_run:
        raise InvalidInput("These cabinets stand in no run, so they cannot be laid out again; restyle them instead", code="no-run")
    slots = []
    for run_id, ms in by_run.items():
        body = [m for m in ms if m.storey in ("base", "tall")] or ms
        start = min(m.fromCorner for m in body)
        slots.append(Slot(run_id, start, max(m.endAt for m in body) - start, frozenset(m.storey for m in ms)))
    order = [r.id for r in spec.runs]
    return sorted(slots, key=lambda s: (-s.length, order.index(s.run) if s.run in order else len(order)))


PLAIN_TYPE = {"base-sink": "base", "base-cooktop": "base", "base-oven": "base", "base-corner-sink": "base", "upper-hood": "upper"}


def plain_cabinets(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same cabinets without what belongs to the main run only: sink, hob, oven and hood cabinets become plain ones (their devices
    go), a fridge cabinet is left out. For the other runs of a system laid out from one sentence."""
    out = []
    for m in modules:
        if m["type"] == "tall-fridge":
            continue
        entry = {k: v for k, v in m.items() if k not in ("appliances", "appliance", "niche")}
        if m["type"] in PLAIN_TYPE:
            entry["type"] = PLAIN_TYPE[m["type"]]
            entry.pop("name", None)
        out.append(entry)
    return out


STOREY_OF_TYPE = {"upper-loft": "loft", "corner-shelf": "corner"}


def storey_of(module_type: str) -> str:
    """The storey of a module type (as ``Module.storey``)."""
    if module_type in STOREY_OF_TYPE:
        return STOREY_OF_TYPE[module_type]
    return "tall" if module_type.startswith("tall") else "upper" if module_type.startswith("upper") else "base"


EXTRA_FIELDS = ("name", "niche", "appliance", "appliances", "doors", "frontSections", "hingeSides", "doorStyle", "blindCorner", "blindSide", "shelfCount")


def _handle_of(m: Module) -> tuple[tuple[str, Any], ...]:
    """The module's own handle settings (only those it sets) as sorted pairs; empty when it has none."""
    h = m.handle
    return tuple((k, v) for k, v in (("length", h.length), ("material", h.material), ("variant", h.variant)) if v is not None) if h else ()


def _inherited(spec: KitchenSpec, mods: list[Module]) -> dict[str, dict[str, Any]]:
    """Per storey, what the old cabinets showed most: their own front material, door style and handle (only what they set themselves)."""
    out: dict[str, dict[str, Any]] = {}
    for storey in ("base", "upper", "loft", "tall"):
        ms = [m for m in mods if m.storey == storey and m.type not in FRONTLESS]
        keep: dict[str, Any] = {}
        for key in ("material", "doorStyle"):
            seen = Counter(v for m in ms if (v := getattr(m, key)))
            if seen:
                keep[key] = seen.most_common(1)[0][0]
        handles = Counter(h for m in ms if (h := _handle_of(m)))
        if handles:
            keep["handle"] = dict(handles.most_common(1)[0][0])
        out[storey] = keep
    return out


def relayout_ops(spec: KitchenSpec, mods: list[Module], laid: dict[str, list[dict[str, Any]]], fronts: dict[str, Any],
                 asked: frozenset[str] = frozenset(), refused: frozenset[str] = frozenset()) -> tuple[list[dict[str, Any]], list[str]]:
    """``(operations, summary)``: add ``laid[run]`` to each run, then remove every old cabinet of the system (modules as ``run_template`` gives
    them: ``{"type", "width", "s", "y", "height", "depth", ...}``, ``s`` from the slot's start). ``fronts``: what the sentence said about the fronts,
    ``{"material"?: {storey: name}, "handle"?: {...}}``; what it did not say is taken from the old cabinets of the same storey."""
    slots = {s.run: s for s in run_slots(spec, mods)}
    old = _inherited(spec, mods)
    ops: list[dict[str, Any]] = []      # the new cabinets go in first: a run left with no cabinet is removed with its last one
    summary: list[str] = []
    dropped: Counter[str] = Counter()
    for run_id, modules in laid.items():
        slot = slots[run_id]
        added = 0
        for m in sorted(modules, key=lambda item: item["s"]):
            storey = storey_of(str(m["type"]))
            if storey in refused or (storey not in slot.storeys and storey not in ("base", "tall") and storey not in asked):
                dropped[storey] += 1
                continue
            entry: dict[str, Any] = {"type": m["type"], "wall": "island", "run": run_id, "fromCorner": slot.start + float(m["s"]),
                                     "width": float(m["width"]), "y": float(m["y"]), "height": float(m["height"]), "depth": float(m["depth"])}
            for key in EXTRA_FIELDS:
                if m.get(key):
                    entry[key] = m[key]
            front = (fronts.get("material") or {}).get(storey) or (fronts.get("material") or {}).get("base" if storey == "tall" else storey)
            keep = old.get(storey, {})
            if m["type"] not in FRONTLESS:
                if front or keep.get("material"):
                    entry["material"] = front or keep["material"]
                if "doorStyle" not in entry and keep.get("doorStyle") and m["type"] not in OWN_DOOR:
                    entry["doorStyle"] = keep["doorStyle"]
                handle = fronts.get("handle") or keep.get("handle")
                if handle:
                    entry["handle"] = dict(handle)
            ops.append({"op": "add", "closeGap": False, "module": entry})
            added += 1
        summary.append(f"Run {run_id}: {added} cabinets over {slot.length:g} mm")
    ops.extend({"op": "remove", "id": m.id, "closeGap": False} for m in mods)
    for storey, n in sorted(dropped.items()):
        summary.append(f"{n} {storey} cabinets left out: " + ("the sentence asks so" if storey in refused else "the system had none on that storey"))
    return ops, summary
