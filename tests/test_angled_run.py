"""Runs at any angle: the template along a diagonal edge, add-run, ids and run pruning, collisions with exact polygons."""
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import cabinet_run, edit, geometry, rules, runs  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402
from kitchen.floorplan.geom import point_in_poly  # noqa: E402
from kitchen.spec import KitchenSpec, from_data, to_data  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
# a diamond (square turned 45 degrees) with 700 mm sides, standing in the room
DIAMOND = [(-2300.0, 1800.0), (-1805.0, 2295.0), (-2300.0, 2790.0), (-2795.0, 2295.0)]


def _spec() -> KitchenSpec:
    return from_data(KitchenSpec, json.loads(json.dumps(FIX)))


class TestAngledTemplate(unittest.TestCase):
    def test_diagonal_edge_gets_an_explicit_run_facing_away(self):
        spec = _spec()
        plan = cabinet_run.plan_i_run(spec, DIAMOND, (-2050.0, 2050.0))          # near the edge (-2300,1800)-(-1805,2295)
        self.assertIsNone(plan["facing"])
        self.assertAlmostEqual(plan["length"], 700, delta=1)
        out = edit.apply_op(spec, plan["operation"])
        self.assertEqual(len(out.runs), 1)
        mods = [m for m in out.module if m.run]
        self.assertEqual(sum(m.width for m in mods), plan["length"])
        fr = runs.frame_of(out, mods[0])
        nx, nz = fr.normal()
        mid = ((DIAMOND[0][0] + DIAMOND[1][0]) / 2, (DIAMOND[0][1] + DIAMOND[1][1]) / 2)
        self.assertFalse(point_in_poly((mid[0] + nx * 5, mid[1] + nz * 5), DIAMOND), "the doors look out of the object")
        # the cabinets touch the edge and never go into the object
        for m in mods:
            foot = runs.module_footprint(fr, m)
            self.assertLessEqual(runs.penetration(foot, DIAMOND), 0.5, m.id)
        self.assertAlmostEqual(math.hypot(nx, nz), 1.0)

    def test_every_edge_of_the_diamond_faces_outward(self):
        for i in range(4):
            a, b = DIAMOND[i], DIAMOND[(i + 1) % 4]
            point = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            spec = _spec()
            plan = cabinet_run.plan_i_run(spec, DIAMOND, point)
            out = edit.apply_op(spec, plan["operation"])
            mods = [m for m in out.module if m.run]
            fr = runs.frame_of(out, mods[0])
            for m in mods:
                self.assertEqual(runs.penetration(runs.module_footprint(fr, m), DIAMOND) > 0.5, False, (i, m.id))
            check = geometry.compile_spec(out)
            self.assertTrue(any(p.frame is not None for p in check.parts))


