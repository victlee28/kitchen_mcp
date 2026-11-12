"""A TV wall unit (hệ tủ tivi) laid along one line (pure, rule R1): the run is marked ``purpose = "tv"`` so no worktop, wall tile or kitchen
rule applies to it. Default layout (chosen by the user 10/11/2026): a low console with drawers the whole width between two tall storage
columns at the ends, the open TV niche above the console with a flat TV on the wall, and one floating open shelf above the TV. A line shorter
than 2400 mm (the ``columns`` layout's ``columnsFrom``) has no columns. Modules are given as ``run_line.plan_on_line`` takes them (``s`` along the run from its start); the
caller makes base and tall cabinets as deep as the object they replace (``cabinet_run.fit_depth``).
"""
from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from . import appliance_models, builtin
from .catalog import Catalog
from .catalog import expr
from .jsonview import as_dict, as_list
from .errors import InvalidInput
from .labels import DEFAULT_FRONT, NAMES
from .numeric import round_int
from .spec import KitchenSpec, LaidModule, Run, from_data, to_data
from . import lexicon

PURPOSE = "tv"
CONSOLE_HEIGHT_MM = 450.0     # low media console, plinth included (mm)
CONSOLE_MAX_MM = 1200.0       # widest console cabinet; a longer stretch is split evenly
TV_CENTER_MM = 1100.0         # height of the middle of the screen (seated eye level)
# the sizes of each layout (columns from 2400 mm, shelf heights, the "full" wall cabinets...) are the layout's data (catalog kind tv-layout)
PANEL_THICKNESS_MM = 18.0
STYLES = ("columns", "shelves", "full")
TV_DEPTH_MM = 30.0



