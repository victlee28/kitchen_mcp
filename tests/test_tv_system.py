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

from kitchen import edit, geometry, prompts, rules, runs as runmod, threejs_export, tv_system as tv  # noqa: E402
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
        host = next(m for m in mods if m.get("appliance"))
        self.assertEqual((sets[0]["type"], sets[0]["model"], host["s"] + sets[0]["center"]), ("tv", "tv-65", 1990.0))

    def test_short_line_has_no_columns_and_a_smaller_tv(self):
        mods = tv.layout(1300, COMMON)
        self.assertFalse([m for m in mods if m["type"] == "tall"])
        self.assertEqual(next(m["appliance"]["model"] for m in mods if m.get("appliance")), "tv-43")

    def test_three_layouts_by_sentence(self):
        self.assertEqual([tv.style_of(t) for t in ("tạo hệ tủ tivi", "tủ tivi kín cả vách", "kệ tivi, kệ treo, không có cột")],
                         ["columns", "full", "shelves"])
        self.assertIsNone(tv.explicit_style("thay cả hệ tivi"))
        self.assertEqual(tv.explicit_style("tivi 2 cột"), "columns")
        full = tv.layout(3980, COMMON, "full")
        self.assertEqual(sorted({m["type"] for m in full}), ["base", "tall", "upper"])
        self.assertEqual(sum(m["width"] for m in full if m["y"] == 0), 3980.0)        # closed from end to end at floor level
        for style in tv.STYLES:
            for length in (3980, 3170, 2450, 1600):
                widths = [m["width"] for m in tv.layout(length, COMMON, style)]
                self.assertTrue(all(w % 10 == 0 for w in widths), (style, length, widths))
        shelves = tv.layout(3980, COMMON, "shelves")
        self.assertFalse([m for m in shelves if m["type"] == "tall"])
        self.assertEqual(len([m for m in shelves if m["type"] == "upper-open"]), 2)

    def test_panel_behind_the_tv_unless_refused(self):
        host = next(m for m in tv.layout(3980, COMMON) if m.get("appliance"))
        bp = host["backPanel"]
        self.assertEqual((host["s"] + bp["from"], host["s"] + bp["to"], bp["y0"], bp["y1"]), (600.0, 3380.0, 450.0, tv.SHELF_Y))
        self.assertFalse(tv.wants_panel("tạo hệ tủ tivi không ốp"))
        self.assertFalse(any(m.get("backPanel") for m in tv.layout(3980, COMMON, panel=False)))

    def test_asks_tv(self):
        for text in ("tạo hệ tủ tivi", "làm kệ TV", "tủ ti vi gỗ sồi"):
            self.assertTrue(tv.asks_tv(text), text)
        for text in ("tạo tủ bếp có tủ lạnh", "", None):
            self.assertFalse(tv.asks_tv(text), text)


def _spec_with_tv() -> KitchenSpec:
    spec = KitchenSpec.model_validate({"module": []})
    plan = plan_on_line(spec, Line((0.0, 0.0), (3980.0, 0.0), (0.0, 1.0)), tv.layout(3980, COMMON), run_fields=tv.run_fields("columns"))
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


class TestTvRunOps(unittest.TestCase):
    def test_panel_is_drawn_and_the_tv_stands_in_front_of_it(self):
        scene = geometry.compile_spec(_spec_with_tv())
        host = next(a.module for a in _spec_with_tv().appliances if a.type == "tv")
        panel = [p for p in scene.parts if p.module == host and p.type == "side-panel" and p.lmax[1] - p.lmin[1] > 1000]
        self.assertEqual(len(panel), 1)

    def test_the_tv_moves_with_its_cabinet(self):
        spec = _spec_with_tv()
        tv_app = next(a for a in spec.appliances if a.type == "tv")
        before = next(p for p in geometry.compile_spec(spec).parts if p.type == "tv")
        host = spec.find(tv_app.module)
        moved = edit.apply_op(spec, {"op": "update", "id": host.id, "changes": {"fromCorner": host.fromCorner + 100}})
        after = next(p for p in geometry.compile_spec(moved).parts if p.type == "tv")
        self.assertAlmostEqual(abs((after.lmin[0] - before.lmin[0]) + (after.lmin[2] - before.lmin[2])), 100.0, delta=0.5)

    def test_full_layout_wall_cabinets_share_the_tall_finish(self):
        uppers = [m for m in tv.layout(3980, {"cabinetTop": 2610, "material": {"tall": "Gỗ óc chó"}}, "full") if m["type"] == "upper"]
        self.assertTrue(uppers and all(m["material"] == "Gỗ óc chó" for m in uppers))

    def test_set_run_tv_marks_and_clears(self):
        spec = _spec_with_tv()
        rid = next(iter(tv.tv_runs(spec)))
        spec = edit.apply_op(spec, {"op": "set-run-tv", "id": rid, "layout": "full"})
        self.assertEqual(tv.layout_of(spec, rid), "full")
        spec = edit.apply_op(spec, {"op": "set-run-tv", "id": rid, "layout": None})
        self.assertEqual(tv.tv_runs(spec), set())

    def test_whole_system_laid_again_in_another_layout_or_as_a_kitchen(self):
        from kitchen.service import KitchenService
        spec = _spec_with_tv()
        system = runmod.systems(spec)[spec.module[0].id]
        plan = KitchenService._replace_system(spec, system, "đổi hệ tivi sang kín cả vách", None, None)
        new = edit.apply_op(spec, plan["operation"])
        rid = next(iter(tv.tv_runs(new)))
        self.assertEqual(tv.layout_of(new, rid), "full")
        self.assertIn("upper", {m.type for m in new.module})
        self.assertEqual(len([a for a in new.appliances if a.type == "tv"]), 1)
        kitchen = edit.apply_op(new, KitchenService._replace_system(new, system, "thành tủ bếp có chậu rửa", None, None)["operation"])
        self.assertEqual(tv.tv_runs(kitchen), set())


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
