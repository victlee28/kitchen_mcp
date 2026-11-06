"""Audited floorplan -> persistent room geometry (mm), element classification and kitchen/wall binding.

Rules that hold everywhere in this module:
* nothing is ever shifted or snapped to "fix" a drawing; a bad outline raises, an element that belongs elsewhere is reported;
* every number that was not measured in the drawing (wall thickness, wall height) is flagged ``assumed``;
* scene coordinates: x to the right, z towards the viewer of a top-down plan (up on the page = -z), y up, millimetres.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .placement import Placement
from .errors import InvalidInput

DEFAULT_WALL_THICKNESS = 140.0   # mm, used only for edges without a measured wall element
DEFAULT_WALL_HEIGHT = 3000.0     # mm
TOL = 30.0                       # mm, drawing/pick tolerance for "touching"
PARALLEL_DEG = 8.0
SUPPORTED_CONTRACT = "2."

# axis name used by the floorplan contract -> unit vector in (right, forward, up)
AXIS = {"toi": (0, 1, 0), "lui": (0, -1, 0), "phai": (1, 0, 0), "trai": (-1, 0, 0), "len": (0, 0, 1), "xuong": (0, 0, -1)}
UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


# ---------------------------------------------------------------- small geometry helpers
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _norm(a):
    n = math.hypot(*a)
    return (a[0] / n, a[1] / n) if n > 1e-9 else (0.0, 0.0)


def _area2(poly):
    return sum(_cross(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def _seg_dist(p, a, b):
    ab = _sub(b, a)
    L2 = _dot(ab, ab)
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, _dot(_sub(p, a), ab) / L2))
    q = (a[0] + ab[0] * t, a[1] + ab[1] * t)
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _boundary_dist(p, poly):
    return min(_seg_dist(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def _pip(p, poly):
    x, y = p
    inside = False
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _proper_cross(a, b, c, d):
    """Segments ab and cd cross at a single interior point of both (touching/collinear does not count)."""
    d1, d2 = _cross(_sub(b, a), _sub(c, a)), _cross(_sub(b, a), _sub(d, a))
    d3, d4 = _cross(_sub(d, c), _sub(a, c)), _cross(_sub(d, c), _sub(b, c))
    return d1 * d2 < -1e-9 and d3 * d4 < -1e-9


def _polys_cross(p, q):
    return any(_proper_cross(p[i], p[(i + 1) % len(p)], q[j], q[(j + 1) % len(q)]) for i in range(len(p)) for j in range(len(q)))


def _poly_dist(p, q):
    """Distance between two polygon boundaries (0 when they touch or cross)."""
    if _polys_cross(p, q):
        return 0.0
    return min([_seg_dist(v, q[j], q[(j + 1) % len(q)]) for v in p for j in range(len(q))] +
               [_seg_dist(v, p[j], p[(j + 1) % len(p)]) for v in q for j in range(len(p))])


def _self_intersects(poly):
    n = len(poly)
    for i in range(n):
        for j in range(i + 1, n):
            if (j + 1) % n == i or (i + 1) % n == j:
                continue
            if _proper_cross(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]):
                return True
    return False


def _angle_between(d1, d2):
    """Smallest angle (deg) between two undirected lines."""
    return math.degrees(math.atan2(abs(_cross(d1, d2)), abs(_dot(d1, d2))))


def _long_dir(pts):
    best, d = 0.0, (1.0, 0.0)
    for i in range(len(pts)):
        v = _sub(pts[(i + 1) % len(pts)], pts[i])
        if math.hypot(*v) > best:
            best, d = math.hypot(*v), _norm(v)
    return d


# ---------------------------------------------------------------- reading the document
def _frame_vectors(data: dict[str, Any]):
    frame = data.get("frame")
    if not isinstance(frame, dict):
        raise InvalidInput("Floorplan has no 'frame'; axis directions would have to be guessed")
    names = [frame.get(k) for k in ("x", "y", "z")]
    if any(n not in AXIS for n in names):
        raise InvalidInput(f"Unsupported frame axes {names}; known names: {', '.join(AXIS)}")
    vx, vy, vz = (AXIS[n] for n in names)
    if vx[2] or vy[2] or not vz[2]:
        raise InvalidInput("Frame must have horizontal x and y axes and a vertical z axis")
    det = (vx[0] * (vy[1] * vz[2] - vy[2] * vz[1]) - vx[1] * (vy[0] * vz[2] - vy[2] * vz[0]) + vx[2] * (vy[0] * vz[1] - vy[1] * vz[0]))
    declared = frame.get("handed")
    if declared in ("trai", "phai"):
        expected = -1 if declared == "trai" else 1
        if det != expected:
            raise InvalidInput(f"Frame axes {names} are {'left' if det < 0 else 'right'}-handed but the file declares '{declared}'")
    return vx, vy


def _points(value: Any, element_id: str, what: str = "outline") -> list[tuple[float, float]]:
    outline = value.get(what) if isinstance(value, dict) else None
    if not isinstance(outline, list) or len(outline) < 3:
        raise InvalidInput(f"{element_id}: geometry.{what} must contain at least three points")
    pts = []
    for index, point in enumerate(outline):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise InvalidInput(f"{element_id}: {what} point {index} must be [x, y]")
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError) as error:
            raise InvalidInput(f"{element_id}: {what} point {index} must be numeric") from error
        if not (math.isfinite(x) and math.isfinite(y)):
            raise InvalidInput(f"{element_id}: {what} point {index} must be finite")
        pts.append((x, y))
    return pts


def _field(element: dict, name: str) -> dict:
    f = (element.get("fields") or {}).get(name)
    return f if isinstance(f, dict) else {}


def _fv(element: dict, name: str):
    return _field(element, name).get("value")


def document_hash(data: dict[str, Any]) -> str:
    """Stable id of a floorplan document (the key it is stored under)."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


KITCHEN_WORDS = ("kitchen", "bếp", "bep")
REGION_COVER = 0.2          # a wall bounds a side of the region when it covers this share of the seed's width
REGION_MARGIN_MM = 600.0    # how far an open side (no wall found) reaches beyond the seed