def _plain(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def asks_tv(text: str | None) -> bool:
    """Does the sentence ask for a TV unit ("tạo hệ tủ tivi", "kệ tivi", "tủ TV")?"""
    return bool(text) and bool(lexicon.pattern("tv.word").search(_plain(str(text))))


def tv_for(niche: float, catalog: Catalog = builtin.CATALOG) -> dict[str, Any]:
    """The TV that suits a niche ``niche`` mm wide: the biggest TV model of the catalog whose ``fits.nicheFrom`` the niche reaches (65" from
    1700 mm, 55" from 1400 mm, else 43" with the builtin models)."""
    def niche_from(m: dict[str, Any]) -> float:
        fits: dict[str, Any] = m.get("fits") or {}
        return float(fits.get("nicheFrom", 0))
    tvs = sorted((m for m in appliance_models.models(catalog).values() if m["type"] == "tv"), key=lambda m: -niche_from(m))
    m = next((t for t in tvs if niche >= niche_from(t)), tvs[-1] if tvs else None)
    if m is None:
        raise InvalidInput("The catalog has no TV model", code="no-tv-model")
    s = m["size"]
    return {"type": "tv", "name": m["name"], "dimensions": f"{s['w']:g}x{s['h']:g}x{s['d']:g}", "model": m["id"]}


def _split(length: float, most: float = CONSOLE_MAX_MM) -> list[float]:
    n = max(1, math.ceil(length / most - 1e-9))
    w = float(round_int(length / n / 10) * 10)
    return [w] * (n - 1) + [length - w * (n - 1)]


def style_of(text: str | None) -> str:
    """Which layout a sentence asks for: ``full`` ("kín cả vách", "tủ kín", "full tường"), ``shelves`` ("kệ treo", "không có cột") or ``columns``
    (the default: low console + niche + two columns)."""
    t = _plain(str(text or ""))
    if lexicon.pattern("tv.full").search(t):
        return "full"
    if lexicon.pattern("tv.shelves").search(t):
        return "shelves"
    return "columns"


def explicit_style(text: str | None) -> str | None:
    """The layout the sentence names, None when it names none ("thay cả hệ tivi" keeps the layout the unit has)."""
    style = style_of(text)
    if style != "columns":
        return style
    return "columns" if lexicon.pattern("tv.columns").search(_plain(str(text or ""))) else None


def wants_panel(text: str | None) -> bool:
    """A panel behind the TV unless the sentence refuses it ("không ốp", "bỏ tấm ốp", "không vách ốp")."""
    return not lexicon.pattern("tv.no-panel").search(_plain(str(text or "")))


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


def _put_tv(console: list[LaidModule], center: float, width: float, panel: tuple[float, float, float] | None,
            catalog: Catalog = builtin.CATALOG) -> None:
    """The TV (sized for ``width``) on the console cabinet under ``center``; the panel behind it (``(width, y0, y1)``) on the same cabinet."""
    host = next((c for c in console if c["s"] <= center < c["s"] + c["width"]), console[0])
    tv = tv_for(width, catalog)
    tv["center"] = center - host["s"]       # from the start of its cabinet: the TV moves with it (it may straddle two console cabinets)
    host["appliance"] = tv
    if panel is not None:
        pw, y0, y1 = panel
        host["backPanel"] = {"s0": center - pw / 2 - host["s"], "s1": center + pw / 2 - host["s"], "y0": y0, "y1": y1}


@dataclass(frozen=True)
class _Step:
    do: str
    when: expr.Formula | None
    data: Mapping[str, Any]
    formulas: Mapping[str, expr.Formula]
    lets: tuple[tuple[str, expr.Formula], ...] = ()


@dataclass(frozen=True)
class TvLayout:
    id: str
    vars: tuple[tuple[str, expr.Formula], ...]
    steps: tuple[_Step, ...]


TV_INPUTS = {"length": expr.NUM, "top": expr.NUM, "panel": expr.BOOL}


def _compile_layout(lid: str, d: Mapping[str, Any]) -> TvLayout:
    def f(where: str, text: Any, want: str = expr.NUM) -> expr.Formula:
        try:
            return expr.compile(str(text), names, want)
        except InvalidInput as e:
            raise InvalidInput(f"TV layout {lid}, {where}: {e.message}", code="layout-template-formula",
                               params={"template": lid, "where": where, "at": e.params.get("at", 0), "detail": e.code}) from None
    names: dict[str, str] = dict(TV_INPUTS)
    vars_: list[tuple[str, expr.Formula]] = []
    for k, v in (as_dict(d.get("vars")) or {}).items():
        vars_.append((k, f(f"vars.{k}", v)))
        names[k] = expr.NUM
    steps: list[_Step] = []
    for i, raw in enumerate(as_list(d.get("steps")) or []):
        st = as_dict(raw) or {}
        at = f"steps[{i}]"
        when = f(f"{at}.when", st["when"], expr.BOOL) if "when" in st else None
        do = str(st.get("do") or "")
        if do == "let":
            lets: list[tuple[str, expr.Formula]] = []
            for k, v in (as_dict(st.get("vars")) or {}).items():
                lets.append((k, f(f"{at}.vars.{k}", v)))
                names[k] = expr.NUM
            steps.append(_Step(do, when, st, {}, tuple(lets)))
            continue
        if do == "tv":
            formulas = {k: f(f"{at}.{k}", st[k]) for k in ("center", "fit")}
            names["tvWidth"] = expr.NUM                 # the TV's width, after this step
            panel = as_dict(st.get("panel")) or {}
            formulas.update({f"panel.{k}": f(f"{at}.panel.{k}", panel[k]) for k in ("width", "y0", "y1") if k in panel})
            steps.append(_Step(do, when, st, formulas))
            continue
        if do != "cabinets":
            raise InvalidInput(f"TV layout {lid}, {at}: unknown step {do!r}", code="layout-template-step", params={"template": lid, "where": at})
        formulas = {k: f(f"{at}.{k}", st[k]) for k in ("start", "length", "split", "y", "height", "depth") if k in st}
        steps.append(_Step(do, when, st, formulas))
    return TvLayout(lid, tuple(vars_), tuple(steps))


def _layouts(catalog: Catalog) -> dict[str, TvLayout]:
    return {it.id: _compile_layout(it.id, it.data) for it in catalog.all("tv-layout")}


def layouts(catalog: Catalog = builtin.CATALOG) -> dict[str, TvLayout]:
    """The TV unit layouts of ``catalog`` (catalog kind ``tv-layout``), compiled once per catalog."""
    return catalog.derived("tv-layouts", _layouts)


def layout(length: float, common: dict[str, Any], style: str = "columns", panel: bool = True, catalog: Catalog = builtin.CATALOG) -> list[LaidModule]:
    """The cabinets of a TV unit ``length`` mm long, by the layout ``style`` of the catalog (kind ``tv-layout``): ``columns`` (low console +
    niche + a tall column at each end from 2400 mm, a floating shelf over the TV), ``shelves`` (low console the whole length, open shelves
    on the wall beside the TV, no columns) or ``full`` (closed from floor to top but for the TV niche). ``common``: the design's ``common``
    (``cabinetTop`` sets the tall cabinets' height, the tall / base front the wall cabinets' finish). ``panel``: a panel behind the TV.

    A layout's steps: ``cabinets`` (``start`` + ``length``, split evenly into pieces at most ``split`` wide; ``group`` names them for the TV
    step), ``tv`` (the TV that suits ``fit``, on the cabinet of ``on`` under ``center``; then ``tvWidth`` is its width; ``panel``: the
    panel behind it, when the request wants one) and ``let`` (more values)."""
    t = layouts(catalog).get(style) or layouts(catalog).get("columns")
    if t is None:
        raise InvalidInput(f"Unknown TV layout {style!r}", code="unknown-layout-template", params={"template": style})
    env: dict[str, expr.Value] = {"length": float(int(length // 10) * 10), "top": float(common.get("cabinetTop") or 2400.0), "panel": panel}
    for name, fm in t.vars:
        env[name] = float(expr.evaluate(fm, env))
    front = front_of(common)
    out: list[LaidModule] = []
    groups: dict[str, list[LaidModule]] = {}
    for st in t.steps:
        if st.when is not None and not expr.evaluate(st.when, env):
            continue
        v = {k: float(expr.evaluate(fm, env)) for k, fm in st.formulas.items() if not k.startswith("panel.")}
        if st.do == "let":
            for name, fm in st.lets:
                env[name] = float(expr.evaluate(fm, env))
        elif st.do == "tv":
            tv = tv_for(v["fit"], catalog)
            env["tvWidth"] = float(str(tv["dimensions"]).split("x")[0])
            v = {k: float(expr.evaluate(fm, env)) for k, fm in st.formulas.items()}
            host_group = groups.get(str(st.data.get("on") or ""), [])
            if host_group:
                wants = panel and "panel.width" in v
                _put_tv(host_group, v["center"], v["fit"], (v["panel.width"], v["panel.y0"], v["panel.y1"]) if wants else None, catalog)
        else:
            at, length_ = v.get("start", 0.0), v.get("length", 0.0)
            pieces = _split(length_, v["split"]) if "split" in v else [length_]
            made: list[LaidModule] = []
            for w in pieces:
                entry: dict[str, Any] = {"type": str(st.data.get("type") or "base"), "s": at, "width": w, "y": v.get("y", 0.0), "height": v.get("height", 0.0),
                                         "depth": v.get("depth", 0.0), "name": NAMES.get(str(st.data.get("name") or ""), str(st.data.get("name") or ""))}
                if st.data.get("drawer"):
                    entry["frontSections"] = [{"type": "drawer", "height": v.get("height", 0.0)}]
                if "shelfCount" in st.data:
                    entry["shelfCount"] = int(st.data["shelfCount"])
                if st.data.get("front"):
                    entry["material"] = front
                made.append(cast(LaidModule, entry))
                at += w
            out += made
            if st.data.get("group"):
                groups.setdefault(str(st.data["group"]), []).extend(made)
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
