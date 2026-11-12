"""JSON-in / JSON-out wrappers around the portable core, one per golden function id (rule R19).

Each wrapper takes the ``input`` object of a case and returns plain JSON data. A future Rust build exposes the same ids with the same
inputs and outputs, and runs the same files in tests/golden/. Wrappers hold no logic of their own beyond decoding input and
projecting the result to the fields the case pins down.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen.spec import KitchenSpec  # noqa: E402
from kitchen import edit, floorplan, geometry, layers, moldings, numeric, proposal, rules, run_line, runs, structure_mesh  # noqa: E402
from kitchen.recognition import build_draft, build_layout, choose_recognizer, gemini_wire, recognizer_wire, runs_from_draft  # noqa: E402
from kitchen import intent, run_template, tv_system, vocab  # noqa: E402
from kitchen import appliance_kind, appliance_models, camera_plan, system_replace, wall_line  # noqa: E402
from kitchen import handles, hardware, lexicon, regions  # noqa: E402
from kitchen import cabinet_run, edit_intent, rows_to_runs, threejs_export  # noqa: E402
from kitchen.spec import Handle, Module  # noqa: E402
from kitchen.placement import Placement  # noqa: E402
from kitchen.spec import load_spec, to_data  # noqa: E402
from kitchen.catalog import expr  # noqa: E402
from kitchen import cabinet_types  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402


def _env(raw: dict) -> dict:
    return {k: v if isinstance(v, bool) else float(v) for k, v in raw.items()}


def catalog_expr_run(i):
    """The value of a formula, or the error code and the position it points at."""
    try:
        return {"value": expr.run(i["text"], _env(i["env"]), i.get("want"))}
    except InvalidInput as e:
        return {"error": e.code, "at": e.params.get("at")}


def catalog_expr_compile(i):
    try:
        f = expr.compile(i["text"], i["names"], i.get("want"))
        return {"type": f.type, "names": list(f.names)}
    except InvalidInput as e:
        return {"error": e.code, "at": e.params.get("at")}


def _placement(i: dict) -> Placement:
    return Placement(float(i["yaw"]), float(i["ox"]), float(i["oz"]))


def placement_to_room(i):
    x, z = _placement(i).to_room(i["x"], i["z"])
    return {"x": x, "z": z}


def placement_to_kitchen(i):
    x, z = _placement(i).to_kitchen(i["x"], i["z"])
    return {"x": x, "z": z}


def numeric_round_half_away(i):
    return {"value": numeric.round_half_away(i["x"], i.get("ndigits", 0))}


def proposal_op_hash(i):
    return {"hash": proposal.op_hash(i["operation"], i["baseRev"])}


def _spec(i):
    src = i["spec"]
    if isinstance(src, dict) and "$fixture" in src:
        src = json.loads((ROOT / src["$fixture"]).read_text(encoding="utf-8"))
    return load_spec(src)


def edit_apply_op(i):
    """Projection: the module list as [id, type, wall, fromCorner, width] and the common block's plinth/ceiling."""
    spec = edit.apply_op(_spec(i), i["op"])
    data = to_data(spec)
    return {"modules": [[m["id"], m["type"], m["wall"], m.get("fromCorner"), m.get("width")] for m in data["module"]],
            "common": {k: data["common"].get(k) for k in i.get("commonKeys", ["plinthHeight", "ceiling"])}}


def floorplan_trim_room(i):
    room, cut = floorplan.trim_room([tuple(p) for p in i["room"]], [(rid, list(r)) for rid, r in i["rects"]], i["snap"])
    return {"room": [list(p) for p in room], "cut": list(cut)}


def structure_mesh_swing_sheet(i):
    pl = _placement(i["placement"])
    sheet = structure_mesh.swing_sheet(i["structure"], pl.to_kitchen)
    if sheet is None:
        return None
    vertices, faces = sheet
    return {"vertices": [list(v) for v in vertices], "faces": [list(f) for f in faces]}


def _spec_after(i):
    """The case's spec, with optional ``ops`` (edit operations) applied first, so a case can describe a broken design briefly."""
    spec = _spec(i)
    for op in i.get("ops", []):
        spec = edit.apply_op(spec, op)
    return spec


def rules_validate(i):
    """Projection: validity, counts, the applied-rule table and each issue as [rule, severity, modules, content]."""
    r = rules.validate(_spec_after(i), None, i.get("country"), i.get("region"))
    return {"valid": r["valid"], "counts": r["dem"], "country": r["country"], "region": r["region"], "appliedRules": r["appliedRules"],
            "issues": [[x["rule"], x["severity"], list(x.get("module") or []), x["content"]] for x in r["issues"]]}


def moldings_compute_runs(i):
    """Projection: each run as [molding id, profile id, y, walls, modules, points rounded to 0.001 mm]."""
    return [[r.molding.id, r.profile.id, round(r.y, 3), list(r.wall), list(r.modules), [[round(x, 3), round(z, 3)] for x, z in r.points]]
            for r in moldings.compute_runs(_spec_after(i))]


def layers_design_op(i):
    spec = _spec_after(i)
    scene = geometry.compile_spec(spec)
    layer, _ = layers.resolve(layers.catalogue(spec, scene), i["layerId"])
    got = layers.design_op(spec, layer, i["material"], scene)
    return None if got is None else {"op": got[0], "scope": got[1]}


def floorplan_apply_binding(i):
    return floorplan.apply_binding(i["doc"], i.get("fp", {}), i["binding"])


def gemini_wire_sniff_media_type(i):
    return {"mediaType": gemini_wire.sniff_media_type(bytes.fromhex(i["hex"]), i.get("declared", ""))}


def gemini_wire_request_body(i):
    """Projection: the prompt's opening and closing words, the image part verbatim, and the generation config."""
    import base64
    body = gemini_wire.request_body(i["kind"], base64.b64decode(i["dataBase64"]), i["mediaType"], i.get("note", ""))
    parts = body["contents"][0]["parts"]
    text = parts[0]["text"]
    cfg = body["generationConfig"]
    out = {"role": body["contents"][0]["role"], "textStart": text[:60], "mentionsTypes": all(t in text for t in i["mustMention"]),
           "image": parts[1]["inline_data"], "responseMimeType": cfg["responseMimeType"], "temperature": cfg["temperature"],
           "schemaRequired": cfg["responseSchema"]["required"]}
    if len(parts) > 2:
        out["noteText"] = parts[2]["text"]
    return out


def gemini_wire_answer_text(i):
    return {"text": gemini_wire.answer_text(i["response"])}


def gemini_wire_parse_draft(i):
    return {"draft": gemini_wire.parse_draft(i["text"])}


def recognition_choose_recognizer(i):
    return {"name": choose_recognizer(i["available"], i.get("requested"), i.get("default"))}


def recognizer_wire_clean_note(i):
    return {"note": recognizer_wire.clean_note(i["text"])}


def recognizer_wire_request_body(i):
    import base64
    return {"body": recognizer_wire.request_body(i["kind"], base64.b64decode(i["dataBase64"]), i.get("note", ""))}


def recognizer_wire_response_error(i):
    return {"error": recognizer_wire.response_error(i["payload"])}


def recognizer_wire_draft_from_runs(i):
    return {"draft": recognizer_wire.draft_from_runs(i["payload"])}


def recognizer_wire_clean_job_id(i):
    return {"job": recognizer_wire.clean_job_id(i["value"])}


def recognizer_wire_job_progress(i):
    return {"progress": recognizer_wire.job_progress(i["payload"])}


def run_line_run_frame(i):
    return {"frame": run_line.run_frame(run_line.Line(tuple(i["a"]), tuple(i["b"]), tuple(i["normal"])))}


def run_line_edge_line(i):
    line = run_line.edge_line([tuple(p) for p in i["outline"]], tuple(i["point"]))
    return {"a": list(line.a), "b": list(line.b), "normal": [round(line.normal[0], 6), round(line.normal[1], 6)]}


def runs_systems(i):
    spec = KitchenSpec.model_validate(i["spec"])
    return {"systems": runs.systems(spec), "tiers": {m.id: runs.tier_of(m) for m in spec.module}}


