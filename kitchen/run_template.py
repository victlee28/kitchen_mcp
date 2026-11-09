"""A kitchen described in words, as the cabinets of ONE straight run (shell zone: it builds on ``intent``, which uses Pydantic; the golden file pins it).

``intent.from_template`` already turns a described kitchen (fridge, loft row, black worktop, door colours, handles...) into a whole design with
the cabinets along the back wall. Here those cabinets are re-expressed along a line: ``run_line.plan_on_line`` then stands them against any
edge, so a sentence can be turned into cabinets at the place the user clicked.
"""
from __future__ import annotations

from typing import Any

from .intent import KitchenTemplate, from_template
from .spec import Module

COMMON_KEYS = ("backsplashHeight", "backsplashHeightMm", "wallTilePattern")


def _device(t: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": t.type, "name": t.name}
    if t.dimensions:
        entry["dimensions"] = t.dimensions
    return entry


def _module(m: Module, length: float) -> dict[str, Any]:
    """One back-wall cabinet as a run cabinet. The back wall counts ``fromCorner`` from its right-hand end, a run counts ``s`` from its left-hand
    end, so positions are mirrored and the door list is read the other way round."""
    entry: dict[str, Any] = {"type": m.type, "width": m.width, "s": length - m.fromCorner - m.width, "y": m.y, "height": m.height, "depth": m.depth}
    if m.name:
        entry["name"] = m.name
    if m.doors:
        entry["doors"] = list(reversed(m.doors))
    if m.frontSections:
        entry["frontSections"] = [{"type": s.type, "height": s.height} for s in m.frontSections]
    if m.niche:
        entry["niche"] = m.niche
    if m.hingeSides:
        entry["hingeSides"] = list(m.hingeSides)
    if m.doorStyle:
        entry["doorStyle"] = m.doorStyle
    return entry


def run_from_template(color: KitchenTemplate, length: float) -> dict[str, Any]:
    """``{"modules": [...], "common": {...}, "length"}`` for a straight run ``length`` mm long.

    Each module is ``{type, width, s, y, height, depth, name?, doors?, frontSections?, niche?, appliances?, ...}`` (``s`` from the run's start).
    ``common`` holds only what the sentence itself asked for (materials, handle, backsplash), to be merged into the design's own.
    """
    t = color.model_copy(update={"geometry_edit": "I", "island": False, "peninsula": False, "backWallLength": float(length)})
    spec = from_template(t)
    back = [m for m in spec.module if m.wall == "back"]
    entries = {m.id: _module(m, length) for m in back}
    for tb in spec.appliances:
        if tb.module in entries:                                  # a fridge or a hood stands in its cabinet
            entries[tb.module].setdefault("appliances", []).append(_device(tb))
        elif tb.wall == "back" and tb.center is not None:        # a sink / hob / tap stands on the worktop above the cabinet under its centre
            hit = next((m for m in back if m.storey == "base" and m.fromCorner <= tb.center < m.endAt), None)
            if hit:
                entries[hit.id].setdefault("appliances", []).append({**_device(tb), "wall": "back", "center": length - tb.center})
    common: dict[str, Any] = {}
    if color.material:
        common["material"] = dict(color.material)
    if color.handleVariant or color.handleMaterial:
        common["handle"] = spec.common.handle.model_dump(exclude_none=True)
    for key in COMMON_KEYS:
        value = getattr(spec.common, key)
        if value not in (None, "standard"):
            common[key] = value
    modules = sorted(entries.values(), key=lambda e: e["s"])
    return {"modules": modules, "common": common, "length": float(length)}
