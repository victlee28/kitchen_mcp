"""Auto place (18/11/2026): the web's "Auto place" builds what the imported floorplan draws: doors and windows in its holes, a cabinet
system in place of each cabinet, chosen from the plan's tag and label, else from the size."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import auto_place  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

BUILDING = json.loads((ROOT / "tests" / "data" / "floorplan-building.json").read_text(encoding="utf-8-sig"))


class TestChoices(unittest.TestCase):
    def test_the_label_or_the_tag_names_the_system(self):
        self.assertEqual(auto_place.furniture_choice({"tag": "cabinet", "label": "Vách TV"}, 350).kind, "tv")
        wine = auto_place.furniture_choice({"tag": "cabinet", "label": "TỦ RƯỢU"}, 300)
        self.assertEqual((wine.kind, wine.unit), ("unit", "wine"))
        self.assertEqual(auto_place.furniture_choice({"tag": "cabinet_kitchen_set", "label": None}, 600).kind, "kitchen")
        self.assertEqual(auto_place.furniture_choice({"tag": "Cabinet Kitchen Set", "label": "Tủ bếp 2"}, 600).kind, "kitchen")
        self.assertEqual(auto_place.furniture_choice({"tag": "wine_cabinet", "label": None}, 300).unit, "wine")

    def test_without_words_the_size_decides_and_what_is_no_cabinet_is_left(self):
        self.assertEqual(auto_place.furniture_choice({"tag": "cabinet"}, 600).kind, "plain")
        low = auto_place.furniture_choice({"tag": "cabinet"}, 350)
        self.assertEqual((low.kind, low.unit), ("unit", "low"))
        self.assertEqual(auto_place.furniture_choice({"tag": "cabinet"}, 150).reason, "too-shallow")
        self.assertEqual(auto_place.furniture_choice({"tag": "bed", "label": "Giường"}, 1600).reason, "not-cabinet")
        self.assertEqual(auto_place.furniture_choice({"tag": "sofa"}, 900).kind, "skip")

    def test_the_opening_type_fits_the_hole(self):
        self.assertEqual(auto_place.opening_choice("door", "door-sliding-2", 3920), ("door-sliding-4", None))
        self.assertEqual(auto_place.opening_choice("door", "door-swing-1", 900), ("door-swing-1", None))
        self.assertEqual(auto_place.opening_choice("door", "door-swing-1", 1450), ("door-swing-2", None))
        self.assertEqual(auto_place.opening_choice("window", "window-swing-2", 1180), ("window-swing-2", None))
        self.assertEqual(auto_place.opening_choice("door", "door-swing-1", 7000), ("door-swing-1", "keep"))

    def test_depth_of_a_box_drawn_at_an_angle(self):
        self.assertAlmostEqual(auto_place.depth_of([(0, 0), (3000, 0), (3000, 600), (0, 600)]), 600)
        self.assertAlmostEqual(auto_place.depth_of([(0, 0), (2121.3, 2121.3), (1697.1, 2545.6), (-424.3, 424.3)]), 600, delta=1)


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="auto-place-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.did = self.svc.import_floorplan(BUILDING)["id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_everything_the_plan_draws_is_built_in_one_revision(self):
        out = self.svc.auto_place(self.did)
        self.assertEqual(out["rev"], 2)
        what = {p["element"]: p["what"] for p in out["placed"]}
        self.assertEqual(what.get("furniture_001"), "unit")
        self.assertEqual(what.get("furniture_003"), "kitchen")
        self.assertEqual(what.get("furniture_017"), "kitchen")
        self.assertEqual(what.get("furniture_021"), "tv")
        self.assertEqual(what.get("furniture_019"), "plain")
        spec, _ = self.svc.store.get(self.did)
        purposes = sorted(str(r.purpose) for r in spec.runs)
        self.assertEqual(purposes, ["None", "None", "None", "tv", "unit"])
        self.assertTrue(any(m.type == "base-sink" for m in spec.module))
        doors = [p for p in out["placed"] if p["what"] == "opening"]
        self.assertEqual(len(doors), len(spec.openings))
        self.assertTrue(self.svc.validate(self.did)["valid"])

    def test_a_system_laid_again_from_a_sentence_takes_the_designs_levels(self):      # "thay thế bằng tủ bếp chữ i có tủ lạnh"
        self.svc.auto_place(self.did)
        spec, rev = self.svc.store.get(self.did)
        system = next(r.system for r in spec.runs if r.system == "furniture_017")
        out = self.svc.template(self.did, {"kind": "replace-system", "system": system, "prompt": "tủ bếp chữ i có tủ lạnh"}, rev)
        added = [o["module"] for o in out["operation"]["ops"] if o["op"] == "add"]
        c = spec.common
        self.assertTrue(any(m["type"] == "tall-fridge" for m in added))
        for m in added:
            if m["type"] == "upper":
                self.assertEqual((m["y"], m["y"] + m["height"]), (c.upperBottom, c.upperTierSplit))
            if m["type"] in ("tall", "tall-fridge"):
                self.assertEqual(m["y"] + m["height"], c.cabinetTop)
        self.assertFalse([i for i in out["proposal"]["validation"]["introduced"] if i["rule"] == "GEO-HEIGHTS"])

    def test_a_second_run_builds_nothing_more(self):
        self.svc.auto_place(self.did)
        again = self.svc.auto_place(self.did)
        self.assertEqual(again["rev"], 2)
        self.assertEqual(again["placed"], [])
        self.assertTrue(all(s["reason"] == "exists" for s in again["skipped"]))


if __name__ == "__main__":
    unittest.main()
