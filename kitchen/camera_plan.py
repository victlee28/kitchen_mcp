"""Camera views for the cabinets of a kitchen: eye height, inside the room, with whatever stands in the way hidden (pure plane math, rule R1).

Everything is in the KITCHEN frame (mm, ``y`` up), the frame the scene's parts use. A ``Face`` is the front of a run of cabinets (a wall run or an
explicit run). For each face ``plan_views`` gives a front view and an oblique view: the camera stands at eye height (1.6 m), inside the room (clear
of its walls), as far back as the room allows so the whole run fits in a sensible field of view. Solids that are not cabinets (walls, columns,
furniture...) standing between the camera and the cabinets are listed in the view's ``hide``: the viewer and the renderer leave them out of that view.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any

from . import builtin
from .floorplan.geom import point_in_poly
from .words import say
from .numeric import round_half_away

Pt = tuple[float, float]

_R = builtin.CATALOG.data("camera-rules", "default")   # locked catalog kind camera-rules (data/items/camera-rules.json): developers only
EYE = float(_R["eye"])                  # camera height (mm)
ASPECT = 4 / 3                          # the renderer's default 1280 x 960
MIN_DIST = float(_R["minDist"])         # nearest the camera stands to a run's front (mm): in a narrow room it steps in and opens the lens instead
MAX_DIST = float(_R["maxDist"])
STEP = float(_R["step"])
WALL_CLEAR = float(_R["wallClear"])     # nearest the camera stands to a wall (mm)
V_MIN, V_MAX = float(_R["vMinDeg"]), float(_R["vMaxDeg"])    # vertical field of view limits (degrees): the hard clamp
V_NATURAL_DEG = float(_R["vNaturalDeg"])  # widest lens that still looks like a photograph (~76° across at 4:3, a 22 mm full-frame lens): wider looks fake
                          # (user, 11/11/2026: "ống kính góc rộng vừa đủ, không quá rộng"); past it the camera stands outside the wall instead
OBLIQUE = math.radians(float(_R["obliqueDeg"]))
NON_BLOCKING = ("area", "opening")
FRONT_PROBE = float(_R["frontProbe"])   # how far in front of a run its room is probed (mm)   # floor areas and door/window openings are not solids that hide cabinets


@dataclass(frozen=True)
class Face:
    """The front of a run of cabinets: ``center`` is the middle of the front line, ``normal`` the unit vector the doors look along."""
    key: str
    name: str
    center: Pt
    normal: Pt
    length: float
    height: float
    run: str = ""         # the run (or wall) the front belongs to: its own cabinets never block it


@dataclass(frozen=True)
class Obstacle:
    """A solid that is not a cabinet: floor outline ``outline`` extruded from ``y0`` to ``y1``."""
    id: str
    kind: str
    outline: tuple[Pt, ...]
    y0: float
    y1: float


def _dist_to_segment(p: Pt, a: Pt, b: Pt) -> float:
    ex, ez = b[0] - a[0], b[1] - a[1]
    n2 = ex * ex + ez * ez
    t = 0.0 if n2 < 1e-9 else max(0.0, min(1.0, ((p[0] - a[0]) * ex + (p[1] - a[1]) * ez) / n2))
    return math.hypot(p[0] - (a[0] + t * ex), p[1] - (a[1] + t * ez))


def stands_in_room(p: Pt, room: list[Pt] | None, clear: float = WALL_CLEAR) -> bool:
    """Inside the room's floor outline and at least ``clear`` from every wall; always true when the room is unknown."""
    if not room:
        return True
    if not point_in_poly(p, room):
        return False
    return all(_dist_to_segment(p, room[i], room[(i + 1) % len(room)]) >= clear for i in range(len(room)))


def _crossings(a: Pt, b: Pt, poly: tuple[Pt, ...]) -> list[float]:
    """Parameters t in [0, 1] where the segment a->b crosses the polygon's edges, sorted."""
    ts: list[float] = []
    dx, dz = b[0] - a[0], b[1] - a[1]
    for i in range(len(poly)):
        c, d = poly[i], poly[(i + 1) % len(poly)]
        ex, ez = d[0] - c[0], d[1] - c[1]
        den = dx * ez - dz * ex
        if abs(den) < 1e-9:
            continue
        t = ((c[0] - a[0]) * ez - (c[1] - a[1]) * ex) / den
        u = ((c[0] - a[0]) * dz - (c[1] - a[1]) * dx) / den
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
            ts.append(t)
    return sorted(ts)


