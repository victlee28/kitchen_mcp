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
    return SeenOpening(run, str(kind), tuple(sorted(axes)), sill, head, tuple(sorted(h_axes)), str(edges) if edges in EDGES else "casing",
                       str(style) if style in STYLES else "swing", leaves if isinstance(leaves, int) and not isinstance(leaves, bool) and 0 <= leaves <= 8 else 1,
                       confidence_of(obj.get("confidence")), str(obj.get("note") or "")[:120])


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


def opening_type(seen: SeenOpening) -> str:
    """The catalog type closest to what was seen (builtin ids; the workshop may hide or change them, ``normalize`` then refuses)."""
    if seen.kind == "passage":
        return "passage"
    if seen.kind == "door":
        if seen.style == "sliding":
            return "door-sliding-2"
        if seen.style == "folding":
            return "door-folding-4"
        if seen.leaves >= 2:
            return "door-swing-2-transom" if seen.h_axes else "door-swing-2"
        return "door-swing-1-transom" if seen.h_axes else "door-swing-1"
    by_style = {"fixed": "window-fixed", "sliding": "window-sliding-2", "top-hung": "window-top-hung"}
    if seen.style in by_style:
        return by_style[seen.style]
    return "window-swing-2-top" if seen.h_axes else "window-swing-2"     # no one-leaf casement type: two leaves, marked unsure by normalize


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
        raw: dict[str, Any] = {"kind": o.kind, "openingType": opening_type(o), "source": "ai", "wallAxis": axis.ref().to_data(),
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
            found.append(PhotoOpening(str(o["kind"]), str(style) if style in STYLES else "swing",
                                      leaves if isinstance(leaves, int) and not isinstance(leaves, bool) and 0 <= leaves <= 8 else 1,
                                      str(edges) if edges in EDGES else "casing", aspect, mids, lows, confidence_of(o.get("confidence")),
                                      str(o.get("note") or "")[:120]))
    return found, rejected


def photo_opening(seen: PhotoOpening, point: Pt, catalog: Catalog, country: str | None = None) -> dict[str, Any]:
    """The ``add-opening`` record of a door or window seen in a picture with nothing to measure it by: its type from what was seen; its
    height the type's default (doors and windows vary least in height), its width from the picture's proportions, rounded and taken to a
    standard width of the country when one is close; the dividers where the picture shows them. Placed at ``point`` (the axes' frame).
    Width, height and sill are marked unsure: the user checks them."""
    kind_type = opening_type(SeenOpening("photo", seen.kind, ((0.0, 1.0), (1.0, 1.0)), None, None,
                                         tuple((r, 1.0) for r in seen.h_axes_ratio), seen.edges_seen, seen.style, seen.leaves, seen.confidence))
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
    kind_type = opening_type(SeenOpening("photo", seen.kind, ((0.0, 1.0), (1.0, 1.0)), None, None,
                                         tuple((r, 1.0) for r in seen.h_axes_ratio), seen.edges_seen, seen.style, seen.leaves, seen.confidence))
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


def photo_into_hole(seen: PhotoOpening, axis: WallAxis, center: float, width: float, catalog: Catalog) -> dict[str, Any]:
    """The ``add-opening`` record that puts the opening of a picture into a hole of the drawing (a selected floorplan opening element):
    the hole's place and width; its height the type's default (the drawing gives none, and doors and windows vary least in height),
    marked unsure; a door on the floor, a window at the type's sill. The dividers sit at the picture's proportions of the hole."""
    kind_type = opening_type(SeenOpening("photo", seen.kind, ((0.0, 1.0), (1.0, 1.0)), None, None,
                                         tuple((r, 1.0) for r in seen.h_axes_ratio), seen.edges_seen, seen.style, seen.leaves, seen.confidence))
    data = get(catalog, kind_type)
    width = float(round_half_away(width, 0))
    height = num(data, "defaultHeight", 2200.0 if seen.kind != "window" else 1200.0)
    raw: dict[str, Any] = {"kind": seen.kind, "openingType": kind_type, "source": "ai", "wallAxis": axis.ref().to_data(), "center": _r(center),
                           "width": width, "height": height, "sill": 0.0 if seen.kind != "window" else num(data, "defaultSill", 900.0),
                           "unsure": ["height", *(["sill"] if seen.kind == "window" else [])]}
    if seen.axes_ratio:
        raw["axes"] = [_r((r - 0.5) * width) for r in seen.axes_ratio]
    if seen.h_axes_ratio:
        raw["hAxes"] = [_r(r * height) for r in seen.h_axes_ratio]
    return raw


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
    target = clicked_opening(point, axes, existing, selected)
    if target is not None:
        changes = photo_replacement(seen[0], target, catalog)
        fitted = "its height from the picture's proportions; check it" if changes["unsure"] else "its height kept"
        notes.append(f"opening-replaced-from-photo: {target.id} becomes {changes['openingType']} {target.width:g} x {changes['height']:g} mm "
                     f"(fitted to the selected opening: its place and width kept, {fitted}).")
        return [{"op": "update-opening", "id": target.source_element or target.id, "changes": changes}], notes
    element = next((e for e in elements if selected and e.get("id") == selected), None) or element_at(point, elements)
    hole = element_hole(element, axes) if element is not None else None
    if hole is not None:
        axis, center, width = hole
        raw = photo_into_hole(seen[0], axis, center, width, catalog)
        sized = (f"opening-sized-from-selection: {raw['openingType']} {raw['width']:g} x {raw['height']:g} mm in the hole of "
                 f"{element.get('id') if element else ''} (its place and width; the type's height, check it).")
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
