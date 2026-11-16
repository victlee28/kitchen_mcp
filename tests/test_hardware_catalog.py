"""Handles and hinges as catalog kinds (``handle``, ``hinge``): built-in items, and a handle named in a sentence."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import builtin, edit, edit_intent  # noqa: E402
from kitchen.spec import KitchenSpec, from_data  # noqa: E402

CAT = builtin.CATALOG


class TestKinds(unittest.TestCase):
    def test_built_in_items(self):
        self.assertEqual({it.id for it in CAT.all("handle")}, {"bar-black-160", "bar-steel-320", "knob-brass", "recessed", "push-open"})
        self.assertEqual(CAT.data("hinge", "wide-165")["openingAngle"], 165)
        self.assertIn("handle", builtin.KINDS)
        self.assertIn("hinge", builtin.KINDS)


class TestNamedHandle(unittest.TestCase):
    def setUp(self):
        self.spec = from_data(KitchenSpec, json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8")))

    def op(self, text):
        r = edit_intent.interpret_edit(self.spec, text, None)
        self.assertEqual(r["status"], "ok", text)
        return edit.apply_op(self.spec, r["operation"]).common.handle

    def test_a_catalog_handle_brings_its_settings(self):
        h = self.op("đổi tay nắm thành tay thanh inox 320")
        self.assertEqual((h.variant, h.length, h.material, h.item), ("bar", 320.0, "Inox xước", "bar-steel-320"))
        self.assertEqual(self.op("dùng tay nắm Black aluminium bar 160").item, "bar-black-160")

    def test_changing_it_by_hand_forgets_the_item(self):
        self.assertIsNone(self.op("tay nắm tay thanh inox 320 màu đen").item)
        self.assertIsNone(self.op("tay nắm màu trắng").item)


if __name__ == "__main__":
    unittest.main()
