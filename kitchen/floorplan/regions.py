"""Finding the kitchen region of a building plan: candidates, rooms, ``region:`` specs."""
from __future__ import annotations

from typing import Any, TypedDict

from ..errors import InvalidInput

from .constants import TOL, UNIT_MM
from .document import REGION_COVER, REGION_MARGIN_MM, as_dict, element_bbox, element_field, elements_of, field_value, is_kitchen_unit, read_points
from .geom import point_in_poly


Interval = tuple[float, float]
WallCandidate = tuple[float, float, Any, Interval]   # (distance from the seed, face coordinate, wall id, covered interval)


class KitchenCandidate(TypedDict):
    """Kitchen units outside every room that share one wall-bounded region."""
    bbox: list[float]
    seeds: list[Any]
    labels: list[Any]
    open: bool


def derive_region(data: dict[str, Any], seeds: list[str]) -> dict[str, Any]:
    """The rectangle of file coordinates that the walls around the seed elements enclose (for a plan with no room for the kitchen).

    Each side stops at the nearest wall whose face lies beyond the seed and that covers at least REGION_COVER of the seed's width.
    A side with no such wall stays open and reaches REGION_MARGIN_MM beyond the seed; that is reported.
    """
    unit = data.get("unit")
    if unit not in UNIT_MM:
        raise InvalidInput("Floorplan unit must be cm, mm, or m", code="floorplan-bad-unit")
    k = UNIT_MM[unit]
    tol = TOL / k
    by_id: dict[Any, dict[str, Any]] = {e.get("id"): e for e in elements_of(data)}
    boxes: list[list[float]] = []
    for sid in seeds:
        if sid not in by_id:
            raise InvalidInput(f"Region seed '{sid}' not found", code="floorplan-bad-region", params={"what": sid})
        bb = element_bbox(by_id[sid])
        if not bb:
            raise InvalidInput(f"Region seed '{sid}' has no geometry", code="floorplan-bad-region", params={"what": sid})
        boxes.append(bb)
    if not boxes:
        raise InvalidInput("A region needs at least one seed element", code="floorplan-bad-region", params={"what": "-"})
    seed = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    walls: list[tuple[Any, list[float]]] = [(e.get("id"), bb) for e in by_id.values() if e.get("kind") == "wall" and (bb := element_bbox(e))]
    out = [0.0] * 4
    sides: dict[str, Any] = {}
    for axis, sign, name in ((0, -1, "forwardMin"), (0, 1, "forwardMax"), (1, -1, "rightMin"), (1, 1, "rightMax")):
        other = 1 - axis
        lo_o, hi_o = seed[other], seed[other + 2]
        span = hi_o - lo_o
        cands: list[WallCandidate] = []
        for wid, bb in walls:
            face = bb[axis] if sign > 0 else bb[axis + 2]
            beyond = face - seed[axis + 2] if sign > 0 else seed[axis] - face
            ov = min(hi_o, bb[other + 2]) - max(lo_o, bb[other])
            if beyond >= -tol and ov > 0:
                cands.append((abs(face - (seed[axis + 2] if sign > 0 else seed[axis])), face, wid, (max(lo_o, bb[other]), min(hi_o, bb[other + 2]))))
        cands.sort()
        chosen: list[WallCandidate] | None = None
        i = 0
        while i < len(cands):
            group = [c for c in cands[i:] if abs(c[1] - cands[i][1]) <= tol]
            intervals = sorted(c[3] for c in group)
            covered = 0.0
            cur_end: float | None = None
            for lo0, hi in intervals:
                lo = lo0 if cur_end is None else max(lo0, cur_end)
                if hi > lo:
                    covered += hi - lo
                cur_end = hi if cur_end is None else max(cur_end, hi)
            if covered >= REGION_COVER * span:
                chosen = group
                break
            i += len(group)
        idx = axis if sign < 0 else axis + 2
        if chosen:
            face = min(c[1] for c in chosen) if sign > 0 else max(c[1] for c in chosen)
            out[idx] = face
            sides[name] = {"face": face, "walls": sorted({c[2] for c in chosen}), "open": False}
        else:
            face = seed[idx] + sign * REGION_MARGIN_MM / k
            out[idx] = face
            sides[name] = {"face": face, "walls": [], "open": True}
    return {"bbox": [out[0], out[1], out[2], out[3]], "seeds": list(seeds), "sides": sides, "unit": unit}


