"""TV wall units (hệ tủ tivi, 10/11/2026): layout, no worktop, no kitchen rule, the TV drawn and exported."""
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import geometry, prompts, rules, threejs_export, tv_system as tv  # noqa: E402
from kitchen.edit import apply_op  # noqa: E402
from kitchen.run_line import Line, plan_on_line  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402

COMMON = {"cabinetTop": 2610}


class TestLayout(unittest.TestCase):
    def test_long_line_has_two_columns_a_console_a_shelf_and_a_tv(self):
        mods = tv.layout(3980, COMMON)
        tall = [m for m in mods if m["type"] == "tall"]
        self.assertEqual([(m["s"], m["width"], m["height"]) for m in tall], [(0.0, 600.0, 2610.0), (3380.0, 600.0, 2610.0)])
        console = [m for m in mods if m["type"] == "base"]
        self.assertEqual(sum(m["width"] for m in console), 2780.0)
        self.assertTrue(all(m["height"] == tv.CONSOLE_HEIGHT and m["width"] <= tv.CONSOLE_MAX for m in console))
        shelf = [m for m in mods if m["type"] == "upper-open"]
        self.assertEqual((shelf[0]["s"], shelf[0]["width"]), (600.0, 2780.0))
        sets = [m["appliance"] for m in mods if m.get("appliance")]
        self.assertEqual(len(sets), 1)
        self.assertEqual((sets[0]["type"], sets[0]["model"], sets[0]["center"]), ("tv", "tv-65", 1990.0))

    def test_short_line_has_no_columns_and_a_smaller_tv(self):
        mods = tv.layout(1300, COMMON)
        self.assertFalse([m for m in mods if m["type"] == "tall"])
        self.assertEqual(next(m["appliance"]["model"] for m in mods if m.get("appliance")), "tv-43")

    def test_asks_tv(self):
        for text in ("tạo hệ tủ tivi", "làm kệ TV", "tủ ti vi gỗ sồi"):
            self.assertTrue(tv.asks_tv(text), text)
        for text in ("tạo tủ bếp có tủ lạnh", "", None):
            self.assertFalse(tv.asks_tv(text), text)


def _spec_with_tv() -> KitchenSpec:
    spec = KitchenSpec.model_validate({"module": []})
    plan = plan_on_line(spec, Line((0.0, 0.0), (3980.0, 0.0), (0.0, 1.0)), tv.layout(3980, COMMON), purpose=tv.PURPOSE)
    return apply_op(spec, plan["operation"])


class TestTvUnitInTheDesign(unittest.TestCase):
    def test_run_is_marked_and_has_no_worktop(self):
        spec = _spec_with_tv()
        self.assertEqual(len(tv.tv_runs(spec)), 1)
        scene = geometry.compile_spec(spec)
        self.assertFalse([p for p in scene.parts if p.type in ("countertop", "wall-tile")])
        screen = [p for p in scene.parts if p.type == "tv"]
        self.assertEqual(len(screen), 1)

    def test_no_kitchen_rule_fires_on_it(self):
        spec = _spec_with_tv()
        mods = {m.id for m in spec.module}
        hits = [i for i in rules.validate(spec)["issues"] if set(i["module"]) & mods]
        self.assertEqual(hits, [])

    def test_export_has_a_television_and_the_prompt_says_tv_unit(self):
        spec = _spec_with_tv()
        doc = threejs_export.export(spec, "tv", 1)
        tvs = [a for a in doc["appliances"] if a["type"] == "Television"]
        self.assertEqual(len(tvs), 1)
        self.assertEqual(tvs[0]["installation"]["mountType"], "wall_mounted")
        import jsonschema
        schema = json.loads((ROOT / "schemas" / "kitchen-threejs.schema.json").read_text(encoding="utf-8"))
        self.assertEqual([e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(doc)][:3], [])
        text = prompts.global_prompt(spec)
        self.assertIn("TV wall unit", text)
        self.assertIn("living room", text)

    def test_kitchen_only_drops_the_tv_unit(self):
        spec = _spec_with_tv()
        self.assertEqual(tv.kitchen_only(spec).module, [])


class TestReplaceFurnitureWithATvUnit(unittest.TestCase):
    def setUp(self):
        from kitchen.service import KitchenService
        self.tmp = Path(tempfile.mkdtemp(prefix="tv-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_vach_tv_becomes_a_tv_unit(self):
        src = ROOT / "kitchen.db"
        row = sqlite3.connect(f"file:{src}?mode=ro", uri=True).execute(
            "select spec_json from revisions where design_id='mau-du-lieu-c64d31' order by rev desc limit 1").fetchone() if src.exists() else None
        if row is None:
            self.skipTest("mau-du-lieu-c64d31 not in kitchen.db")
        did = self.svc.create_from_spec(json.loads(row[0]))["id"]
        r = self.svc.template(did, {"kind": "run-i", "structureId": "STRUCT-furniture_021", "point": {"x": 0, "z": 0}, "prompt": "tạo hệ tủ tivi"})
        self.assertEqual(r["status"], "ok")
        self.svc.apply(did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        spec, _ = self.svc.store.get(did)
        runs = tv.tv_runs(spec)
        self.assertEqual(len(runs), 1)
        mods = [m for m in spec.module if m.run in runs]
        self.assertEqual(sorted({m.type for m in mods}), ["base", "tall", "upper-open"])
        self.assertTrue(any(a.type == "tv" for a in spec.appliances))
        self.assertIn("furniture_021", spec.floorplan["replaced"])


if __name__ == "__main__":
    unittest.main()
