"""Furniture units other than kitchens and TV walls (kitchen.unit_system, catalog kind unit-layout): a wine cabinet, low cabinets only."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import edit, rules, unit_system  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

PLAN = json.loads((ROOT / "tests" / "data" / "floorplan-sliding-hole.json").read_text(encoding="utf-8"))


class TestWords(unittest.TestCase):
    def test_what_a_sentence_asks_for(self):
        self.assertEqual(unit_system.asks("tạo hệ tủ rượu ở đây"), "wine")
        self.assertEqual(unit_system.asks("thay bằng hệ tủ thấp"), "low")
        self.assertEqual(unit_system.asks("make a wine cabinet here"), "wine")
        self.assertEqual(unit_system.asks("chỉ tủ dưới thôi"), "low")
        self.assertEqual(unit_system.asks("tủ rượu thấp"), "wine", "the longest word wins")
        for kitchen in ("tạo tủ bếp chữ I có tủ lạnh", "tạo hệ tủ tivi", "", None):
            self.assertIsNone(unit_system.asks(kitchen))


class TestLayouts(unittest.TestCase):
    def test_a_wine_cabinet(self):
        mods = unit_system.layout("wine", 2930, {"cabinetTop": 2280})
        types = [m["type"] for m in mods]
        self.assertEqual((types.count("tall"), types.count("base"), types.count("upper-glass")), (2, 3, 3))
        self.assertIn("upper-open", types, "a niche for the bottles")
        self.assertAlmostEqual(sum(m["width"] for m in mods if m["type"] in ("tall", "base")), 2930)
        self.assertTrue(all(m["y"] + m["height"] <= 2280 for m in mods))
        glass = next(m for m in mods if m["type"] == "upper-glass")
        self.assertEqual(sum(glass["doors"]), glass["width"])

    def test_a_short_wine_cabinet_has_no_columns(self):
        self.assertNotIn("tall", [m["type"] for m in unit_system.layout("wine", 1200, {"cabinetTop": 2280})])

    def test_low_cabinets_only(self):
        mods = unit_system.layout("low", 2930, {})
        self.assertEqual({m["type"] for m in mods}, {"base"})
        self.assertAlmostEqual(sum(m["width"] for m in mods), 2930)


class TestInDesigns(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="units-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.did = self.svc.create_from_spec(PLAN)["id"]
        spec, _ = self.svc.store.get(self.did)
        self.furniture = next(e["id"] for e in spec.floorplan["elements"] if e.get("kind") == "furniture")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_piece_of_furniture_replaced_by_a_wine_cabinet_has_no_kitchen_rule(self):
        r = self.svc.template(self.did, {"kind": "run-i", "structureId": f"STRUCT-{self.furniture}", "point": {"x": 0, "z": 0},
                                         "prompt": "tạo hệ tủ rượu ở đây"})
        run = r["operation"]["ops"][0]["run"]
        self.assertEqual((run["purpose"], run["unitLayout"]), ("unit", "wine"))
        self.assertFalse([i for i in r["proposal"]["validation"]["introduced"] if i["severity"] != "info"])
        self.assertFalse(any(m["module"]["type"] in ("base-sink", "base-cooktop", "tall-fridge")
                             for m in r["operation"]["ops"] if m["op"] == "add"), "not a kitchen")
        self.svc.apply(self.did, r["operation"], r["baseRev"], "t", r["proposal"]["opHash"])
        spec, _ = self.svc.store.get(self.did)
        self.assertFalse([i for i in rules.validate(spec)["issues"] if i["rule"] in ("KITCHEN-DEFAULT-001", "GEO-HEIGHTS")])
        back = edit.apply_op(spec, {"op": "set-run-unit", "id": run["id"], "unit": None})
        self.assertIsNone(next(x for x in back.runs if x.id == run["id"]).purpose)

    def test_low_cabinets_and_a_system_laid_again(self):
        r = self.svc.template(self.did, {"kind": "run-i", "structureId": f"STRUCT-{self.furniture}", "point": {"x": 0, "z": 0},
                                         "prompt": "thay bằng hệ tủ thấp"})
        self.assertEqual({o["module"]["type"] for o in r["operation"]["ops"] if o["op"] == "add"}, {"base"})
        self.svc.apply(self.did, r["operation"], r["baseRev"], "t", r["proposal"]["opHash"])
        again = self.svc.template(self.did, {"kind": "replace-system", "system": self.furniture, "prompt": "thay bằng hệ tủ rượu"})
        self.assertIn({"op": "set-run-unit", "id": r["operation"]["ops"][0]["run"]["id"], "unit": "wine"}, again["operation"]["ops"])


if __name__ == "__main__":
    unittest.main()
