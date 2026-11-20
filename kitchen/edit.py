"""Lệnh sửa thiết kế: hàm thuần, nhận spec cũ trả spec mới (không sửa tại chỗ).

"Dồn dãy" (don_day=True): các module cùng tường, cùng dải cao độ, nằm phía sau điểm thay đổi
được dịch theo để không chồng/hở. Tủ cao (cao*) chắn cả tầng dưới lẫn tầng trên nên được tính chung.
"""
from __future__ import annotations

import re

from typing import Any

from .numeric import round_half_away
from . import builtin, defaults, tv_system
from .catalog import Catalog
from .spec import Appliance, KitchenSpec, Module, Run, from_data, to_data
from .errors import InvalidInput, NotFound
from .jsonview import as_dict, as_list
from . import cabinet_types


def _clone(spec: KitchenSpec) -> KitchenSpec:
    return from_data(KitchenSpec, to_data(spec))


def _same_run(a: Module, b: Module) -> bool:
    """Two cabinets of the same run that overlap in height (the row that closes up when one of them changes)."""
    return bool(a.run) and a.run == b.run and min(a.y + a.height, b.y + b.height) - max(a.y, b.y) > 1


def _shift(spec: KitchenSpec, ref: Module, shift_from: float, delta: float, skip: set[str]):
    if not delta:
        return
    moved = [m for m in spec.module if m.id not in skip and _same_run(m, ref) and m.storey != "corner" and m.fromCorner >= shift_from - 1]
    if delta < 0:   # closing a gap: a tall cabinet slides only into room that is free on every storey; else it and what follows it stay
        blocked = [t for t in moved if t.storey == "tall" and _tall_blocked(spec, t, delta, moved, skip)]
        if blocked:
            stop = min(t.fromCorner for t in blocked)
            moved = [m for m in moved if m.fromCorner < stop - 1]
    # tủ cao bị dịch thì kéo theo mọi module cùng tường phía sau nó (mọi tầng)
    for tall in [m for m in moved if m.storey == "tall"]:
        moved += [m for m in spec.module if m.run == tall.run and m.storey != "corner" and m.fromCorner >= tall.fromCorner - 1 and m.id not in skip and m not in moved]
    for m in moved:
        m.fromCorner = max(0.0, m.fromCorner + delta)
    _move_devices(spec, moved, delta)


def _move_devices(spec: KitchenSpec, moved: list[Module], delta: float) -> None:
    """A device placed at a point along the run of the cabinet it stands in (``center``) moves with that cabinet."""
    ids = {m.id for m in moved}
    for tb in spec.appliances:
        if tb.module in ids and tb.center is not None:
            tb.center += delta


def _anchored_end(spec: KitchenSpec, ref: Module) -> Run | None:
    """The run of ``ref`` when its END stays put (``Run.anchor == "end"``): there closing a gap moves the cabinets before the change."""
    run = next((r for r in spec.runs if r.id == ref.run), None) if ref.run else None
    return run if run is not None and run.anchor == "end" else None


def _shift_back(spec: KitchenSpec, ref: Module, upto: float, delta: float, skip: set[str]) -> None:
    """``_shift`` for a run anchored at its end: the cabinets of ``ref``'s row that end at or before ``upto`` move by ``-delta`` (a corner shelf stays,
    as in a corner it always did); a tall cabinet that moves takes every storey before it along. The run's start is then kept at s = 0."""
    if not delta:
        return
    moved = [m for m in spec.module if m.id not in skip and _same_run(m, ref) and m.storey != "corner" and m.endAt <= upto + 1]
    if delta < 0:   # closing a gap: a tall cabinet slides only into room free on every storey
        blocked = [t for t in moved if t.storey == "tall" and _tall_blocked(spec, t, -delta, moved, skip)]
        if blocked:
            stop = max(t.endAt for t in blocked)
            moved = [m for m in moved if m.endAt > stop + 1]
    for tall in [m for m in moved if m.storey == "tall"]:
        moved += [m for m in spec.module if m.run == tall.run and m.storey != "corner" and m.endAt <= tall.endAt + 1 and m.id not in skip and m not in moved]
    for m in moved:
        m.fromCorner = m.fromCorner - delta
    _move_devices(spec, moved, -delta)


def _keep_start(spec: KitchenSpec, run_id: str | None) -> None:
    """A run anchored at its end whose cabinets now start before (or after) s = 0: its origin moves there, so nothing moves in the room."""
    run = next((r for r in spec.runs if r.id == run_id), None) if run_id else None
    mods = [m for m in spec.module if m.run == run_id]
    if run is None or run.anchor != "end" or not mods:
        return
    lo = min(m.fromCorner for m in mods)
    if abs(lo) <= 1e-6:
        return
    from .runs import RunFrame
    run.x, run.z = RunFrame(run.id, run.x, run.z, run.yaw).to_world(lo, 0.0)
    for m in mods:
        m.fromCorner = m.fromCorner - lo
    _move_devices(spec, mods, -lo)


