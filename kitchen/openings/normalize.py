"""One normalization for the three sources of a room opening (plan §3): the floorplan (``drawn``), image recognition (``ai``) and
the user (``human``). Pure.

Input forms accepted besides the contract itself (``center`` + ``width``):

* ``ai``: ``axes`` as ``[{"s": mm along the wall axis, "confidence": 0..1}, ...]`` - every vertical axis it saw, outer ones
  included - with ``edgesSeen`` (``casing`` by default: the visible edges are the outer edges of the trims), ``head`` instead of
  ``height``, ``hAxes`` as ``[{"h": mm above the floor, "confidence"}]``. Only AI sizes snap to the country's standard hole sizes
  (``defaults.openings.snapTolerance``, the centre stays put).
* ``human``: ``fromEdge`` ``{"at": "start" | "end", "distance"}`` (from the inner corner to the near edge of the hole) instead of
  ``center``; ``hinge`` ``"left" | "right"`` and ``opens`` ``"in" | "out"`` (seen standing in the kitchen facing the wall) for the
  main leaf.
* the first, axis-less form (``host`` + ``offset`` + ``hinge: start|end`` + ``swing: in|out``, saved before 13/11/2026) is upgraded.
"""
from __future__ import annotations

from ..numeric import round_half_away

import math
from collections.abc import Mapping, Sequence
from typing import Any, cast

from ..catalog import Catalog
from ..defaults import of as defaults_of
from ..errors import InvalidInput
from .contract import HINGED, KINDS, OPERATIONS, SIDES, SOURCES, AxisRef, Hinge, Leaf, Opening
from .frames import inner_corner_s
from .types import casing_width, default_type, get, grid, num, template_leaves
from .wall_axes import Segment, WallAxis, find, matches, moved_along, nearest, segments_of

ABSOLUTE_MAX_WIDTH = 12000.0                                           # no opening is wider, whatever the user keeps


def width_range(type_data: Mapping[str, Any], kind: str) -> tuple[float, float]:
    """``(min, max)`` hole width of an opening type: its ``minWidth`` / ``maxWidth`` (``types.get`` fills ``maxWidth`` from
    ``defaults.openingKinds.<kind>.maxWidth`` when the type leaves it out), else (0, ``ABSOLUTE_MAX_WIDTH``)."""
    low = type_data.get("minWidth")
    high = type_data.get("maxWidth")
    return (float(low) if isinstance(low, (int, float)) else 0.0,
            float(high) if isinstance(high, (int, float)) else ABSOLUTE_MAX_WIDTH)
MAX_HEIGHT = 3000.0
LOW_CONFIDENCE = 0.5
LEGACY_TYPES = {"window-casement-2": "window-swing-2"}


def _obj(value: Any) -> Mapping[str, Any] | None:
    """``value`` as a JSON object (any mapping), or None."""
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else None


def _arr(value: Any) -> list[Any] | None:
    """``value`` as a JSON array (a list or tuple), or None."""
    return list(cast(Sequence[Any], value)) if isinstance(value, (list, tuple)) else None


def _bad(message: str, code: str, **params: Any) -> InvalidInput:
    return InvalidInput(message, code=code, params=params or None)


def _number(data: Mapping[str, Any], key: str, default: Any = None) -> float | None:
    value = data.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise _bad(f"{key} must be a finite number", "opening-bad-number", field=key)
    return float(value)


def _snap(value: float, candidates: Any, tolerance: float) -> float | None:
    items = _arr(candidates)
    if items is None:
        return None
    sizes = [float(v) for v in items if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))]
    if not sizes:
        return None
    nearest = min(sizes, key=lambda v: (abs(v - value), v))
    return nearest if abs(nearest - value) <= tolerance else None


def _r(v: float) -> float:
    out = round_half_away(v, 3)
    return out + 0.0 if out != 0 else 0.0


def _axis_ref(value: Any) -> AxisRef:
    if isinstance(value, str) and value:
        return AxisRef(value)
    raw = _obj(value)
    if raw is None or not raw.get("id"):
        raise _bad("wallAxis must name a wall axis", "opening-bad-axis")
    fields_: Mapping[str, Any] = raw
    def pair(key: str) -> tuple[float, float] | None:
        if fields_.get(key) is None:
            return None
        v = _arr(fields_.get(key))
        if v is None or len(v) != 2 or not all(isinstance(x, (int, float)) for x in v):
            raise _bad(f"wallAxis.{key} must be two numbers", "opening-bad-axis")
        return (float(v[0]), float(v[1]))
    length: Any = raw.get("length")
    return AxisRef(str(raw["id"]), pair("start"), pair("dir"),
                   float(length) if isinstance(length, (int, float)) and not isinstance(length, bool) else None)