def blocks(eye: tuple[float, float, float], target: tuple[float, float, float], ob: Obstacle) -> bool:
    """Does the solid stand on the straight line from ``eye`` to ``target`` (x, y, z; mm)?"""
    a, b = (eye[0], eye[2]), (target[0], target[2])
    ts = [0.0, *_crossings(a, b, ob.outline), 1.0]
    for t0, t1 in zip(ts, ts[1:]):
        if t1 - t0 < 1e-6:
            continue
        tm = (t0 + t1) / 2
        if not point_in_poly((a[0] + (b[0] - a[0]) * tm, a[1] + (b[1] - a[1]) * tm), list(ob.outline)):
            continue
        y_lo, y_hi = sorted((eye[1] + (target[1] - eye[1]) * t0, eye[1] + (target[1] - eye[1]) * t1))
        if y_hi > ob.y0 and y_lo < ob.y1:
            return True
    return False


def face_targets(face: Face) -> list[tuple[float, float, float]]:
    """Points on the front of the run (3 along x 3 heights) the camera must see."""
    ux, uz = face.normal[1], -face.normal[0]            # along the run, to the right of someone facing the doors
    top = max(face.height, 900.0)
    out: list[tuple[float, float, float]] = []
    for f in (-0.4, 0.0, 0.4):
        for h in (0.2, 0.55, 0.9):
            out.append((face.center[0] + ux * face.length * f, top * h, face.center[1] + uz * face.length * f))
    return out


def blockers(eye: tuple[float, float, float], targets: list[tuple[float, float, float]], obstacles: list[Obstacle]) -> list[str]:
    return sorted({ob.id for ob in obstacles if ob.kind not in NON_BLOCKING and any(blocks(eye, t, ob) for t in targets)})


def _fov(face: Face, dist: float, width_factor: float) -> float:
    """Vertical field of view (degrees) in which the run's width and height fit at ``dist``, before clamping."""
    ty = _look_height(face)
    half_v = max(face.height - ty, ty - 0.0, EYE - ty) * 1.1
    half_h = (face.length * width_factor / 2 + 150.0) * 1.1
    return math.degrees(2 * math.atan(max(half_v, half_h / ASPECT) / max(dist, 1.0)))


def _look_height(face: Face) -> float:
    return min(1100.0, max(face.height, 900.0) / 2)


def _candidate(face: Face, direction: Pt, dist: float, width_factor: float) -> tuple[Pt, float]:
    return (face.center[0] + direction[0] * dist, face.center[1] + direction[1] * dist), _fov(face, dist, width_factor)


def in_body(p: Pt, bodies: list[Obstacle], clear: float = WALL_CLEAR) -> bool:
    """Does the point stand inside a cabinet, or closer than ``clear`` to one?"""
    for b in bodies:
        poly = list(b.outline)
        if point_in_poly(p, poly) or any(_dist_to_segment(p, poly[i], poly[(i + 1) % len(poly)]) < clear for i in range(len(poly))):
            return True
    return False


def _best(face: Face, directions: list[Pt], width_factor: float, room: list[Pt] | None, obstacles: list[Obstacle],
          bodies: list[Obstacle]) -> tuple[Pt, float, list[str]]:
    """Ranked: never inside or against a cabinet or another solid (stairs, columns, furniture); without a room, fewest target points seen
    across another run's cabinets (they cannot be hidden); a lens no wider than ``V_NATURAL_DEG``; inside the room (else outside a wall, the
    walls in the way hidden — the user's choice of 11/11/2026: a wide lens first, the wall only when even that is not enough); fewest solids
    to hide; the narrowest lens among the too-wide ones; inside, farthest back (least distortion), outside the wall, nearest to it (the
    picture stays a view into the room, not from across the next one)."""
    targets = face_targets(face)
    # seen over a run is still across it; only weighed where no room guides the camera (keeps the planned views of rooms as they were)
    others = [] if room else [Obstacle(b.id, b.kind, b.outline, -math.inf, math.inf) for b in bodies if b.kind != f"cabinet:{face.run}"]
    # never stand inside (or within WALL_CLEAR of) a solid: a stair, a column, a piece of furniture, a wall the room outline does not cover
    solids = [ob for ob in obstacles if ob.kind not in NON_BLOCKING and ob.y1 > 0.0 and ob.y0 < EYE]
    best: tuple[tuple[Any, ...], Pt, float, list[str]] | None = None
    dist = MAX_DIST
    while dist >= MIN_DIST - 1e-6:
        for direction in directions:
            pos, fov = _candidate(face, direction, dist, width_factor)
            eye = (pos[0], EYE, pos[1])
            bad = in_body(pos, bodies) or in_body(pos, solids)
            outside = not stands_in_room(pos, room)
            hidden = blockers(eye, targets, obstacles)
            behind = sum(any(blocks(eye, t, b) for b in others) for t in targets)
            wide = fov > V_NATURAL_DEG
            key = (bad, behind, wide, outside, len(hidden), fov if wide else 0.0, dist if outside else -dist)
            if best is None or key < best[0]:
                best = (key, pos, fov, hidden)
        dist -= STEP
    assert best is not None
    return best[1], best[2], best[3]


