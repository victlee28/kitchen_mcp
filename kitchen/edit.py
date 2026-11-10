"""Lệnh sửa thiết kế: hàm thuần, nhận spec cũ trả spec mới (không sửa tại chỗ).

"Dồn dãy" (don_day=True): các module cùng tường, cùng dải cao độ, nằm phía sau điểm thay đổi
được dịch theo để không chồng/hở. Tủ cao (cao*) chắn cả tầng dưới lẫn tầng trên nên được tính chung.
"""
from __future__ import annotations

from typing import Any

from .numeric import round_half_away
from .spec import Appliance, KitchenSpec, Module, Run, from_data, to_data
from .errors import InvalidInput, NotFound


def _clone(spec: KitchenSpec) -> KitchenSpec:
    return from_data(KitchenSpec, to_data(spec))


def _same_run(a: Module, b: Module) -> bool:
    """Hai module cùng tường và chồng nhau theo phương đứng."""
    if a.run or b.run:
        return a.run == b.run and min(a.y + a.height, b.y + b.height) - max(a.y, b.y) > 1     # modules of an explicit run only meet in that run
    if a.wall == "island" and (a.offset, a.facing or "-z") != (b.offset, b.facing or "-z"):
        return False                      # free runs at another place or facing are other runs
    return a.wall == b.wall and a.wall != "corner" and min(a.y + a.height, b.y + b.height) - max(a.y, b.y) > 1


def _shift(spec: KitchenSpec, ref: Module, shift_from: float, delta: float, skip: set[str]):
    if not delta:
        return
    moved = [m for m in spec.module if m.id not in skip and _same_run(m, ref) and m.fromCorner >= shift_from - 1]
    # tủ cao bị dịch thì kéo theo mọi module cùng tường phía sau nó (mọi tầng)
    for tall in [m for m in moved if m.storey == "tall"]:
        moved += [m for m in spec.module if m.wall == tall.wall and m.run == tall.run and (m.offset, m.facing) == (tall.offset, tall.facing)
                  and m.fromCorner >= tall.fromCorner - 1 and m.id not in skip and m not in moved]
    for m in moved:
        m.fromCorner = max(0.0, m.fromCorner + delta)
    for tb in spec.appliances:  # thiết bị gắn vị trí trên tường dịch cùng
        if tb.wall == ref.wall and tb.center is not None and ref.storey == "base" and tb.center >= shift_from - 1:
            tb.center += delta


def new_id(spec: KitchenSpec, prefix: str) -> str:
    """Next id of a kind. Monotonic: the number never goes back (not even into the hole a removed module left), so a name
    that once meant one cabinet never means another — images, comments and approvals stay attached to the right one."""
    top = 0
    for m in [*spec.module, *spec.runs]:
        tail = m.id[len(prefix):] if m.id.startswith(prefix) else ""
        if tail.isdigit():
            top = max(top, int(tail))
    n = max(top, spec.idCounters.get(prefix, 0)) + 1
    spec.idCounters[prefix] = n
    return f"{prefix}{n}"


def add_module(spec: KitchenSpec, module: dict[str, Any], after_module: str | None = None, close_gap: bool = True) -> KitchenSpec:
    """Thêm module. Nếu có `sau_module`, đặt ngay sau module đó (cùng tường, cùng tầng nếu không nói khác)."""
    s = _clone(spec)
    data = dict(module)
    devices = [d for d in [data.pop("appliance", None), *(data.pop("appliances", None) or [])] if isinstance(d, dict)]   # devices standing in/on this module
    if after_module:
        ref = s.find(after_module)
        data.setdefault("wall", ref.wall)
        data.setdefault("y", ref.y)
        data.setdefault("height", ref.height)
        data.setdefault("depth", ref.depth)
        data.setdefault("type", ref.type if ref.storey != "corner" else "base")
        data["fromCorner"] = ref.endAt
        if ref.wall == "island":              # a free or angled run: the new module stands in the same run
            for key in ("run", "offset", "facing"):
                if getattr(ref, key) and key not in data:
                    data[key] = getattr(ref, key)
    if not data.get("id"):
        storey = data.get("type", "base")
        data["id"] = new_id(s, "TC" if storey.startswith("tall") else "TT" if storey.startswith("upper") else "TD")
    new = from_data(Module, data)
    if close_gap:
        _shift(s, new, new.fromCorner, new.width, set())
    s.module.append(new)
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
        raise InvalidInput(f"Dãy '{data['id']}' đã có", code="run-exists")
    s.runs.append(from_data(Run, data))
    return from_data(KitchenSpec, to_data(s))