def recognition_build_layout(i):
    layout = build_layout(i["raw"])
    return {"layout": None if layout is None else layout.to_data()}


def run_line_run_lines(i):
    placed, skipped = run_line.run_lines(run_line.Line(tuple(i["a"]), tuple(i["b"]), tuple(i["normal"])), i["runs"], [tuple(j) for j in i["joints"]])
    return {"placed": [{"run": r["id"], **run_line.run_frame(line)} for r, line in placed], "skipped": skipped}


def recognition_runs_from_draft(i):
    return {"runs": runs_from_draft(build_draft(i["raw"]), i["common"])}


def run_template_run_from_template(i):
    """Projection: each cabinet as [type, width, s, y, height, niche, device types] plus the common block the sentence asked for."""
    color, _ = intent.parse_prompt(i["prompt"])
    out = run_template.run_from_template(color, i["length"])
    return {"modules": [[m["type"], m["width"], m["s"], m["y"], m["height"], m.get("niche"), [d["type"] for d in m.get("appliances", [])]] for m in out["modules"]],
            "common": out["common"]}


def tv_system_layout(i):
    mods = tv_system.layout(i["length"], i.get("common", {}), i.get("style", "columns"), i.get("panel", True))
    return {"modules": [[m["type"], m["s"], m["width"], m["y"], m["height"]] for m in mods],
            "tv": [m["appliance"]["model"] for m in mods if m.get("appliance")],
            "panel": [m["backPanel"] for m in mods if m.get("backPanel")]}


def vocab_to_english(i):
    return {"english": vocab.to_english(i["text"]), "color": vocab.color(i["text"])}


def _app(spec, i):
    return next(a for a in spec.appliances if a.id == i["appliance"])


def appliance_kind_plan(i):
    spec = _spec_after(i)
    ops, summary = appliance_kind.plan(spec, _app(spec, i), appliance_models.model(i["model"]))
    return {"ops": ops, "summary": summary}


def appliance_models_fit(i):
    spec = _spec_after(i)
    status, reasons = appliance_models.fit(spec, _app(spec, i), appliance_models.model(i["model"]))
    return {"status": status, "reasons": reasons}


def appliance_models_candidates(i):
    spec = _spec_after(i)
    return {"models": [[c["id"], c["status"]] for c in appliance_models.candidates(spec, _app(spec, i), i.get("text", ""))]}


def system_replace_relayout_ops(i):
    """``laid``: {run: [modules]}; ``sentence`` decides which appliance models are kept (``kept_models``)."""
    spec = _spec_after(i)
    mods = system_replace.members(spec, i["system"])
    ops, summary = system_replace.relayout_ops(spec, mods, i["laid"], i.get("fronts", {}), frozenset(i.get("asked", [])),
                                               frozenset(i.get("refused", [])), system_replace.kept_models(spec, mods, i.get("sentence", "")))
    return {"ops": ops, "summary": summary}


def _pts(xs):
    return [(float(p[0]), float(p[1])) for p in xs]


def wall_line_replace_lines(i):
    walls = [seg for poly in i["walls"] for seg in wall_line.segments(_pts(poly))]
    r = wall_line.replace_lines(_pts(i["object"]), walls, i.get("backEdge"))
    if r["status"] == "choose-edge":
        return {"status": "choose-edge", "edges": [[e.index, e.length, e.gap] for e in r["edges"]]}
    return {"status": "ok", "runs": [[list(p.a), list(p.b), list(p.doors), p.depth, p.edge] for p in r["runs"]]}


def camera_plan_plan_views(i):
    faces = [camera_plan.Face(f["key"], f["name"], tuple(f["center"]), tuple(f["normal"]), f["length"], f["height"], f.get("run", ""))
             for f in i["faces"]]
    obs = [camera_plan.Obstacle(o["id"], o["kind"], tuple(_pts(o["outline"])), o["y0"], o["y1"]) for o in i.get("obstacles", [])]
    bodies = [camera_plan.Obstacle(o["id"], o["kind"], tuple(_pts(o["outline"])), o["y0"], o["y1"]) for o in i.get("bodies", [])]
    room = _pts(i["room"]) if i.get("room") else None
    views = camera_plan.plan_views(faces, room, obs, bodies)
    return {"views": {k: {"position": list(v["position"]), "lookAt": list(v["lookAt"]), "verticalFov": v["verticalFov"], "hide": v["hide"]}
                      for k, v in sorted(views.items())}}


def _floorplan(i):
    """The case's floorplan document: inline, or ``{"$fixture": path}`` (UTF-8 with or without BOM); ``normalized: true`` normalises it."""
    src = i["floorplan"]
    if isinstance(src, dict) and "$fixture" in src:
        src = json.loads((ROOT / src["$fixture"]).read_text(encoding="utf-8-sig"))
    return floorplan.normalize(src, i.get("roomId")) if i.get("normalized") else src


def regions_normalize(i):
    c, r = regions.normalize(i.get("country"), i.get("region"))
    return {"country": c, "region": r}


def regions_from_description(i):
    c, r = regions.from_description(i["text"])
    return {"country": c, "region": r}


def regions_sort_rows(i):
    rows = regions.sort_rows(i["rows"], i.get("country"), i.get("region"))
    return {"order": [r["code"] for r in rows], "scores": [regions.priority_score(r, i.get("country"), i.get("region")) for r in rows]}


def hardware_hinges(i):
    return {"hinges": hardware.hinges(Module.model_validate(i["module"]), [tuple(d) for d in i["doors"]])}


def hardware_handle(i):
    return {"handle": hardware.handle(Handle.model_validate(i.get("handle", {})), i["w"], i["h"], i["tier"], i.get("hinge"), i.get("horizontal", False))}


def handles_clear_overrides(i):
    op, cleared = handles.clear_overrides(_spec_after(i), tuple(i["fields"]))
    return {"op": op, "cleared": cleared}


def handles_material_slot(i):
    slot, name = handles.material_slot(_spec_after(i), i.get("module"))
    return {"slot": slot, "material": name}


def lexicon_interpret(i):
    r = lexicon.interpret(i["text"])
    return {"updates": r.updates, "items": r.items}


def lexicon_tag_phrases(i):
    return {"phrases": lexicon.tag_phrases(i.get("tags"))}


def floorplan_normalize(i):
    """Projection: the room's size, outline, element and wall counts, warning codes and the source hash."""
    fp = floorplan.normalize(_floorplan(i), i.get("roomId"))
    return {"roomId": fp["roomId"], "width": fp["width"], "depth": fp["depth"], "height": fp["height"], "outline": fp["outline"],
            "walls": len(fp["walls"]), "elements": sorted(e["id"] for e in fp["elements"]), "counts": fp["counts"],
            "warnings": sorted({w["code"] for w in fp["warnings"]}), "sha256": fp["sourceSha256"]}


def floorplan_list_rooms(i):
    return {"rooms": [[r["id"], r.get("label")] for r in floorplan.list_rooms(_floorplan(i), i.get("regions", True))]}


def floorplan_bind_kitchen(i):
    b = floorplan.bind_kitchen(_floorplan(i), i["need"], i.get("backEdge"), i.get("offset", 0.0))
    return {k: b[k] for k in ("back", "right", "left", "offset", "source", "score", "warnings", "transform")}


def floorplan_structures(i):
    return {"structures": [[st["id"], st["kind"], st.get("base"), st.get("height"), len(st["outline"])] for st in floorplan.structures(_floorplan(i))]}


def floorplan_detect_back(i):
    return {"back": floorplan.detect_back(i["outline"], _floorplan(i))}


def _r3(v):
    return [round(float(x), 3) for x in v]


def geometry_compile_spec(i):
    """Projection: the frame lengths, the part count per type and every part as [id, module, type, min, max] (mm, 0.001)."""
    scene = geometry.compile_spec(_spec_after(i))
    counts = {}
    for p in scene.parts:
        counts[p.type] = counts.get(p.type, 0) + 1
    return {"lsau": scene.lsau, "lphai": scene.lphai, "counts": dict(sorted(counts.items())),
            "parts": [[p.id, p.module, p.type, _r3(p.min), _r3(p.max)] for p in scene.parts], "meshes": [[m.id, m.type, len(m.vertices)] for m in scene.meshes]}


