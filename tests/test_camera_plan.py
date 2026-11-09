"""Automatic camera views: eye height 1.6 m, inside the room, solids in front of the cabinets hidden."""
import unittest

from kitchen import camera_plan, geometry
from kitchen.camera_plan import Face, Obstacle
from kitchen.spec import KitchenSpec

ROOM = [(-4000.0, 0.0), (0.0, 0.0), (0.0, 3500.0), (-4000.0, 3500.0)]
BACK = Face("back-wall", "Back wall", (-1500.0, 600.0), (0.0, 1.0), 3000.0, 2200.0)
TABLE = Obstacle("STRUCT-T1", "furniture", ((-2200.0, 1500.0), (-800.0, 1500.0), (-800.0, 2100.0), (-2200.0, 2100.0)), 0.0, 750.0)


class TestCameraPlan(unittest.TestCase):
    def test_eye_height_and_inside_room(self):
        views = camera_plan.plan_views([BACK], ROOM, [])
        self.assertEqual({"back-wall", "back-wall-oblique"}, set(views))
        for v in views.values():
            self.assertAlmostEqual(1.6, v["position"][1])
            self.assertTrue(camera_plan.stands_in_room((v["position"][0] * 1000, v["position"][2] * 1000), ROOM))
            self.assertTrue(40 <= v["verticalFov"] <= 78)

    def test_blocking_table_is_hidden_or_avoided(self):
        views = camera_plan.plan_views([BACK], ROOM, [TABLE])
        # a table 0.75 m high is below the 1.6 m eye line, so it cannot hide the upper part but may hide the base row: either avoided or listed
        for v in views.values():
            self.assertTrue(set(v["hide"]) <= {"STRUCT-T1"})

    def test_hidden_for_lists_wall_between_camera_and_cabinets(self):
        wall = Obstacle("STRUCT-W1", "wall", ((-4000.0, 2000.0), (0.0, 2000.0), (0.0, 2100.0), (-4000.0, 2100.0)), 0.0, 2600.0)
        self.assertEqual(["STRUCT-W1"], camera_plan.hidden_for((-1.5, 1.6, 3.0), [BACK], [wall]))
        self.assertEqual([], camera_plan.hidden_for((-1.5, 1.6, 1.5), [BACK], [wall]))


class TestDefaultViews(unittest.TestCase):
    def test_legacy_keys_kept_and_eye_height(self):
        spec = KitchenSpec.model_validate({"module": [{"id": "A", "type": "base", "wall": "back", "width": 600, "fromCorner": 0, "height": 720, "depth": 560}]})
        views = geometry.default_views(spec)
        for key in ("perspective", "overhead", "plan", "back-wall"):
            self.assertIn(key, views)
        self.assertAlmostEqual(1.6, views["back-wall"].position[1])


if __name__ == "__main__":
    unittest.main()
