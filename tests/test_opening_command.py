"""Right-click sentences about room doors and windows (``edit_intent.opening_wish``, ``openings.command``, ``service.opening_command``) and the
axes of walls outside the imported room (``wall_axes.other_axes``)."""
from __future__ import annotations

import dataclasses
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import opening_fixtures as F  # noqa: E402
from kitchen import builtin, edit_intent  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402
from kitchen.intent import KitchenTemplate  # noqa: E402
from kitchen.openings import command, normalize, wall_axes  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

CAT = builtin.CATALOG


def _rect(x0, z0, x1, z1):
    return [{"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1}, {"x": x0, "z": z1}]


def _with_next_room() -> dict:
    """The fixture room plus a wall of another room 3 m to its right (x = 6600..6800, z = 0..4000) with a 1200 mm hole drawn as an
    opening element between z = 1500 and 2700."""
    fp = F.room()
    fp["elements"] += [{"id": "wall_n1", "kind": "wall", "tag": "wall", "outline": _rect(6600.0, 0.0, 6800.0, 1500.0)},
                       {"id": "wall_n2", "kind": "wall", "tag": "wall", "outline": _rect(6600.0, 2700.0, 6800.0, 4000.0)},
                       {"id": "opening_n1", "kind": "opening", "outline": _rect(6600.0, 1500.0, 6800.0, 2700.0)}]
    return fp


class TestWish(unittest.TestCase):
    def test_reads_doors_windows_sizes_and_names(self):
        w = edit_intent.opening_wish
        self.assertEqual(w("tạo cửa đi ở vị trí này"), {"action": "make", "kind": "door", "type": None})
        self.assertEqual(w("thay bằng cửa sổ 1200x1400"), {"action": "replace", "kind": "window", "type": None, "width": 1200.0, "height": 1400.0})
        self.assertEqual(w("đặt cửa đi hai cánh có ô thoáng rộng 1600")["type"], "door-swing-2-transom")
        self.assertEqual(w("tạo cửa sổ cao 1400 rộng 1000")["height"], 1400.0)
        self.assertEqual(w("add a window")["kind"], "window")

    def test_types_named_loosely(self):
        w = edit_intent.opening_wish
        self.assertEqual(w("tạo cửa đi hai cánh")["type"], "door-swing-2")                   # label "Cửa đi hai cánh đều"
        self.assertEqual(w("đặt cửa đi 1 cánh")["type"], "door-swing-1")
        self.assertEqual(w("cửa đi 2 cánh có ô thoáng")["type"], "door-swing-2-transom")
        self.assertIsNone(w("tạo cửa đi ở vị trí này")["type"])

    def test_cabinet_doors_and_other_sentences_are_not_openings(self):
        self.assertIsNone(edit_intent.opening_wish("đổi màu cửa tủ sang trắng"))
        self.assertIsNone(edit_intent.opening_wish("thêm tủ dưới"))

    def test_save(self):
        self.assertEqual(edit_intent.opening_wish("lưu vào database"), {"action": "save", "name": None, "what": None})
        self.assertEqual(edit_intent.opening_wish("lưu cửa này vào thư viện tên Cửa nhôm đen")["name"], "Cửa nhôm đen")
        self.assertEqual(edit_intent.opening_wish("lưu hệ tủ vào database")["what"], "system")


class TestOtherAxes(unittest.TestCase):
    def test_walls_of_another_room_get_one_axis_through_the_hole(self):
        axes = wall_axes.from_floorplan(_with_next_room())
        room = wall_axes.from_floorplan(F.room())
        self.assertEqual([a.id for a in axes[:len(room)]], [a.id for a in room])          # the room's axes come first, unchanged
        other = [a for a in axes if a.inward == 0]
        self.assertEqual([(a.id, a.start, a.length, a.sources()) for a in other],
                         [("WA-wall_n1", (6700.0, 0.0), 4000.0, ("wall_n1", "wall_n2"))])

    def test_no_floorplan_wall_left_over(self):
        self.assertFalse([a for a in wall_axes.from_floorplan(F.room()) if a.inward == 0])


class TestCommand(unittest.TestCase):
    def setUp(self):
        self.fp = _with_next_room()
        self.axes = wall_axes.from_floorplan(self.fp)

    def test_a_default_door_at_the_point(self):
        op, what, facts = command.operation({"action": "make", "kind": "door", "type": None}, (2500.0, 0.0), self.axes, CAT)
        self.assertEqual((what, op["opening"]["openingType"], op["opening"]["width"], op["opening"]["height"]), ("added", "door-swing-1", 900.0, 2200.0))
        opening, _ = normalize(op["opening"], "human", CAT, self.axes)
        self.assertEqual((opening.wall_axis.id, opening.center), (self.axes[0].id, 2550.0))

    def test_the_hole_of_a_selected_element(self):
        wish = {"action": "make", "kind": "door", "type": "door-swing-2-transom"}
        op, what, facts = command.operation(wish, (6650.0, 2000.0), self.axes, CAT, (), "opening_n1", self.fp["elements"])
        self.assertEqual((what, op["opening"]["wallAxis"]["id"], op["opening"]["center"], op["opening"]["width"], op["opening"]["height"]),
                         ("hole", "WA-wall_n1", 2100.0, 1200.0, 2700.0))
        clicked, _, _ = command.operation(wish, (6610.0, 1600.0), self.axes, CAT, (), None, self.fp["elements"])
        self.assertEqual(clicked["opening"]["center"], 2100.0)                            # a click inside the hole finds it too

    def test_a_width_outside_the_type_is_asked_about(self):
        wish = {"action": "make", "kind": "door", "type": None, "width": 2000.0}
        with self.assertRaises(command.SizeQuestion) as asked:
            command.operation(wish, (2500.0, 0.0), self.axes, CAT)
        self.assertEqual((asked.exception.params["min"], asked.exception.params["max"]), (400.0, 1400.0))
        kept, _, _ = command.operation({**wish, "size": "keep"}, (2500.0, 0.0), self.axes, CAT)
        self.assertEqual((kept["opening"]["width"], kept["opening"]["oversize"]), (2000.0, True))
        fitted, _, _ = command.operation({**wish, "size": "fit"}, (2500.0, 0.0), self.axes, CAT)
        self.assertEqual((fitted["opening"]["width"], "oversize" in fitted["opening"]), (1400.0, False))
        self.assertEqual(edit_intent.opening_wish("tạo cửa đi rộng 2000 giữ nguyên khổ")["size"], "keep")
        self.assertEqual(edit_intent.opening_wish("tạo cửa đi rộng 2000 dùng khổ của mẫu")["size"], "fit")

    def test_far_from_every_wall(self):
        with self.assertRaises(InvalidInput):
            command.operation({"action": "make", "kind": "door", "type": None}, (20000.0, 9000.0), self.axes, CAT)

    def test_replacing_keeps_place_and_width(self):
        added, _ = normalize({"kind": "door", "openingType": "door-swing-1", "wallAxis": self.axes[0].ref().to_data(), "center": 2550.0,
                              "width": 900.0, "height": 2100.0}, "human", CAT, self.axes)
        added = dataclasses.replace(added, id="OP1")
        op, what, facts = command.operation({"action": "replace", "kind": "window", "type": None}, (2550.0, 0.0), self.axes, CAT, (added,))
        self.assertEqual(op["op"], "update-opening")
        self.assertEqual({k: op["changes"][k] for k in ("kind", "openingType", "width", "height", "sill")},
                         {"kind": "window", "openingType": "window-swing-2", "width": 900.0, "height": 1200.0, "sill": 900.0})

    def test_the_opening_a_hole_stands_for(self):
        self.fp["elements"][-1].update(tag="door", label="Cửa trượt sau", elev={"base": 0.0, "height": 2400.0})
        found = command.hole_opening((6650.0, 2000.0), self.axes, CAT, None, self.fp["elements"])
        self.assertIsNotNone(found)
        opening, label = found
        self.assertEqual((opening.opening_type, opening.width, opening.height, opening.center, label),
                         ("door-sliding-2", 1200.0, 2400.0, 2100.0, "Cửa trượt sau"))
        self.assertIsNone(command.hole_opening((2500.0, 0.0), self.axes, CAT, None, self.fp["elements"]))

    def test_saved_type(self):
        opening, _ = normalize({"kind": "door", "openingType": "door-swing-2-transom", "wallAxis": self.axes[0].ref().to_data(), "center": 2600.0,
                                "width": 1600.0, "height": 2700.0}, "human", CAT, self.axes)
        item = command.saved_type(opening, CAT.data("opening-type", "door-swing-2-transom"), "Cửa nhôm đen")
        self.assertEqual((item["label"], item["defaultWidth"], item["defaultHeight"], item["kind"]),
                         ({"vi": "Cửa nhôm đen", "en": "Cửa nhôm đen"}, 1600.0, 2700.0, "door"))
        self.assertNotIn("sources", item)


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        did = self.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3600}), "t")["id"]
        spec = self.svc.get(did)["spec"]
        self.did = self.svc.create_from_spec(spec)["id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_make_save_and_use_again(self):
        self.assertEqual(self.svc.opening_command(self.did, "đổi màu cửa tủ", {"point": {"x": -1000, "z": -50}}, "user")["status"], "not-opening")
        made = self.svc.opening_command(self.did, "tạo cửa đi hai cánh có ô thoáng rộng 1600", {"point": {"x": -1500, "z": -50}}, "user")
        self.assertEqual((made["status"], made["proposal"]["applicable"]), ("ok", True))
        self.svc.apply(self.did, made["operation"], made["baseRev"])
        saved = self.svc.opening_command(self.did, "lưu cửa này vào database tên Cửa nhôm đen", {"point": {"x": -1500, "z": -50}}, "user")
        self.assertEqual((saved["status"], saved["item"]["id"]), ("saved", "cua-nhom-den"))
        again = self.svc.opening_command(self.did, "tạo cửa nhôm đen", {"point": {"x": -3300, "z": -50}}, "user")
        self.assertEqual((again["operation"]["opening"]["openingType"], again["operation"]["opening"]["width"]), ("cua-nhom-den", 1600.0))

    def test_nothing_to_save(self):
        self.assertEqual(self.svc.opening_command(self.did, "lưu vào database", {"point": {"x": -1500, "z": 1500}}, "user")["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
