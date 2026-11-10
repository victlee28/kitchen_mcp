"""Runs on lines with their backs to the wall; a piece of furniture replaced by cabinets (plan 10/11/2026: ke-hoach-thay-vat-bang-he-tu)."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import cabinet_run, edit, runs, wall_line as w  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402

ROOM = [(0.0, 0.0), (4000.0, 0.0), (4000.0, 3000.0), (0.0, 3000.0)]
WALLS = w.segments(ROOM)


class TestWallEdges(unittest.TestCase):
    def test_a_box_against_one_wall(self):
        box = [(500.0, 50.0), (3000.0, 50.0), (3000.0, 650.0), (500.0, 650.0)]
        got = w.wall_edges(box, WALLS)
        self.assertEqual([(e.index, e.length, e.gap) for e in got], [(0, 2500.0, 50.0)])
        self.assertEqual(w.depth_from(box, got[0]), 600.0)

    def test_too_far_or_not_parallel_is_not_against_the_wall(self):
        far = [(500.0, 200.0), (3000.0, 200.0), (3000.0, 800.0), (500.0, 800.0)]
        self.assertEqual(w.wall_edges(far, WALLS), [])
        skew = [(500.0, 50.0), (3000.0, 250.0), (3000.0, 850.0), (500.0, 650.0)]   # ~4.6°
        self.assertEqual(w.wall_edges(skew, WALLS), [])

    def test_an_l_in_the_corner_gives_two_runs_that_do_not_overlap(self):
        corner = [(0.0, 0.0), (3000.0, 0.0), (3000.0, 600.0), (600.0, 600.0), (600.0, 2000.0), (0.0, 2000.0)]
        r = w.replace_lines(corner, WALLS)
        self.assertEqual(r["status"], "ok")
        (a, b) = r["runs"]
        self.assertEqual((a.a, a.b, a.doors, a.depth), ((0.0, 0.0), (3000.0, 0.0), (-0.0, 1.0), 600.0))
        self.assertEqual((b.a, b.b, b.doors, b.depth), ((0.0, 2000.0), (0.0, 600.0), (1.0, 0.0), 600.0))     # starts after the first run's depth

    def test_an_island_asks_for_the_back_edge(self):
        island = [(1500.0, 1200.0), (3000.0, 1200.0), (3000.0, 2100.0), (1500.0, 2100.0)]
        r = w.replace_lines(island, WALLS)
        self.assertEqual(r["status"], "choose-edge")
        self.assertEqual([(e.index, e.length) for e in r["edges"]], [(0, 1500.0), (2, 1500.0), (1, 900.0), (3, 900.0)])
        (p,) = w.replace_lines(island, WALLS, back_edge=2)["runs"]
        self.assertEqual((p.doors, p.depth), ((-0.0, -1.0), 900.0))

    def test_back_to_wall_turns_the_doors_away_from_the_wall(self):
        self.assertEqual(w.back_to_wall((500.0, 100.0), (3000.0, 100.0), (0.0, -1.0), WALLS), ((-0.0, 1.0), True))
        self.assertEqual(w.back_to_wall((500.0, 1500.0), (3000.0, 1500.0), (0.0, 1.0), WALLS), ((0.0, 1.0), False))


class TestLayoutRules(unittest.TestCase):
    """Rules of 10/11/2026: with a fridge the sink stands nearer to it than the hob; the hood always stands over the hob."""

    def _check(self, prompt):
        from kitchen import intent
        color, _ = intent.parse_prompt(prompt)
        spec = intent.from_template(color)
        hob = next(m for m in spec.module if m.type == "base-cooktop")
        hoods = [m for m in spec.module if m.type == "upper-hood"]
        self.assertEqual([(h.wall, h.fromCorner, h.width) for h in hoods], [(hob.wall, hob.fromCorner, hob.width)], prompt)
        return spec

    def test_sink_nearer_the_fridge_than_the_hob(self):
        from kitchen import geometry
        for prompt in ("bếp chữ I dài 3m có tủ lạnh", "bếp chữ I dài 4.5m có tủ lạnh", "bếp chữ L 3m và 2.4m có tủ lạnh", "bếp chữ U có tủ lạnh"):
            spec = self._check(prompt)
            scene = geometry.compile_spec(spec)
            centre = {m.id: next(((p.min[0] + p.max[0]) / 2, (p.min[2] + p.max[2]) / 2) for p in scene.parts if p.module == m.id) for m in spec.module}
            fridge = centre[next(m.id for m in spec.module if m.type == "tall-fridge")]
            sink = centre[next(m.id for m in spec.module if m.type == "base-sink")]
            hob = centre[next(m.id for m in spec.module if m.type == "base-cooktop")]
            dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
            self.assertLess(dist(sink, fridge), dist(hob, fridge), prompt)

    def test_hood_over_the_hob_without_a_fridge_too(self):
        for prompt in ("bếp chữ I dài 3m", "bếp chữ L 3m và 2.4m", "bếp chữ U"):
            self._check(prompt)


class TestFitDepth(unittest.TestCase):
    def test_base_and_tall_follow_the_object_wall_cabinets_only_when_shallow(self):
        mods = [{"type": "base", "depth": 580.0}, {"type": "tall-fridge", "depth": 640.0}, {"type": "upper", "depth": 320.0}, {"type": "upper-loft", "depth": 320.0}]
        self.assertEqual([m["depth"] for m in cabinet_run.fit_depth(mods, 600.0)], [600.0, 600.0, 320.0, 320.0])
        self.assertEqual([m["depth"] for m in cabinet_run.fit_depth(mods, 330.0)], [330.0, 330.0, 330.0, 330.0])


class TestPlanReplace(unittest.TestCase):
    def test_old_cabinets_of_the_element_go_and_the_element_is_marked(self):
        fp = {"elements": [{"id": "furniture_003", "kind": "furniture"}]}
        old = KitchenSpec.model_validate({"floorplan": fp, "runs": [{"id": "R1", "x": 0, "z": 1000, "yaw": 0, "system": "furniture_003"}],
                                          "module": [{"id": "TD1", "type": "base", "wall": "island", "run": "R1", "fromCorner": 0, "width": 600, "height": 840, "depth": 580}]})
        placed = [w.Placed((0.0, 0.0), (1200.0, 0.0), (0.0, 1.0), 600.0, 0)]
        laid = [[{"type": "base", "width": 600.0, "s": 0.0, "y": 0.0, "height": 840.0, "depth": 600.0},
                 {"type": "base", "width": 600.0, "s": 600.0, "y": 0.0, "height": 840.0, "depth": 600.0}]]
        plan = cabinet_run.plan_replace(old, "furniture_003", placed, laid)
        after = edit.apply_op(old, plan["operation"])
        self.assertEqual(plan["removed"], ["TD1"])
        self.assertEqual(after.floorplan["replaced"], ["furniture_003"])
        self.assertFalse(any(m.id == "TD1" for m in after.module))
        self.assertEqual({runs.systems(after)[m.id] for m in after.module}, {"furniture_003"})
        self.assertEqual(len(after.module), 2)
        back = edit.apply_op(after, {"op": "replace-element", "id": "furniture_003", "replaced": False})
        self.assertNotIn("replaced", back.floorplan)


class TestServiceOnARealFloorplan(unittest.TestCase):
    """The audited floorplan fixture of the repository, if present."""

    def setUp(self):
        from kitchen.service import KitchenService
        self.tmp = Path(tempfile.mkdtemp(prefix="replace-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_replace_then_change_the_system_then_go_back(self):
        src = ROOT / "kitchen.db"
        if not src.exists():
            self.skipTest("no kitchen.db with an imported floorplan")
        import json
        import sqlite3
        row = sqlite3.connect(f"file:{src}?mode=ro", uri=True).execute(
            "select spec_json from revisions where design_id='mau-du-lieu-c64d31' order by rev desc limit 1").fetchone()
        if row is None:
            self.skipTest("mau-du-lieu-c64d31 not in kitchen.db")
        from kitchen.errors import InvalidInput
        did = self.svc.create_from_spec(json.loads(row[0]))["id"]
        first = self.svc.store.get(did)[1]
        r = self.svc.template(did, {"kind": "run-i", "structureId": "STRUCT-furniture_003", "point": {"x": 0, "z": 0}})
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["proposal"]["applicable"], r["proposal"].get("error"))
        self.svc.apply(did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        spec, rev = self.svc.store.get(did)
        system = runs.systems(spec)
        mine = [m for m in spec.module if system[m.id] == "furniture_003"]
        self.assertEqual(len({m.run for m in mine}), 1)
        self.assertEqual({m.depth for m in mine if m.storey == "base"}, {600.0})
        self.assertEqual(spec.floorplan["replaced"], ["furniture_003"])
        with self.assertRaises(InvalidInput) as again:                     # the object is gone: its cabinets are changed as a system
            self.svc.template(did, {"kind": "run-i", "structureId": "STRUCT-furniture_003", "point": {"x": 0, "z": 0}})
        self.assertEqual(again.exception.code, "element-replaced")
        r = self.svc.template(did, {"kind": "replace-system", "system": "furniture_003", "prompt": "có chậu rửa"})
        self.assertTrue(r["proposal"]["applicable"], r["proposal"].get("error"))
        self.svc.revert(did, first, rev)
        spec, _ = self.svc.store.get(did)
        self.assertNotIn("replaced", spec.floorplan)
        self.assertFalse(any(runs.systems(spec).get(m.id) == "furniture_003" for m in spec.module))


if __name__ == "__main__":
    unittest.main()
