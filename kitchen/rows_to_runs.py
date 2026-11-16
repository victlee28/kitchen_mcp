"""Rewrite a kitchen whose cabinets follow the walls (or stand in a legacy free run) as explicit runs standing in exactly the same place.

A run is a pure rotation: its s grows to the right of someone looking at the doors. The rows of the back wall, the left wall and the free runs
facing +z / +x measure the other way, so their cabinets are mirrored along the row: ``s = length - fromCorner - width``, door widths in
reverse order. A blind corner or an end panel changes ends with them (``blindSide``). A corner shelf becomes a cabinet at the end of the back run that
turns into the right run (``turnsInto``); without both runs it is left on its walls and reported. The kitchen frame is kept by writing the wall lengths down (``room``), since a kitchen without
wall cabinets no longer implies them. Pure: data in, data out; ``equivalent`` tells whether two kitchens compile to the same boxes.
"""
from __future__ import annotations

from typing import Any

from . import builtin, geometry, hardware, runs
from .catalog import Catalog
from .errors import InvalidInput
from .numeric import round_half_away, round_int
from .spec import KitchenSpec, Module, Run, from_data, to_data

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


def lone_doors_right(m: Module, scene: Any) -> list[str]:
    """``Module.hingeSides`` (rows from the bottom, left to right) of a cabinet against the right wall, whose doors alone in their row hinge
    on the right as they always did there; ``scene``: a compiled kitchen holding the cabinet (in its run)."""
    doors = [p for p in scene.parts if p.module == m.id and p.type in ("door", "glass-door")]
    boxes: list[tuple[float, float, float, float]] = []
    for p in doors:                              # the run's local box: s along the row, y up
        if p.lmin is not None and p.lmax is not None:
            boxes.append((p.lmin[0], p.lmax[0], p.lmin[1], p.lmax[1]))
        else:
            u0, u1, _ = runs.front_span(p.orient, p.min, p.max)
            boxes.append((u0, u1, p.min[1], p.max[1]))
    as_right = from_data(Module, {**to_data(m), "blindCorner": max(m.blindCorner, 1.0)})          # on the right wall a lone door hinged on the right
    now = hardware.hinges(as_right, boxes)
    order = sorted(range(len(boxes)), key=lambda i: (round_int(boxes[i][2]), boxes[i][0]))
    return [_SIDE[now[i]] for i in order if now[i] in _SIDE]


def has_rows(spec: KitchenSpec) -> bool:
    """Whether any cabinet still follows a wall, stands in a legacy free run or is a corner shelf between two walls."""
    return any(not m.run and m.wall in ("back", "right", "left", "island", "corner") for m in spec.module)


def row_lengths(spec: KitchenSpec) -> tuple[float, float]:
    """(back wall, right wall) lengths for a kitchen still given by wall: the room's own, else as far as its rows (and runs) reach, the back
    wall 600 mm past its cabinets, the right wall 600 mm past the deepest row."""
    def end(wall: str) -> float:
        vals = [m.endAt for m in spec.module if m.wall == wall and not m.run]
        if wall in ("back", "right"):
            vals += [(m.backLength if wall == "back" else m.rightLength) or 0.0 for m in spec.module if m.type == "corner-shelf" and not m.run]
        return max(vals, default=0.0)
    lsau, lphai = geometry.wall_length(spec)          # the room's, or the reach of the runs already there
    if not (spec.room and spec.room.length("back")):
        lsau = max(end("back") + 600, lsau if any(m.run for m in spec.module) else 0.0)
    if not (spec.room and spec.room.length("right")):
        free = [m.offset + m.depth for m in spec.module if m.wall == "island" and not m.run and (m.facing or "-z") in ("-z", "+z")]
        lphai = max(end("right"), end("left"), *free, lphai - 600 if any(m.run for m in spec.module) else 0.0, 0.0) + 600
    return lsau, lphai


def placed_in_run(spec: KitchenSpec, module: dict[str, Any]) -> tuple[dict[str, Any], list[Run]]:
    """A cabinet given by wall (``wall`` + ``fromCorner``), to be added to ``spec`` (a kitchen by runs): (the cabinet placed in the run that
    stands along that wall, the runs that had to be made for it). Its doors, hinges and blind side are read the way the run counts them."""
    probe = dict(module)
    probe.setdefault("id", "__new__")
    data = to_data(spec)
    data["module"] = [*data["module"], probe]
    try:
        out, _ = convert(from_data(KitchenSpec, data))
    except (InvalidInput, ValueError):
        return module, []
    got = next((m for m in out["module"] if m["id"] == probe["id"]), None)
    if got is None or not got.get("run"):
        return module, []
    have = {r.id for r in spec.runs}
    made = [from_data(Run, r) for r in out.get("runs", []) if r["id"] not in have]
    placed = {**module, **{k: got[k] for k in ("wall", "run", "offset", "facing", "fromCorner", "doors", "hingeSides", "blindSide", "turnsInto", "width")
                           if k in got}}
    if "id" not in module:
        placed.pop("id", None)
    return placed, made