def _tall_blocked(spec: KitchenSpec, tall: Module, delta: float, moved: list[Module], skip: set[str]) -> bool:
    """Whether a cabinet that stays put stands where ``tall`` would go after sliding by ``delta`` (same wall row, any storey)."""
    lo, hi = tall.fromCorner + delta, tall.endAt + delta
    return any(m.id not in skip and m not in moved and m.run == tall.run and m.storey != "corner" and m.fromCorner < hi - 1 and m.endAt > lo + 1
               for m in spec.module)


def new_id(spec: KitchenSpec, prefix: str) -> str:
    """Next id of a kind. Monotonic: the number never goes back (not even into the hole a removed module left), so a name
    that once meant one cabinet never means another — images, comments and approvals stay attached to the right one."""
    top = 0
    for m in [*spec.module, *spec.runs, *spec.openings]:
        tail = m.id[len(prefix):] if m.id.startswith(prefix) else ""
        if tail.isdigit():
            top = max(top, int(tail))
    n = max(top, spec.idCounters.get(prefix, 0)) + 1
    spec.idCounters[prefix] = n
    return f"{prefix}{n}"


def add_module(spec: KitchenSpec, module: dict[str, Any], after_module: str | None = None, close_gap: bool = True,
               before_module: str | None = None) -> KitchenSpec:
    """Thêm module. ``after_module`` / ``before_module``: right after (to the right of) / right before that cabinet, in its run, with its
    storey's sizes unless said otherwise. Closing up moves the cabinets on the run's free side: after the new one, or before it when the
    run keeps its end (``Run.anchor``)."""
    s = _clone(spec)
    data = dict(module)
    devices = [d for d in (as_dict(x) for x in [data.pop("appliance", None), *(as_list(data.pop("appliances", None)) or [])]) if d is not None]   # devices standing in/on this module
    if before_module and not after_module:
        ref = s.find(before_module)
        for key in ("y", "height", "depth"):
            data.setdefault(key, getattr(ref, key))
        data.setdefault("type", ref.type if ref.storey != "corner" else "base")
        data["wall"], data["run"] = "island", ref.run
        width = float(data.get("width") or 0)
        data["fromCorner"] = ref.fromCorner
        if _anchored_end(s, ref) is not None:          # the run keeps its end: the new cabinet ends where ``ref`` starts
            data["fromCorner"] = ref.fromCorner - width
            if close_gap:                              # ...and the cabinets before ``ref`` make room
                _shift_back(s, from_data(Module, {**data, "id": data.get("id") or "__probe__"}), ref.fromCorner, width, set())
                close_gap = False
    if after_module:
        ref = s.find(after_module)
        data.setdefault("wall", ref.wall)
        data.setdefault("y", ref.y)
        data.setdefault("height", ref.height)
        data.setdefault("depth", ref.depth)
        data.setdefault("type", ref.type if ref.storey != "corner" else "base")
        data["fromCorner"] = ref.endAt
        if ref.run and "run" not in data:     # the new module stands in the same run
            data["run"] = ref.run
    if not data.get("run") and data.get("wall") in ("back", "right", "left", "island", "corner"):     # given by wall: placed in the run along it
        from .rows_to_runs import placed_in_run
        data, made = placed_in_run(s, data)
        s.runs.extend(made)
    if not data.get("id"):
        storey = data.get("type", "base")
        data["id"] = new_id(s, "KG" if storey == "corner-shelf" else "TC" if storey.startswith("tall") else "TT" if storey.startswith("upper") else "TD")
    if after_module and _anchored_end(s, s.find(after_module)) is not None:      # the run keeps its end: the new cabinet ends where ``ref`` ended
        data["fromCorner"] = s.find(after_module).endAt - float(data.get("width") or 0)
    new = from_data(Module, data)
    if close_gap:
        if _anchored_end(s, new) is not None:
            _shift_back(s, new, new.endAt, new.width, set())
        else:
            _shift(s, new, new.fromCorner, new.width, set())
    s.module.append(new)
    _keep_start(s, new.run)
    for device in devices:                        # {"type", "name"?, "dimensions"?, "wall"?/"center"? for a sink, hob or tap}
        s.appliances.append(from_data(Appliance, {**device, "id": new_id(s, "TB"), "module": new.id}))
    return from_data(KitchenSpec, to_data(s))


def add_run(spec: KitchenSpec, run: dict[str, Any]) -> KitchenSpec:
    """Declare an explicit run (any angle). ``run``: ``{"id"?: "R1", "x": mm, "z": mm, "yaw": degrees}``; the id defaults to the next free ``R<n>``."""
    s = _clone(spec)
    data = dict(run)
    if not data.get("id"):
        data["id"] = new_id(s, "R")
    if any(r.id == data["id"] for r in s.runs):
        raise InvalidInput(f"Run {data['id']!r} already exists", code="run-exists", params={"id": data["id"]})
    s.runs.append(from_data(Run, data))
    return from_data(KitchenSpec, to_data(s))


