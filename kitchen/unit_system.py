"""Furniture units other than kitchens and TV walls (pure, rule R1), laid along one line by a ``unit-layout`` of the catalog: a wine cabinet
(tủ rượu), low cabinets only (tủ thấp)... A layout is data (catalog kind ``unit-layout``): its ``words`` (what a sentence says to ask for it,
unaccented, per language), its ``vars`` and ``steps`` in the TV layouts' language (``tv_system.lay_out``: ``cabinets``, ``let``). The run is
marked ``purpose = "unit"`` with its ``unitLayout``: no worktop, wall tile or kitchen rule applies to it (``tv_system.NOT_KITCHEN``).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import builtin, tv_system
from .catalog import Catalog
from .errors import InvalidInput
from .jsonview import as_dict, as_list
from .spec import KitchenSpec, LaidModule, Run

PURPOSE = "unit"


@dataclass(frozen=True)
class UnitLayout:
    id: str
    words: tuple[re.Pattern[str], ...]
    layout: tv_system.TvLayout


def _plain(text: str) -> str:
    return " ".join(tv_system._plain(text).split())     # pyright: ignore[reportPrivateUsage]


def _compile(lid: str, d: Mapping[str, Any]) -> UnitLayout:
    said = as_dict(d.get("words")) or {}
    pats = tuple(re.compile(r"\b" + re.escape(_plain(str(w))) + r"\b") for lang in said.values() for w in (as_list(lang) or []) if str(w).strip())
    return UnitLayout(lid, pats, tv_system._compile_layout(lid, d))     # pyright: ignore[reportPrivateUsage]


def _units(catalog: Catalog) -> dict[str, UnitLayout]:
    return {it.id: _compile(it.id, it.data) for it in catalog.all("unit-layout")}


def units(catalog: Catalog = builtin.CATALOG) -> dict[str, UnitLayout]:
    """The unit layouts of ``catalog`` (catalog kind ``unit-layout``), compiled once per catalog."""
    return catalog.derived("unit-layouts", _units)


def asks(text: str | None, catalog: Catalog = builtin.CATALOG) -> str | None:
    """The unit layout a sentence asks for ("tạo hệ tủ rượu" -> ``wine``, "thay bằng hệ tủ thấp" -> ``low``), None for none. The longest
    word found wins, so "tủ rượu thấp" is a wine cabinet."""
    if not text:
        return None
    plain = _plain(str(text))
    best: tuple[int, str] | None = None
    for u in units(catalog).values():
        for p in u.words:
            m = p.search(plain)
            if m and (best is None or len(m.group(0)) > best[0]):
                best = (len(m.group(0)), u.id)
    return best[1] if best else None


def layout(unit: str, length: float, common: dict[str, Any], catalog: Catalog = builtin.CATALOG) -> list[LaidModule]:
    """The cabinets of the unit ``unit`` ``length`` mm long (``common``: the design's ``common``; ``top`` = its ``cabinetTop``)."""
    u = units(catalog).get(unit)
    if u is None:
        raise InvalidInput(f"Unknown unit layout {unit!r}", code="unknown-unit-layout", params={"unit": unit})
    return tv_system.lay_out(u.layout, length, common, False, catalog)


def run_fields(unit: str) -> dict[str, Any]:
    """What the run of a unit carries besides its place."""
    return {"purpose": PURPOSE, "unitLayout": unit}


def is_unit_run(run: Run) -> bool:
    return run.purpose == PURPOSE


def unit_of(spec: KitchenSpec, run_id: str) -> str | None:
    """The unit layout a run was made with (None: not a unit run)."""
    r = next((r for r in spec.runs if r.id == run_id), None)
    return r.unitLayout if r is not None and is_unit_run(r) else None
