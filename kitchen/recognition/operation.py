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


def line_modules(draft: Draft, common: dict[str, Any], wall: str = "back") -> tuple[list[dict[str, Any]], int]:
    """The draft's cabinets of ONE straight run, ready for ``run_line.plan_on_line``: ``({type, width, s, y, height, depth, name?}, dropped)``.

    Only the draft's ``wall`` is used (a photo of an L or U kitchen has more runs; ``dropped`` counts the cabinets of the others). The draft measures
    ``fromCorner`` from the right-hand end of the run towards the left, as seen from the front; a run's ``s`` grows to the right, so each cabinet
    is mirrored: ``s = length - fromCorner - width``. A cabinet with no position follows the previous one of its storey, as in ``draft_operation``.
    """
    cursor: dict[str, float] = {}
    placed: list[tuple[float, DraftModule]] = []
    for m in draft.modules:
        if m.wall != wall:
            continue
        storey = _storey(m)
        start = m.fromCorner if m.fromCorner is not None else cursor.get(storey, 0.0)
        cursor[storey] = start + m.width
        placed.append((start, m))
    length = max((start + m.width for start, m in placed), default=0.0)
    out: list[dict[str, Any]] = []
    for start, m in placed:
        y, height, depth = _geometry(m, common)
        entry: dict[str, Any] = {"type": m.type, "width": m.width, "s": length - start - m.width, "y": y, "height": height, "depth": depth}
        if m.label:
            entry["name"] = m.label
        out.append(entry)
    return out, len(draft.modules) - len(placed)
