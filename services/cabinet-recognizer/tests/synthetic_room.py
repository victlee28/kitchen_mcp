"""A kitchen drawn by a known camera, for checking the perspective geometry without a photo.

``l_kitchen(angle)`` lays a back run and a left run meeting at an inner corner of ``angle`` degrees, photographs it with a level pinhole
camera and returns what the recogniser would have measured (``meas``), the scene and run answers and a policy, plus the truth (module
widths along each run). Units: mm in the room, px in the image. The back wall is z = 0, x grows to the right; the left wall leaves the
corner at x = 0 towards the camera at ``angle`` degrees from the back wall.
"""
from __future__ import annotations

import math
from typing import Any

W, H, F = 1200, 900, 820.0                     # image size and focal length (px)
CAMERA = (2300.0, 1450.0, 4300.0)              # x, height, z (mm)
YAW = math.radians(-28.0)                      # camera turned towards the back-left corner
DEPTH, RECESS, UPPER = 600.0, 50.0, 350.0
HEIGHTS = {"plinthBottom": 0.0, "frontsBottom": 100.0, "worktopFront": 890.0, "upperBottom": 1490.0, "upperTop": 2240.0}
POLICY = {"region": "VN", "plinthRecessMm": 50, "baseDepthMm": 600, "upperDepthMm": 350, "tallDepthMm": 600, "worktopThicknessMm": 40,
          "widthRoundingMm": 10, "heightRoundingMm": 10, "alignToleranceMm": 30, "snapToleranceMm": 40,
          "worktopOptionsMm": [850, 860, 870, 880, 890, 900], "gapOptionsMm": [550, 600, 650, 700, 750],
          "upperHeightOptionsMm": [700, 750, 760, 800, 900], "verticalCorrection": "none", "fovDeg": 60, "reasoning": "synthetic"}


def _project(p: tuple[float, float, float]) -> tuple[float, float]:
    dx, dy, dz = p[0] - CAMERA[0], p[1] - CAMERA[1], p[2] - CAMERA[2]
    fwd = (math.sin(YAW), 0.0, -math.cos(YAW))           # looking towards -z, turned by YAW
    right = (math.cos(YAW), 0.0, math.sin(YAW))
    x = dx * right[0] + dz * right[2]
    z = dx * fwd[0] + dz * fwd[2]
    return (W / 2 + F * x / z, H / 2 + F * (-dy) / z)


def _run(origin: tuple[float, float], t: tuple[float, float], n: tuple[float, float], start: float, cuts: list[float],
         prefix: str, uppers: bool = True) -> dict[str, Any]:
    """Lines and candidate boundaries of one run: ``start``/``cuts`` along t (mm from the corner)."""
    def at(s: float, c: float, y: float) -> tuple[float, float]:
        return _project((origin[0] + t[0] * s + n[0] * c, y, origin[1] + t[1] * s + n[1] * c))
    lines: dict[str, list[float]] = {}
    s0, s1 = start, cuts[-1]
    for key, y in HEIGHTS.items():
        if key.startswith("upper") and not uppers:
            continue
        c = DEPTH - RECESS if key == "plinthBottom" else (UPPER if key.startswith("upper") else DEPTH)
        (u0, v0), (u1, v1) = at(s0 + 20, c, y), at(s1 - 20, c, y)
        a = (v1 - v0) / (u1 - u0)
        lines[key] = [a, v0 - a * u0, 0.3, 80, min(u0, u1), max(u0, u1)]
    cand = {"base": [{"id": f"{prefix}D{i + 1}", "pos": round(at(s, DEPTH, 450)[0]), "strength": 50.0} for i, s in enumerate(cuts)]}
    if uppers:
        cand["upper"] = [{"id": f"{prefix}U{i + 1}", "pos": round(at(s, UPPER, 1800)[0]), "strength": 50.0} for i, s in enumerate(cuts)]
    us = [at(s, DEPTH, 450)[0] for s in cuts]
    return {"lines": lines, "xRange": [min(us), max(us)], "cand": cand}


def l_kitchen(angle: float, island: tuple[float, list[float]] | None = None) -> dict[str, Any]:
    """``island``: (its back face's distance from the back wall, its boundaries along x) — a free run parallel to the back run."""
    a = math.radians(angle)
    t_left = (math.cos(a), math.sin(a))
    n_left = (t_left[1], -t_left[0])
    back_cuts = [700.0, 1300.0, 1900.0, 2500.0, 3100.0]          # the back run starts behind the left run (blind corner) at 700
    left_cuts = [700.0, 1300.0, 1900.0, 2500.0]
    meas = {"imageSize": [W, H], "runs": {"back": _run((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 700.0, back_cuts, "B"),
                                           "left": _run((0.0, 0.0), t_left, n_left, 700.0, left_cuts, "L")}}
    if island is not None:
        meas["runs"]["island"] = _run((0.0, island[0]), (1.0, 0.0), (0.0, 1.0), island[1][0], island[1], "I", uppers=False)

    def answer(prefix: str, cuts: list[float]) -> dict[str, Any]:
        wall = {"B": "back", "L": "left", "I": "island"}[prefix]

        def ordered(storey: str) -> list[str]:          # boundaries go left to right IN THE IMAGE
            return [c["id"] for c in sorted(meas["runs"][wall]["cand"].get(storey, []), key=lambda c: c["pos"])]
        ids, uids = ordered("base"), ordered("upper")
        mod = {"type": "base", "doors": 1, "doorSplits": [], "drawers": 0, "open": False, "applianceBelow": None, "confidence": 0.9, "note": ""}
        storeys: dict[str, Any] = {"base": {"boundaries": ids, "modules": [dict(mod) for _ in cuts[1:]]}}
        if uids:
            storeys["upper"] = {"boundaries": uids, "modules": [{**mod, "type": "upper"} for _ in cuts[1:]]}
        return {"storeys": storeys,
                "widthRefs": [{"storey": "base", "from": ids[0], "to": ids[1], "mm": 600, "what": "dishwasher"}],
                "heightRefs": [], "appliances": []}

    box = {"left": 0.0, "right": 1.0, "top": 0.0, "bottom": 1.0}
    scene = {"layout": "l-shape", "view": "perspective", "materials": {},
             "runs": [{"wall": "back", "end": "open", "box": box, "lines": {}}, {"wall": "left", "end": "open", "box": box, "lines": {}}]}
    answers = {"back": answer("B", back_cuts), "left": answer("L", left_cuts)}
    truth = {"back": [b - a for a, b in zip(back_cuts, back_cuts[1:])], "left": [b - a for a, b in zip(left_cuts, left_cuts[1:])]}
    if island is not None:
        scene["runs"].append({"wall": "island", "end": "open", "box": box, "lines": {}})
        answers["island"] = answer("I", island[1])
        truth["island"] = [b - a for a, b in zip(island[1], island[1][1:])]
    return {"meas": meas, "scene": scene, "answers": answers, "policy": POLICY, "truth": truth}
