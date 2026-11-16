"""Room doors and windows by axes (kitchen.openings, ADR 0005) and the checks of the cabinets against them (rules_openings)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import opening_fixtures as F  # noqa: E402
from kitchen import builtin, edit, geometry, openings  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402
from kitchen.intent import KitchenTemplate  # noqa: E402
from kitchen.openings import frames, wall_axes  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import KitchenSpec, to_data  # noqa: E402

TOPICS = ("doorway-width", "doorway-width-accessible", "doorway-height", "doorway-blocked", "door-interference", "cooktop-window", "window-upper")
CAT = builtin.CATALOG


def _shape(opening, axes):
    return openings.shape(opening, wall_axes.find(opening.wall_axis, axes), CAT.data("opening-type", opening.opening_type))


def _same(o):
    """What must agree whichever way an opening came in (not its id, source, unsure fields or floorplan element)."""
    d = o.to_data()
    return {k: v for k, v in d.items() if k not in ("id", "source", "unsure", "sourceElement")}


class TestWallAxes(unittest.TestCase):
    def test_collinear_edges_are_one_axis_ending_where_the_centrelines_cross(self):
        axes = wall_axes.from_floorplan(F.room())
        first = wall_axes.find("WA-wall_001", axes)
        self.assertEqual((first.start, first.dir, first.length), ((-50.0, -50.0), (1.0, 0.0), 3750.0))   # 3600 + 2 x 50 (100 mm side walls)
        self.assertEqual([g.source for g in first.segments], ["wall_001", "wall_002"])
        right = wall_axes.find("WA-wall_003", axes)
        self.assertEqual((right.start, right.length), ((3700.0, -50.0), 3100.0))                   # 200 mm wall: its centreline at x = 3700
        front = wall_axes.find("WA-wall_004", axes)
        self.assertEqual((front.start, front.dir, front.inward), ((-50.0, 3050.0), (1.0, 0.0), -1))   # runs towards +x whatever the outline order
        self.assertEqual(len(axes), 4)

    def test_default_walls_start_at_the_back_right_corner(self):
        back, right, left = wall_axes.for_room(3000, 2500, {"right": 200})
        self.assertEqual((back.start, back.dir, back.length), ((100.0, -50.0), (-1.0, 0.0), 3150.0))
        self.assertEqual((right.start, right.dir, right.inward), ((100.0, -50.0), (0.0, 1.0), 1))
        self.assertEqual((left.start, left.inward), ((-3050.0, -50.0), -1))

    def test_a_recognizer_distance_starts_at_the_inner_corner(self):
        axes = wall_axes.from_floorplan(F.room())
        first = wall_axes.find("WA-wall_001", axes)
        self.assertEqual(frames.inner_corner_s(first, axes, "start"), 50.0)
        self.assertEqual(frames.inner_corner_s(first, axes, "end"), 3650.0)     # the 200 mm wall: 100 in from the axis end
        self.assertEqual(frames.from_inner_corner(first, axes, 1000, "start"), 1050.0)
        self.assertEqual(frames.from_inner_corner(first, axes, 1000, "end"), 2650.0)

    def test_a_changed_floorplan_marks_the_opening_instead_of_moving_it(self):
        axes = wall_axes.from_floorplan(F.room())
        raw = {"id": "OP1", "kind": "door", "wallAxis": {"id": "WA-wall_001", "start": [-50, 0], "dir": [1, 0], "length": 3750},
               "center": 1500, "width": 900, "height": 2100}                  # the wall moved 50 mm across: not the same centreline
        opening, notes = openings.normalize(raw, "human", CAT, axes)
        self.assertIn("wallAxis", opening.unsure)
        self.assertTrue(any(n.startswith("opening-orphaned") for n in notes))
        self.assertEqual(opening.center, 1500)

    def test_a_wall_running_on_into_another_room_carries_its_axis(self):
        """R4: the first wall goes on west past the room's corner (x = -100 -> -2600, same thickness) and the right wall goes on south."""
        fp = F.room()
        fp["elements"] += [{"id": "wall_101", "kind": "wall", "outline": F._rect(-2600.0, -100.0, -100.0, 0.0)},
                           {"id": "wall_102", "kind": "wall", "outline": F._rect(-2700.0, -2000.0, -2600.0, 1000.0)},   # it ends against this wall
                           {"id": "wall_103", "kind": "wall", "outline": F._rect(3600.0, 3000.0, 3800.0, 5000.0)}]
        plain = {a.id: a for a in wall_axes.from_floorplan(F.room())}
        grown = {a.id: a for a in wall_axes.from_floorplan(fp)}
        first = grown["WA-wall_001"]
        self.assertEqual((first.start, first.length), ((-2650.0, -50.0), 6350.0), "starts on the centreline of the wall it runs into")
        self.assertEqual(first.segments[0].s0 - plain["WA-wall_001"].segments[0].s0, 2600.0, "the room's own stretch only moved along")
        right = grown["WA-wall_003"]
        self.assertEqual((right.start, right.length), ((3700.0, -50.0), 5050.0), "a free end: the end of the last piece")
        self.assertEqual(grown["WA-wall_004"].length, plain["WA-wall_004"].length, "a wall that stops at the corner keeps its axis")

    def test_an_opening_saved_on_the_shorter_axis_keeps_its_place(self):
        fp = F.room()
        fp["elements"].append({"id": "wall_101", "kind": "wall", "outline": F._rect(-2600.0, -100.0, -100.0, 0.0)})
        old_axis = wall_axes.find("WA-wall_001", wall_axes.from_floorplan(F.room()))
        saved, _ = openings.normalize({"id": "OP1", "kind": "door", "wallAxis": old_axis.ref().to_data(), "center": 1500, "width": 900,
                                       "height": 2100}, "human", CAT, [old_axis])
        axes = wall_axes.from_floorplan(fp)
        axis = wall_axes.find("WA-wall_001", axes)
        read, notes = openings.normalize(saved.to_data(), "human", CAT, axes, reading=True)
        self.assertEqual(axis.point(read.center), old_axis.point(1500))
        self.assertEqual(read.wall_axis, axis.ref())
        self.assertNotIn("wallAxis", read.unsure)
        self.assertTrue(any(n.startswith("opening-axis-extended") for n in notes))

    def test_a_gap_without_a_door_joins_only_walls_of_the_same_thickness(self):
        thin = F.room()
        thin["elements"].append({"id": "wall_101", "kind": "wall", "outline": F._rect(-2600.0, -100.0, -1100.0, 0.0)})   # 1000 gap, 100 thick
        thick = F.room()
        thick["elements"].append({"id": "wall_101", "kind": "wall", "outline": F._rect(-2600.0, -130.0, -1100.0, 0.0)})  # 130 thick
        self.assertEqual(wall_axes.find("WA-wall_001", wall_axes.from_floorplan(thin)).start, (-2600.0, -50.0))
        self.assertEqual(wall_axes.find("WA-wall_001", wall_axes.from_floorplan(thick)).start, (-50.0, -50.0))
        thick["elements"].append({"id": "opening_101", "kind": "opening", "outline": F._rect(-1000.0, -130.0, -200.0, 0.0)})
        self.assertEqual(wall_axes.find("WA-wall_001", wall_axes.from_floorplan(thick)).start, (-2600.0, -50.0), "a door in the gap")