def _run(s: KitchenSpec, id: str) -> Run:
    run = next((r for r in s.runs if r.id == id), None)
    if run is None:
        raise NotFound(f"No run {id!r}", code="run-not-found", params={"id": id})
    return run


def move_run(spec: KitchenSpec, id: str, changes: dict[str, Any]) -> KitchenSpec:
    """Move or turn an explicit run: ``changes`` may give ``x``, ``z`` (mm, kitchen frame) and ``yaw`` (degrees). Its cabinets follow."""
    s = _clone(spec)
    run = _run(s, id)
    extra = sorted(set(changes) - {"x", "z", "yaw"})
    if extra or not changes:
        raise InvalidInput(f"move-run changes x, z, yaw only, not {', '.join(extra) or '(nothing)'}", code="bad-run-change", params={"fields": ', '.join(extra) or '-'})
    for key, value in changes.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidInput(f"{key} must be a number", code="bad-run-number", params={"field": key})
        setattr(run, key, float(value))
    return from_data(KitchenSpec, to_data(s))


def set_run_system(spec: KitchenSpec, id: str, system: Any) -> KitchenSpec:
    """Say which cabinet system a run belongs to (``Run.system``); None or "" lets it be worked out from the runs it touches again."""
    s = _clone(spec)
    run = _run(s, id)
    if system not in (None, "") and not isinstance(system, str):
        raise InvalidInput("system must be a string or null", code="bad-run-system")
    data = {**to_data(run), "system": system or None}
    s.runs = [from_data(Run, data) if r.id == id else r for r in s.runs]
    return from_data(KitchenSpec, to_data(s))


def set_run_tv(spec: KitchenSpec, id: str, layout: Any, catalog: Catalog = builtin.CATALOG) -> KitchenSpec:
    """Make a run a TV unit (``purpose: "tv"`` with its layout, one of the catalog's ``tv-layout`` items) or, with None, a kitchen run again."""
    s = _clone(spec)
    run = _run(s, id)
    known = list(tv_system.layouts(catalog))
    if layout is not None and layout not in known:
        raise InvalidInput(f"layout must be one of {', '.join(known)} or null", code="bad-tv-layout", params={"allowed": ', '.join(known)})
    data = {k: v for k, v in to_data(run).items() if k not in ("purpose", "tvLayout", "unitLayout")}
    if layout is not None:
        data.update(tv_system.run_fields(layout, catalog))
    s.runs = [from_data(Run, data) if r.id == id else r for r in s.runs]
    return from_data(KitchenSpec, to_data(s))


def set_run_unit(spec: KitchenSpec, id: str, unit: Any, catalog: Catalog = builtin.CATALOG) -> KitchenSpec:
    """Make a run a furniture unit (``purpose: "unit"`` with its ``unitLayout``, catalog kind unit-layout) or, with None, a kitchen run again."""
    from .unit_system import units
    s = _clone(spec)
    run = _run(s, id)
    known = sorted(units(catalog))
    if unit is not None and not (isinstance(unit, str) and unit in known):
        raise InvalidInput(f"unit must be one of {', '.join(known)} or null", code="bad-unit-layout", params={"allowed": ', '.join(known)})
    data = {k: v for k, v in to_data(run).items() if k not in ("purpose", "tvLayout", "unitLayout")}
    if unit is not None:
        data.update({"purpose": "unit", "unitLayout": unit})
    s.runs = [from_data(Run, data) if r.id == id else r for r in s.runs]
    return from_data(KitchenSpec, to_data(s))


APPLIANCE_FIELDS = ("model", "name", "dimensions", "size", "cutout", "mount", "energy", "module")   # module: another kind (appliance_kind)
# ``type`` changes only with a model of another wall-hung type (a TV for a painting): appliance_models.swaps


def update_appliance(spec: KitchenSpec, id: str, model: Any = None, changes: dict[str, Any] | None = None,
                     catalog: Catalog = builtin.CATALOG) -> KitchenSpec:
    """Give an appliance another model (catalog kind ``appliance``): its name, dimensions, size, cut-out, mount and energy become the model's;
    its id, module, wall and centre stay, so it stays where it is. ``changes`` may set those fields by hand instead."""
    from .appliance_models import changes_for, model as model_of, swaps
    s = _clone(spec)
    hit = next((a for a in s.appliances if a.id == id), None)
    if hit is None:
        raise NotFound(f"No appliance {id!r}", code="appliance-not-found", params={"id": id})
    upd: dict[str, Any] = {}
    if model is not None:
        m = model_of(str(model), catalog)
        if not swaps(hit.type, m["type"]):
            raise InvalidInput(f"{m['name']} is a {m['type']}, {id} is a {hit.type}", code="model-wrong-type", params={"model": m["name"], "id": id})
        upd.update(changes_for(m))
        if m["type"] != hit.type:
            upd["type"] = m["type"]            # a painting in a TV's place (or back)
    bad = [k for k in (changes or {}) if k not in APPLIANCE_FIELDS]
    if bad:
        raise InvalidInput(f"update-appliance cannot change {bad}; only {', '.join(APPLIANCE_FIELDS)}", code="bad-appliance-field",
                           params={"fields": ', '.join(sorted(bad)), "allowed": ', '.join(APPLIANCE_FIELDS)})
    upd.update(changes or {})
    if "module" in upd and not any(m.id == upd["module"] for m in s.module):
        raise NotFound(f"No module {upd['module']!r}", code="module-not-found")
    data = {**to_data(hit), **upd}
    s.appliances = [from_data(Appliance, data) if a.id == id else a for a in s.appliances]
    return from_data(KitchenSpec, to_data(s))


