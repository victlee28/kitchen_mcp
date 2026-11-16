"""How far a recognised kitchen is from the truth. Pure core: JSON in, JSON out.

A truth file (``tests/data/truth/<case>.truth.json``) says what is known of a photo, any of:
- ``edges``: ``{"<wall>/<storey>": [mm, ...]}`` — the module edges along that run, from its inner corner (as ``modules[].x`` counts);
  a tall cabinet counts in the base storey;
- ``lengths``: ``{"<wall>": mm}`` — each run's length;
- ``heights``: ``{"worktopTop" | "plinthHeight" | "upperBottom" | "upperTop": mm}``;
- ``angles``: ``{"<side wall>": degrees}`` — the inside corner between the back wall and a side wall;
- ``cameraHeightMm``, ``focalPx``.
``compare(spec, truth)`` gives each error and a summary (worst edge error in mm and as a share of the run, worst length error as a share).
"""
from __future__ import annotations

from typing import Any

from .numeric import round_half_away


def _edges(spec: dict[str, Any], wall: str, storey: str) -> list[float]:
    mods = sorted((m for m in spec.get("modules", []) if m.get("wall", "back") == wall
                   and (m.get("storey") == storey or (storey == "base" and m.get("storey") == "tall"))), key=lambda m: m["x"])
    if not mods:
        return []
    return [float(mods[0]["x"]), *(float(m["x"] + m["width"]) for m in mods)]


def compare(spec: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"case": truth.get("case", ""), "edges": {}, "lengths": {}, "heights": {}, "angles": {}, "camera": {}}
    worst_mm, worst_share, worst_len = 0.0, 0.0, 0.0
    for key, want in (truth.get("edges") or {}).items():
        wall, storey = key.split("/")
        got = _edges(spec, wall, storey)
        span = max(want) - min(want) if want else 0.0
        if len(got) != len(want):
            out["edges"][key] = {"want": want, "got": got, "error": "count"}
            worst_share = max(worst_share, 1.0)
            continue
        errs = [abs(g - w) for g, w in zip(got, want)]
        out["edges"][key] = {"maxMm": round_half_away(max(errs), 0.1), "meanMm": round_half_away(sum(errs) / len(errs), 0.1)}
        worst_mm = max(worst_mm, max(errs))
        if span > 0:
            worst_share = max(worst_share, max(errs) / span)
    walls = spec.get("walls") or {}
    for wall, want in (truth.get("lengths") or {}).items():
        got = float((walls.get(wall) or {}).get("runLength") or 0)
        share = abs(got - want) / want if want else 0.0
        out["lengths"][wall] = {"want": want, "got": got, "share": round_half_away(share, 0.001)}
        worst_len = max(worst_len, share)
    common = spec.get("common") or {}
    for key, want in (truth.get("heights") or {}).items():
        got = float(common.get(key) or 0)
        out["heights"][key] = {"want": want, "got": got, "errorMm": round_half_away(abs(got - want), 0.1)}
    for wall, want in (truth.get("angles") or {}).items():
        got = float((walls.get(wall) or {}).get("angleDeg", 90.0))
        out["angles"][wall] = {"want": want, "got": got, "errorDeg": round_half_away(abs(got - want), 0.1)}
    ev = spec.get("evidence") or {}
    if "cameraHeightMm" in truth:
        got = float(ev.get("cameraHeightMm") or 0)
        out["camera"]["heightShare"] = round_half_away(abs(got - truth["cameraHeightMm"]) / truth["cameraHeightMm"], 0.001)
    if "focalPx" in truth:
        got = float((ev.get("camera") or {}).get("focalPx") or 0)
        out["camera"]["focalShare"] = round_half_away(abs(got - truth["focalPx"]) / truth["focalPx"], 0.001)
    out["summary"] = {"worstEdgeMm": round_half_away(worst_mm, 0.1), "worstEdgeShare": round_half_away(worst_share, 0.001),
                      "worstLengthShare": round_half_away(worst_len, 0.001)}
    return out
