"""Cabinet templates: a straight ("I") run of base cabinets standing against one edge of an object, doors facing away from it.

Pure. Everything here is in the KITCHEN frame (origin at the right-hand corner of the back wall, +z into the room, x runs towards the
left wall as -x); the caller maps the object's outline from the room into that frame with ``placement``. The result is one ``multi``
(or ``add``) operation for ``service.propose``: nothing is saved here.
"""
from __future__ import annotations

import math
from typing import Any

from . import builtin, defaults
from .catalog import Catalog
from .edit import combine_ops, next_run_id
from .errors import InvalidInput
from .floorplan.geom import point_in_poly
from .numeric import round_half_away
from . import runs as runmod
from .run_line import Line, nearest_edge as _nearest_edge, outward as _outward, plan_on_line, run_frame
from .spec import KitchenSpec, LaidModule

MODULE_WIDTH = defaults.BUILTIN.module_width     # preferred cabinet width (catalog kind defaults: the functions take the merged catalog)
MIN_WIDTH = defaults.BUILTIN.min_width           # narrowest cabinet we make
MAX_RUN = defaults.BUILTIN.max_run               # longest run made in one go
AXIS_TOLERANCE_DEG = 1.5     # an edge this close to an axis counts as parallel to it
Pt = tuple[float, float]


def _is_diagonal(a: Pt, b: Pt) -> bool:
    angle = math.degrees(math.atan2(abs(b[1] - a[1]), abs(b[0] - a[0])))
    return AXIS_TOLERANCE_DEG < angle < 90 - AXIS_TOLERANCE_DEG


def _plan_angled(spec: KitchenSpec, outline: list[Pt], a: Pt, b: Pt, module_type: str, system: str | None = None,
                 catalog: Catalog = builtin.CATALOG) -> dict[str, Any]:
    """A run along an edge at any angle: one explicit run (origin on the edge, doors along the outward normal) and the cabinets in it."""
    line = Line(a, b, _outward(outline, a, b))
    widths = split_widths(run_frame(line)["length"], catalog)
    c = spec.common
    at = 0.0
    modules: list[LaidModule] = []
    for w in widths:
        modules.append({"type": module_type, "width": w, "s": at, "y": 0, "height": float(c.baseTop), "depth": float(c.baseDepth)})
        at += w
    plan = plan_on_line(spec, line, modules, system=system)
    return {"operation": plan["operation"], "facing": None, "run": plan["run"], "yaw": plan["run"]["yaw"], "length": sum(widths), "widths": widths,
            "summary": [f"{len(widths)} base cabinets, {sum(widths):g} mm, along an edge at {plan['run']['yaw']:g}° (run {plan['run']['id']})"]}


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


