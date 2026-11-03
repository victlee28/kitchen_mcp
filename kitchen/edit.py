"""Lệnh sửa thiết kế: hàm thuần, nhận spec cũ trả spec mới (không sửa tại chỗ).

"Dồn dãy" (don_day=True): các module cùng tường, cùng dải cao độ, nằm phía sau điểm thay đổi
được dịch theo để không chồng/hở. Tủ cao (cao*) chắn cả tầng dưới lẫn tầng trên nên được tính chung.
"""
from __future__ import annotations

from typing import Any

from .spec import KitchenSpec, Module


def _clone(spec: KitchenSpec) -> KitchenSpec:
    return KitchenSpec.model_validate(spec.model_dump(mode="json"))


def _same_run(a: Module, b: Module) -> bool:
    """Hai module cùng tường và chồng nhau theo phương đứng."""
    return a.wall == b.wall and a.wall != "corner" and min(a.y + a.height, b.y + b.height) - max(a.y, b.y) > 1


def _shift(spec: KitchenSpec, ref: Module, shift_from: float, delta: float, skip: set[str]):
    if not delta:
        return
    moved = [m for m in spec.module if m.id not in skip and _same_run(m, ref) and m.fromCorner >= shift_from - 1]
    # tủ cao bị dịch thì kéo theo mọi module cùng tường phía sau nó (mọi tầng)
    for tall in [m for m in moved if m.storey == "tall"]:
        moved += [m for m in spec.module if m.wall == tall.wall and m.fromCorner >= tall.fromCorner - 1
                  and m.id not in skip and m not in moved]
    for m in moved:
        m.fromCorner = max(0.0, m.fromCorner + delta)
    for tb in spec.appliances:  # thiết bị gắn vị trí trên tường dịch cùng
        if tb.wall == ref.wall and tb.center is not None and ref.storey == "base" and tb.center >= shift_from - 1:
            tb.center += delta


def new_id(spec: KitchenSpec, prefix: str) -> str:
    used = {m.id for m in spec.module}
    i = 1
    while f"{prefix}{i}" in used:
        i += 1
    return f"{prefix}{i}"


def add_module(spec: KitchenSpec, module: dict[str, Any], after_module: str | None = None, close_gap: bool = True) -> KitchenSpec:
    """Thêm module. Nếu có `sau_module`, đặt ngay sau module đó (cùng tường, cùng tầng nếu không nói khác)."""
    s = _clone(spec)
    data = dict(module)
    if after_module:
        ref = s.find(after_module)
        data.setdefault("wall", ref.wall)
        data.setdefault("y", ref.y)
        data.setdefault("height", ref.height)
        data.setdefault("depth", ref.depth)
        data.setdefault("type", ref.type if ref.storey != "corner" else "base")
        data["fromCorner"] = ref.endAt
    if not data.get("id"):
        storey = data.get("type", "base")
        data["id"] = new_id(s, "TC" if storey.startswith("tall") else "TT" if storey.startswith("upper") else "TD")
    new = Module.model_validate(data)
    if close_gap:
        _shift(s, new, new.fromCorner, new.width, set())
    s.module.append(new)
    return KitchenSpec.model_validate(s.model_dump(mode="json"))


def remove_module(spec: KitchenSpec, id: str, close_gap: bool = True) -> KitchenSpec:
    s = _clone(spec)
    m = s.find(id)
    s.module = [x for x in s.module if x.id != id]
    s.appliances = [t for t in s.appliances if t.module != id]
    if close_gap and m.wall != "corner":
        _shift(s, m, m.endAt, -m.width, set())
    return KitchenSpec.model_validate(s.model_dump(mode="json"))


def update_module(spec: KitchenSpec, id: str, changes: dict[str, Any], close_gap: bool = True) -> KitchenSpec:
    s = _clone(spec)
    old = s.find(id)
    if "id" in changes and changes["id"] != id:
        raise ValueError("Không đổi mã module bằng update; hãy xóa rồi thêm")
    merged = {**old.model_dump(mode="json"), **changes}
    if "width" in changes and "door" not in changes and old.doors:  # giữ tỉ lệ cánh khi đổi rộng
        free_old = old.width - old.blindCorner - old.endPanel
        free_new = merged["width"] - merged.get("blindCorner", 0) - merged.get("endPanel", 0)
        merged["doors"] = [round(w * free_new / free_old, 1) for w in old.doors]
    new = Module.model_validate(merged)
    if close_gap and new.wall == old.wall and new.wall != "corner":
        if new.endAt != old.endAt:
            _shift(s, old, old.endAt, new.endAt - old.endAt, {id})
    s.module = [new if x.id == id else x for x in s.module]
    return KitchenSpec.model_validate(s.model_dump(mode="json"))


def combine_ops(ops: list[dict[str, Any]]) -> dict[str, Any]:
    """One op from a list of ops. A multi op cannot nest, so nested multi ops are flattened."""
    flat = [x for o in ops for x in ((o.get("ops") or []) if o.get("op") == "multi" else [o])]
    return flat[0] if len(flat) == 1 else {"op": "multi", "ops": flat}


def update_common(spec: KitchenSpec, changes: dict[str, Any]) -> KitchenSpec:
    s = _clone(spec)
    data = s.model_dump(mode="json")
    data["common"].update(changes)
    return KitchenSpec.model_validate(data)


def apply_op(spec: KitchenSpec, op: dict[str, Any]) -> KitchenSpec:
    """Lệnh dạng dữ liệu (dùng chung cho MCP và HTTP).
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
    if kind == "remove":
        return remove_module(spec, op["id"], dd)
    if kind == "update":
        return update_module(spec, op["id"], op.get("changes", {}), dd)
    if kind == "common":
        return update_common(spec, op.get("changes", {}))
    if kind == "replace":
        return KitchenSpec.model_validate(op["spec"])
    if kind == "lower-top":  # hạ đỉnh tủ (vd để phào nóc lọt trần)
        from .moldings import lower_top
        return lower_top(spec, float(op["newTop"]))
    if kind == "molding":  # sửa một phào: {"ma": "phao-noc", "thayDoi": {...}}
        data = spec.model_dump(mode="json")
        hit = [m for m in data["moldings"] if m["id"] == op["id"]]
        if not hit:
            raise KeyError(f"Không có phào '{op['id']}'")
        hit[0].update(op.get("changes", {}))
        return KitchenSpec.model_validate(data)
    if kind == "set-moldings":  # thay toàn bộ phào (+ mặt cắt riêng) và phong cách
        data = spec.model_dump(mode="json")
        data["moldings"] = op.get("moldings", [])
        if "moldingProfiles" in op:
            data["moldingProfiles"] = op["moldingProfiles"]
        if op.get("style"):
            data["style"] = op["style"]
        return KitchenSpec.model_validate(data)
    if kind == "set-views":  # ghim / thay bộ góc nhìn (vd giữ camera cũ khi xóa tủ làm khung bao đổi)
        data = spec.model_dump(mode="json")
        data["cameraViews"] = op.get("cameraViews") or {}
        return KitchenSpec.model_validate(data)
    if kind == "multi":
        ops = op.get("ops") or []
        if not ops or any(o.get("op") == "multi" for o in ops):
            raise ValueError("op 'nhieu' cần danh sách ops (không lồng 'nhieu')")
        for o in ops:
            spec = apply_op(spec, o)
        return spec
    raise ValueError(f"op không hợp lệ: {kind!r}")
