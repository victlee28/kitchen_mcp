"""A sentence about a room door, window or passage at a clicked point, as one design operation (``edit_intent.opening_wish`` reads the
sentence; this places what it asks for). Pure (rule R1).

* Clicked on an opening the design has (or selected it): it becomes the type asked for (``update-opening``); its place and width stay,
  its height too unless the kind changes or the sentence gives one.
* Clicked in the hole of a floorplan opening element (or selected it): a new opening fills that hole, its place and width.
* Elsewhere on a wall: a new opening centred at the point, the type's default width (``opening-type.defaultWidth``) unless the sentence
  gives one.
* The type: the one the sentence names (a type of the catalog, the user's own saved ones included), else the default of the kind.
* Height: the sentence's, else the type's ``defaultHeight``. A door stands on the floor. A window sits as high as the sentence says
  ("cách sàn 900"), else as the clicked window or the floorplan element records, else at ``defaults.openings.windowSill`` (900 mm)
  whatever its type.
* "sửa / chỉnh / nâng ... cửa sổ": the clicked opening keeps its type, the sizes said change (``update-opening``); "xóa / bỏ ...":
  it is removed (``remove-opening``; a floorplan opening leaves a tombstone).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..catalog import Catalog
from ..defaults import of as defaults_of
from ..errors import InvalidInput
from ..jsonview import as_dict
from ..numeric import round_half_away
from .contract import Opening
from .normalize import normalize, width_range
from .types import default_type, get, num
from .wall_axes import WallAxis, nearest

Pt = tuple[float, float]
REACH_MM = 900.0               # a click farther than this from every wall axis is on no wall
def default_width(type_data: Mapping[str, Any], kind: str) -> float:
    """The type's ``defaultWidth`` (``types.get`` fills it from ``defaults.openingKinds`` when the type leaves it out)."""
    return num(type_data, "defaultWidth", 900.0 if kind != "window" else 1200.0)


class SizeQuestion(InvalidInput):
    """The width asked for (or the hole's) is outside the opening type's range: the user is asked whether to keep it or fit it."""


def _sized(width: float, data: Mapping[str, Any], kind: str, type_id: str, wish: Mapping[str, Any]) -> tuple[float, bool]:
    """``(width, oversize)``: inside the type's range as it is; outside it, kept (``oversize``) or brought to the nearest end of the range as
    the sentence answered; with no answer, raises ``SizeQuestion``."""
    low, high = width_range(data, kind)
    if low <= width <= high:
        return width, False
    if wish.get("size") == "keep":
        return width, True
    if wish.get("size") == "fit":
        return (high if width > high else low), False
    raise SizeQuestion(f"Width {width:g} mm is outside the range of type {type_id} ({low:g}..{high:g} mm)", code="opening-size-ask",
                       params={"width": width, "min": low, "max": high, "type": type_id})


