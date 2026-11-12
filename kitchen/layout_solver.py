"""Kitchen layout templates (catalog kinds ``layout-template`` and ``layout-rules``): the runs of a straight, L or U kitchen, laid out by one
solver from data.

A template names the steps that lay a kitchen out, each with formulas (``catalog.expr``) over the request's sizes:

* ``corner-base``: the blind corner cabinet at the start of a wall (its blind part is the depth of the run it meets);
* ``base-run``: base cabinets over a stretch of a wall: the appliances it holds (``appliances``: the first entry whose ``when`` holds),
  the worktop left in front (``front``), the fridge cabinet at its end (``fridgeAtEnd``), cabinets of a given type and width at its start
  or end (``extras``: a wine cabinet at the end of the run...; the fridge stays outermost);
* ``corner-shelf``: open shelves round the inside corner, at the wall cabinets' height;
* ``cabinets``: the cabinets of a stretch in order, as a saved kitchen had them (``items``: type, width, ``fill``, ``when``; the type ``gap``
  is empty room): the fixed ones keep their width, the ``fill`` ones share what is left (``fit_items``), so the same cabinets fit another
  wall length; ``template_from_design`` writes such a template from a design;
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

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from . import builtin
from .catalog import Catalog
from .catalog import expr
from .errors import InvalidInput
from .jsonview import as_dict, as_list
from .numeric import round_half_away
from .runs import RunFrame

INPUTS = {"back": expr.NUM, "right": expr.NUM, "left": expr.NUM, "g": expr.NUM, "upperDepth": expr.NUM, "fridge": expr.BOOL, "lr": expr.NUM,
          "islandLength": expr.NUM, "aisle": expr.NUM}
STEPS = ("base-run", "cabinets", "corner-base", "corner-shelf", "upper-run")
GAP = "gap"   # an item of a ``cabinets`` step that is empty room, not a cabinet


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
    extras: tuple[tuple[expr.Formula | None, str, expr.Formula, str], ...] = ()     # (when, cabinet type, width, "start" | "end")
    items: tuple[tuple[expr.Formula | None, str, expr.Formula, bool], ...] = ()     # ``cabinets``: (when, cabinet type, width, fill)


@dataclass(frozen=True)
class Template:
    id: str
    vars: tuple[tuple[str, expr.Formula], ...]
    steps: tuple[Step, ...]
    room: expr.Formula | None = None
    island: tuple[expr.Formula, expr.Formula] | None = None          # (start, length)
    peninsula: tuple[expr.Formula, expr.Formula] | None = None       # (where along the right wall, room left for it)
    peninsula_uses: str = ""
    walls: tuple[str, ...] = ("back",)                                # the walls it puts cabinets on
    names: tuple[str, ...] = ()                                       # its names (``label``), lower case


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
        extras: list[tuple[expr.Formula | None, str, expr.Formula, str]] = []
        for j, x in enumerate(as_list(s.get("extras")) or []):
            x_ = as_dict(x) or {}
            when = _f(tid, f"{at}.extras[{j}].when", x_["when"], names, expr.BOOL) if "when" in x_ else None
            extras.append((when, str(x_.get("type") or "base"), _f(tid, f"{at}.extras[{j}].width", x_.get("width", "600"), names),
                           "start" if x_.get("at") == "start" else "end"))
        items: list[tuple[expr.Formula | None, str, expr.Formula, bool]] = []
        for j, x in enumerate(as_list(s.get("items")) or []):
            x_ = as_dict(x) or {}
            when = _f(tid, f"{at}.items[{j}].when", x_["when"], names, expr.BOOL) if "when" in x_ else None
            items.append((when, str(x_.get("type") or "base"), _f(tid, f"{at}.items[{j}].width", x_.get("width", "600"), names), x_.get("fill") is True))
        steps.append(Step(do, str(s.get("wall") or ""), opt("start"), opt("length"), opt("end"), opt("front"), opt("fridgeAtEnd", expr.BOOL),
                          str(s.get("type") or "base"), opt("width"), opt("blind"),
                          tuple(_f(tid, f"{at}.doors[{j}]", x, names) for j, x in enumerate(as_list(s.get("doors")) or [])), tuple(apps), tuple(extras),
                          tuple(items)))
    island = as_dict(d.get("island"))
    isl = None
    if island is not None:
        length = _f(tid, "island.length", island["length"], names)
        isl = (_f(tid, "island.start", island["start"], {**names, "n": expr.NUM}), length)
    pen = as_dict(d.get("peninsula"))
    return Template(tid, tuple(vars_), tuple(steps), _f(tid, "room", d["room"], names) if "room" in d else None, isl,
                    (_f(tid, "peninsula.at", pen["at"], names), _f(tid, "peninsula.room", pen["room"], names)) if pen is not None else None,
                    str(d.get("peninsulaUses") or ""), tuple(str(w) for w in as_list(d.get("walls")) or ["back"]),
                    tuple(sorted({str(v).strip().lower() for v in (as_dict(d.get("label")) or {}).values() if str(v).strip()})))


def _templates(catalog: Catalog) -> dict[str, Template]:
    return {it.id: _compile(it.id, it.data) for it in catalog.all("layout-template")}


def templates(catalog: Catalog = builtin.CATALOG) -> dict[str, Template]:
    return catalog.derived("layout-templates", _templates)


def template(tid: str, catalog: Catalog = builtin.CATALOG) -> Template:
    t = templates(catalog).get(tid)
    if t is None:
        raise InvalidInput(f"Unknown layout template {tid!r}", code="unknown-layout-template", params={"template": tid})
    return t


def named_in(text: str, catalog: Catalog = builtin.CATALOG) -> tuple[str, str] | None:
    """``(template id, the name found)`` of the template a sentence calls by its name (the longest name found as whole words, case
    ignored), or None."""
    low = unicodedata.normalize("NFC", text).lower()
    best: tuple[int, str, str] | None = None
    for tid, t in sorted(templates(catalog).items()):
        for name in t.names:
            if len(name) >= 3 and re.search(r"(?<!\w)" + re.escape(unicodedata.normalize("NFC", name)) + r"(?!\w)", low) and (best is None or len(name) > best[0]):
                best = (len(name), tid, name)
    return (best[1], best[2]) if best else None


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
            extras = [{"type": kind, "width": val(w), "at": where} for when, kind, w, where in s.extras if when is None or expr.evaluate(when, env)]
            on("base-run", {"wall": s.wall, "start": val(s.start), "length": val(s.length), "appliances": items, "front": val(s.front, 450.0),
                            "fridgeAtEnd": at_end, "extras": extras})
        elif s.do == "cabinets":
            kept = [{"type": kind, "width": val(w), "fill": fill} for when, kind, w, fill in s.items if when is None or expr.evaluate(when, env)]
            on("cabinets", {"wall": s.wall, "start": val(s.start), "length": val(s.length), "items": kept})
        elif s.do == "corner-base":
            on("corner-base", {"wall": s.wall, "type": s.type, "width": val(s.width), "blind": val(s.blind), "doors": [val(f) for f in s.doors]})
        elif s.do == "upper-run":
            on("upper-run", {"wall": s.wall, "start": val(s.start), "end": val(s.end)})
        else:
            on("corner-shelf", {})
    return env


# ------------------------------------------------------------------ a fixed run of cabinets
def fit_items(length: float, items: list[dict[str, Any]], rules_: Rules) -> list[tuple[float, str]]:
    """``[(width, type)]`` of a ``cabinets`` step over ``length`` mm: fixed items keep their width; each group of consecutive ``fill`` items
    of one type takes its share of what is left, in proportion to its width as saved, to 10 mm (the saved widths kept when the share is the same,
    else the share split into standard widths; a share under the narrowest cabinet joins the base cabinet next to it, never a tall one). No ``fill`` item: the
    items as they are."""
    fixed = sum(float(i["width"]) for i in items if not i.get("fill"))
    filled = sum(float(i["width"]) for i in items if i.get("fill"))
    scale = (length - fixed) / filled if filled > 0 else 1.0
    groups: list[tuple[bool, str, list[float]]] = []
    for i in items:
        fill, kind, w = bool(i.get("fill")), str(i["type"]), float(i["width"])
        if fill and groups and groups[-1][0] and groups[-1][1] == kind:
            groups[-1][2].append(w)
        else:
            groups.append((fill, kind, [w]))
    shares: list[float] = []                 # each fill group's share, to 10 mm; the last one takes what rounding left
    fill_groups = [sum(ws) for f, _, ws in groups if f]
    for n, total in enumerate(fill_groups):
        shares.append(length - fixed - sum(shares) if n == len(fill_groups) - 1 else float(round_half_away(total * scale / 10) * 10))
    out: list[tuple[float, str]] = []
    carry = 0.0                              # a share too narrow for a cabinet, for the next base cabinet (a tall one keeps its width)
    def put(w: float, kind: str) -> None:
        nonlocal carry
        if carry and kind != GAP and not kind.startswith("tall"):
            w, carry = w + carry, 0.0
        out.append((w, kind))
    for fill, kind, widths in groups:
        if not fill:
            for w in widths:
                put(w, kind)
            continue
        share = shares.pop(0)
        if abs(share - sum(widths)) < 0.5:
            for w in widths:
                put(w, kind)
        elif share >= rules_.min_width:
            for w in split(share, rules_):
                put(w, kind)
        elif share > 0.5:
            last = next((i for i in range(len(out) - 1, -1, -1) if out[i][1] != GAP and not out[i][1].startswith("tall")), None)
            if last is not None and last == len(out) - 1:
                out[last] = (out[last][0] + share, out[last][1])
            else:
                carry += share
    if carry:
        last = next((i for i in range(len(out) - 1, -1, -1) if out[i][1] != GAP and not out[i][1].startswith("tall")), None)
        if last is not None:
            out[last] = (out[last][0] + carry, out[last][1])
    return [(float(round_half_away(w)), kind) for w, kind in out if w > 0.5]


def _mm(v: float) -> str:
    """A length as a formula: whole millimetres without a decimal point."""
    r = round_half_away(v * 10) / 10
    return str(int(r)) if r == int(r) else str(r)


def _minus(wall: str, *parts: float) -> str:
    """``wall`` less the lengths ``parts`` (a negative one added) as a formula."""
    total = sum(parts)
    if abs(total) < 0.5:
        return wall
    return f"{wall} - {_mm(total)}" if total > 0 else f"{wall} + {_mm(-total)}"


CORNER_REACH = 1200.0   # mm: a run meets the main one at a corner when their back lines cross this near the main run's end


def system_as_walls(frames: list[Mapping[str, Any]], modules: list[Mapping[str, Any]], main: str) -> dict[str, Any]:
    """The cabinets of a system in runs (``spec.runs`` entries ``frames``; ``modules`` with ``run`` and ``fromCorner`` = s) as the walls of a
    kitchen: the back wall is the run with most corners (``main``, the longest, when it is a tie), a run square to it whose back line meets it near its high-s end is the right wall, near its
    low-s end the left wall (the corner is where the two back lines cross). A back wall counts ``fromCorner`` from its right-hand end, so
    its places are mirrored (``rows_to_runs``); a side wall counts from the corner. Returns ``{"module", "room", "skipped"}`` (ids of the
    cabinets of the runs that are neither)."""
    by_id = {str(f.get("id")): RunFrame(str(f.get("id")), float(f.get("x") or 0), float(f.get("z") or 0), float(f.get("yaw") or 0)) for f in frames}
    on: dict[str, list[Mapping[str, Any]]] = {}
    for m in modules:
        on.setdefault(str(m.get("run") or ""), []).append(m)
    def span(run: str) -> tuple[float, float]:
        ms = on.get(run, [])
        return (min(float(m.get("fromCorner") or 0) for m in ms), max(float(m.get("fromCorner") or 0) + float(m.get("width") or 0) for m in ms))
    def corners(main: str) -> dict[str, tuple[str, float, float]]:
        """wall -> (run, s of the corner along ``main``, s of the corner along that run)."""
        a = by_id[main]
        a0, a1 = span(main)
        ax, az = a.to_world(0, 0)
        ux, uz = a.to_world(1, 0)
        ux, uz = ux - ax, uz - az
        sides: dict[str, tuple[str, float, float]] = {}
        for rid in sorted(on):
            if rid in ("", main) or rid not in by_id:
                continue
            b = by_id[rid]
            bx, bz = b.to_world(0, 0)
            vx, vz = b.to_world(1, 0)
            vx, vz = vx - bx, vz - bz
            cross = ux * vz - uz * vx
            if abs(cross) < 0.98:                          # not square to the main run
                continue
            t = ((bx - ax) * vz - (bz - az) * vx) / cross
            px, pz = ax + t * ux, az + t * uz
            s_main, s_side = a.to_local(px, pz)[0], b.to_local(px, pz)[0]
            wall = "right" if abs(s_main - a1) <= CORNER_REACH else "left" if abs(s_main - a0) <= CORNER_REACH else ""
            if wall and wall not in sides:
                sides[wall] = (rid, s_main, s_side)
        return sides
    candidates = [r for r in on if r and r in by_id]
    if main not in candidates:
        candidates.append(main)
    # the back wall: the run with most corners (a U's middle run), then one with a right-hand corner (where a corner shelf goes), then ``main``
    main = max(sorted(candidates), key=lambda r: (len(corners(r)), "right" in corners(r), r == main))
    sides = corners(main)
    a0, a1 = span(main)
    right = sides["right"][1] if "right" in sides else a1
    left = sides["left"][1] if "left" in sides else a0
    out: list[dict[str, Any]] = []
    lengths: dict[str, float] = {"back": right - left}
    def place(m: Mapping[str, Any], wall: str, at: float) -> None:
        out.append({**{k: v for k, v in m.items() if k not in ("run", "offset", "facing")}, "wall": wall, "fromCorner": at})
    for m in on.get(main, []):
        w = float(m.get("width") or 0)
        place(m, "corner" if m.get("type") == "corner-shelf" else "back", right - float(m.get("fromCorner") or 0) - w)
    for wall, (rid, _, corner) in sides.items():
        ms = on[rid]
        forward = sum(float(m.get("fromCorner") or 0) + float(m.get("width") or 0) / 2 for m in ms) / len(ms) >= corner
        end = 0.0
        for m in ms:
            s, w = float(m.get("fromCorner") or 0), float(m.get("width") or 0)
            at = s - corner if forward else corner - s - w
            place(m, wall, at)
            end = max(end, at + w)
        lengths[wall] = end
    taken = {main, *(rid for rid, _, _ in sides.values())}
    return {"module": out, "room": {"wall": [{"id": k, "length": v} for k, v in lengths.items()]},
            "skipped": sorted(str(m.get("id")) for m in modules if str(m.get("run") or "") not in taken)}


def template_from_design(spec: Mapping[str, Any], label: str, storey_of: Callable[[str], str]) -> dict[str, Any]:
    """A ``layout-template`` item (its data) that lays out the cabinet system of ``spec`` (a design as JSON) again: per wall, the corner
    cabinet (``corner-base``), the base and tall cabinets in order (``cabinets``: plain base cabinets ``fill``, empty room as ``gap``) and the wall cabinets (``upper-run``); the corner shelf; the island's length. Lengths are
    written from the end of each wall, so the template fits other wall lengths. ``storey_of``: a cabinet type's storey. Returns
    ``{"data", "skipped"}`` (ids of the cabinets a template cannot hold: angled runs, peninsula ends...)."""
    mods = [as_dict(m) or {} for m in as_list(spec.get("module")) or []]
    room = as_dict(spec.get("room")) or {}
    lengths = {str(w.get("id")): float(w.get("length") or 0) for w in (as_dict(x) or {} for x in as_list(room.get("wall")) or [])}
    common = as_dict(spec.get("common")) or {}
    depth = float(common.get("baseDepth") or 600)
    def end_of(m: Mapping[str, Any]) -> float:
        return float(m.get("fromCorner") or 0) + float(m.get("width") or 0)
    steps: list[dict[str, Any]] = []
    uppers: list[dict[str, Any]] = []
    walls: list[str] = []
    used: set[str] = set()
    for wall in ("right", "back", "left"):
        on = sorted((m for m in mods if m.get("wall") == wall and not m.get("run")), key=lambda m: float(m.get("fromCorner") or 0))
        if not on:
            continue
        walls.append(wall)
        wall_len = max(lengths.get(wall, 0.0), max(end_of(m) for m in on))
        low = [m for m in on if storey_of(str(m.get("type"))) in ("base", "tall")]
        corner = next((m for m in low if float(m.get("blindCorner") or 0) > 0 and float(m.get("fromCorner") or 0) < 0.5), None)
        if corner is not None:
            blind = float(corner.get("blindCorner") or 0)
            steps.append({"do": "corner-base", "wall": wall, "type": str(corner.get("type")), "width": _mm(float(corner.get("width") or 0)),
                          "blind": "g" if abs(blind - depth) < 0.5 else _mm(blind),
                          "doors": [_mm(float(d)) for d in as_list(corner.get("doors")) or []]})
            used.add(str(corner.get("id")))
            low = [m for m in low if m is not corner]
        if low:
            start = float(low[0].get("fromCorner") or 0)
            items: list[dict[str, Any]] = []
            at = start
            for m in low:
                s = float(m.get("fromCorner") or 0)
                if s - at >= 0.5:
                    items.append({"type": GAP, "width": _mm(s - at)})
                kind = str(m.get("type"))
                item: dict[str, Any] = {"type": kind, "width": _mm(float(m.get("width") or 0))}
                if kind in ("base", "base-drawers"):
                    item["fill"] = True
                items.append(item)
                at = max(at, end_of(m))
                used.add(str(m.get("id")))
            steps.append({"do": "cabinets", "wall": wall, "start": _mm(start), "length": _minus(wall, start, wall_len - at), "items": items})
        high = [m for m in on if storey_of(str(m.get("type"))) in ("upper", "loft")]
        if high:
            a = min(float(m.get("fromCorner") or 0) for m in high)
            b = max(end_of(m) for m in high)
            uppers.append({"do": "upper-run", "wall": wall, "start": _mm(a), "end": _minus(wall, wall_len - b)})
            used.update(str(m.get("id")) for m in high)
    shelf = [m for m in mods if m.get("type") == "corner-shelf"]
    if shelf:
        steps.append({"do": "corner-shelf"})
        used.update(str(m.get("id")) for m in shelf)
    data: dict[str, Any] = {"label": {"vi": label, "en": label}, "walls": [w for w in ("back", "right", "left") if w in walls] or ["back"],
                            "steps": steps + uppers}
    island = [m for m in mods if m.get("wall") == "island" and not m.get("run")]
    if island:
        a = min(float(m.get("fromCorner") or 0) for m in island)
        b = max(end_of(m) for m in island)
        data["island"] = {"start": _mm(a), "length": _mm(b - a)}
        used.update(str(m.get("id")) for m in island)
    return {"data": data, "skipped": sorted(str(m.get("id")) for m in mods if str(m.get("id")) not in used)}