def _kitchen_candidates(data: dict[str, Any]) -> list[KitchenCandidate]:
    """Kitchen units that sit in no listed room, grouped by the region the walls give them."""
    rooms = {r["id"]: r for r in list_rooms(data, regions=False)}
    room_polys: dict[Any, list[tuple[float, float]]] = {}
    for e in elements_of(data):
        if e.get("id") in rooms:
            try:
                room_polys[e["id"]] = read_points(field_value(e, "geometry"), str(e["id"]))
            except ValueError:
                pass
    groups: list[KitchenCandidate] = []
    for e in elements_of(data):
        if not is_kitchen_unit(e) or not (bb := element_bbox(e)):
            continue
        c = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
        if any(point_in_poly(c, poly) for poly in room_polys.values()):
            continue
        try:
            reg = derive_region(data, [e["id"]])
        except ValueError:
            continue
        for g in groups:
            if all(abs(a - b) <= 1e-6 + 3 * TOL / UNIT_MM[data["unit"]] for a, b in zip(g["bbox"], reg["bbox"])):
                g["seeds"].append(e["id"])
                g["labels"].append(field_value(e, "label") or e["id"])
                break
        else:
            groups.append({"bbox": reg["bbox"], "seeds": [e["id"]], "labels": [field_value(e, "label") or e["id"]], "open": any(s["open"] for s in reg["sides"].values())})
    return groups


def list_rooms(data: dict[str, Any], regions: bool = True) -> list[dict[str, Any]]:
    """Every element tagged as a room, then (kind 'region') areas the walls enclose around kitchen units that no room covers."""
    out: list[dict[str, Any]] = []
    for e in elements_of(data):
        if e.get("kind") != "area" or field_value(e, "tag") != "room":
            continue
        g = as_dict(field_value(e, "geometry")) or {}
        out.append({"id": e.get("id"), "kind": "room", "label": field_value(e, "label"), "labelStatus": element_field(e, "label").get("status"),
                    "bbox": g.get("bbox"), "points": len(g.get("outline") or [])})
    if regions and isinstance(data.get("elements"), list) and data.get("unit") in UNIT_MM:
        for g in _kitchen_candidates(data):
            out.append({"id": "region:around=" + ",".join(g["seeds"]), "kind": "region", "label": "Kitchen area around " + ", ".join(g["labels"]),
                        "labelStatus": "derived", "bbox": g["bbox"], "points": 4, "seeds": g["seeds"], "openSides": g["open"]})
    return out


def parse_region(data: dict[str, Any], spec: str) -> dict[str, Any]:
    """'region:kitchen' | 'region:around=id,id' | 'region:bbox=x0,y0,x1,y1' (file units) -> {"bbox", "seeds"|None, "sides"|None}."""
    body = spec[len("region:"):]
    if body == "kitchen":
        cands = _kitchen_candidates(data)
        if len(cands) != 1:
            raise InvalidInput("region:kitchen needs exactly one kitchen area; found " + (", ".join("region:around=" + ",".join(g["seeds"]) for g in cands) or "none"),
                           code="floorplan-kitchen-area", params={"found": ", ".join("region:around=" + ",".join(g["seeds"]) for g in cands) or "-"})
        return derive_region(data, cands[0]["seeds"])
    if body.startswith("around="):
        return derive_region(data, [x for x in body[len("around="):].split(",") if x])
    if body.startswith("bbox="):
        try:
            x0, y0, x1, y1 = (float(v) for v in body[len("bbox="):].split(","))
        except ValueError as err:
            raise InvalidInput("region:bbox needs four numbers x0,y0,x1,y1", code="floorplan-bad-region", params={"what": "bbox"}) from err
        if x1 <= x0 or y1 <= y0:
            raise InvalidInput("region:bbox must have x1 > x0 and y1 > y0", code="floorplan-bad-region", params={"what": "bbox"})
        return {"bbox": [x0, y0, x1, y1], "seeds": None, "sides": None, "unit": data.get("unit")}
    raise InvalidInput(f"Unknown region '{spec}'. Use region:kitchen, region:around=<ids> or region:bbox=x0,y0,x1,y1", code="floorplan-bad-region", params={"what": spec})
