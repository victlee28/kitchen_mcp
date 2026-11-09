"""A tall unit found in the base band is a tall module reaching the top of the wall cabinets (not the 830 base body)."""
import copy
import json
import unittest
from pathlib import Path

from cabinet_recognizer import pipeline
from cabinet_recognizer.vision import ReplayClient

HERE = Path(__file__).parent
IMAGE = (HERE / "data" / "bep-chu-I-xam.png").read_bytes()
ANSWERS = json.loads((HERE / "data" / "bep-chu-I-xam.answers.json").read_text(encoding="utf-8"))


class TallV01Test(unittest.TestCase):
    def test_tall_fridge_reaches_the_top_of_the_wall_cabinets(self):
        answers = copy.deepcopy(ANSWERS)
        answers["segmentation"]["base"]["modules"][-1]["type"] = "tall-fridge"
        spec = pipeline.recognize(IMAGE, ReplayClient(answers))["spec"]
        tall = [m for m in spec["modules"] if m["type"] == "tall-fridge"]
        self.assertEqual([(m["storey"], m["y"], m["height"]) for m in tall], [("tall", 0, spec["common"]["upperTop"])])


if __name__ == "__main__":
    unittest.main()
