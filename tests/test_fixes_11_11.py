"""Fixes of 11/11/2026: a laid-again system keeps the appliance models picked before and its corner shelf; its fridge cabinet stays deep
enough; "họng" (a gas burner) is not "hồng" (pink)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import appliance_models, system_replace as sr, vocab  # noqa: E402

SINK = {"type": "base-sink", "width": 800.0, "s": 600.0, "y": 0.0, "height": 840.0, "depth": 580.0,
        "appliances": [{"type": "sink", "name": "Chậu", "dimensions": "760 × 430", "center": 1000.0}]}
PLAIN = {"type": "base", "width": 450.0, "s": 1400.0, "y": 0.0, "height": 840.0, "depth": 580.0}
LEFT = {"type": "base", "width": 600.0, "s": 0.0, "y": 0.0, "height": 840.0, "depth": 580.0}
UPPER = {"type": "upper", "width": 800.0, "s": 600.0, "y": 1530.0, "height": 700.0, "depth": 320.0}
DOUBLE = appliance_models.BY_ID["sink-double-82"]


class TestKeepModels(unittest.TestCase):
    def test_the_sink_cabinet_takes_the_room_its_kept_model_needs_from_a_plain_neighbour(self):
        out = sr._make_room([LEFT, SINK, UPPER, PLAIN], {"sink": DOUBLE})
        sink = next(m for m in out if m["type"] == "base-sink")
        right = next(m for m in out if m["s"] >= 1400)
        self.assertEqual((sink["s"], sink["width"]), (600.0, appliance_models.needed_width(DOUBLE)))
        self.assertEqual(right["s"] + right["width"], 1850.0)                      # the run keeps its length
        self.assertAlmostEqual(sink["appliances"][0]["center"], 1000.0 + (sink["width"] - 800.0) / 2)

    def test_a_kept_model_replaces_the_default_device(self):
        notes: list[str] = []
        d = sr._keep_device(SINK["appliances"][0], {"sink": DOUBLE}, 830.0, notes)
        self.assertEqual(d["model"], "sink-double-82")
        self.assertEqual(notes, [f"{DOUBLE['name']} kept"])
        d = sr._keep_device(SINK["appliances"][0], {"sink": DOUBLE}, 800.0, notes)
        self.assertNotIn("model", d)

    def test_the_sentence_naming_the_appliance_asks_for_a_new_one(self):
        from kitchen.spec import KitchenSpec
        spec = KitchenSpec.model_validate({"module": [{"id": "TD1", "type": "base-sink", "wall": "back", "width": 830, "height": 840, "depth": 580}],
                                           "appliances": [{"id": "TB1", "type": "sink", "module": "TD1", "model": "sink-double-82"}]})
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