class TestRunOps(unittest.TestCase):
    def _with_run(self):
        spec = edit.apply_op(_spec(), {"op": "add-run", "run": {"x": -1500, "z": 2500, "yaw": 30}})
        self.assertEqual(spec.runs[0].id, "R1")
        for w in (600, 600):
            spec = edit.apply_op(spec, {"op": "add", "closeGap": False, "module": {"type": "base", "wall": "island", "run": "R1", "fromCorner": 0 if not any(m.run for m in spec.module) else 600, "width": w, "y": 0, "height": 840, "depth": 550}})
        return spec

    def test_second_run_gets_the_next_id(self):
        spec = self._with_run()
        spec = edit.apply_op(spec, {"op": "add-run", "run": {"x": 0, "z": 3000, "yaw": 90}})
        self.assertEqual([r.id for r in spec.runs], ["R1", "R2"])
        with self.assertRaises(InvalidInput):
            edit.apply_op(spec, {"op": "add-run", "run": {"id": "R1", "x": 0, "z": 0, "yaw": 0}})

    def test_add_after_a_module_stays_in_its_run(self):
        spec = self._with_run()
        last = [m for m in spec.module if m.run][-1]
        spec = edit.apply_op(spec, {"op": "add", "afterModule": last.id, "module": {"type": "base", "width": 450}})
        new = spec.module[-1]
        self.assertEqual((new.run, new.wall, new.fromCorner), ("R1", "island", last.endAt))

    def test_removing_the_last_module_drops_the_run(self):
        spec = self._with_run()
        for m in [m for m in spec.module if m.run]:
            spec = edit.apply_op(spec, {"op": "remove", "id": m.id})
        self.assertEqual(spec.runs, [])

    def test_removing_a_cabinet_closes_the_gap_inside_its_run_only(self):
        spec = self._with_run()
        first, second = [m for m in spec.module if m.run]
        spec2 = edit.apply_op(spec, {"op": "remove", "id": first.id})
        self.assertEqual(spec2.find(second.id).fromCorner, 0)
        # the wall cabinets did not move
        self.assertEqual([m.fromCorner for m in spec2.module if not m.run], [m.fromCorner for m in spec.module if not m.run])

    def test_ids_are_never_reused(self):
        spec = _spec()
        ids = [m.id for m in spec.module if m.id.startswith("TD")]
        top = max(int(i[2:]) for i in ids)
        spec = edit.apply_op(spec, {"op": "add", "module": {"type": "base", "wall": "back", "fromCorner": 3000, "width": 300, "height": 840, "depth": 550}})
        first = spec.module[-1].id
        self.assertEqual(first, f"TD{top + 1}")
        spec = edit.apply_op(spec, {"op": "remove", "id": first})
        spec = edit.apply_op(spec, {"op": "add", "module": {"type": "base", "wall": "back", "fromCorner": 3000, "width": 300, "height": 840, "depth": 550}})
        self.assertEqual(spec.module[-1].id, f"TD{top + 2}")

    def test_unknown_run_is_rejected(self):
        spec = _spec()
        with self.assertRaises(ValueError):
            edit.apply_op(spec, {"op": "add", "module": {"type": "base", "wall": "island", "run": "R9", "width": 600, "height": 840, "depth": 550}})


class TestAngledRules(unittest.TestCase):
    def _two(self, yaw2):
        data = json.loads(json.dumps(FIX))
        data["runs"] = [{"id": "R1", "x": -1500, "z": 2500, "yaw": 0}, {"id": "R2", "x": -1500, "z": 2500, "yaw": yaw2}]
        base = {"type": "base", "wall": "island", "y": 0, "height": 840, "depth": 550, "width": 1000}
        data["module"] += [{**base, "id": "TD91", "run": "R1"}, {**base, "id": "TD92", "run": "R2"}]
        return from_data(KitchenSpec, data)

    def test_overlap_uses_exact_polygons(self):
        hits = lambda spec: [i for i in rules.check_geometry(spec) if i["rule"] == "GEO-COLLISION" and "TD91" in i["module"] and "TD92" in i["module"]]
        self.assertTrue(hits(self._two(45)), "two rows that cross collide")
        far = self._two(120)                                   # move the second run so its footprint clears the first
        d = to_data(far)
        d["runs"][1].update(x=-4000, z=4500)
        self.assertFalse(hits(from_data(KitchenSpec, d)))

    def test_bounding_boxes_alone_would_over_report(self):
        # a long row at 45 degrees next to a straight cabinet: boxes overlap, shapes do not
        data = json.loads(json.dumps(FIX))
        data["runs"] = [{"id": "R1", "x": -3000, "z": 1500, "yaw": 135}]       # u = (cos135, -sin135) = (-0.7, -0.7)
        data["module"] += [{"id": "TD91", "type": "base", "wall": "island", "run": "R1", "fromCorner": 0, "width": 2000, "y": 0, "height": 840, "depth": 550},
                           {"id": "TD92", "type": "base", "wall": "island", "offset": 3200, "facing": "-z", "fromCorner": 2500, "width": 600, "y": 0, "height": 840, "depth": 550}]
        spec = from_data(KitchenSpec, data)
        fr = runs.frame_of(spec, spec.find("TD91"))
        (ax, az), (bx, bz) = runs.aabb(runs.module_footprint(fr, spec.find("TD91")))
        env = {i: (mn, mx) for i, mn, mx in rules._envelopes(spec)}
        self.assertEqual(env["TD91"][0][0], ax)
        clash = [i for i in rules.check_geometry(spec) if i["rule"] == "GEO-COLLISION" and "TD91" in i["module"] and "TD92" in i["module"]]
        self.assertEqual(clash, [])


if __name__ == "__main__":
    unittest.main()
