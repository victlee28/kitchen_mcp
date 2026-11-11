"""Fixes of 11/11/2026: a laid-again system keeps the appliance models picked before and its corner shelf; its fridge cabinet stays deep
enough; "họng" (a gas burner) is not "hồng" (pink)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import appliance_models, edit, system_replace as sr, vocab  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402

SINK = {"type": "base-sink", "width": 800.0, "s": 600.0, "y": 0.0, "height": 840.0, "depth": 580.0,
        "appliances": [{"type": "sink", "name": "Chậu", "dimensions": "760 × 430", "center": 1000.0}]}
PLAIN = {"type": "base", "width": 450.0, "s": 1400.0, "y": 0.0, "height": 840.0, "depth": 580.0}
LEFT = {"type": "base", "width": 600.0, "s": 0.0, "y": 0.0, "height": 840.0, "depth": 580.0}
DOUBLE = appliance_models.BY_ID["sink-double-82"]


def _run_spec() -> KitchenSpec:
    return KitchenSpec.model_validate({
        "runs": [{"id": "R1", "x": 0, "z": 0, "yaw": 0}],
        "module": [{"id": "TD1", "type": "base", "wall": "island", "run": "R1", "fromCorner": 0, "width": 600, "height": 840, "depth": 580},
                   {"id": "TD2", "type": "base-sink", "wall": "island", "run": "R1", "fromCorner": 600, "width": 830, "height": 840, "depth": 580},
                   {"id": "TD3", "type": "base", "wall": "island", "run": "R1", "fromCorner": 1430, "width": 420, "height": 840, "depth": 580}],
        "appliances": [{"id": "TB1", "type": "sink", "module": "TD2", "model": "sink-double-82", "dimensions": "820 × 450"}]})


class TestKeepModels(unittest.TestCase):
    def test_laid_again_the_system_keeps_the_double_sink_and_makes_room_for_it(self):
        spec = _run_spec()
        mods = list(spec.module)
        ops, summary = sr.relayout_ops(spec, mods, {"R1": [LEFT, SINK, PLAIN]}, {}, models=sr.kept_models(spec, mods, "thêm tủ nóc"))
        after = edit.apply_op(spec, edit.combine_ops(ops))
        sink = next(m for m in after.module if m.type == "base-sink")
        self.assertEqual(sink.width, appliance_models.needed_width(DOUBLE))                  # 800 laid out, 830 for the double sink
        self.assertEqual(max(m.endAt for m in after.module), 1850.0)                        # taken from the plain cabinet next to it
        self.assertEqual(next(a for a in after.appliances if a.type == "sink").model, "sink-double-82")
        self.assertIn(f"{DOUBLE['name']} kept", summary)

    def test_the_sentence_naming_the_appliance_asks_for_a_new_one(self):
        spec = _run_spec()
        mods = list(spec.module)
        self.assertIn("sink", sr.kept_models(spec, mods, "thêm tủ nóc"))
        self.assertNotIn("sink", sr.kept_models(spec, mods, "đổi sang chậu đơn"))


class TestVocab(unittest.TestCase):
    def test_hong_with_its_own_diacritics(self):
        self.assertEqual(vocab.to_english("Bếp gas âm 2 họng 75 cm"), "")
        self.assertIsNone(vocab.color("2 họng"))
        self.assertEqual(vocab.to_english("Sơn hồng phấn"), "pink painted")
        self.assertEqual(vocab.to_english("mau hong"), "pink")                     # typed without diacritics: still pink
        self.assertEqual(vocab.to_english("xanh luc"), "green")


if __name__ == "__main__":
    unittest.main()
