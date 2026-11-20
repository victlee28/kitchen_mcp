"""Opening types (catalog kind ``opening-type``): the axis template, the leaves and the frame of a door, window or passage."""
from __future__ import annotations

from ..numeric import round_half_away

from collections.abc import Mapping, Sequence
from typing import Any, cast

from ..catalog import Catalog
from ..errors import InvalidInput
from .contract import Hinge, Leaf

MIN_H_BAY = 100.0                     # a horizontal axis needs this much room above and below it


LEGACY_IDS = {"window-casement-2": "window-swing-2"}


def _current_form(data: Mapping[str, Any]) -> bool:
    return isinstance(data.get("leaves"), list)


def kind_defaults(catalog: Catalog, kind: str) -> Mapping[str, Any]:
    """What an opening of ``kind`` takes when its type leaves it out (catalog ``defaults.openingKinds``): ``type``, ``width``, ``maxWidth``,
    ``handle``, ``photoHeight``."""
    from ..defaults import of as defaults_of
    return defaults_of(catalog).opening_kinds.get(kind) or defaults_of(catalog).opening_kinds.get("door") or {}


def default_type(catalog: Catalog, kind: str) -> str:
    """The type an opening of ``kind`` gets when none is named (``defaults.openingKinds.<kind>.type``)."""
    return str(kind_defaults(catalog, kind).get("type") or "door-swing-1")


def _complete(catalog: Catalog, data: Mapping[str, Any]) -> dict[str, Any]:
    """The type's data with what it leaves out taken from the defaults of its kind: ``defaultWidth``, ``maxWidth``, ``handle``, and the
    handle's part sizes (``handleParts``)."""
    from ..defaults import of as defaults_of
    k = kind_defaults(catalog, str(data.get("kind") or "door"))
    out = dict(data)
    for key, src in (("defaultWidth", "width"), ("maxWidth", "maxWidth"), ("handle", "handle")):
        if key not in out and k.get(src) is not None:
            out[key] = k[src]
    out.setdefault("handleParts", dict(defaults_of(catalog).opening_handle_parts))
    return out


def get(catalog: Catalog, opening_type: str) -> Mapping[str, Any]:
    """The type's data, completed by the defaults of its kind (``_complete``). A design saved with the first opening types (12/11/2026:
    ``leaves`` a count, ``frameWidth``) in its catalog snapshot, or without the type at all, reads the built-in type of the same id instead."""
    table: dict[str, dict[str, Any]] = catalog.derived("opening-types.complete", lambda c: {})
    if opening_type in table:
        return dict(table[opening_type])          # a copy: a caller may add to it
    item = catalog.find("opening-type", opening_type)
    if item is not None and _current_form(item.data):
        table[opening_type] = _complete(catalog, item.data)
        return dict(table[opening_type])
    from .. import builtin
    fallback = builtin.CATALOG.find("opening-type", LEGACY_IDS.get(opening_type, opening_type))
    if fallback is not None and _current_form(fallback.data):
        table[opening_type] = _complete(catalog, fallback.data)
        return dict(table[opening_type])
    raise InvalidInput(f"Unknown opening type {opening_type!r}", code="opening-type-not-found", params={"id": opening_type})


def for_kind(catalog: Catalog, kind: str) -> list[dict[str, Any]]:
    return [{"id": item.id, **dict(item.data)} for item in catalog.all("opening-type") if item.data.get("kind") == kind]


def obj(value: Any) -> Mapping[str, Any] | None:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else None


def arr(value: Any) -> list[Any]:
    return list(cast(Sequence[Any], value)) if isinstance(value, (list, tuple)) else []


def num(data: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = data.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def casing_width(data: Mapping[str, Any]) -> float:
    casing = obj(data.get("casing"))
    return num(casing, "width") if casing is not None else 0.0


def template_axes(data: Mapping[str, Any], width: float) -> tuple[float, ...]:
    """Middle vertical axes of the template, relative to the centre."""
    ratios = arr(data.get("axesRatio"))
    return tuple(round_half_away(-width / 2 + float(r) * width, 3) + 0.0 for r in ratios if isinstance(r, (int, float)))


def template_h_axes(data: Mapping[str, Any], height: float) -> tuple[float, ...]:
    """Middle horizontal axes of the template, mm above the sill; an axis without 100 mm above and below it is left out."""
    fixed = [float(v) for v in arr(data.get("hAxesFromSill")) if isinstance(v, (int, float))]
    values = fixed if fixed else [float(r) * height for r in arr(data.get("hAxesRatio")) if isinstance(r, (int, float))]
    return tuple(round_half_away(v, 3) + 0.0 for v in values if MIN_H_BAY <= v <= height - MIN_H_BAY)


def _index(value: Any, count: int) -> int:
    i = int(value)
    return i + count if i < 0 else i


def template_leaves(data: Mapping[str, Any], n_v: int, n_h: int, inward: int) -> tuple[Leaf, ...]:
    """The type's leaves on a grid of ``n_v`` vertical and ``n_h`` horizontal axes (outer ones included). Negative indices count
    from the last axis. ``opens`` (in / out, seen from the kitchen) becomes a side with ``inward`` (+1: the + side is the kitchen's;
    unknown: in = +). Leaves above a horizontal axis the grid does not have are left out; the others stretch to the head."""
    out: list[Leaf] = []
    for item in arr(data.get("leaves")):
        raw = obj(item)
        if raw is None:
            continue
        cols = (_index(raw["cols"][0], n_v), _index(raw["cols"][1], n_v))
        rows = (_index(raw["rows"][0], n_h), _index(raw["rows"][1], n_h))
        if rows[0] >= n_h - 1 or cols[0] >= n_v - 1:
            continue
        rows = (rows[0], min(rows[1], n_h - 1))
        cols = (cols[0], min(cols[1], n_v - 1))
        hinge_raw = obj(raw.get("hinge"))
        hinge = None
        if hinge_raw is not None:
            axis = str(hinge_raw.get("axis"))
            hinge = Hinge(axis, _index(hinge_raw["index"], n_v if axis == "v" else n_h))
        opens: Any = raw.get("opens")
        side = None
        if opens in ("in", "out"):
            into = inward if inward else 1
            side = "+" if (into > 0) == (opens == "in") else "-"
        out.append(Leaf(cols, rows, str(raw["operation"]), hinge, side, bool(raw.get("active", False))))
    return tuple(out)


def grid(data: Mapping[str, Any], width: float, height: float, axes: Sequence[float] | None,
         h_axes: Sequence[float] | None) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """All vertical axes relative to the centre and all horizontal axes above the sill, outer ones included."""
    mid = tuple(axes) if axes is not None else template_axes(data, width)
    hmid = tuple(h_axes) if h_axes is not None else template_h_axes(data, height)
    return (-width / 2, *mid, width / 2), (0.0, *hmid, height)


def default_height(kind: str, catalog: Catalog | None = None) -> float:
    """Height of an opening the drawing leaves without one: the default height of the kind's default type (data:
    ``opening-type.defaultHeight``; the built-in catalog unless another is given)."""
    from .. import builtin
    data = get(catalog or builtin.CATALOG, default_type(catalog or builtin.CATALOG, kind))
    return num(data, "defaultHeight", 2200.0 if kind != "window" else 1200.0)