def replace_element(spec: KitchenSpec, element: str, replaced: Any = True) -> KitchenSpec:
    """Mark a floorplan element (``elements[].id``, e.g. furniture_003) as replaced by cabinets, or bring it back (``replaced`` false): it is
    listed in ``floorplan.replaced`` and no longer built. The imported floorplan's elements are left as they are."""
    fp = as_dict(spec.floorplan)
    if fp is None:
        raise InvalidInput("This design has no imported floorplan", code="no-floorplan")
    ids = {str(e.get("id")) for e in (as_dict(x) for x in as_list(fp.get("elements")) or []) if e is not None}
    if element not in ids:
        raise NotFound(f"No floorplan element {element!r}", code="element-not-found", params={"id": element})
    if not isinstance(replaced, bool):
        raise InvalidInput("replaced must be true or false", code="bad-replaced")
    data = to_data(spec)
    now: list[Any] = [x for x in as_list(data["floorplan"].get("replaced")) or [] if x != element]
    data["floorplan"]["replaced"] = [*now, element] if replaced else now
    if not data["floorplan"]["replaced"]:
        data["floorplan"].pop("replaced")
    return from_data(KitchenSpec, data)


def remove_run(spec: KitchenSpec, id: str) -> KitchenSpec:
    """Remove an explicit run with every cabinet and appliance standing in it."""
    s = _clone(spec)
    _run(s, id)
    gone = {m.id for m in s.module if m.run == id}
    s.module = [m for m in s.module if m.id not in gone]
    s.appliances = [t for t in s.appliances if t.module not in gone]
    s.runs = [r for r in s.runs if r.id != id]
    return from_data(KitchenSpec, to_data(s))


STRETCH_MIN, STRETCH_MAX = defaults.BUILTIN.stretch_min, defaults.BUILTIN.stretch_max     # a cabinet's width stays a cabinet's width (catalog defaults)


def stretch_run(spec: KitchenSpec, id: str, end: str, delta: float, catalog: Catalog = builtin.CATALOG) -> KitchenSpec:
    """Drag one end of an explicit run by ``delta`` mm along the run (positive: longer). The other end stays where it is.

    The cabinets standing AT the dragged end (one per storey group: floor = base and tall, upper, loft) take the change in their width, doors
    keeping their proportions; cabinets that stop short of the end are left alone. Dragging the ``start`` moves the run's origin, so every
    other cabinet keeps its place in the room. Refused when a cabinet would leave ``STRETCH_MIN``-``STRETCH_MAX``."""
    from . import runs as runmod
    if end not in ("start", "end"):
        raise InvalidInput("end must be 'start' or 'end'", code="bad-run-end")
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not delta:   # pyright: ignore[reportUnnecessaryIsInstance] (JSON input)
        raise InvalidInput("delta must be a non-zero number (mm)", code="bad-run-delta")
    w_lo, w_hi = defaults.of(catalog).stretch_min, defaults.of(catalog).stretch_max
    s = _clone(spec)
    run = _run(s, id)
    mods = [m for m in s.module if m.run == id]
    if not mods:
        raise InvalidInput(f"Run {id!r} has no cabinet", code="empty-run", params={"id": id})
    lo, hi = min(m.fromCorner for m in mods), max(m.endAt for m in mods)
    group = {"base": "floor", "tall": "floor", "upper": "upper", "loft": "loft"}
    targets: dict[str, Module] = {}
    for m in mods:
        g = group.get(m.storey)
        if g is None:
            continue
        at_end = hi - m.endAt <= 1.0 if end == "end" else m.fromCorner - lo <= 1.0
        better = g not in targets or (m.endAt > targets[g].endAt if end == "end" else m.fromCorner < targets[g].fromCorner)
        if at_end and better:
            targets[g] = m
    for m in targets.values():
        width = m.width + delta
        if not w_lo <= width - m.blindCorner - m.endPanel or width > w_hi:
            raise InvalidInput(f"{m.id} would be {width:g} mm wide (allowed {w_lo:g}-{w_hi:g}); add or remove a cabinet instead", code="stretch-limit",
                               params={"id": m.id, "width": f"{width:g}", "min": f"{w_lo:g}", "max": f"{w_hi:g}"})
    hit = {m.id for m in targets.values()}
    for m in mods:
        if m.id in hit:
            if m.doors:                                         # keep the doors' proportions
                free_old, free_new = m.width - m.blindCorner - m.endPanel, m.width + delta - m.blindCorner - m.endPanel
                m.doors = [round_half_away(w * free_new / free_old, 1) for w in m.doors]
            m.width += delta
        elif end == "start":
            m.fromCorner += delta                               # the origin moves back by delta, so these stay where they are in the room
    for tb in s.appliances:                                     # a centre stored along the run follows its cabinet
        if tb.center is not None and tb.module in {m.id for m in mods}:
            tb.center += delta / 2 if tb.module in hit else (delta if end == "start" else 0.0)
    if end == "start":
        cos, sin = runmod.trig(run.yaw)
        run.x, run.z = run.x - delta * cos, run.z + delta * sin
    return from_data(KitchenSpec, to_data(s))


