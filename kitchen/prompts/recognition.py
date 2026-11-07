"""Wording for a vision model that reads a kitchen photo or drawing into a module draft (rule R1: pure, no I/O)."""
from __future__ import annotations

from typing import Any

SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "modules": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "type": {"type": "STRING"}, "wall": {"type": "STRING"}, "width": {"type": "NUMBER"}, "fromCorner": {"type": "NUMBER"},
            "height": {"type": "NUMBER"}, "depth": {"type": "NUMBER"}, "confidence": {"type": "NUMBER"}, "label": {"type": "STRING"}},
            "required": ["type", "wall", "width"]}},
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
        "Also give room.ceiling if shown, the materials you see (base, upper, tall, countertop, wall, floor) as short names, "
        "and notes for anything you could not read. Never invent modules that are not visible. "
        "If the image is not a kitchen, return an empty modules list and say so in notes.")