def operation(wish: Mapping[str, Any], point: Pt, axes: Sequence[WallAxis], catalog: Catalog, existing: Sequence[Opening] = (),
              selected: str | None = None, elements: Sequence[Mapping[str, Any]] = (), country: str | None = None
              ) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """``(operation, what, facts)`` for ``wish`` (``edit_intent.opening_wish``, action make / replace) at ``point`` (the axes' frame).
    ``what``: ``replaced`` | ``hole`` | ``added``; ``facts``: id, type, width, height for the summary. Raises InvalidInput (code
    ``opening-no-wall`` or normalize's) when nothing can be placed."""
    from ..recognition.openings import clicked_opening, element_at, element_hole
    kind = str(wish.get("kind") or "door")
    named = wish.get("type")
    width_asked = wish.get("width")
    height_asked = wish.get("height")
    sill_asked = wish.get("sill")
    action = wish.get("action")
    target = clicked_opening(point, axes, existing, selected)
    if action in ("remove", "edit"):
        if target is None:
            raise InvalidInput("Right-click the door or window to change or remove", code="opening-none-clicked")
        oid = target.source_element or target.id
        facts = {"id": target.id, "type": target.opening_type, "width": target.width, "height": target.height, "sill": target.sill}
        if action == "remove":
            return {"op": "remove-opening", "id": oid}, "removed", facts
        changes: dict[str, Any] = {}
        data = get(catalog, target.opening_type)
        if width_asked:
            changes["width"], oversize = _sized(float(width_asked), data, target.kind, target.opening_type, wish)
            if oversize:
                changes["oversize"] = True
        if height_asked:
            changes["height"] = float(height_asked)
        if sill_asked is not None:
            if target.kind != "window":
                raise InvalidInput("A door stands on the floor: only a window has a height above the floor", code="opening-door-sill")
            changes["sill"] = float(sill_asked)
        if not changes:
            raise InvalidInput("Say what to change: its width, its height, or how far above the floor it sits", code="opening-nothing-to-change")
        changes.update(source="human", unsure=[])
        facts.update({k: changes[k] for k in ("width", "height", "sill") if k in changes})
        return {"op": "update-opening", "id": oid, "changes": changes}, "edited", facts
    if target is not None:
        type_id = str(named or (target.opening_type if target.kind == kind else default_type(catalog, kind)))
        data = get(catalog, type_id)
        kind = str(data.get("kind") or kind)
        height = float(height_asked) if height_asked else (target.height if target.kind == kind else num(data, "defaultHeight", 2200.0))
        width, oversize = _sized(float(width_asked) if width_asked else target.width, data, kind, type_id, wish)
        changes: dict[str, Any] = {"kind": kind, "openingType": type_id, "width": width, "height": height, "source": "human", "unsure": [],
                                   "oversize": oversize}
        if type_id != target.opening_type:
            changes.update(axes=None, hAxes=None, leaves=None)
        changes["sill"] = 0.0 if kind != "window" else (
            float(sill_asked) if sill_asked is not None else target.sill if target.kind == "window" else window_sill(catalog))
        return ({"op": "update-opening", "id": target.source_element or target.id, "changes": changes}, "replaced",
                {"id": target.id, "type": type_id, "width": width, "height": height, "sill": changes["sill"]})
    type_id = str(named or default_type(catalog, kind))
    data = get(catalog, type_id)
    kind = str(data.get("kind") or kind)
    height = float(height_asked) if height_asked else num(data, "defaultHeight", 2200.0 if kind != "window" else 1200.0)
    element = next((e for e in elements if selected and e.get("id") == selected and e.get("kind") == "opening"), None) \
        or element_at(point, elements)        # a selected wall: the opening element under the click
    sill = 0.0 if kind != "window" else (float(sill_asked) if sill_asked is not None else drawn_sill(element) or window_sill(catalog))
    raw: dict[str, Any] = {"kind": kind, "openingType": type_id, "source": "human", "height": height, "sill": sill}
    hole = element_hole(element, axes) if element is not None else None
    if hole is not None:
        axis, center, width = hole
        width, oversize = _sized(float(width_asked) if width_asked else float(round_half_away(width, 0)), data, kind, type_id, wish)
        raw.update(wallAxis=axis.ref().to_data(), center=round_half_away(center, 1), width=width, **({"oversize": True} if oversize else {}))
        if element is not None and element.get("id"):
            raw["sourceElement"] = str(element["id"])     # it takes the drawn element's place: the element is no longer built as a solid
            elev = as_dict(element.get("elev")) or {}
            drawn_h = elev.get("height")
            if not height_asked and isinstance(drawn_h, (int, float)) and not isinstance(drawn_h, bool) and drawn_h > 0:
                raw["height"] = height = float(drawn_h)
        what = "hole"
    else:
        if nearest(point, axes, REACH_MM) is None:
            raise InvalidInput("No wall near the point picked: right-click a wall, or the door or window to replace", code="opening-no-wall")
        width, oversize = _sized(float(width_asked) if width_asked else default_width(data, kind), data, kind, type_id, wish)
        raw.update(point={"x": point[0], "z": point[1]}, width=width, **({"oversize": True} if oversize else {}))
        what = "added"
    normalize(dict(raw), "human", catalog, axes, country)          # refuses what cannot stand there (too wide, past the wall's end...)
    return {"op": "add-opening", "opening": raw}, what, {"type": type_id, "width": raw["width"], "height": height, "sill": sill}


def window_sill(catalog: Catalog) -> float:
    """How far above the floor a window sits when neither the sentence, the clicked window nor the drawing says: the catalog default
    (``defaults.openings.windowSill``, 900 mm), whatever its type."""
    return float(defaults_of(catalog).openings.get("windowSill", 900.0))


