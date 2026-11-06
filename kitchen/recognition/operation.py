"""Draft -> one ``replace`` operation over the current design. The caller previews it with ``propose``; this never applies anything."""
from __future__ import annotations

from typing import Any

from ..spec import KitchenSpec, to_data
from .draft import Draft, DraftModule

PREFIX = {"base": "TD", "upper": "TT", "tall": "TC"}


def _storey(m: DraftModule) -> str:
    return "tall" if m.type.startswith("tall") else "upper" if m.type.startswith("upper") else "base"


def _geometry(m: DraftModule, common: dict[str, Any]) -> tuple[float, float, float]:
    """(y, height, depth) from the module's own numbers, else the design's common levels."""
    storey = _storey(m)
    if storey == "tall":
        y, height, depth = 0.0, common["cabinetTop"], common["baseDepth"]
    elif storey == "upper":
        y, height, depth = common["upperBottom"], common["upperTierSplit"] - common["upperBottom"], common["upperDepth"]
    else:
        y, height, depth = 0.0, common["baseTop"], common["baseDepth"]
    return y, m.height or height, m.depth or depth


def draft_operation(spec: KitchenSpec, draft: Draft) -> dict[str, Any]:
    """The design with its cabinets replaced by the draft's; room, appliances and the rest of ``common`` stay. Modules without a position
    follow the previous one on the same wall and storey (in the order given)."""
    data = to_data(spec)
    common = data["common"]
    cursor: dict[tuple[str, str], float] = {}
    count: dict[str, int] = {}
    modules: list[dict[str, Any]] = []
    for m in draft.modules:
        storey = _storey(m)
        key = (m.wall, storey)
        start = m.fromCorner if m.fromCorner is not None else cursor.get(key, 0.0)
        cursor[key] = start + m.width
        count[storey] = count.get(storey, 0) + 1
        y, height, depth = _geometry(m, common)
        entry: dict[str, Any] = {"id": f"{PREFIX[storey]}{count[storey]}", "type": m.type, "wall": m.wall, "fromCorner": start, "width": m.width,
                                 "y": y, "height": height, "depth": depth}
        if m.label:
            entry["name"] = m.label
        modules.append(entry)
    data["module"] = modules
    data["appliances"] = []                       # they pointed at the old module ids
    if draft.ceiling is not None:
        common["ceiling"] = draft.ceiling
    if draft.materials:
        common["material"] = {**common.get("material", {}), **draft.materials}
    return {"op": "replace", "spec": data}
