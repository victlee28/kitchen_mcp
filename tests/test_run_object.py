"""A run is an object the user handles: draw its line, move it, turn it, drag an end, remove it; where two runs meet in an inside corner the
worktop and the moldings go round the corner."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import edit, geometry, moldings, rules, runs  # noqa: E402
from kitchen.errors import InvalidInput, NotFound  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from test_rows import SINK, base, kitchen  # noqa: E402


def upper(s, width):
    return {"type": "upper", "s": s, "width": width, "y": 1500, "height": 700, "depth": 350}


def world(spec, module_id):
    """World (x0, z0, x1, z1) of a cabinet's carcass."""
    p = next(p for p in geometry.compile_spec(spec).parts if p.module == module_id and p.type == "carcass")
    return tuple(round(v, 3) for v in (p.min[0], p.min[2], p.max[0], p.max[2]))


class TestRunOps(unittest.TestCase):
    def setUp(self):
        self.spec = kitchen([base("base", 0, 600, doors=[300, 300]), base("base-sink", 600, 800, **SINK), base("base", 1400, 600), upper(0, 600), upper(600, 800)])
        self.run = self.spec.runs[0].id
        self.by_s = sorted((m for m in self.spec.module if m.storey == "base"), key=lambda m: m.fromCorner)

    def test_moving_and_turning_a_run_takes_its_cabinets_along(self):
        before = world(self.spec, self.by_s[0].id)
        moved = edit.apply_op(self.spec, {"op": "move-run", "id": self.run, "changes": {"x": self.spec.runs[0].x + 500, "z": 1200}})
        after = world(moved, self.by_s[0].id)
        self.assertEqual((after[0] - before[0], after[1] - before[1]), (500.0, 1200.0))
        turned = edit.apply_op(self.spec, {"op": "move-run", "id": self.run, "changes": {"yaw": 90}})
        x0, z0, x1, z1 = world(turned, self.by_s[0].id)
        self.assertEqual(round(z1 - z0), 600, "now its width runs along z")
        self.assertLess(x1 - x0, 600)
        for bad in ({}, {"length": 3}, {"x": "1"}):
            with self.assertRaises(InvalidInput):
                edit.apply_op(self.spec, {"op": "move-run", "id": self.run, "changes": bad})
        with self.assertRaises(NotFound):
            edit.apply_op(self.spec, {"op": "move-run", "id": "R99", "changes": {"x": 0}})

    def test_dragging_the_end_widens_the_last_cabinet_of_each_storey_that_reaches_it(self):
        out = edit.apply_op(self.spec, {"op": "stretch-run", "id": self.run, "end": "end", "delta": 150})
        widths = {m.id: m.width for m in out.module}
        self.assertEqual(widths[self.by_s[2].id], 750.0)
        self.assertEqual([widths[m.id] for m in self.by_s[:2]], [600.0, 800.0])
        self.assertEqual(sorted(m.width for m in out.module if m.storey == "upper"), [600.0, 800.0], "the wall cabinets stop short of the end: left alone")
        self.assertEqual(world(out, self.by_s[0].id), world(self.spec, self.by_s[0].id))
        self.assertEqual((out.runs[0].x, out.runs[0].z), (self.spec.runs[0].x, self.spec.runs[0].z))

    def test_dragging_the_start_keeps_every_other_cabinet_where_it_stands(self):
        out = edit.apply_op(self.spec, {"op": "stretch-run", "id": self.run, "end": "start", "delta": 200})
        first = next(m for m in out.module if m.id == self.by_s[0].id)
        self.assertEqual((first.width, first.fromCorner, first.doors), (800.0, 0.0, [400.0, 400.0]), "wider, doors in proportion")
        self.assertEqual(sorted(m.width for m in out.module if m.storey == "upper"), [800.0, 800.0], "the wall cabinet at the start is widened too (600 -> 800)")
        for m in self.by_s[1:]:
            self.assertEqual(world(out, m.id), world(self.spec, m.id), f"{m.id} did not move in the room")
        self.assertEqual(out.runs[0].x, self.spec.runs[0].x - 200)
        sink = next(t for t in out.appliances if t.type == "sink")
        self.assertEqual(runs.spot(out, sink).center, 1200.0, "the sink is still in the middle of its cabinet")
        self.assertFalse([i for i in rules.validate(out)["issues"] if i["rule"] in ("GEO-COLLISION", "GEO-DOOR")])

    def test_a_drag_that_would_make_a_cabinet_too_narrow_or_too_wide_is_refused(self):
        for delta in (-500, 1500):
            with self.assertRaises(InvalidInput) as ctx:
                edit.apply_op(self.spec, {"op": "stretch-run", "id": self.run, "end": "end", "delta": delta})
            self.assertEqual(ctx.exception.code, "stretch-limit")
        for bad in ({"end": "middle", "delta": 10}, {"end": "end", "delta": 0}, {"end": "end", "delta": "x"}):
            with self.assertRaises(InvalidInput):
                edit.apply_op(self.spec, {"op": "stretch-run", "id": self.run, **bad})

    def test_removing_a_run_takes_its_cabinets_and_appliances(self):
        two = kitchen([base("base", 0, 900), base("base", 900, 900)], left=[base("base-sink", 0, 900, **SINK), base("base", 900, 600)])
        left = next(r.id for r in two.runs if r.yaw == 90.0)
        out = edit.apply_op(two, {"op": "remove-run", "id": left})
        self.assertEqual(([r.id for r in out.runs], len(out.module), len(out.appliances)), ([r.id for r in two.runs if r.id != left], 2, 0))