class TestThreePaths(unittest.TestCase):
    """The same door read from the floorplan, from a recognition draft and from the user gives the same parameters and shape."""

    def setUp(self):
        self.axes_one = wall_axes.from_floorplan(F.room(F.door()))

    def test_one_leaf_door(self):
        fp = F.room(F.door())
        axes = wall_axes.from_floorplan(fp)
        drawn = openings.from_floorplan(fp, CAT, axes, "VN")[0]
        ai, _ = openings.normalize({"kind": "door", "openingType": "door-swing-1", "wallAxis": "WA-wall_001",
                                    "axes": [{"s": 1000.0, "confidence": 0.9}, {"s": 2000.0, "confidence": 0.9}],   # outer edges of the trims
                                    "sill": 0, "head": 2100,
                                    "leaves": [{"cols": [0, 1], "rows": [0, 1], "operation": "swing", "hinge": {"axis": "v", "index": 0},
                                                "side": "+", "active": True}]}, "ai", CAT, axes, "VN")
        spec = KitchenSpec.model_validate({"floorplan": fp})
        human = edit.apply_op(spec, {"op": "add-opening", "opening": {
            "kind": "door", "openingType": "door-swing-1", "wallAxis": "WA-wall_001", "fromEdge": {"at": "start", "distance": 1000},
            "width": 900, "height": 2100, "hinge": "left", "opens": "in"}}, CAT)
        mine = openings.effective(to_data(human), CAT, axes)[-1]
        self.assertEqual(_same(drawn), _same(ai))
        self.assertEqual(_same(ai), _same(mine))
        self.assertEqual(_shape(drawn, axes), _shape(ai, axes))
        self.assertEqual(_shape(ai, axes), _shape(mine, axes))
        self.assertEqual((drawn.center, drawn.width, drawn.clear_width), (1500.0, 900.0, 795.0))
        self.assertEqual(openings.facing(drawn.leaves[0].side, wall_axes.find("WA-wall_001", axes)), "in")

    def test_unequal_two_leaf_door(self):
        fp = F.room(F.door(width=1200, radius=870), gap=(1000.0, 2200.0))
        axes = wall_axes.from_floorplan(fp)
        drawn = openings.from_floorplan(fp, CAT, axes, "VN")[0]
        leaves = [{"cols": [0, 1], "rows": [0, 1], "operation": "swing", "hinge": {"axis": "v", "index": 0}, "side": "+", "active": True},
                  {"cols": [1, 2], "rows": [0, 1], "operation": "swing", "hinge": {"axis": "v", "index": 2}, "side": "+"}]
        ai, _ = openings.normalize({"kind": "door", "openingType": "door-swing-2-unequal", "wallAxis": "WA-wall_001", "edgesSeen": "hole",
                                    "axes": [{"s": 1050.0}, {"s": 1950.0}, {"s": 2250.0}], "sill": 0, "head": 2100, "leaves": leaves},
                                   "ai", CAT, axes, "VN")
        spec = KitchenSpec.model_validate({"floorplan": fp})
        human = edit.apply_op(spec, {"op": "add-opening", "opening": {
            "kind": "door", "openingType": "door-swing-2-unequal", "wallAxis": "WA-wall_001", "center": 1650, "width": 1200,
            "axes": [300], "height": 2100, "opens": "in"}}, CAT)
        mine = openings.effective(to_data(human), CAT, axes)[-1]
        self.assertEqual(drawn.axes, (300.0,))
        self.assertEqual(_same(drawn), _same(ai))
        self.assertEqual(_same(ai), _same(mine))
        self.assertEqual(_shape(drawn, axes), _shape(mine, axes))
        self.assertIn("leaves.1.side", drawn.unsure)          # the floorplan draws only the big leaf's arc

    def test_door_with_a_transom_from_recognition_and_from_the_user(self):
        axes = self.axes_one
        ai, _ = openings.normalize({"kind": "door", "openingType": "door-swing-1-transom", "wallAxis": "WA-wall_001", "edgesSeen": "hole",
                                    "axes": [{"s": 1050.0}, {"s": 1950.0}], "hAxes": [{"h": 2100.0}], "sill": 0, "head": 2400,
                                    "leaves": [{"cols": [0, 1], "rows": [0, 1], "operation": "swing", "hinge": {"axis": "v", "index": 0},
                                                "side": "+", "active": True}, {"cols": [0, 1], "rows": [1, 2], "operation": "fixed"}]},
                                   "ai", CAT, axes, "VN")
        mine, _ = openings.normalize({"kind": "door", "openingType": "door-swing-1-transom", "wallAxis": "WA-wall_001", "center": 1500,
                                      "width": 900, "height": 2400, "hAxes": [2100], "hinge": "left", "opens": "in"}, "human", CAT, axes)
        self.assertEqual(_same(ai), _same(mine))
        sh = _shape(mine, axes)
        self.assertEqual([b["part"] for b in sh["frame"] if b["part"].startswith("transom")], ["transom-1"])
        self.assertEqual(sh["hAxes"], [0.0, 2100.0, 2400.0])
        self.assertEqual(len(sh["sweeps"]), 1)                    # the fixed glass above does not sweep


