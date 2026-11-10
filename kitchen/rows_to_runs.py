"""Rewrite a kitchen whose cabinets follow the walls (or stand in a legacy free run) as explicit runs standing in exactly the same place.

A run is a pure rotation: its s grows to the right of someone looking at the doors. The rows of the back wall, the left wall and the free runs
facing +z / +x measure the other way, so their cabinets are mirrored along the row: ``s = length - fromCorner - width``, door widths in
reverse order. A blind corner or an end panel changes ends with them (``blindSide``). A corner shelf becomes a cabinet at the end of the back run that
turns into the right run (``turnsInto``); without both runs it is left on its walls and reported. The kitchen frame is kept by writing the wall lengths down (``room``), since a kitchen without
wall cabinets no longer implies them. Pure: data in, data out; ``equivalent`` tells whether two kitchens compile to the same boxes.
"""
from __future__ import annotations

from typing import Any

from . import geometry, hardware, runs
from .numeric import round_half_away, round_int
from .spec import KitchenSpec, Module, to_data

WALLS = ("back", "right", "left")


def _row_key(m: Module) -> tuple[Any, ...] | None:
    if m.run or m.wall == "corner":
        return None
    if m.wall == "island":
        return ("island", m.offset, m.facing or "-z", m.depth)        # the depth is part of a free run's seat
    return (m.wall,)


def _wall_run(spec: KitchenSpec, scene: Any, wall: str) -> tuple[str, float, bool] | None:
    """An explicit run that already stands for ``wall`` (a kitchen converted earlier): (run id, the s of the back-right corner along it, mirrored)."""
    for r in spec.runs:
        fr = runs.RunFrame(r.id, r.x, r.z, r.yaw)
        if runs.run_wall(fr, scene.lsau) == wall and any(m.run == r.id for m in spec.module):
            s, _ = fr.to_local(0.0, 0.0)
            return r.id, float(round_half_away(s, 3)), wall == "back"
    return None


_SIDE = {"Left": "left", "Right": "right", "Top": "upper", "Bottom": "base"}


def _hinge_sides(m: Module, scene: Any) -> list[str]:
    """The hinge side every door of a cabinet has now, in the order ``Module.hingeSides`` counts doors (rows from the bottom, left to right)."""
    doors = [p for p in scene.parts if p.module == m.id and p.type in ("door", "glass-door")]
    boxes = []
    for p in doors:
        u0, u1, _ = runs.front_span(p.orient, p.min, p.max)
        boxes.append((u0, u1, p.min[1], p.max[1]))
    now = hardware.hinges(m, boxes)
    order = sorted(range(len(boxes)), key=lambda i: (round_int(boxes[i][2]), boxes[i][0]))
    return [_SIDE[now[i]] for i in order if now[i] in _SIDE]