def threejs_export_export(i):
    """Projection: per section the ids with their kind, size and place (mm, 0.01), the camera rigs, the material ids and the integrity check."""
    doc = threejs_export.export(_spec_after(i), "golden", 1, created_at="2026-01-01T00:00:00+00:00")

    def dims(x):
        d = x["dimensions"]
        return [d["width"], d["height"], d["depth"]]

    def place(x):
        t = x["transform"]
        return [t["position"]["x"], t["position"]["y"], t["position"]["z"], t["rotation"]["y"]]
    return {"schemaVersion": doc["schemaVersion"], "room": dims(doc["room"]), "walls": [w["id"] for w in doc["room"]["walls"]],
            "modules": [[m["id"], m["moduleType"], dims(m), place(m), len(m["parts"]), len(m["doors"]), len(m["drawers"])] for m in doc["modules"]],
            "appliances": [[a["id"], a["type"], dims(a), place(a)] for a in doc["appliances"]],
            "accessories": [[a["id"], a["type"], dims(a), len(a.get("cutouts", []))] for a in doc["accessories"]],
            "decorations": [[d["id"], d["type"], len(d["path"]["points"])] for d in doc["decorations"]],
            "cameras": [[c["id"], [c["position"][k] for k in "xyz"], [c["target"][k] for k in "xyz"], c["fov"]] for c in doc["cameras"]],
            "materials": [m["id"] for m in doc["materials"]], "integrity": threejs_export.integrity(doc)}


def edit_intent_interpret_edit(i):
    return edit_intent.interpret_edit(_spec_after(i), i["text"], i.get("scope"))


def cabinet_run_split_widths(i):
    return {"widths": cabinet_run.split_widths(i["length"])}


def cabinet_run_plan_i_run(i):
    return cabinet_run.plan_i_run(_spec_after(i), [tuple(p) for p in i["outline"]], tuple(i["point"]), i.get("moduleType", "base"))


def rows_to_runs_convert(i):
    """Projection: the runs made, each module as [id, run, fromCorner, width, depth], the notes, and what differs after the conversion."""
    spec = _spec_after(i)
    data, notes = rows_to_runs.convert(spec)
    after = load_spec(data)
    return {"runs": data.get("runs", []), "modules": [[m["id"], m.get("run"), m.get("fromCorner"), m.get("width"), m.get("depth")] for m in data["module"]],
            "notes": notes, "differences": rows_to_runs.equivalent(spec, after)}


def proposal_spec_diff(i):
    before = _spec(i)
    after = before
    for op in i["ops"]:
        after = edit.apply_op(after, op)
    diff = proposal.spec_diff(before, after)
    return {**diff, "affected": proposal.affected_modules(diff)}


def run_line_plan_runs(i):
    """A recognised kitchen (``recognized-runs/1``, inline or ``{"$fixture"}``) put on a line: the runs placed, the cabinets added, the summary."""
    doc = i["layout"]
    if isinstance(doc, dict) and "$fixture" in doc:
        doc = json.loads((ROOT / doc["$fixture"]).read_text(encoding="utf-8"))["runs"]
    layout = build_layout(doc)
    if layout is None:
        return None
    runs_in = [{"id": r.id, "length": r.length, "modules": list(r.modules)} for r in layout.runs]
    spec = _spec_after(i)
    line = run_line.Line(tuple(i["a"]), tuple(i["b"]), tuple(i["normal"])) if "a" in i else run_line.back_wall_line(spec, runs_in)
    plan = run_line.plan_runs(spec, line, runs_in, list(layout.joints), i.get("clear"))
    ops = plan["operation"]["ops"] if plan["operation"]["op"] == "multi" else [plan["operation"]]
    return {"runs": plan.get("runs"), "summary": plan.get("summary"),
            "addRuns": [o["run"] for o in ops if o["op"] == "add-run"],
            "modules": [[o["module"]["run"], o["module"]["type"], o["module"]["fromCorner"], o["module"]["width"]] for o in ops if o["op"] == "add"],
            "removed": [o["id"] for o in ops if o["op"] == "remove"]}


def cabinet_run_plan_corner(i):
    """The corner cabinet between two runs; the spec's wall rows are turned into explicit runs first when ``convertRows`` is set."""
    spec = _spec_after(i)
    if i.get("convertRows"):
        spec = load_spec(rows_to_runs.convert(spec)[0])
    return cabinet_run.plan_corner(spec, i["runA"], i["runB"], i.get("width", 900.0), i.get("moduleType", "base"))


def _tup(v):
    """JSON arrays of numbers -> tuples (points), arrays of points -> lists of tuples; other values as they are."""
    if isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v):
        return tuple(v)
    if isinstance(v, list) and v and all(isinstance(x, list) for x in v):
        return [_tup(x) for x in v]
    return v


def _json(v):
    return json.loads(json.dumps(v))


def _geom(name):
    fn = getattr(floorplan.geom, name)
    return lambda i: {"value": _json(fn(*[_tup(a) for a in i["args"]]))}


def regions_priority_score(i):
    score = regions.priority_score(i["row"], i.get("country"), i.get("region"))
    return {"score": score, "label": regions.priority_label(score)}


def handles_material_ops(i):
    spec = _spec_after(i)
    op, scope = handles.material_ops(spec, geometry.compile_spec(spec), i["partIds"], i["material"])
    return {"op": op, "scope": scope}


def lexicon_fold(i):
    return {"folded": lexicon.fold(i["text"])}


def lexicon_notes(i):
    return {"notes": lexicon.notes(lexicon.interpret(i["text"]).items)}


def floorplan_derive_region(i):
    return floorplan.derive_region(_floorplan(i), i["seeds"])


def floorplan_parse_region(i):
    return floorplan.parse_region(_floorplan(i), i["spec"])


def floorplan_kitchen_transform(i):
    return floorplan.kitchen_transform(_floorplan(i), i["binding"])


def floorplan_room_edges(i):
    return {"edges": _json(floorplan.back.room_edges([tuple(p) for p in i["room"]]))}


def floorplan_detect_element_backs(i):
    return {"backs": floorplan.detect_element_backs(_floorplan(i), tuple(i.get("kinds", ["furniture"])), tuple(i["tags"]) if i.get("tags") else None)}


def floorplan_resolve_binding(i):
    b = floorplan.resolve_binding(_floorplan(i), i.get("need"))
    return None if b is None else {k: b[k] for k in ("back", "right", "left", "offset", "source", "transform")}


def floorplan_room_section(i):
    """Projection: size, floor outline, each wall as [id, edge, thickness, openings] and each structure as [id, kind, tag, height]."""
    fp = _floorplan(i)
    sec = floorplan.room_section(fp, i.get("binding"), "MAT-WALL")
    return {"width": sec["width"], "depth": sec["depth"], "floorOutline": sec["floorOutline"],
            "walls": [[w["id"], len(w["openings"]), w["thickness"], w["height"]] for w in sec["walls"]],
            "structures": [[st["id"], st["kind"], st["tag"], st["height"]] for st in sec["structures"]]}


def floorplan_finish_document(i):
    """The L fixture's scene put into a normalised floorplan room: walls kept, the floorplan record, where the first cabinet lands."""
    fp = _floorplan(i)
    binding = floorplan.bind_kitchen(fp, i["need"], i.get("backEdge"))
    doc = threejs_export.export(_spec_after(i), "golden", 1, created_at="2026-01-01T00:00:00+00:00")
    out = floorplan.finish_document(doc, fp, binding)
    first = out["modules"][0]
    return {"walls": [w["id"] for w in out["room"]["walls"]], "coordinateOrigin": out["coordinateSystem"]["origin"],
            "firstModule": [first["id"], first["transform"]["position"], first["transform"]["rotation"]["y"]],
            "floorplanKeys": sorted(out.get("floorplan", {}).keys()), "integrity": threejs_export.integrity(out)}


def floorplan_default_height(i):
    return {"height": floorplan.default_height(i["record"])}


def floorplan_document_hash(i):
    return {"hash": floorplan.document_hash(_floorplan(i))}