class TestNormalize(unittest.TestCase):
    def setUp(self):
        self.axes = wall_axes.for_room(3600, 3000)

    def test_ai_sizes_snap_to_the_standard_hole_keeping_the_centre(self):
        raw = {"kind": "door", "openingType": "door-swing-1", "wallAxis": "back", "center": 1500, "width": 885, "height": 2115}
        snapped, notes = openings.normalize(raw, "ai", CAT, self.axes, "VN")
        self.assertEqual((snapped.width, snapped.height, snapped.center), (900.0, 2100.0, 1500.0))
        self.assertIn("width", notes[0].lower())
        self.assertIn("leaves.0.hinge", snapped.unsure)         # a photo seldom shows the hinge: always reviewed
        kept, _ = openings.normalize({**raw, "width": 840}, "ai", CAT, self.axes, "VN")
        self.assertEqual(kept.width, 840.0)
        self.assertIn("width", kept.unsure)
        drawn, _ = openings.normalize(raw, "drawn", CAT, self.axes, "VN")
        self.assertEqual(drawn.width, 885.0)

    def test_width_change_keeps_the_centre_and_a_template_axis_follows(self):
        a, _ = openings.normalize({"kind": "door", "openingType": "door-swing-2", "wallAxis": "back", "center": 1500, "width": 1200,
                                   "height": 2100}, "human", CAT, self.axes)
        b, _ = openings.normalize({**a.to_data(), "width": 1400}, "human", CAT, self.axes)
        self.assertEqual((b.center, b.axes), (1500.0, None))
        self.assertEqual(_shape(b, self.axes)["vAxes"], [800.0, 1500.0, 2200.0])
        c, _ = openings.normalize({**a.to_data(), "axes": [300], "width": 1400}, "human", CAT, self.axes)
        self.assertEqual(_shape(c, self.axes)["vAxes"], [800.0, 1800.0, 2200.0])   # an axis set in mm stays in mm

    def test_bad_inputs_are_refused_with_codes(self):
        base = {"kind": "door", "wallAxis": "back", "center": 1500, "width": 900, "height": 2100}
        cases = [({**base, "width": 2401}, "opening-width-out-of-range"), ({**base, "width": 12001, "oversize": True}, "opening-bad-width"),
                 ({**base, "center": 300}, "opening-outside-axis"),
                 ({**base, "wallAxis": "front"}, "opening-axis-not-found"), ({**base, "axes": [460]}, "opening-axis-outside"),
                 ({**base, "leaves": [{"cols": [0, 1], "rows": [0, 1], "operation": "swing", "hinge": {"axis": "h", "index": 1}}]}, "opening-bad-hinge"),
                 ({**base, "openingType": "door-swing-2", "leaves": [{"cols": [0, 1], "rows": [0, 1], "operation": "fixed"}]}, "opening-leaves-gap"),
                 ({**base, "openingType": "window-fixed"}, "opening-type-kind-mismatch")]
        for raw, code in cases:
            with self.subTest(code=code), self.assertRaises(InvalidInput) as caught:
                openings.normalize(raw, "human", CAT, self.axes)
            self.assertEqual(caught.exception.code, code)

    def test_hinge_left_and_right_are_seen_from_the_kitchen(self):
        def hinge(wall, hand):
            o, _ = openings.normalize({"kind": "door", "wallAxis": wall, "center": 1500, "width": 900, "height": 2100, "hinge": hand},
                                      "human", CAT, self.axes)
            return o.leaves[0].hinge.index
        # facing the back wall from the room the right wall is on your right; the back axis runs from the right corner leftwards
        self.assertEqual((hinge("back", "right"), hinge("back", "left")), (0, 1))
        # facing the right wall from the room the back wall is on your left; the axis runs away from it
        self.assertEqual((hinge("right", "left"), hinge("right", "right")), (0, 1))

    def test_the_first_axis_less_records_still_read(self):
        axes = wall_axes.from_floorplan(F.room())
        upgraded, notes = openings.normalize({"id": "OP1", "kind": "door", "openingType": "door-swing-1", "host": {"element": "WALL-FP-1"},
                                              "offset": 1000, "width": 900, "height": 2100, "hinge": "start", "swing": "in"}, "human", CAT, axes)
        self.assertEqual((upgraded.wall_axis.id, upgraded.center, upgraded.leaves[0].hinge.index, upgraded.leaves[0].side),
                         ("WA-wall_001", 1500.0, 0, "+"))
        self.assertTrue(notes)
        back, _ = openings.normalize({"id": "OP2", "kind": "window", "openingType": "window-casement-2", "host": {"wall": "back"},
                                      "offset": 100, "width": 1200, "height": 1200, "sill": 900}, "human", CAT, self.axes)
        self.assertEqual((back.wall_axis.id, back.center, back.opening_type), ("back", 750.0, "window-swing-2"))

    def test_a_clicked_point_lands_on_the_nearest_axis(self):
        o, _ = openings.normalize({"kind": "door", "point": {"x": -2000, "z": 300}, "width": 900, "height": 2100}, "human", CAT, self.axes)
        self.assertEqual((o.wall_axis.id, o.center), ("back", 2050.0))


