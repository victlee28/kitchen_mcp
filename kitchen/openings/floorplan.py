"""Doors and windows of an imported floorplan read into the opening contract (source ``drawn``, plan §3). Pure; the floorplan data
is never changed.

* Position: the attached opening's centre on the room edge, projected on the wall axis.
* Width: the gap between the floorplan's wall elements around the opening when there is one of a plausible size (the hole in the
  wall), else the opening's drawn length; a note says which.
* Leaves: each swing arc is a turning leaf - its centre (the hinge point) gives the hinge axis, its radius the leaf. Two leaves when
  the radius is clearly shorter than the hole (``width - 2 * frameFace - 100``). No arc: one leaf, its operation unsure. No size
  snapping.
"""
from __future__ import annotations

from ..numeric import round_half_away

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ..catalog import Catalog
from ..jsonview import as_dict, as_list
from .contract import Opening, Pt
from .normalize import normalize
from .types import default_height, get, num
from .wall_axes import WallAxis, segment_of

TWO_LEAF_MARGIN = 100.0
GAP_SLACK = (60.0, 400.0)        # a wall gap counts as the hole when it is at most this much narrower / wider than the drawn opening
NEAR_AXIS = 40.0


def _pt(value: Any) -> Pt | None:
    p = as_dict(value)
    if p is None or not isinstance(p.get("x"), (int, float)) or not isinstance(p.get("z"), (int, float)):
        return None
    return (float(p["x"]), float(p["z"]))


def _wall_gap(axis: WallAxis, elements: Sequence[Mapping[str, Any]], center: float) -> tuple[float, float] | None:
    """(start, end) of the gap between the floorplan's wall elements on ``axis`` around ``center``, or None."""
    half = max(g.thickness for g in axis.segments) / 2 + NEAR_AXIS
    spans: list[tuple[float, float]] = []
    for e in elements:
        if e.get("kind") != "wall":
            continue
        pts = [p for p in (_pt(q) for q in as_list(e.get("outline")) or []) if p is not None]
        if len(pts) < 3 or any(abs(axis.d_of(p)) > half for p in pts):
            continue
        ss = [axis.s_of(p) for p in pts]
        spans.append((min(ss), max(ss)))
    if any(lo < center < hi for lo, hi in spans):
        return None
    left = max((hi for _, hi in spans if hi <= center), default=None)
    right = min((lo for lo, _ in spans if lo >= center), default=None)
    if left is None or right is None:
        return None
    return (left, right)