def convert(spec: KitchenSpec) -> tuple[dict[str, Any], list[str]]:
    """``(spec data with every convertible row as an explicit run, notes)``. Rows that cannot be converted stay as they are."""
    scene = geometry.compile_spec(spec)
    data = to_data(spec)
    notes: list[str] = []
    rows: dict[tuple[Any, ...], list[Module]] = {}
    for m in spec.module:
        key = _row_key(m)
        if key is None:
            continue
        rows.setdefault(key, []).append(m)
    taken = {r.id for r in spec.runs}
    made: dict[tuple[Any, ...], tuple[str, float, bool]] = {}           # row -> (run id, length, mirrored)
    by_id = {m["id"]: m for m in data["module"]}
    for key, mods in rows.items():
        seat = runs.seat_of(mods[0], scene.lsau)
        if seat is None:
            continue
        mirrored = seat.left_end(0.0, 1.0) == 1.0
        length = max(m.endAt for m in mods)
        n = 1
        while f"R{n}" in taken:
            n += 1
        rid = f"R{n}"
        taken.add(rid)
        x, z = seat.to_world(length if mirrored else 0.0, 0.0)
        data.setdefault("runs", []).append({"id": rid, "x": float(x), "z": float(z), "yaw": seat.yaw})
        made[key] = (rid, length, mirrored)
        for m in mods:
            out = by_id[m.id]
            out.update(wall="island", run=rid, offset=0, facing=None, fromCorner=(length - m.fromCorner - m.width) if mirrored else m.fromCorner)
            if m.wall == "right" and not m.blindCorner:   # a lone door on the right wall hinges on the right by default; off the wall that must be said
                sides = _hinge_sides(m, scene)
                if sides:
                    out["hingeSides"] = sides
            if mirrored and (m.blindCorner or m.endPanel):   # the corner end of a mirrored row is the END of its run
                out["blindSide"] = "end" if m.blindSide == "start" else "start"
            if mirrored:                                  # door widths are listed along the row; hinge sides are told as seen from the front, which stays
                out["doors"] = list(reversed(out.get("doors") or []))
    for m in spec.module:                                              # a corner shelf: first leg at the end of the back run, second at the start of the right run
        if m.wall != "corner":
            continue
        back, right = made.get(("back",)) or _wall_run(spec, scene, "back"), made.get(("right",)) or _wall_run(spec, scene, "right")
        if back is None or right is None or (m.backLength or 0) > back[1]:
            notes.append(f"{m.id}: a corner shelf needs a run along the back wall (at least as long as its leg) and one along the right wall; left on its walls")
            continue
        notes = [n for n in notes if not n.startswith(f"{m.id}:")]
        by_id[m.id].update(wall="island", run=back[0], turnsInto=right[0], fromCorner=back[1] - (m.backLength or 0), width=m.backLength)
    if not made and not any(m.get("turnsInto") for m in data["module"]):
        return data, notes
    for tb in data.get("appliances", []):                                # a worktop appliance given by wall + centre joins the cabinet under it
        wall, center = tb.get("wall"), tb.get("center")
        if wall not in WALLS or center is None or (wall,) not in made:
            continue
        rid, length, mirrored = made[(wall,)]
        host = next((m for m in rows[(wall,)] if m.id == tb.get("module")), None) or \
            next((m for m in rows[(wall,)] if m.storey == "base" and m.fromCorner <= center < m.endAt), None)
        if host is None:
            notes.append(f"{tb.get('id')}: no cabinet under it on the {wall} wall; left by wall and centre")
            continue
        along = length - center if mirrored else center
        middle = by_id[host.id]["fromCorner"] + host.width / 2
        tb.update(module=tb.get("module") or host.id, wall=None, center=None if abs(along - middle) <= 0.5 else along)
    wall_runs = {key[0]: rid for key, (rid, _, _) in made.items() if len(key) == 1}
    for mol in data.get("moldings", []):
        if mol.get("wall"):
            mol["wall"] = [wall_runs.get(w, w) for w in mol["wall"]]
    room = data.get("room") or {"wall": []}
    have = {w.get("id") for w in room.get("wall", [])}
    room["wall"] = [*room.get("wall", []), *[{"id": w, "length": float(v)} for w, v in (("back", scene.lsau), ("right", scene.lphai)) if w not in have and v > 0]]
    data["room"] = room
    return data, notes


def _boxes(spec: KitchenSpec) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    scene = geometry.compile_spec(spec)

    def r(v: Any) -> tuple[float, ...]:
        return tuple(float(round_half_away(float(c), 1)) + 0.0 for c in v)
    parts = sorted((str(p.module), p.type, r(p.min), r(p.max)) for p in scene.parts)
    meshes = sorted((m.type, len(m.vertices), r((min(v[0] for v in m.vertices), min(v[1] for v in m.vertices), min(v[2] for v in m.vertices))),
                     r((max(v[0] for v in m.vertices), max(v[1] for v in m.vertices), max(v[2] for v in m.vertices)))) for m in scene.meshes if m.vertices)
    return parts, meshes


def equivalent(before: KitchenSpec, after: KitchenSpec) -> list[str]:
    """What differs between the compiled kitchens ([] when every box stands where it stood): counts per kind of difference."""
    (pa, ma), (pb, mb) = _boxes(before), _boxes(after)
    out: list[str] = []
    lost, new = [p for p in pa if p not in pb], [p for p in pb if p not in pa]
    if lost or new:
        kinds = sorted({p[1] for p in lost + new})
        out.append(f"{len(lost)} boxes gone, {len(new)} new ({', '.join(kinds)})")
    if ma != mb:
        out.append(f"meshes differ ({sorted({m[0] for m in ma + mb if (m in ma) != (m in mb)})})")
    return out
