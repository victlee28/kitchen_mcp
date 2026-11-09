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

from kitchen import edit, floorplan, geometry, layers, moldings, numeric, proposal, rules, run_line, structure_mesh  # noqa: E402
from kitchen.recognition import build_draft, choose_recognizer, gemini_wire, line_modules, recognizer_wire  # noqa: E402
from kitchen.placement import Placement  # noqa: E402
from kitchen.spec import load_spec, to_data  # noqa: E402


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


def recognizer_wire_draft_from_kitchen_spec(i):
    return {"draft": recognizer_wire.draft_from_kitchen_spec(i["payload"])}


def recognizer_wire_clean_job_id(i):
    return {"job": recognizer_wire.clean_job_id(i["value"])}


def recognizer_wire_job_progress(i):
    return {"progress": recognizer_wire.job_progress(i["payload"])}


def run_line_run_frame(i):
    return {"frame": run_line.run_frame(run_line.Line(tuple(i["a"]), tuple(i["b"]), tuple(i["normal"])))}


def run_line_edge_line(i):
    line = run_line.edge_line([tuple(p) for p in i["outline"]], tuple(i["point"]))
    return {"a": list(line.a), "b": list(line.b), "normal": [round(line.normal[0], 6), round(line.normal[1], 6)]}


def recognition_line_modules(i):
    modules, dropped = line_modules(build_draft(i["raw"]), i["common"], i.get("wall", "back"))
    return {"modules": modules, "dropped": dropped}


FUNCTIONS = {
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
    "recognition.recognizer_wire.draft_from_kitchen_spec": recognizer_wire_draft_from_kitchen_spec,
    "run_line.run_frame": run_line_run_frame,
    "run_line.edge_line": run_line_edge_line,
    "recognition.line_modules": recognition_line_modules,
    "recognition.recognizer_wire.clean_job_id": recognizer_wire_clean_job_id,
    "recognition.recognizer_wire.job_progress": recognizer_wire_job_progress,
}
