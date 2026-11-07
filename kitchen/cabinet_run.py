"""Cabinet templates: a straight ("I") run of base cabinets standing against one edge of an object, doors facing away from it.

Pure. Everything here is in the KITCHEN frame (origin at the right-hand corner of the back wall, +z into the room, x runs towards the
left wall as -x); the caller maps the object's outline from the room into that frame with ``placement``. The result is one ``multi``
(or ``add``) operation for ``service.propose``: nothing is saved here.
"""
from __future__ import annotations

import math
from typing import Any

from .edit import combine_ops, next_run_id
from .errors import InvalidInput
from .floorplan.geom import point_in_poly
from .numeric import round_half_away
from . import runs as runmod
from .spec import KitchenSpec

MODULE_WIDTH = 600.0         # preferred cabinet width
MIN_WIDTH = 300.0            # narrowest cabinet we make
MAX_RUN = 6000.0             # longest run made in one go
AXIS_TOLERANCE_DEG = 1.5     # an edge this close to an axis counts as parallel to it
Pt = tuple[float, float]


def _nearest_edge(poly: list[Pt], p: Pt) -> tuple[Pt, Pt]:
    best, best_d = (poly[0], poly[1]), float("inf")
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        ex, ez = b[0] - a[0], b[1] - a[1]
        n2 = ex * ex + ez * ez
        if n2 < 1e-9:
            continue
        t = max(0.0, min(1.0, ((p[0] - a[0]) * ex + (p[1] - a[1]) * ez) / n2))
        d = math.hypot(p[0] - (a[0] + t * ex), p[1] - (a[1] + t * ez))
        if d < best_d:
            best, best_d = (a, b), d
    return best


def _is_diagonal(a: Pt, b: Pt) -> bool:
    angle = math.degrees(math.atan2(abs(b[1] - a[1]), abs(b[0] - a[0])))
    return AXIS_TOLERANCE_DEG < angle < 90 - AXIS_TOLERANCE_DEG


def _outward(poly: list[Pt], a: Pt, b: Pt) -> Pt:
    """Unit normal of the edge pointing out of the object (the way the doors must look)."""
    ex, ez = b[0] - a[0], b[1] - a[1]
    length = math.hypot(ex, ez)
    if length < 1.0:
        raise InvalidInput("The edge is too short", code="edge-too-short")
    nx, nz = -ez / length, ex / length
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    probe = 5.0
    if not point_in_poly((mid[0] + nx * probe, mid[1] + nz * probe), poly):
        return nx, nz
    if not point_in_poly((mid[0] - nx * probe, mid[1] - nz * probe), poly):
        return -nx, -nz
    raise InvalidInput("Both sides of this edge are inside the object", code="edge-inside")


def _plan_angled(spec: KitchenSpec, outline: list[Pt], a: Pt, b: Pt, module_type: str) -> dict[str, Any]:
    """A run along an edge at any angle: one explicit run (origin on the edge, doors along the outward normal) and the cabinets in it."""
    nx, nz = _outward(outline, a, b)
    yaw = math.degrees(math.atan2(nx, nz))                       # doors look along (sin yaw, cos yaw)
    ux, uz = nz, -nx                                              # s direction = (cos yaw, -sin yaw)
    start, end = (a, b) if (b[0] - a[0]) * ux + (b[1] - a[1]) * uz >= 0 else (b, a)
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    widths = split_widths(length)
    c = spec.common
    depth = float(c.baseDepth)
    run = {"id": next_run_id(spec), "x": float(round_half_away(start[0], 1)), "z": float(round_half_away(start[1], 1)), "yaw": float(round_half_away(yaw, 2))}
    ops: list[dict[str, Any]] = [{"op": "add-run", "run": run}]
    at = 0.0
    for w in widths:
        ops.append({"op": "add", "closeGap": False, "module": {"type": module_type, "wall": "island", "run": run["id"], "fromCorner": at, "width": w,
                                                                "y": 0, "height": float(c.baseTop), "depth": depth}})
        at += w
    return {"operation": combine_ops(ops), "facing": None, "run": run, "yaw": run["yaw"], "length": sum(widths), "widths": widths,
            "summary": [f"{len(widths)} base cabinets, {sum(widths):g} mm, along an edge at {run['yaw']:g}° (run {run['id']})"]}