class TestFloorplanReading(unittest.TestCase):
    def test_width_comes_from_the_wall_gap_and_a_framed_single_leaf_stays_single(self):
        fp = F.room(F.door(width=860, radius=800), gap=(1000.0, 1900.0))    # drawn 860 in a 900 gap, leaf 800 in a 900 hole
        drawn = openings.from_floorplan(fp, CAT, wall_axes.from_floorplan(fp))[0]
        self.assertEqual((drawn.width, drawn.opening_type, len(drawn.leaves)), (900.0, "door-swing-1", 1))

    def test_a_door_without_an_arc_is_unsure_and_hinge_at_the_end_opening_out(self):
        fp = F.room(F.door(radius=0))
        plain = openings.from_floorplan(fp, CAT, wall_axes.from_floorplan(fp))[0]
        self.assertIn("leaves.0.operation", plain.unsure)
        fp = F.room(F.door(hinge_at_start=False, into_room=False))
        axes = wall_axes.from_floorplan(fp)
        out = openings.from_floorplan(fp, CAT, axes)[0]
        self.assertEqual((out.leaves[0].hinge.index, openings.facing(out.leaves[0].side, axes[0])), (1, "out"))


class TestOperations(unittest.TestCase):
    def test_ids_are_monotonic_and_records_are_stored_normalized(self):
        spec = edit.apply_op(KitchenSpec(), {"op": "add-opening", "opening": {"kind": "door", "wallAxis": "back", "center": 900,
                                                                               "width": 900, "height": 2100}}, CAT)
        self.assertEqual((spec.openings[0].id, spec.openings[0].clearWidth, len(spec.openings[0].leaves)), ("OP1", 795.0, 1))
        moved = edit.apply_op(spec, {"op": "move-opening", "id": "OP1", "center": 1200}, CAT)
        self.assertEqual(moved.openings[0].center, 1200)
        removed = edit.apply_op(moved, {"op": "remove-opening", "id": "OP1"}, CAT)
        again = edit.apply_op(removed, {"op": "add-opening", "opening": {"kind": "door", "wallAxis": "back", "center": 900,
                                                                          "width": 900, "height": 2100}}, CAT)
        self.assertEqual(again.openings[0].id, "OP2")

    def test_floorplan_openings_are_overridden_removed_and_reset_by_records(self):
        fp = F.room(F.door())
        spec = KitchenSpec.model_validate({"floorplan": fp})
        axes = wall_axes.from_floorplan(fp)
        wider = edit.apply_op(spec, {"op": "update-opening", "id": "opening_001", "changes": {"width": 1000}}, CAT)
        self.assertEqual((wider.openings[0].sourceElement, wider.openings[0].width), ("opening_001", 1000))
        listed = openings.effective(to_data(wider), CAT, axes)
        self.assertEqual([(o.id, o.width, o.leaves[0].hinge.index) for o in listed], [("OP1", 1000.0, 0)])   # the drawn hinge is kept
        gone = edit.apply_op(wider, {"op": "remove-opening", "id": "opening_001"}, CAT)
        self.assertEqual(openings.effective(to_data(gone), CAT, axes), [])
        self.assertTrue(gone.openings[0].removed)
        back = edit.apply_op(gone, {"op": "reset-opening", "id": "opening_001"}, CAT)
        self.assertEqual([o.id for o in openings.effective(to_data(back), CAT, axes)], ["opening_001"])
        self.assertEqual(back.openings, [])