def _run(s: KitchenSpec, id: str) -> Run:
    run = next((r for r in s.runs if r.id == id), None)
    if run is None:
        raise NotFound(f"Không có dãy '{id}'", code="run-not-found")
    return run


def move_run(spec: KitchenSpec, id: str, changes: dict[str, Any]) -> KitchenSpec:
    """Move or turn an explicit run: ``changes`` may give ``x``, ``z`` (mm, kitchen frame) and ``yaw`` (degrees). Its cabinets follow."""
    s = _clone(spec)
    run = _run(s, id)
    extra = sorted(set(changes) - {"x", "z", "yaw"})
    if extra or not changes:
        raise InvalidInput(f"move-run đổi được x, z, yaw; không đổi được {', '.join(extra) or '(trống)'}", code="bad-run-change")
    for key, value in changes.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidInput(f"{key} phải là số", code="bad-run-change")
        setattr(run, key, float(value))
    return from_data(KitchenSpec, to_data(s))


def set_run_system(spec: KitchenSpec, id: str, system: Any) -> KitchenSpec:
    """Say which cabinet system a run belongs to (``Run.system``); None or "" lets it be worked out from the runs it touches again."""
    s = _clone(spec)
    run = _run(s, id)
    if system not in (None, "") and not isinstance(system, str):
        raise InvalidInput("system phải là chuỗi hoặc null", code="bad-run-system")
    data = {**to_data(run), "system": system or None}
    s.runs = [from_data(Run, data) if r.id == id else r for r in s.runs]
    return from_data(KitchenSpec, to_data(s))


def remove_run(spec: KitchenSpec, id: str) -> KitchenSpec:
    """Remove an explicit run with every cabinet and appliance standing in it."""
    s = _clone(spec)
    _run(s, id)
    gone = {m.id for m in s.module if m.run == id}
    s.module = [m for m in s.module if m.id not in gone]
    s.appliances = [t for t in s.appliances if t.module not in gone]
    s.runs = [r for r in s.runs if r.id != id]
    return from_data(KitchenSpec, to_data(s))


STRETCH_MIN, STRETCH_MAX = 150.0, 2000.0     # a cabinet's width stays a cabinet's width


def stretch_run(spec: KitchenSpec, id: str, end: str, delta: float) -> KitchenSpec:
    """Drag one end of an explicit run by ``delta`` mm along the run (positive: longer). The other end stays where it is.

    The cabinets standing AT the dragged end (one per storey group: floor = base and tall, upper, loft) take the change in their width, doors
    keeping their proportions; cabinets that stop short of the end are left alone. Dragging the ``start`` moves the run's origin, so every
    other cabinet keeps its place in the room. Refused when a cabinet would leave ``STRETCH_MIN``-``STRETCH_MAX``."""
    from . import runs as runmod
    if end not in ("start", "end"):
        raise InvalidInput("end phải là 'start' hoặc 'end'", code="bad-run-end")
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not delta:
        raise InvalidInput("delta phải là số khác 0 (mm)", code="bad-run-delta")
    s = _clone(spec)
    run = _run(s, id)
    mods = [m for m in s.module if m.run == id]
    if not mods:
        raise InvalidInput(f"Dãy '{id}' không có tủ", code="empty-run")
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
        if not STRETCH_MIN <= width - m.blindCorner - m.endPanel or width > STRETCH_MAX:
            raise InvalidInput(f"{m.id} sẽ rộng {width:g} mm (cho phép {STRETCH_MIN:g}-{STRETCH_MAX:g}); thêm hoặc bớt một tủ thay vì kéo", code="stretch-limit")
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
    used = {m.run for m in s.module if m.run}
    s.runs = [r for r in s.runs if r.id in used]


def remove_module(spec: KitchenSpec, id: str, close_gap: bool = True) -> KitchenSpec:
    s = _clone(spec)
    m = s.find(id)
    s.module = [x for x in s.module if x.id != id]
    s.appliances = [t for t in s.appliances if t.module != id]
    if close_gap and m.wall != "corner":
        _shift(s, m, m.endAt, -m.width, set())
    _prune_runs(s)
    return from_data(KitchenSpec, to_data(s))


def update_module(spec: KitchenSpec, id: str, changes: dict[str, Any], close_gap: bool = True) -> KitchenSpec:
    s = _clone(spec)
    old = s.find(id)
    if "id" in changes and changes["id"] != id:
        raise InvalidInput("Không đổi mã module bằng update; hãy xóa rồi thêm")
    merged = {**to_data(old), **changes}
    if "width" in changes and "door" not in changes and old.doors:  # giữ tỉ lệ cánh khi đổi rộng
        free_old = old.width - old.blindCorner - old.endPanel
        free_new = merged["width"] - merged.get("blindCorner", 0) - merged.get("endPanel", 0)
        merged["doors"] = [round_half_away(w * free_new / free_old, 1) for w in old.doors]
    new = from_data(Module, merged)
    if close_gap and new.wall == old.wall and new.wall != "corner":
        if new.endAt != old.endAt:
            _shift(s, old, old.endAt, new.endAt - old.endAt, {id})
    s.module = [new if x.id == id else x for x in s.module]
    return from_data(KitchenSpec, to_data(s))