def _facing(poly: list[Pt], a: Pt, b: Pt) -> str:
    """The side of the edge away from the object: the direction the doors must look."""
    ex, ez = b[0] - a[0], b[1] - a[1]
    length = math.hypot(ex, ez)
    if length < 1.0:
        raise InvalidInput("The edge is too short", code="edge-too-short")
    angle = math.degrees(math.atan2(abs(ez), abs(ex)))
    if AXIS_TOLERANCE_DEG < angle < 90 - AXIS_TOLERANCE_DEG:
        raise InvalidInput("This edge is diagonal; runs can only stand along an edge parallel to a wall", code="diagonal-edge")
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    nx, nz = (0.0, 1.0) if angle <= AXIS_TOLERANCE_DEG else (1.0, 0.0)          # edge along x -> normal along z, and the other way round
    probe = 5.0
    if not point_in_poly((mid[0] + nx * probe, mid[1] + nz * probe), poly):
        sign = 1
    elif not point_in_poly((mid[0] - nx * probe, mid[1] - nz * probe), poly):
        sign = -1
    else:
        raise InvalidInput("Both sides of this edge are inside the object", code="edge-inside")
    if nz:
        return "+z" if sign > 0 else "-z"
    return "+x" if sign > 0 else "-x"


def split_widths(length: float) -> list[float]:
    """Whole-mm cabinet widths filling ``length``: 600s, and a remainder under 300 widens the last one."""
    length = float(round_half_away(min(length, MAX_RUN), 0))
    if length < MIN_WIDTH:
        raise InvalidInput(f"The run would be {length:g} mm; the narrowest cabinet is {MIN_WIDTH:g} mm", code="run-too-short")
    n = int(length // MODULE_WIDTH)
    rest = length - n * MODULE_WIDTH
    if n == 0:
        return [length]
    widths = [MODULE_WIDTH] * n
    if rest >= MIN_WIDTH:
        widths.append(rest)
    else:
        widths[-1] += rest
    return widths


def plan_i_run(spec: KitchenSpec, outline: list[Pt], point: Pt, module_type: str = "base") -> dict[str, Any]:
    """An I-shaped run along the edge of ``outline`` nearest to ``point`` (both in the kitchen frame, mm)."""
    if len(outline) < 3:
        raise InvalidInput("The object has no outline", code="no-outline")
    a, b = _nearest_edge(outline, point)
    if _is_diagonal(a, b):
        return _plan_angled(spec, outline, a, b, module_type)
    facing = _facing(outline, a, b)
    c = spec.common
    depth = float(c.baseDepth)
    along_x = facing in ("-z", "+z")
    lo, hi = (min(a[0], b[0]), max(a[0], b[0])) if along_x else (min(a[1], b[1]), max(a[1], b[1]))
    fixed = a[1] if along_x else a[0]                       # z of the edge for runs along x, x of the edge for runs along z
    notes: list[str] = []
    if along_x:                                             # fromCorner counts from x = 0 towards -x
        start, end = -hi, -lo
    else:                                                   # fromCorner counts from the back wall (z = 0)
        start, end = lo, hi
    if start < 0:
        notes.append(f"Trimmed {-start:g} mm that lies behind the kitchen's origin")
        start = 0.0
    offset = {"-z": fixed - depth, "+z": fixed + depth, "-x": depth - fixed, "+x": -(fixed + depth)}[facing]
    if end - start < MIN_WIDTH or offset < 0:
        # fromCorner and offset cannot be negative, so the wall-parallel form only covers the quadrant left of the right-hand corner and in
        # front of the back wall. Anywhere else (beside the kitchen, behind it) the same cabinets stand in an explicit run at that place.
        plan = _plan_angled(spec, outline, a, b, module_type)
        return {**plan, "facing": facing, "summary": [*plan["summary"], "This edge lies outside the area measured from the kitchen's corner, so the cabinets stand in a free run"]}
    widths = split_widths(end - start)
    ops: list[dict[str, Any]] = []
    at = float(round_half_away(start, 0))
    for w in widths:
        ops.append({"op": "add", "closeGap": False, "module": {"type": module_type, "wall": "island", "facing": facing, "offset": float(round_half_away(offset, 0)),
                                                                "fromCorner": at, "width": w, "y": 0, "height": float(c.baseTop), "depth": depth}})
        at += w
    where = {"-z": "-z (towards the back wall)", "+z": "+z (into the room)", "-x": "-x", "+x": "+x"}[facing]
    return {"operation": combine_ops(ops), "facing": facing, "length": sum(widths), "widths": widths,
            "summary": [f"{len(widths)} base cabinets, {sum(widths):g} mm, doors facing {where}", *notes]}


def _meet(fa: runmod.RunFrame, fb: runmod.RunFrame) -> Pt:
    """Where the back lines (d = 0) of two runs cross."""
    ax, az = fa.to_world(1.0, 0.0)
    bx, bz = fb.to_world(1.0, 0.0)
    ua = (ax - fa.x, az - fa.z)
    ub = (bx - fb.x, bz - fb.z)
    den = ua[0] * ub[1] - ua[1] * ub[0]
    if abs(den) < 1e-6:
        raise InvalidInput("The two runs are parallel, so they never meet", code="runs-parallel")
    t = ((fb.x - fa.x) * ub[1] - (fb.z - fa.z) * ub[0]) / den
    return fa.x + t * ua[0], fa.z + t * ua[1]


def plan_corner(spec: KitchenSpec, run_a: str, run_b: str, width: float = 900.0, module_type: str = "base") -> dict[str, Any]:
    """A special corner cabinet where run ``run_a`` (its s grows towards the corner) meets run ``run_b`` (its s grows away from it), at any angle.

    The cabinet is one box on the bisector of the two back lines, its front square to the bisector, its back corners on the two walls. It is a
    run of its own. Nothing of the two runs is moved: ``clearance`` says how far run A may extend (``aMaxEnd``) and where run B may start
    (``bMinStart``) without touching the corner cabinet, and the summary says so when a run is currently longer; the overlap check of
    ``propose`` reports the same thing as a collision.
    """
    frames = runmod.frames(spec)
    if run_a not in frames or run_b not in frames:
        raise InvalidInput("Both runs must exist", code="run-not-found")
    if not MIN_WIDTH <= width <= 1500:
        raise InvalidInput(f"The corner cabinet width must be {MIN_WIDTH:g}-1500 mm", code="bad-corner-width")
    fa, fb = frames[run_a], frames[run_b]
    px, pz = _meet(fa, fb)
    ax, az = fa.to_world(1.0, 0.0)
    bx, bz = fb.to_world(1.0, 0.0)
    ua, ub = (ax - fa.x, az - fa.z), (bx - fb.x, bz - fb.z)
    mx, mz = ub[0] - ua[0], ub[1] - ua[1]                     # along the wall of B away from the corner + along the wall of A away from it
    norm = math.hypot(mx, mz)
    if norm < 1e-6:
        raise InvalidInput("The runs are collinear, so there is no corner", code="runs-parallel")
    mx, mz = mx / norm, mz / norm
    na = fa.normal()
    if mx * na[0] + mz * na[1] <= 0.05:
        raise InvalidInput("This is an outside corner; the corner cabinet needs the runs to enclose the room side", code="outside-corner")
    cos_phi = max(-1.0, min(1.0, -(ua[0] * ub[0] + ua[1] * ub[1])))          # angle between the two wall rays leaving the corner
    phi = math.acos(cos_phi)
    if not math.radians(20) < phi < math.radians(170):
        raise InvalidInput("The angle between the runs must be between 20 and 170 degrees", code="bad-corner-angle")
    depth = float(spec.common.baseDepth)
    back = width / (2.0 * math.tan(phi / 2.0))                # distance of the cabinet's back from the corner so its back corners touch both walls
    yaw = math.degrees(math.atan2(mx, mz))
    c, sn = runmod.trig(yaw)
    ox = px + back * mx - (width / 2.0) * c
    oz = pz + back * mz + (width / 2.0) * sn
    run = {"id": next_run_id(spec), "x": float(round_half_away(ox, 1)), "z": float(round_half_away(oz, 1)), "yaw": float(round_half_away(yaw, 2))}
    cf = runmod.RunFrame(run["id"], run["x"], run["z"], run["yaw"])
    box = cf.footprint(0.0, width, 0.0, depth)
    depth_a = max((m.depth for m in spec.module if m.run == run_a), default=depth)
    depth_b = max((m.depth for m in spec.module if m.run == run_b), default=depth)
    ea, eb = runmod.strip_extent(box, fa, depth_a), runmod.strip_extent(box, fb, depth_b)
    a_max = ea[0] if ea else None
    b_min = eb[1] if eb else None
    notes: list[str] = []
    a_end = max((m.endAt for m in spec.module if m.run == run_a), default=0.0)
    b_start = min((m.fromCorner for m in spec.module if m.run == run_b), default=0.0)
    if a_max is not None and a_end > a_max + 1:
        notes.append(f"Run {run_a} ends at {a_end:g} mm but must end by {a_max:g} mm to clear the corner cabinet")
    if b_min is not None and b_start < b_min - 1:
        notes.append(f"Run {run_b} starts at {b_start:g} mm but must start from {b_min:g} mm to clear the corner cabinet")
    ops: list[dict[str, Any]] = [{"op": "add-run", "run": run},
                                 {"op": "add", "closeGap": False, "module": {"type": module_type, "name": "Corner cabinet", "wall": "island", "run": run["id"], "fromCorner": 0.0,
                                                                              "width": float(width), "y": 0, "height": float(spec.common.baseTop), "depth": depth, "doors": [float(width)]}}]
    return {"operation": combine_ops(ops), "run": run, "angle": float(round_half_away(math.degrees(phi), 1)),
            "clearance": {"aMaxEnd": a_max, "bMinStart": b_min},
            "summary": [f"Corner cabinet {width:g} mm at {math.degrees(phi):.1f}° (run {run['id']})", *notes]}