class TestCorner(unittest.TestCase):
    """left run (ends at the corner) + back run (starts at the corner)."""

    def test_the_joint_is_found_from_where_the_runs_stand(self):
        spec = kitchen([base("base", 600, 900), base("base", 1500, 900)], left=[base("base", 0, 900), base("base", 900, 600)])
        left, back = (next(r.id for r in spec.runs if r.yaw == yaw) for yaw in (90.0, 0.0))
        self.assertEqual(runs.corner_joints(spec), [runs.Joint(left, back, 1500.0)])
        apart = edit.apply_op(spec, {"op": "move-run", "id": left, "changes": {"x": spec.runs[0].x - 900}})
        self.assertEqual(runs.corner_joints(apart), [], "moved away: no corner any more")
        turned = edit.apply_op(spec, {"op": "move-run", "id": left, "changes": {"yaw": 45}})
        self.assertEqual(runs.corner_joints(turned), [])

    def test_the_worktop_closes_an_empty_corner(self):
        spec = kitchen([base("base", 600, 900), base("base", 1500, 900)], left=[base("base", 0, 900), base("base", 900, 600)])
        left = next(r.id for r in spec.runs if r.yaw == 90.0)
        last = max((m for m in spec.module if m.run == left), key=lambda m: m.fromCorner)
        spec = edit.apply_op(spec, {"op": "remove", "id": last.id, "closeGap": False})                    # now both runs stop 600 short of the corner
        self.assertEqual(len(runs.corner_joints(spec)), 1)
        tops = {p.run: (p.lmin[0], p.lmax[0]) for p in geometry.compile_spec(spec).parts if p.type == "countertop"}
        self.assertEqual(tops[left], (0.0, 1500.0), "carried on from 900 to the corner")
        far = kitchen([base("base", 2000, 900)], left=[base("base", 0, 900), base("base", 2000, 600)])
        gaps = [p for p in geometry.compile_spec(far).parts if p.type == "countertop" and p.run == next(r.id for r in far.runs if r.yaw == 90.0)]
        self.assertEqual(len(gaps), 2, "a real gap in a run is not bridged")

    def test_moldings_turn_the_corner_as_one_piece(self):
        spec = kitchen([base("base", 600, 900), base("base", 1500, 900), upper(350, 1150), upper(1500, 900)],
                       left=[base("base", 0, 900), base("base", 900, 600), upper(0, 900), upper(900, 600)])
        spec = edit.apply_op(spec, {"op": "set-moldings", "moldings": [m.model_dump() for m in moldings.default_moldings(True, True)], "style": "Classic"})
        chains = moldings.compute_runs(spec)
        self.assertEqual(sorted((c.molding.variant, len(c.wall)) for c in chains), [("base", 2), ("crown", 2)], "one chain per molding, through both runs")
        crown = next(c for c in chains if c.molding.variant == "crown")
        x0 = min(r.x for r in spec.runs)
        self.assertIn((x0 + 350.0, 350.0), [(round(x, 1), round(z, 1)) for x, z in crown.points], "it turns where the two fronts cross")
        self.assertEqual(len(moldings.meshes(spec)), 2)
        apart = edit.apply_op(spec, {"op": "move-run", "id": next(r.id for r in spec.runs if r.yaw == 90.0), "changes": {"x": x0 - 2000}})
        self.assertEqual(sorted(len(c.wall) for c in moldings.compute_runs(apart)), [1, 1, 1, 1], "apart again: each run its own pieces")