def _leaves(axis: WallAxis, center: float, width: float, hinge: Pt | None, arc: list[Pt], frame: float, min_leaf: float
            ) -> tuple[str, list[float] | None, list[dict[str, Any]], list[str]]:
    """(opening type, middle axes, leaves, unsure fields) of a drawn door from its hinge point and swing arc."""
    if not arc and hinge is None:
        return "door-swing-1", None, [], ["leaves.0.operation", "leaves.0.hinge", "leaves.0.side"]
    if hinge is None:
        hinge = min(arc, key=lambda p: abs(axis.d_of(p)))
    points = [p for p in arc if math.hypot(p[0] - hinge[0], p[1] - hinge[1]) > 1.0]
    if not points:
        return "door-swing-1", None, [], ["leaves.0.side"]
    radii = sorted(math.hypot(p[0] - hinge[0], p[1] - hinge[1]) for p in points)
    radius = radii[len(radii) // 2]
    side = "+" if sum(axis.d_of(p) for p in points) / len(points) > 0 else "-"
    e0, e1 = center - width / 2, center + width / 2
    s_h = axis.s_of(hinge)
    at_start = abs(s_h - e0) <= abs(s_h - e1)
    if radius >= width - 2 * frame - TWO_LEAF_MARGIN:
        return "door-swing-1", None, [{"cols": [0, 1], "rows": [0, 1], "operation": "swing",
                                       "hinge": {"axis": "v", "index": 0 if at_start else 1}, "side": side, "active": True}], []
    meet = (e0 + frame + radius) if at_start else (e1 - frame - radius)
    rel = max(-width / 2 + frame + min_leaf, min(width / 2 - frame - min_leaf, meet - center))
    mids = None if abs(rel) <= 10.0 else [round_half_away(rel, 1)]
    leaves = [{"cols": [0, 1], "rows": [0, 1], "operation": "swing", "hinge": {"axis": "v", "index": 0}, "side": side, "active": at_start},
              {"cols": [1, 2], "rows": [0, 1], "operation": "swing", "hinge": {"axis": "v", "index": 2}, "side": side, "active": not at_start}]
    return ("door-swing-2" if mids is None else "door-swing-2-unequal"), mids, leaves, [f"leaves.{1 if at_start else 0}.side"]


def raw_from_floorplan(fp: Mapping[str, Any], axes: Sequence[WallAxis], catalog: Catalog) -> list[tuple[dict[str, Any], list[str]]]:
    """Contract-form drafts (plus notes) of the floorplan's attached doors and windows."""
    elements = [as_dict(x) or {} for x in as_list(fp.get("elements")) or []]
    out: list[tuple[dict[str, Any], list[str]]] = []
    for rec in elements:
        tag = rec.get("tag")
        attached = as_dict(rec.get("attached")) or {}
        if rec.get("kind") != "opening" or tag not in ("door", "window") or not attached:
            continue
        found = segment_of(str(attached.get("wall") or ""), axes)
        if found is None:
            continue
        axis, seg = found
        offset, drawn = float(attached.get("offset") or 0.0), float(attached.get("width") or 0.0)
        mid_face = (seg.face_start[0] + seg.face_dir[0] * (offset + drawn / 2), seg.face_start[1] + seg.face_dir[1] * (offset + drawn / 2))
        center, width = axis.s_of(mid_face), drawn
        notes: list[str] = []
        gap = _wall_gap(axis, elements, center)
        if gap is not None and drawn - GAP_SLACK[0] <= gap[1] - gap[0] <= drawn + GAP_SLACK[1]:
            center, width = (gap[0] + gap[1]) / 2, gap[1] - gap[0]
            notes.append(f"{rec.get('id')}: width from the gap between wall elements ({width:.0f} mm; drawn {drawn:.0f} mm).")
        else:
            notes.append(f"{rec.get('id')}: width from the drawn opening ({drawn:.0f} mm).")
        elev = as_dict(rec.get("elev")) or {}
        unsure: list[str] = []
        kind = "door" if tag == "door" else "window"
        raw: dict[str, Any] = {"id": str(rec.get("id") or ""), "kind": kind, "wallAxis": axis.ref().to_data(), "center": center,
                               "width": width, "sourceElement": str(rec.get("sourceElement") or rec.get("id") or "")}
        if kind == "door":
            type_data = get(catalog, "door-swing-1")
            hinge = _pt(rec.get("hinge"))
            arc = [p for p in (_pt(q) for q in as_list(rec.get("swing")) or []) if p is not None]
            opening_type, mids, leaves, more = _leaves(axis, center, width, hinge, arc, num(type_data, "frameFace"), num(type_data, "minLeaf"))
            raw.update(openingType=opening_type, axes=mids)
            if leaves:
                raw["leaves"] = leaves
            unsure += more
        else:
            raw["openingType"] = "window-swing-2"
            unsure.append("openingType")
        if isinstance(elev.get("height"), (int, float)):
            raw.update(height=float(elev["height"]), sill=float(elev.get("base") or 0.0))
        else:
            raw.update(height=default_height(kind), sill=0.0)                       # what the floorplan import assumes
            unsure += ["height", "sill"] if kind == "window" else ["height"]
        raw["unsure"] = unsure
        out.append((raw, notes))
    return out


def from_floorplan(fp: Mapping[str, Any], catalog: Catalog, axes: Sequence[WallAxis], country: str | None = None) -> list[Opening]:
    """The floorplan's attached doors and windows, normalized (``axes``: ``wall_axes.from_floorplan(fp)``)."""
    return [normalize(raw, "drawn", catalog, axes, country)[0] for raw, _ in raw_from_floorplan(fp, axes, catalog)]
