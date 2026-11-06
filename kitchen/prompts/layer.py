"""Prompt text for one layer / one scene: the English style sentence of the whole kitchen and the sentence for one edited part."""
from __future__ import annotations

from .. import lexicon, vocab
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
    return (f"photorealistic interior photograph of a {style} kitchen, {mats}, "
            + (f"{extra}, " if extra else "") + "realistic materials, sharp details, architectural photography").replace(", ,", ",")


def layer_prompt(spec: KitchenSpec, layer: dict, instruction: str = "", material: str | None = None) -> str:
    role = ROLES.get(layer.get("type") or "", (None, "kitchen element"))[1]
    material_text = material or layer.get("material") or ""
    en = vocab.to_english(material_text)
    parts = [role, en and f"made of {en}", material_text and f"({material_text})", instruction.strip(),
             "keep exactly the same shape, edges, panel gaps and perspective", "consistent lighting with the surrounding scene"]
    return ", ".join(p for p in parts if p)


def edit_task_prompt(spec: KitchenSpec, layer: dict, instruction: str = "", material: str | None = None) -> str:
    """``layer_prompt`` plus the realism tail every region edit carries."""
    return layer_prompt(spec, layer, instruction, material) + ", photorealistic, matching scene lighting and grain, realistic texture, soft contact shadows"
