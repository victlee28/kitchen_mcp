"""A recognised tall-fridge becomes a fridge bay: a niche, a deeper cabinet and a fridge model standing in it."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import edit  # noqa: E402
from kitchen.recognition import build_draft, build_layout, runs_from_draft  # noqa: E402
from kitchen.recognition.operation import fridge_bay  # noqa: E402
from kitchen.spec import KitchenSpec, from_data, to_data  # noqa: E402

COMMON = {"cabinetTop": 2770, "baseDepth": 550, "upperBottom": 1500, "upperTierSplit": 2770, "upperDepth": 350, "baseTop": 830}
RAW = {"modules": [{"type": "tall-fridge", "wall": "back", "width": 1010, "fromCorner": 0, "height": 830}]}


class TestFridgeBay(unittest.TestCase):
    def test_bay_fields_from_a_wide_recognised_width(self):
        m = build_draft(RAW).modules[0]
        extra, fridge = fridge_bay(m, 2770, 550)
        self.assertEqual(extra, {"niche": 1850.0, "depth": 640.0})
        self.assertEqual(fridge["dimensions"], "910 × 1800 × 620")

    def test_a_flat_draft_written_by_runs_carries_the_bay_and_the_fridge(self):
        layout = build_layout(runs_from_draft(build_draft(RAW), COMMON))
        m = layout.runs[0].modules[0]
        self.assertEqual((m["height"], m["niche"], [a["type"] for a in m["appliances"]]), (2770, 1850.0, ["fridge"]))

    def test_add_with_an_appliance_attaches_it_to_the_new_module(self):
        spec = from_data(KitchenSpec, {"schemaVersion": 2, "name": "x", "room": {"wall": [{"id": "back", "length": 3000}]}, "module": []})
        out = edit.apply_op(spec, {"op": "add", "module": {"type": "tall-fridge", "wall": "back", "fromCorner": 0, "width": 700, "y": 0, "height": 2200,
                                                          "depth": 640, "niche": 1850, "appliance": {"type": "fridge", "dimensions": "600 × 1800 × 620"}}})
        data = to_data(out)
        self.assertEqual([(a["type"], a["module"]) for a in data["appliances"]], [("fridge", data["module"][0]["id"])])


if __name__ == "__main__":
    unittest.main()
