"""Wording for a vision model that reads a kitchen photo or drawing into a module draft (rule R1: pure, no I/O)."""
from __future__ import annotations

from typing import Any


PANELS: dict[str, Any] = {      # each leaf and pane of a door / window: how it opens, its handle, its rail
    "type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "row": {"type": "INTEGER"}, "operation": {"type": "STRING"}, "handle": {"type": "BOOLEAN"}, "front": {"type": "BOOLEAN"}},
        "required": ["operation"]}}

SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "modules": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "type": {"type": "STRING"}, "wall": {"type": "STRING"}, "width": {"type": "NUMBER"}, "fromCorner": {"type": "NUMBER"},
            "height": {"type": "NUMBER"}, "depth": {"type": "NUMBER"}, "confidence": {"type": "NUMBER"}, "label": {"type": "STRING"}},
            "required": ["type", "wall", "width"]}},
        "openings": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "kind": {"type": "STRING"}, "wall": {"type": "STRING"},
            "axes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"fromCorner": {"type": "NUMBER"}, "confidence": {"type": "NUMBER"}},
                                                "required": ["fromCorner"]}},
            "sill": {"type": "NUMBER"}, "head": {"type": "NUMBER"}, "edgesSeen": {"type": "STRING"}, "style": {"type": "STRING"},
            "leaves": {"type": "INTEGER"}, "transomPanes": {"type": "INTEGER"}, "panels": PANELS, "confidence": {"type": "NUMBER"}},
            "required": ["kind", "wall", "axes"]}},
        "photoOpenings": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "kind": {"type": "STRING"}, "style": {"type": "STRING"}, "leaves": {"type": "INTEGER"}, "edgesSeen": {"type": "STRING"},
            "aspect": {"type": "NUMBER"}, "axesRatio": {"type": "ARRAY", "items": {"type": "NUMBER"}},
            "hAxesRatio": {"type": "ARRAY", "items": {"type": "NUMBER"}}, "transomPanes": {"type": "INTEGER"}, "panels": PANELS,
            "confidence": {"type": "NUMBER"}},
            "required": ["kind", "aspect"]}},
        "room": {"type": "OBJECT", "properties": {"ceiling": {"type": "NUMBER"}}},
        "materials": {"type": "OBJECT", "properties": {k: {"type": "STRING"} for k in ("base", "upper", "tall", "countertop", "wall", "floor")}},
        "confidence": {"type": "NUMBER"},
        "notes": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["modules"],
}


def recognition_text(kind: str, module_types: tuple[str, ...]) -> str:
    what = "a photograph of a kitchen" if kind == "photo" else "a technical drawing (plan or elevation) of a kitchen"
    return (
        f"You are reading {what}. List the cabinet modules you can see, wall by wall, in millimetres.\n"
        f"- type: one of {', '.join(module_types)}.\n"
        "- wall: 'back' (facing wall), 'left' or 'right', as seen when standing in the room facing the back wall.\n"
        "- width: the front width of the module. Use printed dimensions when the drawing has them; otherwise estimate from "
        "standard sizes (base units 300-900, a hob or sink unit 600-900, a tall unit 600).\n"
        "- fromCorner: distance from the left end of that wall to the module's left edge, when you can tell.\n"
        "- height and depth only when printed or obvious. confidence 0-1 for each module: be honest, use below 0.5 when guessing.\n"
        "openings: the doors, windows and open passages in those walls (not cabinet or appliance doors): kind door, window or passage; wall; "
        "axes = every vertical edge or divider you see across it, as fromCorner measured like the modules' fromCorner, outer edges included; "
        "sill and head heights above the floor; edgesSeen 'casing' when the edges you measured are the outer edges of a trim, else 'hole'; "
        "style swing, sliding, folding, fixed or top-hung; leaves; confidence; and, for every opening, transomPanes (how many panes the "
        "row above the first horizontal divider has, when there is one) and panels: every leaf and fixed pane row by row (row 0 = the main "
        "row, 1 = the transom), left to right, each with operation (swing, sliding, folding, fixed, top-hung), handle (a handle or pull is "
        "visible on it) and front (a sliding leaf on the front rail: its edge covers the leaf next to it).\n"
        "If the picture shows no cabinets at all but a door or window, return an empty modules list and photoOpenings instead: kind, style, "
        "leaves (the ones that open or slide), edgesSeen, aspect = height / width of the opening, axesRatio = each vertical divider as a "
        "fraction of the width from the left edge, hAxesRatio = each horizontal divider as a fraction of the height from the sill, transomPanes, panels, confidence.\n"
        "Also give room.ceiling if shown, the materials you see (base, upper, tall, countertop, wall, floor) as short names, "
        "and notes for anything you could not read. Never invent modules that are not visible. "
        "If the image is not a kitchen, return an empty modules list and say so in notes.")
