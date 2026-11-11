"""A TV wall unit (hệ tủ tivi) laid along one line (pure, rule R1): the run is marked ``purpose = "tv"`` so no worktop, wall tile or kitchen
rule applies to it. Default layout (chosen by the user 10/11/2026): a low console with drawers the whole width between two tall storage
columns at the ends, the open TV niche above the console with a flat TV on the wall, and one floating open shelf above the TV. A line shorter
than ``COLUMNS_FROM_MM`` has no columns. Modules are given as ``run_line.plan_on_line`` takes them (``s`` along the run from its start); the
caller makes base and tall cabinets as deep as the object they replace (``cabinet_run.fit_depth``).
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from .labels import DEFAULT_FRONT, NAMES, tv_name
from .numeric import round_int
from .spec import KitchenSpec, LaidModule, Run, from_data, to_data

PURPOSE = "tv"
CONSOLE_HEIGHT_MM = 450.0     # low media console, plinth included (mm)
CONSOLE_MAX_MM = 1200.0       # widest console cabinet; a longer stretch is split evenly
COLUMNS_FROM_MM = 2400.0      # a line at least this long gets a tall column at each end
COLUMN_MIN_MM, COLUMN_MAX_MM = 400.0, 600.0
SHELF_Y_MM, SHELF_HEIGHT_MM, SHELF_DEPTH_MM = 1850.0, 250.0, 300.0
TV_CENTER_MM = 1100.0         # height of the middle of the screen (seated eye level)
FULL_UPPER_Y_MM = 1750.0      # "full" layout: bottom of the wall cabinets over the niche; also the top of the panel behind the TV
SIDE_SHELF_Y_MM, SIDE_GAP_MM = 1300.0, 300.0      # "shelves" layout: open shelves beside the TV, this far from it
PANEL_THICKNESS_MM = 18.0
STYLES = ("columns", "shelves", "full")
TV_DEPTH_MM = 30.0
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
    return {"type": "tv", "name": tv_name(inch), "dimensions": f"{w:g}x{h:g}x{TV_DEPTH_MM:g}", "model": f"tv-{inch}"}


def _split(length: float, most: float = CONSOLE_MAX_MM) -> list[float]:
    n = max(1, math.ceil(length / most - 1e-9))
    w = float(round_int(length / n / 10) * 10)
    return [w] * (n - 1) + [length - w * (n - 1)]


def style_of(text: str | None) -> str:
    """Which layout a sentence asks for: ``full`` ("kín cả vách", "tủ kín"), ``shelves`` ("kệ treo", "không có cột") or ``columns``
    (the default: low console + niche + two columns)."""
    t = _plain(str(text or ""))
    if re.search(r"\bkin\s+(?:ca\s+|het\s+)?(?:vach|tuong)\b|\btu\s+kin\b|\bkin\s+tu\s+san\b", t):
        return "full"
    if re.search(r"\bke\s+(?:treo|ho)\b|\bkhong\s+(?:co\s+|can\s+|lam\s+)?cot\b|\bbo\s+cot\b", t):
        return "shelves"
    return "columns"


def explicit_style(text: str | None) -> str | None:
    """The layout the sentence names, None when it names none ("thay cả hệ tivi" keeps the layout the unit has)."""
    style = style_of(text)
    if style != "columns":
        return style
    return "columns" if re.search(r"\b(?:2|hai)\s+cot\b|\bcot\s+tu\b|\bhoc\s+tivi\b", _plain(str(text or ""))) else None


def wants_panel(text: str | None) -> bool:
    """A panel behind the TV unless the sentence refuses it ("không ốp", "bỏ tấm ốp")."""
    return not re.search(r"\b(?:khong|bo|bot)\s+(?:can\s+|co\s+)?(?:tam\s+)?op\b", _plain(str(text or "")))


def run_fields(style: str) -> dict[str, Any]:
    """What a TV unit's run carries besides its place."""
    return {"purpose": PURPOSE, "tvLayout": style if style in STYLES else "columns"}


def front_of(common: dict[str, Any]) -> str:
    """The front finish a TV unit's closed cabinets share: the design's tall (else base) front."""
    mats: dict[str, Any] = common.get("material") or {}
    return str(mats.get("tall") or mats.get("base") or DEFAULT_FRONT)


def _console(at: float, length: float) -> list[LaidModule]:
    out: list[LaidModule] = []
    for w in _split(length):
        out.append({"type": "base", "s": at, "width": w, "y": 0.0, "height": CONSOLE_HEIGHT_MM, "depth": 400.0, "name": NAMES["tv-console"],
                    "frontSections": [{"type": "drawer", "height": CONSOLE_HEIGHT_MM}]})
        at += w
    return out


def _put_tv(console: list[LaidModule], center: float, width: float, panel: tuple[float, float, float] | None) -> None:
    """The TV (sized for ``width``) on the console cabinet under ``center``; the panel behind it (``(width, y0, y1)``) on the same cabinet."""
    host = next((c for c in console if c["s"] <= center < c["s"] + c["width"]), console[0])
    tv = tv_for(width)
    tv["center"] = center - host["s"]       # from the start of its cabinet: the TV moves with it (it may straddle two console cabinets)
    host["appliance"] = tv
    if panel is not None:
        pw, y0, y1 = panel
        host["backPanel"] = {"s0": center - pw / 2 - host["s"], "s1": center + pw / 2 - host["s"], "y0": y0, "y1": y1}


