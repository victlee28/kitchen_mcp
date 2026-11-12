"""Appliance models: what a design's appliance is (its model, size, cut-out, energy, look), whether another model fits where it stands, and the
facts the image AI needs about it (pure, rule R1). Plan: claude/ke-hoach-thay-mau-thiet-bi.md.

A design written before models existed has no ``model``: it is read as a guess (a hob is gas when its name says so, else induction; a sink is
double when its name says "đôi") and its own ``dimensions`` stay its size, so nothing it shows changes.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import Any

from . import builtin, defaults, words
from .words import Said, key_of, said
from .catalog import Catalog
from .errors import InvalidInput
from .i18n import pick
from .jsonview import as_dict
from .runs import row_of, spot
from .spec import Appliance, KitchenSpec, Module
from . import lexicon

SIDE = defaults.BUILTIN.side                  # mm: cabinet side panel; a hole must fit between the two (catalog kind defaults)
WORKTOP_EDGE = defaults.BUILTIN.worktop_edge  # mm: worktop left in front of and behind a hole
HOOD_SIDE = defaults.BUILTIN.hood_side        # mm: an integrated hood needs this much room each side inside its cabinet
TYPES = ("cooktop", "sink", "faucet", "hood", "fridge", "oven", "tv")


def models(catalog: Catalog = builtin.CATALOG) -> dict[str, dict[str, Any]]:
    """The appliance models of the catalog (kind ``appliance``), by id: each its data plus ``id``, ``name`` in Vietnamese (as designs store
    it) and ``label`` (the localised name). ``catalog``: the merged catalog the service passes; the builtin layer when none is given."""
    return {i.id: {"id": i.id, **i.data, "name": pick(i.data.get("name"), "vi"), "label": i.data.get("name")} for i in catalog.all("appliance")}


def model(model_id: str, catalog: Catalog = builtin.CATALOG) -> dict[str, Any]:
    found = models(catalog).get(model_id)
    if found is None:
        raise InvalidInput(f"No appliance model {model_id!r}", code="model-not-found", params={"id": model_id})
    return found


def default_for(kind: str, catalog: Catalog = builtin.CATALOG) -> dict[str, Any] | None:
    return next((m for m in models(catalog).values() if m["type"] == kind and m.get("default")), None)


def guessed(app: Appliance, catalog: Catalog = builtin.CATALOG) -> str | None:
    """The model a model-less appliance is read as (from its name, as before models existed)."""
    name = (app.name or "").lower()
    if app.type == "cooktop":
        return "hob-gas-2b-75" if "gas" in name else "hob-ind-2z-73"
    if app.type == "sink":
        return "sink-double-82" if "đôi" in name else "sink-single-60"
    d = default_for(app.type, catalog)
    return d["id"] if d else None


def model_id(app: Appliance, catalog: Catalog = builtin.CATALOG) -> str | None:
    """The appliance's own model, else the guess."""
    own = getattr(app, "model", None)
    return own if isinstance(own, str) and own in models(catalog) else guessed(app, catalog)


def size_of(app: Appliance) -> dict[str, float] | None:
    """The appliance's size {w, d, h} (mm): its own ``size``, else read from ``dimensions`` in the order each type writes it."""
    own = as_dict(getattr(app, "size", None))
    if own is not None and all(isinstance(own.get(k), (int, float)) for k in ("w", "d", "h")):
        return {k: float(own[k]) for k in ("w", "d", "h")}
    k = app.numeric_dimensions()
    if app.type == "fridge" and len(k) >= 3:
        return {"w": k[0], "h": k[1], "d": k[2]}
    if app.type in ("oven", "hood") and len(k) >= 2:
        return {"w": k[0], "h": k[1], "d": k[2] if len(k) >= 3 else 0.0}
    if app.type in ("sink", "cooktop") and len(k) >= 2:
        return {"w": k[0], "d": k[1], "h": k[2] if len(k) >= 3 else 0.0}
    if app.type == "faucet" and k:
        return {"w": 50.0, "d": 220.0, "h": k[0]}
    return None


def dimension_string(m: dict[str, Any]) -> str:
    """``dimensions`` as the 3D builder reads it for that type (fridge w×h×d, oven / hood w×h, sink / hob w×d, tap height)."""
    s = m["size"]
    t = m["type"]
    def f(*xs: float) -> str:
        return " × ".join(f"{x:g}" for x in xs)
    if t == "fridge":
        return f(s["w"], s["h"], s["d"])
    if t in ("oven", "hood"):
        return f(s["w"], s["h"])
    if t in ("sink", "cooktop"):
        return f(s["w"], s["d"])
    if t == "faucet":
        return f"cao {s['h']:g}"
    return f(s["w"], s["d"], s["h"])