def next_run_id(spec: KitchenSpec) -> str:
    """The id ``add_run`` would give a run now (the caller's preview and the later apply see the same design, so they agree)."""
    return new_id(_clone(spec), "R")


def _prune_runs(s: KitchenSpec) -> None:
    """Drop runs no module stands in any more (a removed last cabinet leaves no ghost frame behind)."""
    used = {m.run for m in s.module if m.run} | {m.turnsInto for m in s.module if m.turnsInto}     # a corner shelf's second leg holds its run
    s.runs = [r for r in s.runs if r.id in used]


def remove_module(spec: KitchenSpec, id: str, close_gap: bool = True) -> KitchenSpec:
    s = _clone(spec)
    m = s.find(id)
    s.module = [x for x in s.module if x.id != id]
    s.appliances = [t for t in s.appliances if t.module != id]
    if close_gap and m.storey != "corner":
        if _anchored_end(s, m) is not None:
            _shift_back(s, m, m.fromCorner, -m.width, set())
        else:
            _shift(s, m, m.endAt, -m.width, set())
    _keep_start(s, m.run)
    _prune_runs(s)
    return from_data(KitchenSpec, to_data(s))


def update_module(spec: KitchenSpec, id: str, changes: dict[str, Any], close_gap: bool = True) -> KitchenSpec:
    s = _clone(spec)
    old = s.find(id)
    if "id" in changes and changes["id"] != id:
        raise InvalidInput("update cannot change a module's id; remove it and add it again", code="module-id-change")
    merged = {**to_data(old), **changes}
    if "width" in changes and "door" not in changes and old.doors:  # giữ tỉ lệ cánh khi đổi rộng
        free_old = old.width - old.blindCorner - old.endPanel
        free_new = merged["width"] - merged.get("blindCorner", 0) - merged.get("endPanel", 0)
        merged["doors"] = [round_half_away(w * free_new / free_old, 1) for w in old.doors]
    end_run = _anchored_end(s, old) if old.run and merged.get("run") == old.run else None
    if end_run is not None and close_gap and "fromCorner" not in changes and merged.get("width") != old.width:
        merged["fromCorner"] = old.endAt - float(merged["width"])        # the run keeps its end: the cabinet keeps its right edge
    new = from_data(Module, merged)
    if close_gap and new.run == old.run and new.storey != "corner":
        if end_run is not None:
            if new.fromCorner != old.fromCorner:
                _shift_back(s, old, old.fromCorner, old.fromCorner - new.fromCorner, {id})
                if "fromCorner" not in changes:
                    _move_devices(s, [old], new.fromCorner - old.fromCorner)
        elif new.endAt != old.endAt:
            _shift(s, old, old.endAt, new.endAt - old.endAt, {id})
    s.module = [new if x.id == id else x for x in s.module]
    _keep_start(s, new.run)
    return from_data(KitchenSpec, to_data(s))


def combine_ops(ops: list[dict[str, Any]]) -> dict[str, Any]:
    """One op from a list of ops. A multi op cannot nest, so nested multi ops are flattened."""
    flat = [x for o in ops for x in ((o.get("ops") or []) if o.get("op") == "multi" else [o])]
    return flat[0] if len(flat) == 1 else {"op": "multi", "ops": flat}


SURFACE_ID = re.compile(r"[^#\s]{1,80}#[a-z0-9-]{1,20}")


def surface_material(spec: KitchenSpec, surfaces: Any, material: Any) -> KitchenSpec:
    """{"op": "surface-material", "surfaces": ["wall_006#inside", ...], "material": "Sơn trắng" | null}: the finish of single wall faces
    (``kitchen.wall_surfaces`` ids); null or "" gives the faces back the wall's own finish."""
    ids = [str(x) for x in as_list(surfaces) or []]
    if not ids or any(not SURFACE_ID.fullmatch(i) for i in ids):
        raise InvalidInput("surfaces must be wall surface ids such as wall_006#inside", code="bad-surfaces")
    name = str(material).strip() if isinstance(material, str) else ""
    if material is not None and not isinstance(material, str):
        raise InvalidInput("material must be a material name or null", code="bad-material")
    if len(name) > 120:
        raise InvalidInput("material name is too long (120 characters at most)", code="bad-material")
    data = to_data(_clone(spec))
    finishes: dict[str, str] = {str(k): str(v) for k, v in (as_dict(data.get("surfaceMaterials")) or {}).items()}
    for i in ids:
        if name:
            finishes[i] = name
        else:
            finishes.pop(i, None)
    data["surfaceMaterials"] = dict(sorted(finishes.items())) or None
    return from_data(KitchenSpec, data)


