"""Cabinet types built from formulas (catalog kind ``cabinet-type``): which panels a cabinet of a type is made of.

A type is a list of steps over the cabinet's numbers (``VARIABLES``), each with an optional ``when`` (a true/false formula):

* ``{"part": "carcass", "s": [s0, s1], "d": [d0, d1], "y": [y0, y1]}``: one box, along the run (s), out from the wall (d), up (y);
* ``{"fronts": "door" | "glass-door" | "drawer", "s": [...], "y": [...]}``: the fronts over that stretch, split by the cabinet's
  ``doors`` with the door gap (``geometry`` does the splitting);
* ``{"repeat": n, "as": "i", "let": {...}, "parts": [...]}``: the inner steps n times, ``i`` = 0 .. n-1;
* ``{"special": "back-panel" | "front-sections", ...}``: a step the code does (a TV unit's back panel; the stacked drawers / niches of
  ``frontSections``).

``let`` names helper values (type level and per repeat), each formula seeing the names before it. ``like`` reuses another type's
steps; ``builder`` names a builder kept in code (the two-legged corner shelf). Formulas are compiled once per catalog (``table``);
a formula that does not compile stops the catalog with the type, the step and the position.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from . import builtin
from .catalog import Catalog
from .catalog import expr
from .errors import InvalidInput
from .jsonview import as_dict, as_list
from .numeric import round_half_away

VARIABLES = (     # the numbers a formula of a cabinet type may read (all in mm, counts as numbers)
    "fromCorner", "endAt", "width", "height", "depth", "y", "top",          # the cabinet's place and size
    "fs0", "fs1", "b0", "b1", "p0", "p1",                                   # the stretch with fronts, the blind corner, the end panel
    "endPanel", "blindCorner", "niche", "shelfCount", "sections", "doors",  # 0 when the cabinet has none
    "doorThickness", "doorGap", "plinthHeight",                             # common sizes of the design
)
FRONTS = ("door", "glass-door", "drawer")
SPECIALS = ("back-panel", "front-sections")
BUILDERS = ("corner-shelf",)
MAX_REPEAT = 200


@dataclass(frozen=True)
class Step:
    when: expr.Formula | None
    part: str = ""                                     # a box of this part type
    box: tuple[expr.Formula, ...] = ()                 # s0, s1, d0, d1, y0, y1 (fronts / special: s0, s1, y0, y1)
    fronts: str = ""
    special: str = ""
    repeat: expr.Formula | None = None
    index: str = ""
    lets: tuple[tuple[str, expr.Formula], ...] = ()
    steps: tuple["Step", ...] = ()
    where: str = ""                                    # the step's place in the type ("parts[2]"), for the checks


@dataclass(frozen=True)
class CabinetType:
    id: str
    storey: str
    builder: str                                       # "" = the steps below
    lets: tuple[tuple[str, expr.Formula], ...]
    steps: tuple[Step, ...]
    frontless: bool = False        # no doors or drawer fronts: no front material, door style or handle
    own_door: bool = False         # its door style is its own (glass): a restyle leaves it
    front_style: str = "slab"      # the door style the 3D file says when the design names none
    plain_type: str = ""           # what it becomes in the other runs of a relayout (sink cabinet -> plain base); "" = itself
    main_run_only: bool = False    # left out of the other runs of a relayout (the fridge cabinet)
    export_type: str = ""          # moduleType in the 3D file; "" = by storey


class Emit(Protocol):
    """What the steps produce, done by the caller (``geometry``): boxes, fronts, the steps kept in code."""

    def box(self, part: str, s0: float, s1: float, d0: float, d1: float, y0: float, y1: float) -> None: ...

    def fronts(self, kind: str, s0: float, s1: float, y0: float, y1: float) -> None: ...

    def special(self, name: str, span: tuple[float, ...]) -> None: ...


def _fail(type_id: str, where: str, e: InvalidInput) -> InvalidInput:
    return InvalidInput(f"cabinet type {type_id}, {where}: {e.message}", code="cabinet-type-formula",
                        params={"type": type_id, "where": where, "at": e.params.get("at", 0), "detail": e.code})


def _formula(type_id: str, where: str, text: Any, names: Mapping[str, str], want: str) -> expr.Formula:
    try:
        return expr.compile(str(text), names, want)
    except InvalidInput as e:
        raise _fail(type_id, where, e) from None


def _lets(type_id: str, where: str, raw: Any, names: dict[str, str]) -> tuple[tuple[str, expr.Formula], ...]:
    out: list[tuple[str, expr.Formula]] = []
    for name, text in (as_dict(raw) or {}).items():
        out.append((name, _formula(type_id, f"{where}let.{name}", text, names, expr.NUM)))
        names[name] = expr.NUM
    return tuple(out)


def _range(type_id: str, where: str, raw: Any, names: Mapping[str, str]) -> tuple[expr.Formula, ...]:
    xs = as_list(raw) or []
    if len(xs) != 2:
        raise InvalidInput(f"cabinet type {type_id}, {where}: needs [from, to]", code="cabinet-type-step", params={"type": type_id, "where": where})
    return tuple(_formula(type_id, f"{where}[{i}]", x, names, expr.NUM) for i, x in enumerate(xs))


def _steps(type_id: str, where: str, raw: Any, names: dict[str, str]) -> tuple[Step, ...]:
    out: list[Step] = []
    for k, r in enumerate(as_list(raw) or []):
        d = as_dict(r) or {}
        at = f"{where}parts[{k}]"
        when = _formula(type_id, f"{at}.when", d["when"], names, expr.BOOL) if "when" in d else None
        if "repeat" in d:
            inner = dict(names)
            index = str(d.get("as") or "i")
            inner[index] = expr.NUM
            lets = _lets(type_id, f"{at}.", d.get("let"), inner)
            out.append(Step(when, repeat=_formula(type_id, f"{at}.repeat", d["repeat"], names, expr.NUM), index=index, lets=lets,
                            steps=_steps(type_id, f"{at}.", d.get("parts"), inner), where=at))
        elif "part" in d:
            box = (*_range(type_id, f"{at}.s", d.get("s"), names), *_range(type_id, f"{at}.d", d.get("d"), names),
                   *_range(type_id, f"{at}.y", d.get("y"), names))
            out.append(Step(when, part=str(d["part"]), box=box, where=at))
        elif "fronts" in d:
            kind = str(d["fronts"])
            if kind not in FRONTS:
                raise InvalidInput(f"cabinet type {type_id}, {at}: fronts must be one of {', '.join(FRONTS)}", code="cabinet-type-step",
                                   params={"type": type_id, "where": at})
            out.append(Step(when, fronts=kind, box=(*_range(type_id, f"{at}.s", d.get("s"), names), *_range(type_id, f"{at}.y", d.get("y"), names)),
                            where=at))
        elif "special" in d:
            name = str(d["special"])
            if name not in SPECIALS:
                raise InvalidInput(f"cabinet type {type_id}, {at}: special must be one of {', '.join(SPECIALS)}", code="cabinet-type-step",
                                   params={"type": type_id, "where": at})
            span = (*_range(type_id, f"{at}.s", d["s"], names), *_range(type_id, f"{at}.y", d.get("y"), names)) if "s" in d else ()
            out.append(Step(when, special=name, box=span, where=at))
        else:
            raise InvalidInput(f"cabinet type {type_id}, {at}: a step is a part, fronts, repeat or special", code="cabinet-type-step",
                               params={"type": type_id, "where": at})
    return tuple(out)


def _compile(type_id: str, data: Mapping[str, Any], raw: Mapping[str, Mapping[str, Any]], seen: tuple[str, ...] = ()) -> CabinetType:
    like = data.get("like")
    if like:
        if like in seen or like not in raw:
            raise InvalidInput(f"cabinet type {type_id}: like {like!r} is missing or loops", code="cabinet-type-like", params={"type": type_id, "like": like})
        base = _compile(str(like), raw[str(like)], raw, (*seen, type_id))
        return _with_props(CabinetType(type_id, str(data.get("storey") or base.storey), base.builder, base.lets, base.steps), data)
    builder = str(data.get("builder") or "")
    if builder and builder not in BUILDERS:
        raise InvalidInput(f"cabinet type {type_id}: unknown builder {builder!r}", code="cabinet-type-step", params={"type": type_id, "where": "builder"})
    names = {v: expr.NUM for v in VARIABLES}
    lets = _lets(type_id, "", data.get("let"), names)
    return _with_props(CabinetType(type_id, str(data.get("storey") or "base"), builder, lets, _steps(type_id, "", data.get("parts"), names)), data)


def _with_props(t: CabinetType, data: Mapping[str, Any]) -> CabinetType:
    """The properties other code reads (not the steps): each type says its own, ``like`` does not pass them on."""
    return replace(t, frontless=bool(data.get("frontless", False)), own_door=bool(data.get("ownDoor", False)),
                   front_style=str(data.get("frontStyle") or "slab"), plain_type=str(data.get("plainType") or ""),
                   main_run_only=bool(data.get("mainRunOnly", False)), export_type=str(data.get("exportType") or ""))


def _table(catalog: Catalog) -> dict[str, CabinetType]:
    raw = {it.id: it.data for it in catalog.all("cabinet-type")}
    out = {k: _compile(k, v, raw) for k, v in raw.items()}
    for t in out.values():
        if storey_by_name(t.id) != t.storey:
            raise InvalidInput(f"cabinet type {t.id}: its id must start with its storey ({t.storey})", code="cabinet-type-id",
                               params={"type": t.id, "storey": t.storey})
    return out


def check_known(types: list[str], catalog: Catalog = builtin.CATALOG) -> None:
    """Raises when a cabinet of the design has a type the catalog does not have."""
    table_ = table(catalog)
    unknown = sorted({t for t in types if t not in table_})
    if unknown and table_:            # a catalog without the kind at all (a test catalog) checks nothing
        raise InvalidInput(f"Unknown cabinet type {', '.join(unknown)}; the catalog has {', '.join(table_)}", code="unknown-cabinet-type",
                           params={"type": ", ".join(unknown)})


def table(catalog: Catalog = builtin.CATALOG) -> dict[str, CabinetType]:
    """Every cabinet type of ``catalog``, compiled (once per catalog)."""
    return catalog.derived("cabinet-types", _table)


def of(type_id: str, catalog: Catalog = builtin.CATALOG) -> CabinetType:
    t = table(catalog).get(type_id)
    if t is None:
        raise InvalidInput(f"Unknown cabinet type {type_id!r}", code="unknown-cabinet-type", params={"type": type_id})
    return t


def get(type_id: str, catalog: Catalog = builtin.CATALOG) -> CabinetType | None:
    """The type ``type_id``, None when the catalog has none."""
    return table(catalog).get(type_id)


def storey_by_name(type_id: str) -> str:
    """The storey a type id says: ``tall…``, ``upper-loft…`` / ``loft…``, ``upper…``, ``corner…``, else base. A type's id must say its storey
    (checked when the catalog loads), so code that has no catalog at hand (``Module.storey``) still knows the storey of a type the workshop
    added."""
    if type_id.startswith("tall"):
        return "tall"
    if type_id.startswith(("upper-loft", "loft")):
        return "loft"
    if type_id.startswith("upper"):
        return "upper"
    if type_id.startswith("corner"):
        return "corner"
    return "base"


def storey_of(type_id: str, catalog: Catalog = builtin.CATALOG) -> str:
    """The storey of a cabinet type (base, upper, loft, tall, corner)."""
    t = get(type_id, catalog)
    return t.storey if t is not None else storey_by_name(type_id)


def frontless(type_id: str, catalog: Catalog = builtin.CATALOG) -> bool:
    t = get(type_id, catalog)
    return t is not None and t.frontless


def own_door(type_id: str, catalog: Catalog = builtin.CATALOG) -> bool:
    t = get(type_id, catalog)
    return t is not None and t.own_door


def _num(f: expr.Formula, env: Mapping[str, expr.Value]) -> float:
    return float(expr.evaluate(f, env))


def _run(steps: tuple[Step, ...], env: dict[str, expr.Value], emit: Emit, seen: list[str] | None = None) -> None:
    for st in steps:
        if st.when is not None and not expr.evaluate(st.when, env):
            continue
        if st.repeat is not None:
            n = int(_num(st.repeat, env))
            if n > MAX_REPEAT:
                raise InvalidInput(f"a cabinet type repeats a step {n} times (most {MAX_REPEAT})", code="cabinet-type-repeat", params={"n": n, "most": MAX_REPEAT})
            for i in range(max(0, n)):
                inner = dict(env)
                inner[st.index] = float(i)
                for name, f in st.lets:
                    inner[name] = _num(f, inner)
                _run(st.steps, inner, emit, seen)
        elif st.part:
            if seen is not None:
                seen.append(st.where)
            v = [_num(f, env) for f in st.box]
            emit.box(st.part, v[0], v[1], v[2], v[3], v[4], v[5])
        elif st.fronts:
            if seen is not None:
                seen.append(st.where)
            v = [_num(f, env) for f in st.box]
            emit.fronts(st.fronts, v[0], v[1], v[2], v[3])
        else:
            if seen is not None:
                seen.append(st.where)
            emit.special(st.special, tuple(_num(f, env) for f in st.box))


def build(t: CabinetType, values: Mapping[str, float], emit: Emit, seen: list[str] | None = None) -> None:
    """Run the steps of ``t`` for a cabinet whose ``VARIABLES`` are ``values``. ``seen``: filled with the place of each step that emits,
    in order (the checks use it to say which step a problem comes from)."""
    env: dict[str, expr.Value] = {k: float(values[k]) for k in VARIABLES}
    for name, f in t.lets:
        env[name] = _num(f, env)
    _run(t.steps, env, emit, seen)


TOLERANCE_MM = 0.5
FRONT_COVER = 0.85      # the fronts must cover this much of the front face (the stretch with fronts, above the plinth)


class _Record:
    """An ``Emit`` that keeps what the steps produce, in order, for the checks: ``(what, name, numbers)``, what = box / fronts / special."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, tuple[float, ...]]] = []

    def box(self, part: str, s0: float, s1: float, d0: float, d1: float, y0: float, y1: float) -> None:
        self.events.append(("box", part, (s0, s1, d0, d1, y0, y1)))

    def fronts(self, kind: str, s0: float, s1: float, y0: float, y1: float) -> None:
        self.events.append(("fronts", kind, (s0, s1, y0, y1)))

    def special(self, name: str, span: tuple[float, ...]) -> None:
        self.events.append(("special", name, span))