def split_widths(length: float, catalog: Catalog = builtin.CATALOG) -> list[float]:
    """Whole-mm cabinet widths filling ``length``: 600s, and a remainder under 300 widens the last one (sizes: catalog kind defaults)."""
    d = defaults.of(catalog)
    length = float(round_half_away(min(length, d.max_run), 0))
    if length < d.min_width:
        raise InvalidInput(f"The run would be {length:g} mm; the narrowest cabinet is {d.min_width:g} mm", code="run-too-short")
    n = int(length // d.module_width)
    rest = length - n * d.module_width
    if n == 0:
        return [length]
    widths = [d.module_width] * n
    if rest >= d.min_width:
        widths.append(rest)
    else:
        widths[-1] += rest
    return widths


def plan_i_run(spec: KitchenSpec, outline: list[Pt], point: Pt, module_type: str = "base", system: str | None = None,
               catalog: Catalog = builtin.CATALOG) -> dict[str, Any]:
    """An I-shaped run along the edge of ``outline`` nearest to ``point`` (both in the kitchen frame, mm): always one explicit run, its back on
    the edge, doors looking away from the object. ``facing`` (-z / +z / -x / +x) is reported for an edge parallel to a wall, None otherwise.
    ``system``: the cabinet system the new run belongs to (the floorplan element the edge belongs to)."""
    if len(outline) < 3:
        raise InvalidInput("The object has no outline", code="no-outline")
    a, b = _nearest_edge(outline, point)
    plan = _plan_angled(spec, outline, a, b, module_type, system, catalog)
    if not _is_diagonal(a, b):
        facing = _facing(outline, a, b)
        where = {"-z": "-z (towards the back wall)", "+z": "+z (into the room)", "-x": "-x", "+x": "+x"}[facing]
        plan = {**plan, "facing": facing, "summary": [f"{len(plan['widths'])} base cabinets, {plan['length']:g} mm, doors facing {where} (run {plan['run']['id']})"]}
    return plan


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


def plan_corner(spec: KitchenSpec, run_a: str, run_b: str, width: float = 900.0, module_type: str = "base",
                catalog: Catalog = builtin.CATALOG) -> dict[str, Any]:
    """A special corner cabinet where run ``run_a`` (its s grows towards the corner) meets run ``run_b`` (its s grows away from it), at any angle.

    The cabinet is one box on the bisector of the two back lines, its front square to the bisector, its back corners on the two walls. It is a
    run of its own. Nothing of the two runs is moved: ``clearance`` says how far run A may extend (``aMaxEnd``) and where run B may start
    (``bMinStart``) without touching the corner cabinet, and the summary says so when a run is currently longer; the overlap check of
    ``propose`` reports the same thing as a collision.
    """
    frames = runmod.frames(spec)
    if run_a not in frames or run_b not in frames:
        raise InvalidInput("Both runs must exist", code="run-not-found")
    d = defaults.of(catalog)
    if not d.min_width <= width <= d.corner_max_width:
        raise InvalidInput(f"The corner cabinet width must be {d.min_width:g}-{d.corner_max_width:g} mm", code="bad-corner-width")
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
    run: dict[str, Any] = {"id": next_run_id(spec), "x": float(round_half_away(ox, 1)), "z": float(round_half_away(oz, 1)), "yaw": float(round_half_away(yaw, 2))}
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


# ---- replacing a floorplan object (furniture) with cabinets: the runs stand on the object's edges against a wall (wall_line.replace_lines)

SHALLOW = 350.0      # mm: an object this shallow or shallower also sets the depth of wall cabinets and the loft row


def fit_depth(modules: list[LaidModule], depth: float) -> list[LaidModule]:
    """The cabinets made as deep as the object they replace: base and tall cabinets always; wall cabinets and the loft row only when the
    object is ``SHALLOW`` or shallower (otherwise they keep their own depth)."""
    out: list[LaidModule] = []
    for m in modules:
        n = m.copy()
        if not str(m["type"]).startswith("upper") or depth <= SHALLOW:
            n["depth"] = float(depth)
        out.append(n)
    return out


def plan_replace(spec: KitchenSpec, element: str, placed: list[Any], laid: list[list[LaidModule]],
                 after: list[dict[str, Any]] | None = None, run_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """The operation that replaces floorplan element ``element`` with cabinets: one run per ``placed`` (``wall_line.Placed``) holding
    ``laid[i]`` (cabinets as ``plan_on_line`` takes them, already as deep as they should be), each run in system ``element``; then the
    cabinets made against that element before (its old system) are removed, and the element is marked replaced (no longer built).
    The new cabinets go in before the old ones go out (a run left empty is removed with its last cabinet)."""
    from .edit import apply_op
    from .run_line import Line
    if not placed:
        raise InvalidInput("No edge of this object is long enough for a run (600 mm)", code="edge-too-short")
    ops: list[dict[str, Any]] = []
    made: list[dict[str, Any]] = []
    summary: list[str] = []
    current = spec
    for p, modules in zip(placed, laid):
        plan = plan_on_line(current, Line(p.a, p.b, p.doors), modules, system=element, run_fields=run_fields)
        ops.append(plan["operation"])
        made.append(plan["run"])
        summary.append(f"Run {plan['run']['id']}{' (TV unit)' if (run_fields or {}).get('purpose') == 'tv' else ''}: {len(modules)} cabinets, {p.length:.0f} mm long, {p.depth:.0f} mm deep, back on edge {p.edge} against the wall")
        current = apply_op(current, {"op": "add-run", "run": plan["run"]})
    old_system = runmod.systems(spec)
    old = [m.id for m in spec.module if old_system.get(m.id) == element]
    gone = [a.name or a.id for a in spec.appliances if a.module in set(old)]
    ops.extend({"op": "remove", "id": i, "closeGap": False} for i in old)
    ops.extend(after or [])
    ops.append({"op": "replace-element", "id": element, "replaced": True})
    summary.insert(0, f"{element} is replaced by {len(made)} run(s) of cabinets and is no longer drawn")
    if old:
        summary.append(f"The cabinets made against {element} before are removed: {', '.join(old)}")
    if gone:
        summary.append(f"Appliances removed with them: {', '.join(gone)}")
    return {"operation": combine_ops(ops), "runs": made, "removed": old, "appliancesRemoved": gone, "summary": summary,
            "length": float(round_half_away(sum(p.length for p in placed), 1))}
