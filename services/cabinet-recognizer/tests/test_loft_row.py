"""Two stacked rows of wall cabinets: rows.upperSplit gives a top (loft) row over each wall cabinet."""
import copy
import json
import unittest
from pathlib import Path

from cabinet_recognizer import pipeline
from cabinet_recognizer.errors import RecognizerError
from cabinet_recognizer.to_kitchen import to_kitchen_spec
from cabinet_recognizer.vision import ReplayClient

HERE = Path(__file__).parent
IMAGE = (HERE / "data" / "bep-chu-I-xam.png").read_bytes()
ANSWERS = json.loads((HERE / "data" / "bep-chu-I-xam.answers.json").read_text(encoding="utf-8"))


def run(split):
    answers = copy.deepcopy(ANSWERS)
    if split:
        answers["segmentation"]["rows"]["upperSplit"] = split
    return pipeline.recognize(IMAGE, ReplayClient(answers))["spec"]


class LoftRowTest(unittest.TestCase):
    def test_no_split_no_loft(self):
        self.assertFalse([m for m in run(None)["modules"] if m["storey"] == "upper-top"])

    def test_split_adds_a_loft_over_each_wall_cabinet(self):
        spec = run("H5")
        upper = [m for m in spec["modules"] if m["storey"] == "upper"]
        loft = [m for m in spec["modules"] if m["storey"] == "upper-top"]
        self.assertEqual(len(loft), len(upper))
        for low, top in zip(upper, loft):
            self.assertEqual((top["x"], top["width"]), (low["x"], low["width"]))
            self.assertEqual(top["y"], low["y"] + low["height"])
        whole = [m for m in run(None)["modules"] if m["storey"] == "upper"][0]["height"]
        self.assertEqual(upper[0]["height"] + loft[0]["height"], whole)
        self.assertEqual(spec["common"]["upperSplit"], upper[0]["y"] + upper[0]["height"])

    def test_kitchen_spec_uses_the_loft_type_and_tier_split(self):
        out = to_kitchen_spec(run("H5"))["spec"]
        self.assertTrue(any(m["type"] == "upper-loft" for m in out["module"]))
        self.assertLess(out["common"]["upperTierSplit"], out["common"]["cabinetTop"])

    def test_split_must_lie_between_the_rows(self):
        with self.assertRaises(RecognizerError):
            run("H12")


if __name__ == "__main__":
    unittest.main()
