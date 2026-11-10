"""A TV wall unit (hệ tủ tivi) laid along one line (pure, rule R1): the run is marked ``purpose = "tv"`` so no worktop, wall tile or kitchen
rule applies to it. Default layout (chosen by the user 10/11/2026): a low console with drawers the whole width between two tall storage
columns at the ends, the open TV niche above the console with a flat TV on the wall, and one floating open shelf above the TV. A line shorter
than ``COLUMNS_FROM`` has no columns. Modules are given as ``run_line.plan_on_line`` takes them (``s`` along the run from its start); the
caller makes base and tall cabinets as deep as the object they replace (``cabinet_run.fit_depth``).
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from .numeric import round_int
from .spec import KitchenSpec, from_data, to_data

PURPOSE = "tv"
CONSOLE_HEIGHT = 450.0     # low media console, plinth included (mm)
CONSOLE_MAX = 1200.0       # widest console cabinet; a longer stretch is split evenly
COLUMNS_FROM = 2400.0      # a line at least this long gets a tall column at each end
COLUMN_MIN, COLUMN_MAX = 400.0, 600.0
SHELF_Y, SHELF_HEIGHT, SHELF_DEPTH = 1850.0, 250.0, 300.0
TV_CENTER = 1100.0         # height of the middle of the screen (seated eye level)
TV_DEPTH = 30.0
TVS = ((1700.0, "65", 1450.0, 830.0), (1400.0, "55", 1230.0, 710.0), (0.0, "43", 960.0, 560.0))   # (niche from, inches, w, h)

_WORD = re.compile(r"\b(?:ti\s*vi|tv|tivi)\b")


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def asks_tv(text: str | None) -> bool:
    """Does the sentence ask for a TV unit ("tạo hệ tủ tivi", "kệ tivi", "tủ TV")?"""
    return bool(text) and bool(_WORD.search(_plain(str(text))))


def tv_for(niche: float) -> dict[str, Any]:
    """The TV that suits a niche ``niche`` mm wide: the biggest of 65" / 55" / 43" that leaves some wall on each side."""
    _, inch, w, h = next(t for t in TVS if niche >= t[0])
    return {"type": "tv", "name": f"Tivi {inch} inch treo tường", "dimensions": f"{w:g}x{h:g}x{TV_DEPTH:g}", "model": f"tv-{inch}"}


def _split(length: float) -> list[float]:
    n = max(1, math.ceil(length / CONSOLE_MAX - 1e-9))
    w = float(round_int(length / n / 10) * 10)
    return [w] * (n - 1) + [length - w * (n - 1)]


def layout(length: float, common: dict[str, Any]) -> list[dict[str, Any]]:
    """The cabinets of a TV unit ``length`` mm long. ``common``: the design's ``common`` (its ``cabinetTop`` sets the columns' height)."""
    length = float(int(length // 10) * 10)
    col = 0.0
    if length >= COLUMNS_FROM:
        col = min(COLUMN_MAX, max(COLUMN_MIN, float(round_int(length * 0.15 / 50) * 50)))
    niche = length - 2 * col
    top = float(common.get("cabinetTop") or 2400.0)
    out: list[dict[str, Any]] = []
    for s in ((0.0, length - col) if col else ()):
        out.append({"type": "tall", "s": s, "width": col, "y": 0.0, "height": top, "depth": 400.0, "name": "Cột tủ tivi"})
    at = col
    widths = _split(niche)
    for i, w in enumerate(widths):
        cabinet: dict[str, Any] = {"type": "base", "s": at, "width": w, "y": 0.0, "height": CONSOLE_HEIGHT, "depth": 400.0, "name": "Kệ tivi",
                                   "frontSections": [{"type": "drawer", "height": CONSOLE_HEIGHT}]}
        if i == 0:
            tv = tv_for(niche)
            tv["center"] = col + niche / 2          # along the run, the middle of the niche (it may straddle two console cabinets)
            cabinet["appliance"] = tv
        out.append(cabinet)
        at += w
    if niche >= 600:
        out.append({"type": "upper-open", "s": col, "width": niche, "y": SHELF_Y, "height": SHELF_HEIGHT, "depth": SHELF_DEPTH,
                    "name": "Kệ treo trên tivi", "shelfCount": 1})
    return out


def console(length: float) -> list[dict[str, Any]]:
    """Only the low console (a second edge of the same object: the TV and the columns stand on the first)."""
    length = float(int(length // 10) * 10)
    out, at = [], 0.0
    for w in _split(length):
        out.append({"type": "base", "s": at, "width": w, "y": 0.0, "height": CONSOLE_HEIGHT, "depth": 400.0, "name": "Kệ tivi",
                    "frontSections": [{"type": "drawer", "height": CONSOLE_HEIGHT}]})
        at += w
    return out


def is_tv_run(run: Any) -> bool:
    return getattr(run, "purpose", None) == PURPOSE


def tv_runs(spec: Any) -> set[str]:
    """Ids of the runs that are TV units."""
    return {r.id for r in spec.runs if is_tv_run(r)}


def tv_modules(spec: Any) -> set[str]:
    """Ids of the cabinets standing in a TV unit."""
    ids = tv_runs(spec)
    return {m.id for m in spec.module if m.run in ids}


def kitchen_only(spec: KitchenSpec) -> KitchenSpec:
    """The design without its TV units (and what stands in them): what kitchen rules look at."""
    gone = tv_modules(spec)
    if not gone:
        return spec
    ids = tv_runs(spec)
    d = to_data(spec)
    d["module"] = [m for m in d["module"] if m["id"] not in gone]
    d["appliances"] = [a for a in d.get("appliances", []) if a.get("module") not in gone]
    d["runs"] = [r for r in d.get("runs", []) if r["id"] not in ids]
    return from_data(KitchenSpec, d)
