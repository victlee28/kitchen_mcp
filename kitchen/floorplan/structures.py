"""Every drawn element -> a 3-D structure record."""
from __future__ import annotations

from typing import Any

from .constants import DEFAULT_WALL_HEIGHT


# ---------------------------------------------------------------- every drawn element -> 3D structures
STRUCTURE_COLORS = {"wall": "#E7E2D5", "column": "#F2B65D", "opening": "#55C6A9", "furniture": "#D38662", "shaft": "#8C83D6",
                    "stair": "#CFAE52", "area": "#7D9EAA"}
STAIR_STEPS = 10
STAIR_RISE = 1800.0


def default_height(rec: dict[str, Any]) -> float:
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


def structures(fp: dict[str, Any]) -> list[dict[str, Any]]:
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
