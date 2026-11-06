import unittest

from kitchen import edit, edit_intent
from kitchen.spec import KitchenSpec, from_data


def _spec() -> KitchenSpec:
    common = {"material": {"base": "Trắng"}}
    mods = [
        {"id": "TD1", "type": "base", "wall": "back", "fromCorner": 0, "width": 600, "height": 840, "depth": 550, "y": 0},
        {"id": "TD2", "type": "base", "wall": "back", "fromCorner": 600, "width": 600, "height": 840, "depth": 550, "y": 0},
        {"id": "TT1", "type": "upper", "wall": "back", "fromCorner": 0, "width": 600, "height": 720, "depth": 320, "y": 1530},
    ]
    return from_data(KitchenSpec, {"name": "t", "common": common, "module": mods})


class EditIntentTests(unittest.TestCase):
    def setUp(self):
        self.spec = _spec()

    def run_ok(self, text, scope=None):
        r = edit_intent.interpret_edit(self.spec, text, scope)
        self.assertEqual(r["status"], "ok", r)
        return r

    def test_remove_by_id_applies(self):
        r = self.run_ok("xóa tủ TD2")
        self.assertEqual(r["operation"], {"op": "remove", "id": "TD2"})
        self.assertEqual([m.id for m in edit.apply_op(self.spec, r["operation"]).module], ["TD1", "TT1"])

    def test_remove_uses_selection_when_text_names_none(self):
        r = self.run_ok("bỏ tủ này", scope=["TD1"])
        self.assertEqual(r["operation"]["id"], "TD1")

    def test_remove_without_target_asks(self):
        r = edit_intent.interpret_edit(self.spec, "xóa tủ")
        self.assertEqual(r["status"], "clarify")
        self.assertIn("TD1", r["choices"])

    def test_width_units(self):
        self.assertEqual(self.run_ok("TD1 rộng 80cm")["operation"]["changes"], {"width": 800.0})
        self.assertEqual(self.run_ok("đổi độ rộng TD1 thành 750")["operation"]["changes"], {"width": 750.0})

    def test_add_needs_width_and_anchor(self):
        self.assertEqual(edit_intent.interpret_edit(self.spec, "thêm tủ ngăn kéo sau TD1")["status"], "clarify")
        self.assertEqual(edit_intent.interpret_edit(self.spec, "thêm tủ ngăn kéo rộng 600")["status"], "clarify")
        r = self.run_ok("thêm tủ ngăn kéo rộng 600 sau TD1")
        self.assertEqual(r["operation"], {"op": "add", "module": {"type": "base-drawers", "width": 600.0}, "afterModule": "TD1"})
        self.assertEqual(len(edit.apply_op(self.spec, r["operation"]).module), 4)

    def test_add_other_storey_asks(self):
        self.assertEqual(edit_intent.interpret_edit(self.spec, "thêm tủ cao rộng 600 sau TD1")["status"], "clarify")

    def test_door_style_by_storey(self):
        r = self.run_ok("đổi cánh kính cho tủ trên")
        self.assertEqual(r["operation"], {"op": "update", "id": "TT1", "changes": {"doorStyle": "glass"}})

    def test_handle_common_and_module(self):
        r = self.run_ok("tay nắm âm")
        self.assertEqual(r["operation"]["changes"]["handle"]["variant"], "concealed")
        r = self.run_ok("tay nắm núm cho TD1")
        self.assertEqual(r["operation"]["changes"], {"handle": {"variant": "knob"}})

    def test_color_slot(self):
        r = self.run_ok("mặt bàn màu đen")
        self.assertEqual(r["operation"]["changes"]["material"]["countertop"], "Đá đen")
        self.assertEqual(r["operation"]["changes"]["material"]["base"], "Trắng")
        self.assertEqual(edit_intent.interpret_edit(self.spec, "đổi sang màu xanh rêu")["status"], "clarify")

    def test_multi_clause(self):
        r = self.run_ok("xóa TD2, tay nắm núm")
        self.assertEqual(r["operation"]["op"], "multi")

    def test_unknown_and_empty(self):
        self.assertEqual(edit_intent.interpret_edit(self.spec, "hôm nay trời đẹp")["status"], "unsupported")
        self.assertEqual(edit_intent.interpret_edit(self.spec, "  ")["status"], "unsupported")

    def test_check_operation_blocks_replace(self):
        self.assertEqual(edit_intent.check_operation({"op": "replace", "spec": {}})["status"], "unsupported")
        self.assertEqual(edit_intent.check_operation({"op": "remove", "id": "TD1"})["status"], "ok")
        self.assertEqual(edit_intent.check_operation({"op": "multi", "ops": [{"op": "multi", "ops": []}]})["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
