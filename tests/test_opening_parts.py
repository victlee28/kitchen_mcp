"""Room doors and windows: their handles (``openings.shape._handles``), a camera view per opening (``geometry.opening_views``) and the
image layers of each opening (``layers.catalogue``)."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import builtin, geometry, layers  # noqa: E402
from kitchen.intent import KitchenTemplate  # noqa: E402
from kitchen.openings import normalize, wall_axes  # noqa: E402
from kitchen.openings.shape import shape  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402

CAT = builtin.CATALOG
AXES = wall_axes.for_room(3600, 2400)


def opening(kind, type_id, **more):
    o, _ = normalize({"kind": kind, "openingType": type_id, "wallAxis": AXES[0].ref().to_data(), "center": 1500, "width": 900,
                      "height": 2100, **more}, "human", CAT, AXES)
    return o, shape(o, AXES[0], CAT.data("opening-type", type_id))


class TestHandles(unittest.TestCase):
    def test_a_swing_door_has_a_lever_on_both_faces_away_from_the_hinge(self):
        o, sh = opening("door", "door-swing-1")
        (leaf,) = sh["leaves"]
        parts = {h["part"]: h for h in sh["handles"]}
        self.assertEqual(sorted(parts), ["lever-back", "lever-front", "rose-back", "rose-front"])
        rose = parts["rose-front"]
        far_end = leaf["s1"] if leaf["hingeS"] == leaf["s0"] else leaf["s0"]
        self.assertAlmostEqual(abs((rose["s0"] + rose["s1"]) / 2 - far_end), 70, delta=0.5, msg="70 mm from the edge away from the hinge")
        self.assertAlmostEqual((rose["y0"] + rose["y1"]) / 2, 1000, delta=0.5, msg="1000 mm above the floor")
        self.assertGreaterEqual(parts["lever-front"]["d0"], leaf["d1"])
        self.assertLessEqual(parts["lever-back"]["d1"], leaf["d0"])

    def test_sliding_pull_window_lever_and_none(self):
        _, sliding = opening("door", "door-sliding-2", width=1600)
        self.assertTrue(sliding["handles"] and all(h["part"].startswith("pull") for h in sliding["handles"]))
        _, window = opening("window", "window-swing-2", width=1200, height=1200, sill=900)
        mids = {round((h["y0"] + h["y1"]) / 2) for h in window["handles"] if h["part"].startswith("rose")}
        self.assertEqual(mids, {round(900 + 1200 / 2)}, "a window handle in the middle of its leaf")
        _, fixed = opening("window", "window-fixed", width=1200, height=1200, sill=900)
        self.assertEqual(fixed["handles"], [])
        _, passage = opening("passage", "passage")
        self.assertEqual(passage["handles"], [])

    def test_the_opening_type_says_how(self):
        data = {**CAT.data("opening-type", "door-swing-1"), "handle": {"kind": "none"}}
        o, _ = opening("door", "door-swing-1")
        self.assertEqual(shape(o, AXES[0], data)["handles"], [])
        data = {**CAT.data("opening-type", "door-swing-1"), "handle": {"kind": "lever", "height": 1100, "inset": 90}}
        rose = next(h for h in shape(o, AXES[0], data)["handles"] if h["part"] == "rose-front")
        self.assertAlmostEqual((rose["y0"] + rose["y1"]) / 2, 1100, delta=0.5)


class TestFourPanelSliding(unittest.TestCase):
    def test_the_sentence_names_the_sliding_type_not_the_folding_one(self):
        from kitchen.edit_intent import opening_wish
        for text, want in (("tạo cửa trượt 4 cánh", "door-sliding-4"), ("tạo cửa lùa bốn cánh", "door-sliding-4"),
                           ("tạo cửa trượt 2 cánh", "door-sliding-2"), ("tạo cửa xếp 4 cánh", "door-folding-4")):
            self.assertEqual((opening_wish(text) or {}).get("type"), want, text)

    def test_four_leaves_on_two_rails_with_pulls_on_the_middle_two(self):
        o, sh = opening("door", "door-sliding-4", width=3920, center=2000)
        leaves = sh["leaves"]
        self.assertEqual(len(leaves), 4)
        pulls = [h for h in sh["handles"] if h["part"] == "pull-front"]
        self.assertEqual(sorted(h["leaf"] for h in pulls), [1, 2], "only the two middle leaves have a pull (handle.leaves)")
        for h in pulls:                                   # at the edge where the middle leaves meet
            self.assertLess(abs((h["s0"] + h["s1"]) / 2 - o.center), 65)
        outer, middle = {leaves[0]["d0"], leaves[3]["d0"]}, {leaves[1]["d0"], leaves[2]["d0"]}
        self.assertEqual((len(outer), len(middle)), (1, 1))
        self.assertGreaterEqual(abs(next(iter(outer)) - next(iter(middle))), 40, "the outer and middle leaves on two rails, one behind the other")
        self.assertGreater(leaves[0]["s1"], leaves[1]["s0"], "leaves on different rails overlap where they meet")
        self.assertLessEqual(leaves[1]["s1"], leaves[2]["s0"], "the two middle leaves on one rail meet, not overlap")

    def test_a_glass_leaf_has_a_frame_and_a_pane(self):
        o, sh = opening("door", "door-sliding-2", width=1600)
        parts = [p for p in sh["leafParts"] if p["leaf"] == 0]
        self.assertEqual(sorted(p["part"] for p in parts), ["pane", "rail-bottom", "rail-top", "stile-end", "stile-start"])
        stile = next(p for p in parts if p["part"] == "stile-start")
        self.assertAlmostEqual(stile["s1"] - stile["s0"], 45)
        from kitchen.openings.meshes import meshes
        types = {m.type for m in meshes(o, AXES[0], CAT.data("opening-type", "door-sliding-2"))}
        self.assertTrue({"opening-leaf-frame", "opening-glass"} <= types)
        self.assertNotIn("opening-leaf", types, "the framed leaf is drawn as its frame and pane, not as one solid")
        _, swing = opening("door", "door-swing-1")
        self.assertEqual(swing["leafParts"], [], "a solid door leaf has no frame of its own")


class TestViewsAndLayers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "r")
        self.did = self.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3600}), "t")["id"]
        made = self.svc.opening_command(self.did, "tạo cửa đi", {"point": {"x": 50, "z": 1500}}, "user", 1)
        self.svc.apply(self.did, made["operation"], 1, "t")
        self.spec = KitchenSpec.model_validate(self.svc.get(self.did)["spec"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_each_opening_has_its_own_square_on_view_from_the_kitchen_side(self):
        views = geometry.default_views(self.spec)
        v = views["opening-OP1"]
        self.assertEqual(v.name, "Cửa OP1")
        self.assertLess(v.position[0], v.lookAt[0], "the door is in the right wall (x = 0): the camera stands in the kitchen (x < 0)")
        self.assertAlmostEqual(v.position[2], v.lookAt[2], places=3, msg="square-on")
        door = next(o for o in self.spec.openings if o.id == "OP1")
        self.assertAlmostEqual(v.lookAt[1], (door.sill + door.height / 2) / 1000, places=3, msg="looking at the middle of the door")
        self.assertGreaterEqual(v.lookAt[0] - v.position[0], 1.2)
        self.assertNotIn("opening-OP1", geometry.default_views(KitchenSpec.model_validate(self.svc.get(self.did, 1)["spec"])))

    def test_each_opening_has_layers_for_its_leaves_frame_handles_and_the_whole(self):
        sc = geometry.compile_spec(self.spec)
        cat = {x["id"]: x for x in layers.catalogue(self.spec, sc)}
        for gid in ("leaves:OP1", "frame:OP1", "handle:OP1", "module:OP1"):
            self.assertIn(gid, cat)
        handles = cat["handle:OP1"]
        self.assertEqual((handles["name"], handles["materialLocked"], handles["material"]),
                         ("tay nắm cửa OP1", "common:openingHandle", "Tay nắm cửa inox mờ"))
        self.assertTrue(all(cat[i]["type"] == "opening-handle" for i in handles["component"]))
        self.assertEqual(set(cat["module:OP1"]["component"]) >= set(handles["component"]) | set(cat["frame:OP1"]["component"]), True)
        op, _ = layers.design_op(self.spec, handles, "Tay nắm đồng", sc)
        self.assertEqual(op["changes"]["material"]["openingHandle"], "Tay nắm đồng")


if __name__ == "__main__":
    unittest.main()