def faces_room(face: Face, room: list[Pt] | None) -> bool:
    """Does the run's front open into the room (a point just in front of its middle lies inside the outline)? True when the room is unknown."""
    if not room:
        return True
    return point_in_poly((face.center[0] + face.normal[0] * FRONT_PROBE, face.center[1] + face.normal[1] * FRONT_PROBE), room)


def plan_views(faces: list[Face], room: list[Pt] | None, obstacles: list[Obstacle], bodies: Sequence[Obstacle] = ()) -> dict[str, dict[str, Any]]:
    """``{key: {name, position, lookAt, verticalFov, hide}}`` (position / lookAt in metres, like ``ViewAngle``): per face a front view and an
    oblique view from the side that sees it with the fewest solids in the way. ``room``: the floor outline, or None when it is not known.
    ``bodies``: the cabinets' footprints (kind ``cabinet:<run>``), never stood in and never hidden; a run outside the room is planned without it."""
    bodies = list(bodies)
    views: dict[str, dict[str, Any]] = {}
    for face in faces:
        nx, nz = face.normal
        room_of = room if faces_room(face, room) else None     # a run outside the imported room: no room to stand in, only the solids to hide
        look = (face.center[0] / 1000.0, _look_height(face) / 1000.0, face.center[1] / 1000.0)
        pos, fov, hide = _best(face, [(nx, nz)], 1.0, room_of, obstacles, bodies)
        views[face.key] = _view(face.name, pos, look, fov, hide)
        sides = [(nx * math.cos(s * OBLIQUE) - nz * math.sin(s * OBLIQUE), nx * math.sin(s * OBLIQUE) + nz * math.cos(s * OBLIQUE)) for s in (-1, 1)]
        pos, fov, hide = _best(face, sides, 0.85, room_of, obstacles, bodies)
        views[f"{face.key}-oblique"] = _view(say("name.view.oblique", name=face.name), pos, look, fov, hide)
    return views


def hidden_for(position: tuple[float, float, float], faces: list[Face], obstacles: list[Obstacle]) -> list[str]:
    """Ids of the solids between a camera (metres, as in ``ViewAngle``) and the fronts of all the runs: for views that are not planned per face."""
    eye = (position[0] * 1000.0, position[1] * 1000.0, position[2] * 1000.0)
    targets = [t for f in faces for t in face_targets(f)]
    return blockers(eye, targets, obstacles)


def _view(name: str, pos: Pt, look: tuple[float, float, float], fov: float, hide: list[str]) -> dict[str, Any]:
    return {"name": name, "position": (round_half_away(pos[0] / 1000.0, 3), EYE / 1000.0, round_half_away(pos[1] / 1000.0, 3)),
            "lookAt": (round_half_away(look[0], 3), round_half_away(look[1], 3), round_half_away(look[2], 3)), "verticalFov": round_half_away(min(max(fov, V_MIN), V_MAX), 1), "hide": hide}


PLAN_MARGIN = 1.08               # room left around the floorplan in the plan and overview views (x the size that just fits)
OVERVIEW_ELEVATION_MIN = 45.0    # degrees: the overview looks down at least this steeply, so the near walls hide little
ROOM_TOP = 2700.0                # mm: the least height the overview frames (walls of an imported plan without one)