def floorplan_document_frame_vectors(i):
    vx, vy = floorplan.document.frame_vectors(i["data"])
    return {"x": list(vx), "y": list(vy)}


def floorplan_document_read_points(i):
    return {"points": [list(p) for p in floorplan.document.read_points(i["value"], i.get("elementId", "e"), i.get("what", "outline"))]}


def floorplan_document_element_bbox(i):
    return {"bbox": floorplan.document.element_bbox(i["element"])}


def floorplan_document_is_kitchen_unit(i):
    return {"kitchen": floorplan.document.is_kitchen_unit(i["element"])}


# ---- helpers of runs, tv_system and appliance_models, one wrapper each (R19)
def _ctx(i):
    """The case's spec: an imported ``floorplan`` set on it (normalised, ``roomId``), rows turned into explicit runs first when
    ``convertRows`` is set, then ``ops`` applied."""
    spec = _spec(i)
    if i.get("floorplan"):
        spec = load_spec({**to_data(spec), "floorplan": floorplan.normalize(_floorplan({"floorplan": i["floorplan"]}), i.get("roomId"))})
    if i.get("convertRows"):
        spec = load_spec(rows_to_runs.convert(spec)[0])
    for op in i.get("ops", []):
        spec = edit.apply_op(spec, op)
    return spec


def _rf(d):
    return runs.RunFrame(d["id"], float(d["x"]), float(d["z"]), float(d["yaw"]))


def _seat(seat):
    if seat is None:
        return None
    import dataclasses
    return {**_json(dataclasses.asdict(seat)), "origin": _json(seat.to_world(0.0, 0.0)), "normal": _json(seat.normal()), "yaw": seat.yaw}


def _frame_data(fr):
    return None if fr is None else {"id": fr.id, "x": fr.x, "z": fr.z, "yaw": fr.yaw}


def _mod(spec, i, key="module"):
    return spec.find(i[key])


def runs_trig(i):
    return {"cs": _json(runs.trig(i["yaw"]))}


def runs_wall_seat(i):
    return {"seat": _seat(runs.wall_seat(i["wall"], i["backLength"]))}


def runs_free_seat(i):
    return {"seat": _seat(runs.free_seat(i["offset"], i["depth"], i["facing"]))}


def runs_seat_of(i):
    spec = _ctx(i)
    return {"seat": _seat(runs.seat_of(_mod(spec, i), i["backLength"]))}


def runs_front_span(i):
    return {"span": _json(runs.front_span(i["front"], tuple(i["min"]), tuple(i["max"])))}


def runs_front_box(i):
    return {"box": _json(runs.front_box(i["front"], *i["args"]))}


def runs_frame_of(i):
    spec = _ctx(i)
    return {"frame": _frame_data(runs.frame_of(spec, _mod(spec, i)))}


def runs_row_of(i):
    spec = _ctx(i)
    return {"rows": {m.id: runs.row_of(m) for m in spec.module}}


def runs_spot(i):
    spec = _ctx(i)
    sp = runs.spot(spec, _app(spec, i))
    return {"spot": None if sp is None else {"row": sp.row, "center": sp.center, "module": sp.module}}


def runs_corner_joints(i):
    return {"joints": [{"a": j.a, "b": j.b, "at": j.at, "angle": j.angle} for j in runs.corner_joints(_ctx(i))]}


def runs_front_cross(i):
    return {"cross": _json(runs.front_cross(_rf(i["a"]), i["da"], _rf(i["b"]), i["db"]))}


def runs_run_wall(i):
    return {"wall": runs.run_wall(_rf(i["frame"]), i["backLength"])}


def runs_walls_used(i):
    return {"walls": sorted(runs.walls_used(_ctx(i), i["backLength"]))}


def runs_along_wall(i):
    return {"span": _json(runs.along_wall(_rf(i["frame"]), i["wall"], i["s0"], i["s1"]))}


def runs_frames(i):
    return {"frames": {k: _frame_data(v) for k, v in runs.frames(_ctx(i)).items()}}


def runs_aabb(i):
    return {"box": _json(runs.aabb([tuple(p) for p in i["points"]]))}


def runs_penetration(i):
    return {"depth": runs.penetration([tuple(p) for p in i["a"]], [tuple(p) for p in i["b"]])}


def runs_module_footprint(i):
    spec = _ctx(i)
    m = _mod(spec, i)
    return {"footprint": _json(runs.module_footprint(require_frame(spec, m), m))}


def require_frame(spec, m):
    from kitchen.errors import require
    return require(runs.frame_of(spec, m), f"{m.id}: run frame")


def runs_strip_extent(i):
    return {"extent": _json(runs.strip_extent([tuple(p) for p in i["poly"]], _rf(i["frame"]), i["dMax"]))}


def runs_system_id(i):
    return {"id": runs.system_id(i["raw"])}


def runs_polygon_gap(i):
    return {"gap": runs.polygon_gap([tuple(p) for p in i["a"]], [tuple(p) for p in i["b"]])}


def runs_run_systems(i):
    return {"systems": runs.run_systems(_ctx(i))}


def tv_system_texts(i):
    """The sentence readers of tv_system on one text: asks_tv, style_of, explicit_style, wants_panel."""
    t = i["text"]
    return {"asksTv": tv_system.asks_tv(t), "style": tv_system.style_of(t), "explicitStyle": tv_system.explicit_style(t),
            "panel": tv_system.wants_panel(t)}


def tv_system_tv_for(i):
    return {"tv": tv_system.tv_for(i["niche"])}


def tv_system_run_fields(i):
    return {"fields": tv_system.run_fields(i["style"])}


def tv_system_front_of(i):
    return {"front": tv_system.front_of(i["common"])}


def tv_system_console(i):
    return {"modules": _json(tv_system.console(i["length"]))}


def tv_system_runs(i):
    """A design's TV runs: tv_runs, layout_of / is_tv_run per run, tv_modules, and what kitchen_only keeps."""
    spec = _ctx(i)
    return {"tvRuns": sorted(tv_system.tv_runs(spec)), "layouts": {r.id: tv_system.layout_of(spec, r.id) for r in spec.runs},
            "isTv": {r.id: tv_system.is_tv_run(r) for r in spec.runs}, "tvModules": sorted(tv_system.tv_modules(spec)),
            "kitchenOnly": [m.id for m in tv_system.kitchen_only(spec).module]}


def appliance_models_lookup(i):
    """The catalogue lookups: model (or its error), default_for, kind_of, needed_width, dimension_string, changes_for."""
    m = appliance_models.model(i["model"])
    return {"kind": appliance_models.kind_of(m), "neededWidth": appliance_models.needed_width(m), "dimensions": appliance_models.dimension_string(m),
            "changes": appliance_models.changes_for(m), "defaultOfType": (appliance_models.default_for(m["type"]) or {}).get("id")}


def appliance_models_of_appliance(i):
    """What a design's appliance is read as: guessed, model_id, size_of, host, where, ai_facts and its sentence."""
    spec = _ctx(i)
    app = _app(spec, i)
    h = appliance_models.host(spec, app)
    facts = appliance_models.ai_facts(spec, app)
    return {"guessed": appliance_models.guessed(app), "modelId": appliance_models.model_id(app), "size": appliance_models.size_of(app),
            "host": h.id if h else None, "where": appliance_models.where(spec, app), "facts": _json(facts),
            "sentence": appliance_models.sentence(facts, i.get("bbox"))}


def appliance_models_changes_cabinets(i):
    spec = _ctx(i)
    app = _app(spec, i)
    return {"changes": appliance_models.changes_cabinets(spec, app, appliance_models.model(i["model"]), appliance_models.host(spec, app))}


def appliance_models_energy_notes(i):
    spec = _ctx(i)
    return {"notes": appliance_models.energy_notes(_app(spec, i), appliance_models.model(i["model"]))}


def appliance_models_over(i):
    spec = _ctx(i)
    return {"over": appliance_models.over(spec.find(i["a"]), spec.find(i["b"]))}


def appliance_models_check(i):
    return {"issues": [[x["rule"], x["severity"], list(x.get("module") or []), x["content"]] for x in appliance_models.check(_ctx(i))]}


