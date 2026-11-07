import json
import math
import unittest
from pathlib import Path

from cabinet_recognizer import contract_persp, persp
from cabinet_recognizer.errors import RecognizerError
from cabinet_recognizer.pipeline import recognize_auto
from cabinet_recognizer.vision import ReplayClient

HERE = Path(__file__).parent
CASES = ["bep-chu-L-trang", "u-frontal-render"]


def run_case(name):
    answers = json.loads((HERE / "data" / f"{name}.answers.json").read_text(encoding="utf-8"))
    client = ReplayClient(answers)
    spec = recognize_auto((HERE / "data" / f"{name}.png").read_bytes(), client)["spec"]
    return spec, client


class GoldenTest(unittest.TestCase):
    def test_cases_match_golden(self):
        for name in CASES:
            with self.subTest(name=name):
                spec, _ = run_case(name)
                golden = json.loads((HERE / "golden" / f"{name}.spec.json").read_text(encoding="utf-8"))
                self.assertEqual(spec, golden)

    def test_widths_and_doors_consistent(self):
        for name in CASES:
            spec, _ = run_case(name)
            for m in spec["modules"]:
                if "doors" in m:
                    self.assertEqual(sum(m["doors"]) + m.get("blindWidth", 0), m["width"], m["id"])


class SyntheticUTruthTest(unittest.TestCase):
    """Ảnh U dựng bằng three.js (camera ngang tầm 1450, fov dọc 55°): so với số thật."""

    def test_u_shape_within_tolerance(self):
        spec, client = run_case("u-frontal-render")
        self.assertEqual(client.calls, ["scene", "run-back", "run-left", "run-right", "policy"])
        truth = {  # (wall, storey) -> mép module tính từ góc trong
            ("back", "base"): [0, 900, 1700, 2300, 2700, 3600],
            ("left", "base"): [600, 1200, 1800, 2400],
            ("right", "base"): [600, 1300, 2200],
            ("back", "upper"): [0, 800, 1700, 2300, 3000, 3600],
        }
        for (wall, storey), edges in truth.items():
            mods = sorted((m for m in spec["modules"] if m["wall"] == wall and
                           (m["storey"] == storey or (storey == "base" and m["storey"] == "tall"))),
                          key=lambda m: m["x"])
            got = [mods[0]["x"]] + [m["x"] + m["width"] for m in mods]
            self.assertEqual(len(got), len(edges), (wall, storey))
            for g, t in zip(got, edges):
                self.assertLessEqual(abs(g - t), 0.04 * 3600, (wall, storey, got, edges))
        cam = spec["evidence"]["camera"]
        self.assertEqual(cam["focalSource"], "reference-consistency")
        self.assertAlmostEqual(cam["focalPx"], 450 / math.tan(math.radians(27.5)), delta=0.04 * 864)
        self.assertAlmostEqual(spec["evidence"]["cameraHeightMm"], 1450, delta=0.06 * 1450)


class GeometryTest(unittest.TestCase):
    def test_vanishing_point_of_converging_lines(self):
        vp = persp.vanishing_point([(0.5, -100.0), (-0.25, 650.0), (0.1, 300.0 - 0.1 * 1000 + 0.1 * 1000 - 0.1 * 1000 + 100)])
        self.assertTrue(vp.finite)
        self.assertAlmostEqual(vp.u, 1000, delta=1)
        self.assertAlmostEqual(vp.v, 400, delta=1)

    def test_parallel_lines_are_infinite(self):
        self.assertFalse(persp.vanishing_point([(0.0, 10.0), (0.0005, 50.0)]).finite)

    def test_camera_roundtrip(self):
        vb = persp.VanishingPoint(True, -2600.0, 430.0, 0.0, 0.0)
        vs = persp.VanishingPoint(True, 930.0, 430.0, 0.0, 0.0)
        f = persp.focal_from_vps(vb, vs, 612.0, 434.0)
        cam = persp.build_camera(vb, vs, f, 612.0, 434.0)
        p = cam.on_floor(500.0, 700.0)
        u, v = cam.project(p)
        self.assertAlmostEqual(u, 500.0, places=6)
        self.assertAlmostEqual(v, 700.0, places=6)
        q = cam.on_plane(500.0, 600.0, "z", p[2])
        self.assertAlmostEqual(q[2], p[2], places=9)


class SceneContractTest(unittest.TestCase):
    def test_u_shape_needs_three_walls(self):
        base = json.loads((HERE / "data" / "u-frontal-render.answers.json").read_text(encoding="utf-8"))["scene"]
        bad = {**base, "runs": base["runs"][:2]}
        with self.assertRaises(RecognizerError) as cm:
            contract_persp.parse_scene(bad)
        self.assertEqual(cm.exception.code, "layout-walls")


if __name__ == "__main__":
    unittest.main()


class InboxTest(unittest.TestCase):
    def test_inbox_pauses_then_resumes(self):
        import tempfile
        from cabinet_recognizer.vision import InboxClient
        name = "bep-chu-L-trang"
        answers = json.loads((HERE / "data" / f"{name}.answers.json").read_text(encoding="utf-8"))
        image = (HERE / "data" / f"{name}.png").read_bytes()
        with tempfile.TemporaryDirectory() as d:
            box = Path(d)
            (box / "answers").mkdir()
            for step in ["scene", "run-back", "run-left", "policy"]:
                with self.assertRaises(RecognizerError) as cm:
                    recognize_auto(image, InboxClient(d))
                self.assertEqual(cm.exception.code, "awaiting-answer")
                self.assertTrue((box / "pending" / step / "prompt.txt").exists())
                (box / "answers" / f"{step}.json").write_text(json.dumps(answers[step]), encoding="utf-8")
            spec = recognize_auto(image, InboxClient(d))["spec"]
            golden = json.loads((HERE / "golden" / f"{name}.spec.json").read_text(encoding="utf-8"))
            self.assertEqual(spec, golden)


class WebInboxTest(unittest.TestCase):
    def test_job_waits_then_finishes(self):
        import tempfile
        from datetime import datetime
        from cabinet_recognizer import web_inbox
        answers = json.loads((HERE / "data" / "bep-chu-L-trang.answers.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as d:
            job = web_inbox.create_job(Path(d), (HERE / "data" / "bep-chu-L-trang.png").read_bytes(),
                                       "bếp chữ L", "VN", datetime(2026, 11, 7, 16, 0, 0))
            self.assertEqual(job.name, "20261107-160000")
            for step in ["scene", "run-back", "run-left", "policy"]:
                st = web_inbox.run_job(job)
                self.assertEqual((st["state"], st["step"]), ("waiting", step))
                self.assertIn("User notes", (job / "inbox" / "pending" / step / "prompt.txt").read_text(encoding="utf-8"))
                (job / "inbox" / "answers" / f"{step}.json").write_text(json.dumps(answers[step]), encoding="utf-8")
            st = web_inbox.run_job(job)
            self.assertEqual(st["state"], "done")
            self.assertEqual(st["modules"], 28)
