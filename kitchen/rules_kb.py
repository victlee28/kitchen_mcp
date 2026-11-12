"""Bộ kiểm tra theo CHỦ ĐỀ, tham số lấy từ kho tri thức theo khu vực/quốc gia.

Với mỗi chủ đề (vd "hut-mui"), chọn đúng MỘT mục tri thức ưu tiên nhất cho quốc gia của thiết kế
(xem kitchen/regions.py), rồi kiểm theo `params` của mục đó. Issue ghi mã mục đã dùng, mức ưu tiên
và mức độ suy từ loại nguồn (bắt buộc -> error, tiêu chuẩn/khuyến nghị -> warning, thực hành -> info).
Nếu chỉ có tiêu chuẩn nước khác thì vẫn kiểm nhưng hạ xuống info và đánh dấu "thamKhao".
"""
from __future__ import annotations

from typing import Any

import math
from collections.abc import Iterable

from .numeric import round_half_away, round_int
from . import builtin, defaults, regions, runs, words
from .catalog import Catalog
from .jsonview import as_dict, as_list
from .spec import KitchenSpec, Appliance

TOPICS = tuple(builtin.CATALOG.ids("rule-topic"))   # the topics checked here (catalog kind rule-topic: names there)


def select(rows: list[dict[str, Any]], country: str | None, region: str | None, catalog: Catalog = builtin.CATALOG) -> dict[str, dict[str, Any]]:
    """rows: các mục tri thức (đã parse metadata). Trả {chủ đề: {code, params, mucDo, uuTien, thamKhao}}. Chủ đề: catalog kind ``rule-topic``
    (xưởng ẩn một chủ đề = bỏ kiểm chủ đề đó); mức độ theo loại nguồn: kind ``source-type``."""
    out: dict[str, dict[str, Any]] = {}
    topics = set(catalog.ids("rule-topic"))
    severity = regions.tables(catalog).severity
    for r in regions.sort_rows(rows, country, region, catalog):
        meta = as_dict(r.get("metadata")) or {}
        for topic in as_list(meta.get("validation")) or []:
            if topic in out or topic not in topics:
                continue
            score = regions.priority_score(r, country, region)
            level = severity.get(meta.get("sourceType", "unknown"), "warning")
            reference = score < 10  # tiêu chuẩn của nước khác (hoặc chưa chọn quốc gia): chỉ tham khảo -> info
            priority_text = regions.priority_label(score) if (country or region) or score >= 10 else words.said("priority.no-country")
            out[topic] = {"code": r["code"], "params": meta.get("params") or {}, "severity": "info" if reference else level,
                          "priority": priority_text, "reference": reference,
                          "zone": f"{r.get('region') or 'GLOBAL'}{'/' + r['country'] if r.get('country') else ''}"}
    return out


class _Ctx:
    def __init__(self, spec: KitchenSpec, sel: dict[str, dict[str, Any]]):
        self.spec, self.sel = spec, sel
        self.out: list[dict[str, Any]] = []

    def p(self, topic: str) -> dict[str, Any] | None:
        s = self.sel.get(topic)
        return s["params"] if s else None

    def add(self, topic: str, mods: Iterable[str], key: str, params: dict[str, Any], measured: Any = None, limit: Any = None) -> None:
        s = self.sel[topic]
        d: dict[str, Any] = {**words.finding(s["code"], s["severity"], list(mods), key, **params), "topic": topic,
                             "theo": words.said("finding.by", zone=s['zone'], priority=s['priority'])}
        if s["reference"]:
            d["reference"] = True
        if measured is not None:
            d["measured"] = round_half_away(measured, 1) if isinstance(measured, float) else measured
        if limit is not None:
            d["limit"] = limit
        self.out.append(d)


def _runs(spec: KitchenSpec, row: str) -> list[tuple[float, float]]:
    """Continuous stretches of base cabinets (worktop) in a row: a wall's row or an explicit run (``runs.row_of``)."""
    ms = sorted((m for m in spec.module if runs.row_of(m) == row and m.storey == "base"), key=lambda m: m.fromCorner)
    out: list[list[float]] = []
    for m in ms:
        if out and m.fromCorner <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], m.endAt)
        else:
            out.append([m.fromCorner, m.endAt])
    return [(a, b) for a, b in out]


def _span(tb: Appliance, center: float) -> tuple[float, float]:
    w = (tb.numeric_dimensions() or [0])[0]
    return center - w / 2, center + w / 2


