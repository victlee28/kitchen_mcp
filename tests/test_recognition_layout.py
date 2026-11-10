"""A kitchen recognised BY RUNS (recognized-runs/1) stands on the edge the user picked: the main run along it, the joined runs square to it."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import geometry, roomctx, run_line  # noqa: E402
from kitchen.recognition import build_layout, recognizer_wire  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402
from test_floorplan import ROOM, elem, plan, rect  # noqa: E402

DATA = ROOT / "tests" / "data" / "recognized_runs"


def fixture(name):
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))["runs"]


def ops_of(operation):
    return operation["ops"] if "ops" in operation else [operation]


class Fake:
    def __init__(self, doc):
        self.doc = doc

    def recognize(self, source):
        flat = [{"type": m["type"], "wall": "back", "width": m["width"], "fromCorner": m["s"]} for r in self.doc["runs"] for m in r["modules"]]
        return {"modules": flat, "layout": self.doc}


class TestPlanRuns(unittest.TestCase):
    """Pure core: recognised runs -> one operation on an empty kitchen."""
    LINE = run_line.Line((0.0, 0.0), (6000.0, 0.0), (0.0, 1.0))

    def plan(self, name):
        layout = build_layout(fixture(name))
        self.assertIsNotNone(layout)
        runs = [{"id": r.id, "length": r.length, "modules": list(r.modules)} for r in layout.runs]
        return layout, run_line.plan_runs(KitchenSpec(), self.LINE, runs, list(layout.joints))

    def test_every_recognised_cabinet_of_every_fixture_is_placed_and_the_kitchen_compiles(self):
        from kitchen import edit
        for name in ("l-shape", "u-shape", "straight"):
            with self.subTest(fixture=name):
                layout, p = self.plan(name)
                spec = edit.apply_op(KitchenSpec(), p["operation"])
                self.assertEqual(len(spec.module), layout.count)
                self.assertEqual(len(spec.runs), len(layout.runs))
                self.assertTrue(all(m.run and m.wall == "island" for m in spec.module))
                geometry.compile_spec(spec)

    def test_the_runs_of_an_l_and_a_u_stand_square_to_each_other(self):
        _, l = self.plan("l-shape")
        self.assertEqual(sorted(round(r["run"]["yaw"]) % 180 for r in l["runs"]), [0, 90])
        _, u = self.plan("u-shape")
        self.assertEqual(sorted(round(r["run"]["yaw"]) for r in u["runs"]), [-90, 0, 90])

    def test_doors_drawers_and_appliances_survive(self):
        from kitchen import edit
        layout, p = self.plan("l-shape")
        spec = edit.apply_op(KitchenSpec(), p["operation"])
        want_doors = sum(1 for r in layout.runs for m in r.modules if m.get("doors"))
        want_fronts = sum(1 for r in layout.runs for m in r.modules if m.get("frontSections"))
        want_apps = sum(len(m.get("appliances") or []) for r in layout.runs for m in r.modules)
        self.assertGreater(want_doors + want_fronts, 0)
        self.assertGreater(want_apps, 0)
        self.assertTrue(all(a.module for a in spec.appliances))
        self.assertEqual(sum(1 for m in spec.module if m.doors), want_doors)
        self.assertEqual(sum(1 for m in spec.module if m.frontSections), want_fronts)
        self.assertEqual(len(spec.appliances), want_apps)


class TestBackWall(unittest.TestCase):
    """No edge picked: the kitchen stands on the back wall of the kitchen frame, and a kitchen made only of runs still gets its room."""

    def build(self, name, room=None):
        from kitchen import edit
        layout = build_layout(fixture(name))
        runs = [{"id": r.id, "length": r.length, "modules": list(r.modules)} for r in layout.runs]
        spec = KitchenSpec.model_validate({"common": {"material": {"wallTile": "white"}}, **({"room": room} if room else {})})
        line = run_line.back_wall_line(spec, runs)
        after = edit.apply_op(spec, run_line.plan_runs(spec, line, runs, list(layout.joints))["operation"])
        return runs, line, after, geometry.compile_spec(after)

    def test_the_line_is_the_back_wall_as_long_as_the_main_run_or_the_room(self):
        runs, line, _, _ = self.build("l-shape")
        main = next(r for r in runs if r["id"] == "back")
        self.assertEqual((line.a, line.b, line.normal), ((-main["length"], 0.0), (0.0, 0.0), (0.0, 1.0)))
        _, wide, _, _ = self.build("l-shape", {"wall": [{"id": "back", "length": 6000}, {"id": "right", "length": 4000}]})
        self.assertEqual(wide.a, (-6000.0, 0.0))

    def test_walls_and_tiles_follow_the_runs(self):
        for name, walls in (("straight", 2), ("l-shape", 3), ("u-shape", 3)):
            with self.subTest(fixture=name):
                runs, _, after, scene = self.build(name)
                main = next((r for r in runs if r["id"] == "back"), runs[0])
                self.assertEqual(scene.lsau, main["length"], "the back wall is as long as the main run, so a left run stands against the left wall")
                self.assertEqual(sum(1 for p in scene.parts if p.type == "wall"), walls)
                tiled = sum(1 for p in scene.parts if p.type == "wall-tile")
                tops = sum(1 for p in scene.parts if p.type == "countertop")
                self.assertEqual(tiled, tops, "every worktop of a run that stands against a wall has its tiles")
                for p in scene.parts:
                    if p.module:
                        self.assertTrue(-scene.lsau - 1 <= p.min[0] and p.max[0] <= 1 and p.min[2] >= -1, f"{p.id} is inside the room")

    def test_a_run_standing_free_or_in_an_imported_plan_has_no_wall_tiles(self):
        from kitchen import edit
        spec = KitchenSpec.model_validate({"common": {"material": {"wallTile": "white"}}})
        free = run_line.plan_on_line(spec, run_line.Line((-3000.0, 1500.0), (0.0, 1500.0), (0.0, 1.0)),
                                     [{"type": "base", "s": 0, "width": 600, "y": 0, "height": 840, "depth": 600}])
        scene = geometry.compile_spec(edit.apply_op(spec, free["operation"]))
        self.assertFalse([p for p in scene.parts if p.type == "wall-tile"])


class TestWire(unittest.TestCase):
    def test_layout_is_taken_only_from_a_recognized_runs_payload(self):
        doc = fixture("l-shape")
        self.assertEqual(recognizer_wire.layout_from_runs({"runs": doc}), doc)
        self.assertIsNone(recognizer_wire.layout_from_runs({"runs": {"schema": "other"}}))
        self.assertIsNone(recognizer_wire.layout_from_runs({"kitchenSpec": {}}))


class TestAnchoredLayout(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="layout-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.recognizers.clear()
        self.doc = fixture("l-shape")
        self.svc.recognizers["fake"] = Fake(self.doc)
        col = elem("column_a", "column", "column", rect(1500, 2000, 1900, 2400), "Cot")
        self.did = self.svc.import_floorplan(plan(ROOM, col))["id"]
        self.svc.apply(self.did, {"op": "add", "module": {"type": "base", "wall": "back", "fromCorner": 0, "width": 600, "y": 0, "height": 840, "depth": 550}}, 1)
        self.svc.bind_floorplan(self.did)
        spec, self.rev = self.svc.store.get(self.did)
        sc = geometry.compile_spec(spec)
        self.place = roomctx.for_spec(spec, sc.lsau, sc.lphai).placement
        self.source = {"kind": "photo", "imageBase64": "AA=="}
        x, z = self.place.to_room(-1500.0, 1990.0)
        self.anchor = {"structureId": "STRUCT-column_a", "point": {"x": x, "z": z}}
        self.total = sum(len(r["modules"]) for r in self.doc["runs"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_runs_are_proposed_and_nothing_is_saved_until_apply(self):
        before, rev = self.svc.store.get(self.did)
        r = self.svc.recognize(self.did, self.source, "fake", anchor=self.anchor)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(r["runs"]), len(self.doc["runs"]))
        kinds = [o["op"] for o in ops_of(r["operation"])]
        self.assertEqual((kinds.count("add-run"), kinds.count("add")), (len(self.doc["runs"]), self.total))
        self.assertEqual(r["layout"]["joints"], [["left", "back"]] if self.doc["joints"][0]["a"] == "left" else [["back", "right"]])
        self.assertEqual(self.svc.store.get(self.did)[1], rev)
        self.assertTrue(r["proposal"]["applicable"])
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        after, rev2 = self.svc.store.get(self.did)
        self.assertEqual((rev2, len(after.module)), (rev + 1, len(before.module) + self.total))

    def test_replace_mode_clears_the_old_cabinets(self):
        r = self.svc.recognize(self.did, self.source, "fake", anchor=self.anchor, mode="replace")
        self.assertEqual(r["status"], "ok")
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        after, _ = self.svc.store.get(self.did)
        self.assertEqual(len(after.module), self.total)

    def test_without_an_anchor_the_runs_replace_the_cabinets_along_the_back_wall(self):
        r = self.svc.recognize(self.did, self.source, "fake")
        self.assertEqual((r["status"], r["mode"]), ("ok", "replace"))
        self.assertNotIn("structureId", r)
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        after, _ = self.svc.store.get(self.did)
        self.assertEqual(len(after.module), self.total)
        self.assertEqual(sorted(run.yaw for run in after.runs), [0.0, 90.0])
        self.assertTrue(all(run.z == 0.0 for run in after.runs if run.yaw == 0.0))

    def test_a_flat_draft_is_written_by_runs_and_placed_the_same_way(self):
        class Flat:
            def recognize(self, source):
                return {"modules": [{"type": "base", "wall": "back", "width": 600, "fromCorner": 0}, {"type": "base", "wall": "back", "width": 900},
                                    {"type": "base", "wall": "right", "width": 600, "fromCorner": 600}, {"type": "base", "wall": "left", "width": 500, "fromCorner": 600}],
                        "room": {"ceiling": 2900}, "materials": {"countertop": "black granite"}}
        self.svc.recognizers["fake"] = Flat()
        for anchor in (None, self.anchor):
            with self.subTest(anchored=anchor is not None):
                r = self.svc.recognize(self.did, self.source, "fake", anchor=anchor)
                self.assertEqual(r["status"], "ok")
                self.assertEqual([run["id"] for run in r["layout"]["runs"]], ["left", "back", "right"])
                back = next(run for run in r["layout"]["runs"] if run["id"] == "back")
                self.assertEqual(sorted((m["s"], m["width"]) for m in back["modules"]), [(0.0, 900.0), (900.0, 600.0)], "mirrored: fromCorner 0 is the right-hand end")
                self.assertEqual(r["layout"]["joints"], [["left", "back"], ["back", "right"]])
                self.assertEqual(sum(1 for o in r["operation"]["ops"] if o["op"] == "add"), 4)

    def test_replacing_takes_the_levels_ceiling_and_materials_that_were_seen(self):
        doc = json.loads(json.dumps(self.doc))
        doc["common"] = {**doc.get("common", {}), "baseTop": 820, "countertop": 850, "countertopThickness": 30, "cabinetTop": 2400, "plinthHeight": "x"}
        self.svc.recognizers["fake"] = Fake(doc)
        r = self.svc.recognize(self.did, self.source, "fake")
        first = r["operation"]["ops"][0]
        self.assertEqual(first["op"], "common")
        self.assertEqual((first["changes"]["baseTop"], first["changes"]["countertop"], first["changes"]["cabinetTop"]), (820.0, 850.0, 2400.0))
        self.assertNotIn("plinthHeight", first["changes"])
        added = self.svc.recognize(self.did, self.source, "fake", anchor=self.anchor)
        self.assertFalse([o for o in added["operation"]["ops"] if o["op"] == "common"], "adding beside the cabinets already there changes no level")


if __name__ == "__main__":
    unittest.main()