class TestShape(unittest.TestCase):
    def test_a_top_hung_window_sweeps_outside_and_a_sliding_door_not_at_all(self):
        axes = wall_axes.for_room(3600, 3000)
        win, _ = openings.normalize({"kind": "window", "openingType": "window-top-hung", "wallAxis": "back", "center": 1800, "width": 900},
                                    "human", CAT, axes)
        sh = _shape(win, axes)
        self.assertEqual(len(sh["sweeps"]), 1)
        self.assertTrue(all(p[1] < -50 for p in sh["sweeps"][0][2:]))          # the back wall's outside is -z
        door, _ = openings.normalize({"kind": "door", "openingType": "door-sliding-2", "wallAxis": "back", "center": 1800, "width": 1600},
                                     "human", CAT, axes)
        self.assertEqual(_shape(door, axes)["sweeps"], [])

    def test_published_schema_and_core_contract_have_the_spec_fields(self):
        from kitchen.openings import Opening as CoreOpening
        from kitchen.spec import Opening as SpecOpening
        schema = json.loads((ROOT / "schemas" / "opening.schema.json").read_text(encoding="utf-8"))
        schema.pop("$schema")
        schema.pop("$id")
        self.assertEqual(schema, SpecOpening.model_json_schema(mode="validation"))
        camel = lambda name: name.split("_")[0] + "".join(part.title() for part in name.split("_")[1:])
        self.assertEqual([camel(item.name) for item in fields(CoreOpening)], list(SpecOpening.model_fields))