def as_runs(spec: KitchenSpec, catalog: Catalog = builtin.CATALOG) -> KitchenSpec:
    """``spec`` written by explicit runs only: the one form the builder, the rules and the exports read. Cabinets given by wall
    (``wall`` back/right/left + ``fromCorner``), legacy free runs and corner shelves between two walls are input forms only."""
    if not has_rows(spec):
        return spec
    data, notes = convert(spec, catalog)
    left = [str(m["id"]) for m in data["module"] if not m.get("run") and m.get("wall") in ("back", "right", "left", "island", "corner")]
    if left:
        raise InvalidInput(f"Cabinets that cannot stand in a run: {', '.join(left)}", code="not-in-run", params={"ids": left, "notes": notes})
    return from_data(KitchenSpec, data)


def convert(spec: KitchenSpec, catalog: Catalog = builtin.CATALOG) -> tuple[dict[str, Any], list[str]]:
    """``(spec data with every convertible row as an explicit run, notes)``. Rows that cannot be converted stay as they are.
    Reads only the walls' lengths (``row_lengths``) and the seats of ``runs``: no wall row is ever compiled."""
    lsau, lphai = row_lengths(spec)
    scene = _Lengths(lsau, lphai)
    hinge_fix: list[Module] = []
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
    shifts: dict[tuple[Any, ...], float] = {}                            # row -> where its start lies in a run it joined (0: a run of its own)
    by_id = {m["id"]: m for m in data["module"]}
    for key, mods in rows.items():
        seat = runs.seat_of(mods[0], scene.lsau)
        if seat is None:
            continue
        mirrored = seat.left_end(0.0, 1.0) == 1.0
        length = max(m.endAt for m in mods)
        x, z = seat.to_world(length if mirrored else 0.0, 0.0)
        shift = 0.0                          # run-local s of a cabinet = shift + (its fromCorner, counted from the run's own start)
        same = None if mods[0].wall not in WALLS else next((r for r in spec.runs if abs((r.yaw - seat.yaw + 180) % 360 - 180) <= 0.01
                     and abs(runs.RunFrame(r.id, r.x, r.z, r.yaw).to_local(x, z)[1]) <= 0.5), None)
        rid = ""
        if same is not None:                 # a cabinet added by wall to a run that already stands along that wall: it joins the run
            rid = same.id
            shift = runs.RunFrame(same.id, same.x, same.z, same.yaw).to_local(x, z)[0]
            if min(shift + ((length - m.fromCorner - m.width) if mirrored else m.fromCorner) for m in mods) < -0.5:
                same = None                  # it would stand before the run's start: a run of its own
                shift = 0.0
        if same is None:
            n = 1
            while f"R{n}" in taken:
                n += 1
            rid = f"R{n}"
            taken.add(rid)
            data.setdefault("runs", []).append({"id": rid, "x": float(x), "z": float(z), "yaw": seat.yaw, **({"anchor": "end"} if mirrored else {})})
        made[key] = (rid, length, mirrored)
        shifts[key] = shift
        for m in mods:
            out = by_id[m.id]
            at = (length - m.fromCorner - m.width) if mirrored else m.fromCorner
            out.update(wall="island", run=rid, offset=0, facing=None, fromCorner=shift + at)
            if m.wall == "right" and not m.blindCorner and not m.hingeSides:   # a lone door on the right wall hinges on the right by default; off the wall that must be said
                hinge_fix.append(m)
            if mirrored and (m.blindCorner or m.endPanel):   # the corner end of a mirrored row is the END of its run
                out["blindSide"] = "end" if m.blindSide == "start" else "start"
            if mirrored:                                  # door widths are listed along the row; hinge sides are told as seen from the front, which stays
                out["doors"] = list(reversed(out.get("doors") or []))
    for m in spec.module:                                              # a corner shelf: first leg at the end of the back run, second at the start of the right run
        if m.wall != "corner":
            continue
        leg = float(m.backLength or 0)
        for wall, need in (("back", leg), ("right", 0.0)):
            if made.get((wall,)) is None and _wall_run(spec, scene, wall) is None:     # no cabinet along that wall: a run of its own for the leg
                made[(wall,)] = _new_wall_run(data, taken, wall, need, scene.lsau)
                shifts[(wall,)] = 0.0
        got = made.get(("back",))
        if got is not None and got[2] and got[1] < leg and not shifts.get(("back",)):    # a back run shorter than the leg: it reaches back further
            rid, length, _ = got
            seat = runs.wall_seat("back", scene.lsau)
            assert seat is not None
            x, z = seat.to_world(leg, 0.0)
            for r in data["runs"]:
                if r["id"] == rid:
                    r["x"], r["z"] = float(x), float(z)
            for mod in data["module"]:
                if mod.get("run") == rid:
                    mod["fromCorner"] = float(mod["fromCorner"]) + leg - length
            made[("back",)] = (rid, leg, True)
        back, right = made.get(("back",)) or _wall_run(spec, scene, "back"), made.get(("right",)) or _wall_run(spec, scene, "right")
        if back is None or right is None or (m.backLength or 0) > back[1] or shifts.get(("back",), 0.0) or shifts.get(("right",), 0.0):
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
        along = shifts.get((wall,), 0.0) + (length - center if mirrored else center)
        middle = by_id[host.id]["fromCorner"] + host.width / 2
        tb.update(module=tb.get("module") or host.id, wall=None, center=None if abs(along - middle) <= 0.5 else along)
    wall_runs = {key[0]: rid for key, (rid, _, _) in made.items() if len(key) == 1}
    for mol in data.get("moldings", []):
        if mol.get("wall"):
            mol["wall"] = [wall_runs.get(w, w) for w in mol["wall"]]
    room: dict[str, Any] = data.get("room") or {"wall": []}
    have = {w.get("id") for w in room.get("wall", [])}
    room["wall"] = [*room.get("wall", []), *[{"id": w, "length": float(v)} for w, v in (("back", scene.lsau), ("right", scene.lphai)) if w not in have and v > 0]]
    data["room"] = room
    if hinge_fix and not any(not m.get("run") and m.get("wall") in ("back", "right", "left", "island", "corner") for m in data["module"]):
        # the hinge sides the right wall gave its doors, read off the doors of the run they now stand in
        try:
            built = geometry.compile_spec(from_data(KitchenSpec, data), catalog)
        except InvalidInput as error:         # a catalog that cannot build the kitchen: the doors keep the run's default hinges
            notes.append(f"hinge sides of {', '.join(m.id for m in hinge_fix)} not kept: {error}")
            return data, notes
        for m in hinge_fix:
            sides = lone_doors_right(m, built)
            if sides:
                by_id[m.id]["hingeSides"] = sides
    return data, notes


