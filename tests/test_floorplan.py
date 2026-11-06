"""Floorplan import: room choice, axes, wall classification, walls and openings, back detection, binding and export."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kitchen import floorplan as fpm, intent, threejs_export  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BUILDING = json.loads((ROOT / "tests" / "data" / "floorplan-building.json").read_text(encoding="utf-8-sig"))
SAMPLE = json.loads((ROOT / "tests" / "data" / "floorplan-sample.json").read_text(encoding="utf-8-sig"))


def fld(value, status="confirmed"):
    return {"value": value, "source": "human", "confidence": 1, "status": status}


def elem(eid, kind, tag, outline, label=None, **geo):
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    return {"id": eid, "kind": kind, "fields": {"geometry": fld({"outline": outline, "bbox": [min(xs), min(ys), max(xs), max(ys)], **geo}),
                                                 "tag": fld(tag), "label": fld(label)}}


def rect(f0, r0, f1, r1):
    return [[f0, r0], [f1, r0], [f1, r1], [f0, r1]]


def plan(*elements, unit="mm"):
    return {"contractVersion": "2.1", "kind": "floorplan-audited", "planId": "t", "unit": unit,
            "frame": {"unit": unit, "x": "toi", "y": "phai", "z": "len", "handed": "trai"}, "elements": list(elements)}


# forward 0..4000, right 0..5000. The scene back wall (z = 0) is the file's forward = 4000 side.
ROOM = elem("room_a", "area", "room", rect(0, 0, 4000, 5000), "Bep")


class TestSample(unittest.TestCase):
    def test_import_keeps_the_room_and_warns_about_what_lies_outside(self):
        fp = fpm.normalize(SAMPLE)
        self.assertEqual(fp["roomId"], "room_003")
        self.assertEqual((fp["width"], round(fp["depth"], 1)), (6030.0, 4720.9))
        out = {w["element"] for w in fp["warnings"] if w["code"] == "outside-room"}
        self.assertEqual(out, {"opening_002", "furniture_001", "shaft_001"})
        members = {e["id"]: e["membership"] for e in fp["elements"]}
        self.assertIn(members["column_001"], ("adjacent", "overlapping", "inside"), "the column is not rejected")
        self.assertEqual(members["wall_006"], "adjacent")
        self.assertEqual(len(fp["walls"]), 12)

    def test_measured_wall_sets_thickness_and_the_rest_is_flagged_assumed(self):
        fp = fpm.normalize(SAMPLE)
        measured = [w for w in fp["walls"] if w["thicknessSource"] == "measured"]
        self.assertEqual([(w["sourceElement"], w["thickness"]) for w in measured], [("wall_006", 140.0)])
        self.assertTrue(any(w["code"] == "assumed-wall-thickness" for w in fp["warnings"]))

    def test_source_unit_and_contract(self):
        bad = copy.deepcopy(SAMPLE)
        bad["frame"]["unit"] = "mm"
        with self.assertRaises(ValueError):
            fpm.normalize(bad)
        odd = copy.deepcopy(SAMPLE)
        odd["contractVersion"] = "9.0"
        self.assertTrue(any(w["code"] == "contract-version" for w in fpm.normalize(odd)["warnings"]))

    def test_hash_is_stable_and_detects_changes(self):
        self.assertEqual(fpm.document_hash(SAMPLE), fpm.document_hash(copy.deepcopy(SAMPLE)))
        other = copy.deepcopy(SAMPLE)
        other["planId"] = "x"
        self.assertNotEqual(fpm.document_hash(SAMPLE), fpm.document_hash(other))


BUILDING = json.loads((ROOT / "tests" / "data" / "floorplan-building.json").read_text(encoding="utf-8-sig"))


class TestStructures(unittest.TestCase):
    """The whole building is drawn, not only the chosen room (the kitchen has no room element in this plan)."""

    def setUp(self):
        self.fp = fpm.normalize(BUILDING)
        self.st = {x["sourceElement"]: x for x in fpm.structures(self.fp)}

    def test_every_element_is_drawn_except_the_room_and_all_walls_are_real_ones(self):
        want = {e["id"] for e in BUILDING["elements"]} - {"room_003"}
        self.assertEqual({e["id"] for e in BUILDING["elements"] if e["kind"] == "wall"} - set(self.st), set())
        self.assertEqual(set(self.st), want)
        self.assertTrue({"furniture_003", "furniture_017", "stair_001", "shaft_001", "column_001", "opening_002"} <= set(self.st))

    def test_heights_are_measured_or_flagged_assumed(self):
        self.assertEqual((self.st["opening_002"]["height"], self.st["opening_002"]["heightSource"]), (2200.0, "measured"))
        self.assertEqual((self.st["furniture_003"]["height"], self.st["furniture_003"]["heightSource"]), (900.0, "assumed"))

    def test_door_swing_and_stair_steps_are_kept(self):
        self.assertTrue(self.st["opening_002"]["swing"] and self.st["opening_002"]["hinge"])
        self.assertEqual(self.st["stair_001"]["steps"], 10)

    def test_export_validates_and_carries_the_structures(self):
        spec = intent.from_template(intent.parse_prompt("Bếp thẳng 3m")[0])
        spec.module, spec.appliances = [], []
        spec.floorplan = self.fp
        doc = threejs_export.export(spec, "d", 1)
        jsonschema.Draft202012Validator(json.loads((ROOT / "schemas" / "kitchen-threejs.schema.json").read_text(encoding="utf-8"))).validate(doc)
        self.assertEqual(len(doc["room"]["structures"]), len(self.st))
        self.assertTrue(all(w["visible"] is False for w in doc["room"]["walls"]), "no synthetic perimeter walls are drawn")


class TestAxes(unittest.TestCase):
    def test_forward_is_flipped_and_right_is_kept(self):
        fp = fpm.normalize(plan(ROOM))
        pts = {(p["x"], p["z"]) for p in fp["outline"]}
        # file (forward, right): (0,0) -> scene (right, 4000 - forward) = (0, 4000); (4000, 5000) -> (5000, 0)
        self.assertEqual(pts, {(0.0, 4000.0), (5000.0, 4000.0), (5000.0, 0.0), (0.0, 0.0)})
        self.assertEqual((fp["width"], fp["depth"]), (5000.0, 4000.0))

    def test_axis_names_and_handedness_are_checked(self):
        d = plan(ROOM)
        d["frame"]["handed"] = "phai"
        with self.assertRaises(ValueError):
            fpm.normalize(d)

    def test_centimetres_are_converted(self):
        d = plan(elem("room_a", "area", "room", rect(0, 0, 400, 500), "Bep"), unit="cm")
        self.assertEqual(fpm.normalize(d)["width"], 5000.0)


class TestRooms(unittest.TestCase):
    def test_several_rooms_need_a_choice(self):
        d = plan(ROOM, elem("room_b", "area", "room", rect(5000, 0, 8000, 3000), "Khac"))
        self.assertEqual([r["id"] for r in fpm.list_rooms(d)], ["room_a", "room_b"])
        with self.assertRaises(ValueError):
            fpm.normalize(d)
        self.assertEqual(fpm.normalize(d, "room_b")["roomId"], "room_b")

    def test_a_label_that_says_room_does_not_make_a_room(self):
        d = plan(elem("x", "area", "balcony", rect(0, 0, 100, 100), "phòng khách"))
        with self.assertRaises(ValueError):
            fpm.normalize(d)

    def test_self_intersecting_outline_is_rejected(self):
        d = plan(elem("room_a", "area", "room", [[0, 0], [4000, 5000], [4000, 0], [0, 5000]], "Bep"))
        with self.assertRaises(ValueError):
            fpm.normalize(d)


class TestOpenings(unittest.TestCase):
    def test_door_in_the_wall_attaches_to_the_right_edge_with_its_offset(self):
        door = elem("d1", "opening", "door", rect(4000, 1000, 4100, 1900), "Cua", width=900)
        fp = fpm.normalize(plan(ROOM, door))
        att = next(e for e in fp["elements"] if e["id"] == "d1")["attached"]
        wall = fp["walls"][att["edge"]]
        self.assertEqual(wall["interiorNormal"]["z"], 1.0, "the scene back wall (z = 0)")
        self.assertEqual(round(att["width"]), 900)
        self.assertEqual(wall["openings"][0]["sourceElement"], "d1")

    def test_door_floating_in_the_room_is_reported_not_guessed(self):
        door = elem("d2", "opening", "door", rect(1500, 1000, 1600, 1900), "Cua", width=900)
        fp = fpm.normalize(plan(ROOM, door))
        self.assertIsNone(next(e for e in fp["elements"] if e["id"] == "d2")["attached"])
        self.assertTrue(any(w["code"] == "opening-unattached" for w in fp["warnings"]))


class TestBackDetection(unittest.TestCase):
    def setUp(self):
        self.fp = fpm.normalize(plan(ROOM))

    def test_unit_against_a_wall(self):
        out = [{"x": 1000, "z": 0}, {"x": 3000, "z": 0}, {"x": 3000, "z": 600}, {"x": 1000, "z": 600}]
        b = fpm.detect_back(out, self.fp)
        self.assertEqual((b["status"], b["gap"], b["depth"]), ("wall-backed", 0.0, 600.0))
        self.assertEqual(b["facing"], {"x": 0.0, "z": 1.0})

    def test_unit_with_a_gap_still_found_and_unit_in_a_corner(self):
        out = [{"x": 1000, "z": 40}, {"x": 3000, "z": 40}, {"x": 3000, "z": 640}, {"x": 1000, "z": 640}]
        self.assertEqual(fpm.detect_back(out, self.fp)["gap"], 40.0)
        corner = [{"x": 0, "z": 0}, {"x": 600, "z": 0}, {"x": 600, "z": 2000}, {"x": 0, "z": 2000}]
        self.assertEqual(fpm.detect_back(corner, self.fp)["status"], "wall-backed")
        c2 = [{"x": 0, "z": 0}, {"x": 1500, "z": 0}, {"x": 1500, "z": 1500}, {"x": 0, "z": 1500}]
        self.assertEqual(fpm.detect_back(c2, self.fp)["status"], "corner")

    def test_floating_unit_has_no_back(self):
        out = [{"x": 1000, "z": 1500}, {"x": 3000, "z": 1500}, {"x": 3000, "z": 2100}, {"x": 1000, "z": 2100}]
        self.assertIsNone(fpm.detect_back(out, self.fp))

    def test_cabinet_element_in_the_plan(self):
        cab = elem("c1", "furniture", "cabinet", rect(3400, 1000, 4000, 3000), "Tu")
        fp = fpm.normalize(plan(ROOM, cab))
        res = fpm.detect_element_backs(fp)
        self.assertEqual(res[0]["element"], "c1")
        self.assertEqual(res[0]["back"]["status"], "wall-backed")


class TestBindingAndExport(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "t.db", self.tmp / "renders")
        self.cab = elem("c1", "furniture", "cabinet", rect(3400, 1000, 4000, 3000), "Tu")
        self.fp = fpm.normalize(plan(ROOM, self.cab))
        self.spec = intent.from_template(intent.parse_prompt("Bếp thẳng 3m")[0])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_auto_binding_follows_the_detected_cabinet_back(self):
        b = fpm.bind_kitchen(self.fp, {"back": 3000})
        back_edge = next(w for w in self.fp["walls"] if w["interiorNormal"]["z"] == 1.0)["edge"]
        self.assertEqual((b["back"], b["source"]), (back_edge, "auto"))
        self.assertEqual(b["transform"]["yaw"], 0.0)

    def test_manual_binding_and_a_kitchen_that_does_not_fit(self):
        short = next(w for w in self.fp["walls"] if w["length"] == 4000)["edge"]
        with self.assertRaises(ValueError):
            fpm.bind_kitchen(self.fp, {"back": 4500}, back_edge=short)
        with self.assertRaises(ValueError):
            fpm.bind_kitchen(self.fp, {"back": 9000})
        self.assertEqual(fpm.bind_kitchen(self.fp, {"back": 3000}, back_edge=next(w for w in self.fp["walls"] if w["length"] == 5000)["edge"])["source"], "manual")

    def test_export_moves_the_kitchen_into_the_room_and_validates(self):
        self.spec.floorplan = self.fp
        doc = threejs_export.export(self.spec, "d", 1)
        jsonschema.Draft202012Validator(json.loads((ROOT / "schemas" / "kitchen-threejs.schema.json").read_text(encoding="utf-8"))).validate(doc)
        ids = {w["id"] for w in doc["room"]["walls"]}
        self.assertIn("WALL-BACK", ids)
        self.assertEqual(doc["metadata"]["floorplan"]["roomId"], "room_a")
        inside = [m for m in doc["modules"] if m["placement"].get("wallId") == "WALL-BACK"]
        self.assertTrue(inside)
        for m in doc["modules"]:
            p = m["transform"]["position"]
            self.assertTrue(-1 <= p["x"] <= 5001 and -1 <= p["z"] <= 4001, p)

    def test_every_wall_choice_keeps_the_run_against_that_wall(self):
        for edge, w in enumerate(self.fp["walls"]):
            self.spec.floorplan = {**self.fp, "binding": fpm.bind_kitchen(self.fp, {"back": 3000}, edge)}
            doc = threejs_export.export(self.spec, "d", 1)
            n = w["interiorNormal"]
            for m in (x for x in doc["modules"] if x["placement"].get("wallId") == "WALL-BACK"):
                p = m["transform"]["position"]
                dist = (p["x"] - w["start"]["x"]) * n["x"] + (p["z"] - w["start"]["z"]) * n["z"]
                self.assertAlmostEqual(dist, 0.0, delta=1.0, msg=f"edge {edge}")

    def test_export_refuses_a_kitchen_that_fits_nowhere(self):
        tiny = fpm.normalize(plan(elem("room_a", "area", "room", rect(0, 0, 1500, 1500), "Nho")))
        self.spec.floorplan = tiny
        with self.assertRaises(ValueError):
            threejs_export.export(self.spec, "d", 1)

    def test_service_import_stores_the_source_once_and_binds(self):
        d = plan(ROOM, self.cab)
        a = self.svc.import_floorplan(d, "A")
        b = self.svc.import_floorplan(d, "B")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(self.svc.store.get_floorplan(a["floorplan"]["ref"]), d)
        with self.svc.store._conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM floorplans").fetchone()[0], 1)
        spec, _ = self.svc.store.get(a["id"])
        self.assertNotIn("source", json.dumps(spec.floorplan.get("rooms")), "revisions carry the ref, not the source")
        with self.assertRaises(ValueError):
            self.svc.bind_floorplan(a["id"])  # no cabinets yet
        spec.module = self.spec.module
        spec.appliances = self.spec.appliances
        rev = self.svc.store.add_revision(a["id"], None, spec, {"op": "test"}, "test")
        res = self.svc.bind_floorplan(a["id"], base_revision=rev)
        self.assertEqual(res["rev"], rev + 1)
        self.assertEqual(res["binding"]["source"], "auto")

    def test_wall_elements_inside_the_outline_are_cut_out_of_the_room(self):
        n = fpm.normalize(BUILDING, "room_003")
        self.assertIn("room-trimmed", [w["code"] for w in n["warnings"]])
        raw = next(e for e in BUILDING["elements"] if e["id"] == "room_003")["fields"]["geometry"]["value"]["outline"]
        shoelace = lambda pts: abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2  # noqa: E731
        got = shoelace([(p["x"], p["z"]) for p in n["outline"]])
        want = shoelace([(p[0] * 10, p[1] * 10) for p in raw])
        self.assertLess(got, want * 0.97)
        self.assertGreater(got, want * 0.85)

    def test_trim_room_cuts_notches_and_leaves_everything_else(self):
        room = [(0, 0), (1000, 0), (1000, 800), (0, 800)]
        notch = ("w1", [400, 0, 600, 100])                               # a wall sitting in the room's boundary
        out, cut = fpm.trim_room(room, [notch], 5.0)
        self.assertEqual(cut, ["w1"])
        self.assertEqual(len(out), 8)
        island = ("w2", [400, 300, 600, 400])                            # free standing inside: not a notch
        self.assertEqual(fpm.trim_room(room, [island], 5.0), (room, []))
        outside = ("w3", [1200, 0, 1300, 100])
        self.assertEqual(fpm.trim_room(room, [outside], 5.0), (room, []))
        diagonal = [(0, 0), (1000, 0), (1000, 800), (500, 900), (0, 800)]
        self.assertEqual(fpm.trim_room(diagonal, [notch], 5.0), (diagonal, []))
        huge = ("w4", [0, 0, 1000, 500])                                 # would take most of the room
        self.assertEqual(fpm.trim_room(room, [huge], 5.0), (room, []))
        near = ("w5", [398, 2, 603, 100])                                # sides a few units off the outline still count
        self.assertEqual(fpm.trim_room(room, [near], 5.0)[1], ["w5"])

    def test_region_for_the_kitchen_is_derived_from_walls(self):
        d = BUILDING
        cands = [r for r in fpm.list_rooms(d) if r["kind"] == "region"]
        self.assertIn("region:around=furniture_003", [r["id"] for r in cands])
        n = fpm.normalize(d, "region:around=furniture_003")
        self.assertEqual(n["region"]["bbox"], [16.0, 1394.0, 337.0, 1559.0])
        self.assertEqual((n["width"], n["depth"]), (1650.0, 3210.0))
        self.assertTrue(all(not s["open"] for s in n["region"]["sides"].values()))
        codes = [w["code"] for w in n["warnings"]]
        self.assertIn("region-derived", codes)
        door = next(e for e in n["elements"] if e["id"] == "opening_002")
        self.assertIsNotNone(door.get("attached"))
        back = fpm.detect_element_backs(n)
        self.assertEqual(back[0]["element"], "furniture_003")
        self.assertEqual(back[0]["back"]["status"], "wall-backed")

    def test_region_kitchen_alias_and_box(self):
        d = BUILDING
        with self.assertRaises(ValueError):
            fpm.normalize(d, "region:kitchen")        # two kitchen areas: ambiguous
        n = fpm.normalize(d, "region:bbox=16,1394,337,1559")
        self.assertEqual((n["width"], n["depth"]), (1650.0, 3210.0))
        for bad in ("region:bbox=1,2,3", "region:bbox=5,5,1,1", "region:nope", "region:around=zzz"):
            with self.assertRaises(ValueError):
                fpm.normalize(d, bad)

    def test_region_open_side_is_reported(self):
        d = BUILDING
        d = json.loads(json.dumps(d))
        d["elements"] = [e for e in d["elements"] if e["id"] not in ("wall_h08", "wall_002")]
        n = fpm.normalize(d, "region:around=furniture_003")
        self.assertIn("region-open-side", [w["code"] for w in n["warnings"]])

    def test_region_imports_through_the_service(self):
        r = self.svc.import_floorplan(BUILDING, "Kitchen", "region:around=furniture_003")
        self.assertEqual(r["floorplan"]["roomId"], "region:around=furniture_003")
        spec, _ = self.svc.store.get(r["id"])
        doc = threejs_export.export(spec)
        self.assertTrue(doc["room"]["structures"])

    def test_list_rooms_on_the_service(self):
        self.assertEqual([r["id"] for r in self.svc.list_floorplan_rooms(plan(ROOM))], ["room_a"])


if __name__ == "__main__":
    unittest.main()
