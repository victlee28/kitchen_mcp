"""The scene sentence of a picture looking down on the room from above (the overview, the orthographic plan): each area the picture
holds named in a short phrase seen from above and placed where it lies in the image ("a kitchen run ... with a sink and a cooktop, in the
top right of the image; a low TV media console ..., in the top left of the image; a staircase ..., in the middle of the image").
An eye-level description (a TV mounted on the wall above a niche) read against a picture from above made the model paint TV units over
every cabinet block. Pure (rule R1).
"""
from __future__ import annotations

from typing import Any

from .. import builtin
from ..numeric import round_half_away
from ..catalog import Catalog
from ..spec import KitchenSpec
from .photo import text
from .seen import Box, Seen, where

KITCHEN_FEATURES = (("base-sink", "a sink"), ("base-cooktop", "a cooktop"), ("tall-fridge", "a tall fridge cabinet"), ("tall", "tall cabinets"))
STRUCTURE_TEXT = {"structure-stair": "topdown-stair"}       # floorplan structures named in the scene (catalog kind prompt-text)


def _union(boxes: list[Box]) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _kitchen(types: set[str], catalog: Catalog) -> str:
    feats = list(dict.fromkeys(name for t, name in KITCHEN_FEATURES if t in types))
    base = text("topdown-kitchen", catalog)
    return base + (" with " + ", ".join(feats[:-1]) + (" and " if len(feats) > 1 else "") + feats[-1] if feats else "")


def areas(spec: KitchenSpec, seen: Seen, catalog: Catalog = builtin.CATALOG) -> list[str]:
    """The phrases of the areas the picture shows, top to bottom then left to right: each cabinet run (kitchen, TV unit, furniture unit)
    and the named floorplan structures (stairs), each with where it lies in the image."""
    runs = {r.id: r for r in spec.runs}
    groups: dict[str, list[Any]] = {}
    for m in spec.module:
        if seen.has(m.id) and m.id in seen.boxes:
            groups.setdefault(m.run or f"wall:{m.wall}", []).append(m)
    found: list[tuple[Box, str]] = []
    for key, mods in groups.items():
        r = runs.get(key)
        if r is not None and r.purpose == "tv":
            phrase = text("topdown-tv", catalog)
        elif r is not None and r.purpose == "unit":
            phrase = text(f"topdown-unit-{r.unitLayout}", catalog) if r.unitLayout else ""
            phrase = phrase or text("topdown-unit-low", catalog)
        else:       # from above the worktop covers the base cabinets: the run's sink and cooktop count though only its top is seen
            phrase = _kitchen({m.type for m in spec.module if (m.run or f"wall:{m.wall}") == key}, catalog)
        found.append((_union([seen.boxes[m.id] for m in mods]), phrase))
    for module, kind in sorted(seen.parts):
        if kind in STRUCTURE_TEXT and module in seen.boxes:
            found.append((seen.boxes[module], text(STRUCTURE_TEXT[kind], catalog)))
    found.sort(key=lambda f: (round_half_away((f[0][1] + f[0][3]) / 2 / max(seen.size[1], 1.0) * 3, 0), (f[0][0] + f[0][2]) / 2))
    return [f"{phrase}, {where(box, seen.size)}" for box, phrase in found if phrase]


def scene(spec: KitchenSpec, seen: Seen, style: str, materials: str, extra: str, catalog: Catalog = builtin.CATALOG) -> str:
    """The scene sentence of a picture from above: the room, its areas where they lie, the kitchen's materials."""
    parts = areas(spec, seen, catalog)
    only_kitchen = bool(parts) and all(p.startswith(text("topdown-kitchen", catalog)) for p in parts)
    room = f"a {style} kitchen" if only_kitchen else f"a {style} home interior"
    out = f"photorealistic top-down photograph of {room} seen from above"
    if parts:
        out += ", showing: " + "; ".join(parts)
    return out + "; " + ", ".join(x for x in (materials, extra, "realistic materials, sharp details, architectural photography") if x)
