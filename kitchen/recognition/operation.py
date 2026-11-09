"""Draft -> one ``replace`` operation over the current design. The caller previews it with ``propose``; this never applies anything."""
from __future__ import annotations

from typing import Any

from ..numeric import round_half_away
from ..spec import KitchenSpec, to_data
from .draft import Draft, DraftModule

PREFIX = {"base": "TD", "upper": "TT", "tall": "TC"}


def _storey(m: DraftModule) -> str:
    return "tall" if m.type.startswith("tall") else "upper" if m.type.startswith("upper") else "base"


MIN_TALL_HEIGHT = 1500.0     # a "tall" cabinet shorter than this is a base-band height the recognizer could not improve on


def _geometry(m: DraftModule, common: dict[str, Any]) -> tuple[float, float, float]:
    """(y, height, depth) from the module's own numbers, else the design's common levels. A tall cabinet's implausibly low height is ignored."""
    storey = _storey(m)
    if storey == "tall":
        y, height, depth = 0.0, common["cabinetTop"], common["baseDepth"]
    elif storey == "upper":
        y, height, depth = common["upperBottom"], common["upperTierSplit"] - common["upperBottom"], common["upperDepth"]
    else:
        y, height, depth = 0.0, common["baseTop"], common["baseDepth"]
    own = m.height if m.height and not (storey == "tall" and m.height < MIN_TALL_HEIGHT) else None
    return (y if m.y is None else m.y), own or height, m.depth or depth


FRIDGE_NICHE = 1850.0        # clear height of a fridge bay (a 1800 mm fridge plus its gap); the doors above it are the cabinet over the fridge
FRIDGE_HEIGHT = 1800.0
FRIDGE_DEPTH = 620.0
FRIDGE_MODULE_DEPTH = 640.0  # a fridge bay is deeper than the base cabinets beside it
FRIDGE_SIDE_GAP = 100.0      # side panels + clearance taken off the bay's width
FRIDGE_MAX_WIDTH = 920.0     # a side-by-side fridge; a recognised bay is often wider because it includes the panels around the fridge


def fridge_bay(m: DraftModule, height: float, depth: float) -> tuple[dict[str, Any], dict[str, Any]]:
    """The extra fields of a ``tall-fridge`` cabinet and the fridge standing in it: ``({"niche", "depth"}, appliance)``."""
    niche = min(m.niche or FRIDGE_NICHE, height - 200.0)
    width = round_half_away(min(max(m.width - FRIDGE_SIDE_GAP, 500.0), FRIDGE_MAX_WIDTH), -1)
    appliance = {"type": "fridge", "name": "Tủ lạnh", "dimensions": f"{width:g} × {min(FRIDGE_HEIGHT, niche - 50.0):g} × {FRIDGE_DEPTH:g}"}
    return {"niche": niche, "depth": max(depth, FRIDGE_MODULE_DEPTH)}, appliance


def draft_operation(spec: KitchenSpec, draft: Draft) -> dict[str, Any]:
    """The design with its cabinets replaced by the draft's; room, appliances and the rest of ``common`` stay. Modules without a position
    follow the previous one on the same wall and storey (in the order given)."""
    data = to_data(spec)
    common = data["common"]
    cursor: dict[tuple[str, str], float] = {}
    count: dict[str, int] = {}
    modules: list[dict[str, Any]] = []
    appliances: list[dict[str, Any]] = []
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
        if m.type == "tall-fridge":
            extra, fridge = fridge_bay(m, height, depth)
            entry.update(extra)
            appliances.append({**fridge, "id": f"TB{len(appliances) + 1}", "module": entry["id"]})
        modules.append(entry)
    data["module"] = modules
    data["appliances"] = appliances               # the old ones pointed at the old module ids
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
        if m.type == "tall-fridge":
            extra, fridge = fridge_bay(m, height, depth)
            entry.update(extra)
            entry["appliance"] = fridge
        out.append(entry)
    return out, len(draft.modules) - len(placed)
