"""The answered recognition jobs of tests/data/openings/cases.json, replayed with tools/measure_openings.py (proposal P5): what is right
may only grow."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("measure_openings", ROOT / "tools" / "measure_openings.py")
assert spec is not None and spec.loader is not None
mo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mo)

CASES = json.loads((ROOT / "tests" / "data" / "openings" / "cases.json").read_text(encoding="utf-8"))
BASELINE = json.loads((ROOT / "tests" / "data" / "openings" / "baseline.json").read_text(encoding="utf-8"))


class TestOpeningCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = mo.measure(CASES["cases"])

    def test_every_case_has_its_picture_and_answers(self):
        for case in CASES["cases"]:
            with self.subTest(case=case["case"]):
                self.assertTrue((mo.DATA / f"{case['case']}.png").exists())
                self.assertTrue((mo.DATA / f"{case['case']}.answers.json").exists())
                for want in case["expect"]:
                    self.assertTrue(want.get("source"), "say how the truth is known")

    def test_no_worse_than_the_baseline(self):
        t = self.result["total"]
        for key in ("typeRight", "leavesRight", "transomPanesRight", "handlesRight"):
            with self.subTest(key=key):
                self.assertGreaterEqual(t[key], BASELINE[key], self.result["rows"])
        self.assertEqual(t["dividerCountWrong"], 0, self.result["rows"])
        self.assertLessEqual(t["worstDividerErr"], BASELINE["worstDividerErr"], self.result["rows"])

    def test_compare_tells_wrong_from_right(self):
        from kitchen.recognition.opening_match import seen_features
        got = {"run": "photo", "type": "door-sliding-2", "features": seen_features("door", "sliding", 2, False), "axesRatio": [0.5], "hAxesRatio": []}
        row = mo.compare({"kind": "door", "type": "door-sliding-4", "style": "sliding", "leaves": 4, "axesRatio": [0.25, 0.5, 0.75]}, got)
        self.assertEqual((row["typeRight"], row["leavesRight"], row["axesErr"]), (False, False, "count"))
        self.assertEqual(mo.compare({"kind": "door", "type": "x"}, None), {"found": False, "typeRight": False})


if __name__ == "__main__":
    unittest.main()
