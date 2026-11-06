"""Which side of a unit lies against a wall of the room (the "back" of a unit)."""
from __future__ import annotations

import math
from typing import Any

from ..numeric import round_half_away

from .constants import PARALLEL_DEG, TOL
from .geom import Poly, angle_between, area2, vdot, vnorm, vsub


# ---------------------------------------------------------------- back face of a unit next to a wall
def room_edges(room: Poly) -> list[dict[str, Any]]:
    ccw = area2(room) > 0
    out = []
    for i, a in enumerate(room):
        b = room[(i + 1) % len(room)]
        d = vnorm(vsub(b, a))
        out.append({"i": i, "a": a, "b": b, "dir": d, "n": (-d[1], d[0]) if ccw else (d[1], -d[0]), "length": math.hypot(*vsub(b, a))})
    return out


def outline_xy(outline: list[Any]) -> Poly:
    return [(p["x"], p["z"]) if isinstance(p, dict) else tuple(p) for p in outline]


def detect_back(outline: list[Any], fp: dict[str, Any], gap_tol: float = 100.0, min_len: float = 200.0) -> dict[str, Any] | None:
    """Which side of a unit is its back, i.e. the side lying against a wall of the room.

    The back is the unit's edge that is parallel to a room edge, on the room side of it, within ``gap_tol`` of the wall
    face and overlapping it. Returns None (and no guess) when no side qualifies; ``status`` is 'corner' when a second,
    non-parallel wall qualifies too.
    """
    pts = outline_xy(outline)
    edges = room_edges(outline_xy(fp["outline"]))
    cen = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    found = []
    for j in range(len(pts)):
        p, q = pts[j], pts[(j + 1) % len(pts)]
        ln = math.hypot(*vsub(q, p))
        if ln < min_len:
            continue
        d = vnorm(vsub(q, p))
        for ed in edges:
            if angle_between(d, ed["dir"]) > PARALLEL_DEG:
                continue
            ins = [vdot(vsub(v, ed["a"]), ed["n"]) for v in (p, q)]   # distance into the room
            if min(ins) < -TOL or max(ins) > gap_tol:
                continue
            if vdot(vsub(cen, ed["a"]), ed["n"]) <= max(ins) + 1.0:    # the unit's body must lie on the room side of this face
                continue
            al = sorted(vdot(vsub(v, ed["a"]), ed["dir"]) for v in (p, q))
            ov = min(al[1], ed["length"]) - max(al[0], 0.0)
            if ov < 0.4 * ln:
                continue
            gap = max(0.0, sum(ins) / 2)
            found.append({"elementEdge": j, "roomEdge": ed["i"], "gap": round_half_away(gap, 1), "overlap": round_half_away(ov, 1), "run": round_half_away(ln, 1),
                          "score": ov * (1 - min(gap, gap_tol) / (gap_tol * 1.5)), "facing": {"x": round_half_away(ed["n"][0], 6), "z": round_half_away(ed["n"][1], 6)},
                          "depth": round_half_away(max(vdot(vsub(v, ed["a"]), ed["n"]) for v in pts) - gap, 1)})
    if not found:
        return None
    found.sort(key=lambda r: -r["score"])
    best = found[0]
    other = next((r for r in found[1:] if r["roomEdge"] != best["roomEdge"] and r["score"] >= 0.5 * best["score"]), None)
    conf = 0.95 if best["gap"] <= 20 else 0.85 if best["gap"] <= 50 else 0.7
    if best["overlap"] < 0.9 * best["run"]:
        conf -= 0.1
    best = {k2: v for k2, v in best.items() if k2 != "score"}
    best.update(confidence=round_half_away(conf, 2), status="corner" if other else "wall-backed")
    if other:
        best["alsoAgainst"] = other["roomEdge"]
    return best


def detect_element_backs(fp: dict[str, Any], kinds: tuple[str, ...] = ("furniture",), tags: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """detect_back for every retained furniture/cabinet that belongs to the room."""
    out = []
    for e in fp["elements"]:
        if e["kind"] not in kinds or not e.get("outline") or e["membership"] not in ("inside", "overlapping", "adjacent"):
            continue
        if tags and e.get("tag") not in tags:
            continue
        out.append({"element": e["id"], "label": e.get("label"), "back": detect_back(e["outline"], fp)})
    return out