class TestChecksThroughTheService(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _with(self, items):
        """A straight kitchen against a 3600 mm back wall; ``items``: (kind, distance from the right corner, width, height, sill)."""
        did = self.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3600, "fridge": True}), "t")["id"]
        spec = self.svc.get(did)["spec"]
        spec["openings"] = [{"id": f"OP{i}", "kind": kind, "openingType": "door-swing-1" if kind == "door" else "window-swing-2",
                             "wallAxis": {"id": "back"}, "center": 50 + at + width / 2, "width": width, "height": height, "sill": sill}
                            for i, (kind, at, width, height, sill) in enumerate(items, 1)]
        return self.svc.create_from_spec(spec)["id"]

    def _found(self, did, country="VN"):
        return [i for i in self.svc.validate(did, None, country)["issues"] if i.get("topic") in TOPICS]

    def test_nothing_without_openings(self):
        self.assertEqual(self._found(self._with([])), [])

    def test_a_door_behind_the_cabinets_is_a_warning_never_an_error(self):
        blocked = [i for i in self._found(self._with([("door", 1000, 900, 2100, 0)])) if i["topic"] == "doorway-blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["severity"], "warning")

    def test_a_narrow_door_and_the_wheelchair_level(self):
        narrow = self._found(self._with([("door", 10, 700, 2100, 0)]), "US")
        self.assertIn("doorway-width", {i["topic"] for i in narrow})
        wide = self._found(self._with([("door", 10, 960, 2100, 0)]), "US")
        self.assertIn("doorway-width-accessible", {i["topic"] for i in wide})        # 855 clear: over 813, under 865
        self.assertNotIn("doorway-width", {i["topic"] for i in wide})

    def test_a_window_over_the_run(self):
        topics = {i["topic"] for i in self._found(self._with([("window", 0, 1800, 1200, 1000)]))}
        self.assertTrue({"cooktop-window", "window-upper"} <= topics, topics)

    def test_service_lists_previews_and_old_records_still_open(self):
        did = self.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3600, "fridge": True}), "t")["id"]
        added = self.svc.apply(did, {"op": "add-opening", "opening": {"kind": "door", "wallAxis": "back", "center": 600, "width": 900,
                                                                      "height": 2100, "opens": "in"}}, 1)
        listed = self.svc.list_openings(did)
        self.assertEqual((listed["rev"], listed["openings"][0]["id"], listed["openings"][0]["opens"]), (added["rev"], "OP1", ["in"]))
        self.assertIn("back", {a["id"] for a in listed["wallAxes"]})
        preview = self.svc.preview_opening(did, {"kind": "door", "wallAxis": "back", "center": 600, "width": 900, "height": 2100})
        self.assertEqual((preview["opening"]["clearWidth"], len(preview["shape"]["hole"]), len(preview["shape"]["sweeps"])), (795.0, 4, 1))
        spec = self.svc.get(did)["spec"]
        spec["openings"] = [{"id": "OP1", "kind": "door", "openingType": "door-swing-1", "host": {"wall": "back"}, "offset": 100,
                             "width": 900, "height": 2100, "hinge": "start", "swing": "in", "source": "human", "unsure": []}]
        old = self.svc.create_from_spec(spec)["id"]
        self.assertEqual(self.svc.list_openings(old)["openings"][0]["center"], 600.0)
        self.assertTrue(self.svc.threejs(old)["room"]["walls"])

    def test_photo_prompt_counts_the_design_windows(self):
        from kitchen.prompts.photo import _has_window
        spec = KitchenSpec.model_validate({"openings": [{"id": "OP1", "kind": "window", "openingType": "window-fixed", "wallAxis": {"id": "back"},
                                                         "center": 1000, "width": 1200, "height": 1200, "sill": 900}]})
        self.assertTrue(_has_window(spec, CAT))
        self.assertFalse(_has_window(KitchenSpec(), CAT))


    def test_opening_type_preview_and_country_hole_sizes(self):
        data = dict(CAT.data("opening-type", "door-swing-1"))
        res = self.svc.opening_type_preview("my-door", data, "workshop", "AU")
        self.assertEqual([x["width"] for x in res["samples"]], [655.0, 755.0, 805.0, 855.0, 905.0, 955.0])
        first = res["samples"][3]
        self.assertEqual((first["clearWidth"], len(first["leaves"]), first["sweeps"]), (750.0, 1, 1))
        self.assertTrue(any(b["part"] == "head" for b in first["frame"]))
        axes = wall_axes.for_room(4000, 3000)
        us, _ = openings.normalize({"kind": "door", "wallAxis": "back", "center": 1500, "width": 820, "height": 2090}, "ai", CAT, axes, "US")
        self.assertEqual((us.width, us.height), (813.0, 2096.0))                # 32 in slab: 34 in rough opening, 82 1/2 in
        gb, _ = openings.normalize({"kind": "door", "wallAxis": "back", "center": 1500, "width": 835, "height": 2040}, "ai", CAT, axes, "GB")
        self.assertEqual((gb.width, gb.height), (828.0, 2033.0))


