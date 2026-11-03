"""Island, peninsula and open shelving: placement, geometry, the 3D file and the rules check."""
import json
import sys
import unittest
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kitchen import geometry, intent, rules, threejs_export  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def build(prompt):
    return intent.from_template(intent.parse_prompt(prompt)[0])


def island(spec):
    return [m for m in spec.module if m.wall == "island"]


class TestIsland(unittest.TestCase):
    def test_island_sits_an_aisle_in_front_of_the_back_run(self):
        s = build("Bếp thẳng 4m có đảo bếp")
        ms = island(s)
        self.assertTrue(ms)
        self.assertEqual({m.offset for m in ms}, {s.common.baseDepth + 1100})
        self.assertEqual(min(m.fromCorner for m in ms), 300, "centred on the 4 m back run")
        self.assertEqual(max(m.endAt for m in ms), 2700)

    def test_doors_face_the_back_wall_and_countertop_covers_the_run(self):
        s = build("Bếp thẳng 4m có đảo bếp")
        sc = geometry.compile_spec(s)
        z0 = island(s)[0].offset
        fronts = [p for p in sc.parts if p.wall == "island" and p.type == "drawer"]
        self.assertTrue(fronts and all(p.max[2] <= z0 + s.common.doorThickness + 1 for p in fronts))
        top = [p for p in sc.parts if p.type == "countertop" and p.wall == "island"]
        self.assertEqual(len(top), 1)
        self.assertLessEqual(top[0].min[2], z0)
        self.assertGreater(sc.lphai, z0 + s.common.baseDepth)

    def test_island_in_l_and_u_keeps_the_aisle_to_the_side_runs(self):
        for prompt, lo in (("Bếp chữ L dài 4m x 3m, đảo bếp", 580 + 1100), ("Bếp chữ U dài 4.5m x 3m, đảo bếp", 580 + 1100)):
            s = build(prompt)
            self.assertGreaterEqual(min(m.fromCorner for m in island(s)), lo, prompt)
            self.assertEqual(rules.validate(s)["dem"]["error"], 0, prompt)
            self.assertEqual(rules.check_geometry(s), [], prompt)

    def test_too_small_room_reports_instead_of_overlapping(self):
        s = build("Bếp chữ U dài 2m, đảo bếp")
        self.assertEqual(island(s), [])
        note = next(i for i in s.promptInterpretation if i["canonical"] == "island")
        self.assertEqual(note["status"], "ambiguous")

    def test_one_interpretation_row_per_feature(self):
        s = build("Bếp chữ L dài 4m x 3m, đảo bếp, kệ mở")
        for k in ("island", "openShelf"):
            self.assertEqual([i["canonical"] for i in s.promptInterpretation].count(k), 1, k)

    def test_threejs_file_places_the_island_freely_and_validates(self):
        s = build("Bếp thẳng 4m có đảo bếp")
        doc = threejs_export.export(s, "d", 1)
        self.assertEqual(threejs_export.integrity(doc), [])
        jsonschema.Draft202012Validator(json.loads((ROOT / "schemas" / "kitchen-threejs.schema.json").read_text(encoding="utf-8"))).validate(doc)
        m = next(x for x in doc["modules"] if x["sourceRef"] == island(s)[0].id)
        self.assertEqual(m["transform"]["rotation"]["y"], 180.0)
        self.assertNotIn("wallId", m["placement"])
        d = m["drawers"][0]
        self.assertAlmostEqual(d["transform"]["position"]["z"], m["dimensions"]["depth"] - 18, delta=1)


class TestPeninsula(unittest.TestCase):
    def test_attached_to_the_end_of_the_right_run_with_a_blind_start(self):
        s = build("Bếp chữ L dài 3.6m x 2.4m, bán đảo")
        ms = island(s)
        self.assertEqual({m.offset for m in ms}, {2400})
        self.assertEqual(ms[0].fromCorner, 0)
        self.assertEqual(ms[0].blindCorner, s.common.baseDepth, "no door where the neighbouring run touches")
        self.assertEqual(rules.check_geometry(s), [])

    def test_straight_kitchen_is_promoted_to_l_and_says_so(self):
        s = build("Bếp thẳng 3m, bán đảo")
        self.assertTrue(any(m.wall == "right" for m in s.module))
        self.assertTrue(any("chữ L" in i["message"] for i in s.promptInterpretation))
        self.assertTrue(island(s))


class TestOpenShelf(unittest.TestCase):
    def test_wall_cabinet_over_the_sink_becomes_open_shelving(self):
        s = build("Bếp chữ L dài 4m x 3m, kệ mở")
        open_ = [m for m in s.module if m.type == "upper-open"]
        self.assertEqual(len(open_), 1)
        sink = next(a for a in s.appliances if a.type == "sink")
        self.assertTrue(open_[0].wall == sink.wall and open_[0].fromCorner <= sink.center < open_[0].endAt)
        self.assertEqual(open_[0].doors, [])

    def test_geometry_has_shelves_and_no_doors_and_the_file_lists_shelves(self):
        s = build("Bếp thẳng 4m, kệ mở")
        m = next(x for x in s.module if x.type == "upper-open")
        parts = [p for p in geometry.compile_spec(s).parts if p.module == m.id]
        self.assertEqual(sum(p.type == "shelf" for p in parts), m.shelfCount + 1)
        self.assertFalse([p for p in parts if p.type in ("door", "glass-door", "handle")])
        doc = threejs_export.export(s, "d", 1)
        self.assertEqual(threejs_export.integrity(doc), [])
        entry = next(x for x in doc["modules"] if x["sourceRef"] == m.id)
        self.assertEqual((len(entry["doors"]), len(entry["shelves"])), (0, m.shelfCount + 1))
        self.assertEqual(rules.validate(s)["dem"]["error"], 0)


if __name__ == "__main__":
    unittest.main()