class TestOpenCorner(unittest.TestCase):
    """Two runs meeting at 135 degrees (a bay): the back run, and a second run turned 45 degrees starting on its back line."""

    def setUp(self):
        from kitchen.spec import KitchenSpec
        mods = []
        for run, at in (("R1", 0), ("R1", 900), ("R2", 300), ("R2", 1200)):
            n = len(mods) + 1
            mods.append({"id": f"TD{n}", "type": "base", "wall": "island", "run": run, "fromCorner": at, "width": 900, "y": 0, "height": 840, "depth": 600})
            mods.append({"id": f"TT{n}", "type": "upper", "wall": "island", "run": run, "fromCorner": at, "width": 900, "y": 1500, "height": 700, "depth": 350})
        self.spec = KitchenSpec.model_validate({"runs": [{"id": "R1", "x": -4000, "z": 0, "yaw": 0}, {"id": "R2", "x": -1900, "z": 0, "yaw": -45}], "module": mods,
                                                "floorplan": None})

    def test_the_corner_is_found_with_its_angle(self):
        (joint,) = runs.corner_joints(self.spec)
        self.assertEqual((joint.a, joint.b, joint.at, round(joint.angle, 3), joint.square), ("R1", "R2", 2100.0, 135.0, False))
        flat = edit.apply_op(self.spec, {"op": "move-run", "id": "R2", "changes": {"yaw": -5}})
        self.assertEqual(runs.corner_joints(flat), [], "nearly straight on: not a corner")

    def test_a_wedge_of_worktop_closes_it(self):
        scene = geometry.compile_spec(self.spec)
        (wedge,) = [m for m in scene.meshes if m.type == "countertop"]
        xs, zs, ys = [v[0] for v in wedge.vertices], [v[2] for v in wedge.vertices], {v[1] for v in wedge.vertices}
        self.assertEqual(ys, {self.spec.common.baseTop, self.spec.common.countertop})
        self.assertEqual((round(min(xs)), round(min(zs))), (-2200, 0), "from the end of the first worktop, at the wall")
        self.assertGreater(max(zs), 600, "round the point where the two front edges cross, to the second worktop")
        self.assertFalse([i for i in rules.validate(self.spec)["issues"] if i["rule"] == "GEO-COLLISION"])
        square = edit.apply_op(self.spec, {"op": "move-run", "id": "R2", "changes": {"yaw": -90}})
        self.assertFalse([m for m in geometry.compile_spec(square).meshes if m.type == "countertop"], "a square corner needs no wedge")

    def test_moldings_turn_it_as_one_piece(self):
        spec = edit.apply_op(self.spec, {"op": "set-moldings", "moldings": [m.model_dump() for m in moldings.default_moldings(True, True)], "style": "Classic"})
        chains = moldings.compute_runs(spec)
        self.assertEqual(sorted((c.molding.variant, c.wall) for c in chains), [("base", ["R2", "R1"]), ("crown", ["R2", "R1"])])
        crown = next(c for c in chains if c.molding.variant == "crown")
        cross = runs.front_cross(runs.frames(spec)["R1"], 350.0, runs.frames(spec)["R2"], 350.0)
        self.assertIn(tuple(round(v, 3) for v in cross[2]), [tuple(round(v, 3) for v in p) for p in crown.points])
        self.assertEqual(len(moldings.meshes(spec)), 2)


class TestDrawnLine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="line-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.did = self.svc.create_from_spec({"schemaVersion": 2, "name": "x", "module": []})["id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def draw(self, **extra):
        return self.svc.template(self.did, {"kind": "run-line", "a": {"x": -3000, "z": 1000}, "b": {"x": -500, "z": 1000}, "front": {"x": -1000, "z": 3000}, **extra})

    def test_a_drawn_line_becomes_a_run_of_base_cabinets_facing_the_side_asked(self):
        r = self.draw()
        self.assertEqual((r["status"], r["length"], r["run"]["yaw"]), ("ok", 2500.0, 0.0))
        self.assertTrue(r["proposal"]["applicable"])
        self.assertEqual(self.svc.store.get(self.did)[1], r["baseRev"], "a preview: nothing saved")
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        spec, _ = self.svc.store.get(self.did)
        self.assertEqual(sorted(m.width for m in spec.module), [600.0, 600.0, 600.0, 700.0])
        self.assertEqual((spec.runs[0].x, spec.runs[0].z), (-3000.0, 1000.0))
        other = self.svc.template(self.did, {"kind": "run-line", "a": {"x": -3000, "z": 4000}, "b": {"x": -500, "z": 4000}, "front": {"x": -1000, "z": 3000}})
        self.assertEqual(other["run"]["yaw"], 180.0, "the same line drawn with the front on the other side looks the other way")

    def test_a_sentence_says_what_stands_on_the_line(self):
        r = self.draw(prompt="tủ bếp có chậu rửa và bếp")
        kinds = {o["module"]["type"] for o in r["operation"]["ops"] if o["op"] == "add"}
        self.assertTrue({"base-sink", "base-cooktop"} <= kinds, kinds)

    def test_bad_lines(self):
        for bad in ({"a": {"x": 1}}, {"b": {"x": -3000, "z": 1000}}, {"front": {"x": -1000, "z": 1000}}, {"b": {"x": -2900, "z": 1000}}):
            with self.assertRaises(InvalidInput):
                self.draw(**bad)


if __name__ == "__main__":
    unittest.main()
