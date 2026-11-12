"""The workshop's default sizes and limits: the catalog kind ``defaults`` (one item, ``default``; the workshop edits it, nobody adds another).

What it decides is used when something is made or changed (a new design, a run split into cabinets, a dragged run end, an appliance put in
a cabinet), never when an existing design is drawn: editing it changes no stored design. A field the item lacks keeps the builtin value.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import builtin
from .catalog import Catalog
from .jsonview import as_dict

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


def _number(v: Any) -> float | None:
    """A JSON number as it is written (700 stays an int, so a design made with it stores 700, not 700.0)."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _section(data: Mapping[str, Any], fallback: Mapping[str, Any], key: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for source in (as_dict(fallback.get(key)) or {}, as_dict(data.get(key)) or {}):
        out.update({k: n for k, v in source.items() if (n := _number(v)) is not None})
    return out


def _build(catalog: Catalog) -> Defaults:
    fallback = builtin.CATALOG.data("defaults", ID)
    item = catalog.find("defaults", ID)
    data = item.data if item is not None else fallback
    run, stretch, hole = (_section(data, fallback, k) for k in ("run", "stretch", "applianceHole"))
    return Defaults(run["moduleWidth"], run["minWidth"], run["maxRun"], run["cornerMaxWidth"], stretch["min"], stretch["max"],
                    hole["side"], hole["worktopEdge"], hole["hoodSide"], _section(data, fallback, "newDesign"), _section(data, fallback, "menu"))


def of(catalog: Catalog = builtin.CATALOG) -> Defaults:
    """The defaults of ``catalog`` (computed once per catalog)."""
    return catalog.derived("defaults", _build)


BUILTIN = of()
