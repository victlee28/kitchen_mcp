"""Wall surfaces (plan claude/ke-hoach-chon-mat-tuong): every flat face of every wall, its stable id, the room it looks into, its holes."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import wall_surfaces as W  # noqa: E402

KITCHEN = ("kitchen", [(0.0, 0.0), (4000.0, 0.0), (4000.0, 3000.0), (0.0, 3000.0)])
HALL = ("hall", [(0.0, -3000.0), (4000.0, -3000.0), (4000.0, -100.0), (0.0, -100.0)])


def faces(surfaces):
    return {s.face: s for s in surfaces}


class TestOneWall(unittest.TestCase):
    def test_a_box_wall_between_two_rooms(self):
        got = faces(W.of_wall("w1", [(0, -100), (4000, -100), (4000, 0), (0, 0)], 0, 2700, [KITCHEN, HALL], "kitchen"))
        self.assertEqual(sorted(got), ["bottom", "end", "inside", "outside", "start", "top"])
        self.assertEqual((got["inside"].room, got["inside"].normal), ("kitchen", (0.0, 0.0, 1.0)))
        self.assertEqual((got["outside"].room, got["outside"].normal), ("hall", (0.0, 0.0, -1.0)))
        self.assertEqual((got["start"].normal[0], got["end"].normal[0]), (-1.0, 1.0), "start lies first along +x")
        self.assertEqual((got["inside"].width, got["inside"].height), (4000.0, 2700.0))
        self.assertIsNone(got["top"].room)
        self.assertEqual(got["inside"].id, "w1#inside")

    def test_the_names_do_not_depend_on_how_the_outline_was_drawn(self):
        a = W.of_wall("w1", [(0, -100), (4000, -100), (4000, 0), (0, 0)], 0, 2700, [KITCHEN], "kitchen")
        b = W.of_wall("w1", [(4000, 0), (4000, -100), (0, -100), (0, 0)], 0, 2700, [KITCHEN], "kitchen")
        self.assertEqual({s.id: s.normal for s in a}, {s.id: s.normal for s in b})

    def test_a_wall_facing_no_known_room(self):
        got = faces(W.of_wall("w2", [(0, 5000), (0, 9000), (200, 9000), (200, 5000)], 0, 2700, [KITCHEN], "kitchen"))
        self.assertEqual(sorted(got), ["bottom", "end", "side-a", "side-b", "start", "top"])
        self.assertEqual(got["side-a"].normal, (1.0, 0.0, 0.0), "side-a: the long side looking along +x")
        self.assertTrue(all(s.room is None for s in got.values()))

    def test_any_other_outline_names_its_edges(self):
        l_shape = [(0, 0), (2000, 0), (2000, 100), (100, 100), (100, 2000), (0, 2000)]
        got = W.of_wall("w3", l_shape, 0, 2700)
        self.assertEqual(sorted(s.face for s in got), ["bottom", "e0", "e1", "e2", "e3", "e4", "e5", "top"])
        self.assertEqual(len({s.id for s in got}), 8)

    def test_a_long_wall_belongs_to_the_room_it_mostly_faces(self):
        long = faces(W.of_wall("w4", [(0, -100), (10000, -100), (10000, 0), (0, 0)], 0, 2700, [KITCHEN, HALL], "kitchen"))
        self.assertEqual(long["inside"].room, "kitchen", "4 of its 10 m face the kitchen and none another room")

    def test_holes_cut_the_sides_they_pass_through(self):
        hole = W.Hole((0.0, -50.0), (1.0, 0.0), 1000.0, 1900.0, 0.0, 2100.0, 110.0)
        got = faces(W.of_wall("w1", [(0, -100), (4000, -100), (4000, 0), (0, 0)], 0, 2700, [KITCHEN, HALL], "kitchen", [hole]))
        self.assertEqual(got["inside"].holes, ((1000.0, 1900.0, 0.0, 2100.0),), "u runs to the right seen from the kitchen: +x")
        self.assertEqual(got["outside"].holes, ((2100.0, 3000.0, 0.0, 2100.0),), "and the other way seen from the hall")
        self.assertEqual((got["inside"].origin, got["inside"].u), ((0.0, 0.0, 0.0), (1.0, 0.0)))
        self.assertEqual(got["start"].holes, ())
        far = W.Hole((0.0, 5000.0), (1.0, 0.0), 1000.0, 1900.0, 0.0, 2100.0, 110.0)
        self.assertEqual(faces(W.of_wall("w1", [(0, -100), (4000, -100), (4000, 0), (0, 0)], 0, 2700, [], None, [far]))["side-a"].holes, ())

    def test_a_default_wall_outline(self):
        self.assertEqual(W.box_outline((0, 0), (-3000, 0), (0, 1), 100), [(0, 0), (-3000, 0), (-3000, -100), (0, -100)])


class TestDesigns(unittest.TestCase):
    def test_a_design_without_floorplan_has_its_default_walls_faces(self):
        from kitchen.service import KitchenService
        with tempfile.TemporaryDirectory() as d:
            svc = KitchenService(Path(d) / "k.db", Path(d) / "r")
            fix = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
            did = svc.create_from_spec(fix)["id"]
            surf = {s["id"]: s for s in svc.threejs(did)["room"]["surfaces"]}
        self.assertEqual(surf["WALL-BACK#inside"]["room"], "kitchen")
        self.assertEqual(surf["WALL-RIGHT#inside"]["room"], "kitchen")
        self.assertIsNone(surf["WALL-BACK#outside"]["room"])

    def test_a_floorplan_design_names_its_rooms_and_the_doors_it_places(self):
        from kitchen.service import KitchenService
        from test_recognition_openings import building_design
        with tempfile.TemporaryDirectory() as d:
            svc = KitchenService(Path(d) / "k.db", Path(d) / "r")
            did = building_design(svc)
            svc.apply(did, {"op": "add-opening", "opening": {"kind": "door", "wallAxis": "WA-WALL-FP-1", "center": 2995, "width": 800,
                                                             "height": 2100}}, 1)
            doc = svc.threejs(did)
        surf = doc["room"]["surfaces"]
        kitchen = doc["metadata"]["floorplan"]["roomId"]
        mine = [s for s in surf if s["room"] == kitchen]
        self.assertTrue(mine)
        self.assertTrue(all(s["face"] not in ("top", "bottom", "start", "end") for s in mine))
        holed = [s for s in surf if s.get("holes")]
        self.assertTrue(holed, "the new door cuts the wall it stands in")
        self.assertTrue(all(s["structure"].startswith("STRUCT-") for s in surf))
        self.assertEqual(len({s["id"] for s in surf}), len(surf), "ids are unique")


if __name__ == "__main__":
    unittest.main()


class TestSurfaceFinish(unittest.TestCase):
    """The first use of picked faces (user, 13/11): a finish of their own, given by a sentence in the menu's command box."""

    def setUp(self):
        from kitchen.service import KitchenService
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = KitchenService(Path(self.tmp.name) / "k.db", Path(self.tmp.name) / "r")
        fix = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
        self.did = self.svc.create_from_spec(fix)["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def say(self, text, faces):
        return self.svc.interpret(self.did, text, surfaces=faces)

    def test_a_sentence_gives_the_picked_faces_a_finish(self):
        faces = ["WALL-BACK#inside", "WALL-RIGHT#inside"]
        r = self.say("ốp gạch thẻ xanh", faces)
        self.assertEqual(r["operation"], {"op": "surface-material", "surfaces": faces, "material": "Gạch thẻ xanh"})
        self.assertTrue(r["proposal"]["applicable"])
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        doc = self.svc.threejs(self.did)
        lit = {s["id"]: s.get("materialId") for s in doc["room"]["surfaces"]}
        self.assertEqual(lit["WALL-BACK#inside"], lit["WALL-RIGHT#inside"])
        self.assertIsNotNone(lit["WALL-BACK#inside"])
        self.assertIsNone(lit["WALL-BACK#outside"], "the other faces keep the wall's finish")
        mat = next(m for m in doc["materials"] if m["id"] == lit["WALL-BACK#inside"])
        self.assertEqual(mat["name"], "Gạch thẻ xanh")
        back = self.say("bỏ vật liệu", ["WALL-BACK#inside"])
        self.svc.apply(self.did, back["operation"], back["baseRev"], "test", back["proposal"]["opHash"])
        self.assertEqual(self.svc.store.get(self.did)[0].surfaceMaterials, {"WALL-RIGHT#inside": "Gạch thẻ xanh"})

    def test_words_the_rules_do_not_read_ask_back(self):
        self.assertEqual(self.say("làm gì đó", ["WALL-BACK#inside"])["status"], "clarify")
        self.assertEqual(self.say("paint it white", ["WALL-BACK#inside"])["operation"]["material"], "White")

    def test_bad_face_ids_are_refused(self):
        from kitchen import edit
        from kitchen.errors import InvalidInput
        spec = self.svc.store.get(self.did)[0]
        for bad in ([], ["no-hash"], ["a b#c"]):
            with self.subTest(bad=bad), self.assertRaises(InvalidInput):
                edit.apply_op(spec, {"op": "surface-material", "surfaces": bad, "material": "x"})

    def test_without_finishes_the_design_data_is_unchanged(self):
        self.assertIsNone(self.svc.store.get(self.did)[0].surfaceMaterials)

    def test_a_finish_on_a_face_the_design_lost_is_a_warning(self):
        face = self.svc.threejs(self.did)["room"]["surfaces"][0]["id"]
        rev = self.svc.store.get(self.did)[1]
        self.svc.apply(self.did, {"op": "surface-material", "surfaces": [face, "WALL-GONE#inside"], "material": "Trắng"}, rev)
        lost = [i for i in self.svc.validate(self.did)["issues"] if i["rule"] == "SURFACE"]
        self.assertEqual([(i["severity"], i["params"]["ids"]) for i in lost], [("warning", "WALL-GONE#inside")])

    def test_the_control_images_paint_finished_faces(self):
        from kitchen import render
        rev = self.svc.store.get(self.did)[1]
        self.svc.apply(self.did, {"op": "surface-material", "surfaces": ["WALL-BACK#inside"], "material": "Sơn đỏ"}, rev)
        spec = self.svc.store.get(self.did)[0]
        faces = render.face_colors(spec, self.svc.catalog())
        self.assertEqual([(f.wall, f.normal) for f in faces], [("back", (0.0, 0.0, 1.0))])
        import numpy as np
        from PIL import Image
        out = render.render_views(spec, Path(self.tmp.name) / "views", ["back-wall"], 320, 240, catalog=self.svc.catalog())
        alb = np.asarray(Image.open(Path(out["views"]["back-wall"]["dir"]) / "albedo.png"), float).reshape(-1, 3)
        red = (alb[:, 0] > 1.8 * alb[:, 1]) & (alb[:, 0] > 100)
        self.assertGreater(int(red.sum()), 1000)

    def test_cabinets_along_a_picked_face(self):
        r = self.say("tạo dãy tủ dưới", ["WALL-BACK#top", "WALL-RIGHT#inside"])
        self.assertEqual(r["status"], "ok")
        self.assertIn("add-run", json.dumps(r["operation"]))
        self.assertEqual(self.say("tạo dãy tủ dưới", ["WALL-BACK#top"])["status"], "unsupported")
