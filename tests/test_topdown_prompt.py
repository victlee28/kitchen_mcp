"""A picture from above (the overview, the orthographic plan) is described from above (18/11/2026): the camera text says so, each area
is named where it lies in the image, and the eye-level description of a TV wall (which made the model paint TV units over every cabinet
block) is not used."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import prompts  # noqa: E402
from kitchen.prompts.seen import where  # noqa: E402
from test_fixes_17_11 import _design  # noqa: E402

DOWN = {"view": {"position": [2.0, 9.0, 3.001], "lookAt": [2.0, 0.0, 3.0]}}
ORTHO = {"view": {"position": [2.0, 4.0, 3.001], "lookAt": [2.0, 0.0, 3.0], "orthoHeight": 8.0}}
EYE = {"view": {"position": [0.0, 1.6, 5.0], "lookAt": [0.0, 1.2, 0.0]}}


def _instances() -> dict:
    """TV unit top left, kitchen top right, wine cabinet bottom right, a staircase in the middle (a 1000 x 750 picture)."""
    def inst(module, kind, box):
        return {"module": module, "type": kind, "pixels": (box[2] - box[0]) * (box[3] - box[1]), "bbox": box}
    return {"width": 1000, "height": 750, "instances": [
        inst("TD1", "carcass", [50, 40, 300, 80]), inst("TD2", "countertop", [650, 40, 800, 90]), inst("TT2", "carcass", [650, 40, 800, 70]),
        inst("TD3", "carcass", [700, 660, 950, 700]), inst("TT3", "carcass", [700, 660, 950, 690]),
        inst("STRUCT-stair_001", "structure-stair", [420, 300, 580, 450])]}


class TestTopDown(unittest.TestCase):
    def test_the_camera_tells_if_it_looks_down_and_if_orthographic(self):
        self.assertEqual((prompts.seen_in(_instances(), camera=DOWN).top_down, prompts.seen_in(_instances(), camera=DOWN).ortho), (True, False))
        self.assertEqual((prompts.seen_in(_instances(), camera=ORTHO).top_down, prompts.seen_in(_instances(), camera=ORTHO).ortho), (True, True))
        self.assertFalse(prompts.seen_in(_instances(), camera=EYE).top_down)

    def test_each_area_is_named_where_it_lies(self):
        scene = prompts.global_prompt(_design(), seen=prompts.seen_in(_instances(), camera=DOWN))
        self.assertIn("top-down", scene)
        self.assertIn("TV media console", scene)
        self.assertNotIn("TV niche", scene)                                  # the eye-level look of a TV wall is not used
        tv, kitchen, stair, wine = (scene.index(x) for x in ("TV media console", "kitchen run", "staircase", "wine cabinet"))
        self.assertLess(tv, kitchen)                                         # top row, left to right, then the middle, then the bottom
        self.assertLess(kitchen, stair)
        self.assertLess(stair, wine)
        self.assertIn("in the top left of the image", scene[tv:kitchen])
        self.assertIn("in the top right of the image", scene[kitchen:stair])
        self.assertIn("in the middle of the image", scene[stair:wine])
        self.assertIn("in the bottom right of the image", scene[wine:])

    def test_the_photo_text_is_shot_from_above_without_eye_level_or_led(self):
        spec = _design()
        photo = prompts.full(spec, "daylight", seen=prompts.seen_in(_instances(), camera=DOWN))
        self.assertIn("straight down on the room from above", photo)
        self.assertNotIn("eye level", photo)
        self.assertNotIn("LED", photo)
        self.assertNotIn("orthographic", photo)
        plan = prompts.full(spec, "daylight", seen=prompts.seen_in(_instances(), camera=ORTHO))
        self.assertIn("orthographic", plan)

    def test_small_cabinets_of_a_whole_room_picture_still_count(self):
        doc = {"width": 1000, "height": 1000, "instances": [{"module": "TD1", "type": "carcass", "pixels": 500, "bbox": [0, 0, 50, 10]}]}
        self.assertEqual(prompts.seen_in(doc).modules, frozenset())                       # an eye-level sliver
        self.assertEqual(prompts.seen_in(doc, camera=DOWN).modules, frozenset({"TD1"}))   # a cabinet seen from above

    def test_where(self):
        self.assertEqual(where((0, 0, 100, 100), (1000, 1000)), "in the top left of the image")
        self.assertEqual(where((450, 450, 550, 550), (1000, 1000)), "in the middle of the image")
        self.assertEqual(where((900, 450, 1000, 550), (1000, 1000)), "in the right of the image")


if __name__ == "__main__":
    unittest.main()
