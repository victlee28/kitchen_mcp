"""The workshop's default sizes and limits: the catalog kind ``defaults`` (one item, ``default``; the workshop edits it, nobody adds another).

What it decides is used when something is made or changed (a new design, a run split into cabinets, a dragged run end, an appliance put in
a cabinet), never when an existing design is drawn: editing it changes no stored design. A field the item lacks keeps the builtin value.
The finish names a design leaves out (``materials``) are drawn from the builtin item (``BUILTIN``), so editing them changes no drawing either.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import builtin
from .catalog import Catalog
from .jsonview import as_dict, as_list

ID = "default"


@dataclass(frozen=True)
class Defaults:
    module_width: float          # preferred cabinet width when a run is split
    min_width: float             # narrowest cabinet made
    max_run: float               # longest run made in one go
    corner_max_width: float      # widest diagonal corner cabinet
    stretch_min: float           # a dragged run end leaves every cabinet this wide at least...
    stretch_max: float           # ...and at most
    side: float                  # cabinet side panel: a hole or niche must fit between two
    worktop_edge: float          # worktop left in front of and behind a cut-out
    hood_side: float             # room each side of an integrated hood inside its cabinet
    new_design: Mapping[str, float]   # common sizes of a new design the request does not give
    menu: Mapping[str, float]         # input limits of the web menu
    openings: Mapping[str, float]     # the checks against doors and windows (``openings.checks``): clearAllowance, doorZone, windowZone, near
    materials: Mapping[str, str]      # finish names drawn where a design names none (``base``, ``carcass``, ``sink`` ...)
    hinge: str = "clip-110-soft"      # the catalog hinge of a door whose design names none
    hinge_edge: float = 100.0         # top and bottom hinge from the door's edge (mm)
    hinge_counts: tuple[tuple[float, int], ...] = ((900.0, 2), (1600.0, 3), (2000.0, 4), (2600.0, 5))   # (door up to mm, hinges)
    auto_place: Mapping[str, Any] = field(default_factory=lambda: {})   # the words and sizes of "Auto place" (``auto_place``)
    opening_kinds: Mapping[str, Mapping[str, Any]] = field(default_factory=lambda: {})   # door / window / passage: default type, width,
    #   widest, handle, plausible height from a picture (``openingKinds``): what an opening type that leaves them out takes
    opening_handle_parts: Mapping[str, Mapping[str, float]] = field(default_factory=lambda: {})   # lever / pull sizes (mm)
    molding_styles: tuple[str, ...] = ()        # styles that get crown and base moldings when the design does not say (``moldingStyles``)
    furniture_heights: Mapping[str, Any] = field(default_factory=lambda: {})   # floor-plan furniture with no height: ``default`` and ``words`` (label word -> mm)


def _number(v: Any) -> float | None:
    """A JSON number as it is written (700 stays an int, so a design made with it stores 700, not 700.0)."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _section(data: Mapping[str, Any], fallback: Mapping[str, Any], key: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for source in (as_dict(fallback.get(key)) or {}, as_dict(data.get(key)) or {}):
        out.update({k: n for k, v in source.items() if (n := _number(v)) is not None})
    return out


def _names(data: Mapping[str, Any], fallback: Mapping[str, Any], key: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for source in (as_dict(fallback.get(key)) or {}, as_dict(data.get(key)) or {}):
        out.update({k: v for k, v in source.items() if isinstance(v, str) and v})
    return out


def _hinge(data: Mapping[str, Any], fallback: Mapping[str, Any]) -> tuple[str, float, tuple[tuple[float, int], ...]]:
    h = {**(as_dict(fallback.get("hinge")) or {}), **(as_dict(data.get("hinge")) or {})}
    rows = [as_dict(r) or {} for r in as_list(h.get("counts")) or []]
    counts = tuple(sorted((float(u), int(c)) for r in rows if (u := _number(r.get("upTo"))) is not None and (c := _number(r.get("count"))) is not None))
    edge = _number(h.get("edge"))
    return str(h.get("item") or "clip-110-soft"), float(edge if edge is not None else 100), counts or ((900.0, 2), (1600.0, 3), (2000.0, 4), (2600.0, 5))


def _merged(data: Mapping[str, Any], fallback: Mapping[str, Any], key: str) -> dict[str, dict[str, Any]]:
    """A section of named groups (``openingKinds``: door / window / passage): each group's fields from the builtin item, then the item's own."""
    base, own = as_dict(fallback.get(key)) or {}, as_dict(data.get(key)) or {}
    return {str(k): {**(as_dict(base.get(k)) or {}), **(as_dict(own.get(k)) or {})} for k in dict.fromkeys([*base, *own])}


def _build(catalog: Catalog) -> Defaults:
    fallback = builtin.CATALOG.data("defaults", ID)
    item = catalog.find("defaults", ID)
    data = item.data if item is not None else fallback
    run, stretch, hole = (_section(data, fallback, k) for k in ("run", "stretch", "applianceHole"))
    return Defaults(float(run["moduleWidth"]), float(run["minWidth"]), float(run["maxRun"]), float(run["cornerMaxWidth"]),
                    float(stretch["min"]), float(stretch["max"]), float(hole["side"]), float(hole["worktopEdge"]), float(hole["hoodSide"]), _section(data, fallback, "newDesign"), _section(data, fallback, "menu"),
                    _section(data, fallback, "openings"), _names(data, fallback, "materials"), *_hinge(data, fallback),
                    {**(as_dict(fallback.get("autoPlace")) or {}), **(as_dict(data.get("autoPlace")) or {})},
                    _merged(data, fallback, "openingKinds"), _merged(data, fallback, "openingHandleParts"),
                    tuple(str(s) for s in as_list(data.get("moldingStyles") if "moldingStyles" in data else fallback.get("moldingStyles")) or []),
                    {**(as_dict(fallback.get("furnitureHeights")) or {}), **(as_dict(data.get("furnitureHeights")) or {})})


def of(catalog: Catalog = builtin.CATALOG) -> Defaults:
    """The defaults of ``catalog`` (computed once per catalog)."""
    return catalog.derived("defaults", _build)


BUILTIN = of()
