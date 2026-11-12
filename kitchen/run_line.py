"""A line is the back of a run of cabinets: two points and the side the doors look at. From a line the run frame and the cabinets on it follow.

Pure plane math (rule R1), everything in the KITCHEN frame (mm). The sources of a line (the nearest edge of a floor-plan object, a wall, two
points the user draws, a run read from a photo) all end up as the same ``Line``; ``run_frame`` gives the explicit run (``spec.runs``) that stands on
it and ``plan_on_line`` the operation that puts cabinets in that run. ``cabinet_run`` (templates) and ``recognition.operation`` (photos) build on it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, cast

from . import builtin
from .words import Said, said
from .catalog import Catalog
from .edit import apply_op, combine_ops, next_run_id
from .errors import InvalidInput
from .floorplan.geom import point_in_poly
from .numeric import round_half_away
from .spec import KitchenSpec, LaidModule

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


def drawn_line(a: Pt, b: Pt, front: Pt) -> Line:
    """The line from ``a`` to ``b`` with its doors looking at the side ``front`` is on (a point exactly on the line is refused)."""
    ex, ez = b[0] - a[0], b[1] - a[1]
    length = math.hypot(ex, ez)
    if length < 1.0:
        raise InvalidInput("The line has no length", code="bad-line")
    nx, nz = -ez / length, ex / length
    side = (front[0] - a[0]) * nx + (front[1] - a[1]) * nz
    if abs(side) < 1.0:
        raise InvalidInput("The front point lies on the line: it must be on the side the doors look at", code="bad-line")
    return Line(a, b, (nx, nz) if side > 0 else (-nx, -nz))


def base_cabinets(length: float, common: dict[str, Any], catalog: Catalog = builtin.CATALOG) -> list[LaidModule]:
    """Plain base cabinets filling ``length`` (``cabinet_run.split_widths``: 600s, a short remainder widening the last), ready for ``plan_on_line``."""
    from .cabinet_run import split_widths
    out: list[LaidModule] = []
    at = 0.0
    for w in split_widths(float(int(length // 10) * 10), catalog):
        out.append({"type": "base", "s": at, "width": w, "y": 0.0, "height": float(common["baseTop"]), "depth": float(common["baseDepth"])})
        at += w
    return out


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


EXTRA_FIELDS = ("name", "niche", "appliance", "appliances", "doors", "frontSections", "hingeSides", "doorStyle", "blindCorner", "blindSide", "shelfCount", "backPanel", "material")   # what a module may carry besides its box


def plan_on_line(spec: KitchenSpec, line: Line, modules: list[LaidModule], clear: list[str] | None = None,
                 after: list[dict[str, Any]] | None = None, system: str | None = None, run_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """The operation that puts ``modules`` in a new run on ``line``. Each module is ``{"type", "width", "s", "y", "height", "depth", "name"?}`` with
    ``s`` measured along the run from its start. ``clear``: ids of cabinets to remove first (replace instead of add); ``after``: operations to run once the cabinets are in.
    ``system``: the cabinet system the run belongs to (``Run.system``), None to let it be worked out. ``run_fields``: more fields of the run (a TV unit: ``tv_system.run_fields``)."""
    frame = run_frame(line)
    run = {"id": next_run_id(spec), "x": frame["x"], "z": frame["z"], "yaw": frame["yaw"], **({"system": system} if system else {}),
           **(run_fields or {})}
    ops: list[dict[str, Any]] = [{"op": "remove", "id": module_id, "closeGap": False} for module_id in clear or []]
    ops.append({"op": "add-run", "run": run})
    reach = 0.0
    for m in sorted(modules, key=lambda item: item["s"]):
        entry: dict[str, Any] = {"type": m["type"], "wall": "island", "run": run["id"], "fromCorner": float(m["s"]), "width": float(m["width"]), "y": float(m["y"]),
                 "height": float(m["height"]), "depth": float(m["depth"])}
        extra = cast("dict[str, Any]", m)                     # the optional fields, read by name
        for key in EXTRA_FIELDS:
            if extra.get(key):
                entry[key] = extra[key]
        ops.append({"op": "add", "closeGap": False, "module": entry})
        reach = max(reach, entry["fromCorner"] + entry["width"])
    ops.extend(after or [])
    summary = [said("summary.line-run", n=len(modules), length=reach, yaw=run['yaw'], run=run['id'])]
    if reach > frame["length"] + 1.0:
        summary.append(said("summary.longer-than-edge", over=reach - frame['length'], edge=frame['length']))
    return {"operation": combine_ops(ops), "run": run, "length": reach, "summary": summary}


def run_lines(line: Line, runs: list[dict[str, Any]], joints: list[tuple[str, str]]) -> tuple[list[tuple[dict[str, Any], Line]], list[str]]:
    """Where each run of a recognised kitchen stands when its MAIN run (``back``, else the first) stands on ``line``: ``([(run, line)], skipped ids)``.

    ``runs``: ``[{"id", "length", "modules"}]``; a joint ``(a, b)`` = the end of run ``a`` meets the start of run ``b`` at a right angle in an inside
    corner. A run joined to the main run's START stands square to it at the line's start and reaches into the room; one joined to its END stands at
    the main run's end. With only an end corner the main run is pushed to the far end of the line, so the corner sits where the edge ends.
    Runs not joined to the main run have no place and are skipped."""
    by_id = {r["id"]: r for r in runs}
    main = by_id.get("back") or runs[0]
    before = next((by_id[a] for a, b in joints if b == main["id"] and a in by_id and a != main["id"]), None)
    after = next((by_id[b] for a, b in joints if a == main["id"] and b in by_id and b != main["id"]), None)
    frame = run_frame(line)
    nx, nz = line.normal
    ux, uz = nz, -nx                                              # the main run's s direction
    offset = max(0.0, frame["length"] - float(main["length"])) if after is not None and before is None else 0.0
    p0 = (frame["x"] + ux * offset, frame["z"] + uz * offset)
    p1 = (p0[0] + ux * float(main["length"]), p0[1] + uz * float(main["length"]))
    placed: list[tuple[dict[str, Any], Line]] = [(main, Line(p0, p1, (nx, nz)))]
    if before is not None:                                        # its doors look along the main run; its s runs towards the corner
        reach = float(before["length"])
        placed.append((before, Line((p0[0] + nx * reach, p0[1] + nz * reach), p0, (ux, uz))))
    if after is not None:                                         # its doors look back along the main run; its s runs away from the corner
        reach = float(after["length"])
        placed.append((after, Line(p1, (p1[0] + nx * reach, p1[1] + nz * reach), (-ux, -uz))))
    used = {r["id"] for r, _ in placed}
    return placed, [r["id"] for r in runs if r["id"] not in used]


def back_wall_line(spec: KitchenSpec, runs: list[dict[str, Any]]) -> Line:
    """The line of the kitchen frame's back wall (z = 0, from the back-left corner to the back-right corner at the origin, doors looking into
    the room), long enough for the main run: where a recognised kitchen stands when the user picked no edge. With a wider room the rules of
    ``run_lines`` decide the end it starts from (a left run: the left corner; only a right run: the right corner)."""
    if not runs:
        raise InvalidInput("No run to place", code="no-run")
    main = next((r for r in runs if r["id"] == "back"), runs[0])
    wall = (spec.room.length("back") if spec.room else None) or 0.0
    length = max(float(wall), float(main["length"]))
    return Line((-length, 0.0), (0.0, 0.0), (0.0, 1.0))


def plan_runs(spec: KitchenSpec, line: Line, runs: list[dict[str, Any]], joints: list[tuple[str, str]], clear: list[str] | None = None,
              system: str | None = None) -> dict[str, Any]:
    """The operation that puts a whole recognised kitchen (one run, an L or a U) on ``line``: one explicit run per recognised run, see ``run_lines``.
    ``clear``: ids of cabinets to remove first. Returns what ``plan_on_line`` returns, plus ``runs`` (``[{"source", "run"}]``)."""
    if not runs:
        raise InvalidInput("No run to place", code="no-run")
    placed, skipped = run_lines(line, runs, joints)
    ops: list[dict[str, Any]] = []
    summary: list[Said] = []
    made: list[dict[str, Any]] = []
    current = spec
    for index, (run, at) in enumerate(placed):
        plan = plan_on_line(current, at, [cast(LaidModule, dict(m)) for m in run["modules"]], clear if index == 0 else None, system=system)
        ops.append(plan["operation"])
        summary.extend(plan["summary"] if index == 0 else [said("summary.prefixed", id=run['id'], text=plan['summary'][0])])
        made.append({"source": run["id"], "run": plan["run"]})
        current = apply_op(current, {"op": "add-run", "run": plan["run"]})      # so the next run gets the next id
    if skipped:
        summary.append(said("summary.runs-left-out", ids=', '.join(skipped)))
    return {"operation": combine_ops(ops), "run": made[0]["run"], "runs": made, "length": float(placed[0][0]["length"]), "summary": summary}


ANCHOR_KINDS = ("furniture", "column", "wall", "shaft")     # floorplan elements a run can stand against (not openings, stairs, areas)
ANCHOR_TOLERANCE = 1.0                                      # mm: how far a run's back line may lie from the element's edge


def element_against(frame: dict[str, float], s0: float, s1: float, structures: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
    """The floorplan element a run stands against: its back line (``s0..s1`` along the run, d = 0) lies on an edge of the element (within
    ``ANCHOR_TOLERANCE``), overlapping it, and its doors look out of the element. ``frame``: the run (``x, z, yaw``, kitchen frame); each
    structure: ``{"sourceElement", "kind", "outline": [(x, z), ...]}`` in the kitchen frame. Returns ``(element id, [])``, or ``(None,
    candidates)`` when no element or more than one equally good one is found (then nothing should be guessed)."""
    from . import runs as runmod
    fr = runmod.RunFrame("", frame["x"], frame["z"], frame["yaw"])
    a, b = fr.to_world(s0, 0.0), fr.to_world(s1, 0.0)
    nx, nz = fr.normal()
    best: dict[str, float] = {}
    for st in structures:
        if st.get("kind") not in ANCHOR_KINDS or len(st["outline"]) < 3:
            continue
        poly = [(float(p[0]), float(p[1])) for p in st["outline"]]
        for i, p in enumerate(poly):
            q = poly[(i + 1) % len(poly)]
            ex, ez = q[0] - p[0], q[1] - p[1]
            length = math.hypot(ex, ez)
            if length < MIN_LENGTH:
                continue
            ux, uz = ex / length, ez / length
            off = [abs((pt[0] - p[0]) * uz - (pt[1] - p[1]) * ux) for pt in (a, b)]          # distance of both ends from the edge's line
            if max(off) > ANCHOR_TOLERANCE:
                continue
            t = sorted(((pt[0] - p[0]) * ux + (pt[1] - p[1]) * uz) for pt in (a, b))
            overlap = min(t[1], length) - max(t[0], 0.0)
            if overlap <= ANCHOR_TOLERANCE:
                continue
            try:
                ox, oz = outward(poly, p, q)
            except InvalidInput:
                continue
            if ox * nx + oz * nz < 0.99:
                continue
            key = str(st["sourceElement"])
            best[key] = max(best.get(key, 0.0), overlap)
    if not best:
        return None, []
    top = max(best.values())
    winners = sorted(k for k, v in best.items() if v >= top - ANCHOR_TOLERANCE)
    return (winners[0], []) if len(winners) == 1 else (None, winners)