def upgrade_first_form(raw: Mapping[str, Any], axes: Sequence[WallAxis]) -> tuple[dict[str, Any], list[str]]:
    """The axis-less form (``host`` + ``offset`` from the start of one wall face, ``hinge`` start / end, ``swing`` in / out) -> the
    contract form, or the input unchanged when its wall is not found (normalize then refuses it)."""
    host = _obj(raw.get("host"))
    if host is None:
        return dict(raw), []
    wall = str(host.get("wall") or host.get("element") or "")
    offset = float(raw.get("offset") or 0.0)
    width = float(raw.get("width") or 0.0)
    found = segments_of(wall, axes)
    if not found:
        raise _bad(f"Opening {raw.get('id')!r} names a wall that is not in the design", "opening-axis-not-found", id=str(raw.get("id") or ""))
    def inside(pair: tuple[WallAxis, Segment]) -> bool:          # a wall element bounding several edges: the edge the offset fits
        a, g = pair
        return offset + width <= math.hypot(*(a.point(g.s1)[i] - a.point(g.s0)[i] for i in (0, 1))) + 1
    axis, seg = next((pair for pair in found if inside(pair)), found[0])
    def at(s_face: float) -> float:
        return axis.s_of((seg.face_start[0] + seg.face_dir[0] * s_face, seg.face_start[1] + seg.face_dir[1] * s_face))
    out = {k: v for k, v in raw.items() if k not in ("host", "offset", "hinge", "swing")}
    out["openingType"] = LEGACY_TYPES.get(str(raw.get("openingType") or ""), raw.get("openingType"))
    out["wallAxis"] = axis.ref().to_data()
    out["center"] = _r(at(offset + width / 2))
    if raw.get("hinge") in ("start", "end"):
        hinge_s = at(offset if raw["hinge"] == "start" else offset + width)
        out["_hingeEnd"] = "start" if hinge_s <= at(offset + width / 2) else "end"
    if raw.get("swing") in ("in", "out"):
        out["opens"] = raw["swing"]
    return out, [f"Opening {raw.get('id') or ''} upgraded from the axis-less form."]


def _place_at_point(data: dict[str, Any], axes: Sequence[WallAxis]) -> dict[str, Any]:
    """A clicked point (the axes' frame, mm) -> the nearest wall axis and the centre there, kept far enough from the axis ends for
    the hole to fit."""
    point = data["point"]
    x, z = _number(point, "x"), _number(point, "z")
    if x is None or z is None:
        raise _bad("point needs x and z", "opening-bad-point")
    near = nearest((x, z), axes, math.inf)
    if near is None:
        raise _bad("This design has no wall to put the opening in", "opening-axis-not-found", id="")
    axis, s = near
    width = _number(data, "width") or 0.0
    out = {k: v for k, v in data.items() if k != "point"}
    out["wallAxis"] = axis.ref().to_data()
    out["center"] = _r(max(width / 2, min(axis.length - width / 2, s)))
    return out


def facing(side: str | None, axis: WallAxis | None) -> str | None:
    """in / out (seen from the kitchen) of a leaf side on ``axis``; None when either is unknown."""
    if side not in SIDES or axis is None or not axis.inward:
        return None
    return "in" if (side == "+") == (axis.inward > 0) else "out"


def _side_for(opens: str, axis: WallAxis | None) -> str:
    inward = axis.inward if axis is not None and axis.inward else 1
    return "+" if (inward > 0) == (opens == "in") else "-"