def changes_for(m: dict[str, Any]) -> dict[str, Any]:
    """What ``update-appliance`` writes on the appliance for model ``m``."""
    out: dict[str, Any] = {"model": m["id"], "name": m["name"], "dimensions": dimension_string(m), "size": dict(m["size"]),
                           "mount": m.get("mount"), "energy": m.get("energy")}
    out["cutout"] = dict(m["cutout"]) if m.get("cutout") else None
    return out


def kind_of(m: dict[str, Any] | None) -> str:
    """The kind of a model inside its type, which decides the cabinets around it: a hood ``insert`` (in a wall cabinet), ``chimney`` (on
    the wall over the hob) or ``island`` (from the ceiling); a fridge ``freestanding`` (in an open niche) or ``integrated`` (behind doors)."""
    if not m:
        return ""
    if m["type"] == "hood":
        return "island" if "island" in m["id"] else "chimney" if m.get("mount") == "wall" else "insert"
    if m["type"] == "fridge":
        return "integrated" if m.get("mount") == "built_in" else "freestanding"
    return ""


def host(spec: KitchenSpec, app: Appliance) -> Module | None:
    """The cabinet the appliance stands in or on (the module at its place on the worktop for a sink, hob or tap)."""
    if app.type in ("sink", "cooktop", "faucet"):
        at = spot(spec, app)
        if at is not None and at.module:
            return next((m for m in spec.module if m.id == at.module), None)
        if at is not None:                    # given by wall + centre (designs by wall rows): the base cabinet of that row under the centre
            return next((m for m in spec.module if m.storey == "base" and row_of(m) == at.row and m.fromCorner - 1 <= at.center <= m.endAt + 1), None)
    return next((m for m in spec.module if m.id == app.module), None) if app.module else None


def cannot(reason: str) -> bool:
    """Is this line of ``changes_cabinets`` a reason the change cannot be made?"""
    return key_of(reason).startswith("reason.cannot.")


def fit(spec: KitchenSpec, app: Appliance, m: dict[str, Any], catalog: Catalog = builtin.CATALOG) -> tuple[str, list[Said]]:
    """``(status, reasons)`` for model ``m`` in the place of ``app``: ``ok``, ``bad`` (does not fit), ``check`` (could not be checked, or
    another kind of appliance that changes the cabinets around it: say what happens), ``blocked`` (another kind that cannot go there)."""
    if m["type"] != app.type:
        return "bad", [said("reason.model-wrong-type", model=m['name'], type=said(f"appliance.type.{m['type']}"), want=said(f"appliance.type.{app.type}"))]
    h = host(spec, app)
    now = kind_of(models(catalog).get(model_id(app, catalog) or ""))
    if kind_of(m) != now and app.type in ("hood", "fridge"):
        around = changes_cabinets(spec, app, m, h, catalog)
        if around is None:
            return "bad", [said("reason.no-host-for-change")]
        bad = [r for r in around if cannot(r)]
        return ("blocked", bad) if bad else ("check", around)
    if h is None:
        return ("ok", []) if app.type == "faucet" else ("check", [said("reason.no-host")])
    d = defaults.of(catalog)
    reasons: list[Said] = []
    s = m["size"]
    if app.type in ("sink", "cooktop"):
        hole = m.get("cutout")
        if not hole:
            return "check", [said("reason.no-cutout")]
        inner = h.width - 2 * d.side
        if hole["w"] > inner:
            reasons.append(said("reason.cutout-wide", w=hole['w'], id=h.id, inner=inner, need=hole['w'] + 2 * d.side))
        top = h.depth + spec.common.countertopOverhang
        if hole["d"] + 2 * d.worktop_edge > top:
            reasons.append(said("reason.cutout-deep", d=hole['d'], edge=d.worktop_edge, top=top))
    elif app.type == "hood":
        if kind_of(m) == "insert" and s["w"] + 2 * d.hood_side > h.width:
            reasons.append(said("reason.hood-not-inside", w=s['w'], id=h.id, width=h.width))
        hob = next((a for a in spec.appliances if a.type == "cooktop" and (hm := host(spec, a)) is not None and hm.run == h.run
                    and hm.fromCorner < h.endAt and h.fromCorner < hm.endAt), None)
        hob_size = size_of(hob) if hob is not None else None
        if hob_size and s["w"] < hob_size["w"]:
            reasons.append(said("reason.hood-narrow", w=s['w'], cooktop=hob_size['w']))
            return ("bad" if any(key_of(r) == "reason.hood-not-inside" for r in reasons) else "check"), reasons
    elif app.type == "fridge":
        niche = m.get("niche") or {"w": s["w"] + 20, "h": s["h"] + 20}
        if kind_of(m) == "integrated":
            niche = {**niche, "h": 0.0}           # behind full-height doors: no open niche to fit in
        if niche["w"] > h.width - 2 * d.side:
            reasons.append(said("reason.niche-wide", w=niche['w'], id=h.id, has=h.width - 2 * d.side))
        if h.niche and niche["h"] > h.niche:
            reasons.append(said("reason.niche-high", h=niche['h'], id=h.id, has=h.niche))
    elif app.type == "oven":
        niche = m.get("niche") or {"w": s["w"] - 35, "h": s["h"]}
        if niche["w"] > h.width - 2 * d.side:
            reasons.append(said("reason.niche-wide", w=niche['w'], id=h.id, has=h.width - 2 * d.side))
        if niche["h"] > h.height:
            reasons.append(said("reason.niche-high", h=niche['h'], id=h.id, has=h.height))
    return ("bad", reasons) if reasons else ("ok", [])


