"""An inner corner that is not square is measured (from the width references on both runs), not assumed to be 90 degrees."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import synthetic_room as sr  # noqa: E402

from cabinet_recognizer import compute_persp, contract_persp, to_runs  # noqa: E402


def build(angle):
    k = sr.l_kitchen(angle)
    runs = [contract_persp.parse_run(k["answers"][w], w, k["meas"]["runs"][w]["cand"]) for w in ("back", "left")]
    return k, compute_persp.build_spec_p(k["scene"], k["meas"], runs, contract_persp.parse_policy_p(k["policy"]), [], None)


class CornerAngleTest(unittest.TestCase):
    def test_a_square_corner_stays_square(self):
        _, spec = build(90)
        self.assertEqual(spec["evidence"]["camera"]["focalSource"], "vanishing-points")
        self.assertNotIn("angleDeg", spec["walls"]["left"])
        self.assertNotIn("corner-not-square", [w["code"] for w in spec["warnings"]])

    def test_an_open_or_tight_corner_is_measured(self):
        for angle in (80, 100, 110):
            with self.subTest(angle=angle):
                k, spec = build(angle)
                self.assertEqual(spec["evidence"]["camera"]["focalSource"], "reference-consistency-angle")
                self.assertAlmostEqual(spec["walls"]["left"]["angleDeg"], angle, delta=2.0)
                self.assertIn("corner-not-square", [w["code"] for w in spec["warnings"]])
                for wall in ("back", "left"):
                    got = [m["width"] for m in spec["modules"] if m["wall"] == wall and m["storey"] == "base"]
                    self.assertEqual(len(got), len(k["truth"][wall]))
                    for g, t in zip(got, k["truth"][wall]):
                        self.assertAlmostEqual(g, t, delta=25, msg=wall)

    def test_the_runs_document_carries_the_angle(self):
        _, spec = build(100)
        doc = to_runs.to_runs(spec)
        (joint,) = doc["joints"]
        self.assertEqual((joint["a"], joint["b"]), ("left", "back"))
        self.assertAlmostEqual(joint["angle"], 100, delta=2.0)
        self.assertEqual(to_runs.check_runs(doc), [])


if __name__ == "__main__":
    unittest.main()


class FreeRunTest(unittest.TestCase):
    """A run standing free (an island), parallel to the back run: measured from its own floor line, placed against the back run."""

    def test_the_island_is_found_where_it_stands(self):
        k = sr.l_kitchen(90, (1700.0, [1000.0, 1600.0, 2200.0, 2800.0]))
        walls = [r["wall"] for r in k["scene"]["runs"]]
        runs = [contract_persp.parse_run(k["answers"][w], w, k["meas"]["runs"][w]["cand"]) for w in walls]
        spec = compute_persp.build_spec_p(k["scene"], k["meas"], runs, contract_persp.parse_policy_p(k["policy"]), [], None)
        self.assertAlmostEqual(spec["walls"]["island"]["offsetMm"], 1700, delta=30)
        island = [m for m in spec["modules"] if m["wall"] == "island"]
        self.assertEqual([(m["x"], m["width"]) for m in island], [(1000, 600), (1600, 600), (2200, 600)])
        doc = to_runs.to_runs(spec)
        run = next(r for r in doc["runs"] if r["id"] == "island")
        self.assertEqual(run["free"]["from"], "back")
        self.assertEqual(run["free"]["s"], 1000, "where it starts along the back run")
        self.assertEqual([m["s"] for m in run["modules"]], [0, 600, 1200])
        self.assertEqual([j for j in doc["joints"] if "island" in (j["a"], j["b"])], [], "it meets no other run")
        self.assertEqual(to_runs.check_runs(doc), [])

    def test_the_scene_may_name_one_free_run(self):
        line = [[0.1, 0.5], [0.9, 0.52]]
        run = {"end": "open", "box": {"left": 0, "right": 1, "top": 0, "bottom": 1},
               "lines": {"upperBottom": line, "worktopFront": line, "frontsBottom": line, "plinthBottom": line}}
        scene = contract_persp.parse_scene({"layout": "straight", "view": "perspective",
                                            "runs": [{**run, "wall": "island"}, {**run, "wall": "back"}]})
        self.assertEqual([r["wall"] for r in scene["runs"]], ["back", "island"])


class PeninsulaTest(unittest.TestCase):
    """A peninsula: a run with no wall behind it, perpendicular to a run and touching it. Either a side run standing in the room (it leaves the
    back run, seen from its side) or a free run parallel to the back run whose end touches a side run."""

    def _spec(self, k):
        walls = [r["wall"] for r in k["scene"]["runs"]]
        runs = [contract_persp.parse_run(k["answers"][w], w, k["meas"]["runs"][w]["cand"]) for w in walls]
        return compute_persp.build_spec_p(k["scene"], k["meas"], runs, contract_persp.parse_policy_p(k["policy"]), [], None)

    def test_a_side_run_standing_in_the_room(self):
        k = sr.l_kitchen(90)
        k["scene"]["runs"][1]["peninsula"] = True
        spec = self._spec(k)
        self.assertIs(spec["walls"]["left"]["peninsula"], True)
        doc = to_runs.to_runs(spec)
        left = next(r for r in doc["runs"] if r["id"] == "left")
        self.assertIs(left["peninsula"], True)
        self.assertNotIn("peninsula", next(r for r in doc["runs"] if r["id"] == "back"))
        self.assertEqual([(j["a"], j["b"]) for j in doc["joints"]], [("left", "back")], "it still meets the back run")
        self.assertEqual(to_runs.check_runs(doc), [])

    def test_a_free_run_touching_a_side_run(self):
        k = sr.l_kitchen(90, (1700.0, [600.0, 1200.0, 1800.0, 2400.0]))
        k["scene"]["runs"][2]["touches"] = "left"
        spec = self._spec(k)
        self.assertEqual(spec["walls"]["island"]["touches"], "left")
        doc = to_runs.to_runs(spec)
        island = next(r for r in doc["runs"] if r["id"] == "island")
        self.assertEqual(island["free"]["touches"], "left")
        self.assertAlmostEqual(island["free"]["s"], 600, delta=20, msg="it starts at the left run's front")
        self.assertEqual(to_runs.check_runs(doc), [])

    def test_the_scene_says_which_run(self):
        line = [[0.1, 0.5], [0.9, 0.52]]
        run = {"end": "open", "box": {"left": 0, "right": 1, "top": 0, "bottom": 1},
               "lines": {"upperBottom": line, "worktopFront": line, "frontsBottom": line, "plinthBottom": line}}
        scene = contract_persp.parse_scene({"layout": "l-shape", "view": "perspective",
                                            "runs": [{**run, "wall": "back"}, {**run, "wall": "right", "peninsula": True},
                                                     {**run, "wall": "island", "touches": "right"}]})
        self.assertEqual([(r["wall"], r.get("peninsula"), r.get("touches")) for r in scene["runs"]],
                         [("back", None, None), ("right", True, None), ("island", None, "right")])
        with self.assertRaises(Exception):
            contract_persp.parse_scene({"layout": "straight", "view": "perspective",
                                        "runs": [{**run, "wall": "back"}, {**run, "wall": "island", "touches": "left"}]})
        scene = contract_persp.parse_scene({"layout": "straight", "view": "perspective",
                                            "runs": [{**run, "wall": "back", "peninsula": True}]})
        self.assertNotIn("peninsula", scene["runs"][0], "only a side run can be a peninsula")