def combine_ops(ops: list[dict[str, Any]]) -> dict[str, Any]:
    """One op from a list of ops. A multi op cannot nest, so nested multi ops are flattened."""
    flat = [x for o in ops for x in ((o.get("ops") or []) if o.get("op") == "multi" else [o])]
    return flat[0] if len(flat) == 1 else {"op": "multi", "ops": flat}


def update_common(spec: KitchenSpec, changes: dict[str, Any]) -> KitchenSpec:
    s = _clone(spec)
    data = to_data(s)
    data["common"].update(changes)
    return from_data(KitchenSpec, data)


def apply_op(spec: KitchenSpec, op: dict[str, Any]) -> KitchenSpec:
    """Lệnh dạng dữ liệu (dùng chung cho MCP và HTTP).
    {"op": "add-run", "run": {"id"?, "x", "z", "yaw"}}  — an explicit run at any angle; modules join it with wall="island", run=<id>
    {"op": "move-run", "id": "R1", "changes": {"x"?, "z"?, "yaw"?}} | {"op": "remove-run", "id": "R1"}  — the run with all its cabinets
    {"op": "set-run-system", "id": "R1", "system": "furniture_003" | null}  — the cabinet system of a run (null: work it out)
    {"op": "stretch-run", "id": "R1", "end": "start"|"end", "delta": mm}  — drag one end; the cabinets at that end take the change
    {"op": "add", "module": {...}, "afterModule": "TD3"} | {"op": "remove", "id": "TD3"}
    {"op": "update", "id": "TD3", "changes": {...}} | {"op": "common", "changes": {...}}
    {"op": "replace", "spec": {...}}  — thay toàn bộ (vd nhập file)
    {"op": "lower-top", "newTop": 2550} | {"op": "molding", "id": "crown-molding", "changes": {"ignoreCeiling": true}}
    {"op": "set-moldings", "moldings": [...], "moldingProfiles"?: [...], "style"?: "Classic"}
    {"op": "set-views", "cameraViews": {...}}  — ghim góc nhìn
    {"op": "multi", "ops": [...]}  — nhiều thao tác áp lần lượt, ghi thành một rev (vd job sửa ảnh nhiều việc)"""
    kind = op.get("op")
    dd = op.get("closeGap", True)
    if kind == "add":
        return add_module(spec, op["module"], op.get("afterModule"), dd)
    if kind == "add-run":
        return add_run(spec, op["run"])
    if kind == "move-run":
        return move_run(spec, op["id"], op.get("changes", {}))
    if kind == "set-run-system":
        return set_run_system(spec, op["id"], op.get("system"))
    if kind == "remove-run":
        return remove_run(spec, op["id"])
    if kind == "stretch-run":
        return stretch_run(spec, op["id"], op.get("end", "end"), op.get("delta", 0))
    if kind == "remove":
        return remove_module(spec, op["id"], dd)
    if kind == "update":
        return update_module(spec, op["id"], op.get("changes", {}), dd)
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
            raise NotFound(f"Không có phào '{op['id']}'", code="molding-not-found")
        hit[0].update(op.get("changes", {}))
        return from_data(KitchenSpec, data)
    if kind == "set-moldings":  # thay toàn bộ phào (+ mặt cắt riêng) và phong cách
        data = to_data(spec)
        data["moldings"] = op.get("moldings", [])
        if "moldingProfiles" in op:
            data["moldingProfiles"] = op["moldingProfiles"]
        if op.get("style"):
            data["style"] = op["style"]
        return from_data(KitchenSpec, data)
    if kind == "set-views":  # ghim / thay bộ góc nhìn (vd giữ camera cũ khi xóa tủ làm khung bao đổi)
        data = to_data(spec)
        data["cameraViews"] = op.get("cameraViews") or {}
        return from_data(KitchenSpec, data)
    if kind == "multi":
        ops = op.get("ops") or []
        if not ops or any(o.get("op") == "multi" for o in ops):
            raise InvalidInput("op 'nhieu' cần danh sách ops (không lồng 'nhieu')")
        for o in ops:
            spec = apply_op(spec, o)
        return spec
    raise InvalidInput(f"op không hợp lệ: {kind!r}")
