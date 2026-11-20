"""Auto place (pure, rule R1): what to build for each drawn object of an imported floorplan, from what the plan says about it.

A piece of furniture of the plan becomes a cabinet system and a door or window hole becomes a room opening, chosen from the element's
``tag`` and ``label`` (the plan's words) and, when those say too little, from its size. The words and the sizes are the workshop's data
(``defaults.autoPlace``); the cabinets themselves come from the same generators as a right-click sentence ("tạo hệ tủ bếp", "tạo hệ tủ
tivi", "tạo hệ tủ rượu"), so an auto-placed system is the one the menu would have made.

``furniture_choice`` decides for a piece of furniture: ``tv`` (a TV unit), ``unit`` (a furniture unit of a ``unit-layout``: wine cabinet,
low cabinets), ``kitchen`` (a kitchen run with sink and cooktop as the generator lays them), ``plain`` (base cabinets), or ``skip`` with
its reason (not a cabinet: a bed, a sofa; too shallow for a cabinet).
``opening_choice`` decides the type of a door or window hole: the type its label names (a sliding door), else the kind's default, kept
when the hole's width is within the type's range, else the type of the same kind whose range holds the width (the one whose default
width is nearest), else the first choice kept at the drawn width (``oversize``).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import builtin, defaults as defaults_mod, tv_system, unit_system
from .catalog import Catalog
from .jsonview import as_dict, as_list
from .lexicon import fold
from .openings.normalize import width_range
from .openings.types import get as opening_type



@dataclass(frozen=True)
class Choice:
    kind: str                     # tv | unit | kitchen | plain | skip
    prompt: str | None = None     # the words handed to the generator (the element's label, or the kitchen word)
    unit: str | None = None       # the unit layout (kind ``unit``)
    reason: str = ""              # why: tag | label | size | not-cabinet | too-shallow


def rules(catalog: Catalog = builtin.CATALOG) -> dict[str, Any]:
    """The auto-place words and sizes of the catalog (``defaults.autoPlace``), with the builtin values for what it leaves out."""
    return dict(defaults_mod.of(catalog).auto_place)      # the item's fields over the builtin item's (``defaults._build``)


def _words(value: Any) -> list[str]:
    return [fold(str(w)) for w in as_list(value) or [] if isinstance(w, str) and w]


def _tag(value: Any) -> str:
    """A plan tag as compared: lower case, spaces as underscores (``Cabinet Kitchen Set`` = ``cabinet_kitchen_set``)."""
    return "_".join(str(value or "").strip().lower().split())


def _tags(value: Any) -> list[str]:
    return [_tag(w) for w in as_list(value) or [] if isinstance(w, str) and w]


def _tag_in(tag: str, tags: Sequence[str]) -> bool:
    """``tag`` is one of ``tags`` or a kind of one (``cabinet_kitchen_set`` is a ``cabinet``)."""
    return any(tag == t or tag.startswith(t + "_") for t in tags)


def depth_of(outline: Sequence[tuple[float, float]]) -> float:
    """How deep a drawn object is: its narrowest width across, over the directions of its own edges (a box drawn at any angle)."""
    pts = list(outline)
    best: float | None = None
    for (ax, az), (bx, bz) in zip(pts, pts[1:] + pts[:1]):
        dx, dz = bx - ax, bz - az
        n = (dx * dx + dz * dz) ** 0.5
        if n < 1e-6:
            continue
        across = [((x - ax) * -dz + (z - az) * dx) / n for x, z in pts]
        width = max(across) - min(across)
        best = width if best is None else min(best, width)
    return best or 0.0


def furniture_choice(element: Mapping[str, Any], depth: float, catalog: Catalog = builtin.CATALOG) -> Choice:
    """What to build in place of the floorplan furniture ``element`` (its ``tag`` and ``label``), ``depth`` mm deep."""
    r = rules(catalog)
    tag = _tag(element.get("tag"))
    label = str(element.get("label") or "").strip()
    if not _tag_in(tag, _tags(r.get("cabinetTags"))):
        return Choice("skip", reason="not-cabinet")
    unit_tags = {_tag(k): str(v) for k, v in (as_dict(r.get("unitTags")) or {}).items()}
    if tv_system.asks_tv(label):
        return Choice("tv", label, reason="label")
    if _tag_in(tag, _tags(r.get("tvTags"))):
        return Choice("tv", label or None, reason="tag")
    unit = unit_system.asks(label, catalog) if label else None
    if unit is not None:
        return Choice("unit", label, unit, reason="label")
    tagged_unit = next((v for t, v in unit_tags.items() if _tag_in(tag, [t])), None)
    if tagged_unit is not None:
        return Choice("unit", label or None, tagged_unit, reason="tag")
    kitchen_words = _words(r.get("kitchenWords"))
    if _tag_in(tag, _tags(r.get("kitchenTags"))) or any(w in fold(label) for w in kitchen_words):
        first = next((str(w) for w in as_list(r.get("kitchenWords")) or [] if isinstance(w, str) and w), None)
        return Choice("kitchen", label or first, reason="tag")
    if depth >= float(r.get("kitchenMinDepth") or 0):            # a deep cabinet nobody named: base cabinets as deep as it
        return Choice("plain", reason="size")
    if depth >= float(r.get("unitMinDepth") or 0):               # a shallow one: the low unit
        return Choice("unit", None, str(r.get("shallowUnit") or "low"), reason="size")
    return Choice("skip", reason="too-shallow")


def opening_choice(kind: str, preferred: str, width: float, catalog: Catalog = builtin.CATALOG) -> tuple[str, str | None]:
    """``(opening type, size)`` for a ``kind`` hole ``width`` mm wide. ``preferred``: the type the label names (a sliding door) or the kind's
    default. The types of the kind whose width range holds the hole are tried, those of ``preferred``'s family first (``door-sliding``:
    two or four leaves), plain types before their variants (a transom), the one whose default width is nearest the hole winning: a 3920 mm
    sliding door gets four leaves, a 900 mm door one. ``size`` is "keep" when no type fits (``preferred`` kept at the drawn width)."""
    def fits(type_id: str) -> bool:
        low, high = width_range(opening_type(catalog, type_id), kind)
        return low <= width <= high

    def key(it: Any) -> tuple[bool, float, str]:
        d = (as_dict(it.data) or {}).get("defaultWidth")
        gap = abs(float(d) - width) if isinstance(d, (int, float)) and not isinstance(d, bool) else 1e9
        return len(it.id.split("-")) > 3, gap, it.id

    fitting = [it for it in catalog.all("opening-type") if str((as_dict(it.data) or {}).get("kind") or "") == kind and fits(it.id)]
    family = "-".join(preferred.split("-")[:2])
    pool = [it for it in fitting if it.id == family or it.id.startswith(family + "-")] or fitting
    if pool:
        return min(pool, key=key).id, None
    return preferred, "keep"
