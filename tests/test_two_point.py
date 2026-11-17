"""Two-point perspective: eye-level cameras are level with a shifted picture; steep views keep their tilt."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kitchen import two_point  # noqa: E402
from kitchen.render import Camera  # noqa: E402
from kitchen.spec import ViewAngle  # noqa: E402


def project(cam: Camera, pt) -> tuple[float, float]:
    x, y, z = cam.to_camera(np.array([pt], float))[0]
    return cam.cx + cam.focal * x / z, cam.cy - cam.focal * y / z


class TestTwoPoint(unittest.TestCase):
    def test_level(self):
        lv = two_point.level((0, 1.6, 4), (0, 0.9, 0))
        self.assertEqual(lv.forward, (0.0, 0.0, -1.0))
        self.assertAlmostEqual(lv.shift, -0.7 / 4)
        self.assertIsNone(two_point.level((0, 6.5, 0.001), (0, 0, 0)), "the plan looks straight down")
        self.assertIsNone(two_point.level((0, 5, 5), (0, 0, 0)), "the overhead view: 45°")
        self.assertIsNone(two_point.level((1, 0, 1), (1, 2, 1)))

    def test_vertical_edges_stay_vertical_and_the_aim_stays_in_the_middle(self):
        cam = Camera(ViewAngle(position=(1.2, 1.6, 4.0), lookAt=(-0.5, 0.8, 0.3), verticalFov=50), 1280, 960)
        self.assertAlmostEqual(cam.f[1], 0.0)
        cx, cy = project(cam, (-0.5, 0.8, 0.3))
        self.assertAlmostEqual(cx, 640, places=6)
        self.assertAlmostEqual(cy, 480, places=6)
        for x, z in ((-1.0, 0.0), (0.4, -0.6), (1.5, 1.0)):     # a vertical edge: one image column from floor to ceiling
            (xa, _), (xb, _) = project(cam, (x, 0.0, z)), project(cam, (x, 2.6, z))
            self.assertAlmostEqual(xa, xb, places=6)
        self.assertLess(cam.cy, 480, "looking down: the horizon is above the middle")
        self.assertEqual(cam.json()["cy"], cam.cy)

    def test_a_plan_keeps_its_tilt(self):
        cam = Camera(ViewAngle(position=(0, 6.5, 0.001), lookAt=(0, 0, 0), verticalFov=36), 1280, 960)
        self.assertEqual((cam.cx, cam.cy), (640, 480))
        self.assertAlmostEqual(cam.f[1], -1.0, places=3)

    def test_the_threejs_camera_carries_the_shift(self):
        import tempfile
        import shutil
        from kitchen.intent import KitchenTemplate
        from kitchen.service import KitchenService
        tmp = Path(tempfile.mkdtemp())
        try:
            svc = KitchenService(tmp / "k.db", tmp / "r")
            did = svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3600}), "t")["id"]
            doc = svc.threejs(did)
            cams = {c["id"]: c for c in (doc or {}).get("cameras", [])}
            self.assertIn("twoPoint", cams["CAM-perspective"])
            self.assertGreater(cams["CAM-perspective"]["twoPoint"]["lensShiftY"], 0, "it looks down: the window moves down")
            self.assertEqual(cams["CAM-perspective"]["twoPoint"]["lookAt"]["y"], cams["CAM-perspective"]["position"]["y"])
            self.assertNotIn("twoPoint", cams["CAM-plan"])
            fov = cams["CAM-perspective"]["fov"]
            self.assertLess(cams["CAM-perspective"]["twoPoint"]["lensShiftY"], 1 / math.tan(math.radians(fov / 2)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