def changes_cabinets(spec: KitchenSpec, app: Appliance, m: dict[str, Any], h: Module | None,
                     catalog: Catalog = builtin.CATALOG) -> list[Said] | None:
    """What changing ``app`` to a model of another kind does to the cabinets around it (shown in the popup, "check"), or why it cannot
    (lines whose key starts ``reason.cannot.``: see ``cannot``). None when the appliance's cabinet is not found."""
    if h is None:
        return None
    to = kind_of(m)
    if app.type == "hood":
        if to == "insert":
            if h.storey != "base":
                return [said("reason.cannot.in-wall-cabinet", id=app.id)]
            if not h.run and h.wall == "island":
                return [said("reason.cannot.island")]
            busy = [x.id for x in spec.module if x.storey in ("upper", "loft") and over(x, h)]
            if busy:
                return [said("reason.cannot.cabinets-over-cooktop", ids=', '.join(busy))]
            return [said("reason.hood-cabinet-built", id=h.id)]
        hob = h if h.storey == "base" else next((x for x in spec.module if x.storey == "base" and over(h, x)), None)
        if hob is None:
            return [said("reason.cannot.no-cooktop-cabinet")]
        out = [said("reason.hood-hangs-island" if to == "island" else "reason.hood-hangs-wall", id=hob.id)]
        if h.storey != "base":
            above = [x.id for x in spec.module if x.type == "upper-loft" and over(x, h)]
            out.append(said("reason.hood-cabinet-removed-with", id=h.id, above=', '.join(above)) if above else said("reason.hood-cabinet-removed", id=h.id))
        return out
    if app.type == "fridge":
        need = needed_width(m, catalog) or 0.0
        if h.width < need:
            return [said("reason.cannot.fridge-narrow", id=h.id, width=h.width, need=need)]
        if to == "integrated":
            return [said("reason.fridge-behind-doors", id=h.id)]
        niche = (m.get("niche") or {"h": m["size"]["h"] + 20})["h"]
        return [said("reason.fridge-open-niche", id=h.id, h=niche)]
    return []


def over(a: Module, b: Module) -> bool:
    """Do the two cabinets share some length of the same row (one above the other)?"""
    same = (a.run == b.run) if (a.run or b.run) else (a.wall == b.wall and (a.offset, a.facing) == (b.offset, b.facing))
    return same and a.fromCorner < b.endAt - 1 and b.fromCorner < a.endAt - 1


