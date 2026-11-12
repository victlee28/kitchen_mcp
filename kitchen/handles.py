"""Handle settings per storey / per module, and the design operations that change them.

Resolution order for one module (see `spec.effective_handle`): module override > storey override > common default.
A material edit from the image editor must be expressible exactly in the spec, so `material_ops` picks the coarsest
scope that equals the selected handles (every handle, whole storeys, or whole modules) and refuses a partial module.
"""
from __future__ import annotations

from typing import Any

from collections import defaultdict

from .geometry import Scene
from .spec import HandleOverride, KitchenSpec, effective_handle, to_data
from .errors import InvalidInput, require


def _dump(override: HandleOverride | None) -> dict[str, Any]:
    return to_data(override, exclude_none=True) if override is not None else {}


def material_slot(spec: KitchenSpec, module_id: str | None) -> tuple[str, str]:
    """(slot key, material name) of the handles of one module. The key says which level the material comes from."""
    m = next((x for x in spec.module if x.id == module_id), None)
    if m is None:
        return "common:handle", spec.common.handle.material
    name = effective_handle(spec.common, m).material
    if m.handle is not None and m.handle.material is not None:
        return f"module-handle:{m.id}", name
    storey = (spec.common.handleByStorey or {}).get(m.storey)
    if storey is not None and storey.material is not None:
        return f"storey-handle:{m.storey}", name
    return "common:handle", name


def material_ops(spec: KitchenSpec, scene: Scene, part_ids: list[str], material: str) -> tuple[dict[str, Any], str]:
    """Design op (and scope text) that gives exactly the selected handles the new material.

    Raises ValueError when the selection covers only part of a module's handles, because the spec stores handles
    per module and per storey, not per handle.
    """
    all_by_module: dict[str, set[str]] = defaultdict(set)
    chosen: dict[str, set[str]] = defaultdict(set)
    wanted = set(part_ids)
    for p in scene.parts:
        if p.type == "handle":
            mod = require(p.module, f"{p.id}.module")
            all_by_module[mod].add(p.id)
            if p.id in wanted:
                chosen[mod].add(p.id)
    if not chosen:
        raise InvalidInput("No handle in the selection", code="no-handle-selected")
    partial = sorted(m for m, ids in chosen.items() if ids != all_by_module[m])
    if partial:
        raise InvalidInput(f"Handles are stored per cabinet and storey, not one by one: only some handles of {', '.join(partial)} are selected",
                           code="partial-handles", params={"ids": ', '.join(partial)})
    storey_of = {m.id: m.storey for m in spec.module}
    module_of = {m.id: m for m in spec.module}
    chosen_modules, all_modules = set(chosen), set(all_by_module)
    by_storey = {k: _dump(v) for k, v in (spec.common.handleByStorey or {}).items()}
    changes: dict[str, Any] = {}
    covered: set[str] = set()
    ops: list[dict[str, Any]] = []
    if chosen_modules == all_modules:
        changes["handle"] = {**to_data(spec.common.handle), "material": material}
        for k in list(by_storey):
            by_storey[k].pop("material", None)
            if not by_storey[k]:
                del by_storey[k]
        changes["handleByStorey"] = by_storey or None
        covered, scope = all_modules, "mọi tay nắm"
    else:
        storeys: list[str] = []
        for s in dict.fromkeys(storey_of[m] for m in sorted(all_modules)):
            members = {m for m in all_modules if storey_of[m] == s}
            if members <= chosen_modules:
                by_storey.setdefault(s, {})["material"] = material
                covered |= members
                storeys.append(s)
        if storeys:
            changes["handleByStorey"] = by_storey
        single = sorted(chosen_modules - covered)
        for mid in single:
            ops.append({"op": "update", "id": mid, "changes": {"handle": {**_dump(module_of[mid].handle), "material": material}}})
        scope = "tay nắm " + "; ".join(x for x in (f"tầng {', '.join(storeys)}" if storeys else "", f"module {', '.join(single)}" if single else "") if x)
    for mid in sorted(covered):  # a module-level material would still win over the new storey / common material
        override = module_of[mid].handle
        if override is not None and override.material is not None:
            rest = {k: v for k, v in _dump(override).items() if k != "material"}
            ops.append({"op": "update", "id": mid, "changes": {"handle": rest or None}})
    if changes:
        ops.insert(0, {"op": "common", "changes": changes})
    return (ops[0] if len(ops) == 1 else {"op": "multi", "ops": ops}), scope


def clear_overrides(spec: KitchenSpec, fields: tuple[str, ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Common-level changes and module update ops that drop the given override fields (variant, length, material),
    so that a common-level edit applies to every cabinet."""
    current = {k: _dump(v) for k, v in (spec.common.handleByStorey or {}).items()}
    cleaned: dict[str, dict[str, Any]] = {}
    for k, v in current.items():
        rest = {f: x for f, x in v.items() if f not in fields}
        if rest:
            cleaned[k] = rest
    changes: dict[str, Any] = {"handleByStorey": cleaned or None} if cleaned != current else {}
    ops: list[dict[str, Any]] = []
    for m in spec.module:
        if m.handle is None:
            continue
        data = _dump(m.handle)
        rest = {f: x for f, x in data.items() if f not in fields}
        if rest != data:
            ops.append({"op": "update", "id": m.id, "changes": {"handle": rest or None}})
    return changes, ops
