"""Cabinet template: an I-shaped run of base cabinets along the edge of an object, doors facing away from it."""
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import cabinet_run, edit, geometry, roomctx, threejs_export  # noqa: E402
from kitchen.errors import InvalidInput, NotFound  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import KitchenSpec, from_data  # noqa: E402
from test_floorplan import ROOM, elem, plan, rect  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
# object in the kitchen frame: x from -2500 to -2100 (towards the left wall), z from 2000 to 2400 (into the room)
BOX = [(-2500.0, 2000.0), (-2100.0, 2000.0), (-2100.0, 2400.0), (-2500.0, 2400.0)]


def _spec() -> KitchenSpec:
    return from_data(KitchenSpec, json.loads(json.dumps(FIX)))


def _carcass(spec, new_ids):
    parts = [p for p in geometry.compile_spec(spec).parts if p.module in new_ids and p.type in ("carcass", "door", "plinth")]
    return [min(p.min[0] for p in parts), max(p.max[0] for p in parts), min(p.min[2] for p in parts), max(p.max[2] for p in parts)]


class TestPlan(unittest.TestCase):
    def test_each_side_of_the_object_faces_away_from_it(self):
        cases = {(-2300.0, 1990.0): "-z", (-2300.0, 2410.0): "+z", (-2510.0, 2200.0): "-x", (-2090.0, 2200.0): "+x"}
        for point, facing in cases.items():
            plan = cabinet_run.plan_i_run(_spec(), BOX, point)
            self.assertEqual(plan["facing"], facing, point)
            self.assertEqual(plan["length"], 400.0 if facing in ("-z", "+z") else 400.0)

    def test_run_stands_against_the_object_without_entering_it(self):
        spec = _spec()
        for point in ((-2300.0, 1990.0), (-2300.0, 2410.0), (-2510.0, 2200.0), (-2090.0, 2200.0)):
            op = cabinet_run.plan_i_run(spec, BOX, point)["operation"]
            after = edit.apply_op(spec, op)
            new = {m.id for m in after.module} - {m.id for m in spec.module}
            x0, x1, z0, z1 = _carcass(after, new)
            # touching the object is fine, entering it is not
            inside_x, inside_z = min(x1, -2100) - max(x0, -2500), min(z1, 2400) - max(z0, 2000)
            self.assertFalse(inside_x > 1 and inside_z > 1, (point, [x0, x1, z0, z1]))
            self.assertTrue(inside_x >= -1 and inside_z >= -1 and (inside_x <= 1 or inside_z <= 1), (point, [x0, x1, z0, z1]))

    def test_widths(self):
        self.assertEqual(cabinet_run.split_widths(1800), [600, 600, 600])
        self.assertEqual(cabinet_run.split_widths(1500), [600, 600, 300])
        self.assertEqual(cabinet_run.split_widths(1700), [600, 600, 500])
        self.assertEqual(cabinet_run.split_widths(1250), [600, 650])
        self.assertEqual(cabinet_run.split_widths(400), [400])
        with self.assertRaises(InvalidInput):
            cabinet_run.split_widths(200)

    def test_degenerate_input_is_refused(self):
        with self.assertRaises(InvalidInput):
            cabinet_run.plan_i_run(_spec(), BOX[:2], (0.0, 0.0))
        diamond = [(-2300.0, 2000.0), (-2100.0, 2200.0), (-2300.0, 2400.0), (-2500.0, 2200.0)]     # sides of 283 mm: below the narrowest cabinet
        with self.assertRaises(InvalidInput) as ctx:
            cabinet_run.plan_i_run(_spec(), diamond, (-2200.0, 2100.0))
        self.assertEqual(ctx.exception.code, "run-too-short")

    def test_outside_the_wall_quadrant_becomes_a_free_run(self):
        """fromCorner/offset cannot be negative: an object behind the back wall or right of the right-hand corner gets an explicit run, not an error."""
        behind = [(-2500.0, -900.0), (-2100.0, -900.0), (-2100.0, -500.0), (-2500.0, -500.0)]
        right_of_corner = [(4890.0, 4260.0), (8870.0, 4260.0), (8870.0, 4610.0), (4890.0, 4610.0)]
        for outline, point in ((behind, (-2300.0, -910.0)), (right_of_corner, (6000.0, 4610.0)), (right_of_corner, (6000.0, 4260.0))):
            spec = _spec()
            plan = cabinet_run.plan_i_run(spec, outline, point)
            ops = plan["operation"]["ops"] if "ops" in plan["operation"] else [plan["operation"]]
            self.assertEqual(ops[0]["op"], "add-run")
            run = ops[0]["run"]
            self.assertTrue(all(o["module"]["run"] == run["id"] for o in ops[1:]))
            applied = edit.apply_op(spec, plan["operation"])
            self.assertEqual(len(applied.runs), 1)
            self.assertGreaterEqual(plan["length"], 300)


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="template-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        col = elem("column_a", "column", "column", rect(1500, 2000, 1900, 2400), "Cot")
        self.did = self.svc.import_floorplan(plan(ROOM, col))["id"]
        self.svc.apply(self.did, {"op": "add", "module": {"type": "base", "wall": "back", "fromCorner": 0, "width": 600, "y": 0, "height": 840, "depth": 550}}, 1)
        self.svc.bind_floorplan(self.did)
        spec, self.rev = self.svc.store.get(self.did)
        sc = geometry.compile_spec(spec)
        self.place = roomctx.for_spec(spec, sc.lsau, sc.lphai).placement

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def click(self, kx, kz):
        x, z = self.place.to_room(kx, kz)
        return {"kind": "run-i", "structureId": "STRUCT-column_a", "point": {"x": x, "z": z}}

    def test_preview_faces_away_from_the_column_and_saves_nothing(self):
        r = self.svc.template(self.did, self.click(-2300.0, 1990.0))
        self.assertEqual((r["status"], r["facing"], r["length"]), ("ok", "-z", 400.0))
        self.assertTrue(r["proposal"]["applicable"])
        self.assertEqual(len(self.svc.history(self.did)), self.rev)            # nothing was written
        r2 = self.svc.template(self.did, self.click(-2300.0, 2410.0))
        self.assertEqual(r2["facing"], "+z")

    def test_confirm_applies_exactly_the_preview(self):
        r = self.svc.template(self.did, self.click(-2300.0, 1990.0))
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        spec, rev = self.svc.store.get(self.did)
        self.assertEqual(rev, self.rev + 1)
        run = [m for m in spec.module if m.wall == "island"]
        self.assertEqual([(m.facing, m.width) for m in run], [("-z", 400.0)])

    def test_confirm_survives_a_browser_round_trip(self):
        """JSON.parse turns 600.0 into 600; the opHash of the preview must still match what the browser sends back."""
        r = self.svc.template(self.did, self.click(-2300.0, 1990.0))

        def browser(v):
            if isinstance(v, float) and v.is_integer():
                return int(v)
            if isinstance(v, dict):
                return {k: browser(x) for k, x in v.items()}
            if isinstance(v, list):
                return [browser(x) for x in v]
            return v
        sent = browser(json.loads(json.dumps(r["operation"])))
        self.assertNotEqual(json.dumps(sent, sort_keys=True), json.dumps(r["operation"], sort_keys=True))     # the round trip really changed the text
        self.svc.apply(self.did, sent, r["baseRev"], "web", r["proposal"]["opHash"])

    def test_diagonal_object_gets_an_angled_run_and_confirm_applies_it(self):
        diamond = elem("diamond_a", "column", "column", [[1500, 2150], [1850, 1800], [2200, 2150], [1850, 2500]], "Cot cheo")
        did = self.svc.import_floorplan(plan(ROOM, diamond))["id"]
        self.svc.apply(did, {"op": "add", "module": {"type": "base", "wall": "back", "fromCorner": 0, "width": 600, "y": 0, "height": 840, "depth": 550}}, 1)
        self.svc.bind_floorplan(did)
        spec, rev = self.svc.store.get(did)
        sc = geometry.compile_spec(spec)
        ctx = roomctx.for_spec(spec, sc.lsau, sc.lphai)
        struct = next(t for t in ctx.structures if t["id"] == "STRUCT-diamond_a")
        a, b = struct["outline"][0], struct["outline"][1]
        r = self.svc.template(did, {"kind": "run-i", "structureId": "STRUCT-diamond_a", "point": {"x": (a["x"] + b["x"]) / 2, "z": (a["z"] + b["z"]) / 2}})
        self.assertEqual(r["status"], "ok")
        self.assertIsNone(r["facing"])
        self.assertTrue(r["proposal"]["applicable"])
        self.assertFalse(r["proposal"]["validation"]["introducesErrors"], r["proposal"]["validation"])
        self.svc.apply(did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        spec, rev2 = self.svc.store.get(did)
        self.assertEqual((rev2, [x.id for x in spec.runs]), (rev + 1, ["R1"]))
        self.assertTrue(any(p.frame is not None for p in geometry.compile_spec(spec).parts))
        doc = threejs_export.export(spec, did, rev2)
        run = doc["runs"][0]
        modules = [m for m in doc["modules"] if m["placement"].get("runId") == run["id"]]
        self.assertTrue(modules)
        # A bound run group must stay aligned with the world transforms of its child modules.
        rp = run["transform"]["position"]
        mp = modules[0]["transform"]["position"]
        self.assertAlmostEqual(rp["x"], mp["x"], delta=0.02)
        self.assertAlmostEqual(rp["z"], mp["z"], delta=0.02)
        self.assertAlmostEqual(run["transform"]["rotation"]["y"], modules[0]["transform"]["rotation"]["y"], delta=0.02)
        yaw = math.radians(run["transform"]["rotation"]["y"])
        self.assertAlmostEqual(run["frontAxis"]["x"], math.sin(yaw), delta=0.01)
        self.assertAlmostEqual(run["frontAxis"]["z"], math.cos(yaw), delta=0.01)
        top = next(a for a in doc["accessories"] if a.get("partRef", {}).get("run") == run["sourceRef"])
        self.assertAlmostEqual(top["transform"]["position"]["x"], rp["x"], delta=0.02)
        self.assertAlmostEqual(top["transform"]["position"]["z"], rp["z"], delta=0.02)

    def test_bad_requests(self):
        with self.assertRaises(NotFound):
            self.svc.template(self.did, {**self.click(-2300.0, 1990.0), "structureId": "STRUCT-nope"})
        with self.assertRaises(InvalidInput):
            self.svc.template(self.did, {"kind": "run-l"})
        with self.assertRaises(InvalidInput):
            self.svc.template(self.did, {"kind": "run-i", "structureId": "STRUCT-column_a", "point": {"x": "a"}})
        plain = self.svc.create_from_spec(json.loads(json.dumps(FIX)))["id"]
        with self.assertRaises(InvalidInput) as ctx:
            self.svc.template(plain, {"kind": "run-i", "structureId": "STRUCT-column_a", "point": {"x": 0, "z": 0}})
        self.assertEqual(ctx.exception.code, "no-floorplan")


if __name__ == "__main__":
    unittest.main()