def needed_width(m: dict[str, Any], catalog: Catalog = builtin.CATALOG) -> float | None:
    """The narrowest cabinet model ``m`` fits in (10 mm steps): the hole / niche plus both side panels, at least its ``fits.hostWidth``."""
    hole = m.get("cutout") or m.get("niche")
    if not hole:
        return None
    need = max(hole["w"] + 2 * defaults.of(catalog).side, float(m.get("fits", {}).get("hostWidth") or 0))
    return float(-(-need // 10) * 10)


WISHES: tuple[tuple[str, Callable[[dict[str, Any]], bool]], ...] = (       # dictionary entry ``wish.<id>`` (the words, lower case WITH diacritics) -> what the model must have
    ("induction", lambda m: m.get("energy") == "induction"),
    ("gas", lambda m: m.get("energy") in ("gas", "mixed")),
    ("mixed", lambda m: m.get("energy") == "mixed"),
    ("double", lambda m: m.get("box", {}).get("basins") == 2 or m.get("box", {}).get("zones") == 2 or m.get("box", {}).get("doors") == 2),
    ("single", lambda m: m.get("box", {}).get("basins") == 1 or m.get("box", {}).get("doors") == 1),
    ("granite", lambda m: "granite" in m["visual"].get("finish", "")),
    ("black", lambda m: "black" in m["visual"].get("finish", "")),
    ("pull", lambda m: "pull" in m["prompt"]),
    ("side-by-side", lambda m: m.get("box", {}).get("doors") == "sbs"),
    ("microwave", lambda m: m.get("box", {}).get("kind") == "microwave"),
)


def candidates(spec: KitchenSpec, app: Appliance, text: str = "", catalog: Catalog = builtin.CATALOG) -> list[dict[str, Any]]:
    """The models that could take ``app``'s place, as the popup lists them: same type, filtered by what the sentence asks for (gas / từ,
    đôi / đơn, đen, granite, rút dây, side-by-side, vi sóng); its current model is left out. Each: ``{id, name, size, cutout, mount, energy,
    status, reasons}``, models that fit first. A sentence that filters everything out gives every model of the type."""
    said = unicodedata.normalize("NFC", (text or "").lower())
    wanted = [test for wish, test in WISHES if lexicon.pattern(f"wish.{wish}", catalog).search(said)]
    now = model_id(app, catalog)
    same = [m for m in models(catalog).values() if m["type"] == app.type and m["id"] != now]
    picked = [m for m in same if all(w(m) for w in wanted)] or same
    out: list[dict[str, Any]] = []
    for m in picked:
        status, reasons = fit(spec, app, m, catalog)
        out.append({"id": m["id"], "name": m["name"], "size": m["size"], "cutout": m.get("cutout"), "mount": m.get("mount"),
                    "energy": m.get("energy"), "status": status, "reasons": reasons})
    order = {"ok": 0, "check": 1, "bad": 2, "later": 3}
    return sorted(out, key=lambda c: order[c["status"]])


def energy_notes(app: Appliance, m: dict[str, Any], catalog: Catalog = builtin.CATALOG) -> list[Said]:
    """Warnings when the new model needs another supply (gas line, dedicated socket)."""
    before = getattr(app, "energy", None) or (models(catalog).get(model_id(app, catalog) or "", {}).get("energy"))
    after = m.get("energy")
    if before == after or app.type != "cooktop":
        return []
    out: list[Said] = []
    if after in ("gas", "mixed") and before not in ("gas", "mixed"):
        out.append(said("reason.needs-gas"))
    if before in ("gas", "mixed") and after not in ("gas", "mixed"):
        out.append(said("reason.gas-unused"))
    if after in ("induction", "mixed") and before not in ("induction", "mixed"):
        out.append(said("reason.needs-circuit"))
    return out


# ---- what the image AI needs (plan, decision A5)

def where(spec: KitchenSpec, app: Appliance, catalog: Catalog = builtin.CATALOG) -> str:
    h = host(spec, app)
    kind = kind_of(models(catalog).get(model_id(app, catalog) or ""))
    if app.type == "hood" and h is not None and h.storey == "base":
        return f"{'hanging from the ceiling' if kind == 'island' else 'on the wall, with its chimney,'} over the hob of {h.id} ({h.name or h.type})"
    if app.type == "fridge" and h is not None and kind == "integrated":
        return f"hidden behind the full-height doors of {h.id} ({h.name or h.type})"
    place = {"cooktop": "built into the worktop above", "sink": "set into the worktop above", "faucet": "on the worktop behind the sink above",
             "hood": "inside the wall cabinet", "fridge": "in the tall cabinet", "oven": "built into the cabinet",
             "tv": "on the wall above the TV console"}.get(app.type, "in")
    return f"{place} {h.id} ({h.name or h.type})" if h is not None else "at its place in the kitchen"


def ai_facts(spec: KitchenSpec, app: Appliance, rendering: str = "box-placeholder", catalog: Catalog = builtin.CATALOG) -> dict[str, Any]:
    """Everything the image AI must know about one appliance. ``rendering``: ``box-placeholder`` (the 3D shows a plain box: every visual fact
    goes in, with a note that the box is a stand-in) or ``model-3d`` (a real model is drawn: only what a picture cannot show goes in)."""
    mid = model_id(app, catalog)
    m = models(catalog).get(mid or "", {})
    size = size_of(app) or m.get("size")
    visual = m.get("visual", {})
    unseen = ["energy", "size", "mount"] + ([*visual.get("features", {})] + ["finish"] if rendering == "box-placeholder" else [])
    out: dict[str, Any] = {"id": app.id, "type": app.type, "model": mid, "name": app.name or m.get("name"), "rendering": rendering,
                           "where": where(spec, app, catalog), "size_mm": size, "mount": getattr(app, "mount", None) or m.get("mount"),
                           "energy": getattr(app, "energy", None) or m.get("energy"), "visual": visual,
                           "prompt": m.get("prompt") or app.name or app.type, "notShownInInputImage": unseen}
    if (getattr(app, "cutout", None) or m.get("cutout")) and app.type in ("sink", "cooktop"):
        out["cutout_mm"] = getattr(app, "cutout", None) or m.get("cutout")
    if rendering == "box-placeholder":
        out["placeholderNote"] = (f"The plain box {where(spec, app, catalog)} is only a stand-in: draw it as {out['prompt']}, at the same place and size.")
    return out


def sentence(facts: dict[str, Any], bbox: list[float] | None = None) -> str:
    """One sentence for a prompt: what to draw, how big, and where (``bbox``: x0, y0, x1, y1 of it in the picture)."""
    s: dict[str, Any] = facts.get("size_mm") or {}
    size = f", about {s['w']:g} mm wide" if s.get("w") else ""
    at = f" (in the picture around x {bbox[0]}–{bbox[2]}, y {bbox[1]}–{bbox[3]})" if bbox else ""
    if facts.get("rendering") == "box-placeholder":
        return f"The plain box {facts['where']}{at} is only a stand-in: draw it as {facts['prompt']}{size}, at the same place."
    return f"The {facts['type']} {facts['where']}{at} is {facts['prompt']}{size}."


def check(spec: KitchenSpec, catalog: Catalog = builtin.CATALOG) -> list[dict[str, Any]]:
    """Rule issues for appliances that carry a model (designs without models are not checked here, so old designs show nothing new):
    ``APPLIANCE-MODEL-FIT`` (the model does not fit its cabinet: hole, niche, hood width — error; could not be checked — warning) and
    ``HOOD-WIDTH`` (a hood narrower than the hob below it — warning)."""
    issues: list[dict[str, Any]] = []
    by_id = models(catalog)
    for app in spec.appliances:
        mid = getattr(app, "model", None)
        if not (isinstance(mid, str) and mid in by_id):
            continue
        status, reasons = fit(spec, app, by_id[mid], catalog)
        h = host(spec, app)
        mods = [app.id, *([h.id] if h is not None else [])]
        if status == "bad":
            issues.extend(words.finding("APPLIANCE-MODEL-FIT", "error", mods, "finding.model-fit-named", id=app.id, model=by_id[mid]['name'], reason=r)
                          for r in reasons if key_of(r) != "reason.hood-narrow")
        if status == "check":
            issues.extend(words.finding("APPLIANCE-MODEL-FIT", "warning", mods, "finding.model-fit", id=app.id, reason=r)
                          for r in reasons if key_of(r) != "reason.hood-narrow")
    for hood in (a for a in spec.appliances if a.type == "hood"):
        hm = host(spec, hood)
        if hm is None:
            continue
        for hob in (a for a in spec.appliances if a.type == "cooktop"):
            bm = host(spec, hob)
            if bm is None or bm.run != hm.run or not (bm.fromCorner < hm.endAt and hm.fromCorner < bm.endAt):
                continue
            if not (getattr(hood, "model", None) or getattr(hob, "model", None)):
                continue                                           # an old design: as it was
            a, b = size_of(hood), size_of(hob)
            if a and b and a["w"] < b["w"]:
                issues.append({**words.finding("HOOD-WIDTH", "warning", [hood.id, hob.id], "finding.hood-narrow", hood=hood.id, hood_w=a["w"],
                                               cooktop=hob.id, cooktop_w=b["w"]), "measured": a["w"], "limit": [b["w"], None]})
    return issues