SAMPLE_ID = re.compile(r"^smp-[0-9a-f]{16}$")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def material_sample(spec: KitchenSpec, name: Any, sample: Any, color: Any = None) -> KitchenSpec:
    """{"op": "material-sample", "name": "Đá marble trắng vân xám", "sample": "smp-…", "color"?: "#rrggbb"}: the material ``name`` looks like
    the stored reference picture ``sample`` (service.material_sample keeps it); ``sample`` null forgets it. Surfaces get the name by the
    usual operations (surface-material, update material, common material)."""
    label = str(name).strip() if isinstance(name, str) else ""
    if not label or len(label) > 120:
        raise InvalidInput("name must be a material name (120 characters at most)", code="bad-material")
    data = to_data(_clone(spec))
    samples: dict[str, Any] = {str(k): v for k, v in (as_dict(data.get("materialSamples")) or {}).items()}
    if sample is None:
        samples.pop(label, None)
    else:
        if not isinstance(sample, str) or not SAMPLE_ID.fullmatch(sample):
            raise InvalidInput("sample must be a stored material sample id (smp-<16 hex>)", code="bad-sample")
        if color is not None and (not isinstance(color, str) or not HEX_COLOR.fullmatch(color)):
            raise InvalidInput("color must be #rrggbb", code="bad-color")
        samples[label] = {"sample": sample, **({"color": color.lower()} if isinstance(color, str) else {})}
    data["materialSamples"] = dict(sorted(samples.items())) or None
    return from_data(KitchenSpec, data)


def update_common(spec: KitchenSpec, changes: dict[str, Any]) -> KitchenSpec:
    s = _clone(spec)
    data = to_data(s)
    data["common"].update(changes)
    return from_data(KitchenSpec, data)


def apply_op(spec: KitchenSpec, op: dict[str, Any], catalog: Catalog = builtin.CATALOG) -> KitchenSpec:
    """``_apply_op``, then every cabinet's type must be one of the catalog (catalog kind ``cabinet-type``)."""
    from .rows_to_runs import as_runs
    out = _apply_op(as_runs(spec, catalog), op, catalog)
    cabinet_types.check_known([m.type for m in out.module], catalog)
    return as_runs(out, catalog)                 # a cabinet added by wall stands in the run along that wall


OPENING_OPS = ("add-opening", "update-opening", "move-opening", "remove-opening", "reset-opening", "rehost-opening", "adopt-openings")