def _landing(spec: KitchenSpec, tb: Appliance, spots: "dict[str, runs.Spot]") -> tuple[float, float] | None:
    me = spots[tb.id]
    s0, s1 = _span(tb, me.center)
    run = next(((a, b) for a, b in _runs(spec, me.row) if a - 1 <= s0 and s1 <= b + 1), None)
    if not run:
        return None
    left, right = run
    for o in spec.appliances:
        at = spots.get(o.id)
        if o is tb or at is None or at.row != me.row or o.type not in ("sink", "cooktop"):
            continue
        o0, o1 = _span(o, at.center)
        if o1 <= s0:
            left = max(left, o1)
        elif o0 >= s1:
            right = min(right, o0)
    return s0 - left, right - s1


def _plan_point(spec: KitchenSpec, row: str, s: float, d: float) -> tuple[float, float]:
    """Plan position (x, z) of the point (s, d) of a row, in the kitchen frame."""
    if row.startswith("run:"):
        fr = runs.frames(spec).get(row[4:])
        if fr is not None:
            return fr.to_world(s, d)
    lsau = (spec.room.length("back") if spec.room else None) or max([m.endAt for m in spec.module if m.wall == "back"] + [0]) + 600
    seat = runs.wall_seat(row, lsau) or runs.wall_seat("left", lsau)
    assert seat is not None
    return seat.to_world(s, d)


def _range(ctx: _Ctx, topic: str, value: float, lo_key: str | None, hi_key: str | None, label: str, mods: Iterable[str] = ()) -> None:
    """``label``: the key of what is measured (``finding.label.<...>`` in data/i18n)."""
    p = ctx.p(topic)
    if not p:
        return
    openings = p.get(lo_key) if lo_key is not None else None
    hi = p.get(hi_key) if hi_key is not None else None
    if (openings is not None and value < openings - 1) or (hi is not None and value > hi + 1):
        lim = f"{openings if openings is not None else '…'}–{hi if hi is not None else '…'}"
        ctx.add(topic, mods, "finding.out-of-range", {"what": words.say(label), "value": value, "range": lim}, value, [openings, hi])


