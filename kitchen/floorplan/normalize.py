"""Audited floorplan document -> persistent room geometry (walls, openings, elements)."""
from __future__ import annotations

from typing import Any

from ..numeric import round_half_away
from ..numeric import round_int
from ..errors import InvalidInput
from ..errors import require

from .back import RoomEdge, room_edges
from .constants import DEFAULT_WALL_HEIGHT, DEFAULT_WALL_THICKNESS, SUPPORTED_CONTRACT, TOL, UNIT_MM
from .document import REGION_MARGIN_MM, as_dict, as_list, document_hash, element_bbox, element_field, field_value, frame_vectors, read_points
from .geom import Poly, Pt, angle_between, area2, boundary_dist, long_dir, point_in_poly, poly_dist, polys_cross, self_intersects, vcross, vdot, vsub
from .regions import list_rooms, parse_region
from .trim import trim_room


# ---------------------------------------------------------------- normalize
def normalize(data: dict[str, Any], room_id: str | None = None) -> dict[str, Any]:
    """Validate a floorplan-audited document and return derived scene geometry (mm).

    The result never contains the source document (it is stored once, under ``ref``); everything in it is derived.
    """
    if as_dict(data) is None or data.get("kind") != "floorplan-audited":
        raise InvalidInput("Expected a floorplan-audited JSON document")
    warnings: list[dict[str, Any]] = []
    cv = str(data.get("contractVersion", ""))
    if not cv.startswith(SUPPORTED_CONTRACT):
        warnings.append({"code": "contract-version", "message": f"contractVersion '{cv}' was not tested (expected {SUPPORTED_CONTRACT}x)"})
    unit = data.get("unit")
    if unit not in UNIT_MM:
        raise InvalidInput("Floorplan unit must be cm, mm, or m")
    frame_unit = (as_dict(data.get("frame")) or {}).get("unit")
    if frame_unit not in (None, unit):
        raise InvalidInput(f"frame.unit '{frame_unit}' differs from unit '{unit}'")
    k = UNIT_MM[unit]
    vx, vy = frame_vectors(data)
    elements = as_list(data.get("elements"))
    if elements is None:
        raise InvalidInput("Floorplan elements must be an array")
    ids: list[Any] = [e.get("id") for e in elements]
    dup = sorted({str(i) for i in ids if ids.count(i) > 1})
    if dup:
        raise InvalidInput("Duplicate element ids: " + ", ".join(dup))

    rooms = [r for r in list_rooms(data) if r["kind"] == "room"]
    region: dict[str, Any] | None = None
    room_el: dict[str, Any] | None = None
    if room_id is not None and str(room_id).startswith("region:"):
        region = parse_region(data, str(room_id))
        bb = region["bbox"]
        raw_room = [(bb[0], bb[1]), (bb[2], bb[1]), (bb[2], bb[3]), (bb[0], bb[3])]
        room_label = "Kitchen area (derived from walls)" if region["seeds"] else "Area (given as a box)"
        room_id = "region:around=" + ",".join(region["seeds"]) if region["seeds"] else "region:bbox=" + ",".join(f"{v:g}" for v in bb)
        open_sides: list[Any] = [n for n, sd in (as_dict(region["sides"]) or {}).items() if sd["open"]]
        warnings.append({"code": "region-derived", "message": f"{room_id} is not a drawn room: its sides stop at the walls around {', '.join(region['seeds'])}. Review the outline before relying on it."
                         if region["seeds"] else f"{room_id} is a box you gave, not a drawn room."})
        if open_sides:
            warnings.append({"code": "region-open-side", "message": f"no wall found on {', '.join(open_sides)}; those sides reach {REGION_MARGIN_MM:g} mm beyond the unit"})
    else:
        if not rooms:
            cands = [r["id"] for r in list_rooms(data) if r["kind"] == "region"]
            raise InvalidInput("No room outline (kind 'area' with tag 'room') in the floorplan" + (". To import the kitchen area pass one of: " + ", ".join(cands) if cands else ""))
        if room_id is None:
            if len(rooms) > 1:
                raise InvalidInput("The floorplan has several rooms; pass room_id. Rooms: " + ", ".join(f"{r['id']} ({r['label']})" for r in rooms))
            room_id = rooms[0]["id"]
        if room_id not in {r["id"] for r in rooms}:
            raise InvalidInput(f"Room '{room_id}' not found. Rooms: " + ", ".join(str(r["id"]) for r in rooms))
        room_id = require(room_id, "room_id")
        found: dict[str, Any] = next(e for e in elements if e.get("id") == room_id)
        room_el = found
        room_label = field_value(found, "label")
        raw_room = read_points(field_value(found, "geometry"), room_id)
        rects: list[tuple[str, list[float]]] = [(e["id"], bb) for e in elements if e.get("kind") == "wall" and e.get("id") and (bb := element_bbox(e))]
        raw_room, trimmed = trim_room(raw_room, rects, 60.0 / UNIT_MM[data["unit"]])
        if trimmed:
            warnings.append({"code": "room-trimmed", "message": f"the room outline overlapped wall elements {', '.join(trimmed)}; those parts were cut out of the room"})

    # file coordinates -> (right, forward) in mm -> scene (x = right - r0, z = f0 - forward)
    def to_rf(p: Pt) -> Pt:
        return ((p[0] * vx[0] + p[1] * vy[0]) * k, (p[0] * vx[1] + p[1] * vy[1]) * k)

    rf = [to_rf(p) for p in raw_room]
    r0, f0 = min(p[0] for p in rf), max(p[1] for p in rf)

    def to_scene(p: Pt) -> Pt:
        r, f = to_rf(p)
        return (round_half_away(r - r0, 3), round_half_away(f0 - f, 3))

    poly = [to_scene(p) for p in raw_room]
    dedup = [p for i, p in enumerate(poly) if p != poly[i - 1]]
    if len(dedup) != len(poly):
        warnings.append({"code": "duplicate-points", "message": f"{room_id}: {len(poly) - len(dedup)} repeated outline point(s) removed"})
    poly = dedup
    if len(poly) < 3 or abs(area2(poly)) < 1e-3:
        raise InvalidInput(f"{room_id}: outline has zero area")
    if self_intersects(poly):
        raise InvalidInput(f"{room_id}: outline crosses itself; fix the drawing (nothing was changed)")
    ccw = area2(poly) > 0

    edges = room_edges(poly)
    for ed in edges:
        if ed["length"] < 1.0:
            raise InvalidInput(f"{room_id}: outline contains a zero-length edge at point {ed['i']}")
        skew = min(angle_between(ed["dir"], (1, 0)), angle_between(ed["dir"], (0, 1)))
        if 0.5 < skew < 10:
            warnings.append({"code": "skewed-edge", "message": f"edge {ed['i']} is {skew:.1f} deg off the nearest axis; kept as drawn"})

    # ---- elements in scene coordinates
    prepared: list[tuple[dict[str, Any], Poly | None]] = []
    for e in elements:
        if e is room_el:
            continue
        g = as_dict(field_value(e, "geometry"))
        pts: Poly | None = None
        if g is not None:
            try:
                pts = [to_scene(p) for p in read_points(g, str(e.get("id")))]
            except ValueError as err:
                bbox = as_list(g.get("bbox"))
                if bbox is not None and len(bbox) == 4:
                    x0, y0, x1, y1 = (float(v) for v in bbox)
                    pts = [to_scene(p) for p in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
                else:
                    warnings.append({"code": "bad-geometry", "element": e.get("id"), "message": str(err)})
        prepared.append((e, pts))

    # ---- measured walls: they set the thickness of the matching room edge
    wall_for_edge: dict[int, dict[str, Any]] = {}
    max_t = DEFAULT_WALL_THICKNESS
    for e, pts in prepared:
        if e.get("kind") != "wall" or not pts:
            continue
        g = as_dict(field_value(e, "geometry")) or {}
        wd = long_dir(pts)
        best: tuple[float, int, float] | None = None
        for ed in edges:
            if angle_between(wd, ed["dir"]) > 5.0:
                continue
            alongs = [vdot(vsub(p, ed["a"]), ed["dir"]) for p in pts]
            offs = [-vdot(vsub(p, ed["a"]), ed["n"]) for p in pts]  # outward distance
            ov = max(0.0, min(max(alongs), ed["length"]) - max(min(alongs), 0.0))
            if ov < 0.5 * ed["length"] or abs(min(offs)) > TOL * 2:
                continue
            if best is None or ov > best[0]:
                thick = float(g["thickness"]) * k if isinstance(g.get("thickness"), (int, float)) else max(offs) - min(offs)
                best = (ov, ed["i"], thick)
        if best:
            el = as_dict(field_value(e, "elev")) or {}
            height = float(el["height"]) * k if isinstance(el.get("height"), (int, float)) else None
            wall_for_edge.setdefault(best[1], {"element": e.get("id"), "thickness": round_half_away(best[2], 3), "height": height})
            max_t = max(max_t, best[2])

    near = max_t + TOL
    retained: list[dict[str, Any]] = []
    for e, pts in prepared:
        kind = e.get("kind")
        el = as_dict(field_value(e, "elev"))
        rec: dict[str, Any] = {"id": e.get("id"), "kind": kind, "tag": field_value(e, "tag"), "label": field_value(e, "label"),
               "review": {n: element_field(e, n).get("status") for n in ("geometry", "tag", "label") if element_field(e, n)},
               "elev": {"base": float(el.get("base", 0)) * k, "height": float(el["height"]) * k} if el and isinstance(el.get("height"), (int, float)) else None,
               "outline": [{"x": p[0], "z": p[1]} for p in pts] if pts else None}
        g_raw = as_dict(field_value(e, "geometry")) or {}
        for key in ("swing", "arrow"):
            seq = as_list(g_raw.get(key))
            if seq is not None:
                try:
                    rec[key] = [{"x": q[0], "z": q[1]} for q in (to_scene(pp) for pp in seq)]
                except (TypeError, ValueError, IndexError):
                    pass
        hinge = as_list(g_raw.get("hinge"))
        if hinge is not None and len(hinge) == 2:
            hq = to_scene((hinge[0], hinge[1]))
            rec["hinge"] = {"x": hq[0], "z": hq[1]}
        if not pts:
            rec["membership"], rec["distance"] = "unknown", None
        else:
            rec["membership"], rec["distance"] = _membership(pts, poly, near)
            if rec["membership"] == "outside":
                warnings.append({"code": "outside-room", "element": rec["id"], "kind": kind, "distance": round_int(rec["distance"]),
                                 "message": f"{rec['id']} ({kind}) lies {rec['distance'] / 10:.0f} cm outside room {room_id}; it probably belongs to another room or area. Kept as data; not placed and not moved."})
        retained.append(rec)

    # ---- walls: inner face = outline edge, the box extends outward
    heights: list[float] = [w["height"] for w in wall_for_edge.values() if w["height"]]
    height = max(heights) if heights else DEFAULT_WALL_HEIGHT
    height_source = "measured" if heights else "assumed"
    walls: list[dict[str, Any]] = []
    for ed in edges:
        m = wall_for_edge.get(ed["i"])
        walls.append({"id": f"WALL-FP-{ed['i'] + 1}", "edge": ed["i"], "thickness": m["thickness"] if m else DEFAULT_WALL_THICKNESS,
                      "thicknessSource": "measured" if m else "assumed", "sourceElement": m["element"] if m else None,
                      "height": height, "openings": []})
    n_assumed = sum(w["thicknessSource"] == "assumed" for w in walls)
    if n_assumed:
        warnings.append({"code": "assumed-wall-thickness", "message": f"{n_assumed} of {len(walls)} walls have no measured wall element; thickness {DEFAULT_WALL_THICKNESS:g} mm assumed"})
    if height_source == "assumed":
        warnings.append({"code": "assumed-wall-height", "message": f"no wall elevation in the drawing; height {DEFAULT_WALL_HEIGHT:g} mm assumed"})
    ext_end = _corner_extensions(edges, walls, ccw)
    for w, ed, ext in zip(walls, edges, ext_end):
        a, b = ed["a"], (ed["b"][0] + ed["dir"][0] * ext, ed["b"][1] + ed["dir"][1] * ext)
        w.update(start={"x": round_half_away(a[0], 3), "y": 0, "z": round_half_away(a[1], 3)}, end={"x": round_half_away(b[0], 3), "y": 0, "z": round_half_away(b[1], 3)},
                 interiorNormal={"x": round_half_away(ed["n"][0], 6), "y": 0, "z": round_half_away(ed["n"][1], 6)}, length=round_half_away(ed["length"], 3), endExtension=round_half_away(ext, 3))

    # ---- openings: attach only when the geometry decides it
    for rec, (e, pts) in zip(retained, prepared):
        if rec["kind"] != "opening":
            continue
        note: list[str] = []
        rec["attached"] = _attach_opening(e, pts, rec, edges, walls, k, note)
        if rec["attached"] is None:
            rec["note"] = note[0] if note else "not attached"
            if rec["membership"] != "outside":
                warnings.append({"code": "opening-unattached", "element": rec["id"], "message": rec["note"]})

    # ---- review state of what was read
    for fld in ("label", "tag") if room_el is not None else ():
        if room_el is None:
            break
        st = element_field(room_el, fld).get("status")
        if st and st not in ("confirmed", "edited"):
            warnings.append({"code": "unreviewed", "element": room_id, "message": f"room {fld} '{field_value(room_el, fld)}' is {st}"})

    counts: dict[str, int] = {}
    for r in retained:
        counts[r["membership"]] = counts.get(r["membership"], 0) + 1
    return {"ref": document_hash(data), "planId": data.get("planId"), "contractVersion": cv,
            "sourceSha256": (as_dict(data.get("source")) or {}).get("sha256"), "sourceUnit": unit,
            "roomId": room_id, "roomLabel": room_label, "rooms": rooms, "region": region,
            "origin": {"unit": unit, "right": r0 / k, "forward": f0 / k, "note": "scene.x = right - origin.right, scene.z = origin.forward - forward (file units)"},
            "outline": [{"x": p[0], "z": p[1]} for p in poly], "width": round_half_away(max(p[0] for p in poly), 3), "depth": round_half_away(max(p[1] for p in poly), 3),
            "height": height, "heightSource": height_source, "areaM2": round_half_away(abs(area2(poly)) / 2e6, 3),
            "walls": walls, "elements": retained, "counts": counts, "binding": None, "warnings": warnings}


def _membership(pts: Poly, poly: Poly, near: float) -> tuple[str, float]:
    inside = [(point_in_poly(p, poly) or boundary_dist(p, poly) <= TOL) for p in pts]
    if all(inside):
        return "inside", 0.0
    if polys_cross(pts, poly) or any(point_in_poly(p, poly) and boundary_dist(p, poly) > TOL for p in pts) or \
            any(point_in_poly(v, pts) and boundary_dist(v, pts) > TOL for v in poly):
        return "overlapping", 0.0
    dist = poly_dist(pts, poly)
    if dist <= near:
        return "adjacent", round_half_away(dist, 3)
    return "outside", round_half_away(dist, 3)


def _corner_extensions(edges: list[RoomEdge], walls: list[dict[str, Any]], ccw: bool) -> list[float]:
    """How far the end of each wall box runs on over the outside corner of a convex vertex, so per-edge boxes leave no notch."""
    n = len(edges)
    ext = [0.0] * n
    cap = 5 * max(w["thickness"] for w in walls)
    for i in range(n):
        ei, ej = edges[i], edges[(i + 1) % n]
        turn = vcross(ei["dir"], ej["dir"])
        if not (turn > 1e-9 if ccw else turn < -1e-9):
            continue  # reflex vertex: the boxes already overlap
        ni, nj = (-ei["n"][0], -ei["n"][1]), (-ej["n"][0], -ej["n"][1])  # outward normals
        den = vdot(ei["dir"], nj)
        if abs(den) < 1e-6:
            continue
        s = (walls[(i + 1) % n]["thickness"] - walls[i]["thickness"] * vdot(ni, nj)) / den
        ext[i] = max(0.0, min(s, cap))
    return ext


def _attach_opening(e: dict[str, Any], pts: Poly | None, rec: dict[str, Any], edges: list[RoomEdge], walls: list[dict[str, Any]], k: float, note: list[str]) -> dict[str, Any] | None:
    if not pts:
        note.append("no geometry")
        return None
    tag = rec.get("tag")
    if tag not in ("door", "window"):
        note.append(f"{rec['id']}: opening tag '{tag}' is not door/window; not attached")
        return None
    g = as_dict(field_value(e, "geometry")) or {}
    d = long_dir(pts)
    cx, cz = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    ext = [vdot(vsub(p, (cx, cz)), d) for p in pts]
    width = float(g["width"]) * k if isinstance(g.get("width"), (int, float)) else max(ext) - min(ext)
    cands: list[tuple[float, int, float]] = []
    for ed in edges:
        if angle_between(d, ed["dir"]) > 10.0:
            continue
        along = vdot(vsub((cx, cz), ed["a"]), ed["dir"])
        out = -vdot(vsub((cx, cz), ed["a"]), ed["n"])
        t = walls[ed["i"]]["thickness"]
        if -TOL <= out <= t + TOL and -TOL <= along - width / 2 and along + width / 2 <= ed["length"] + TOL:
            cands.append((abs(out - t / 2), ed["i"], along))
    if not cands:
        note.append(f"{rec['id']} is not on any wall edge (it must be parallel to one and inside its thickness)")
        return None
    cands.sort()
    if len(cands) > 1 and cands[1][0] - cands[0][0] < 20.0:
        note.append(f"{rec['id']} could belong to edges {cands[0][1]} and {cands[1][1]}; not attached")
        return None
    _, i, along = cands[0]
    el: dict[str, Any] = rec.get("elev") or {}
    entry: dict[str, Any] = {"id": f"{walls[i]['id']}-FP-{rec['id']}", "type": tag, "offset": round_half_away(max(0.0, along - width / 2), 3), "width": round_half_away(width, 3),
             "height": el.get("height") or (2200.0 if tag == "door" else 1200.0), "sillHeight": el.get("base") or 0.0, "sourceElement": rec["id"]}
    walls[i]["openings"].append(entry)
    return {"wall": walls[i]["id"], "edge": i, "offset": entry["offset"], "width": entry["width"]}
