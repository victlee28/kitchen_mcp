"""The recogniser against what is known of its test photos (tests/data/truth): the limits it must stay within."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from cabinet_recognizer.accuracy import compare  # noqa: E402
import measure_accuracy  # noqa: E402

LIMITS = {"worstEdgeShare": 0.05, "worstLengthShare": 0.07}       # of the run; today's results: U render 4.4 %, L photo 6.3 %


class AccuracyTest(unittest.TestCase):
    def test_every_case_with_a_truth_file_stays_within_the_limits(self):
        cases = sorted((ROOT / "tests" / "data" / "truth").glob("*.truth.json"))
        self.assertGreaterEqual(len(cases), 2)
        for path in cases:
            truth = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(case=truth["case"]):
                report = compare(measure_accuracy.run(truth["case"], measure_accuracy.DATA), truth)
                for key, limit in LIMITS.items():
                    self.assertLessEqual(report["summary"][key], limit, (key, report))
                self.assertFalse(any(e.get("error") for e in report["edges"].values()), report["edges"])

    def test_compare_reads_edges_lengths_heights_and_angles(self):
        spec = {"modules": [{"wall": "back", "storey": "base", "x": 0, "width": 610}, {"wall": "back", "storey": "tall", "x": 610, "width": 600}],
                "walls": {"back": {"runLength": 1210}, "left": {"runLength": 900, "angleDeg": 97.0}}, "common": {"worktopTop": 880}}
        truth = {"case": "t", "edges": {"back/base": [0, 600, 1200]}, "lengths": {"back": 1200}, "heights": {"worktopTop": 900},
                 "angles": {"left": 95}}
        r = compare(spec, truth)
        self.assertEqual(r["edges"]["back/base"], {"maxMm": 10.0, "meanMm": 6.7})
        self.assertEqual(r["heights"]["worktopTop"]["errorMm"], 20.0)
        self.assertEqual(r["angles"]["left"]["errorDeg"], 2.0)
        self.assertEqual(r["summary"]["worstEdgeMm"], 10.0)


if __name__ == "__main__":
    unittest.main()