def _bbox(e: dict) -> list[float] | None:
    g = _fv(e, "geometry")
    if not isinstance(g, dict):
        return None
    if isinstance(g.get("bbox"), list) and len(g["bbox"]) == 4:
        return [float(v) for v in g["bbox"]]
    try:
        pts = _points(g, str(e.get("id")))
    except ValueError:
        return None
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]


def _is_kitchen_unit(e: dict) -> bool:
    if e.get("kind") != "furniture":
        return False
    text = f"{_fv(e, 'tag') or ''} {_fv(e, 'label') or ''}".lower()
    return any(w in text for w in KITCHEN_WORDS)


def derive_region(data: dict[str, Any], seeds: list[str]) -> dict[str, Any]:
    """The rectangle of file coordinates that the walls around the seed elements enclose (for a plan with no room for the kitchen).

    Each side stops at the nearest wall whose face lies beyond the seed and that covers at least REGION_COVER of the seed's width.
    A side with no such wall stays open and reaches REGION_MARGIN_MM beyond the seed; that is reported.
    """
    unit = data.get("unit")
    if unit not in UNIT_MM:
        raise InvalidInput("Floorplan unit must be cm, mm, or m")
    k = UNIT_MM[unit]
    tol = TOL / k
    by_id = {e.get("id"): e for e in (data.get("elements") or [])}
    boxes = []
    for sid in seeds:
        if sid not in by_id:
            raise InvalidInput(f"Region seed '{sid}' not found")
        bb = _bbox(by_id[sid])
        if not bb:
            raise InvalidInput(f"Region seed '{sid}' has no geometry")
        boxes.append(bb)
    if not boxes:
        raise InvalidInput("A region needs at least one seed element")
    seed = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    walls = [(e.get("id"), bb) for e in by_id.values() if e.get("kind") == "wall" and (bb := _bbox(e))]
    out = [0.0] * 4
    sides: dict[str, Any] = {}
    for axis, sign, name in ((0, -1, "forwardMin"), (0, 1, "forwardMax"), (1, -1, "rightMin"), (1, 1, "rightMax")):
        other = 1 - axis
        lo_o, hi_o = seed[other], seed[other + 2]
        span = hi_o - lo_o
        cands = []
        for wid, bb in walls:
            face = bb[axis] if sign > 0 else bb[axis + 2]
            beyond = face - seed[axis + 2] if sign > 0 else seed[axis] - face
            ov = min(hi_o, bb[other + 2]) - max(lo_o, bb[other])
            if beyond >= -tol and ov > 0:
                cands.append((abs(face - (seed[axis + 2] if sign > 0 else seed[axis])), face, wid, (max(lo_o, bb[other]), min(hi_o, bb[other + 2]))))
        cands.sort()
        chosen = None
        i = 0
        while i < len(cands):
            group = [c for c in cands[i:] if abs(c[1] - cands[i][1]) <= tol]
            intervals = sorted(c[3] for c in group)
            covered, cur_end = 0.0, None
            for lo, hi in intervals:
                lo = lo if cur_end is None else max(lo, cur_end)
                if hi > lo:
                    covered += hi - lo
                cur_end = hi if cur_end is None else max(cur_end, hi)
            if covered >= REGION_COVER * span:
                chosen = group
                break
            i += len(group)
        idx = axis if sign < 0 else axis + 2
        if chosen:
            face = min(c[1] for c in chosen) if sign > 0 else max(c[1] for c in chosen)
            out[idx] = face
            sides[name] = {"face": face, "walls": sorted({c[2] for c in chosen}), "open": False}
        else:
            face = seed[idx] + sign * REGION_MARGIN_MM / k
            out[idx] = face
            sides[name] = {"face": face, "walls": [], "open": True}
    return {"bbox": [out[0], out[1], out[2], out[3]], "seeds": list(seeds), "sides": sides, "unit": unit}


def _kitchen_candidates(data: dict[str, Any]) -> list[dict]:
    """Kitchen units that sit in no listed room, grouped by the region the walls give them."""
    rooms = {r["id"]: r for r in list_rooms(data, regions=False)}
    room_polys = {}
    for e in data.get("elements") or []:
        if e.get("id") in rooms:
            try:
                room_polys[e["id"]] = _points(_fv(e, "geometry"), str(e["id"]))
            except ValueError:
                pass
    groups: list[dict] = []
    for e in data.get("elements") or []:
        if not _is_kitchen_unit(e) or not (bb := _bbox(e)):
            continue
        c = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
        if any(_pip(c, poly) for poly in room_polys.values()):
            continue
        try:
            reg = derive_region(data, [e["id"]])
        except ValueError:
            continue
        for g in groups:
            if all(abs(a - b) <= 1e-6 + 3 * TOL / UNIT_MM[data["unit"]] for a, b in zip(g["bbox"], reg["bbox"])):
                g["seeds"].append(e["id"])
                g["labels"].append(_fv(e, "label") or e["id"])
                break
        else:
            groups.append({"bbox": reg["bbox"], "seeds": [e["id"]], "labels": [_fv(e, "label") or e["id"]], "open": any(s["open"] for s in reg["sides"].values())})
    return groups


def list_rooms(data: dict[str, Any], regions: bool = True) -> list[dict]:
    """Every element tagged as a room, then (kind 'region') areas the walls enclose around kitchen units that no room covers."""
    out = []
    for e in (data.get("elements") or []):
        if e.get("kind") != "area" or _fv(e, "tag") != "room":
            continue
        g = _fv(e, "geometry") or {}
        out.append({"id": e.get("id"), "kind": "room", "label": _fv(e, "label"), "labelStatus": _field(e, "label").get("status"),
                    "bbox": g.get("bbox"), "points": len(g.get("outline") or [])})
    if regions and isinstance(data.get("elements"), list) and data.get("unit") in UNIT_MM:
        for g in _kitchen_candidates(data):
            out.append({"id": "region:around=" + ",".join(g["seeds"]), "kind": "region", "label": "Kitchen area around " + ", ".join(g["labels"]),
                        "labelStatus": "derived", "bbox": g["bbox"], "points": 4, "seeds": g["seeds"], "openSides": g["open"]})
    return out