def drawn_sill(element: Mapping[str, Any] | None) -> float | None:
    """The sill a floorplan opening element records (``elev.base``, mm), when it records one above the floor; None otherwise."""
    elev = as_dict(element.get("elev")) if element is not None else None
    base = elev.get("base") if elev is not None else None
    return float(base) if isinstance(base, (int, float)) and not isinstance(base, bool) and base > 0 else None


def saved_type(opening: Opening, type_data: Mapping[str, Any], name: str) -> dict[str, Any]:
    """An ``opening-type`` catalog item made from an opening of a design: its type's frame, leaves and standard sizes, its own width,
    height and sill as the defaults, its dividers as the type's template, ``name`` as its label."""
    data = {k: v for k, v in type_data.items() if k not in ("label", "prompt", "sources")}
    data.update(label={"vi": name, "en": name}, defaultWidth=opening.width, defaultHeight=opening.height, defaultSill=opening.sill)
    if opening.axes is not None:
        ratios = [round_half_away((m + opening.width / 2) / opening.width, 4) for m in opening.axes]
        data["axesRatio"] = [r for r in ratios if 0 < r < 1]
    if opening.h_axes is not None:
        data["hAxesFromSill"] = [h for h in opening.h_axes if 0 < h < opening.height]
        data.pop("hAxesRatio", None)
    if isinstance(type_data.get("prompt"), str):
        data["prompt"] = type_data["prompt"]
    return data


def hole_type(element: Mapping[str, Any], catalog: Catalog) -> tuple[str, str]:
    """(kind, type id) of a floorplan opening element drawn without a type: its tag (door / window), else its label (lexicon
    ``opening.label-window``); the kind's sliding / folding type (``defaults.openingKinds.<kind>.sliding`` / ``folding``) when its label
    says so (lexicon ``opening.label-sliding`` / ``opening.label-folding``: "Cửa trượt", "sliding"), else the kind's default type."""
    from ..lexicon import fold, pattern
    from .types import kind_defaults
    tag = str(element.get("tag") or "")
    label = fold(str(element.get("label") or ""))
    kind = tag if tag in ("door", "window") else ("window" if pattern("opening.label-window", catalog).search(label) else "door")
    k = kind_defaults(catalog, kind)
    for how in ("sliding", "folding"):
        if k.get(how) and pattern(f"opening.label-{how}", catalog).search(label):
            return kind, str(k[how])
    return kind, default_type(catalog, kind)


def hole_opening(point: Pt | None, axes: Sequence[WallAxis], catalog: Catalog, selected: str | None = None,
                 elements: Sequence[Mapping[str, Any]] = (), country: str | None = None) -> tuple[Opening, str | None] | None:
    """The opening a floorplan opening element stands for (the one selected, else the one under ``point``): its hole's place and width,
    its drawn height (``elev``) or its type's default, its type from its tag and label. With the element's label (its name in the
    drawing). None when no element is there or no wall axis runs through it."""
    from ..recognition.openings import element_at, element_hole
    element = next((e for e in elements if selected and e.get("id") == selected and e.get("kind") == "opening"), None) \
        or (element_at(point, elements) if point else None)
    hole = element_hole(element, axes) if element is not None else None
    if element is None or hole is None:
        return None
    axis, center, width = hole
    kind, type_id = hole_type(element, catalog)
    data = get(catalog, type_id)
    elev = as_dict(element.get("elev")) or {}
    drawn = elev.get("height")
    height = float(drawn) if isinstance(drawn, (int, float)) else num(data, "defaultHeight", 2200.0)
    hole_width = float(round_half_away(width, 0))
    raw: dict[str, Any] = {"kind": kind, "openingType": type_id, "source": "drawn", "wallAxis": axis.ref().to_data(),
                           "center": round_half_away(center, 1), "width": hole_width, "height": height,
                           "sill": 0.0 if kind != "window" else drawn_sill(element) or window_sill(catalog)}
    low, high = width_range(data, kind)
    if not low <= hole_width <= high:
        raw["oversize"] = True                       # as drawn: the plan is the authority on its own holes
    try:
        opening, _ = normalize(raw, "human", catalog, axes, country)
    except InvalidInput:
        return None
    label = element.get("label")
    return opening, (str(label) if isinstance(label, str) and label.strip() else None)
