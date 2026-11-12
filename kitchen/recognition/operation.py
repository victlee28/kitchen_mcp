"""Draft -> one ``replace`` operation over the current design. The caller previews it with ``propose``; this never applies anything."""
from __future__ import annotations

from typing import Any

from ..numeric import round_half_away
from .draft import Draft, DraftModule
from ..words import say

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
    appliance = {"type": "fridge", "name": say("name.appliance.fridge"), "dimensions": f"{width:g} × {min(FRIDGE_HEIGHT, niche - 50.0):g} × {FRIDGE_DEPTH:g}"}
    return {"niche": niche, "depth": max(depth, FRIDGE_MODULE_DEPTH)}, appliance


def runs_from_draft(draft: Draft, common: dict[str, Any]) -> dict[str, Any]:
    """A flat draft as a ``recognized-runs/1`` document, so every recognition is placed the same way (``build_layout`` checks it).

    The draft gives each cabinet a wall and a ``fromCorner`` measured the way the walls are: on the back wall from its right-hand end towards
    the left, on the side walls from the back corner towards the room. A run's ``s`` grows to the right of someone looking at the doors, so the
    back and left runs are mirrored (``s = length - fromCorner - width``) and the right run is not. A cabinet with no position follows the
    previous one of its wall and storey; one with no size takes the design's common levels. The left run ends, and the right run starts, at
    the corner of the back run (the joints)."""
    cursor: dict[tuple[str, str], float] = {}
    placed: dict[str, list[tuple[float, DraftModule]]] = {"left": [], "back": [], "right": []}
    for m in draft.modules:
        if m.wall not in placed:
            continue
        key = (m.wall, _storey(m))
        start = m.fromCorner if m.fromCorner is not None else cursor.get(key, 0.0)
        cursor[key] = start + m.width
        placed[m.wall].append((start, m))
    runs: list[dict[str, Any]] = []
    for wall in ("left", "back", "right"):
        items = placed[wall]
        if not items:
            continue
        length = max(start + m.width for start, m in items)
        modules: list[dict[str, Any]] = []
        for start, m in items:
            y, height, depth = _geometry(m, common)
            entry: dict[str, Any] = {"type": m.type, "s": start if wall == "right" else length - start - m.width, "width": m.width,
                                     "y": y, "height": height, "depth": depth, "confidence": m.confidence}
            if m.label:
                entry["name"] = m.label
            if m.niche:
                entry["niche"] = m.niche
            modules.append(entry)
        runs.append({"id": wall, "length": length, "modules": modules})
    ids = [r["id"] for r in runs]
    joints = [{"a": a, "b": b, "angle": 90} for a, b in (("left", "back"), ("back", "right")) if a in ids and b in ids]
    return {"schema": "recognized-runs/1", "unit": "mm", "runs": runs, "joints": joints}
