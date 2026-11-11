"""Prompt text for one layer / one scene: the English style sentence of the whole kitchen and the sentence for one edited part."""
from __future__ import annotations

from typing import Any

from .. import lexicon, tv_system, vocab
from ..layers import ROLES
from ..spec import KitchenSpec

NEGATIVE_LAYER = ["distorted geometry", "warped cabinet doors", "changed perspective", "extra handles", "text", "watermark",
            "blurry", "low quality", "people"]

_STYLES = {"Modern": "modern", "Classic": "classic", "Neoclassical": "neoclassical", "Transitional": "transitional",
               "Minimalist": "minimalist"}


def global_prompt(spec: KitchenSpec) -> str:
    style = _STYLES.get(spec.style or "", (spec.style or "modern").lower())
    v = spec.common.material
    mats = ", ".join(x for x in (vocab.to_english(v.get("base", "")) and f"base cabinets {vocab.to_english(v.get('base', ''))}",
                                 vocab.to_english(v.get("upper", "")) and f"wall cabinets {vocab.to_english(v.get('upper', ''))}",
                                 vocab.to_english(v.get("countertop", "")) and f"countertop {vocab.to_english(v.get('countertop', ''))}") if x)
    wall_tile = v.get("wallTile", "")
    if wall_tile and wall_tile != "Đá ốp tường đồng bộ mặt bàn" and vocab.to_english(wall_tile):
        mats = ", ".join(x for x in (mats, f"backsplash {vocab.to_english(wall_tile)}") if x)
    extra = ", ".join(dict.fromkeys([*lexicon.tag_phrases(spec.styleTags), *(spec.aiHints or [])]))
    only_tv = bool(spec.module) and all(m.id in tv_system.tv_modules(spec) for m in spec.module)
    tv = (tv_text(spec) + ", ") if tv_system.tv_runs(spec) else ""
    room = f"a {style} living room with " if only_tv else f"a {style} kitchen, "
    return (f"photorealistic interior photograph of {room}{tv}{mats}, "
            + (f"{extra}, " if extra else "") + "realistic materials, sharp details, architectural photography").replace(", ,", ",")


TV_UNIT = {
    "columns": "a built-in TV wall unit: a low wall-to-wall media console with drawers and no stone top, an open TV niche above it with a flat TV "
               "mounted on the wall, tall storage columns at both ends and a slim floating open shelf above the TV",
    "shelves": "a built-in TV wall unit: a low wall-to-wall media console with drawers and no stone top, a flat TV mounted on the wall above it "
               "and slim open floating shelves on the wall beside the TV",
    "full": "a built-in TV wall unit closed from floor to ceiling: tall cabinets on both sides and wall cabinets above an open TV niche, a low "
            "media console with drawers in the niche and a flat TV mounted on the wall",
}


def tv_text(spec: KitchenSpec) -> str:
    """What the TV units of the design look like, for the prompt (the layout of the first one; the panel behind the TV when there is one).
    ``""`` for a design without a TV unit."""
    tv_runs = sorted(tv_system.tv_runs(spec))
    if not tv_runs:
        return ""
    first = tv_runs[0]
    text = TV_UNIT.get(tv_system.layout_of(spec, first) or "columns", TV_UNIT["columns"])
    if any(m.backPanel is not None for m in spec.module if m.run == first):
        text += ", a smooth panel in the cabinet finish on the wall behind the TV"
    return text


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