class TestDrawing(unittest.TestCase):
    """Slice 2: frames, leaves and glass as parts with their own masks and finishes; the walls cut around them."""

    def _straight(self, openings_data):
        from kitchen import intent
        spec = intent.from_template(intent.parse_prompt("Bếp thẳng 3m")[0])
        return KitchenSpec.model_validate({**to_data(spec), "openings": openings_data})

    def test_a_door_cuts_the_default_wall_and_has_frame_leaf_and_sweep(self):
        spec = self._straight([{"id": "OP1", "kind": "door", "openingType": "door-swing-1-transom", "wallAxis": {"id": "back"},
                                "center": 2600, "width": 900, "height": 2300}])
        scene = geometry.compile_spec(spec, CAT)
        walls = sorted((p.id, p.min[0], p.max[0], p.min[1], p.max[1]) for p in scene.parts if p.type == "wall" and p.wall == "back")
        self.assertEqual([w[0] for w in walls], ["room-wall-1-1", "room-wall-1-2", "room-wall-1-3"])
        self.assertIn((-3000.0, -2100.0), {(w[1], w[2]) for w in walls})                 # the piece over the hole
        types = sorted({m.type for m in scene.meshes if m.module == "OP1"})
        self.assertEqual(types, ["opening-frame", "opening-glass", "opening-handle", "opening-leaf", "opening-sweep"])
        from kitchen import layers
        keys = {l["materialLocked"] for l in layers.catalogue(spec, scene) if l.get("module") == "OP1" and l.get("variant") == "part"}
        self.assertEqual(keys, {"common:openingFrame", "common:openingGlass", "common:openingLeaf", "common:openingHandle", "common:floor"})
        plain = geometry.compile_spec(self._straight([]), CAT)
        self.assertIn("room-wall-1", {p.id for p in plain.parts})                      # no opening: the wall is one box as before

    def test_masks_have_the_opening_parts(self):
        import tempfile as tf
        from kitchen import render
        spec = self._straight([{"id": "OP1", "kind": "door", "wallAxis": {"id": "back"}, "center": 2900, "width": 900, "height": 2100}])
        scene = geometry.compile_spec(spec, CAT)
        view = geometry.views_of(spec, CAT)["back-wall"]
        with tf.TemporaryDirectory() as d:
            render.render_view(scene, view, Path(d), 320, 240)
            found = {i["type"] for i in json.loads((Path(d) / "instances.json").read_text(encoding="utf-8"))["instances"]}
        self.assertTrue({"opening-frame", "opening-leaf"} <= found, found)

    def test_adopting_floorplan_openings_draws_them_by_axes(self):
        from kitchen import floorplan as fpm, threejs_export
        building = json.loads((ROOT / "tests" / "data" / "floorplan-building.json").read_text(encoding="utf-8-sig"))
        spec = self._straight([])
        spec.module, spec.appliances = [], []
        spec.floorplan = fpm.normalize(building, "region:around=furniture_003")
        before = geometry.compile_spec(spec, CAT)
        self.assertIn("STRUCT-opening_002", {m.id for m in before.meshes})
        adopted = edit.apply_op(spec, {"op": "adopt-openings"}, CAT)
        self.assertEqual([(o.id, o.sourceElement) for o in adopted.openings], [("OP1", "opening_002")])
        after = geometry.compile_spec(adopted, CAT)
        self.assertNotIn("STRUCT-opening_002", {m.id for m in after.meshes})
        self.assertIn("opening-leaf", {m.type for m in after.meshes if m.module == "OP1"})
        doc = threejs_export.export(adopted)
        self.assertEqual((doc["schemaVersion"], doc["metadata"]["level"]), ("1.7.0", {"name": "1", "elevation": 0}))
        self.assertNotIn("opening_002", {s.get("sourceElement") for s in doc["room"]["structures"]})
        with self.assertRaises(InvalidInput) as caught:
            edit.apply_op(adopted, {"op": "adopt-openings"}, CAT)
        self.assertEqual(caught.exception.code, "opening-nothing-to-adopt")

    def test_a_door_on_a_floorplan_wall_leaves_a_lintel(self):
        from kitchen import floorplan as fpm
        building = json.loads((ROOT / "tests" / "data" / "floorplan-building.json").read_text(encoding="utf-8-sig"))
        spec = self._straight([])
        spec.module, spec.appliances = [], []
        spec.floorplan = fpm.normalize(building, "region:around=furniture_003")
        axes = geometry.opening_axes(spec, geometry.compile_spec(spec, CAT))
        axis = next(a for a in axes if a.id == "WA-WALL-FP-1")        # the room's west wall; its axis runs on north past the room (R4)
        middle = (axis.segments[0].s0 + axis.segments[0].s1) / 2
        door = edit.apply_op(spec, {"op": "add-opening", "opening": {"kind": "door", "wallAxis": axis.id, "center": middle,
                                                                     "width": 800, "height": 2100}}, CAT)
        wall = [m for m in geometry.compile_spec(door, CAT).meshes if m.id.startswith("STRUCT-wall_h05")]
        self.assertEqual((min(v[1] for m in wall for v in m.vertices), max(v[1] for m in wall for v in m.vertices)), (2100.0, 3000.0))


    def test_removing_a_floorplan_door_closes_its_hole(self):
        from kitchen import floorplan as fpm, threejs_export
        building = json.loads((ROOT / "tests" / "data" / "floorplan-building.json").read_text(encoding="utf-8-sig"))
        spec = self._straight([])
        spec.module, spec.appliances = [], []
        spec.floorplan = fpm.normalize(building, "region:around=furniture_003")
        gone = edit.apply_op(spec, {"op": "remove-opening", "id": "opening_002"}, CAT)
        meshes = {m.id: m for m in geometry.compile_spec(gone, CAT).meshes}
        self.assertNotIn("STRUCT-opening_002", meshes)
        self.assertEqual(meshes["STRUCT-opening_002-infill"].type, "structure-wall")
        doc = threejs_export.export(gone)
        self.assertIn("STRUCT-opening_002-infill", {s["id"] for s in doc["room"]["structures"]})
        back = edit.apply_op(gone, {"op": "reset-opening", "id": "opening_002"}, CAT)
        self.assertNotIn("STRUCT-opening_002-infill", {m.id for m in geometry.compile_spec(back, CAT).meshes})


    def test_the_camera_planner_sees_the_design_openings(self):
        spec = self._straight([{"id": "OP1", "kind": "door", "wallAxis": {"id": "right"}, "center": 1500, "width": 900, "height": 2100}])
        scene = geometry.compile_spec(spec, CAT)
        _, solids = geometry.room_solids(spec, scene)
        door = next(o for o in solids if o.id == "OP1")
        self.assertEqual((door.kind, door.y0, door.y1, len(door.outline)), ("room-opening", 0.0, 2100.0, 4))
        self.assertEqual(geometry.room_solids(self._straight([]), geometry.compile_spec(self._straight([]), CAT))[1], [])


if __name__ == "__main__":
    unittest.main()