def _leaf(value: Any, i: int) -> Leaf:
    raw = _obj(value)
    if raw is None:
        raise _bad(f"leaves[{i}] must be an object", "opening-bad-leaf", index=i)
    fields_: Mapping[str, Any] = raw
    def pair(key: str) -> tuple[int, int]:
        v = _arr(fields_.get(key))
        if v is None or len(v) != 2 or not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
            raise _bad(f"leaves[{i}].{key} must be two axis indices", "opening-bad-leaf", index=i)
        return (int(v[0]), int(v[1]))
    operation = str(raw.get("operation") or "")
    if operation not in OPERATIONS:
        raise _bad(f"leaves[{i}].operation must be one of {', '.join(OPERATIONS)}", "opening-bad-leaf", index=i)
    hinge = None
    h = _obj(raw.get("hinge"))
    if h is not None:
        index: Any = h.get("index")
        if h.get("axis") not in ("v", "h") or not isinstance(index, int) or isinstance(index, bool):
            raise _bad(f"leaves[{i}].hinge must be {{axis: v|h, index}}", "opening-bad-hinge", index=i)
        hinge = Hinge(str(h["axis"]), index)
    elif raw.get("hinge") is not None:
        raise _bad(f"leaves[{i}].hinge must be {{axis: v|h, index}} or null", "opening-bad-hinge", index=i)
    side: Any = raw.get("side")
    if side not in (None, *SIDES):
        raise _bad(f"leaves[{i}].side must be + or -", "opening-bad-side", index=i)
    return Leaf(pair("cols"), pair("rows"), operation, hinge, str(side) if side is not None else None, bool(raw.get("active", False)))


def _check_leaves(kind: str, leaves: Sequence[Leaf], v: Sequence[float], h: Sequence[float], type_data: Mapping[str, Any]) -> tuple[Leaf, ...]:
    """Leaves tile the grid; each hinge sits on its leaf's edge; a leaf is at least ``minLeaf`` wide. Returns the leaves with the
    hinge / side of non-hinged leaves cleared and exactly one active leaf (the first operable one when none is marked)."""
    nv, nh = len(v), len(h)
    if kind == "passage":
        if leaves:
            raise _bad("A passage has no leaves", "opening-bad-leaf")
        return ()
    if not leaves:
        raise _bad("A door or window needs at least one leaf", "opening-bad-leaf")
    cells: dict[tuple[int, int], int] = {}
    fixed: list[Leaf] = []
    frame = num(type_data, "frameFace")
    min_leaf = num(type_data, "minLeaf")
    for i, lf in enumerate(leaves):
        (c0, c1), (r0, r1) = lf.cols, lf.rows
        if not (0 <= c0 < c1 <= nv - 1 and 0 <= r0 < r1 <= nh - 1):
            raise _bad(f"leaves[{i}] lies outside the opening's axes", "opening-leaf-outside", index=i)
        for c in range(c0, c1):
            for r in range(r0, r1):
                if (c, r) in cells:
                    raise _bad(f"leaves[{i}] overlaps leaves[{cells[(c, r)]}]", "opening-leaves-overlap", index=i)
                cells[(c, r)] = i
        span = v[c1] - v[c0] - (frame if c0 == 0 else 0.0) - (frame if c1 == nv - 1 else 0.0)
        if span < min_leaf - 1e-6:
            raise _bad(f"leaves[{i}] is narrower than {min_leaf:g} mm", "opening-leaf-too-narrow", index=i, min=min_leaf)
        hinge, side = lf.hinge, lf.side
        if lf.operation in HINGED:
            if hinge is not None:
                ok = (hinge.axis == "v" and hinge.index in (c0, c1) and lf.operation in ("swing", "tilt-turn")) or \
                     (hinge.axis == "h" and lf.operation == "top-hung" and hinge.index == r1) or \
                     (hinge.axis == "h" and lf.operation == "bottom-hung" and hinge.index == r0)
                if not ok:
                    raise _bad(f"leaves[{i}].hinge is not on an edge the leaf can turn about", "opening-bad-hinge", index=i)
        else:
            hinge, side = None, None
        fixed.append(Leaf(lf.cols, lf.rows, lf.operation, hinge, side, lf.active))
    if len(cells) != (nv - 1) * (nh - 1):
        raise _bad("The leaves must cover every bay between the opening's axes", "opening-leaves-gap")
    if sum(1 for lf in fixed if lf.active) > 1:
        raise _bad("Only one leaf can be the active one", "opening-bad-leaf")
    if not any(lf.active for lf in fixed):
        first = next((i for i, lf in enumerate(fixed) if lf.operation != "fixed"), None)
        if first is not None:
            lf = fixed[first]
            fixed[first] = Leaf(lf.cols, lf.rows, lf.operation, lf.hinge, lf.side, True)
    return tuple(fixed)