def _opening_op(spec: KitchenSpec, kind: str, op: dict[str, Any], catalog: Catalog) -> KitchenSpec:
    """Room openings (kitchen.openings, ADR 0005). ``id`` names the design's record (OPn) or a floorplan opening (its element id):
    changing a floorplan opening writes a record that overrides it, removing one writes a ``removed`` record, ``reset-opening``
    drops the record so the opening is again as drawn. Every record is stored normalized."""
    from . import geometry, openings
    from .openings.normalize import upgrade_first_form
    spec = _clone(spec)
    lsau, lphai = geometry.wall_length(spec)
    axes = openings.wall_axes.for_spec(to_data(spec), lsau, lphai)
    data = to_data(spec)
    def fresh_id() -> str:                              # monotonic (idCounters), carried into the data written back
        oid = new_id(spec, "OP")
        data["idCounters"] = dict(spec.idCounters)
        return oid
    def save(raw: dict[str, Any]) -> dict[str, Any]:
        parsed, _ = openings.normalize(raw, str(raw.get("source") or "human"), catalog, axes, spec.country)
        out = parsed.to_data()
        return {k: v for k, v in out.items() if not (k == "removed" and v is False)}
    if kind == "add-opening":
        raw = dict(op.get("opening") or {})
        raw["id"] = fresh_id()
        return from_data(KitchenSpec, openings.ops.add(data, save(raw)))
    if kind == "adopt-openings":      # floorplan openings left as drawn -> records of their own (drawn with frames and leaves)
        wanted = {str(x) for x in as_list(op.get("ids")) or []}
        taken = openings.overridden(data)
        todo = [o for o in openings.effective(data, catalog, axes, spec.country)
                if o.source == "drawn" and o.source_element and o.source_element not in taken and (not wanted or o.source_element in wanted)]
        if not todo:
            raise InvalidInput("Every floorplan opening already has a record in this design", code="opening-nothing-to-adopt")
        for o in todo:
            record = {**o.to_data(), "id": fresh_id(), "sourceElement": o.source_element}
            record.pop("removed", None)
            data = openings.ops.add(data, record)
        return from_data(KitchenSpec, data)
    oid = str(op.get("id") or "")
    own = next((to_data(o) for o in spec.openings if o.id == oid or (o.sourceElement and o.sourceElement == oid)), None)
    if own is not None and own.get("wallAxis") is None and "host" in own and not own.get("removed"):
        own = upgrade_first_form(own, axes)[0]                             # a record saved in the first, axis-less form
    inherited = None
    if own is None or own.get("removed"):
        inherited = next((o for o in openings.effective(data, catalog, axes, spec.country) if o.source_element == oid and o.source == "drawn"), None)
    if own is None and inherited is None:
        raise NotFound(f"No opening {oid!r}", code="opening-not-found", params={"id": oid})
    if kind == "reset-opening":
        element = (own or {}).get("sourceElement") or (inherited.source_element if inherited is not None else None)
        if not element:
            raise InvalidInput(f"Opening {oid!r} is not a floorplan opening", code="opening-not-inherited", params={"id": oid})
        return from_data(KitchenSpec, openings.ops.reset(data, str(element)))
    if kind == "remove-opening":
        if own is not None and not own.get("sourceElement"):
            return from_data(KitchenSpec, openings.ops.remove(data, str(own["id"])))
        element = str((own or {}).get("sourceElement") or (inherited.source_element if inherited is not None else oid))
        tomb_id = fresh_id()
        base = openings.ops.reset(data, element) if own is not None else data
        tomb = {"id": tomb_id, "kind": (own or {}).get("kind") or (inherited.kind if inherited is not None else "door"),
                "sourceElement": element, "removed": True, "source": "human"}
        return from_data(KitchenSpec, openings.ops.add(base, tomb))
    changes = dict(op.get("changes") or {})
    if kind == "move-opening":
        changes = {"center": op["center"]} if "center" in op else {"fromEdge": op.get("fromEdge")}
    if kind == "rehost-opening":
        changes = {"wallAxis": op.get("wallAxis"), **({"center": op["center"]} if "center" in op else {})}
    if "fromEdge" in changes:
        changes["center"] = None
    current = own if own is not None and not own.get("removed") else (inherited.to_data() if inherited is not None else {})
    merged = {**current, **changes, "source": changes.get("source", "human")}
    if merged.get("center") is None:
        merged.pop("center", None)
    new_axis: Any = changes.get("wallAxis")
    axis_record = as_dict(new_axis)
    if isinstance(new_axis, str):
        merged["wallAxis"] = {"id": new_axis}
    elif axis_record is not None:
        merged["wallAxis"] = {"id": str(axis_record.get("id") or "")}
    if "openingType" in changes and "leaves" not in changes:      # another type: its own template of axes and leaves
        for key in ("leaves", "axes", "hAxes"):
            if key not in changes:
                merged.pop(key, None)
    if own is not None and not own.get("removed"):
        record = save({**merged, "id": own["id"]})
        return from_data(KitchenSpec, openings.ops.replace(data, str(own["id"]), record))
    element = inherited.source_element if inherited is not None else oid
    record = save({**merged, "id": fresh_id(), "sourceElement": element})
    base = openings.ops.reset(data, str(element)) if own is not None else data
    return from_data(KitchenSpec, openings.ops.add(base, record))


