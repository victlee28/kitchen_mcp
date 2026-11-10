"""Rules and drawing look at ROWS (a wall's row or an explicit run), not at walls: an appliance of a run stands in that run, and
cabinets of two runs are never neighbours."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import edit, geometry, rules, run_line, runs  # noqa: E402
from kitchen.recognition import build_layout  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402


def base(kind, s, width, **extra):
    return {"type": kind, "s": s, "width": width, "y": 0, "height": 840, "depth": 600, **extra}


def kitchen(back, left=None, room=None):
    """A recognised kitchen placed with no edge picked: ``back`` (and ``left``) are lists of recognised cabinets."""
    doc = {"schema": "recognized-runs/1", "runs": [], "joints": []}
    if left:
        doc["runs"].append({"id": "left", "length": max(m["s"] + m["width"] for m in left), "modules": left})
        doc["joints"].append({"a": "left", "b": "back", "angle": 90})
    doc["runs"].append({"id": "back", "length": max(m["s"] + m["width"] for m in back), "modules": back})
    layout = build_layout(doc)
    assert layout is not None and not layout.rejected, layout
    found = [{"id": r.id, "length": r.length, "modules": list(r.modules)} for r in layout.runs]
    spec = KitchenSpec.model_validate({"room": room} if room else {})
    return edit.apply_op(spec, run_line.plan_runs(spec, run_line.back_wall_line(spec, found), found, list(layout.joints))["operation"])


def codes(spec):
    return {(i["rule"], tuple(i["module"])) for i in rules.validate(spec)["issues"]}


SINK = {"appliances": [{"type": "sink", "name": "Chậu"}, {"type": "faucet", "name": "Vòi"}]}
HOB = {"appliances": [{"type": "cooktop", "name": "Bếp"}]}


class TestSpot(unittest.TestCase):
    def test_an_appliance_of_a_run_stands_in_the_middle_of_its_module(self):
        spec = kitchen([base("base", 0, 600), base("base-sink", 600, 800, **SINK)])
        sink = next(t for t in spec.appliances if t.type == "sink")
        at = runs.spot(spec, sink)
        self.assertEqual((at.row, at.center, sink.wall), (f"run:{spec.runs[0].id}", 1000.0, None))
        self.assertEqual(sink.dimensions, "760 × 430", "a stock size, as a new kitchen gets: a photo gives none")

    def test_a_stored_centre_along_the_run_is_kept_whatever_wall_it_names(self):
        spec = kitchen([base("base", 0, 600), base("base-sink", 600, 800)])
        host = spec.module[1]
        data = spec.model_dump(mode="json")
        data["appliances"] = [{"id": "TB1", "type": "sink", "module": host.id, "wall": "back", "center": 900, "dimensions": "500 × 430"}]
        at = runs.spot(KitchenSpec.model_validate(data), KitchenSpec.model_validate(data).appliances[0])
        self.assertEqual((at.row, at.center), (f"run:{host.run}", 900.0))

    def test_on_a_wall_nothing_changes(self):
        spec = KitchenSpec.model_validate({"module": [{"id": "TD1", "type": "base-sink", "wall": "right", "fromCorner": 600, "width": 800, "y": 0, "height": 840, "depth": 600}],
                                           "appliances": [{"id": "TB1", "type": "sink", "wall": "right", "center": 950, "dimensions": "700 × 430"},
                                                          {"id": "TB2", "type": "other", "name": "?"}]})
        self.assertEqual(runs.spot(spec, spec.appliances[0]), runs.Spot("right", 950.0, None))
        self.assertIsNone(runs.spot(spec, spec.appliances[1]))
        self.assertEqual(runs.row_of(spec.module[0]), "right")


class TestDrawn(unittest.TestCase):
    def test_sink_tap_and_hob_of_a_recognised_kitchen_are_drawn_on_their_cabinets(self):
        spec = kitchen([base("base-sink", 0, 800, **SINK), base("base", 800, 900), base("base-cooktop", 1700, 800, **HOB)],
                       left=[base("base", 0, 600), base("base", 600, 600)])
        scene = geometry.compile_spec(spec)
        for tb in spec.appliances:
            with self.subTest(appliance=tb.type):
                part = next(p for p in scene.parts if p.module == tb.id)
                host = next(p for p in scene.parts if p.module == tb.module and p.type == "carcass")
                self.assertTrue(host.min[0] - 1 <= part.min[0] and part.max[0] <= host.max[0] + 1, "within the width of its cabinet")
                self.assertGreaterEqual(part.min[1], spec.common.countertop - 1)


class TestRules(unittest.TestCase):
    def test_a_sink_beside_the_hob_in_the_same_run_is_reported(self):
        spec = kitchen([base("base-sink", 0, 800, **SINK), base("base-cooktop", 800, 800, **HOB), base("base", 1600, 600)])
        sink, hob = (next(t.id for t in spec.appliances if t.type == k) for k in ("sink", "cooktop"))
        self.assertIn(("SAFETY-001", (sink, hob)), codes(spec))

    def test_a_sink_and_a_hob_in_two_runs_are_not_neighbours(self):
        spec = kitchen([base("base", 0, 600), base("base-cooktop", 600, 800, **HOB), base("base", 1400, 900)],
                       left=[base("base", 0, 900), base("base-sink", 900, 800, **SINK), base("base", 1700, 600)])
        self.assertFalse([c for c in codes(spec) if c[0] == "SAFETY-001"])

    def test_the_worktop_beside_a_sink_is_measured_in_its_own_run(self):
        tight = kitchen([base("base", 0, 300), base("base-sink", 300, 800, **SINK), base("base", 1100, 300)],
                        left=[base("base", 0, 900), base("base", 900, 900)])
        sink = next(t.id for t in tight.appliances if t.type == "sink")
        self.assertIn(("NKBA-10", (sink,)), codes(tight))
        roomy = kitchen([base("base", 0, 900), base("base-sink", 900, 800, **SINK), base("base", 1700, 900)])
        self.assertFalse([c for c in codes(roomy) if c[0] == "NKBA-10"])

    def test_the_worktop_beside_the_fridge_is_that_of_its_run_only(self):
        spec = kitchen([{"type": "tall-fridge", "s": 0, "width": 800, "y": 0, "height": 2300, "depth": 600}, base("base", 800, 900), base("base", 1700, 900)],
                       left=[base("base", 0, 600), base("base", 600, 600), base("base", 1200, 600)])
        self.assertFalse([c for c in codes(spec) if c[0] == "NKBA-14"], "1800 mm of worktop beside it; the other run must not hide it")

    def test_a_run_reaching_out_of_the_room_is_an_error(self):
        mods = [base("base", 0, 900), base("base", 900, 900), base("base", 1800, 900)]
        inside = kitchen(mods, room={"wall": [{"id": "back", "length": 3000}, {"id": "right", "length": 3000}]})
        self.assertFalse([c for c in codes(inside) if c[0] == "GEO-WALL"])
        data = inside.model_dump(mode="json")
        data["runs"][0]["x"] = -3400
        out = {c for c in codes(KitchenSpec.model_validate(data)) if c[0] == "GEO-WALL"}
        self.assertEqual(len(out), 1, "only the cabinet that sticks out of the back wall's length")

    def test_the_work_triangle_is_measured_where_the_runs_really_stand(self):
        from kitchen import rules_kb
        spec = kitchen([base("base-cooktop", 0, 800, **HOB), base("base", 800, 2000)], left=[base("base", 0, 600), base("base-sink", 600, 800, **SINK)])
        left = next(r for r in spec.runs if r.yaw == 90.0)
        x, z = rules_kb._plan_point(spec, f"run:{left.id}", 1000.0, 300.0)
        self.assertEqual((round(x), round(z)), (round(left.x + 300.0), round(left.z - 1000.0)))


class TestEdit(unittest.TestCase):
    def test_removing_a_cabinet_closes_the_gap_in_its_run_only_and_the_sink_follows_its_cabinet(self):
        spec = kitchen([base("base", 0, 600), base("base-sink", 600, 800, **SINK), base("base", 1400, 600)],
                       left=[base("base", 0, 600), base("base", 600, 600)])
        back = next(r.id for r in spec.runs if r.yaw == 0.0)
        first = min((m for m in spec.module if m.run == back), key=lambda m: m.fromCorner)
        other = {m.id: m.fromCorner for m in spec.module if m.run != back}
        after = edit.apply_op(spec, {"op": "remove", "id": first.id})
        self.assertEqual(sorted(m.fromCorner for m in after.module if m.run == back), [0.0, 800.0])
        self.assertEqual({m.id: m.fromCorner for m in after.module if m.run != back}, other, "the other run does not move")
        sink = next(t for t in after.appliances if t.type == "sink")
        self.assertEqual(runs.spot(after, sink).center, 400.0)
        part = next(p for p in geometry.compile_spec(after).parts if p.module == sink.id)
        host = next(p for p in geometry.compile_spec(after).parts if p.module == sink.module and p.type == "carcass")
        self.assertTrue(host.min[0] - 1 <= part.min[0] and part.max[0] <= host.max[0] + 1)


if __name__ == "__main__":
    unittest.main()