def whole_room(views: dict[str, dict[str, Any]], room: list[Pt], solids: list[Obstacle],
               cabinets: tuple[Sequence[float], Sequence[float]] | None) -> dict[str, dict[str, Any]]:
    """``plan`` and ``overhead`` (``ViewAngle`` data, metres) framed on the whole floorplan: the room outline, its walls and columns,
    and the cabinets' box ``cabinets`` (min, max; mm). The solids between the camera and the room's floor are hidden. The plan looks
    straight down from just high enough; the overview looks down at least ``OVERVIEW_ELEVATION_MIN``, from its own heading or one 45°
    further round if the room fits closer from there, and stands back until the whole room fits."""
    solid = [ob for ob in solids if ob.kind not in NON_BLOCKING]
    pts = [*room, *(p for ob in solid for p in ob.outline)]
    top = max([ROOM_TOP, *(ob.y1 for ob in solid)])
    if cabinets is not None:
        pts += [(cabinets[0][0], cabinets[0][2]), (cabinets[1][0], cabinets[1][2])]
        top = max(top, cabinets[1][1])
    xs, zs = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    hx, hz = (x1 - x0) / 2 * PLAN_MARGIN, (z1 - z0) / 2 * PLAN_MARGIN
    floor = [(x0 + (x1 - x0) * i / 6, 0.0, z0 + (z1 - z0) * j / 6) for i in range(1, 6) for j in range(1, 6)]
    floor = [t for t in floor if point_in_poly((t[0], t[2]), room)] or [(cx, 0.0, cz)]

    def metres(p: Sequence[float]) -> tuple[float, float, float]:
        return (round_half_away(p[0] / 1000, 3), round_half_away(p[1] / 1000, 3), round_half_away(p[2] / 1000, 3))

    plan = views["plan"]
    tv = math.tan(math.radians(float(plan["verticalFov"]) / 2))
    height = top + max(hz / tv, hx / (tv * ASPECT))       # the picture's height runs along z, its width along x
    eye = (cx, height, cz + 1.0)
    out: dict[str, dict[str, Any]] = {"plan": {**plan, "position": metres(eye), "lookAt": metres((cx, 0.0, cz)),
                                               "hide": blockers(eye, floor, solids)}}
    over = views["overhead"]
    (px, py, pz), (lx, ly, lz) = over["position"], over["lookAt"]
    flat = math.hypot(px - lx, pz - lz) or 1.0
    rise = math.radians(max(OVERVIEW_ELEVATION_MIN, math.degrees(math.atan2(py - ly, flat))))
    tv = math.tan(math.radians(float(over["verticalFov"]) / 2))
    look = (cx, top / 3, cz)
    corners = [(x - cx, y - look[1], z - cz) for x in (cx - hx, cx + hx) for y in (0.0, top) for z in (cz - hz, cz + hz)]
    start = math.atan2(pz - lz, px - lx)
    best: tuple[float, float] | None = None
    for k in range(8):
        heading = start + k * math.pi / 4
        dist = _fit_distance(corners, heading, rise, tv)
        if best is None or dist < best[0] * 0.97:
            best = (dist, heading)
    assert best is not None
    dist, heading = best
    eye = (look[0] + math.cos(heading) * math.cos(rise) * dist, look[1] + math.sin(rise) * dist,
           look[2] + math.sin(heading) * math.cos(rise) * dist)
    out["overhead"] = {**over, "position": metres(eye), "lookAt": metres(look), "hide": blockers(eye, floor, solids)}
    return out


def _fit_distance(corners: list[tuple[float, float, float]], heading: float, rise: float, tan_v: float) -> float:
    """How far from the look point (along ``heading`` around it, ``rise`` above the horizon) a camera stands so every corner (relative
    to the look point, mm) is in a picture of vertical half field ``tan_v`` (as a tangent) at the renderer's aspect."""
    w = (math.cos(heading) * math.cos(rise), math.sin(rise), math.sin(heading) * math.cos(rise))      # towards the camera
    r = (-math.sin(heading), 0.0, math.cos(heading))                                                   # to the picture's side
    u = (w[1] * r[2] - w[2] * r[1], w[2] * r[0] - w[0] * r[2], w[0] * r[1] - w[1] * r[0])              # the picture's up
    tan_h = tan_v * ASPECT
    need = 0.0
    for q in corners:
        depth = sum(a * b for a, b in zip(q, w))
        need = max(need, depth + abs(sum(a * b for a, b in zip(q, r))) / tan_h, depth + abs(sum(a * b for a, b in zip(q, u))) / tan_v)
    return need
