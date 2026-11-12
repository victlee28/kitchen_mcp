"""Binding the kitchen frame to a wall of the room and applying the binding to a design document."""
from __future__ import annotations

import copy
import math
from typing import Any, TypedDict

from ..numeric import round_half_away
from ..placement import Placement
from ..errors import InvalidInput

from .back import RoomEdge, detect_element_backs, outline_xy, room_edges
from .constants import TOL
from .geom import Pt, angle_between, area2, seg_dist, vcross, vdot, vsub


# ---------------------------------------------------------------- binding the kitchen frame to the room
def kitchen_transform(fp: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Rigid transform kitchen frame -> scene: origin = right-hand corner of the back wall (as seen from inside), +z = into the room."""
    ed = room_edges(outline_xy(fp["outline"]))[int(binding["back"])]
    n = ed["n"]
    right: Pt = (n[1], -n[0])           # facing the wall (-n), the right-hand direction
    r_end = max((ed["a"], ed["b"]), key=lambda p: vdot(p, right))
    off = float(binding.get("offset", 0.0))
    origin = (r_end[0] - right[0] * off, r_end[1] - right[1] * off)
    return {"origin": {"x": round_half_away(origin[0], 3), "z": round_half_away(origin[1], 3)}, "yaw": round_half_away(math.degrees(math.atan2(n[0], n[1])), 6),
            "right": {"x": round_half_away(right[0], 6), "z": round_half_away(right[1], 6)}, "into": {"x": round_half_away(n[0], 6), "z": round_half_away(n[1], 6)}}


class Verdict(TypedDict):
    """Whether room edge ``edge`` can carry the back run, why not, and how well it fits."""
    edge: int
    ok: bool
    why: list[str]
    warnings: list[str]
    score: float
    right: int | None
    left: int | None


def _perp(e1: RoomEdge, e2: RoomEdge) -> bool:
    return abs(angle_between(e1["dir"], e2["dir"]) - 90.0) <= 10.0


def bind_kitchen(fp: dict[str, Any], need: dict[str, Any], back_edge: int | None = None, offset: float = 0.0) -> dict[str, Any]:
    """Choose (or validate) the room edge that carries the back run of the kitchen.

    ``need``: {"back": mm, "right": mm or 0, "left": mm or 0}. Raises ValueError when nothing fits; never stretches or
    moves the room.
    """
    room = outline_xy(fp["outline"])
    edges = room_edges(room)
    ccw = area2(room) > 0
    n_edges = len(edges)
    need_back, need_right, need_left = (float(need.get(k2) or 0.0) for k2 in ("back", "right", "left"))
    backs = {r["back"]["roomEdge"] for r in detect_element_backs(fp, ("furniture",), ("cabinet",)) if r["back"]}
    verdicts: list[Verdict] = []
    for ed in edges:
        why: list[str] = []
        warns: list[str] = []
        if need_back > ed["length"] + 5.0:
            why.append(f"edge is {ed['length']:.0f} mm, back run needs {need_back:.0f} mm")
        n = ed["n"]
        right: Pt = (n[1], -n[0])
        r_end = max((ed["a"], ed["b"]), key=lambda p: vdot(p, right))
        at_start = r_end == ed["a"]
        nb = edges[(ed["i"] - 1) % n_edges] if at_start else edges[(ed["i"] + 1) % n_edges]
        first, second = (nb, ed) if at_start else (ed, nb)
        turn = vcross(first["dir"], second["dir"])
        convex = turn > 0 if ccw else turn < 0
        if need_right and not (_perp(nb, ed) and convex and nb["length"] + 5.0 >= need_right):
            why.append(f"no perpendicular wall of at least {need_right:.0f} mm at the right-hand corner")
        left_edge = None
        if need_left:
            l_pt = (r_end[0] - right[0] * need_back, r_end[1] - right[1] * need_back)
            left_edge = next((x["i"] for x in edges if x["i"] != ed["i"] and _perp(x, ed) and seg_dist(l_pt, x["a"], x["b"]) <= TOL and x["length"] + 5.0 >= need_left), None)
            if left_edge is None:
                warns.append("the left run does not stand against a wall")
        score = (need_back / ed["length"]) + (0.5 if ed["i"] in backs else 0.0)
        s_r = vdot(vsub(r_end, ed["a"]), ed["dir"])
        s_l = s_r - need_back * vdot(right, ed["dir"])
        lo, hi = sorted((s_r, s_l))
        for e in fp["elements"]:
            att = e.get("attached")
            if not att or att["edge"] != ed["i"]:
                continue
            if att["offset"] + att["width"] > lo and att["offset"] < hi:
                score -= 1.0 if e.get("tag") == "door" else 0.2
                warns.append(f"{e['id']} ({e.get('tag')}) falls inside the back run")
        verdicts.append({"edge": ed["i"], "ok": not why, "why": why, "warnings": warns, "score": round_half_away(score, 3),
                         "right": nb["i"] if need_right else None, "left": left_edge})
    if back_edge is not None:
        chosen = next((x for x in verdicts if x["edge"] == back_edge), None)
        if chosen is None:
            raise InvalidInput(f"edge {back_edge} does not exist (0..{n_edges - 1})", code="bad-back-edge-index", params={"edge": back_edge, "max": n_edges - 1})
        if not chosen["ok"]:
            raise InvalidInput(f"edge {back_edge} cannot carry the kitchen: " + "; ".join(chosen["why"]), code="edge-cannot-carry",
                               params={"edge": back_edge, "why": "; ".join(chosen["why"])})
        source = "manual"
    else:
        ok = sorted((x for x in verdicts if x["ok"]), key=lambda x: -x["score"])
        if not ok:
            raise InvalidInput("The kitchen does not fit any wall of the room: " + "; ".join(f"edge {x['edge']}: {', '.join(x['why'])}" for x in verdicts)[:700], code="kitchen-fits-no-wall")
        chosen, source = ok[0], "auto"
        if len(ok) > 1 and abs(ok[0]["score"] - ok[1]["score"]) < 0.05:
            chosen = chosen.copy()
            chosen["warnings"] = [*chosen["warnings"], f"edge {ok[1]['edge']} fits equally well; pass back_edge to choose"]
    b: dict[str, Any] = {"back": chosen["edge"], "right": chosen["right"], "left": chosen["left"], "offset": float(offset), "source": source, "score": chosen["score"], "warnings": chosen["warnings"],
         "need": {"back": need_back, "right": need_right, "left": need_left}}
    b["transform"] = kitchen_transform(fp, b)
    return b


def apply_binding(doc: dict[str, Any], fp: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """A copy of a three.js document with the kitchen content moved from the kitchen frame into the floorplan room (``doc`` is not changed)."""
    doc = copy.deepcopy(doc)
    t = binding.get("transform") or kitchen_transform(fp, binding)
    pl = Placement.from_transform(t)

    def vec(v: dict[str, Any]) -> dict[str, Any]:  # direction (rotation about +Y, same convention as three.js)
        x, z = pl.dir_to_room(v["x"], v["z"])
        return {**v, "x": round_half_away(x, 6), "z": round_half_away(z, 6)}

    def pos(v: dict[str, Any]) -> dict[str, Any]:
        w = vec(v)
        return {**v, "x": round_half_away(w["x"] + pl.ox, 3), "z": round_half_away(w["z"] + pl.oz, 3)}

    def wrap(a: float) -> float:
        a = round_half_away(a % 360, 6)
        return a - 360 if a > 180 else a

    for sect in ("modules", "runs", "appliances", "accessories", "decorations"):
        for e in doc.get(sect, []):
            tf = e.get("transform")
            if tf:
                tf["position"] = pos(tf["position"])
                rot = tf.setdefault("rotation", {"x": 0, "y": 0, "z": 0, "unit": "deg"})
                rot["y"] = wrap(rot.get("y", 0) + t["yaw"])
            if sect == "runs" and e.get("frontAxis"):
                e["frontAxis"] = vec(e["frontAxis"])
    for cam in doc.get("cameras", []):
        for key in ("position", "target"):
            if cam.get(key):
                cam[key] = pos(cam[key])
    cs: dict[str, Any] = doc.get("coordinateSystem") or {}
    wall_frames: list[dict[str, Any]] = cs.get("wallFrames", [])
    for wf in wall_frames:
        wf["origin"], wf["alongAxis"], wf["frontAxis"] = pos(wf["origin"]), vec(wf["alongAxis"]), vec(wf["frontAxis"])
        wf["rotationY"] = wrap(wf.get("rotationY", 0) + t["yaw"])
    if cs:
        cs["origin"] = "room_corner"
        cs["notes"] = (cs.get("notes", "") + f" Đã đặt vào phòng của mặt bằng: gốc là góc phải của tường sau bếp, xoay {t['yaw']:.1f} độ.").strip()
    return doc
