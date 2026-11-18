"""Prompt text for one layer / one scene: the English style sentence of the whole kitchen and the sentence for one edited part."""
from __future__ import annotations

from typing import Any

from .. import builtin, lexicon, tv_system, vocab
from ..catalog import Catalog
from .photo import text, words
from .seen import Seen, kitchen_modules, runs_seen, shown, worktop_seen
from . import topdown
from ..layers import ROLES
from ..spec import KitchenSpec

NEGATIVE_LAYER = words("negative-layer")   # catalog kind prompt-text (builtin); negative_prompt takes the merged catalog

_STYLES = {"Modern": "modern", "Classic": "classic", "Neoclassical": "neoclassical", "Transitional": "transitional",
               "Minimalist": "minimalist"}


def global_prompt(spec: KitchenSpec, catalog: Catalog = builtin.CATALOG, seen: Seen | None = None) -> str:
    """The scene sentence of a picture: the room, the furniture units in it (TV unit, wine cabinet...), the kitchen's materials.
    ``seen``: what the picture of one view holds (``prompts.seen``) -- only what it shows is described; None: the whole design."""
    style = _STYLES.get(spec.style or "", (spec.style or "modern").lower())
    v = spec.common.material
    kitchen = kitchen_modules(spec)
    in_view = shown(spec, seen)
    kitchen_seen = any(m.id in kitchen for m in in_view)
    worktop = worktop_seen(spec, seen)

    def en(key: str) -> str:
        return vocab.to_english(v.get(key, ""), catalog)
    mats = ", ".join(x for x in (en("base") and f"base cabinets {en('base')}",
                                 en("upper") and f"wall cabinets {en('upper')}",
                                 worktop and en("countertop") and f"countertop {en('countertop')}") if x)
    wall_tile = v.get("wallTile", "")
    if worktop and wall_tile and wall_tile != "Đá ốp tường đồng bộ mặt bàn" and vocab.to_english(wall_tile, catalog):
        mats = ", ".join(x for x in (mats, f"backsplash {vocab.to_english(wall_tile, catalog)}") if x)
    extra = ", ".join(dict.fromkeys([*lexicon.tag_phrases(spec.styleTags), *(spec.aiHints or [])]))
    if seen is not None and seen.top_down:      # from above: each area named where it lies, not the eye-level look of a TV wall
        return topdown.scene(spec, seen, style, mats, extra, catalog)
    tv_seen = runs_seen(spec, seen, "tv")
    units = [unit_text(spec, r, catalog) for r in runs_seen(spec, seen, "unit")]
    furniture = ", ".join(x for x in (tv_text(spec, catalog, tv_seen[0]) if tv_seen else "", *units) if x)
    if kitchen_seen or not in_view or not furniture:
        room = f"a {style} kitchen, "
    elif tv_seen:
        room = f"a {style} living room with "
    else:
        room = f"a {style} interior with "
    return (f"photorealistic interior photograph of {room}" + (f"{furniture}, " if furniture else "") + (f"{mats}, " if mats else "")
            + (f"{extra}, " if extra else "") + "realistic materials, sharp details, architectural photography").replace(", ,", ",")


TV_UNIT = {k: text(f"tv-{k}") for k in ("columns", "shelves", "full")}   # catalog kind prompt-text (builtin)


def tv_text(spec: KitchenSpec, catalog: Catalog = builtin.CATALOG, run: str | None = None) -> str:
    """What a TV unit looks like, for the prompt (``run``, else the first TV run; the panel behind the TV when there is one).
    ``""`` for a design without a TV unit."""
    tv_runs = sorted(tv_system.tv_runs(spec))
    if not tv_runs:
        return ""
    first = run if run in tv_runs else tv_runs[0]
    out = text(f"tv-{tv_system.layout_of(spec, first) or 'columns'}", catalog) or text("tv-columns", catalog)
    if any(m.backPanel is not None for m in spec.module if m.run == first):
        out += ", a smooth panel in the cabinet finish on the wall behind the TV"
    return out


def unit_text(spec: KitchenSpec, run: str, catalog: Catalog = builtin.CATALOG) -> str:
    """What a furniture unit laid by a unit-layout looks like (catalog kind ``prompt-text``, id ``unit-<layout>``); ``""`` when none is written."""
    r = next((x for x in spec.runs if x.id == run), None)
    return text(f"unit-{r.unitLayout}", catalog) if r is not None and r.unitLayout else ""


def layer_prompt(spec: KitchenSpec, layer: dict[str, Any], instruction: str = "", material: str | None = None) -> str:
    role = ROLES.get(layer.get("type") or "", (None, "kitchen element"))[1]
    material_text = material or layer.get("material") or ""
    en = vocab.to_english(material_text)
    parts = [role, en and f"made of {en}", material_text and f"({material_text})", instruction.strip(),
             "keep exactly the same shape, edges, panel gaps and perspective", "consistent lighting with the surrounding scene"]
    return ", ".join(p for p in parts if p)


def edit_task_prompt(spec: KitchenSpec, layer: dict[str, Any], instruction: str = "", material: str | None = None) -> str:
    """``layer_prompt`` plus the realism tail every region edit carries."""
    return layer_prompt(spec, layer, instruction, material) + ", photorealistic, matching scene lighting and grain, realistic texture, soft contact shadows"