def parse_region(data: dict[str, Any], spec: str) -> dict[str, Any]:
    """'region:kitchen' | 'region:around=id,id' | 'region:bbox=x0,y0,x1,y1' (file units) -> {"bbox", "seeds"|None, "sides"|None}."""
    body = spec[len("region:"):]
    if body == "kitchen":
        cands = _kitchen_candidates(data)
        if len(cands) != 1:
            raise InvalidInput("region:kitchen needs exactly one kitchen area; found " + (", ".join("region:around=" + ",".join(g["seeds"]) for g in cands) or "none"))
        return derive_region(data, cands[0]["seeds"])
    if body.startswith("around="):
        return derive_region(data, [x for x in body[len("around="):].split(",") if x])
    if body.startswith("bbox="):
        try:
            x0, y0, x1, y1 = (float(v) for v in body[len("bbox="):].split(","))
        except ValueError as err:
            raise InvalidInput("region:bbox needs four numbers x0,y0,x1,y1") from err
        if x1 <= x0 or y1 <= y0:
            raise InvalidInput("region:bbox must have x1 > x0 and y1 > y0")
        return {"bbox": [x0, y0, x1, y1], "seeds": None, "sides": None, "unit": data.get("unit")}
    raise InvalidInput(f"Unknown region '{spec}'. Use region:kitchen, region:around=<ids> or region:bbox=x0,y0,x1,y1")


# ---------------------------------------------------------------- trim a room outline where wall elements sit inside it
def _snap_orthogonal(poly: list[tuple[float, float]], slope: float = 0.1) -> list[tuple[float, float]] | None:
    """Make a nearly rectilinear outline exactly axis-parallel (edges share their coordinate); None when an edge is clearly diagonal."""
    n = len(poly)
    gx, gy = list(range(n)), list(range(n))

    def find(g, i):
        while g[i] != i:
            g[i] = g[g[i]]
            i = g[i]
        return i
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
        if dx == 0 and dy == 0:
            continue
        if dy <= slope * dx:
            gy[find(gy, i)] = find(gy, (i + 1) % n)
        elif dx <= slope * dy:
            gx[find(gx, i)] = find(gx, (i + 1) % n)
        else:
            return None
    sx: dict[int, list[float]] = {}
    sy: dict[int, list[float]] = {}
    for i, p in enumerate(poly):
        sx.setdefault(find(gx, i), []).append(p[0])
        sy.setdefault(find(gy, i), []).append(p[1])
    return [(sum(sx[find(gx, i)]) / len(sx[find(gx, i)]), sum(sy[find(gy, i)]) / len(sy[find(gy, i)])) for i in range(n)]


def _inside(pt, poly) -> bool:
    x, y = pt
    c = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            c = not c
    return c


def _trace(cells: set[tuple[int, int]], xs: list[float], ys: list[float]) -> list[tuple[float, float]] | None:
    """Outer boundary (counter-clockwise) of a union of grid cells; None when it has holes, several parts, or touches itself at a corner."""
    nxt: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for (i, j) in cells:
        for a, b, nb in (((i, j), (i + 1, j), (i, j - 1)), ((i + 1, j), (i + 1, j + 1), (i + 1, j)),
                         ((i + 1, j + 1), (i, j + 1), (i, j + 1)), ((i, j + 1), (i, j), (i - 1, j))):
            if nb not in cells:
                nxt.setdefault(a, []).append(b)
    if not nxt or any(len(v) != 1 for v in nxt.values()):
        return None
    start = next(iter(nxt))
    loop, cur = [], start
    while True:
        loop.append(cur)
        cur = nxt[cur][0]
        if cur == start:
            break
        if len(loop) > len(nxt):
            return None
    if len(loop) != len(nxt):
        return None
    pts = [(xs[i], ys[j]) for i, j in loop]
    out = []
    for k, p in enumerate(pts):
        a, b = pts[k - 1], pts[(k + 1) % len(pts)]
        if abs((p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0])) > 1e-9:
            out.append(p)
    return out


def trim_room(poly: list[tuple[float, float]], rects: list[tuple[str, list[float]]], snap: float, min_overlap: float = 0.6,
              max_loss: float = 0.15) -> tuple[list[tuple[float, float]], list[str]]:
    """Cut out of a rectilinear room outline the wall elements that mostly lie inside it and touch its boundary.

    ``rects``: (id, [x0, y0, x1, y1]) of wall elements, file coordinates; their sides within ``snap`` of an outline coordinate are
    taken to coincide with it. A wall is cut only when the result stays one simple region and the room loses at most ``max_loss``
    of its area overall. Returns (outline, ids cut); the original outline and [] when nothing applies.
    """
    base = _snap_orthogonal(list(poly))
    if base is None:
        return list(poly), []
    px, py = sorted({round(p[0], 6) for p in base}), sorted({round(p[1], 6) for p in base})

    def near(v, grid):
        best = min(grid, key=lambda g: abs(g - v))
        return best if abs(best - v) <= snap else round(v, 6)
    snapped = [(i, [near(bb[0], px), near(bb[1], py), near(bb[2], px), near(bb[3], py)]) for i, bb in rects]
    snapped = [(i, r) for i, r in snapped if r[2] > r[0] and r[3] > r[1]]
    xs = sorted({*px, *(c for _, r in snapped for c in (r[0], r[2]))})
    ys = sorted({*py, *(c for _, r in snapped for c in (r[1], r[3]))})
    cell = {(i, j) for i in range(len(xs) - 1) for j in range(len(ys) - 1) if _inside(((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2), base)}
    area = lambda cs: sum((xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j]) for i, j in cs)   # noqa: E731
    room_area, kept, cut = area(cell), set(cell), []
    for wid, r in snapped:
        wc = {(i, j) for i in range(len(xs) - 1) for j in range(len(ys) - 1) if xs[i] >= r[0] and xs[i + 1] <= r[2] and ys[j] >= r[1] and ys[j + 1] <= r[3]}
        inside = wc & kept
        if not inside or area(inside) < min_overlap * (r[2] - r[0]) * (r[3] - r[1]):
            continue
        if not any(nb not in cell for (i, j) in inside for nb in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1))):
            continue                                   # an island inside the room, not a notch of its outline
        trial = kept - wc
        if area(cell) - area(trial) > max_loss * room_area or _trace(trial, xs, ys) is None:
            continue
        kept, cut = trial, cut + [wid]
    if not cut:
        return list(poly), []
    out = _trace(kept, xs, ys)
    if out is None:
        return list(poly), []
    sign = lambda pts: sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))   # noqa: E731
    if sign(out) * sign(list(poly)) < 0:
        out.reverse()
    return out, cut