def clear_width(kind: str, leaves: Sequence[Leaf], v: Sequence[float], type_data: Mapping[str, Any], width: float) -> float | None:
    """Clear passage of a door: the active leaf's bay less the frame on the hole's edges and, for a turning leaf, its thickness and
    the stop. A passage: its width. A window: None."""
    if kind == "passage":
        return _r(width)
    if kind != "door":
        return None
    active = next((lf for lf in leaves if lf.active), None)
    if active is None:
        return None
    frame = num(type_data, "frameFace")
    c0, c1 = active.cols
    span = v[c1] - v[c0] - (frame if c0 == 0 else 0.0) - (frame if c1 == len(v) - 1 else 0.0)
    if active.operation in ("swing", "tilt-turn"):
        span -= num(type_data, "leafThickness") + num(type_data, "stop")
    return _r(max(0.0, span))


def normalize(raw: Mapping[str, Any], source: str, catalog: Catalog, axes: Sequence[WallAxis] = (),
              country: str | None = None, reading: bool = False) -> tuple[Opening, list[str]]:
    """Validate and complete one opening. ``axes``: the design's wall axes (``wall_axes.for_spec``); without them the axis is not
    checked and in / out cannot be turned into a side. ``reading``: a saved record is being read, not an edit made: an opening
    that no longer fits its axis is kept (noted, its centre unsure) instead of refused."""
    if source not in SOURCES:
        raise _bad("source must be drawn, ai or human", "opening-bad-source")
    notes: list[str] = []
    data: dict[str, Any] = dict(raw)
    if data.get("wallAxis") is None and "host" in data:
        data, upgraded = upgrade_first_form(data, axes)
        notes += upgraded
    if data.get("wallAxis") is None and isinstance(data.get("point"), Mapping):
        data = _place_at_point(data, axes)
    kind = str(data.get("kind") or "")
    if kind not in KINDS:
        raise _bad("kind must be door, window or passage", "opening-bad-kind")
    oid = str(data.get("id") or "")
    source_element = str(data["sourceElement"]) if data.get("sourceElement") is not None else None
    if data.get("removed") is True:
        if not source_element:
            raise _bad("Only a floorplan opening can be removed by a record", "opening-bad-removal")
        axis_data = _obj(data.get("wallAxis"))
        axis_id = str(axis_data.get("id") or "") if axis_data is not None else str(data.get("wallAxis") or "")
        return Opening(oid, kind, str(data.get("openingType") or default_type(catalog, kind)), AxisRef(axis_id), 0.0, 0.0, None, None, (), 0.0, 0.0,
                       None, source, (), source_element, True), notes
    opening_type = str(data.get("openingType") or default_type(catalog, kind))
    type_data = get(catalog, opening_type)
    if type_data.get("kind") != kind:
        raise _bad(f"Opening type {opening_type!r} is not a {kind}", "opening-type-kind-mismatch", id=opening_type)
    unsure_raw = _arr(data.get("unsure", []))
    if unsure_raw is None or not all(isinstance(x, str) for x in unsure_raw):
        raise _bad("unsure must be a list of field names", "opening-bad-unsure")
    unsure: list[str] = [str(x) for x in unsure_raw]

    ref = _axis_ref(data.get("wallAxis"))
    axis = find(ref, axes) if axes else None
    if axes and axis is None:
        raise _bad(f"No wall axis {ref.id!r} in this design", "opening-axis-not-found", id=ref.id)
    shift = 0.0                         # the wall now runs on past the room (wall_axes.extend): the stored s moves with the axis start
    if axis is not None:
        moved = None if matches(ref, axis) else moved_along(ref, axis)
        if not matches(ref, axis) and moved is None:
            notes.append(f"opening-orphaned: wall axis {ref.id} changed since opening {oid} was placed; check its position.")
            unsure.append("wallAxis")
        elif axis.frame == "room":
            shift = moved or 0.0
            if moved is not None and abs(moved) > 1e-6:
                notes.append(f"opening-axis-extended: wall axis {ref.id} now runs on past the room; opening {oid} kept its place.")
            ref = axis.ref()

    # ---- position and size along the axis
    axes_list = _arr(data.get("axes")) or []
    ai_axes = [m for m in (_obj(a) for a in axes_list) if m is not None]
    mids: tuple[float, ...] | None
    if ai_axes and len(ai_axes) == len(axes_list):
        seen = sorted((float(a["s"]) + shift, float(a.get("confidence", 1.0))) for a in ai_axes if isinstance(a.get("s"), (int, float)))
        if len(seen) < 2:
            raise _bad("Recognized axes need both edges of the opening", "opening-bad-axes")
        center = (seen[0][0] + seen[-1][0]) / 2
        width = seen[-1][0] - seen[0][0]
        if str(data.get("edgesSeen") or "casing") == "casing":
            width -= 2 * casing_width(type_data)
        mids = tuple(_r(s - center) for s, _ in seen[1:-1]) if len(seen) > 2 else None
        if seen[0][1] < LOW_CONFIDENCE or seen[-1][1] < LOW_CONFIDENCE:
            unsure.append("width")
        if any(c < LOW_CONFIDENCE for _, c in seen[1:-1]):
            unsure.append("axes")
    else:
        width_value = _number(data, "width")
        if width_value is None or width_value <= 0:
            widest = width_range(type_data, kind)[1]
            raise _bad(f"width must be greater than 0 and no more than {widest:g} mm", "opening-bad-width", max=widest)
        width = width_value
        edge: Any = data.get("fromEdge")
        center_value = _number(data, "center")
        if center_value is not None:
            center_value += shift
        edge = _obj(edge)
        if edge is not None and center_value is None:
            if axis is None:
                raise _bad("fromEdge needs the design's wall axes", "opening-axis-not-found", id=ref.id)
            at = "end" if edge.get("at") == "end" else "start"
            distance = _number(edge, "distance", 0.0) or 0.0
            corner = inner_corner_s(axis, axes, at)
            center_value = corner + distance + width / 2 if at == "start" else corner - distance - width / 2
        if center_value is None:
            raise _bad("center must give the opening's position along the wall axis", "opening-bad-center")
        center = center_value
        mid_raw = _arr(data.get("axes"))
        if data.get("axes") is None:
            mids = None
        elif mid_raw is not None and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in mid_raw):
            mids = tuple(float(x) for x in mid_raw)
        else:
            raise _bad("axes must be a list of numbers (mm from the centre) or null", "opening-bad-axes")

    sill = _number(data, "sill", type_data.get("defaultSill", 0)) or 0.0
    head = _number(data, "head")
    height_value = _number(data, "height")
    if height_value is None and head is not None:
        height_value = head - sill
    if height_value is None:
        height_value = num(type_data, "defaultHeight", 2200.0)
        if source != "human":
            unsure.append("height")
    height = height_value
    h_raw = _arr(data.get("hAxes"))
    h_seen = [m for m in (_obj(x) for x in h_raw or []) if m is not None]
    h_mids: tuple[float, ...] | None
    if data.get("hAxes") is None:
        h_mids = None
    elif h_raw and len(h_seen) == len(h_raw):
        h_mids = tuple(_r(float(x["h"]) - sill) for x in h_seen if isinstance(x.get("h"), (int, float)))
        if any(float(x.get("confidence", 1.0)) < LOW_CONFIDENCE for x in h_seen):
            unsure.append("hAxes")
    elif h_raw is not None and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in h_raw):
        h_mids = tuple(float(x) for x in h_raw)
    else:
        raise _bad("hAxes must be a list of numbers (mm above the sill) or null", "opening-bad-axes")

    if source == "ai" and country:
        by_country = _obj(type_data.get("sizes"))
        sizes: Mapping[str, Any] = (_obj(by_country.get(country.upper())) if by_country is not None else None) or {}
        tolerance = float(defaults_of(catalog).openings.get("snapTolerance", 30))
        snapped = _snap(width, sizes.get("widths"), tolerance)
        if snapped is None:
            unsure.append("width")
        elif snapped != width:
            notes.append(f"AI width snapped from {width:g} mm to {snapped:g} mm (centre kept).")
            width = snapped
        snapped_h = _snap(height, sizes.get("heights"), tolerance)
        if snapped_h is None:
            if sizes.get("heights"):
                unsure.append("height")
        elif snapped_h != height:
            notes.append(f"AI height snapped from {height:g} mm to {snapped_h:g} mm.")
            height = snapped_h

    if width <= 0 or width > ABSOLUTE_MAX_WIDTH:
        raise _bad(f"width must be greater than 0 and no more than {ABSOLUTE_MAX_WIDTH:g} mm", "opening-bad-width", max=ABSOLUTE_MAX_WIDTH)
    oversize = data.get("oversize") is True
    low, high = width_range(type_data, kind)
    if not oversize and not (low <= width <= high):
        raise _bad(f"width {width:g} mm is outside the range of type {opening_type} ({low:g}..{high:g} mm)", "opening-width-out-of-range",
                   width=width, min=low, max=high, type=opening_type)
    if height <= 0 or height > MAX_HEIGHT:
        raise _bad(f"height must be greater than 0 and no more than {MAX_HEIGHT:g} mm", "opening-bad-height", max=MAX_HEIGHT)
    if sill < 0:
        raise _bad("sill must be non-negative", "opening-bad-sill")
    if axis is not None:                    # the default walls of a design without a floorplan follow the cabinets: only their start is fixed
        if center - width / 2 < -1 or (axis.frame == "room" and center + width / 2 > axis.length + 1):
            if source == "drawn" or reading:
                notes.append(f"opening-outside-axis: opening {oid} reaches past the end of wall axis {axis.id}.")
                unsure.append("center")
            else:
                raise _bad(f"The opening does not fit on wall axis {axis.id} (0..{axis.length:g} mm)", "opening-outside-axis",
                           id=axis.id, length=axis.length)
    if mids is not None:
        if any(b <= a for a, b in zip(mids, mids[1:])) or any(not (-width / 2 < m < width / 2) for m in mids):
            raise _bad("Middle axes must increase and lie inside the opening", "opening-axis-outside")
    if h_mids is not None:
        if any(b <= a for a, b in zip(h_mids, h_mids[1:])) or any(not (0 < m < height) for m in h_mids):
            raise _bad("Horizontal axes must increase and lie between the sill and the head", "opening-axis-outside")
    v, h = grid(type_data, width, height, mids, h_mids)

    # ---- leaves
    leaves_raw = _arr(data.get("leaves"))
    if leaves_raw is not None and (leaves_raw or kind == "passage"):
        leaves = [_leaf(x, i) for i, x in enumerate(leaves_raw)]
    else:
        leaves = list(template_leaves(type_data, len(v), len(h), axis.inward if axis is not None else 0))
        if source == "ai":
            unsure += [f"leaves.{i}.{field}" for i, lf in enumerate(leaves) if lf.operation in HINGED for field in ("hinge", "side")]
    main = next((i for i, lf in enumerate(leaves) if lf.active), next((i for i, lf in enumerate(leaves) if lf.operation in HINGED), None))
    hand = data.get("hinge")
    hinge_end = data.get("_hingeEnd")
    if hand in ("left", "right") or hinge_end in ("start", "end"):
        if main is None or leaves[main].operation not in ("swing", "tilt-turn"):
            raise _bad("This opening has no side-hinged leaf to put the hinge on", "opening-bad-hinge")
        lf = leaves[main]
        if hinge_end in ("start", "end"):
            at_end = hinge_end == "end"
        else:
            if axis is None or not axis.inward:
                raise _bad("hinge left / right needs the design's wall axes", "opening-axis-not-found", id=ref.id)
            look = (-axis.normal[0] * axis.inward, -axis.normal[1] * axis.inward)      # facing the wall from the kitchen
            right = (-look[1], look[0])
            at_end = (right[0] * axis.dir[0] + right[1] * axis.dir[1] > 0) == (hand == "right")
        leaves[main] = Leaf(lf.cols, lf.rows, lf.operation, Hinge("v", lf.cols[1] if at_end else lf.cols[0]), lf.side, lf.active)
    elif hand is not None and not isinstance(hand, Mapping):
        raise _bad("hinge must be left or right (seen from the kitchen)", "opening-bad-hinge")
    opens = data.get("opens")
    if opens in ("in", "out"):
        if main is None:
            raise _bad("This opening has no leaf that opens", "opening-bad-side")
        side = _side_for(str(opens), axis)
        leaves = [Leaf(x.cols, x.rows, x.operation, x.hinge, side if x.operation in HINGED else x.side, x.active) for x in leaves]
    elif opens is not None:
        raise _bad("opens must be in or out", "opening-bad-side")
    checked = _check_leaves(kind, leaves, v, h, type_data)

    clear = _number(data, "clearWidth")
    if clear is not None and (clear <= 0 or clear > width):
        raise _bad("clearWidth must be greater than 0 and no more than width", "opening-bad-clear-width")
    if clear is None:
        clear = clear_width(kind, checked, v, type_data, width)
    return Opening(oid, kind, opening_type, ref, _r(center), _r(width), tuple(_r(m) for m in mids) if mids is not None else None,
                   tuple(_r(m) for m in h_mids) if h_mids is not None else None, checked, _r(sill), _r(height), clear, source,
                   tuple(dict.fromkeys(unsure)), source_element, False, oversize), notes