def layout(length: float, common: dict[str, Any], style: str = "columns", panel: bool = True) -> list[LaidModule]:
    """The cabinets of a TV unit ``length`` mm long. ``common``: the design's ``common`` (``cabinetTop`` sets the tall cabinets' height).
    ``style``: ``columns`` (low console + niche + a tall column at each end from ``COLUMNS_FROM_MM``, a floating shelf over the TV),
    ``shelves`` (low console the whole length, open shelves on the wall beside the TV, no columns) or ``full`` (closed from floor to top
    but for the TV niche: tall cabinets each side, wall cabinets over the niche). ``panel``: a panel on the wall behind the TV."""
    length = float(int(length // 10) * 10)
    top = float(common.get("cabinetTop") or 2400.0)
    front = front_of(common)
    out: list[LaidModule] = []
    if style == "full":
        niche = length if length < 2000 else min(length - 800.0, max(1200.0, float(round_int(length * 0.45 / 10) * 10)))
        side = float(int((length - niche) / 2 // 10) * 10)     # whole 10 mm, like every cabinet width
        niche = length - 2 * side
        at = 0.0
        for w in (_split(side, COLUMN_MAX_MM) if side > 0 else []):
            out.append({"type": "tall", "s": at, "width": w, "y": 0.0, "height": top, "depth": 400.0, "name": NAMES["tv-side-tall"]})
            at += w
        console = _console(side, niche)
        out += console
        at = side + niche
        for w in (_split(side, COLUMN_MAX_MM) if side > 0 else []):
            out.append({"type": "tall", "s": at, "width": w, "y": 0.0, "height": top, "depth": 400.0, "name": NAMES["tv-side-tall"]})
            at += w
        if top - FULL_UPPER_Y_MM >= 250:
            at = side
            for w in _split(niche, 900.0):
                out.append({"type": "upper", "s": at, "width": w, "y": FULL_UPPER_Y_MM, "height": top - FULL_UPPER_Y_MM, "depth": SHELF_DEPTH_MM,
                            "name": NAMES["tv-upper"], "material": front})        # one finish for the whole wall, not the white of kitchen uppers
                at += w
        _put_tv(console, side + niche / 2, niche, (niche, CONSOLE_HEIGHT_MM, FULL_UPPER_Y_MM) if panel else None)
        return out
    if style == "shelves":
        console = _console(0.0, length)
        out += console
        center = length / 2
        tv_w = float(tv_for(length - 900.0)["dimensions"].split("x")[0])
        _put_tv(console, center, length - 900.0, (tv_w + 400.0, CONSOLE_HEIGHT_MM, FULL_UPPER_Y_MM) if panel else None)
        side = (length - tv_w) / 2 - SIDE_GAP_MM
        if side >= 450:
            w = float(min(900.0, int(side // 10) * 10))
            for s in (center - tv_w / 2 - SIDE_GAP_MM - w, center + tv_w / 2 + SIDE_GAP_MM):
                out.append({"type": "upper-open", "s": s, "width": w, "y": SIDE_SHELF_Y_MM, "height": SHELF_HEIGHT_MM, "depth": 250.0,
                            "name": NAMES["tv-shelf-side"], "shelfCount": 1})
        elif length >= 600:
            out.append({"type": "upper-open", "s": 0.0, "width": length, "y": SHELF_Y_MM, "height": SHELF_HEIGHT_MM, "depth": SHELF_DEPTH_MM,
                        "name": NAMES["tv-shelf-over"], "shelfCount": 1})
        return out
    col = 0.0
    if length >= COLUMNS_FROM_MM:
        col = min(COLUMN_MAX_MM, max(COLUMN_MIN_MM, float(round_int(length * 0.15 / 50) * 50)))
    niche = length - 2 * col
    for s0 in ((0.0, length - col) if col else ()):
        out.append({"type": "tall", "s": s0, "width": col, "y": 0.0, "height": top, "depth": 400.0, "name": NAMES["tv-column"]})
    console = _console(col, niche)
    out += console
    _put_tv(console, col + niche / 2, niche, (niche, CONSOLE_HEIGHT_MM, SHELF_Y_MM) if panel else None)
    if niche >= 600:
        out.append({"type": "upper-open", "s": col, "width": niche, "y": SHELF_Y_MM, "height": SHELF_HEIGHT_MM, "depth": SHELF_DEPTH_MM,
                    "name": NAMES["tv-shelf-over"], "shelfCount": 1})
    return out


def console(length: float) -> list[LaidModule]:
    """Only the low console (a second edge of the same object: the TV and the columns stand on the first)."""
    return _console(0.0, float(int(length // 10) * 10))


def layout_of(spec: Any, run_id: str) -> str | None:
    """The layout a TV run was made with (None: not a TV run)."""
    r = next((r for r in spec.runs if r.id == run_id), None)
    return (r.tvLayout or "columns") if r is not None and is_tv_run(r) else None


def is_tv_run(run: Run) -> bool:
    return run.purpose == PURPOSE


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
