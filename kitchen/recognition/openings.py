"""Doors and windows a recognizer saw, as ``add-opening`` operations on the design's wall axes (plan R10). Pure (rule R1).

A recognizer gives each opening on a RUN of its ``recognized-runs/1`` (``runs[*].openings``), in the ``ai`` form of
``openings.normalize`` except that ``s`` is the run's own (from the run's left end, seen from in front of the doors)::

    {"id"?, "kind": "door" | "window" | "passage", "axes": [{"s", "confidence"}], "sill"?, "head"?, "hAxes"?: [{"h", "confidence"}],
     "edgesSeen"?: "casing" | "hole", "style"?: "swing" | "sliding" | "folding" | "fixed" | "top-hung" | "none", "leaves"?: n,
     "confidence"?, "unsure"?: ["head"], "note"?}

Once the runs stand on their lines (``run_line.run_lines``), a run ``s`` is a point on the wall face; that point, in the frame of the wall
axes (the room frame of a floorplan design), gives the nearest axis and the ``s`` on it. An opening that overlaps one the design already
has on the same axis is left out (noted); one that ``normalize`` refuses is left out with its reason. Nothing is trusted.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..catalog import Catalog
from ..errors import InvalidInput
from ..jsonview import as_dict, as_list
from ..numeric import round_half_away
from ..openings import normalize
from ..openings.contract import KINDS, Opening
from ..openings.types import casing_width, get, num
from ..openings.normalize import width_range
from ..openings.wall_axes import WallAxis, nearest, opening_pieces
from . import opening_match
from .draft import confidence_of, number

Pt = tuple[float, float]
MAX_OPENINGS = 12
REACH_MM = 600.0            # a run's back line lies on the wall face, half a wall from the axis; farther than this is no wall
OVERLAP = 0.5               # an opening already there covers at least this share of the narrower one: the same opening
STYLES = ("swing", "sliding", "folding", "fixed", "top-hung", "none")
EDGES = ("casing", "hole")


@dataclass(frozen=True)
class SeenOpening:
    run: str
    kind: str
    axes: tuple[tuple[float, float], ...]          # (s on the run, confidence), sorted, outer edges included
    sill: float | None
    head: float | None
    h_axes: tuple[tuple[float, float], ...]        # (height above the floor, confidence)
    edges_seen: str
    style: str
    leaves: int
    confidence: float
    note: str = ""
    transom_panes: int | None = None               # panes of the transom, when the recognizer counted them
    panels: tuple["Panel", ...] | None = None      # every leaf and pane row by row, left to right, when the recognizer said them


@dataclass(frozen=True)
class Panel:
    row: int
    operation: str
    handle: bool
    front: bool


PANEL_OPS = ("swing", "sliding", "folding", "fixed", "top-hung")


def read_detail(obj: Mapping[str, Any]) -> tuple[int | None, tuple[Panel, ...] | None]:
    """``transomPanes`` and ``panels`` of a recognised opening, checked; what is malformed is left out (both are optional)."""
    tp = obj.get("transomPanes")
    panes = tp if isinstance(tp, int) and not isinstance(tp, bool) and 1 <= tp <= 8 else None
    raw = as_list(obj.get("panels"))
    panels: list[Panel] = []
    for p in (as_dict(x) for x in raw or []):
        row, op = (p.get("row", 0), p.get("operation")) if p is not None else (None, None)
        if p is None or not isinstance(row, int) or isinstance(row, bool) or not 0 <= row <= 2 or op not in PANEL_OPS:
            return panes, None
        panels.append(Panel(row, str(op), p.get("handle") is True, p.get("front") is True))
    return panes, (tuple(panels) if raw is not None and panels else None)


def _seen(run: str, value: Any, index: int, rejected: list[dict[str, Any]]) -> SeenOpening | None:
    obj = as_dict(value)

    def reject(reason: str) -> None:
        rejected.append({"run": run, "index": index, "reason": reason})
    if obj is None:
        return reject("not an object") or None
    kind = obj.get("kind")
    if kind not in KINDS:
        return reject(f"kind must be one of {', '.join(KINDS)}") or None
    axes: list[tuple[float, float]] = []
    for a in as_list(obj.get("axes")) or []:
        item = as_dict(a)
        s = number(item.get("s")) if item is not None else None
        if item is None or s is None:
            return reject("axes must be [{s, confidence}]") or None
        axes.append((s, confidence_of(item.get("confidence"))))
    if len(axes) < 2:
        return reject("an opening needs both of its edges") or None
    h_axes: list[tuple[float, float]] = []
    for a in as_list(obj.get("hAxes")) or []:
        item = as_dict(a)
        h = number(item.get("h")) if item is not None else None
        if item is None or h is None:
            return reject("hAxes must be [{h, confidence}]") or None
        h_axes.append((h, confidence_of(item.get("confidence"))))
    sill, head = number(obj.get("sill")), number(obj.get("head"))
    if obj.get("sill") is not None and sill is None or obj.get("head") is not None and head is None:
        return reject("sill and head must be numbers") or None
    leaves = obj.get("leaves", 1)
    style, edges = obj.get("style", "swing"), obj.get("edgesSeen", "casing")
    panes, panels = read_detail(obj)
    return SeenOpening(run, str(kind), tuple(sorted(axes)), sill, head, tuple(sorted(h_axes)), str(edges) if edges in EDGES else "casing",
                       str(style) if style in STYLES else "swing", leaves if isinstance(leaves, int) and not isinstance(leaves, bool) and 0 <= leaves <= 8 else 1,
                       confidence_of(obj.get("confidence")), str(obj.get("note") or "")[:120], panes, panels)


def read(doc: Any) -> tuple[list[SeenOpening], list[dict[str, Any]]]:
    """The openings of a recognised kitchen by runs, checked: ``(openings, rejected)``."""
    found: list[SeenOpening] = []
    rejected: list[dict[str, Any]] = []
    top = as_dict(doc) or {}
    for run in (as_dict(r) for r in as_list(top.get("runs")) or []):
        if run is None or not isinstance(run.get("id"), str):
            continue
        for i, item in enumerate(as_list(run.get("openings")) or []):
            if len(found) >= MAX_OPENINGS:
                rejected.append({"run": run["id"], "index": i, "reason": f"more than {MAX_OPENINGS} openings"})
                continue
            got = _seen(run["id"], item, i, rejected)
            if got is not None:
                found.append(got)
    return found, rejected


def flat_to_runs(openings: Any, lengths: Mapping[str, float]) -> dict[str, list[dict[str, Any]]]:
    """Openings of a flat draft (``wall`` + ``axes: [{fromCorner, confidence}]``, measured from the end the draft's ``fromCorner`` uses) ->
    the ``openings`` of the runs ``runs_from_draft`` makes: the back and left runs are mirrored like their cabinets (``s = length - d``)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for raw in as_list(openings) or []:
        o = as_dict(raw)
        if o is None or o.get("wall") not in lengths:
            continue
        wall = str(o["wall"])
        length = float(lengths[wall])
        axes: list[dict[str, Any]] = []
        for a in as_list(o.get("axes")) or []:
            item = as_dict(a) or {}
            d = number(item.get("fromCorner"))
            if d is not None:
                axes.append({"s": d if wall == "right" else length - d, "confidence": item.get("confidence", o.get("confidence"))})
        out.setdefault(wall, []).append({**{k: v for k, v in o.items() if k not in ("wall", "axes")}, "axes": axes})
    return out


def _panel_features(panels: tuple[Panel, ...] | None) -> tuple[tuple[int, ...] | None, tuple[int, ...] | None]:
    """``(handles, fronts)``: the leaves (indices of the main row, left to right, as a type numbers its leaves) with a handle and on the
    front rail; None when the panels were not said."""
    if panels is None:
        return None, None
    main = [p for p in panels if p.row == 0]
    fronts = tuple(i for i, p in enumerate(main) if p.front)
    return tuple(i for i, p in enumerate(main) if p.handle), (fronts if fronts else None)


def features_of(seen: SeenOpening) -> opening_match.Features:
    """The features of an opening seen on a run: its middle dividers as fractions of its width."""
    ss = [s for s, _ in seen.axes]
    wide = ss[-1] - ss[0] if len(ss) >= 2 else 0.0
    ratios = tuple((s - ss[0]) / wide for s in ss[1:-1]) if wide > 0 else None
    return opening_match.seen_features(seen.kind, seen.style, seen.leaves, bool(seen.h_axes), ratios, seen.transom_panes,
                                       *_panel_features(seen.panels))


def opening_type(seen: SeenOpening, catalog: Catalog) -> str:
    """The catalog type that fits what was seen best (``opening_match``): no rule per type, so a type the workshop adds is found too."""
    found = opening_match.best(features_of(seen), catalog)
    if found is None:
        raise InvalidInput(f"The catalog has no {seen.kind} type", code="opening-type-missing", params={"kind": seen.kind})
    return found.type_id


def _start_and_dir(line: Any) -> tuple[Pt, Pt]:
    """Where a run's ``s`` = 0 lies on its line and the direction ``s`` grows (see ``run_line.run_frame``)."""
    nx, nz = line.normal
    ux, uz = nz, -nx
    a, b = line.a, line.b
    return ((a, (ux, uz)) if (b[0] - a[0]) * ux + (b[1] - a[1]) * uz >= 0 else (b, (ux, uz)))


def _r(v: float) -> float:
    return float(round_half_away(v, 1))


def _overlaps(c: float, w: float, other: Opening) -> bool:
    lo, hi = max(c - w / 2, other.center - other.width / 2), min(c + w / 2, other.center + other.width / 2)
    return hi - lo >= OVERLAP * min(w, other.width)


def operations(seen: Sequence[SeenOpening], lines: Mapping[str, Any], axes: Sequence[WallAxis], to_axes: Callable[[float, float], Pt],
               existing: Sequence[Opening], catalog: Catalog, country: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """``(add-opening operations, notes)``. ``lines``: run id -> the ``run_line.Line`` it stands on (kitchen frame); ``to_axes``: kitchen
    frame -> the axes' frame; ``existing``: the design's openings (``openings.effective``)."""
    ops: list[dict[str, Any]] = []
    notes: list[str] = []
    taken: list[Opening] = list(existing)
    for o in seen:
        line = lines.get(o.run)
        if line is None:
            notes.append(f"opening-not-placed: the {o.run} run was not placed, so its {o.kind} was left out.")
            continue
        (sx, sz), (ux, uz) = _start_and_dir(line)
        pts = [to_axes(sx + ux * s, sz + uz * s) for s, _ in o.axes]
        mid = ((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2)
        near = nearest(mid, axes, REACH_MM)
        if near is None:
            notes.append(f"opening-not-placed: no wall behind the {o.kind} seen on the {o.run} run.")
            continue
        axis = near[0]
        found = opening_match.best(features_of(o), catalog)
        if found is None:
            notes.append(f"opening-not-placed: the catalog has no {o.kind} type.")
            continue
        notes += opening_match.note(found)
        raw: dict[str, Any] = {"kind": o.kind, "openingType": found.type_id, "source": "ai", "wallAxis": axis.ref().to_data(),
                               "axes": [{"s": _r(axis.s_of(p)), "confidence": c} for p, (_, c) in zip(pts, o.axes)], "edgesSeen": o.edges_seen}
        if o.sill is not None:
            raw["sill"] = o.sill
        if o.head is not None:
            raw["head"] = o.head
        if o.h_axes:
            raw["hAxes"] = [{"h": h, "confidence": c} for h, c in o.h_axes]
        if o.confidence < 0.5:
            raw["unsure"] = ["center"]
        try:
            got, _ = normalize(raw, "ai", catalog, axes, country)
        except InvalidInput as first:
            if len(raw["axes"]) <= 2 and "hAxes" not in raw:
                notes.append(f"opening-not-placed: {o.kind} on the {o.run} run: {first}")
                continue
            raw["axes"] = sorted(raw["axes"], key=lambda a: a["s"])
            raw["axes"] = [raw["axes"][0], raw["axes"][-1]]     # the middle axes did not fit the type: keep its template
            raw.pop("hAxes", None)
            try:
                got, _ = normalize(raw, "ai", catalog, axes, country)
            except InvalidInput as error:
                notes.append(f"opening-not-placed: {o.kind} on the {o.run} run: {error}")
                continue
            notes.append(f"opening-axes-dropped: the dividers seen in the {o.kind} on the {o.run} run do not fit {raw['openingType']}.")
        same = next((x for x in taken if x.wall_axis.id == got.wall_axis.id and not x.removed and _overlaps(got.center, got.width, x)), None)
        if same is not None:
            notes.append(f"opening-already-there: the {o.kind} seen on the {o.run} run is {same.id}; left as it is.")
            continue
        taken.append(got)
        ops.append({"op": "add-opening", "opening": raw})
    return ops, notes


# ---------------- a photo with no cabinets: a door or window as ratios, placed where the user clicked ----------------

PHOTO_WIDTH_STEP = 50.0
PHOTO_SNAP_MM = 60.0         # a width this close to a standard one of the country takes it


@dataclass(frozen=True)
class PhotoOpening:
    kind: str
    style: str
    leaves: int
    edges_seen: str
    aspect: float                         # height / width of what was seen
    axes_ratio: tuple[float, ...]         # middle vertical axes, 0..1 from the left edge
    h_axes_ratio: tuple[float, ...]       # middle horizontal axes, 0..1 from the sill
    confidence: float
    note: str = ""
    transom_panes: int | None = None
    panels: tuple[Panel, ...] | None = None


def _ratios(value: Any) -> tuple[float, ...] | None:
    items = as_list(value) or []
    got = [number(x) for x in items]
    if any(n is None or not 0.0 < n < 1.0 for n in got):
        return None
    return tuple(sorted(float(n) for n in got if n is not None))


def read_photo(doc: Any) -> tuple[list[PhotoOpening], list[dict[str, Any]]]:
    """The openings of a picture with no cabinets (``photoOpenings`` of the recognizer's answer, or of a flat draft), checked."""
    found: list[PhotoOpening] = []
    rejected: list[dict[str, Any]] = []
    for i, item in enumerate((as_list((as_dict(doc) or {}).get("photoOpenings")) or [])[:MAX_OPENINGS]):
        o = as_dict(item)
        aspect = number(o.get("aspect")) if o is not None else None
        mids, lows = (_ratios(o.get("axesRatio")), _ratios(o.get("hAxesRatio"))) if o is not None else (None, None)
        if o is None or o.get("kind") not in KINDS:
            rejected.append({"run": "photo", "index": i, "reason": f"kind must be one of {', '.join(KINDS)}"})
        elif aspect is None or not 0.1 <= aspect <= 10.0:
            rejected.append({"run": "photo", "index": i, "reason": "aspect (height / width) must be 0.1-10"})
        elif mids is None or lows is None:
            rejected.append({"run": "photo", "index": i, "reason": "axesRatio and hAxesRatio must be fractions between 0 and 1"})
        else:
            leaves, style, edges = o.get("leaves", 1), o.get("style", "swing"), o.get("edgesSeen", "casing")
            panes, panels = read_detail(o)
            found.append(PhotoOpening(str(o["kind"]), str(style) if style in STYLES else "swing",
                                      leaves if isinstance(leaves, int) and not isinstance(leaves, bool) and 0 <= leaves <= 8 else 1,
                                      str(edges) if edges in EDGES else "casing", aspect, mids, lows, confidence_of(o.get("confidence")),
                                      str(o.get("note") or "")[:120], panes, panels))
    return found, rejected


def photo_features(seen: PhotoOpening) -> opening_match.Features:
    return opening_match.seen_features(seen.kind, seen.style, seen.leaves, bool(seen.h_axes_ratio), seen.axes_ratio, seen.transom_panes,
                                       *_panel_features(seen.panels))


def photo_match(seen: PhotoOpening, catalog: Catalog) -> opening_match.Match:
    """The catalog type that fits the opening of a picture best."""
    found = opening_match.best(photo_features(seen), catalog)
    if found is None:
        raise InvalidInput(f"The catalog has no {seen.kind} type", code="opening-type-missing", params={"kind": seen.kind})
    return found


def photo_opening(seen: PhotoOpening, point: Pt, catalog: Catalog, country: str | None = None) -> dict[str, Any]:
    """The ``add-opening`` record of a door or window seen in a picture with nothing to measure it by: its type from what was seen; its
    height the type's default (doors and windows vary least in height), its width from the picture's proportions, rounded and taken to a
    standard width of the country when one is close; the dividers where the picture shows them. Placed at ``point`` (the axes' frame).
    Width, height and sill are marked unsure: the user checks them."""
    kind_type = photo_match(seen, catalog).type_id
    data = get(catalog, kind_type)
    height = num(data, "defaultHeight", 2200.0 if seen.kind != "window" else 1200.0)
    casing = casing_width(data) if seen.edges_seen == "casing" else 0.0
    outer = (height + casing) / seen.aspect                     # the photo sees the outer edges: the casing on both sides and on top
    width = float(round_half_away((outer - 2 * casing) / PHOTO_WIDTH_STEP, 0)) * PHOTO_WIDTH_STEP
    sizes = as_dict((as_dict(data.get("sizes")) or {}).get((country or "").upper())) or {}
    standard = [float(w) for w in as_list(sizes.get("widths")) or [] if number(w) is not None]
    near = min(standard, key=lambda w: abs(w - width), default=None)
    if near is not None and abs(near - width) <= PHOTO_SNAP_MM:
        width = near
    raw: dict[str, Any] = {"kind": seen.kind, "openingType": kind_type, "source": "ai", "point": {"x": point[0], "z": point[1]},
                           "width": width, "height": height, "unsure": ["width", "height", *(["sill"] if seen.kind == "window" else [])]}
    low, high = width_range(data, seen.kind)
    if not low <= width <= high:                 # the drawing's hole is the authority; the user sees "check the width" in the preview
        raw["oversize"] = True
        raw["unsure"] = [*raw["unsure"], "width"]
    if seen.axes_ratio:
        raw["axes"] = [_r((r - 0.5) * width) for r in seen.axes_ratio]
    if seen.h_axes_ratio:
        raw["hAxes"] = [_r(r * height) for r in seen.h_axes_ratio]
    return raw


PHOTO_REACH_MM = 900.0      # a click farther than this from every wall axis is on no wall
REPLACE_REACH_MM = 150.0     # a click this close to an opening's hole (along its wall) picks that opening


def clicked_opening(point: Pt, axes: Sequence[WallAxis], existing: Sequence[Opening], selected: str | None = None,
                    reach: float = 900.0) -> Opening | None:
    """The opening the user right-clicked on: the one made from the selected floorplan element (``selected``: its element id), else the
    one whose hole (grown by ``REPLACE_REACH_MM``) covers the point on the wall axis nearest it."""
    live = [o for o in existing if not o.removed]
    if selected:
        hit = next((o for o in live if selected in (o.source_element, o.id)), None)
        if hit is not None:
            return hit
    near = nearest(point, axes, reach)
    if near is None:
        return None
    axis, s = near
    hits = [o for o in live if o.wall_axis.id == axis.id and abs(o.center - s) <= o.width / 2 + REPLACE_REACH_MM]
    return min(hits, key=lambda o: abs(o.center - s), default=None)


HEIGHT_STEP = 10.0


def photo_replacement(seen: PhotoOpening, target: Opening, catalog: Catalog) -> dict[str, Any]:
    """The ``update-opening`` changes that make the selected opening look like the one in the picture, fitted to the selected opening's
    size: its place and width are kept (the drawing knows them better than a picture with nothing to measure by); its height too when the
    drawing gives it for the same kind of opening, else the picture's proportions on that width (a window replaced by a door, a height the
    drawing only assumed), marked unsure. A door stands on the floor. The dividers sit at the picture's proportions of the hole."""
    kind_type = photo_match(seen, catalog).type_id
    keep_height = seen.kind == target.kind and "height" not in target.unsure
    if keep_height:
        height = target.height
    else:
        casing = casing_width(get(catalog, kind_type)) if seen.edges_seen == "casing" else 0.0
        height = float(round_half_away(((target.width + 2 * casing) * seen.aspect - casing) / HEIGHT_STEP, 0)) * HEIGHT_STEP
    changes: dict[str, Any] = {"kind": seen.kind, "openingType": kind_type, "width": target.width, "height": height, "source": "ai",
                               "unsure": [] if keep_height else ["height"]}
    low, high = width_range(get(catalog, kind_type), seen.kind)
    if not low <= target.width <= high:          # the selected opening's width is kept even past the new type's range; flagged to check
        changes["oversize"] = True
        changes["unsure"] = [*changes["unsure"], "width"]
    if seen.kind != "window":
        changes["sill"] = 0.0
    elif target.kind != "window":
        changes["sill"] = num(get(catalog, kind_type), "defaultSill", 900.0)
        changes["unsure"].append("sill")
    if seen.axes_ratio:
        changes["axes"] = [_r((r - 0.5) * target.width) for r in seen.axes_ratio]
    if seen.h_axes_ratio:
        changes["hAxes"] = [_r(r * height) for r in seen.h_axes_ratio]
    return changes


ELEMENT_AXIS_MM = 40.0      # a floorplan opening element lies on a wall axis when its centre is this close to the wall's thickness


def element_hole(element: Mapping[str, Any], axes: Sequence[WallAxis]) -> tuple[WallAxis, float, float] | None:
    """``(axis, centre, width)`` of the hole a floorplan opening element (the one the user selected) leaves in a wall: the wall axis
    running through it and its extent along that axis; None when no axis runs through it."""
    if element.get("kind") != "opening":
        return None
    pieces = opening_pieces({"elements": [element]})
    if not pieces:
        return None
    p = pieces[0]
    mid = ((p.a[0] + p.b[0]) / 2, (p.a[1] + p.b[1]) / 2)
    best: tuple[float, WallAxis, float, float] | None = None
    for axis in axes:
        if abs(axis.dir[0] * p.d[0] + axis.dir[1] * p.d[1]) < 0.999:
            continue
        off = abs(axis.d_of(mid))
        if not axis.segments or off > max(g.thickness for g in axis.segments) / 2 + ELEMENT_AXIS_MM:
            continue
        s0, s1 = sorted((axis.s_of(p.a), axis.s_of(p.b)))
        if s1 < 0 or s0 > axis.length:
            continue
        if best is None or off < best[0]:
            best = (off, axis, (s0 + s1) / 2, s1 - s0)
    return None if best is None else (best[1], best[2], best[3])


CLICK_SLACK_MM = 60.0


def element_at(point: Pt, elements: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The floorplan opening element under a clicked point (its box grown by ``CLICK_SLACK_MM``), or None."""
    for e in elements:
        if e.get("kind") != "opening":
            continue
        pieces = opening_pieces({"elements": [e]})
        if not pieces:
            continue
        p = pieces[0]
        s0, s1 = sorted((p.a[0] * p.d[0] + p.a[1] * p.d[1], p.b[0] * p.d[0] + p.b[1] * p.d[1]))
        s = point[0] * p.d[0] + point[1] * p.d[1]
        off = abs((point[0] - p.a[0]) * -p.d[1] + (point[1] - p.a[1]) * p.d[0])
        if s0 - CLICK_SLACK_MM <= s <= s1 + CLICK_SLACK_MM and off <= p.thickness / 2 + CLICK_SLACK_MM:
            return e
    return None


PHOTO_HEIGHT_MM = {"door": (1800.0, 3200.0), "passage": (1800.0, 3200.0), "window": (300.0, 2400.0)}   # a height from a picture is kept in these


def photo_into_hole(seen: PhotoOpening, axis: WallAxis, center: float, width: float, catalog: Catalog,
                    drawn: tuple[float | None, float | None] = (None, None)) -> dict[str, Any]:
    """The ``add-opening`` record that puts the opening of a picture into a hole of the drawing (a selected floorplan opening element):
    the hole's place and width; its height and sill those the drawing gives (``drawn``: the element's ``elev`` height and base), else
    the hole's width times the picture's proportions (the type's default when that falls outside ``PHOTO_HEIGHT_MM``), marked unsure; a door on the floor, a window at the type's sill. The
    dividers sit at the picture's proportions of the hole."""
    kind_type = photo_match(seen, catalog).type_id
    data = get(catalog, kind_type)
    width = float(round_half_away(width, 0))
    drawn_height, drawn_base = drawn
    if drawn_height:
        height = drawn_height
    else:                                        # the hole's width and the picture's proportions; the type's default when that is implausible
        low, high = PHOTO_HEIGHT_MM.get(seen.kind, PHOTO_HEIGHT_MM["door"])
        from_picture = float(round_half_away(width * seen.aspect / HEIGHT_STEP, 0)) * HEIGHT_STEP
        height = from_picture if low <= from_picture <= high else num(data, "defaultHeight", 2200.0 if seen.kind != "window" else 1200.0)
    if seen.kind != "window":
        sill = 0.0
    else:
        sill = drawn_base if drawn_base else num(data, "defaultSill", 900.0)
    unsure = [*([] if drawn_height else ["height"]), *(["sill"] if seen.kind == "window" and not drawn_base else [])]
    raw: dict[str, Any] = {"kind": seen.kind, "openingType": kind_type, "source": "ai", "wallAxis": axis.ref().to_data(), "center": _r(center),
                           "width": width, "height": height, "sill": sill, "unsure": unsure}
    if seen.axes_ratio:
        raw["axes"] = [_r((r - 0.5) * width) for r in seen.axes_ratio]
    if seen.h_axes_ratio:
        raw["hAxes"] = [_r(r * height) for r in seen.h_axes_ratio]
    return raw


def element_elev(element: Mapping[str, Any] | None) -> tuple[float | None, float | None]:
    """``(height, base)`` a floorplan opening element's ``elev`` gives (mm), None for what it does not give."""
    elev = as_dict((element or {}).get("elev")) or {}
    height, base = number(elev.get("height")), number(elev.get("base"))
    return (height if height is not None and height > 0 else None, base if base is not None and base > 0 else None)


def photo_operations(seen: Sequence[PhotoOpening], point: Pt, axes: Sequence[WallAxis], catalog: Catalog, country: str | None = None,
                     existing: Sequence[Opening] = (), selected: str | None = None, elements: Sequence[Mapping[str, Any]] = ()
                     ) -> tuple[list[dict[str, Any]], list[str]]:
    """``(operations, notes)`` for the openings of a picture with no cabinets: the first one at ``point``; a picture showing more than one
    cannot say where the others are, so they are noted and left out. A click on an opening the design already has (``existing``: its
    effective openings) makes that opening look like the picture (``update-opening``); elsewhere a new one is added. Dividers that do not
    fit the type are dropped for its template."""
    if not seen:
        return [], []
    notes = [f"opening-not-placed: the picture shows {len(seen)} openings; only the first was placed at the point picked."] if len(seen) > 1 else []
    notes += opening_match.note(photo_match(seen[0], catalog))
    target = clicked_opening(point, axes, existing, selected)
    if target is not None:
        changes = photo_replacement(seen[0], target, catalog)
        fitted = "its height from the picture's proportions; check it" if changes["unsure"] else "its height kept"
        notes.append(f"opening-replaced-from-photo: {target.id} becomes {changes['openingType']} {target.width:g} x {changes['height']:g} mm "
                     f"(fitted to the selected opening: its place and width kept, {fitted}).")
        return [{"op": "update-opening", "id": target.source_element or target.id, "changes": changes}], notes
    # the opening element selected; a selected wall (or nothing) means the opening element under the click, if any
    element = next((e for e in elements if selected and e.get("id") == selected and e.get("kind") == "opening"), None) \
        or element_at(point, elements)
    hole = element_hole(element, axes) if element is not None else None
    if hole is not None:
        axis, center, width = hole
        raw = photo_into_hole(seen[0], axis, center, width, catalog, element_elev(element))
        if element is not None and element.get("id"):
            raw["sourceElement"] = str(element["id"])     # it takes the drawn element's place: the element is no longer built as a solid
        tall = "its height from the drawing" if "height" not in raw["unsure"] else "the type's height, check it"
        sized = (f"opening-sized-from-selection: {raw['openingType']} {raw['width']:g} x {raw['height']:g} mm in the hole of "
                 f"{element.get('id') if element else ''} (its place and width; {tall}).")
    else:
        if nearest(point, axes, PHOTO_REACH_MM) is None:
            return [], [*notes, "opening-not-placed: no wall near the point picked; right-click a wall or select the opening to replace."]
        raw = photo_opening(seen[0], point, catalog, country)
        sized = (f"opening-sized-from-photo: {raw['openingType']} {raw['width']:g} x {raw['height']:g} mm from the picture's proportions; "
                 "check the sizes.")
    try:
        normalize(raw, "ai", catalog, axes, country)
    except InvalidInput as first:
        if "axes" not in raw and "hAxes" not in raw:
            return [], [*notes, f"opening-not-placed: {seen[0].kind}: {first}"]
        raw.pop("axes", None)
        raw.pop("hAxes", None)
        try:
            normalize(raw, "ai", catalog, axes, country)
        except InvalidInput as error:
            return [], [*notes, f"opening-not-placed: {seen[0].kind}: {error}"]
        notes.append(f"opening-axes-dropped: the dividers seen do not fit {raw['openingType']}.")
    notes.append(sized)
    return [{"op": "add-opening", "opening": raw}], notes
