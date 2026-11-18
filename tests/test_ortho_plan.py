"""The plan is an orthographic view (18/11/2026): drawn to scale, a cabinet the same size in the picture at any height; the overview is
the perspective camera straight down the plan used to be; the three.js document and the renderer agree on it."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import geometry, render, threejs_export  # noqa: E402
from kitchen.spec import KitchenSpec, ViewAngle  # noqa: E402

SPEC = {"module": [{"id": "TD1", "type": "base", "wall": "back", "fromCorner": 0, "width": 600, "height": 840, "depth": 580},
                   {"id": "TC1", "type": "tall", "wall": "back", "fromCorner": 600, "width": 600, "height": 2200, "depth": 580}]}


class TestOrthoCamera(unittest.TestCase):
    def test_points_at_any_depth_land_at_their_plan_position(self):
        cam = render.Camera(ViewAngle(position=(0.0, 5.0, 0.001), lookAt=(0.0, 0.0, 0.0), orthoHeight=4.0), 800, 600)
        low = cam.to_camera(np.array([[1.0, 0.0, 0.5]]))
        high = cam.to_camera(np.array([[1.0, 2.5, 0.5]]))
        (xl, yl, _), (xh, yh, _) = cam.project(low), cam.project(high)
        self.assertAlmostEqual(float(xl[0]), float(xh[0]), places=6)
        self.assertAlmostEqual(float(yl[0]), float(yh[0]), delta=0.2)     # the plan camera leans 1 mm off vertical (orbit controls)
        self.assertAlmostEqual(float(xl[0]) - 400, 150.0, places=3)           # 1 m right of the centre at 600 px / 4 m
        self.assertEqual(cam.json()["projection"], "orthographic")

    def test_the_plan_draws_a_cabinet_to_scale(self):
        spec = KitchenSpec.model_validate(SPEC)
        views = geometry.default_views(spec)
        plan, over = views["plan"], views["overhead"]
        self.assertIsNotNone(plan.orthoHeight)
        self.assertIsNone(over.orthoHeight)
        self.assertAlmostEqual(over.position[0], over.lookAt[0])
        self.assertGreater(over.position[1], 5.0)                     # the overview looks straight down from high, as the plan did
        scene = geometry.compile_spec(spec)
        with tempfile.TemporaryDirectory() as d:
            render.render_view(scene, plan, Path(d) / "plan", 640, 480)
            import json
            inst = json.loads((Path(d) / "plan" / "instances.json").read_text(encoding="utf-8"))
        tall = [i["bbox"] for i in inst["instances"] if i["module"] == "TC1"]
        x0, y0 = min(b[0] for b in tall), min(b[1] for b in tall)
        x1, y1 = max(b[2] for b in tall), max(b[3] for b in tall)
        scale = 480 / plan.orthoHeight                                 # pixels per metre
        # a 2200 mm tall cabinet seen from above covers its own footprint, 600 x 580 mm, to scale: no perspective growth of its top
        self.assertAlmostEqual(x1 - x0, 0.6 * scale, delta=2)
        self.assertAlmostEqual(y1 - y0, 0.58 * scale + 0.02 * scale, delta=4)

    def test_the_threejs_document_has_an_orthographic_plan_camera(self):
        doc = threejs_export.export(KitchenSpec.model_validate(SPEC))
        cams = {c["id"]: c for c in doc["cameras"]}
        self.assertEqual(cams["CAM-plan"]["projection"], "orthographic")
        self.assertGreater(cams["CAM-plan"]["orthoHeight"], 1000)
        self.assertNotIn("twoPoint", cams["CAM-plan"])
        self.assertEqual(cams["CAM-overhead"]["projection"], "perspective")


if __name__ == "__main__":
    unittest.main()
