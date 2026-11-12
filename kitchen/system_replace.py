"""Replacing a whole cabinet system (``runs.systems``) with a new one (pure, rule R1).

Two ways, both one operation the page previews before it is saved, and both touching that system only (never ``common``):

* **restyle** (``style_ops``): the cabinets stay; every one of them takes a style preset (front material, door style, handle).
* **relayout** (``relayout_ops``): the runs of the system stay where they are (place, angle, length, base depth); their cabinets are removed and new
  ones laid along them. The caller builds the new cabinets (from a sentence, in the shell: ``intent`` + ``run_template``) for the lengths
  ``run_slots`` gives; here they are placed, storeys the system never had are left out (no wall cabinets over an island), and what the sentence
  did not say about the fronts is taken from the old cabinets.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, cast

from . import appliance_models, builtin, runs
from .words import said
from .catalog import Catalog
from .cabinet_run import fit_depth
from .errors import InvalidInput
from .jsonview import as_dict, as_list
from .numeric import EPS_MM
from .i18n import pick
from .spec import KitchenSpec, LaidModule, Module, to_data

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


AUTO = "auto"


def _styles(catalog: Catalog) -> tuple[Style, ...]:
    return tuple(Style(it.id, pick(it.data.get("name"), "vi"), str(it.data["front"]), str(it.data["door"]), str(it.data["handle"]),
                       str(it.data["handleMaterial"])) for it in catalog.all("style"))


def styles(catalog: Catalog = builtin.CATALOG) -> tuple[Style, ...]:
    """The style presets, in catalog order (the catalog kind ``style``: workshop and user edit them)."""
    return catalog.derived("system_replace.styles", _styles)


def members(spec: KitchenSpec, system: str) -> list[Module]:
    """The cabinets of a system, in design order; InvalidInput when it has none."""
    by_module = runs.systems(spec)
    mods = [m for m in spec.module if by_module.get(m.id) == system]
    if not mods:
        raise InvalidInput(f"No cabinet belongs to system {system}", code="system-not-found", params={"system": system})
    return mods


def _front_of(spec: KitchenSpec, m: Module) -> str | None:
    return m.material or spec.common.material.get(m.storey) or spec.common.material.get("base")


def current_front(spec: KitchenSpec, mods: list[Module]) -> str | None:
    """The front material most of the system's cabinets show (their own, else the design's for their storey)."""
    fronts = Counter(f for m in mods if m.type not in FRONTLESS and (f := _front_of(spec, m)))
    return fronts.most_common(1)[0][0] if fronts else None


def pick_style(spec: KitchenSpec, mods: list[Module], wanted: str | None, catalog: Catalog = builtin.CATALOG) -> Style:
    """The preset ``wanted`` names; ``auto`` / None: the first preset whose front differs from what the system shows now."""
    all_styles = styles(catalog)
    by_id = {s.id: s for s in all_styles}
    if wanted and wanted != AUTO:
        if wanted not in by_id:
            raise InvalidInput(f"Unknown style {wanted}; use one of {', '.join(by_id)}", code="bad-style", params={"style": wanted, "allowed": ', '.join(by_id)})
        return by_id[wanted]
    if not all_styles:
        raise InvalidInput("The catalog has no style preset", code="bad-style")
    now = current_front(spec, mods)
    return next((s for s in all_styles if s.front != now), all_styles[0])


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
    depth: float | None = None        # the depth most of its base / tall cabinets have: the new ones keep it


def run_slots(spec: KitchenSpec, mods: list[Module]) -> list[Slot]:
    """The runs of the system, longest first (ties: run order). InvalidInput when its cabinets stand in no run (nothing to lay along)."""
    by_run: dict[str, list[Module]] = {}
    for m in mods:
        if m.run:
            by_run.setdefault(m.run, []).append(m)
    if not by_run:
        raise InvalidInput("These cabinets stand in no run, so they cannot be laid out again; restyle them instead", code="no-run")
    slots: list[Slot] = []
    for run_id, ms in by_run.items():
        body = [m for m in ms if m.storey in ("base", "tall")] or ms
        start = min(m.fromCorner for m in body)
        depths = Counter(m.depth for m in ms if m.storey in ("base", "tall"))
        slots.append(Slot(run_id, start, max(m.endAt for m in body) - start, frozenset(m.storey for m in ms),
                          depths.most_common(1)[0][0] if depths else None))
    order = [r.id for r in spec.runs]
    return sorted(slots, key=lambda s: (-s.length, order.index(s.run) if s.run in order else len(order)))


PLAIN_TYPE = {"base-sink": "base", "base-cooktop": "base", "base-oven": "base", "base-corner-sink": "base", "upper-hood": "upper"}


def plain_cabinets(modules: list[LaidModule]) -> list[LaidModule]:
    """The same cabinets without what belongs to the main run only: sink, hob, oven and hood cabinets become plain ones (their devices
    go), a fridge cabinet is left out. For the other runs of a system laid out from one sentence."""
    out: list[LaidModule] = []
    for m in modules:
        if m["type"] == "tall-fridge":
            continue
        entry = cast(LaidModule, {k: v for k, v in m.items() if k not in ("appliances", "appliance", "niche")})
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


EXTRA_FIELDS = ("name", "niche", "appliance", "appliances", "doors", "frontSections", "hingeSides", "doorStyle", "blindCorner", "blindSide", "shelfCount", "backPanel", "material")


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


APPLIANCE_WORDS = {      # a sentence that names the appliance asks for a new one: its old model is not kept (lower case, with diacritics)
    "cooktop": r"bếp\s*(?:từ|gas|ga|nấu|điện|hồng\s*ngoại|đôi|đơn)|(?<!\w)hob(?!\w)", "sink": r"chậu", "hood": r"hút\s*mùi",
    "fridge": r"tủ\s*lạnh", "oven": r"(?<!\w)lò(?!\w)", "faucet": r"(?<!\w)vòi(?!\w)", "tv": r"ti\s*vi|(?<!\w)tv(?!\w)",
}


def kept_models(spec: KitchenSpec, mods: list[Module], said: str = "", catalog: Catalog = builtin.CATALOG) -> dict[str, dict[str, Any]]:
    """The model each kind of appliance of the system was given (an explicit ``model``, e.g. a double sink picked in the popup), unless the
    sentence names that appliance: laying the system out again keeps it (it used to fall back to the default model)."""
    ids = {m.id for m in mods}
    text = (said or "").lower()
    out: dict[str, dict[str, Any]] = {}
    by_id = appliance_models.models(catalog)
    for a in spec.appliances:
        mid = getattr(a, "model", None)
        if a.module in ids and isinstance(mid, str) and mid in by_id and a.type not in out \
                and not re.search(APPLIANCE_WORDS.get(a.type, r"(?!x)x"), text):
            out[a.type] = by_id[mid]
    return out


def _keep_device(device: dict[str, Any], keep: dict[str, dict[str, Any]], width_mm: float,
                 catalog: Catalog = builtin.CATALOG) -> tuple[dict[str, Any], str | None]:
    """``(device, note)``: the device with its kept model when the new cabinet (``width_mm``) is wide enough, else as laid out."""
    model = keep.get(str(device.get("type")))
    if not model:
        return device, None
    need = appliance_models.needed_width(model, catalog)
    if need and need > width_mm + EPS_MM:
        return device, said("summary.model-not-kept", model=model['name'], need=need, width=width_mm)
    return {**device, **{k: v for k, v in appliance_models.changes_for(model).items() if v is not None}}, said("summary.model-kept", model=model['name'])


def _make_room(modules: list[LaidModule], models: dict[str, dict[str, Any]], catalog: Catalog = builtin.CATALOG) -> list[LaidModule]:
    """Widen the cabinet of a kept appliance that needs more room (a double sink in an 800 cabinet) by taking it from a plain base cabinet
    next to it (left at least ``MIN_PLAIN_MM`` wide); the worktop devices on it stay centred on it."""
    out: list[LaidModule] = sorted((cast(LaidModule, dict(m)) for m in modules), key=lambda m: m["s"])
    for host in out:
        devices = [d for d in [host.get("appliance"), *(host.get("appliances") or [])] if isinstance(d, dict)]
        need = max((appliance_models.needed_width(models[d["type"]], catalog) or 0.0 for d in devices if d.get("type") in models), default=0.0)
        delta = need - float(host["width"])
        if delta <= 1e-6:
            continue
        end = host["s"] + host["width"]
        after = [(True, n) for n in out if abs(n["s"] - end) <= 1]                         # the cabinet just right of it, then just left
        before = [(False, n) for n in out if abs(n["s"] + n["width"] - host["s"]) <= 1]
        for right, n in after + before:
            if n["type"] != "base" or n.get("appliance") or n.get("appliances") or float(n["width"]) - delta < MIN_PLAIN_MM:
                continue
            old_mid = host["s"] + host["width"] / 2
            n["width"] = float(n["width"]) - delta
            if right:
                n["s"] = float(n["s"]) + delta
            else:
                host["s"] = float(host["s"]) - delta
            host["width"] = float(host["width"]) + delta
            shift = host["s"] + host["width"] / 2 - old_mid
            def fix(d: dict[str, Any]) -> dict[str, Any]:
                return {**d, "center": d["center"] + shift} if isinstance(d.get("center"), (int, float)) else d
            if "appliance" in host:
                host["appliance"] = fix(host["appliance"])
            if "appliances" in host:
                host["appliances"] = [fix(d) for d in host["appliances"]]
            break
    return out


MIN_PLAIN_MM = 300.0


def relayout_ops(spec: KitchenSpec, mods: list[Module], laid: dict[str, list[LaidModule]], fronts: dict[str, Any],
                 asked: frozenset[str] = frozenset(), refused: frozenset[str] = frozenset(),
                 models: dict[str, dict[str, Any]] | None = None, catalog: Catalog = builtin.CATALOG) -> tuple[list[dict[str, Any]], list[str]]:
    """``(operations, summary)``: add ``laid[run]`` to each run, then remove every old cabinet of the system (modules as ``run_template`` gives
    them: ``{"type", "width", "s", "y", "height", "depth", ...}``, ``s`` from the slot's start). ``fronts``: what the sentence said about the fronts,
    ``{"material"?: {storey: name}, "handle"?: {...}}``; what it did not say is taken from the old cabinets of the same storey. ``models``:
    models to keep per kind of appliance (``kept_models``)."""
    slots = {s.run: s for s in run_slots(spec, mods)}
    old = _inherited(spec, mods)
    corner: list[tuple[str, float, float, float, float]] = []     # (run, s0, s1, y0, y1) the corner shelves keep: nothing new goes there
    for m in mods:
        if m.type == "corner-shelf" and m.run:
            corner.append((m.run, m.fromCorner, m.endAt, m.y, m.y + m.height))
            if m.turnsInto:
                corner.append((m.turnsInto, 0.0, float(m.rightLength or 0.0), m.y, m.y + m.height))
    blocked = 0
    ops: list[dict[str, Any]] = []      # the new cabinets go in first: a run left with no cabinet is removed with its last one
    summary: list[str] = []
    dropped: Counter[str] = Counter()
    kept: list[str] = []
    for run_id, modules in laid.items():
        slot = slots[run_id]
        added = 0
        if slot.depth is not None:                     # as deep as the run was (plan 10/11/2026, D3)
            modules = fit_depth(modules, slot.depth)
        if models:
            modules = _make_room(modules, models, catalog)
        for m in sorted(modules, key=lambda item: item["s"]):
            storey = storey_of(str(m["type"]))
            hood = m["type"] == "upper-hood"             # the hood always stands over the hob (rule of 10/11/2026), wall cabinets or not
            if not hood and (storey in refused or (storey not in slot.storeys and storey not in ("base", "tall") and storey not in asked)):
                dropped[storey] += 1
                continue
            entry: dict[str, Any] = {"type": m["type"], "wall": "island", "run": run_id, "fromCorner": slot.start + float(m["s"]),
                                     "width": float(m["width"]), "y": float(m["y"]), "height": float(m["height"]), "depth": float(m["depth"])}
            s0, y0 = entry["fromCorner"], entry["y"]
            if any(r == run_id and s0 < c1 - 1 and s0 + entry["width"] > c0 + 1 and y0 < z1 - 1 and y0 + entry["height"] > z0 + 1
                   for r, c0, c1, z0, z1 in corner):
                blocked += 1
                continue
            extra = cast("dict[str, Any]", m)                 # the optional fields, read by name
            for key in EXTRA_FIELDS:
                if extra.get(key):
                    entry[key] = extra[key]
            if models:
                for key in ("appliance", "appliances"):
                    value = entry.get(key)
                    one = as_dict(value)
                    devices: list[Any] = [one] if one is not None else as_list(value) or []
                    done: list[tuple[Any, str | None]] = [_keep_device(dd, models, entry["width"], catalog) if (dd := as_dict(d)) is not None else (d, None)
                                                         for d in devices]
                    kept += [note for _, note in done if note]
                    if devices:
                        entry[key] = done[0][0] if isinstance(value, dict) else [d for d, _ in done]
            mats: dict[str, Any] = fronts.get("material") or {}
            front = mats.get(storey) or mats.get("base" if storey == "tall" else storey)
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
        summary.append(said("summary.run-filled", run=run_id, n=added, length=slot.length))
    ops.extend({"op": "remove", "id": m.id, "closeGap": False} for m in mods)
    for m in mods:                     # a corner shelf joining two runs of the system stands outside both slots: it is built again as it was
        if m.type == "corner-shelf" and m.run:
            data = {k: v for k, v in to_data(m, exclude_none=True).items() if k != "id"}
            ops.append({"op": "add", "closeGap": False, "module": data})
            summary.append(said("summary.corner-shelf-again", id=m.id, a=m.run, b=m.turnsInto or m.run))
    if blocked:
        summary.append(said("summary.left-out-corner", n=blocked))
    summary.extend(dict.fromkeys(kept))
    for storey, n in sorted(dropped.items()):
        summary.append(said("summary.storey-left-out-asked" if storey in refused else "summary.storey-left-out-none", n=n, storey=said(f"storey.{storey}")))
    return ops, summary
