"""Kitchen layout templates (catalog kinds ``layout-template`` and ``layout-rules``): the runs of a straight, L or U kitchen, laid out by one
solver from data.

A template names the steps that lay a kitchen out, each with formulas (``catalog.expr``) over the request's sizes:

* ``corner-base``: the blind corner cabinet at the start of a wall (its blind part is the depth of the run it meets);
* ``base-run``: base cabinets over a stretch of a wall: the appliances it holds (``appliances``: the first entry whose ``when`` holds),
  the worktop left in front (``front``), the fridge cabinet at its end (``fridgeAtEnd``);
* ``corner-shelf``: open shelves round the inside corner, at the wall cabinets' height;
* ``upper-run``: wall cabinets over a stretch, cut where the base cabinets below are cut (pieces under ``minWidth`` joined), the one over
  the cooktop a hood cabinet, a top cabinet over each when the request asks for a loft row.

``vars`` names values the steps share (``W`` the back wall's length...). ``island`` / ``peninsula`` say where those free runs go;
``peninsulaUses`` names the template a peninsula needs (a straight kitchen takes the L one). The numbers every layout uses (filler widths,
the fallback steps of a short run, the fridge cabinet, the aisle...) are ``layout-rules``.

Names a formula may read: ``back``, ``right``, ``left`` (the wall lengths asked; 0 when not given), ``g`` (base depth), ``upperDepth``,
``fridge`` (true / false), ``lr`` (the fridge cabinet's width when there is one, else 0), ``islandLength`` (0 when not given), ``aisle``,
then the template's ``vars`` in order (and ``n``, the free run's length, in ``island.start``).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from . import builtin
from .catalog import Catalog
from .catalog import expr
from .errors import InvalidInput
from .jsonview import as_dict, as_list
from .numeric import round_half_away

INPUTS = {"back": expr.NUM, "right": expr.NUM, "left": expr.NUM, "g": expr.NUM, "upperDepth": expr.NUM, "fridge": expr.BOOL, "lr": expr.NUM,
          "islandLength": expr.NUM, "aisle": expr.NUM}
STEPS = ("base-run", "corner-base", "corner-shelf", "upper-run")


@dataclass(frozen=True)
class Rules:
    standard_widths: tuple[float, ...]
    min_width: float
    smallest_piece: float
    appliance_types: Mapping[str, str]
    tiers: tuple[tuple[float, float, float, float | None], ...]      # (appliance cabinet, between, end, start at most; None = as asked)
    fridge: Mapping[str, Any]
    corner_shelf: Mapping[str, Any]
    double_door_from: float
    hood_height: float
    loft_height: float
    aisle: float
    drawers: tuple[float, ...]


def _num(v: Any, fallback: float) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else fallback


def _rules(catalog: Catalog) -> Rules:
    fallback = builtin.CATALOG.data("layout-rules", "default")
    item = catalog.find("layout-rules", "default")
    d: dict[str, Any] = {**fallback, **(dict(item.data) if item is not None else {})}
    tiers: list[tuple[float, float, float, float | None]] = []
    for raw in as_list(d.get("applianceTiers")) or []:
        t = as_dict(raw) or {}
        cap = t.get("startMax")
        tiers.append((_num(t.get("appliance"), 600), _num(t.get("between"), 0), _num(t.get("end"), 0), None if cap is None else _num(cap, 0)))
    return Rules(tuple(_num(w, 0) for w in as_list(d.get("standardWidths")) or []), _num(d.get("minWidth"), 300), _num(d.get("smallestPiece"), 150),
                 {str(k): str(v) for k, v in (as_dict(d.get("applianceTypes")) or {}).items()}, tuple(tiers), as_dict(d.get("fridge")) or {},
                 as_dict(d.get("cornerShelf")) or {}, _num(d.get("doubleDoorFrom"), 600), _num(d.get("hoodHeight"), 165),
                 _num(d.get("loftHeight"), 330), _num(d.get("aisle"), 1100), tuple(_num(h, 0) for h in as_list(d.get("drawers")) or []))


def rules(catalog: Catalog = builtin.CATALOG) -> Rules:
    return catalog.derived("layout-rules", _rules)


# ------------------------------------------------------------------ splitting a stretch
def split(length: float, rules_: Rules, priority: list[float] | None = None) -> list[float]:
    """Standard cabinet widths over ``length`` (the first that leaves at least the narrowest cabinet, or nothing); what is left goes to the
    last cabinet."""
    out: list[float] = []
    con = length
    least = rules_.min_width
    for w in priority or []:
        if con - w >= least:
            out.append(w)
            con -= w
    while con >= least:
        w = next((x for x in rules_.standard_widths if con - x >= least or con - x == 0), least)
        if con - w < least and con - w != 0:
            w = con
        out.append(w)
        con -= w
    if con > 0.5:
        if out:
            out[-1] += con
        else:
            out.append(con)
    return [float(round_half_away(w)) for w in out]


def base_plan(length: float, appliances: list[str], rules_: Rules, front: float = 450, toward_end: bool = False) -> list[tuple[float, str]]:
    """``[(width, type)]`` of the base cabinets of a run: [worktop in front] + the appliances with worktop between + [worktop at the end],
    the first of the fallback steps (``applianceTiers``) that fits; none fits: plain cabinets. ``toward_end``: the spare room goes to the
    start, so the last appliance stands at the end of the run (the sink next to the fridge)."""
    least = rules_.min_width
    chosen: tuple[float, float, float, float] | None = None
    for w_tb, gap_mid, gap_end, cap in rules_.tiers:
        gap_start = front if cap is None else min(front, cap)
        need = gap_start + len(appliances) * w_tb + gap_mid * max(0, len(appliances) - 1) + gap_end
        if need <= length:
            chosen = (w_tb, gap_mid, gap_end, gap_start)
            break
    if chosen is None:
        return [(w, "base") for w in split(length, rules_)] if length >= least else []
    w_tb, gap_mid, gap_end, gap_start = chosen
    need = gap_start + len(appliances) * w_tb + gap_mid * max(0, len(appliances) - 1) + gap_end
    extra = length - need
    gaps = ([gap_start + extra] if toward_end else [gap_start]) + [gap_mid] * max(0, len(appliances) - 1) + [gap_end + (0 if toward_end else extra)]
    out: list[tuple[float, str]] = []
    for i, gap in enumerate(gaps):
        if gap >= least:
            out += [(w, "base") for w in split(gap, rules_)]
        elif gap > 0:                       # under the narrowest cabinet: joined to the appliance cabinet before it
            if out:
                out[-1] = (out[-1][0] + gap, out[-1][1])
            elif gap >= rules_.smallest_piece:
                out.append((gap, "base"))
        if i < len(appliances):
            out.append((w_tb, rules_.appliance_types.get(appliances[i], "base")))
    return [(float(round_half_away(w)), kind) for w, kind in out]


# ------------------------------------------------------------------ templates
@dataclass(frozen=True)
class Step:
    do: str
    wall: str = ""
    start: expr.Formula | None = None
    length: expr.Formula | None = None
    end: expr.Formula | None = None
    front: expr.Formula | None = None
    fridge_at_end: expr.Formula | None = None
    type: str = ""
    width: expr.Formula | None = None
    blind: expr.Formula | None = None
    doors: tuple[expr.Formula, ...] = ()
    appliances: tuple[tuple[expr.Formula | None, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class Template:
    id: str
    vars: tuple[tuple[str, expr.Formula], ...]
    steps: tuple[Step, ...]
    room: expr.Formula | None = None
    island: tuple[expr.Formula, expr.Formula] | None = None          # (start, length)
    peninsula: tuple[expr.Formula, expr.Formula] | None = None       # (where along the right wall, room left for it)
    peninsula_uses: str = ""


def _f(tid: str, where: str, text: Any, names: Mapping[str, str], want: str = expr.NUM) -> expr.Formula:
    try:
        return expr.compile(str(text), names, want)
    except InvalidInput as e:
        raise InvalidInput(f"layout template {tid}, {where}: {e.message}", code="layout-template-formula",
                           params={"template": tid, "where": where, "at": e.params.get("at", 0), "detail": e.code}) from None


def _compile(tid: str, d: Mapping[str, Any]) -> Template:
    names = dict(INPUTS)
    vars_: list[tuple[str, expr.Formula]] = []
    for k, v in (as_dict(d.get("vars")) or {}).items():
        vars_.append((k, _f(tid, f"vars.{k}", v, names)))
        names[k] = expr.NUM
    steps: list[Step] = []
    for i, raw in enumerate(as_list(d.get("steps")) or []):
        s = as_dict(raw) or {}
        at = f"steps[{i}]"
        do = str(s.get("do") or "")
        if do not in STEPS:
            raise InvalidInput(f"layout template {tid}, {at}: unknown step {do!r}", code="layout-template-step", params={"template": tid, "where": at})
        def opt(key: str, want: str = expr.NUM, s: Mapping[str, Any] = s, at: str = at) -> expr.Formula | None:
            return _f(tid, f"{at}.{key}", s[key], names, want) if key in s else None
        apps: list[tuple[expr.Formula | None, tuple[str, ...]]] = []
        for j, a in enumerate(as_list(s.get("appliances")) or []):
            a_ = as_dict(a) or {}
            when = _f(tid, f"{at}.appliances[{j}].when", a_["when"], names, expr.BOOL) if "when" in a_ else None
            apps.append((when, tuple(str(x) for x in as_list(a_.get("items")) or [])))
        steps.append(Step(do, str(s.get("wall") or ""), opt("start"), opt("length"), opt("end"), opt("front"), opt("fridgeAtEnd", expr.BOOL),
                          str(s.get("type") or "base"), opt("width"), opt("blind"),
                          tuple(_f(tid, f"{at}.doors[{j}]", x, names) for j, x in enumerate(as_list(s.get("doors")) or [])), tuple(apps)))
    island = as_dict(d.get("island"))
    isl = None
    if island is not None:
        length = _f(tid, "island.length", island["length"], names)
        isl = (_f(tid, "island.start", island["start"], {**names, "n": expr.NUM}), length)
    pen = as_dict(d.get("peninsula"))
    return Template(tid, tuple(vars_), tuple(steps), _f(tid, "room", d["room"], names) if "room" in d else None, isl,
                    (_f(tid, "peninsula.at", pen["at"], names), _f(tid, "peninsula.room", pen["room"], names)) if pen is not None else None,
                    str(d.get("peninsulaUses") or ""))


def _templates(catalog: Catalog) -> dict[str, Template]:
    return {it.id: _compile(it.id, it.data) for it in catalog.all("layout-template")}


def templates(catalog: Catalog = builtin.CATALOG) -> dict[str, Template]:
    return catalog.derived("layout-templates", _templates)


def template(tid: str, catalog: Catalog = builtin.CATALOG) -> Template:
    t = templates(catalog).get(tid)
    if t is None:
        raise InvalidInput(f"Unknown layout template {tid!r}", code="unknown-layout-template", params={"template": tid})
    return t


# ------------------------------------------------------------------ laying out
def plan(t: Template, inputs: Mapping[str, expr.Value], rules_: Rules, on: Callable[[str, dict[str, Any]], None]) -> dict[str, expr.Value]:
    """Run the steps of ``t`` with the request's ``inputs`` (``INPUTS``): ``on(step, values)`` for each step, the formulas evaluated
    (``base-run`` gives its ``plan`` of cabinets too). Returns the values the formulas saw (inputs and ``vars``)."""
    env: dict[str, expr.Value] = dict(inputs)
    for name, f in t.vars:
        env[name] = float(expr.evaluate(f, env))
    def val(f: expr.Formula | None, default: float = 0.0) -> float:
        return float(expr.evaluate(f, env)) if f is not None else default
    for s in t.steps:
        if s.do == "base-run":
            items: list[str] = next((list(items) for when, items in s.appliances if when is None or expr.evaluate(when, env)), list[str]())
            at_end = bool(expr.evaluate(s.fridge_at_end, env)) if s.fridge_at_end is not None else False
            on("base-run", {"wall": s.wall, "start": val(s.start), "length": val(s.length), "appliances": items, "front": val(s.front, 450.0),
                            "fridgeAtEnd": at_end})
        elif s.do == "corner-base":
            on("corner-base", {"wall": s.wall, "type": s.type, "width": val(s.width), "blind": val(s.blind), "doors": [val(f) for f in s.doors]})
        elif s.do == "upper-run":
            on("upper-run", {"wall": s.wall, "start": val(s.start), "end": val(s.end)})
        else:
            on("corner-shelf", {})
    return env
