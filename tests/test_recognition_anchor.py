"""A recognised run stands along the edge of the object the user picked (line -> run), instead of at the kitchen's origin."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import geometry, roomctx, run_line  # noqa: E402
from kitchen.errors import InvalidInput, NotFound  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from test_floorplan import ROOM, elem, plan, rect  # noqa: E402

RAW = {"modules": [
    {"type": "base", "wall": "back", "width": 600, "fromCorner": 0},
    {"type": "base", "wall": "back", "width": 900, "fromCorner": 600},
    {"type": "upper", "wall": "back", "width": 600, "fromCorner": 0},
    {"type": "base", "wall": "left", "width": 600, "fromCorner": 0},
]}


class Fake:
    def recognize(self, source):
        return RAW


class TestLine(unittest.TestCase):
    def test_run_frame_from_a_line(self):
        f = run_line.run_frame(run_line.Line((0.0, 0.0), (1000.0, 0.0), (0.0, 1.0)))     # doors look +z: s grows towards +x
        self.assertEqual((f["x"], f["z"], f["yaw"], f["length"]), (0.0, 0.0, 0.0, 1000.0))
        g = run_line.run_frame(run_line.Line((1000.0, 0.0), (0.0, 0.0), (0.0, 1.0)))     # the same line given the other way round
        self.assertEqual((g["x"], g["yaw"], g["length"]), (0.0, 0.0, 1000.0))
        h = run_line.run_frame(run_line.Line((0.0, 0.0), (1000.0, 0.0), (0.0, -1.0)))    # doors look -z: s grows towards -x, the run starts at the far end
        self.assertEqual((h["x"], h["yaw"]), (1000.0, 180.0))

    def test_edge_line_faces_away_from_the_object(self):
        box = [(0.0, 0.0), (400.0, 0.0), (400.0, 300.0), (0.0, 300.0)]
        self.assertEqual(run_line.edge_line(box, (200.0, 310.0)).normal, (0.0, 1.0))
        self.assertEqual(run_line.edge_line(box, (-10.0, 150.0)).normal, (-1.0, 0.0))
        with self.assertRaises(InvalidInput):
            run_line.edge_line(box[:2], (0.0, 0.0))


class TestAnchored(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="anchor-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.recognizers.clear()
        self.svc.recognizers["fake"] = Fake()
        col = elem("column_a", "column", "column", rect(1500, 2000, 1900, 2400), "Cot")
        self.did = self.svc.import_floorplan(plan(ROOM, col))["id"]
        self.svc.apply(self.did, {"op": "add", "module": {"type": "base", "wall": "back", "fromCorner": 0, "width": 600, "y": 0, "height": 840, "depth": 550}}, 1)
        self.svc.bind_floorplan(self.did)
        spec, self.rev = self.svc.store.get(self.did)
        sc = geometry.compile_spec(spec)
        self.place = roomctx.for_spec(spec, sc.lsau, sc.lphai).placement
        self.source = {"kind": "photo", "imageBase64": "AA=="}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def anchor(self, kx, kz):
        x, z = self.place.to_room(kx, kz)
        return {"structureId": "STRUCT-column_a", "point": {"x": x, "z": z}}

    def test_without_an_anchor_everything_is_replaced_as_before(self):
        r = self.svc.recognize(self.did, self.source, "fake")
        self.assertEqual((r["status"], r["operation"]["op"]), ("ok", "replace"))

    def test_the_back_wall_run_is_added_along_the_object_and_saves_nothing(self):
        before, rev = self.svc.store.get(self.did)
        r = self.svc.recognize(self.did, self.source, "fake", anchor=self.anchor(-1500.0, 1990.0))
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["structureId"], "STRUCT-column_a")
        ops = r["operation"]["ops"] if "ops" in r["operation"] else [r["operation"]]
        kinds = [o["op"] for o in ops]
        self.assertEqual(kinds[0], "add-run")
        self.assertEqual(kinds.count("add"), 3, "two base cabinets and one wall cabinet; the left-wall one is dropped")
        self.assertTrue(any("left out" in line for line in r["summary"]))
        self.assertTrue(r["proposal"]["applicable"])
        self.assertEqual(len(self.svc.history(self.did)), rev)
        out = self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        after, rev2 = self.svc.store.get(self.did)
        self.assertEqual((rev2, len(after.module)), (rev + 1, len(before.module) + 3))
        run_modules = [m for m in after.module if m.run]
        self.assertEqual(sorted((m.type, m.fromCorner, m.width) for m in run_modules),
                         [("base", 0.0, 900.0), ("base", 900.0, 600.0), ("upper", 900.0, 600.0)], "mirrored: the first cabinet seen from the right ends the run")
        self.assertTrue(out)

    def test_the_run_touches_the_object_but_does_not_enter_it(self):
        r = self.svc.recognize(self.did, self.source, "fake", anchor=self.anchor(-1500.0, 1990.0))
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        after, _ = self.svc.store.get(self.did)
        sc = geometry.compile_spec(after)
        ctx = roomctx.for_spec(after, sc.lsau, sc.lphai)
        struct = next(s for s in ctx.structures if s["id"] == "STRUCT-column_a")
        pts = [ctx.placement.to_kitchen(float(p["x"]), float(p["z"])) for p in struct["outline"]]
        cx0, cx1, cz0, cz1 = min(p[0] for p in pts), max(p[0] for p in pts), min(p[1] for p in pts), max(p[1] for p in pts)
        run_ids = {m.id for m in after.module if m.run}
        parts = [p for p in sc.parts if p.module in run_ids and p.type in ("carcass", "door", "plinth")]
        ox = min(max(p.max[0] for p in parts), cx1) - max(min(p.min[0] for p in parts), cx0)
        oz = min(max(p.max[2] for p in parts), cz1) - max(min(p.min[2] for p in parts), cz0)
        self.assertFalse(ox > 1 and oz > 1, "the run enters the object")
        self.assertLessEqual(max(-ox, 0) ** 2 + max(-oz, 0) ** 2, 1.0, "the run stands away from the object")

    def test_replace_mode_removes_the_old_cabinets(self):
        before, _ = self.svc.store.get(self.did)
        r = self.svc.recognize(self.did, self.source, "fake", anchor=self.anchor(-1500.0, 1990.0), mode="replace")
        ops = r["operation"]["ops"] if "ops" in r["operation"] else [r["operation"]]
        self.assertEqual([o["id"] for o in ops if o["op"] == "remove"], [m.id for m in before.module])
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        after, _ = self.svc.store.get(self.did)
        self.assertTrue(all(m.run for m in after.module))

    def test_bad_input(self):
        for anchor in ({"structureId": "STRUCT-column_a"}, {"structureId": 3, "point": {"x": 1, "z": 2}}, {"structureId": "a", "point": {"x": "1", "z": 2}}):
            with self.assertRaises(InvalidInput) as ctx:
                self.svc.recognize(self.did, self.source, "fake", anchor=anchor)
            self.assertEqual(ctx.exception.code, "bad-anchor")
        with self.assertRaises(InvalidInput):
            self.svc.recognize(self.did, self.source, "fake", anchor=self.anchor(-1500.0, 1990.0), mode="both")
        with self.assertRaises(NotFound):
            self.svc.recognize(self.did, self.source, "fake", anchor={"structureId": "STRUCT-nope", "point": {"x": 1, "z": 2}})




class TestDescribedKitchen(unittest.TestCase):
    """A sentence (no picture) becomes cabinets along the clicked edge: fridge, loft row, worktop colour, devices."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="described-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        col = elem("column_a", "column", "column", rect(1500, 2000, 1900, 4400), "Cot")
        self.did = self.svc.import_floorplan(plan(ROOM, col))["id"]
        self.svc.apply(self.did, {"op": "add", "module": {"type": "base", "wall": "back", "fromCorner": 0, "width": 600, "y": 0, "height": 840, "depth": 550}}, 1)
        self.svc.bind_floorplan(self.did)
        spec, self.rev = self.svc.store.get(self.did)
        sc = geometry.compile_spec(spec)
        place = roomctx.for_spec(spec, sc.lsau, sc.lphai).placement
        x, z = place.to_room(-1500.0, 3000.0)
        self.point = {"x": x, "z": z}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_described_kitchen_has_the_fridge_loft_devices_and_materials(self):
        r = self.svc.template(self.did, {"kind": "run-i", "structureId": "STRUCT-column_a", "point": self.point,
                                         "prompt": "tạo tủ bếp có tủ lạnh, mặt đá đen, tủ dưới xanh rêu, có tủ nóc"}, self.rev)
        self.assertTrue(r["proposal"]["applicable"])
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        after, _ = self.svc.store.get(self.did)
        types = {m.type for m in after.module if m.run}
        self.assertTrue({"tall-fridge", "upper-loft", "base-sink", "base-cooktop", "upper-hood"} <= types)
        self.assertEqual({t.type for t in after.appliances} >= {"fridge", "sink", "cooktop", "hood"}, True)
        self.assertEqual((after.common.material["countertop"], after.common.material["base"]), ("Đá nhân tạo đen", "Xanh rêu"))
        parts = {p.type for p in geometry.compile_spec(after).parts}
        self.assertTrue({"fridge", "sink", "cooktop", "hood"} <= parts)

    def test_without_a_prompt_the_old_plain_run_is_unchanged(self):
        r = self.svc.template(self.did, {"kind": "run-i", "structureId": "STRUCT-column_a", "point": self.point}, self.rev)
        ops = r["operation"]["ops"] if "ops" in r["operation"] else [r["operation"]]
        self.assertTrue(all(o["module"]["type"] == "base" for o in ops if o["op"] == "add"))

if __name__ == "__main__":
    unittest.main()
