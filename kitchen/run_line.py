"""A line is the back of a run of cabinets: two points and the side the doors look at. From a line the run frame and the cabinets on it follow.

Pure plane math (rule R1), everything in the KITCHEN frame (mm). The sources of a line (the nearest edge of a floor-plan object, a wall, two
points the user draws, a run read from a photo) all end up as the same ``Line``; ``run_frame`` gives the explicit run (``spec.runs``) that stands on
it and ``plan_on_line`` the operation that puts cabinets in that run. ``cabinet_run`` (templates) and ``recognition.operation`` (photos) build on it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .edit import combine_ops, next_run_id
from .errors import InvalidInput
from .floorplan.geom import point_in_poly
from .numeric import round_half_away
from .spec import KitchenSpec

Pt = tuple[float, float]
MIN_LENGTH = 1.0


@dataclass(frozen=True)
class Line:
    """The back of a run from ``a`` to ``b``; ``normal`` is the unit vector the doors look along (perpendicular to the line)."""
    a: Pt
    b: Pt
    normal: Pt


def nearest_edge(poly: list[Pt], p: Pt) -> tuple[Pt, Pt]:
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


def outward(poly: list[Pt], a: Pt, b: Pt) -> Pt:
    """Unit normal of the edge pointing out of the object (the way the doors must look)."""
    ex, ez = b[0] - a[0], b[1] - a[1]
    length = math.hypot(ex, ez)
    if length < MIN_LENGTH:
        raise InvalidInput("The edge is too short", code="edge-too-short")
    nx, nz = -ez / length, ex / length
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    probe = 5.0
    if not point_in_poly((mid[0] + nx * probe, mid[1] + nz * probe), poly):
        return nx, nz
    if not point_in_poly((mid[0] - nx * probe, mid[1] - nz * probe), poly):
        return -nx, -nz
    raise InvalidInput("Both sides of this edge are inside the object", code="edge-inside")


def edge_line(poly: list[Pt], point: Pt) -> Line:
    """The line along the edge of ``poly`` nearest to ``point``, doors facing away from the object."""
    if len(poly) < 3:
        raise InvalidInput("The object has no outline", code="no-outline")
    a, b = nearest_edge(poly, point)
    return Line(a, b, outward(poly, a, b))


def run_frame(line: Line) -> dict[str, float]:
    """The explicit run standing on the line: origin at the start (the end the run's ``s`` grows away from), ``yaw`` so the doors look along the
    normal, and ``length``. ``s`` grows to the right of someone standing in front of the doors."""
    nx, nz = line.normal
    yaw = math.degrees(math.atan2(nx, nz))                       # doors look along (sin yaw, cos yaw)
    ux, uz = nz, -nx                                              # s direction = (cos yaw, -sin yaw)
    a, b = line.a, line.b
    start, end = (a, b) if (b[0] - a[0]) * ux + (b[1] - a[1]) * uz >= 0 else (b, a)
    return {"x": float(round_half_away(start[0], 1)), "z": float(round_half_away(start[1], 1)), "yaw": float(round_half_away(yaw, 2)),
            "length": math.hypot(end[0] - start[0], end[1] - start[1])}


def plan_on_line(spec: KitchenSpec, line: Line, modules: list[dict[str, Any]], clear: list[str] | None = None) -> dict[str, Any]:
    """The operation that puts ``modules`` in a new run on ``line``. Each module is ``{"type", "width", "s", "y", "height", "depth", "name"?}`` with
    ``s`` measured along the run from its start. ``clear``: ids of cabinets to remove first (replace instead of add)."""
    frame = run_frame(line)
    run = {"id": next_run_id(spec), "x": frame["x"], "z": frame["z"], "yaw": frame["yaw"]}
    ops: list[dict[str, Any]] = [{"op": "remove", "id": module_id, "closeGap": False} for module_id in clear or []]
    ops.append({"op": "add-run", "run": run})
    reach = 0.0
    for m in sorted(modules, key=lambda item: item["s"]):
        entry = {"type": m["type"], "wall": "island", "run": run["id"], "fromCorner": float(m["s"]), "width": float(m["width"]), "y": float(m["y"]),
                 "height": float(m["height"]), "depth": float(m["depth"])}
        for key in ("name", "niche", "appliance"):
            if m.get(key):
                entry[key] = m[key]
        ops.append({"op": "add", "closeGap": False, "module": entry})
        reach = max(reach, entry["fromCorner"] + entry["width"])
    summary = [f"{len(modules)} cabinets, {reach:g} mm, along an edge at {run['yaw']:g}° (run {run['id']})"]
    if reach > frame["length"] + 1.0:
        summary.append(f"The cabinets are {reach - frame['length']:g} mm longer than the edge ({frame['length']:g} mm)")
    return {"operation": combine_ops(ops), "run": run, "length": reach, "summary": summary}
