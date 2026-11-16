"""Two runs joined where they meet at any angle (``run_join``): nothing pokes through a wall or into the other run, the corner is
covered by worktop."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import edit, geometry, rules, run_join, runs  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402


def two_runs(yaw_b: float) -> KitchenSpec:
    """Run R1 along z = 0 (its doors to +z) ending at x = -2200; run R2 starting there, turned so the corner between them is 180 + yaw_b."""
    mods = []
    for run, at in (("R1", 0), ("R1", 900), ("R2", 0), ("R2", 900)):
        n = len(mods) + 1
        mods.append({"id": f"TD{n}", "type": "base", "wall": "island", "run": run, "fromCorner": at, "width": 900, "y": 0, "height": 840, "depth": 600})
        mods.append({"id": f"TT{n}", "type": "upper", "wall": "island", "run": run, "fromCorner": at, "width": 900, "y": 1500, "height": 700, "depth": 350})
    return KitchenSpec.model_validate({"runs": [{"id": "R1", "x": -4000, "z": 0, "yaw": 0}, {"id": "R2", "x": -2200, "z": 0, "yaw": yaw_b}],
                                       "module": mods, "floorplan": None})


def collisions(spec: KitchenSpec) -> list[str]:
    return [i["content"] for i in rules.validate(spec)["issues"] if i["rule"] == "GEO-COLLISION"]


class TestJoin(unittest.TestCase):
    def test_any_angle_ends_with_no_overlap_and_the_corner_covered(self):
        for yaw_b, angle, wedges in ((-45, 135.0, 1), (-90, 90.0, 0), (-120, 60.0, 2), (-135, 45.0, 2)):
            with self.subTest(angle=angle):
                spec = two_runs(yaw_b)
                self.assertTrue(collisions(spec), "the runs overlap before they are joined")
                plan = run_join.plan_join(spec, "R1", "R2")
                self.assertEqual(plan["angle"], angle)
                joined = edit.apply_op(spec, plan["operation"])
                self.assertEqual(collisions(joined), [])
                tops = [m for m in geometry.compile_spec(joined).meshes if m.type == "countertop"]
                self.assertEqual(len(tops), wedges)

    def test_the_owner_keeps_the_corner_and_a_sharp_one_stops_at_the_other_wall(self):
        spec = two_runs(-120)                                            # 60 degrees
        plan = run_join.plan_join(spec, "R1", "R2")
        joined = edit.apply_op(spec, plan["operation"])
        r1_end = max(m.endAt for m in joined.module if m.run == "R1" and m.storey == "base")
        self.assertAlmostEqual(r1_end, 1800 - 620 / 3 ** 0.5, delta=1.0)   # its worktop's front corner touches R2's wall
        r2 = runs.frames(joined)["R2"]
        r1 = runs.frames(joined)["R1"]
        for m in joined.module:                                          # nothing behind the other run's wall
            other = r2 if m.run == "R1" else r1
            mine = runs.frames(joined)[m.run]
            for s, d in ((m.fromCorner, 0), (m.endAt, 0), (m.fromCorner, m.depth), (m.endAt, m.depth)):
                self.assertGreaterEqual(other.to_local(*mine.to_world(s, d))[1], -1.0, m.id)

    def test_joining_again_changes_nothing(self):
        spec = two_runs(-45)
        joined = edit.apply_op(spec, run_join.plan_join(spec, "R1", "R2")["operation"])
        self.assertIsNone(run_join.plan_join(joined, "R1", "R2")["operation"])

    def test_the_meeting_run_is_found(self):
        self.assertEqual(run_join.meeting_run(two_runs(-120), "R1"), "R2")


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.did = self.svc.create_from_spec(two_runs(-120).model_dump(mode="json"))["id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_join_from_a_clicked_cabinet(self):
        r = self.svc.template(self.did, {"kind": "join-runs", "module": "TD3"})
        self.assertEqual((r["status"], r["angle"], r["proposal"]["applicable"]), ("ok", 60.0, True))
        self.assertIn("R1", str(r["summary"][0]))


class TestJoinedMoldings(unittest.TestCase):
    def test_crown_and_plinth_turn_any_corner_as_one_piece(self):
        from kitchen import moldings
        from kitchen.spec import to_data
        for yaw_b in (-45, -90, -120, -135):
            with self.subTest(yaw=yaw_b):
                spec = two_runs(yaw_b)
                spec = edit.apply_op(spec, run_join.plan_join(spec, "R1", "R2")["operation"])
                spec = edit.apply_op(spec, {"op": "set-moldings", "moldings": [to_data(m) for m in moldings.default_moldings(True, True)], "style": "Classic"})
                chains = moldings.compute_runs(spec)
                self.assertEqual(sorted(c.molding.variant for c in chains), ["base", "crown"], "one crown and one plinth piece round the corner")
                self.assertTrue(all(len(c.wall) == 2 for c in chains))
                self.assertEqual([i for i in moldings.check(spec) if i["severity"] == "error"], [])


if __name__ == "__main__":
    unittest.main()