def check(t: CabinetType, values: Mapping[str, float]) -> list[dict[str, Any]]:
    """What looks wrong when ``t`` builds a cabinet of ``values`` (the type editor shows it before saving): a box with no size, a box
    outside the cabinet's frame, no carcass, fronts that leave much of the front face open. Each: ``{code, where, ...}``."""
    if t.builder:
        return []
    rec, seen = _Record(), list[str]()
    build(t, values, rec, seen)
    problems: list[dict[str, Any]] = []
    eps = TOLERANCE_MM
    s_lo, s_hi, top, y = values["fromCorner"], values["endAt"], values["top"], values["y"]
    boxes = [(name, v) for what, name, v in rec.events if what == "box"]
    fronts = [v for what, _, v in rec.events if what == "fronts"]
    specials = [name for what, name, _ in rec.events if what == "special"]
    for (what, part, v), where in zip(rec.events, seen):
        if what != "box":
            continue
        s0, s1, d0, d1, y0, y1 = v
        if s1 - s0 <= 0.01 or d1 - d0 <= 0.01 or y1 - y0 <= 0.01:
            problems.append({"code": "box-empty", "where": where, "part": part})
        elif s0 < s_lo - eps or s1 > s_hi + eps or d0 < -eps or d1 > values["depth"] + eps or y1 > top + eps or (y0 < y - eps and part != "plinth"):
            problems.append({"code": "box-outside", "where": where, "part": part})
    if not any(p == "carcass" for p, _ in boxes):
        problems.append({"code": "no-carcass", "where": ""})
    if not t.frontless and "front-sections" not in specials:
        body = max(y, values["plinthHeight"]) if y == 0 else y
        face = max(0.0, values["fs1"] - values["fs0"]) * max(0.0, top - body)
        covered = sum(max(0.0, f[1] - f[0]) * max(0.0, f[3] - f[2]) for f in fronts)
        if face > 0 and covered < FRONT_COVER * face:
            problems.append({"code": "fronts-short", "where": "", "percent": round_half_away(100 * covered / face)})
    return problems