def check(spec: KitchenSpec, sel: dict[str, dict[str, Any]], catalog: Catalog = builtin.CATALOG) -> list[dict[str, Any]]:
    c = spec.common
    ctx = _Ctx(spec, sel)
    spots = {t.id: at for t in spec.appliances if t.type in ("sink", "cooktop") and (at := runs.spot(spec, t)) is not None}   # where each stands, by row
    sink = [t for t in spec.appliances if t.type == "sink" and t.id in spots]
    cooktop = [t for t in spec.appliances if t.type == "cooktop" and t.id in spots]
    fridge = [t for t in spec.appliances if t.type == "fridge" and t.module]
    lows = [m for m in spec.module if m.storey == "base"]
    ups = [m for m in spec.module if m.storey in ("upper", "loft")]

    # kích thước
    if (p := ctx.p("countertop-height")):
        _range(ctx, "countertop-height", c.countertop, "countertop_min", "countertop_max", "finding.label.countertop-height")
        allowed = p.get("countertop_allowed")
        if allowed and all(abs(c.countertop - a) > 1 for a in allowed) and p.get("countertop_min", 0) - 1 <= c.countertop <= p.get("countertop_max", 1e9) + 1:
            ctx.add("countertop-height", [], "finding.countertop-not-allowed", {"value": c.countertop, "allowed": str(allowed)}, c.countertop, allowed)
    if (p := ctx.p("base-depth")):
        bad = [m.id for m in lows if not p.get("baseDepth_min", 0) - 1 <= m.depth <= p.get("baseDepth_max", 1e9) + 1]
        if bad:
            ctx.add("base-depth", bad, "finding.base-depth", {"min": p.get('baseDepth_min'), "max": p.get('baseDepth_max')},
                    sorted({spec.find(b).depth for b in bad}), [p.get("baseDepth_min"), p.get("baseDepth_max")])
    if (p := ctx.p("countertop-depth")) and lows:
        d = max(m.depth for m in lows) + c.countertopOverhang
        if d < p.get("countertopDepth_min", 0) - 1:
            ctx.add("countertop-depth", [], "finding.countertop-depth", {"depth": d, "min": p['countertopDepth_min']}, d, p["countertopDepth_min"])
    if (p := ctx.p("upper-depth")):
        bad = [m.id for m in ups if not p.get("upperDepth_min", 0) - 1 <= m.depth <= p.get("upperDepth_max", 1e9) + 1]
        if bad:
            ctx.add("upper-depth", bad, "finding.upper-depth", {"min": p.get('upperDepth_min'), "max": p.get('upperDepth_max')},
                    sorted({spec.find(b).depth for b in bad}), [p.get("upperDepth_min"), p.get("upperDepth_max")])
    if ups:
        _range(ctx, "upper-gap", c.upperBottom - c.countertop, "upper_gap_min", "upper_gap_max", "finding.label.upper-gap")
    if lows:
        _range(ctx, "cabinet-plinth", c.plinthHeight, "plinthHeight_min", "plinthHeight_max", "finding.label.plinth")
    _range(ctx, "clear-height", c.ceiling, "ceiling_min", None, "finding.label.clear-height")

    # chậu – bếp
    if (p := ctx.p("sink-cooktop")):
        for a in sink:
            for b in cooktop:
                if spots[a.id].row == spots[b.id].row:
                    gap = abs(spots[a.id].center - spots[b.id].center) - (a.numeric_dimensions() or [0])[0] / 2 - (b.numeric_dimensions() or [0])[0] / 2
                    if gap < p["sink_cooktop_min"] - 1:
                        ctx.add("sink-cooktop", [a.id, b.id], "finding.sink-cooktop", {"sink": a.id, "cooktop": b.id, "gap": gap, "min": p['sink_cooktop_min']}, gap, p["sink_cooktop_min"])
    # mặt bàn thao tác
    for topic, items, name in (("sink-table", sink, "finding.label.sink"), ("cooktop-table", cooktop, "finding.label.cooktop")):
        if (p := ctx.p(topic)):
            for t in items:
                sides = _landing(spec, t, spots)
                if not sides:
                    continue
                a, b = sorted(sides, reverse=True)
                if a < p["larger_side"] - 1 or b < p["smaller_side"] - 1:
                    ctx.add(topic, [t.id], "finding.landing", {"what": words.say(name), "id": t.id, "a": sides[0], "b": sides[1],
                                                 "larger": p['larger_side'], "smaller": p['smaller_side']}, [round_int(sides[0]), round_int(sides[1])],
                            [p["larger_side"], p["smaller_side"]])
    if (p := ctx.p("fridge-table")):
        for t in fridge:
            try:
                m = spec.find(t.module or "")
            except KeyError:
                continue
            best = 0.0
            for a, b in _runs(spec, runs.row_of(m)):
                if abs(a - m.endAt) <= 1 or abs(b - m.fromCorner) <= 1:
                    near_start = abs(a - m.endAt) <= 1
                    free = b - a
                    for o in spec.appliances:
                        if (at := spots.get(o.id)) is not None and at.row == runs.row_of(m):
                            o0, o1 = _span(o, at.center)
                            if a - 1 <= o0 and o1 <= b + 1:
                                free = min(free, (o0 - a) if near_start else (b - o1))
                    best = max(best, free)
            if best < p["floor_min"] - 1:
                ctx.add("fridge-table", [m.id, t.id], "finding.fridge-landing", {"id": t.id, "free": best, "min": p['floor_min']},
                        best, p["floor_min"])
    # phía trên bếp
    hood = {t.module: t for t in spec.appliances if t.type == "hood" and t.module}
    for t in cooktop:
        s0, s1 = _span(t, spots[t.id].center)
        above = [m for m in ups if runs.row_of(m) == spots[t.id].row and m.fromCorner < s1 and m.endAt > s0]
        if not above:
            continue
        direct = [m for m in above if m.fromCorner <= spots[t.id].center < m.endAt]
        lowest = min(direct or above, key=lambda m: m.y)
        if lowest.id in hood and (p := ctx.p("hood")):
            h = (hood[lowest.id].numeric_dimensions() + [0, 0])[1]
            gap = lowest.y - h - c.countertop
            if gap < p["gap_min"] - 1:
                ctx.add("hood", [lowest.id, t.id, hood[lowest.id].id], "finding.hood-gap", {"gap": gap, "min": p['gap_min']},
                        gap, p["gap_min"])
        elif lowest.id not in hood and (p := ctx.p("above-cooktop")):
            gap = lowest.y - c.countertop
            if gap < p["no_hood_min"] - 1:
                ctx.add("above-cooktop", [lowest.id, t.id], "finding.above-cooktop", {"id": lowest.id, "cooktop": t.id, "gap": gap, "min": p['no_hood_min']},
                        gap, p["no_hood_min"])
    # lò vi sóng
    if (p := ctx.p("microwave")):
        from .geometry import compile_spec
        parts = None
        for t in spec.appliances:
            if t.type != "oven" or not t.module:
                continue
            parts = parts or compile_spec(spec, catalog).parts
            ps = [x for x in parts if x.module == t.id]
            if ps:
                y0 = ps[0].min[1]
                if y0 < c.baseTop and y0 < p["gap_under_countertop_min"] - 1:
                    ctx.add("microwave", [t.module, t.id], "finding.microwave-low", {"id": t.id, "y": y0, "min": p['gap_under_countertop_min']},
                            y0, p["gap_under_countertop_min"])
                elif y0 > p["bottom_max"] + 1:
                    ctx.add("microwave", [t.module, t.id], "finding.microwave-high", {"id": t.id, "y": y0, "max": p['bottom_max']}, y0, p["bottom_max"])
    # tam giác làm việc
    if (p := ctx.p("triangle")) and sink and cooktop and fridge:
        try:
            m = spec.find(fridge[0].module or "")
            dm = c.baseDepth / 2
            pts = {"sink": _plan_point(spec, spots[sink[0].id].row, spots[sink[0].id].center, dm),
                   "cooktop": _plan_point(spec, spots[cooktop[0].id].row, spots[cooktop[0].id].center, dm),
                   "fridge": _plan_point(spec, runs.row_of(m), m.fromCorner + m.width / 2, m.depth)}
            names = list(pts)
            legs = {f"{a}–{b}": math.dist(pts[a], pts[b]) for i, a in enumerate(names) for b in names[i + 1:]}
            total = sum(legs.values())
            bad = [k for k, v in legs.items() if not p.get("door_min", 0) - 1 <= v <= p.get("door_max", 1e9) + 1]
            if bad or total > p.get("total_max", 1e9) + 1:
                ctx.add("triangle", [sink[0].id, cooktop[0].id, fridge[0].id],
                        "finding.triangle", {"legs": ', '.join(f"{words.say('leg.' + k)} {v:.0f}" for k, v in legs.items()), "total": total,
                                            "min": p.get('door_min', 0), "max": p.get('door_max', '…'), "total_max": p.get('total_max', '…')},
                        {k: round_int(v) for k, v in legs.items()}, {k: p.get(k) for k in ("door_min", "door_max", "total_max")})
        except KeyError:
            pass
    # lối đi
    if (p := ctx.p("walkway")):
        lim = p.get("walkway_min", p.get("walkway_1person"))
        if not spec.room or spec.room.walkway is None:
            s = sel["walkway"]
            ctx.out.append({**words.finding(s["code"], "info", [], "finding.walkway-unknown", min=lim), "topic": "walkway",
                            "theo": words.said("finding.by", zone=s['zone'], priority=s['priority'])})
        elif lim and spec.room.walkway < lim - 1:
            ctx.add("walkway", [], "finding.walkway", {"width": spec.room.walkway, "min": lim}, spec.room.walkway, lim)
    _openings(ctx, spec, catalog)
    return ctx.out


OPENING_TOPICS = ("doorway-width", "doorway-width-accessible", "doorway-height", "doorway-blocked", "door-interference", "cooktop-window", "window-upper")


def _openings(ctx: _Ctx, spec: KitchenSpec, catalog: Catalog) -> None:
    """The checks against the room's doors and windows (``rules_openings``). A cabinet standing in a doorway is always a warning."""
    params = {t: ctx.p(t) or {} for t in OPENING_TOPICS if t in ctx.sel}
    if not params:
        return
    from . import geometry, rules_openings
    found, bodies = geometry.openings_and_bodies(spec, geometry.compile_spec(spec, catalog))
    for f in rules_openings.check(found, bodies, params, defaults.of(catalog).openings):
        ctx.add(f.topic, f.modules, f.key, dict(f.params), f.measured, f.limit)
        if f.topic == "doorway-blocked":                 # always a warning: never an error, never only for reference
            ctx.out[-1]["severity"] = "warning"
            ctx.out[-1].pop("reference", None)

