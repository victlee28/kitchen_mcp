"""Tủ cao ở đường v0.1 (không có sections) cao đến đỉnh dãy tủ, không phải 830 của thân tủ dưới."""
import unittest
from pathlib import Path
import json

JOB = Path(__file__).resolve().parents[1] / "jobs" / "20261109-161009" / "kitchen-spec.json"


class TallHeightTest(unittest.TestCase):
    @unittest.skipUnless(JOB.exists(), "job mẫu không có")
    def test_tall_fridge_reaches_cabinet_top(self):
        spec = json.loads(JOB.read_text(encoding="utf-8"))
        tall = [m for m in spec["module"] if m["type"].startswith("tall")]
        self.assertTrue(tall)
        for m in tall:
            self.assertEqual((m["y"], m["height"]), (0, spec["common"]["cabinetTop"]))


if __name__ == "__main__":
    unittest.main()