def _new_wall_run(data: dict[str, Any], taken: set[str], wall: str, length: float, back_length: float) -> tuple[str, float, bool]:
    """An empty run along ``wall`` (``length`` mm from the corner), for the leg of a corner shelf: (run id, length, mirrored)."""
    seat = runs.wall_seat(wall, back_length)
    assert seat is not None
    mirrored = seat.left_end(0.0, 1.0) == 1.0
    n = 1
    while f"R{n}" in taken:
        n += 1
    rid = f"R{n}"
    taken.add(rid)
    x, z = seat.to_world(length if mirrored else 0.0, 0.0)
    data.setdefault("runs", []).append({"id": rid, "x": float(x), "z": float(z), "yaw": seat.yaw, **({"anchor": "end"} if mirrored else {})})
    return rid, length, mirrored


class _Lengths:
    """The two wall lengths a conversion needs, where a compiled scene used to be passed."""
    def __init__(self, lsau: float, lphai: float):
        self.lsau, self.lphai = lsau, lphai


def _boxes(spec: KitchenSpec, catalog: Catalog = builtin.CATALOG) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    scene = geometry.compile_spec(spec, catalog)

    def r(v: Any) -> tuple[float, ...]:
        return tuple(float(round_half_away(float(c), 1)) + 0.0 for c in v)
    parts = sorted((str(p.module), p.type, r(p.min), r(p.max)) for p in scene.parts)
    meshes = sorted((m.type, len(m.vertices), r((min(v[0] for v in m.vertices), min(v[1] for v in m.vertices), min(v[2] for v in m.vertices))),
                     r((max(v[0] for v in m.vertices), max(v[1] for v in m.vertices), max(v[2] for v in m.vertices)))) for m in scene.meshes if m.vertices)
    return parts, meshes


def equivalent(before: KitchenSpec, after: KitchenSpec, catalog: Catalog = builtin.CATALOG) -> list[str]:
    """What differs between the compiled kitchens ([] when every box stands where it stood): counts per kind of difference."""
    (pa, ma), (pb, mb) = _boxes(before, catalog), _boxes(after, catalog)
    out: list[str] = []
    lost, new = [p for p in pa if p not in pb], [p for p in pb if p not in pa]
    if lost or new:
        kinds = sorted({p[1] for p in lost + new})
        out.append(f"{len(lost)} boxes gone, {len(new)} new ({', '.join(kinds)})")
    if ma != mb:
        out.append(f"meshes differ ({sorted({m[0] for m in ma + mb if (m in ma) != (m in mb)})})")
    return out