def _apply_op(spec: KitchenSpec, op: dict[str, Any], catalog: Catalog = builtin.CATALOG) -> KitchenSpec:
    """Lệnh dạng dữ liệu (dùng chung cho MCP và HTTP).
    {"op": "add-run", "run": {"id"?, "x", "z", "yaw"}}  — an explicit run at any angle; modules join it with wall="island", run=<id>
    {"op": "move-run", "id": "R1", "changes": {"x"?, "z"?, "yaw"?}} | {"op": "remove-run", "id": "R1"}  — the run with all its cabinets
    {"op": "set-run-system", "id": "R1", "system": "furniture_003" | null}  — the cabinet system of a run (null: work it out)
    {"op": "set-run-tv", "id": "R1", "layout": "columns" | "shelves" | "full" | null}  — a TV unit run (null: a kitchen run again)
    {"op": "set-run-unit", "id": "R1", "unit": "wine" | "low" | null}  — a furniture unit run (catalog unit-layout; null: a kitchen run again)
    {"op": "update-appliance", "id": "TB4", "model": "hob-gas-2b-75", "changes"?: {...}}  — another model in the same place
    {"op": "material-sample", "name": "...", "sample": "smp-…", "color"?: "#rrggbb"}  — a material that looks like a reference picture
    {"op": "replace-element", "id": "furniture_003", "replaced": true|false}  — a floorplan element replaced by cabinets (no longer built) / back
    {"op": "stretch-run", "id": "R1", "end": "start"|"end", "delta": mm}  — drag one end; the cabinets at that end take the change
    {"op": "add", "module": {...}, "afterModule": "TD3"} | {"op": "add", "module": {...}, "beforeModule": "TD3"} | {"op": "remove", "id": "TD3"}
    {"op": "update", "id": "TD3", "changes": {...}} | {"op": "common", "changes": {...}}
    {"op": "replace", "spec": {...}}  — thay toàn bộ (vd nhập file)
    {"op": "lower-top", "newTop": 2550} | {"op": "molding", "id": "crown-molding", "changes": {"ignoreCeiling": true}}
    {"op": "set-moldings", "moldings": [...], "moldingProfiles"?: [...], "style"?: "Classic"}
    {"op": "set-views", "cameraViews": {...}}  — ghim góc nhìn
    {"op": "catalog-refresh"}  — nothing changes in the design; its new revision is built with the catalog as it is now
    {"op": "multi", "ops": [...]}  — nhiều thao tác áp lần lượt, ghi thành một rev (vd job sửa ảnh nhiều việc)"""
    kind = op.get("op")
    dd = op.get("closeGap", True)
    if kind == "catalog-refresh":       # the design as it is; saving it keeps the catalog items it uses as they are now (the revision's snapshot)
        return from_data(KitchenSpec, to_data(spec))
    if kind == "add":
        return add_module(spec, op["module"], op.get("afterModule"), dd, op.get("beforeModule"))
    if kind in OPENING_OPS:
        return _opening_op(spec, kind, op, catalog)
    if kind == "surface-material":
        return surface_material(spec, op.get("surfaces"), op.get("material"))
    if kind == "material-sample":
        return material_sample(spec, op.get("name"), op.get("sample"), op.get("color"))
    if kind == "add-run":
        return add_run(spec, op["run"])
    if kind == "move-run":
        return move_run(spec, op["id"], op.get("changes", {}))
    if kind == "set-run-system":
        return set_run_system(spec, op["id"], op.get("system"))
    if kind == "set-run-tv":
        return set_run_tv(spec, str(op.get("id") or ""), op.get("layout"), catalog)
    if kind == "set-run-unit":
        return set_run_unit(spec, str(op.get("id") or ""), op.get("unit"), catalog)
    if kind == "update-appliance":
        return update_appliance(spec, str(op.get("id") or ""), op.get("model"), op.get("changes") or {}, catalog)
    if kind == "replace-element":
        return replace_element(spec, str(op.get("id") or ""), op.get("replaced", True))
    if kind == "remove-run":
        return remove_run(spec, op["id"])
    if kind == "stretch-run":
        return stretch_run(spec, op["id"], op.get("end", "end"), op.get("delta", 0), catalog)
    if kind == "remove":
        return remove_module(spec, op["id"], dd)
    if kind == "update":
        return update_module(spec, op["id"], op.get("changes", {}), dd)
    if kind == "set-room":             # the default room's walls (a design without floorplan): {"room": {"wall": [...]}} or null (sized to its cabinets)
        data = to_data(spec)
        data["room"] = op.get("room")
        return from_data(KitchenSpec, data)
    if kind == "common":
        return update_common(spec, op.get("changes", {}))
    if kind == "replace":
        return from_data(KitchenSpec, op["spec"])
    if kind == "lower-top":  # hạ đỉnh tủ (vd để phào nóc lọt trần)
        from .moldings import lower_top
        return lower_top(spec, float(op["newTop"]))
    if kind == "molding":  # sửa một phào: {"ma": "phao-noc", "thayDoi": {...}}
        data = to_data(spec)
        hit = [m for m in data["moldings"] if m["id"] == op["id"]]
        if not hit:
            raise NotFound(f"No molding {op['id']!r}", code="molding-not-found", params={"id": op["id"]})
        hit[0].update(op.get("changes", {}))
        return from_data(KitchenSpec, data)
    if kind == "set-moldings":  # thay toàn bộ phào (+ mặt cắt riêng) và phong cách
        data = to_data(spec)
        data["moldings"] = op.get("moldings", [])
        if "moldingProfiles" in op:
            data["moldingProfiles"] = op["moldingProfiles"]
        from .moldings import embedded      # a catalog profile the builtin ones do not have travels with the design
        own = from_data(KitchenSpec, data).moldingProfiles
        ids = [str(m.get("profile")) for m in (as_dict(x) or {} for x in data["moldings"]) if m.get("profile")]
        carried = embedded(ids, own, catalog)
        if len(carried) != len(own):
            data["moldingProfiles"] = [to_data(p) for p in carried]
        if op.get("style"):
            data["style"] = op["style"]
        return from_data(KitchenSpec, data)
    if kind == "set-views":  # ghim / thay bộ góc nhìn (vd giữ camera cũ khi xóa tủ làm khung bao đổi)
        data = to_data(spec)
        data["cameraViews"] = op.get("cameraViews") or {}
        return from_data(KitchenSpec, data)
    if kind == "multi":
        ops = [as_dict(o) or {} for o in as_list(op.get("ops")) or []]
        if not ops or any(o.get("op") == "multi" for o in ops):
            raise InvalidInput("op 'multi' needs a list of ops (no nested 'multi')", code="bad-multi")
        for o in ops:
            spec = apply_op(spec, o, catalog)
        return spec
    raise InvalidInput(f"Unknown op: {kind!r}", code="bad-op", params={"op": str(kind)})