# ---- remaining helpers (R19): wall_line, camera_plan, system_replace, run_line, cabinet_run, structure_mesh, layers, proposal, numeric...
def _plain(v):
    """Dataclasses, pydantic models, tuples, sets -> JSON data."""
    import dataclasses
    from pydantic import BaseModel
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {f.name: _plain(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, BaseModel):
        return to_data(v, exclude_none=True)
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (set, frozenset)):
        return sorted(_plain(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def _walls(i):
    return [seg for poly in i.get("walls", []) for seg in wall_line.segments(_pts(poly))]


def _edge_of(i):
    e = i["edge"]
    return wall_line.Edge(e["index"], tuple(e["a"]), tuple(e["b"]), tuple(e["inward"]), e.get("gap"))


def wall_line_segments(i):
    return {"segments": _plain(wall_line.segments(_pts(i["poly"])))}


def wall_line_inward_normal(i):
    return {"normal": _plain(wall_line.inward_normal(_pts(i["poly"]), tuple(i["a"]), tuple(i["b"])))}


def wall_line_wall_gap(i):
    return {"gap": wall_line.wall_gap(tuple(i["a"]), tuple(i["b"]), tuple(i["inward"]), _walls(i))}


def wall_line_edges(i):
    """edges and wall_edges of one object: every edge as [index, a, b, inward, gap, length], and the indexes of the edges against a wall."""
    poly, walls = _pts(i["object"]), _walls(i)
    return {"edges": [[e.index, list(e.a), list(e.b), list(e.inward), e.gap, e.length] for e in wall_line.edges(poly, walls)],
            "wallEdges": [e.index for e in wall_line.wall_edges(poly, walls)]}


def wall_line_depth_from(i):
    return {"depth": wall_line.depth_from(_pts(i["object"]), _edge_of(i))}


def wall_line_back_to_wall(i):
    doors, against = wall_line.back_to_wall(tuple(i["a"]), tuple(i["b"]), tuple(i["normal"]), _walls(i))
    return {"doors": list(doors), "against": against}


def _face(f):
    return camera_plan.Face(f["key"], f["name"], tuple(f["center"]), tuple(f["normal"]), f["length"], f["height"], f.get("run", ""))


def _obstacle(o):
    return camera_plan.Obstacle(o["id"], o["kind"], tuple(_pts(o["outline"])), o["y0"], o["y1"])


def camera_plan_stands_in_room(i):
    return {"inside": camera_plan.stands_in_room(tuple(i["p"]), _pts(i["room"]) if i.get("room") else None, i.get("clear", camera_plan.WALL_CLEAR))}


def camera_plan_blocks(i):
    return {"blocks": camera_plan.blocks(tuple(i["eye"]), tuple(i["target"]), _obstacle(i["obstacle"]))}


def camera_plan_face_targets(i):
    return {"targets": _plain(camera_plan.face_targets(_face(i["face"])))}


def camera_plan_blockers(i):
    return {"blockers": camera_plan.blockers(tuple(i["eye"]), [tuple(t) for t in i["targets"]], [_obstacle(o) for o in i["obstacles"]])}


def camera_plan_in_body(i):
    return {"inBody": camera_plan.in_body(tuple(i["p"]), [_obstacle(o) for o in i["bodies"]], i.get("clear", camera_plan.WALL_CLEAR))}


def camera_plan_faces_room(i):
    return {"facesRoom": camera_plan.faces_room(_face(i["face"]), _pts(i["room"]) if i.get("room") else None)}


def camera_plan_hidden_for(i):
    return {"hidden": camera_plan.hidden_for(tuple(i["position"]), [_face(f) for f in i["faces"]], [_obstacle(o) for o in i["obstacles"]])}


def system_replace_members(i):
    spec = _ctx(i)
    mods = system_replace.members(spec, i["system"])
    return {"members": [m.id for m in mods], "front": system_replace.current_front(spec, mods), "slots": _plain(system_replace.run_slots(spec, mods))}


def system_replace_pick_style(i):
    spec = _ctx(i)
    mods = system_replace.members(spec, i["system"])
    style = system_replace.pick_style(spec, mods, i.get("wanted"))
    return {"style": _plain(style), "ops": system_replace.style_ops(spec, mods, style)}


def system_replace_plain_cabinets(i):
    return {"modules": _plain(system_replace.plain_cabinets(i["modules"]))}


def cabinet_types_storey_of(i):
    return {"storeys": {t: cabinet_types.storey_of(t) for t in i["types"]}}


def system_replace_kept_models(i):
    spec = _ctx(i)
    kept = system_replace.kept_models(spec, system_replace.members(spec, i["system"]), i.get("sentence", ""))
    return {"kept": {k: v["id"] for k, v in sorted(kept.items())}}


def _line(d):
    return run_line.Line(tuple(d["a"]), tuple(d["b"]), tuple(d["normal"]))


def run_line_nearest_edge(i):
    a, b = run_line.nearest_edge(_pts(i["poly"]), tuple(i["p"]))
    return {"a": list(a), "b": list(b), "outward": _plain(run_line.outward(_pts(i["poly"]), a, b))}


def run_line_drawn_line(i):
    line = run_line.drawn_line(tuple(i["a"]), tuple(i["b"]), tuple(i["front"]))
    return {"a": list(line.a), "b": list(line.b), "normal": _plain(line.normal)}


def run_line_base_cabinets(i):
    return {"modules": _plain(run_line.base_cabinets(i["length"], i.get("common", {})))}


def run_line_plan_on_line(i):
    plan = run_line.plan_on_line(_ctx(i), _line(i["line"]), i["modules"], i.get("clear"), i.get("after"), i.get("system"), i.get("runFields"))
    return _plain(plan)


def run_line_back_wall_line(i):
    line = run_line.back_wall_line(_ctx(i), i["runs"])
    return {"a": list(line.a), "b": list(line.b), "normal": _plain(line.normal)}


def run_line_element_against(i):
    structs = [{**st, "outline": _pts(st["outline"])} for st in i["structures"]]
    found, cands = run_line.element_against(i["frame"], i["s0"], i["s1"], structs)
    return {"element": found, "candidates": cands}


def cabinet_run_fit_depth(i):
    return {"modules": _plain(cabinet_run.fit_depth(i["modules"], i["depth"]))}


def cabinet_run_plan_replace(i):
    spec = _ctx(i)
    placed = [wall_line.Placed(tuple(p["a"]), tuple(p["b"]), tuple(p["doors"]), p["depth"], p["edge"]) for p in i["placed"]]
    return _plain(cabinet_run.plan_replace(spec, i["element"], placed, i["laid"], i.get("after"), i.get("runFields")))


def structure_mesh_is_structure(i):
    return {"types": {t: structure_mesh.is_structure(t) for t in i["types"]}}


def structure_mesh_prism(i):
    v, f = structure_mesh.prism(_pts(i["poly"]), i["y0"], i["y1"])
    return {"vertices": _plain(v), "faces": _plain(f)}


def structure_mesh_meshes(i):
    pl = _placement(i["placement"])
    return {"meshes": [[m.id, m.module, m.type, len(m.vertices), len(m.faces)] for m in structure_mesh.meshes(i["structures"], pl.to_kitchen)]}


def layers_material_slot(i):
    spec = _ctx(i)
    return {"slots": {f"{m}/{t}": list(layers.material_slot(spec, m, t)) for m, t in i["parts"]}}


def layers_catalogue(i):
    """Projection: how many layers of each variant, and the groups as [id, type, material, materialLocked, component count]."""
    spec = _ctx(i)
    cat = layers.catalogue(spec, geometry.compile_spec(spec))
    counts = {}
    for x in cat:
        counts[x["variant"]] = counts.get(x["variant"], 0) + 1
    return {"counts": counts, "groups": [[x["id"], x["type"], x["material"], x["materialLocked"], len(x["component"])] for x in cat if x["variant"] == "group"]}


def layers_resolve(i):
    spec = _ctx(i)
    layer, parts = layers.resolve(layers.catalogue(spec, geometry.compile_spec(spec)), i["layerId"])
    return {"layer": [layer["id"], layer["variant"], layer["type"]], "parts": parts}


def layers_changed_parts(i):
    old = _ctx(i)
    new = old
    for op in i["change"]:
        new = edit.apply_op(new, op)
    return {"changed": layers.changed_parts(old, new, geometry.compile_spec(new))}


def proposal_validation_delta(i):
    before = _ctx(i)
    after = before
    for op in i["change"]:
        after = edit.apply_op(after, op)
    d = proposal.validation_delta(rules.validate(before), rules.validate(after))
    short = lambda xs: [[x["rule"], x["severity"], list(x.get("module") or [])] for x in xs]   # noqa: E731
    return {"valid": d["valid"], "introduced": short(d["introduced"]), "resolved": short(d["resolved"]), "remaining": len(d["remaining"]),
            "introducesErrors": d["introducesErrors"]}


def numeric_round_int(i):
    return {"values": [numeric.round_int(x) for x in i["xs"]]}


def numeric_near(i):
    return {"near": numeric.near(i["a"], i["b"], *([i["eps"]] if "eps" in i else []))}


def palette_module_color(i):
    from kitchen import palette
    return {"colors": {m: list(palette.module_color(m)) for m in i["ids"]}}


def errors_kind_of(i):
    """kind_of and http_status of each error class named in the case, plus require on a value and on None."""
    from kitchen import errors as err
    out = {}
    for name in i["classes"]:
        e = getattr(err, name)("x")
        out[name] = [err.kind_of(e), err.http_status(e)]
    out["ValueError"] = [err.kind_of(ValueError("x")), err.http_status(ValueError("x"))]
    return {"classes": out, "requireValue": err.require(i.get("value", 1), "v")}


# ---- geometry, moldings, prompts, recognition, edit (one id per operation kind), appliance_kind (R19)
def _edit_result(before, after):
    """What an edit did: the spec diff (modules added / removed / changed, other paths) and the runs afterwards."""
    diff = proposal.spec_diff(before, after)
    return {"diff": diff, "runs": [to_data(r, exclude_none=True) for r in after.runs]}


def _edit_op(i):
    before = _ctx(i)
    return _edit_result(before, edit.apply_op(before, i["op"]))


def edit_new_id(i):
    spec = _ctx(i)
    return {"ids": {p: edit.new_id(spec, p) for p in i["prefixes"]}, "nextRun": edit.next_run_id(spec)}


def edit_combine_ops(i):
    return {"op": edit.combine_ops(i["ops"])}


def geometry_frame(i):
    """The kitchen frame of a design: wall_length, wall_reach, backsplash_height per row, run_wall per run."""
    spec = _ctx(i)
    lsau, lphai = geometry.wall_length(spec)
    return {"wallLength": [lsau, lphai], "reach": geometry.wall_reach(spec, lsau),
            "backsplash": {w: geometry.backsplash_height(spec, w, r) for w, r in i.get("rows", [])},
            "runWalls": {r.id: geometry.run_wall(runs.RunFrame(r.id, r.x, r.z, r.yaw), lsau) for r in spec.runs}}


def geometry_camera_inputs(i):
    """What the camera planner is given: cabinet_faces, cabinet_bodies and room_solids (outline + solids)."""
    spec = _ctx(i)
    scene = geometry.compile_spec(spec)
    room, solids = geometry.room_solids(spec, scene)
    return {"faces": _plain(geometry.cabinet_faces(spec, scene)), "bodies": [[b.id, b.kind, len(b.outline), b.y0, b.y1] for b in geometry.cabinet_bodies(spec)],
            "room": _plain(room), "solids": [[o.id, o.kind, len(o.outline), o.y0, o.y1] for o in solids]}


def geometry_views(i):
    """default_views and views_of: every view as [name, position, lookAt, fov, hide]."""
    spec = _ctx(i)
    pick = lambda vs: {k: [v.name, list(v.position), list(v.lookAt), v.verticalFov, list(v.hide or [])] for k, v in sorted(vs.items())}   # noqa: E731
    return {"default": pick(geometry.default_views(spec)), "used": pick(geometry.views_of(spec))}


def geometry_scene_json(i):
    """Projection: version, units, bounds, part and module counts, the view names and the molding meshes."""
    sj = geometry.scene_json(_ctx(i))
    return {"version": sj["version"], "units": sj["units"], "bounds": _plain(sj["bounds"]), "parts": len(sj["parts"]), "views": sorted(sj["views"]),
            "modules": len(sj["modules"]), "moldings": sj["moldings"]}


def moldings_profile_of(i):
    spec = _ctx(i)
    out = {}
    for pid in i["ids"]:
        p = moldings.profile_of(spec, pid)
        out[pid] = None if p is None else [p.name, len(p.points), p.height, p.overhang]
    return {"profiles": out}


def moldings_default_moldings(i):
    return {"moldings": [to_data(m, exclude_none=True) for m in moldings.default_moldings(**i.get("args", {}))]}


def moldings_sweep_rings(i):
    return {"rings": _plain(moldings.sweep_rings(_pts(i["profile"]), _pts(i["points"]), i["y"]))}


def moldings_ear_clip(i):
    return {"triangles": _plain(moldings.ear_clip(_pts(i["poly"])))}


def moldings_meshes(i):
    """meshes (run_mesh of every run): [id, molding, vertices, faces]."""
    return {"meshes": [[m.id, m.module, len(m.vertices), len(m.faces)] for m in moldings.meshes(_ctx(i))]}


def moldings_check(i):
    return {"issues": [[x["rule"], x["severity"], list(x.get("module") or []), [a["label"] for a in x.get("action", [])]] for x in moldings.check(_ctx(i))]}


def moldings_lower_top(i):
    spec = _ctx(i)
    after = moldings.lower_top(spec, i["newTop"])
    return {"common": {k: getattr(after.common, k) for k in ("cabinetTop", "upperTierSplit")}, "diff": proposal.spec_diff(spec, after)["modules"]}


def prompts_negative_prompt(i):
    from kitchen import prompts
    return {"text": prompts.negative_prompt(i.get("extra"))}


def prompts_gemini_text(i):
    from kitchen import prompts
    return {"text": prompts.gemini_text(i["kind"], i.get("prompt", ""), i.get("instruction", ""), i.get("stylePrompt", ""), i.get("role", ""), i.get("realism", ""))}


def prompts_gemini_text_edit(i):
    from kitchen import prompts
    return {"text": prompts.gemini_text_edit(i["regions"], i.get("instruction", ""), i.get("realism", ""))}


def prompts_gemini_text_geometry(i):
    from kitchen import prompts
    return {"text": prompts.gemini_text_geometry(i["operation"], i["changes"], i.get("where"), i.get("instruction", ""), i.get("realism", ""))}


def prompts_gemini_text_multi(i):
    from kitchen import prompts
    return {"text": prompts.gemini_text_multi([tuple(r) for r in i["regions"]], i.get("instruction", ""))}


def prompts_style_note(i):
    from kitchen import prompts
    return {"text": prompts.style_note(i["image"], i["view"])}


def prompts_layer(i):
    """global_prompt, tv_text, layer_prompt and edit_task_prompt for one design and one layer."""
    from kitchen.prompts import layer as lp
    spec = _ctx(i)
    layer, _ = layers.resolve(layers.catalogue(spec, geometry.compile_spec(spec)), i["layerId"])
    return {"global": lp.global_prompt(spec), "tv": lp.tv_text(spec), "layer": lp.layer_prompt(spec, layer, i.get("instruction", ""), i.get("material")),
            "edit": lp.edit_task_prompt(spec, layer, i.get("instruction", ""), i.get("material"))}


def prompts_photo(i):
    from kitchen.prompts import photo
    spec = _ctx(i) if i.get("spec") else None
    return {"full": photo.full(spec, i.get("lighting", "daylight")) if spec else None, "local": photo.local(spec, i.get("extra"))}


def prompts_recognition_text(i):
    from kitchen import prompts
    t = prompts.recognition_text(i["kind"], tuple(i["types"]))
    return {"start": t[:120], "length": len(t), "mentions": [x for x in i["types"] if x in t]}


def recognition_common_changes(i):
    from kitchen.recognition import layout as rl
    lay = build_layout(i["layout"])
    if lay is None:
        return None
    return {"changes": rl.common_changes(i["common"], lay, i.get("ceiling"), i.get("materials", {}))}


def recognition_appliance_size(i):
    from kitchen.recognition import layout as rl
    return {"sizes": [rl.appliance_size(k, w, n) for k, w, n in i["cases"]]}


def recognition_fridge_bay(i):
    from kitchen.recognition.draft import DraftModule
    from kitchen.recognition.operation import fridge_bay
    extra, fridge = fridge_bay(DraftModule(type="tall-fridge", wall="back", width=i["width"], niche=i.get("niche")), i["height"], i["depth"])
    return {"module": extra, "fridge": fridge}


def appliance_kind_changes_kind(i):
    spec = _ctx(i)
    return {"changes": appliance_kind.changes_kind(_app(spec, i), appliance_models.model(i["model"]))}


# ---- last helpers (R19): roomctx, rules, rules_kb.select, vocab, edit_intent, jsonview, floorplan readers, recognition
def roomctx_for_spec(i):
    """need_for, then for_spec on the design's floorplan: the binding, the placement and the structures it builds (replaced ones left out)."""
    from kitchen import roomctx
    spec = _ctx(i)
    back, side = geometry.wall_length(spec)
    ctx = roomctx.for_spec(spec, back, side)
    return {"need": roomctx.need_for(spec, back, side),
            "context": None if ctx is None else {"replaced": roomctx.replaced(ctx.floorplan), "back": (ctx.binding or {}).get("back"),
                                                 "placement": [ctx.placement.yaw, ctx.placement.ox, ctx.placement.oz],
                                                 "structures": sorted(st["sourceElement"] for st in ctx.structures)}}


def rules_check_geometry(i):
    return {"issues": [[x["rule"], x["severity"], list(x.get("module") or [])] for x in rules.check_geometry(_ctx(i))]}


def rules_kb_select(i):
    """default_rows (the seed knowledge) put through select for a country / region: topic -> [code, severity, reference]."""
    from kitchen import rules_kb
    sel = rules_kb.select(rules.default_rows(), i.get("country"), i.get("region"))
    return {"selected": {t: [v["code"], v["severity"], v["reference"]] for t, v in sorted(sel.items())}}


def vocab_words(i):
    """norm, has (for each key), explicit_color and hex_rgb of its colour, for one text."""
    t = i["text"]
    c = vocab.explicit_color(t)
    return {"norm": vocab.norm(t), "has": {k: vocab.has(vocab.norm(t), k) for k in i.get("keys", [])}, "explicitColor": c,
            "rgb": list(vocab.hex_rgb(c)) if c else None}


def edit_intent_check_operation(i):
    return edit_intent.check_operation(i["op"])


def edit_intent_module_choices(i):
    spec = _ctx(i)
    return {"choices": edit_intent.module_choices([m for m in spec.module if m.storey in i.get("storeys", ["base"])])}


def jsonview_views(i):
    from kitchen import jsonview
    return {"asDict": [jsonview.as_dict(v) is not None for v in i["values"]], "asList": [jsonview.as_list(v) is not None for v in i["values"]]}


def floorplan_document_fields(i):
    """elements_of, element_field and field_value of a document: per element its ``fields`` read for the names given."""
    els = floorplan.document.elements_of(i["data"])
    return {"elements": [[e.get("id"), {n: [floorplan.document.element_field(e, n), floorplan.document.field_value(e, n)] for n in i["names"]}] for e in els]}


def floorplan_outline_xy(i):
    return {"points": _plain(floorplan.back.outline_xy(i["outline"]))}


def recognition_draft_numbers(i):
    from kitchen.recognition import draft
    return {"numbers": [draft.number(v) for v in i["values"]], "confidence": [draft.confidence_of(v) for v in i["values"]]}


def recognizer_wire_layout_from_runs(i):
    return {"layout": recognizer_wire.layout_from_runs(i["payload"])}


FUNCTIONS = {
    "roomctx.for_spec": roomctx_for_spec,
    "rules.check_geometry": rules_check_geometry,
    "rules_kb.select": rules_kb_select,
    "vocab.words": vocab_words,
    "edit_intent.check_operation": edit_intent_check_operation,
    "edit_intent.module_choices": edit_intent_module_choices,
    "jsonview.views": jsonview_views,
    "floorplan.document.fields": floorplan_document_fields,
    "floorplan.outline_xy": floorplan_outline_xy,
    "recognition.draft.numbers": recognition_draft_numbers,
    "recognition.recognizer_wire.layout_from_runs": recognizer_wire_layout_from_runs,
    "edit.add_module": _edit_op,
    "edit.add_run": _edit_op,
    "edit.move_run": _edit_op,
    "edit.set_run_system": _edit_op,
    "edit.set_run_tv": _edit_op,
    "edit.update_appliance": _edit_op,
    "edit.replace_element": _edit_op,
    "edit.remove_run": _edit_op,
    "edit.stretch_run": _edit_op,
    "edit.remove_module": _edit_op,
    "edit.update_module": _edit_op,
    "edit.update_common": _edit_op,
    "edit.lower_top": _edit_op,
    "edit.molding": _edit_op,
    "edit.set_moldings": _edit_op,
    "edit.set_views": _edit_op,
    "edit.replace": _edit_op,
    "edit.new_id": edit_new_id,
    "edit.combine_ops": edit_combine_ops,
    "geometry.frame": geometry_frame,
    "geometry.camera_inputs": geometry_camera_inputs,
    "geometry.views": geometry_views,
    "geometry.scene_json": geometry_scene_json,
    "moldings.profile_of": moldings_profile_of,
    "moldings.default_moldings": moldings_default_moldings,
    "moldings.sweep_rings": moldings_sweep_rings,
    "moldings.ear_clip": moldings_ear_clip,
    "moldings.meshes": moldings_meshes,
    "moldings.check": moldings_check,
    "moldings.lower_top": moldings_lower_top,
    "prompts.negative_prompt": prompts_negative_prompt,
    "prompts.gemini_text": prompts_gemini_text,
    "prompts.gemini_text_edit": prompts_gemini_text_edit,
    "prompts.gemini_text_geometry": prompts_gemini_text_geometry,
    "prompts.gemini_text_multi": prompts_gemini_text_multi,
    "prompts.style_note": prompts_style_note,
    "prompts.layer": prompts_layer,
    "prompts.photo": prompts_photo,
    "prompts.recognition_text": prompts_recognition_text,
    "recognition.common_changes": recognition_common_changes,
    "recognition.appliance_size": recognition_appliance_size,
    "recognition.fridge_bay": recognition_fridge_bay,
    "appliance_kind.changes_kind": appliance_kind_changes_kind,
    "wall_line.segments": wall_line_segments,
    "wall_line.inward_normal": wall_line_inward_normal,
    "wall_line.wall_gap": wall_line_wall_gap,
    "wall_line.edges": wall_line_edges,
    "wall_line.depth_from": wall_line_depth_from,
    "wall_line.back_to_wall": wall_line_back_to_wall,
    "camera_plan.stands_in_room": camera_plan_stands_in_room,
    "camera_plan.blocks": camera_plan_blocks,
    "camera_plan.face_targets": camera_plan_face_targets,
    "camera_plan.blockers": camera_plan_blockers,
    "camera_plan.in_body": camera_plan_in_body,
    "camera_plan.faces_room": camera_plan_faces_room,
    "camera_plan.hidden_for": camera_plan_hidden_for,
    "system_replace.members": system_replace_members,
    "system_replace.pick_style": system_replace_pick_style,
    "system_replace.plain_cabinets": system_replace_plain_cabinets,
    "cabinet_types.storey_of": cabinet_types_storey_of,
    "system_replace.kept_models": system_replace_kept_models,
    "run_line.nearest_edge": run_line_nearest_edge,
    "run_line.drawn_line": run_line_drawn_line,
    "run_line.base_cabinets": run_line_base_cabinets,
    "run_line.plan_on_line": run_line_plan_on_line,
    "run_line.back_wall_line": run_line_back_wall_line,
    "run_line.element_against": run_line_element_against,
    "cabinet_run.fit_depth": cabinet_run_fit_depth,
    "cabinet_run.plan_replace": cabinet_run_plan_replace,
    "structure_mesh.is_structure": structure_mesh_is_structure,
    "structure_mesh.prism": structure_mesh_prism,
    "structure_mesh.meshes": structure_mesh_meshes,
    "layers.material_slot": layers_material_slot,
    "layers.catalogue": layers_catalogue,
    "layers.resolve": layers_resolve,
    "layers.changed_parts": layers_changed_parts,
    "proposal.validation_delta": proposal_validation_delta,
    "numeric.round_int": numeric_round_int,
    "numeric.near": numeric_near,
    "catalog.expr.run": catalog_expr_run,
    "catalog.expr.compile": catalog_expr_compile,
    "palette.module_color": palette_module_color,
    "errors.kind_of": errors_kind_of,
    "runs.trig": runs_trig,
    "runs.wall_seat": runs_wall_seat,
    "runs.free_seat": runs_free_seat,
    "runs.seat_of": runs_seat_of,
    "runs.front_span": runs_front_span,
    "runs.front_box": runs_front_box,
    "runs.frame_of": runs_frame_of,
    "runs.row_of": runs_row_of,
    "runs.spot": runs_spot,
    "runs.corner_joints": runs_corner_joints,
    "runs.front_cross": runs_front_cross,
    "runs.run_wall": runs_run_wall,
    "runs.walls_used": runs_walls_used,
    "runs.along_wall": runs_along_wall,
    "runs.frames": runs_frames,
    "runs.aabb": runs_aabb,
    "runs.penetration": runs_penetration,
    "runs.module_footprint": runs_module_footprint,
    "runs.strip_extent": runs_strip_extent,
    "runs.system_id": runs_system_id,
    "runs.polygon_gap": runs_polygon_gap,
    "runs.run_systems": runs_run_systems,
    "tv_system.texts": tv_system_texts,
    "tv_system.tv_for": tv_system_tv_for,
    "tv_system.run_fields": tv_system_run_fields,
    "tv_system.front_of": tv_system_front_of,
    "tv_system.console": tv_system_console,
    "tv_system.runs": tv_system_runs,
    "appliance_models.lookup": appliance_models_lookup,
    "appliance_models.of_appliance": appliance_models_of_appliance,
    "appliance_models.changes_cabinets": appliance_models_changes_cabinets,
    "appliance_models.energy_notes": appliance_models_energy_notes,
    "appliance_models.over": appliance_models_over,
    "appliance_models.check": appliance_models_check,
    "regions.priority_score": regions_priority_score,
    "handles.material_ops": handles_material_ops,
    "lexicon.fold": lexicon_fold,
    "lexicon.notes": lexicon_notes,
    "floorplan.derive_region": floorplan_derive_region,
    "floorplan.parse_region": floorplan_parse_region,
    "floorplan.kitchen_transform": floorplan_kitchen_transform,
    "floorplan.room_edges": floorplan_room_edges,
    "floorplan.detect_element_backs": floorplan_detect_element_backs,
    "floorplan.resolve_binding": floorplan_resolve_binding,
    "floorplan.room_section": floorplan_room_section,
    "floorplan.finish_document": floorplan_finish_document,
    "floorplan.default_height": floorplan_default_height,
    "floorplan.document_hash": floorplan_document_hash,
    "floorplan.document.frame_vectors": floorplan_document_frame_vectors,
    "floorplan.document.read_points": floorplan_document_read_points,
    "floorplan.document.element_bbox": floorplan_document_element_bbox,
    "floorplan.document.is_kitchen_unit": floorplan_document_is_kitchen_unit,
    "floorplan.geom.vsub": _geom("vsub"),
    "floorplan.geom.vdot": _geom("vdot"),
    "floorplan.geom.vcross": _geom("vcross"),
    "floorplan.geom.vnorm": _geom("vnorm"),
    "floorplan.geom.area2": _geom("area2"),
    "floorplan.geom.seg_dist": _geom("seg_dist"),
    "floorplan.geom.boundary_dist": _geom("boundary_dist"),
    "floorplan.geom.point_in_poly": _geom("point_in_poly"),
    "floorplan.geom.proper_cross": _geom("proper_cross"),
    "floorplan.geom.polys_cross": _geom("polys_cross"),
    "floorplan.geom.poly_dist": _geom("poly_dist"),
    "floorplan.geom.self_intersects": _geom("self_intersects"),
    "floorplan.geom.angle_between": _geom("angle_between"),
    "floorplan.geom.long_dir": _geom("long_dir"),
    "run_line.plan_runs": run_line_plan_runs,
    "cabinet_run.plan_corner": cabinet_run_plan_corner,
    "geometry.compile_spec": geometry_compile_spec,
    "threejs_export.export": threejs_export_export,
    "edit_intent.interpret_edit": edit_intent_interpret_edit,
    "cabinet_run.split_widths": cabinet_run_split_widths,
    "cabinet_run.plan_i_run": cabinet_run_plan_i_run,
    "rows_to_runs.convert": rows_to_runs_convert,
    "proposal.spec_diff": proposal_spec_diff,
    "placement.to_room": placement_to_room,
    "placement.to_kitchen": placement_to_kitchen,
    "numeric.round_half_away": numeric_round_half_away,
    "proposal.op_hash": proposal_op_hash,
    "edit.apply_op": edit_apply_op,
    "floorplan.trim_room": floorplan_trim_room,
    "structure_mesh.swing_sheet": structure_mesh_swing_sheet,
    "rules.validate": rules_validate,
    "moldings.compute_runs": moldings_compute_runs,
    "layers.design_op": layers_design_op,
    "floorplan.apply_binding": floorplan_apply_binding,
    "recognition.gemini_wire.sniff_media_type": gemini_wire_sniff_media_type,
    "recognition.gemini_wire.request_body": gemini_wire_request_body,
    "recognition.gemini_wire.answer_text": gemini_wire_answer_text,
    "recognition.gemini_wire.parse_draft": gemini_wire_parse_draft,
    "recognition.choose_recognizer": recognition_choose_recognizer,
    "recognition.recognizer_wire.clean_note": recognizer_wire_clean_note,
    "recognition.recognizer_wire.request_body": recognizer_wire_request_body,
    "recognition.recognizer_wire.response_error": recognizer_wire_response_error,
    "recognition.recognizer_wire.draft_from_runs": recognizer_wire_draft_from_runs,
    "run_line.run_frame": run_line_run_frame,
    "run_template.run_from_template": run_template_run_from_template,
    "run_line.edge_line": run_line_edge_line,
    "recognition.runs_from_draft": recognition_runs_from_draft,
    "recognition.build_layout": recognition_build_layout,
    "run_line.run_lines": run_line_run_lines,
    "runs.systems": runs_systems,
    "recognition.recognizer_wire.clean_job_id": recognizer_wire_clean_job_id,
    "recognition.recognizer_wire.job_progress": recognizer_wire_job_progress,
    "tv_system.layout": tv_system_layout,
    "vocab.to_english": vocab_to_english,
    "appliance_kind.plan": appliance_kind_plan,
    "appliance_models.fit": appliance_models_fit,
    "appliance_models.candidates": appliance_models_candidates,
    "system_replace.relayout_ops": system_replace_relayout_ops,
    "wall_line.replace_lines": wall_line_replace_lines,
    "camera_plan.plan_views": camera_plan_plan_views,
    "regions.normalize": regions_normalize,
    "regions.from_description": regions_from_description,
    "regions.sort_rows": regions_sort_rows,
    "hardware.hinges": hardware_hinges,
    "hardware.handle": hardware_handle,
    "handles.clear_overrides": handles_clear_overrides,
    "handles.material_slot": handles_material_slot,
    "lexicon.interpret": lexicon_interpret,
    "lexicon.tag_phrases": lexicon_tag_phrases,
    "floorplan.normalize": floorplan_normalize,
    "floorplan.list_rooms": floorplan_list_rooms,
    "floorplan.bind_kitchen": floorplan_bind_kitchen,
    "floorplan.structures": floorplan_structures,
    "floorplan.detect_back": floorplan_detect_back,
}
