"""What the Three.js export takes from a floorplan: binding, room section, finished document."""
from __future__ import annotations

import copy
from typing import Any

from .binding import apply_binding, bind_kitchen
from .structures import structures


# ---------------------------------------------------------------- the 3D file: what threejs_export takes from a floorplan
def _v3(p: dict[str, Any]) -> dict[str, Any]:
    return {"x": p["x"], "y": 0, "z": p["z"]}


def resolve_binding(fp: dict[str, Any], need: dict[str, Any] | None) -> dict[str, Any] | None:
    """The stored binding, else an automatic one when the design has cabinets (``need`` = run lengths), else None.

    Raises ValueError when the kitchen fits no wall: a wrong scene is never produced.
    """
    if fp.get("binding"):
        return fp["binding"]
    return bind_kitchen(fp, need) if need else None


def room_section(fp: dict[str, Any], binding: dict[str, Any] | None, wall_material: str, structs: list[Any] | None = None) -> dict[str, Any]:
    """Pieces of the three.js ``room``: size, floor outline, wall data (``visible`` False: anchors and openings only) and structures."""
    names = {}
    if binding:
        names = {binding["back"]: "WALL-BACK"}
        if binding.get("right") is not None:
            names.setdefault(binding["right"], "WALL-RIGHT")
        if binding.get("left") is not None:
            names.setdefault(binding["left"], "WALL-LEFT")
    walls: list[dict[str, Any]] = []
    for w in fp["walls"]:
        wid = names.get(w["edge"], w["id"])
        walls.append({"id": wid, "start": _v3(w["start"]), "end": _v3(w["end"]), "height": w["height"], "thickness": w["thickness"],
                      "thicknessSource": w["thicknessSource"], "visible": False, "materialId": wall_material, "interiorNormal": _v3(w["interiorNormal"]),
                      "openings": [{"id": f"{wid}-O{i + 1}", "type": "window" if o.get("type") == "window" else "door", "offset": o["offset"],
                                    "width": o["width"], "height": o["height"], "sillHeight": o.get("sillHeight", 0)} for i, o in enumerate(w["openings"])]})
    out_structs: list[dict[str, Any]] = []
    for st in (structs if structs is not None else structures(fp)):
        d = dict(st)
        for key in ("swing", "arrow"):
            if key in d:
                d[key] = [_v3(q) for q in d[key]]
        if "hinge" in d:
            d["hinge"] = _v3(d["hinge"])
        out_structs.append(d)
    return {"width": fp["width"], "depth": fp["depth"], "floorOutline": [{"x": q["x"], "z": q["z"]} for q in fp["outline"]],
            "walls": walls, "structures": out_structs}


def finish_document(doc: dict[str, Any], fp: dict[str, Any], binding: dict[str, Any] | None) -> dict[str, Any]:
    """A copy of the finished document: references to walls that do not exist dropped, the floorplan recorded, the kitchen moved into the room."""
    doc = copy.deepcopy(doc)
    ids = {w["id"] for w in doc["room"]["walls"]}
    for md in doc["modules"]:
        placement = md.get("placement", {})
        if placement.get("wallId") not in ids:
            placement.pop("wallId", None)
    doc["coordinateSystem"]["wallFrames"] = [wf for wf in doc["coordinateSystem"]["wallFrames"] if wf["wallId"] in ids]
    doc["metadata"]["floorplan"] = {"ref": fp["ref"], "roomId": fp["roomId"], "roomLabel": fp.get("roomLabel"), "warnings": fp["warnings"][:50],
                                    **({"binding": {k: binding[k] for k in ("back", "right", "left", "offset", "source", "score", "warnings")}} if binding else {})}
    if binding:
        doc = apply_binding(doc, fp, binding)
    return doc
