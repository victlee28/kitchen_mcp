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


class TestCornerCabinet(unittest.TestCase):
    """The special corner cabinet where two runs meet at any angle."""

    def _spec(self, degrees, a_end=2000.0, b_start=1000.0):
        import math
        ub = (-math.cos(math.radians(degrees)), math.sin(math.radians(degrees)))    # run B leaves the corner at (3000, 0) at this angle from run A
        yaw_b = math.degrees(math.atan2(-ub[1], ub[0]))
        data = json.loads(json.dumps(FIX))
        data["appliances"] = []
        base = {"type": "base", "wall": "island", "y": 0, "height": 840, "depth": 550}
        data["runs"] = [{"id": "R1", "x": 0, "z": 0, "yaw": 0}, {"id": "R2", "x": 3000, "z": 0, "yaw": yaw_b}]
        data["module"] = [{**base, "id": "A1", "run": "R1", "fromCorner": a_end - 1000, "width": 1000},
                          {**base, "id": "B1", "run": "R2", "fromCorner": b_start, "width": 1000}]
        return from_data(KitchenSpec, data)

    def _clashes(self, spec):
        return [i for i in rules.check_geometry(spec) if i["rule"] == "GEO-COLLISION"]

    def test_clear_runs_leave_no_collision_at_any_angle(self):
        for degrees in (60, 90, 120, 150):
            with self.subTest(degrees=degrees):
                spec = self._spec(degrees)
                plan = cabinet_run.plan_corner(spec, "R1", "R2")
                self.assertAlmostEqual(plan["angle"], degrees, delta=0.1)
                a_max, b_min = plan["clearance"]["aMaxEnd"], plan["clearance"]["bMinStart"]
                tight = self._spec(degrees, a_end=a_max - 2, b_start=b_min + 2)
                out = edit.apply_op(tight, cabinet_run.plan_corner(tight, "R1", "R2")["operation"])
                self.assertEqual(self._clashes(out), [])
                self.assertTrue(any(m.run == "R3" for m in out.module))

    def test_overlapping_runs_are_reported(self):
        spec = self._spec(120, a_end=2900.0, b_start=100.0)
        plan = cabinet_run.plan_corner(spec, "R1", "R2")
        self.assertEqual(len(plan["summary"]), 3)                       # headline + one note per run that is too long
        self.assertTrue(self._clashes(edit.apply_op(spec, plan["operation"])))

    def test_bad_input(self):
        spec = self._spec(90)
        with self.assertRaises(InvalidInput):
            cabinet_run.plan_corner(spec, "R1", "R9")
        data = to_data(spec)
        data["runs"][1].update(yaw=0)
        with self.assertRaises(InvalidInput) as ctx:
            cabinet_run.plan_corner(from_data(KitchenSpec, data), "R1", "R2")
        self.assertEqual(ctx.exception.code, "runs-parallel")


class TestCornerTemplateService(unittest.TestCase):
    def test_service_previews_and_applies_the_corner(self):
        import shutil
        import tempfile
        from kitchen.service import KitchenService
        tmp = Path(tempfile.mkdtemp(prefix="corner-"))
        try:
            svc = KitchenService(tmp / "k.db", tmp / "renders")
            did = svc.create_from_spec(to_data(TestCornerCabinet()._spec(120, a_end=1900.0, b_start=1100.0)))["id"]
            r = svc.template(did, {"kind": "corner", "runA": "R1", "runB": "R2"})
            self.assertEqual((r["status"], r["facing"]), ("ok", None))
            self.assertTrue(r["proposal"]["applicable"])
            svc.apply(did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
            spec, _ = svc.store.get(did)
            self.assertEqual([x.id for x in spec.runs], ["R1", "R2", "R3"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestAngledMoldings(unittest.TestCase):
    """A run with yaw -90 at the origin is the right wall; its moldings must be the same curves, and a turned run must carry them with it."""

    def _spec(self, as_run, yaw=-90.0, x=0.0, z=0.0):
        from kitchen import moldings
        data = json.loads(json.dumps(FIX))
        data["appliances"] = []
        base = {"y": 0, "height": 840, "depth": 550}
        upper = {"y": 1400, "height": 700, "depth": 320}
        place = {"wall": "island", "run": "R1"} if as_run else {"wall": "right"}
        data["module"] = [{**base, **place, "id": "B1", "type": "base", "fromCorner": 100, "width": 900},
                          {**upper, **place, "id": "U1", "type": "upper", "fromCorner": 100, "width": 900}]
        if as_run:
            data["runs"] = [{"id": "R1", "x": x, "z": z, "yaw": yaw}]
        data["moldings"] = [to_data(m) for m in moldings.default_moldings()]
        return from_data(KitchenSpec, data)

    def test_run_equal_to_the_right_wall_gives_the_same_moldings(self):
        from kitchen import moldings
        wall = {(r.molding.variant): r.points for r in moldings.compute_runs(self._spec(False)) if r.wall == ["right"]}
        run = {(r.molding.variant): r.points for r in moldings.compute_runs(self._spec(True)) if r.wall == ["R1"]}
        self.assertEqual(sorted(wall), ["base", "crown"])
        for variant, pts in wall.items():
            self.assertEqual(len(pts), len(run[variant]), variant)
            for a, b in zip(pts, run[variant]):
                self.assertAlmostEqual(a[0], b[0], delta=1e-6)
                self.assertAlmostEqual(a[1], b[1], delta=1e-6)

    def test_turned_run_moves_the_moldings_rigidly(self):
        from kitchen import moldings
        a = {r.molding.variant: r.points for r in moldings.compute_runs(self._spec(True, yaw=0.0)) if r.wall == ["R1"]}
        b = {r.molding.variant: r.points for r in moldings.compute_runs(self._spec(True, yaw=37.0, x=1000.0, z=500.0)) if r.wall == ["R1"]}
        for variant in a:
            da = [math.dist(p, q) for p, q in zip(a[variant], a[variant][1:])]
            db = [math.dist(p, q) for p, q in zip(b[variant], b[variant][1:])]
            for u, v in zip(da, db):
                self.assertAlmostEqual(u, v, delta=1e-6)
        self.assertEqual(len(moldings.meshes(self._spec(True, yaw=37.0))), len(moldings.compute_runs(self._spec(True, yaw=37.0))))