# ---------------------------------------------------------------- normalize
def normalize(data: dict[str, Any], room_id: str | None = None) -> dict[str, Any]:
    """Validate a floorplan-audited document and return derived scene geometry (mm).

    The result never contains the source document (it is stored once, under ``ref``); everything in it is derived.
    """
    if not isinstance(data, dict) or data.get("kind") != "floorplan-audited":
        raise InvalidInput("Expected a floorplan-audited JSON document")
    warnings: list[dict] = []
    cv = str(data.get("contractVersion", ""))
    if not cv.startswith(SUPPORTED_CONTRACT):
        warnings.append({"code": "contract-version", "message": f"contractVersion '{cv}' was not tested (expected {SUPPORTED_CONTRACT}x)"})
    unit = data.get("unit")
    if unit not in UNIT_MM:
        raise InvalidInput("Floorplan unit must be cm, mm, or m")
    frame_unit = (data.get("frame") or {}).get("unit")
    if frame_unit not in (None, unit):
        raise InvalidInput(f"frame.unit '{frame_unit}' differs from unit '{unit}'")
    k = UNIT_MM[unit]
    vx, vy = _frame_vectors(data)
    elements = data.get("elements")
    if not isinstance(elements, list):
        raise InvalidInput("Floorplan elements must be an array")
    ids = [e.get("id") for e in elements]
    dup = sorted({str(i) for i in ids if ids.count(i) > 1})
    if dup:
        raise InvalidInput("Duplicate element ids: " + ", ".join(dup))

    rooms = [r for r in list_rooms(data) if r["kind"] == "room"]
    region = None
    room_el = None
    if room_id is not None and str(room_id).startswith("region:"):
        region = parse_region(data, str(room_id))
        bb = region["bbox"]
        raw_room = [(bb[0], bb[1]), (bb[2], bb[1]), (bb[2], bb[3]), (bb[0], bb[3])]
        room_label = "Kitchen area (derived from walls)" if region["seeds"] else "Area (given as a box)"
        room_id = "region:around=" + ",".join(region["seeds"]) if region["seeds"] else "region:bbox=" + ",".join(f"{v:g}" for v in bb)
        open_sides = [n for n, sd in (region["sides"] or {}).items() if sd["open"]]
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
        room_el = next(e for e in elements if e.get("id") == room_id)
        room_label = _fv(room_el, "label")
        raw_room = _points(_fv(room_el, "geometry"), room_id)
        rects = [(e["id"], bb) for e in elements if e.get("kind") == "wall" and e.get("id") and (bb := _bbox(e))]
        raw_room, trimmed = trim_room(raw_room, rects, 60.0 / UNIT_MM[data["unit"]])
        if trimmed:
            warnings.append({"code": "room-trimmed", "message": f"the room outline overlapped wall elements {', '.join(trimmed)}; those parts were cut out of the room"})

    # file coordinates -> (right, forward) in mm -> scene (x = right - r0, z = f0 - forward)
    def to_rf(p):
        return ((p[0] * vx[0] + p[1] * vy[0]) * k, (p[0] * vx[1] + p[1] * vy[1]) * k)

    rf = [to_rf(p) for p in raw_room]
    r0, f0 = min(p[0] for p in rf), max(p[1] for p in rf)

    def to_scene(p):
        r, f = to_rf(p)
        return (round(r - r0, 3), round(f0 - f, 3))

    poly = [to_scene(p) for p in raw_room]
    dedup = [p for i, p in enumerate(poly) if p != poly[i - 1]]
    if len(dedup) != len(poly):
        warnings.append({"code": "duplicate-points", "message": f"{room_id}: {len(poly) - len(dedup)} repeated outline point(s) removed"})
    poly = dedup
    if len(poly) < 3 or abs(_area2(poly)) < 1e-3:
        raise InvalidInput(f"{room_id}: outline has zero area")
    if _self_intersects(poly):
        raise InvalidInput(f"{room_id}: outline crosses itself; fix the drawing (nothing was changed)")
    ccw = _area2(poly) > 0

    edges = _room_edges(poly)
    for ed in edges:
        if ed["length"] < 1.0:
            raise InvalidInput(f"{room_id}: outline contains a zero-length edge at point {ed['i']}")
        ed["skew"] = min(_angle_between(ed["dir"], (1, 0)), _angle_between(ed["dir"], (0, 1)))
        if 0.5 < ed["skew"] < 10:
            warnings.append({"code": "skewed-edge", "message": f"edge {ed['i']} is {ed['skew']:.1f} deg off the nearest axis; kept as drawn"})

    # ---- elements in scene coordinates
    prepared = []
    for e in elements:
        if e is room_el:
            continue
        g = _fv(e, "geometry")
        pts = None
        if isinstance(g, dict):
            try:
                pts = [to_scene(p) for p in _points(g, str(e.get("id")))]
            except ValueError as err:
                if isinstance(g.get("bbox"), list) and len(g["bbox"]) == 4:
                    x0, y0, x1, y1 = g["bbox"]
                    pts = [to_scene(p) for p in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
                else:
                    warnings.append({"code": "bad-geometry", "element": e.get("id"), "message": str(err)})
        prepared.append((e, pts))

    # ---- measured walls: they set the thickness of the matching room edge
    wall_for_edge: dict[int, dict] = {}
    max_t = DEFAULT_WALL_THICKNESS
    for e, pts in prepared:
        if e.get("kind") != "wall" or not pts:
            continue
        g = _fv(e, "geometry") or {}
        wd = _long_dir(pts)
        best = None
        for ed in edges:
            if _angle_between(wd, ed["dir"]) > 5.0:
                continue
            alongs = [_dot(_sub(p, ed["a"]), ed["dir"]) for p in pts]
            offs = [-_dot(_sub(p, ed["a"]), ed["n"]) for p in pts]  # outward distance
            ov = max(0.0, min(max(alongs), ed["length"]) - max(min(alongs), 0.0))
            if ov < 0.5 * ed["length"] or abs(min(offs)) > TOL * 2:
                continue
            if best is None or ov > best[0]:
                thick = float(g["thickness"]) * k if isinstance(g.get("thickness"), (int, float)) else max(offs) - min(offs)
                best = (ov, ed["i"], thick)
        if best:
            el = _fv(e, "elev") if isinstance(_fv(e, "elev"), dict) else {}
            height = float(el["height"]) * k if isinstance(el.get("height"), (int, float)) else None
            wall_for_edge.setdefault(best[1], {"element": e.get("id"), "thickness": round(best[2], 3), "height": height})
            max_t = max(max_t, best[2])

    near = max_t + TOL
    retained = []
    for e, pts in prepared:
        kind = e.get("kind")
        el = _fv(e, "elev") if isinstance(_fv(e, "elev"), dict) else None
        rec = {"id": e.get("id"), "kind": kind, "tag": _fv(e, "tag"), "label": _fv(e, "label"),
               "review": {n: _field(e, n).get("status") for n in ("geometry", "tag", "label") if _field(e, n)},
               "elev": {"base": float(el.get("base", 0)) * k, "height": float(el["height"]) * k} if el and isinstance(el.get("height"), (int, float)) else None,
               "outline": [{"x": p[0], "z": p[1]} for p in pts] if pts else None}
        g_raw = _fv(e, "geometry") if isinstance(_fv(e, "geometry"), dict) else {}
        for key in ("swing", "arrow"):
            if isinstance(g_raw.get(key), list):
                try:
                    rec[key] = [{"x": q[0], "z": q[1]} for q in (to_scene(pp) for pp in g_raw[key])]
                except (TypeError, ValueError, IndexError):
                    pass
        if isinstance(g_raw.get("hinge"), list) and len(g_raw["hinge"]) == 2:
            hq = to_scene(g_raw["hinge"])
            rec["hinge"] = {"x": hq[0], "z": hq[1]}
        if not pts:
            rec["membership"], rec["distance"] = "unknown", None
        else:
            rec["membership"], rec["distance"] = _membership(pts, poly, near)
            if rec["membership"] == "outside":
                warnings.append({"code": "outside-room", "element": rec["id"], "kind": kind, "distance": round(rec["distance"]),
                                 "message": f"{rec['id']} ({kind}) lies {rec['distance'] / 10:.0f} cm outside room {room_id}; it probably belongs to another room or area. Kept as data; not placed and not moved."})
        retained.append(rec)

    # ---- walls: inner face = outline edge, the box extends outward
    heights = [w["height"] for w in wall_for_edge.values() if w["height"]]
    height = max(heights) if heights else DEFAULT_WALL_HEIGHT
    height_source = "measured" if heights else "assumed"
    walls = []
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
        w.update(start={"x": round(a[0], 3), "y": 0, "z": round(a[1], 3)}, end={"x": round(b[0], 3), "y": 0, "z": round(b[1], 3)},
                 interiorNormal={"x": round(ed["n"][0], 6), "y": 0, "z": round(ed["n"][1], 6)}, length=round(ed["length"], 3), endExtension=round(ext, 3))

    # ---- openings: attach only when the geometry decides it
    for rec, (e, pts) in zip(retained, prepared):
        if rec["kind"] != "opening":
            continue
        note = []
        rec["attached"] = _attach_opening(e, pts, rec, edges, walls, k, note)
        if rec["attached"] is None:
            rec["note"] = note[0] if note else "not attached"
            if rec["membership"] != "outside":
                warnings.append({"code": "opening-unattached", "element": rec["id"], "message": rec["note"]})

    # ---- review state of what was read
    for fld in ("label", "tag") if room_el is not None else ():
        st = _field(room_el, fld).get("status")
        if st and st not in ("confirmed", "edited"):
            warnings.append({"code": "unreviewed", "element": room_id, "message": f"room {fld} '{_fv(room_el, fld)}' is {st}"})

    counts: dict[str, int] = {}
    for r in retained:
        counts[r["membership"]] = counts.get(r["membership"], 0) + 1
    return {"ref": document_hash(data), "planId": data.get("planId"), "contractVersion": cv,
            "sourceSha256": (data.get("source") or {}).get("sha256"), "sourceUnit": unit,
            "roomId": room_id, "roomLabel": room_label, "rooms": rooms, "region": region,
            "origin": {"unit": unit, "right": r0 / k, "forward": f0 / k, "note": "scene.x = right - origin.right, scene.z = origin.forward - forward (file units)"},
            "outline": [{"x": p[0], "z": p[1]} for p in poly], "width": round(max(p[0] for p in poly), 3), "depth": round(max(p[1] for p in poly), 3),
            "height": height, "heightSource": height_source, "areaM2": round(abs(_area2(poly)) / 2e6, 3),
            "walls": walls, "elements": retained, "counts": counts, "binding": None, "warnings": warnings}


def _membership(pts, poly, near):
    inside = [(_pip(p, poly) or _boundary_dist(p, poly) <= TOL) for p in pts]
    if all(inside):
        return "inside", 0.0
    if _polys_cross(pts, poly) or any(_pip(p, poly) and _boundary_dist(p, poly) > TOL for p in pts) or \
            any(_pip(v, pts) and _boundary_dist(v, pts) > TOL for v in poly):
        return "overlapping", 0.0
    dist = _poly_dist(pts, poly)
    if dist <= near:
        return "adjacent", round(dist, 3)
    return "outside", round(dist, 3)


def _corner_extensions(edges, walls, ccw):
    """How far the end of each wall box runs on over the outside corner of a convex vertex, so per-edge boxes leave no notch."""
    n = len(edges)
    ext = [0.0] * n
    cap = 5 * max(w["thickness"] for w in walls)
    for i in range(n):
        ei, ej = edges[i], edges[(i + 1) % n]
        turn = _cross(ei["dir"], ej["dir"])
        if not (turn > 1e-9 if ccw else turn < -1e-9):
            continue  # reflex vertex: the boxes already overlap
        ni, nj = (-ei["n"][0], -ei["n"][1]), (-ej["n"][0], -ej["n"][1])  # outward normals
        den = _dot(ei["dir"], nj)
        if abs(den) < 1e-6:
            continue
        s = (walls[(i + 1) % n]["thickness"] - walls[i]["thickness"] * _dot(ni, nj)) / den
        ext[i] = max(0.0, min(s, cap))
    return ext


def _attach_opening(e, pts, rec, edges, walls, k, note):
    if not pts:
        note.append("no geometry")
        return None
    tag = rec.get("tag")
    if tag not in ("door", "window"):
        note.append(f"{rec['id']}: opening tag '{tag}' is not door/window; not attached")
        return None
    g = _fv(e, "geometry") or {}
    d = _long_dir(pts)
    cx, cz = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    ext = [_dot(_sub(p, (cx, cz)), d) for p in pts]
    width = float(g["width"]) * k if isinstance(g.get("width"), (int, float)) else max(ext) - min(ext)
    cands = []
    for ed in edges:
        if _angle_between(d, ed["dir"]) > 10.0:
            continue
        along = _dot(_sub((cx, cz), ed["a"]), ed["dir"])
        out = -_dot(_sub((cx, cz), ed["a"]), ed["n"])
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
    el = rec.get("elev") or {}
    entry = {"id": f"{walls[i]['id']}-FP-{rec['id']}", "type": tag, "offset": round(max(0.0, along - width / 2), 3), "width": round(width, 3),
             "height": el.get("height") or (2200.0 if tag == "door" else 1200.0), "sillHeight": el.get("base") or 0.0, "sourceElement": rec["id"]}
    walls[i]["openings"].append(entry)
    return {"wall": walls[i]["id"], "edge": i, "offset": entry["offset"], "width": entry["width"]}


# ---------------------------------------------------------------- back face of a unit next to a wall
def _room_edges(room):
    ccw = _area2(room) > 0
    out = []
    for i, a in enumerate(room):
        b = room[(i + 1) % len(room)]
        d = _norm(_sub(b, a))
        out.append({"i": i, "a": a, "b": b, "dir": d, "n": (-d[1], d[0]) if ccw else (d[1], -d[0]), "length": math.hypot(*_sub(b, a))})
    return out


def _xy(outline):
    return [(p["x"], p["z"]) if isinstance(p, dict) else tuple(p) for p in outline]


def detect_back(outline, fp: dict, gap_tol: float = 100.0, min_len: float = 200.0) -> dict | None:
    """Which side of a unit is its back, i.e. the side lying against a wall of the room.

    The back is the unit's edge that is parallel to a room edge, on the room side of it, within ``gap_tol`` of the wall
    face and overlapping it. Returns None (and no guess) when no side qualifies; ``status`` is 'corner' when a second,
    non-parallel wall qualifies too.
    """
    pts = _xy(outline)
    edges = _room_edges(_xy(fp["outline"]))
    cen = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    found = []
    for j in range(len(pts)):
        p, q = pts[j], pts[(j + 1) % len(pts)]
        ln = math.hypot(*_sub(q, p))
        if ln < min_len:
            continue
        d = _norm(_sub(q, p))
        for ed in edges:
            if _angle_between(d, ed["dir"]) > PARALLEL_DEG:
                continue
            ins = [_dot(_sub(v, ed["a"]), ed["n"]) for v in (p, q)]   # distance into the room
            if min(ins) < -TOL or max(ins) > gap_tol:
                continue
            if _dot(_sub(cen, ed["a"]), ed["n"]) <= max(ins) + 1.0:    # the unit's body must lie on the room side of this face
                continue
            al = sorted(_dot(_sub(v, ed["a"]), ed["dir"]) for v in (p, q))
            ov = min(al[1], ed["length"]) - max(al[0], 0.0)
            if ov < 0.4 * ln:
                continue
            gap = max(0.0, sum(ins) / 2)
            found.append({"elementEdge": j, "roomEdge": ed["i"], "gap": round(gap, 1), "overlap": round(ov, 1), "run": round(ln, 1),
                          "score": ov * (1 - min(gap, gap_tol) / (gap_tol * 1.5)), "facing": {"x": round(ed["n"][0], 6), "z": round(ed["n"][1], 6)},
                          "depth": round(max(_dot(_sub(v, ed["a"]), ed["n"]) for v in pts) - gap, 1)})
    if not found:
        return None
    found.sort(key=lambda r: -r["score"])
    best = found[0]
    other = next((r for r in found[1:] if r["roomEdge"] != best["roomEdge"] and r["score"] >= 0.5 * best["score"]), None)
    conf = 0.95 if best["gap"] <= 20 else 0.85 if best["gap"] <= 50 else 0.7
    if best["overlap"] < 0.9 * best["run"]:
        conf -= 0.1
    best = {k2: v for k2, v in best.items() if k2 != "score"}
    best.update(confidence=round(conf, 2), status="corner" if other else "wall-backed")
    if other:
        best["alsoAgainst"] = other["roomEdge"]
    return best


def detect_element_backs(fp: dict, kinds: tuple[str, ...] = ("furniture",), tags: tuple[str, ...] | None = None) -> list[dict]:
    """detect_back for every retained furniture/cabinet that belongs to the room."""
    out = []
    for e in fp["elements"]:
        if e["kind"] not in kinds or not e.get("outline") or e["membership"] not in ("inside", "overlapping", "adjacent"):
            continue
        if tags and e.get("tag") not in tags:
            continue
        out.append({"element": e["id"], "label": e.get("label"), "back": detect_back(e["outline"], fp)})
    return out


# ---------------------------------------------------------------- binding the kitchen frame to the room
def kitchen_transform(fp: dict, binding: dict) -> dict:
    """Rigid transform kitchen frame -> scene: origin = right-hand corner of the back wall (as seen from inside), +z = into the room."""
    ed = _room_edges(_xy(fp["outline"]))[binding["back"]]
    n = ed["n"]
    right = (n[1], -n[0])           # facing the wall (-n), the right-hand direction
    r_end = max((ed["a"], ed["b"]), key=lambda p: _dot(p, right))
    off = float(binding.get("offset", 0.0))
    origin = (r_end[0] - right[0] * off, r_end[1] - right[1] * off)
    return {"origin": {"x": round(origin[0], 3), "z": round(origin[1], 3)}, "yaw": round(math.degrees(math.atan2(n[0], n[1])), 6),
            "right": {"x": round(right[0], 6), "z": round(right[1], 6)}, "into": {"x": round(n[0], 6), "z": round(n[1], 6)}}


def _perp(e1, e2):
    return abs(_angle_between(e1["dir"], e2["dir"]) - 90.0) <= 10.0


def bind_kitchen(fp: dict, need: dict, back_edge: int | None = None, offset: float = 0.0) -> dict:
    """Choose (or validate) the room edge that carries the back run of the kitchen.

    ``need``: {"back": mm, "right": mm or 0, "left": mm or 0}. Raises ValueError when nothing fits; never stretches or
    moves the room.
    """
    room = _xy(fp["outline"])
    edges = _room_edges(room)
    ccw = _area2(room) > 0
    n_edges = len(edges)
    need_back, need_right, need_left = (float(need.get(k2) or 0.0) for k2 in ("back", "right", "left"))
    backs = {r["back"]["roomEdge"] for r in detect_element_backs(fp, ("furniture",), ("cabinet",)) if r["back"]}
    verdicts = []
    for ed in edges:
        why, warns = [], []
        if need_back > ed["length"] + 5.0:
            why.append(f"edge is {ed['length']:.0f} mm, back run needs {need_back:.0f} mm")
        n = ed["n"]
        right = (n[1], -n[0])
        r_end = max((ed["a"], ed["b"]), key=lambda p: _dot(p, right))
        at_start = r_end == ed["a"]
        nb = edges[(ed["i"] - 1) % n_edges] if at_start else edges[(ed["i"] + 1) % n_edges]
        first, second = (nb, ed) if at_start else (ed, nb)
        turn = _cross(first["dir"], second["dir"])
        convex = turn > 0 if ccw else turn < 0
        if need_right and not (_perp(nb, ed) and convex and nb["length"] + 5.0 >= need_right):
            why.append(f"no perpendicular wall of at least {need_right:.0f} mm at the right-hand corner")
        left_edge = None
        if need_left:
            l_pt = (r_end[0] - right[0] * need_back, r_end[1] - right[1] * need_back)
            left_edge = next((x["i"] for x in edges if x["i"] != ed["i"] and _perp(x, ed) and _seg_dist(l_pt, x["a"], x["b"]) <= TOL and x["length"] + 5.0 >= need_left), None)
            if left_edge is None:
                warns.append("the left run does not stand against a wall")
        score = (need_back / ed["length"]) + (0.5 if ed["i"] in backs else 0.0)
        s_r = _dot(_sub(r_end, ed["a"]), ed["dir"])
        s_l = s_r - need_back * _dot(right, ed["dir"])
        lo, hi = sorted((s_r, s_l))
        for e in fp["elements"]:
            att = e.get("attached")
            if not att or att["edge"] != ed["i"]:
                continue
            if att["offset"] + att["width"] > lo and att["offset"] < hi:
                score -= 1.0 if e.get("tag") == "door" else 0.2
                warns.append(f"{e['id']} ({e.get('tag')}) falls inside the back run")
        verdicts.append({"edge": ed["i"], "ok": not why, "why": why, "warnings": warns, "score": round(score, 3),
                         "right": nb["i"] if need_right else None, "left": left_edge})
    if back_edge is not None:
        chosen = next((x for x in verdicts if x["edge"] == back_edge), None)
        if chosen is None:
            raise InvalidInput(f"edge {back_edge} does not exist (0..{n_edges - 1})")
        if not chosen["ok"]:
            raise InvalidInput(f"edge {back_edge} cannot carry the kitchen: " + "; ".join(chosen["why"]))
        source = "manual"
    else:
        ok = sorted((x for x in verdicts if x["ok"]), key=lambda x: -x["score"])
        if not ok:
            raise InvalidInput("The kitchen does not fit any wall of the room: " + "; ".join(f"edge {x['edge']}: {', '.join(x['why'])}" for x in verdicts)[:700], code="kitchen-fits-no-wall")
        chosen, source = ok[0], "auto"
        if len(ok) > 1 and abs(ok[0]["score"] - ok[1]["score"]) < 0.05:
            chosen = {**chosen, "warnings": [*chosen["warnings"], f"edge {ok[1]['edge']} fits equally well; pass back_edge to choose"]}
    b = {"back": chosen["edge"], "right": chosen["right"], "left": chosen["left"], "offset": float(offset), "source": source, "score": chosen["score"], "warnings": chosen["warnings"],
         "need": {"back": need_back, "right": need_right, "left": need_left}}
    b["transform"] = kitchen_transform(fp, b)
    return b


def apply_binding(doc: dict, fp: dict, binding: dict) -> None:
    """Move the kitchen content of a three.js document from the kitchen frame into the floorplan room (in place)."""
    t = binding.get("transform") or kitchen_transform(fp, binding)
    pl = Placement.from_transform(t)

    def vec(v):  # direction (rotation about +Y, same convention as three.js)
        x, z = pl.dir_to_room(v["x"], v["z"])
        return {**v, "x": round(x, 6), "z": round(z, 6)}

    def pos(v):
        w = vec(v)
        return {**v, "x": round(w["x"] + pl.ox, 3), "z": round(w["z"] + pl.oz, 3)}

    def wrap(a):
        a = round(a % 360, 6)
        return a - 360 if a > 180 else a

    for sect in ("modules", "appliances", "accessories", "decorations"):
        for e in doc.get(sect, []):
            tf = e.get("transform")
            if tf:
                tf["position"] = pos(tf["position"])
                rot = tf.setdefault("rotation", {"x": 0, "y": 0, "z": 0, "unit": "deg"})
                rot["y"] = wrap(rot.get("y", 0) + t["yaw"])
    for cam in doc.get("cameras", []):
        for key in ("position", "target"):
            if cam.get(key):
                cam[key] = pos(cam[key])
    cs = doc.get("coordinateSystem") or {}
    for wf in cs.get("wallFrames", []):
        wf["origin"], wf["alongAxis"], wf["frontAxis"] = pos(wf["origin"]), vec(wf["alongAxis"]), vec(wf["frontAxis"])
        wf["rotationY"] = wrap(wf.get("rotationY", 0) + t["yaw"])
    if cs:
        cs["origin"] = "room_corner"
        cs["notes"] = (cs.get("notes", "") + f" Đã đặt vào phòng của mặt bằng: gốc là góc phải của tường sau bếp, xoay {t['yaw']:.1f} độ.").strip()


# ---------------------------------------------------------------- every drawn element -> 3D structures
STRUCTURE_COLORS = {"wall": "#E7E2D5", "column": "#F2B65D", "opening": "#55C6A9", "furniture": "#D38662", "shaft": "#8C83D6",
                    "stair": "#CFAE52", "area": "#7D9EAA"}
STAIR_STEPS = 10
STAIR_RISE = 1800.0


def default_height(rec: dict) -> float:
    """Height for an element that has none in the drawing (flagged heightSource 'assumed')."""
    kind, tag, label = rec["kind"], rec.get("tag") or "", (rec.get("label") or "").lower()
    if kind in ("wall", "column", "shaft"):
        return DEFAULT_WALL_HEIGHT
    if kind == "opening":
        return 2200.0
    if kind == "stair":
        return STAIR_RISE
    if kind == "furniture":
        if "vách tv" in label:
            return 2400.0
        if "rượu" in label:
            return 2100.0
        return 900.0
    return 0.0


def structures(fp: dict) -> list[dict]:
    """Every retained element (all the walls included) as an extruded outline in scene coordinates."""
    out = []
    for e in fp["elements"]:
        if not e.get("outline"):
            continue
        el = e.get("elev") or {}
        measured = bool(el.get("height"))
        h = float(el["height"]) if measured else default_height(e)
        rec = {"id": f"STRUCT-{e['id']}", "sourceElement": e["id"], "kind": e["kind"], "tag": e.get("tag") or e["kind"],
               "outline": [{"x": p["x"], "z": p["z"]} for p in e["outline"]], "base": float((el or {}).get("base", 0.0)), "height": h,
               "heightSource": "measured" if measured else "assumed", "color": STRUCTURE_COLORS.get(e["kind"], "#9BA8B5"),
               "membership": e["membership"]}
        if e.get("label"):
            rec["label"] = e["label"]
        for key in ("swing", "arrow", "hinge"):
            if e.get(key):
                rec[key] = e[key]
        if e["kind"] == "stair":
            rec["steps"] = STAIR_STEPS
        out.append(rec)
    return out


# ---------------------------------------------------------------- the 3D file: what threejs_export takes from a floorplan
def _v3(p: dict) -> dict:
    return {"x": p["x"], "y": 0, "z": p["z"]}


def resolve_binding(fp: dict, need: dict | None) -> dict | None:
    """The stored binding, else an automatic one when the design has cabinets (``need`` = run lengths), else None.

    Raises ValueError when the kitchen fits no wall: a wrong scene is never produced.
    """
    if fp.get("binding"):
        return fp["binding"]
    return bind_kitchen(fp, need) if need else None


def room_section(fp: dict, binding: dict | None, wall_material: str, structs: list | None = None) -> dict:
    """Pieces of the three.js ``room``: size, floor outline, wall data (``visible`` False: anchors and openings only) and structures."""
    names = {}
    if binding:
        names = {binding["back"]: "WALL-BACK"}
        if binding.get("right") is not None:
            names.setdefault(binding["right"], "WALL-RIGHT")
        if binding.get("left") is not None:
            names.setdefault(binding["left"], "WALL-LEFT")
    walls = []
    for w in fp["walls"]:
        wid = names.get(w["edge"], w["id"])
        walls.append({"id": wid, "start": _v3(w["start"]), "end": _v3(w["end"]), "height": w["height"], "thickness": w["thickness"],
                      "thicknessSource": w["thicknessSource"], "visible": False, "materialId": wall_material, "interiorNormal": _v3(w["interiorNormal"]),
                      "openings": [{"id": f"{wid}-O{i + 1}", "type": "window" if o.get("type") == "window" else "door", "offset": o["offset"],
                                    "width": o["width"], "height": o["height"], "sillHeight": o.get("sillHeight", 0)} for i, o in enumerate(w["openings"])]})
    out_structs = []
    for st in (structs if structs is not None else structures(fp)):
        d = dict(st)
        for key in ("swing", "arrow"):
            if key in d:
                d[key] = [_v3(q) for q in d[key]]
        if "hinge" in d:
            d["hinge"] = _v3(d["hinge"])
        out_structs.append(d)
    return {"width": fp["width"], "depth": fp["depth"], "floorOutline": [{"x": q["x"], "z": q["z"]} for q in fp["outline"]],
            "walls": walls, "structures": out_structs}


def finish_document(doc: dict, fp: dict, binding: dict | None) -> None:
    """After the document is built: drop references to walls that do not exist, record the floorplan, move the kitchen into the room."""
    ids = {w["id"] for w in doc["room"]["walls"]}
    for md in doc["modules"]:
        placement = md.get("placement", {})
        if placement.get("wallId") not in ids:
            placement.pop("wallId", None)
    doc["coordinateSystem"]["wallFrames"] = [wf for wf in doc["coordinateSystem"]["wallFrames"] if wf["wallId"] in ids]
    doc["metadata"]["floorplan"] = {"ref": fp["ref"], "roomId": fp["roomId"], "roomLabel": fp.get("roomLabel"), "warnings": fp["warnings"][:50],
                                    **({"binding": {k: binding[k] for k in ("back", "right", "left", "offset", "source", "score", "warnings")}} if binding else {})}
    if binding:
        apply_binding(doc, fp, binding)
