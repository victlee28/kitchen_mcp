import base64
"""Doors and windows seen with a recognised kitchen (plan R10): carried on its runs, placed on the design's wall axes, previewed in the same
operation as the cabinets, drawn once applied."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import builtin, geometry, openings, recognition, run_line  # noqa: E402
from kitchen.recognition import openings as seen_openings  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from test_floorplan import ROOM, plan  # noqa: E402

DATA = ROOT / "tests" / "data" / "recognized_runs"
PNG = "iVBORw0KGgo="
WINDOW = {"id": "CS1", "kind": "window", "axes": [{"s": 300, "confidence": 0.9}, {"s": 750, "confidence": 0.9}, {"s": 1200, "confidence": 0.9}],
          "sill": 1000, "head": 2100, "edgesSeen": "hole", "style": "swing", "leaves": 2, "confidence": 0.9}
DOOR = {"id": "CS2", "kind": "door", "axes": [{"s": 1000, "confidence": 0.9}, {"s": 1900, "confidence": 0.3}], "sill": 0, "head": 2100,
        "edgesSeen": "hole", "style": "swing", "leaves": 1, "confidence": 0.9}


def l_shape(with_openings=True):
    doc = json.loads((DATA / "l-shape.json").read_text(encoding="utf-8"))["runs"]
    if with_openings:
        runs = {r["id"]: r for r in doc["runs"]}
        runs["back"]["openings"] = [copy.deepcopy(WINDOW)]
        runs["left"]["openings"] = [copy.deepcopy(DOOR)]
    return doc


class Fake:
    def __init__(self, raw):
        self.raw = raw

    def recognize(self, source):
        return copy.deepcopy(self.raw)


def by_runs(doc):
    flat = [{"type": m["type"], "wall": "back", "width": m["width"], "fromCorner": m["s"]} for r in doc["runs"] for m in r["modules"]]
    return {"modules": flat, "layout": doc}


class TestRead(unittest.TestCase):
    def test_openings_are_checked(self):
        doc = l_shape()
        doc["runs"][0]["openings"] += [{"kind": "gate", "axes": []}, {"kind": "door", "axes": [{"s": 5}]}, "x"]
        found, rejected = seen_openings.read(doc)
        self.assertEqual(sorted(o.run for o in found), ["back", "left"])
        self.assertEqual(len(rejected), 3)
        self.assertEqual(seen_openings.read({"runs": []}), ([], []))
        self.assertEqual(seen_openings.read(None), ([], []))

    def test_types_follow_what_was_seen(self):
        def t(kind, style="swing", leaves=1, h=()):
            return seen_openings.opening_type(seen_openings.SeenOpening("back", kind, ((0, 1), (900, 1)), None, None, h, "hole", style, leaves, 1.0),
                                              builtin.CATALOG)
        self.assertEqual([t("door"), t("door", leaves=2), t("door", h=((2100, 1),)), t("door", "sliding", 2), t("door", "folding", 4)],
                         ["door-swing-1", "door-swing-2", "door-swing-1-transom", "door-sliding-2", "door-folding-4"])
        self.assertEqual([t("window", "fixed"), t("window", "sliding", 2), t("window", "top-hung"), t("window", leaves=2), t("window", h=((1700, 1),)), t("passage", "none", 0)],
                         ["window-fixed", "window-sliding-2", "window-top-hung", "window-swing-2", "window-swing-2-top", "passage"])
        for kind in ("door", "window", "passage"):
            self.assertIn(t(kind), builtin.CATALOG.ids("opening-type"))

    def test_a_flat_draft_mirrors_its_openings_like_its_cabinets(self):
        got = seen_openings.flat_to_runs([{"wall": "back", "kind": "door", "axes": [{"fromCorner": 100}, {"fromCorner": 1000}]},
                                          {"wall": "right", "kind": "window", "axes": [{"fromCorner": 100}, {"fromCorner": 1000}]},
                                          {"wall": "left", "kind": "door", "axes": []}], {"back": 3000, "right": 2000})
        self.assertEqual([a["s"] for a in got["back"][0]["axes"]], [2900, 2000])
        self.assertEqual([a["s"] for a in got["right"][0]["axes"]], [100, 1000])
        self.assertNotIn("left", got, "no run on that wall: nothing to measure from")


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="recog-open-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.recognizers.clear()
        self.src = {"kind": "photo", "imageBase64": PNG, "name": "a.png"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def design(self, data=None):
        did = self.svc.create_from_spec(data or {})["id"]
        return did

    def recognize(self, did, raw):
        self.svc.recognizers["fake"] = Fake(raw)
        return self.svc.recognize(did, self.src, "fake")

    def apply(self, did, r):
        self.svc.apply(did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        return self.svc.store.get(did)[0]

    def test_the_cabinets_and_the_openings_are_one_previewed_operation(self):
        did = self.design()
        r = self.recognize(did, by_runs(l_shape()))
        self.assertEqual(r["status"], "ok")
        ops = r["operation"]["ops"]
        adds = [o["opening"] for o in ops if o["op"] == "add-opening"]
        self.assertEqual([(o["kind"], o["wallAxis"]["id"], o["openingType"]) for o in adds],
                         [("door", "left", "door-swing-1"), ("window", "back", "window-swing-2")])    # in the order of the runs
        self.assertEqual(ops.index(next(o for o in ops if o["op"] == "add-opening")), len(ops) - 2, "the openings come after the cabinets")
        self.assertTrue(r["proposal"]["applicable"])
        self.assertEqual(len(self.svc.history(did)), 1, "nothing saved before the user confirms")

    def test_applied_openings_stand_where_the_photo_showed_them(self):
        did = self.design()
        spec = self.apply(did, self.recognize(did, by_runs(l_shape())))
        scene = geometry.compile_spec(spec)
        axes = geometry.opening_axes(spec, scene)
        got = {o.kind: o for o in openings.effective(spec.model_dump(mode="json", exclude_none=True), builtin.CATALOG, axes, spec.country)}
        back = next(a for a in axes if a.id == "back")
        left = next(a for a in axes if a.id == "left")
        # the back run stands on z = 0 from x = -lsau (its s = 0) to the right; the back axis runs -x from x = +50
        win = got["window"]
        self.assertEqual((win.source, win.sill, win.height), ("ai", 1000.0, 1100.0))
        self.assertAlmostEqual(win.center, back.s_of((-scene.lsau + 750, 0.0)), delta=1)
        self.assertAlmostEqual(win.width, 900, delta=1)
        self.assertEqual(win.axes, (0.0,), "the middle axis seen in the photo")
        # the left run stands on x = -lsau, its s = 0 at the room end (z = 2130), growing towards the corner
        door = got["door"]
        self.assertAlmostEqual(door.center, left.s_of((-scene.lsau, 2130 - 1450)), delta=1)
        self.assertIn("width", door.unsure, "an edge seen with low confidence")
        drawn = {m.type for m in scene.meshes}
        self.assertTrue({"opening-frame", "opening-leaf", "opening-glass"} <= drawn, drawn)

    def test_recognising_again_does_not_double_the_openings(self):
        did = self.design()
        self.apply(did, self.recognize(did, by_runs(l_shape())))
        r = self.recognize(did, by_runs(l_shape()))
        self.assertFalse([o for o in r["operation"]["ops"] if o["op"] == "add-opening"])
        self.assertEqual(sum("opening-already-there" in str(s) for s in r["summary"]), 2)

    def test_a_flat_draft_brings_its_openings_too(self):
        did = self.design()
        raw = {"modules": [{"type": "base", "wall": "back", "width": 600, "fromCorner": 0}, {"type": "base", "wall": "back", "width": 600, "fromCorner": 600}],
               "openings": [{"kind": "window", "wall": "back", "axes": [{"fromCorner": 200}, {"fromCorner": 1100}], "sill": 1000, "head": 2200}]}
        r = self.recognize(did, raw)
        adds = [o["opening"] for o in r["operation"]["ops"] if o["op"] == "add-opening"]
        self.assertEqual(len(adds), 1)
        spec = self.apply(did, r)
        self.assertEqual(len(spec.openings), 1)

    def test_bad_openings_leave_the_cabinets_alone(self):
        did = self.design()
        doc = l_shape()
        doc["runs"][1]["openings"] = [{"kind": "window", "axes": [{"s": 100}, {"s": 9000}], "sill": 1000, "head": 2100}]   # far too wide
        r = self.recognize(did, by_runs(doc))
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len([o for o in r["operation"]["ops"] if o["op"] == "add-opening"]), 1)
        self.assertTrue(any("opening-not-placed" in str(s) for s in r["summary"]))
        self.assertTrue(r["proposal"]["applicable"])

    def test_without_openings_the_operation_is_as_before(self):
        did = self.design()
        r = self.recognize(did, by_runs(l_shape(with_openings=False)))
        self.assertFalse([o for o in r["operation"]["ops"] if o["op"] == "add-opening"])

    def test_on_a_floorplan_the_openings_are_stored_in_the_room_frame(self):
        did = self.svc.import_floorplan(plan(ROOM))["id"]
        r = self.recognize(did, by_runs(l_shape()))
        self.assertEqual(r["status"], "ok")
        adds = [o["opening"] for o in r["operation"]["ops"] if o["op"] == "add-opening"]
        spec = self.svc.store.get(did)[0]
        scene = geometry.compile_spec(spec)
        ids = {a.id for a in geometry.opening_axes(spec, scene)}
        self.assertTrue(adds)
        self.assertTrue(all(o["wallAxis"]["id"] in ids for o in adds), "floorplan wall axes")
        spec = self.apply(did, r)
        self.assertEqual(len(geometry.design_openings(spec, geometry.compile_spec(spec))), len(adds), "drawn in the 3D scene")


class TestPlanRunsLines(unittest.TestCase):
    def test_every_placed_run_has_its_line(self):
        from kitchen.recognition import build_layout
        from kitchen.spec import KitchenSpec
        layout = build_layout(l_shape(False))
        runs = [{"id": r.id, "length": r.length, "modules": list(r.modules)} for r in layout.runs]
        p = run_line.plan_runs(KitchenSpec(), run_line.Line((0.0, 0.0), (6000.0, 0.0), (0.0, 1.0)), runs, list(layout.joints))
        self.assertEqual(sorted(p["lines"]), ["back", "left"])
        self.assertIsInstance(p["lines"]["back"], run_line.Line)


def wall_axes_for_test():
    from kitchen.openings import wall_axes
    return wall_axes.for_room(5000, 3000)[0]


class TestPhotoIntoTheHoleUnderTheClick(unittest.TestCase):
    """Inbox job 20261117-094128 on design mau-du-lieu-9f94a0: the drawn sliding door opening_004 (3920 wide, 2200 high in the drawing,
    its drawn type too narrow for it so it is not an opening of the design) with the wall wall_h10 as the selection. The picture's
    door goes into that hole at the drawing's height, not beside it at the picture's proportions."""

    FOUR = {"kind": "door", "style": "sliding", "leaves": 4, "edgesSeen": "hole", "aspect": 1.108,
            "axesRatio": [0.239, 0.494, 0.745], "hAxesRatio": [0.86], "confidence": 0.85}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="recog-hole-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.recognizers.clear()
        doc = json.loads((ROOT / "tests" / "data" / "floorplan-sliding-hole.json").read_text(encoding="utf-8"))
        self.did = self.svc.create_from_spec(doc)["id"]
        self.svc.recognizers["fake"] = Fake({"modules": [], "layout": {"schema": "recognized-runs/1", "runs": [], "joints": [],
                                                                       "photoOpenings": [self.FOUR]}})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_selected_wall_still_finds_the_hole_under_the_click(self):
        for selected in ("STRUCT-wall_h10", "STRUCT-opening_004"):
            with self.subTest(selected=selected):
                r = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": PNG}, "fake",
                                       anchor={"structureId": selected, "point": {"x": 0.0, "z": 1962.5}})
                op = r["operation"]["opening"]
                self.assertEqual((op["openingType"], op["width"], op["height"], op["center"], op["unsure"]),
                                 ("door-sliding-4-transom", 3920.0, 2200.0, 2048.7, []))
                self.assertEqual(op["hAxes"], [1892.0])
                self.assertEqual(op["sourceElement"], "opening_004", "it takes the drawn element's place")
                self.assertTrue(r["proposal"]["applicable"])

    def test_the_drawn_element_is_no_longer_built_once_a_door_stands_in_its_hole(self):
        r = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": PNG}, "fake",
                               anchor={"structureId": "STRUCT-wall_h10", "point": {"x": 0.0, "z": 1962.5}})
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        scene = geometry.compile_spec(self.svc.store.get(self.did)[0])
        self.assertNotIn("STRUCT-opening_004", {m.module for m in scene.meshes}, "the solid of the drawn element would hide the door")
        self.assertIn("opening-leaf-frame", {m.type for m in scene.meshes})

    def test_a_door_the_design_places_can_be_the_one_picked(self):
        r = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": PNG}, "fake",
                               anchor={"structureId": "STRUCT-wall_h10", "point": {"x": 0.0, "z": 1962.5}})
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        again = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": PNG}, "fake",
                                   anchor={"structureId": "OP1", "point": {"x": 0.0, "z": 1962.5}})
        self.assertEqual((again["operation"]["op"], again["operation"]["id"]), ("update-opening", "opening_004"))

    def test_a_hole_with_no_height_drawn_takes_the_picture_s_proportions(self):
        seen = seen_openings.read_photo({"photoOpenings": [PHOTO]})[0][0]                  # aspect 1.625
        axis = wall_axes_for_test()
        raw = seen_openings.photo_into_hole(seen, axis, 1000.0, 1650.0, builtin.CATALOG)
        self.assertEqual((raw["height"], raw["unsure"]), (2680.0, ["height"]))
        wide = seen_openings.photo_into_hole(seen, axis, 2000.0, 3920.0, builtin.CATALOG)   # 6370 high: not a door
        self.assertEqual(wide["height"], 2700.0, "an implausible height from the picture falls back to the type's")

    def test_a_typed_command_on_the_wall_also_fills_the_hole(self):
        made = self.svc.opening_command(self.did, "tạo cửa trượt 4 cánh", {"point": {"x": 0.0, "z": 1962.5}, "structureId": "wall_h10"}, "user", 1)
        op = made["operation"]["opening"]
        self.assertEqual((op["openingType"], op["width"], op["height"], op["sourceElement"]), ("door-sliding-4", 3920.0, 2200.0, "opening_004"))


class TestAskWhenUnsure(unittest.TestCase):
    """Proposal P6: an unsure recognizer, or two types that fit as well, make the user pick; the user's note wins over the picture."""

    FOUR = TestPhotoIntoTheHoleUnderTheClick.FOUR
    AT = {"structureId": "STRUCT-wall_h10", "point": {"x": 0.0, "z": 1962.5}}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="recog-ask-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.recognizers.clear()
        doc = json.loads((ROOT / "tests" / "data" / "floorplan-sliding-hole.json").read_text(encoding="utf-8"))
        self.did = self.svc.create_from_spec(doc)["id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_with(self, opening, note="", chosen=None):
        self.svc.recognizers["fake"] = Fake({"modules": [], "layout": {"schema": "recognized-runs/1", "runs": [], "joints": [],
                                                                       "photoOpenings": [opening]}})
        return self.svc.recognize(self.did, {"kind": "photo", "imageBase64": PNG, "note": note}, "fake", anchor=self.AT, opening_type=chosen)

    def test_an_unsure_recognizer_makes_the_user_pick_then_the_pick_is_used(self):
        r = self.run_with({**self.FOUR, "confidence": 0.4})
        self.assertEqual(r["status"], "question")
        picks = [c["openingType"] for c in r["choices"]]
        self.assertEqual(picks[0], "door-sliding-4-transom")
        self.assertLessEqual(len(picks), 3)
        self.assertTrue(r["choices"][0]["label"]["vi"])
        self.assertNotIn("proposal", r, "nothing is placed before the user picks")
        done = self.run_with({**self.FOUR, "confidence": 0.4}, chosen="door-sliding-4")
        self.assertEqual((done["status"], done["operation"]["opening"]["openingType"]), ("ok", "door-sliding-4"))
        with self.assertRaises(InvalidInput):
            self.run_with({**self.FOUR, "confidence": 0.4}, chosen="window-fixed")

    def test_two_types_that_fit_as_well_are_asked(self):
        r = self.run_with({**self.FOUR, "leaves": 3, "axesRatio": [0.33, 0.66], "hAxesRatio": []})
        self.assertEqual(r["status"], "question")
        self.assertEqual({c["openingType"] for c in r["choices"][:2]}, {"door-sliding-2", "door-sliding-4"})

    def test_the_note_wins_over_the_picture_and_says_so(self):
        two = {"kind": "door", "style": "swing", "leaves": 2, "edgesSeen": "hole", "aspect": 1.6, "axesRatio": [0.5], "hAxesRatio": [],
               "confidence": 0.9}
        r = self.run_with(two, note="thay bằng cửa trượt 4 cánh giống ảnh")
        self.assertEqual((r["status"], r["operation"]["opening"]["openingType"]), ("ok", "door-sliding-4"))
        self.assertTrue(any("opening-note-wins" in str(x) for x in r["summary"]))
        plain = self.run_with(two, note="thay bằng cửa giống ảnh")
        self.assertEqual(plain["operation"]["opening"]["openingType"], "door-swing-2")


class TestSecondLook(unittest.TestCase):
    """Proposal P4: the door built from a picture is drawn and shown to a vision model next to the picture; its corrections are used once."""

    AT = TestAskWhenUnsure.AT
    FOUR = TestPhotoIntoTheHoleUnderTheClick.FOUR

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="recog-look-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.recognizers.clear()
        doc = json.loads((ROOT / "tests" / "data" / "floorplan-sliding-hole.json").read_text(encoding="utf-8"))
        self.did = self.svc.create_from_spec(doc)["id"]
        self.asked = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_with(self, answer):
        def checker(picture, drawing, question):
            self.asked.append((picture, drawing, question))
            if isinstance(answer, Exception):
                raise answer
            return answer
        self.svc.opening_checker = checker
        self.svc.recognizers["fake"] = Fake({"modules": [], "layout": {"schema": "recognized-runs/1", "runs": [], "joints": [],
                                                                       "photoOpenings": [self.FOUR]}})
        return self.svc.recognize(self.did, {"kind": "photo", "imageBase64": PNG}, "fake", anchor=self.AT)

    def test_a_match_keeps_the_door_and_shows_both_pictures(self):
        r = self.run_with('{"same": true}')
        self.assertEqual((r["status"], r["operation"]["opening"]["openingType"]), ("ok", "door-sliding-4-transom"))
        picture, drawing, question = self.asked[0]
        self.assertEqual(picture, base64.b64decode(PNG))
        self.assertTrue(drawing.startswith(b"\x89PNG"), "the line drawing of the opening's own view")
        self.assertIn("4 leaves", question)
        self.assertTrue(any("opening-checked" in str(x) for x in r["summary"]))

    def test_corrections_are_used_once(self):
        r = self.run_with('```json\n{"same": false, "corrections": {"leaves": 2, "axesRatio": [0.5], "transomPanes": 0},'
                          ' "notes": ["two leaves, not four"]}\n```')
        self.assertEqual(len(self.asked), 1, "one second look, not a loop")
        self.assertEqual(r["operation"]["opening"]["openingType"], "door-sliding-2")
        said = " ".join(str(x) for x in r["summary"])
        self.assertIn("corrected after a second look", said)
        self.assertIn("two leaves, not four", said)

    def test_a_failed_or_unreadable_look_leaves_the_door_as_first_read(self):
        for answer, mark in ((RuntimeError("quota"), "opening-check-skipped"), ("I think it is fine", "opening-check-unreadable")):
            self.asked.clear()
            r = self.run_with(answer)
            self.assertEqual(r["operation"]["opening"]["openingType"], "door-sliding-4-transom")
            self.assertTrue(any(mark in str(x) for x in r["summary"]), mark)

    def test_without_a_model_auto_mode_is_quiet(self):
        self.svc.opening_checker = self.svc._model_opening_check
        self.svc.recognizers["fake"] = Fake({"modules": [], "layout": {"schema": "recognized-runs/1", "runs": [], "joints": [],
                                                                       "photoOpenings": [self.FOUR]}})
        if self.svc.models.available(None):
            self.skipTest("a model key is set here")
        r = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": PNG}, "fake", anchor=self.AT)
        self.assertFalse(any("opening-check" in str(x) for x in r["summary"]))

    def test_the_model_is_asked_with_both_pictures(self):
        from kitchen.model_contract import ModelReply
        sent = []
        self.svc.models.available = lambda spec=None: True
        self.svc.models.ask = lambda req, spec=None: sent.append((req, spec)) or ModelReply('{"same": true}', (), 1, 1, "end")
        self.svc.opening_checker = self.svc._model_opening_check
        self.svc.recognizers["fake"] = Fake({"modules": [], "layout": {"schema": "recognized-runs/1", "runs": [], "joints": [],
                                                                       "photoOpenings": [self.FOUR]}})
        r = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": PNG}, "fake", anchor=self.AT)
        req = sent[0][0]
        self.assertEqual((req.task, req.json_only), ("opening-check", True))
        self.assertEqual([i["mime"] for i in req.messages[0]["images"]], ["image/png", "image/png"])
        self.assertTrue(any("opening-checked" in str(x) for x in r["summary"]))

if __name__ == "__main__":
    unittest.main()


# the door of inbox job 20261113-154907: a wall with a double door and a transom, no cabinets (services/cabinet-recognizer test data)
PHOTO = {"kind": "door", "style": "swing", "leaves": 2, "edgesSeen": "hole", "aspect": 1.625, "axesRatio": [0.503], "hAxesRatio": [0.818],
         "confidence": 0.85}


def building_design(svc):
    from kitchen import floorplan as fpm
    building = json.loads((ROOT / "tests" / "data" / "floorplan-building.json").read_text(encoding="utf-8-sig"))
    return svc.create_from_spec({"floorplan": fpm.normalize(building, "region:around=furniture_003")})["id"]


class TestPhotoOnly(unittest.TestCase):
    """A picture with a door and no cabinets: no scale, so the type's height and the picture's proportions; placed where the user clicked."""

    def test_reading_checks_the_ratios(self):
        found, rejected = seen_openings.read_photo({"photoOpenings": [PHOTO, {**PHOTO, "aspect": 0}, {**PHOTO, "axesRatio": [1.2]}, {"kind": "x"}]})
        self.assertEqual(len(found), 1)
        self.assertEqual(len(rejected), 3)

    def test_sized_from_the_type_height_and_the_proportions(self):
        seen = seen_openings.read_photo({"photoOpenings": [PHOTO]})[0][0]
        raw = seen_openings.photo_opening(seen, (0.0, 1500.0), builtin.CATALOG, "VN")
        self.assertEqual((raw["openingType"], raw["height"], raw["width"]), ("door-swing-2-transom", 2700.0, 1650.0))
        self.assertEqual(raw["hAxes"], [2208.6])                    # the transom, where the picture shows it
        self.assertEqual(raw["axes"], [5.0])                        # the leaves meet 5 mm right of the centre
        self.assertEqual(raw["unsure"], ["width", "height"])
        cased = seen_openings.photo_opening(seen_openings.read_photo({"photoOpenings": [{**PHOTO, "edgesSeen": "casing"}]})[0][0], (0.0, 0.0),
                                           builtin.CATALOG, "VN")
        self.assertLess(cased["width"], raw["width"], "the casing seen around it is not part of the hole")
        near = seen_openings.photo_opening(seen_openings.read_photo({"photoOpenings": [{**PHOTO, "aspect": 2.2}]})[0][0], (0.0, 0.0),
                                          builtin.CATALOG, "VN")
        self.assertEqual(near["width"], 1200.0, "close to a standard width of the country: taken")

    def test_four_sliding_panels_are_the_four_panel_sliding_door(self):
        """Inbox job 20261117-094128: four sliding glass panels under a fixed transom."""
        four = {"kind": "door", "style": "sliding", "leaves": 4, "aspect": 0.83, "axesRatio": [0.239, 0.494, 0.745], "hAxesRatio": [0.86]}
        seen = seen_openings.read_photo({"photoOpenings": [four]})[0][0]
        raw = seen_openings.photo_opening(seen, (0.0, 0.0), builtin.CATALOG, "VN")
        self.assertEqual((raw["openingType"], raw["height"]), ("door-sliding-4-transom", 2700.0))
        self.assertEqual(len(raw["axes"]), 3)
        plain = seen_openings.read_photo({"photoOpenings": [{**four, "hAxesRatio": []}]})[0][0]
        self.assertEqual(seen_openings.photo_opening(plain, (0.0, 0.0), builtin.CATALOG, "VN")["openingType"], "door-sliding-4")
        two = seen_openings.read_photo({"photoOpenings": [{**four, "leaves": 2, "axesRatio": [0.5], "hAxesRatio": []}]})[0][0]
        self.assertEqual(seen_openings.photo_opening(two, (0.0, 0.0), builtin.CATALOG, "VN")["openingType"], "door-sliding-2")

    def test_a_window_keeps_its_sill_unsure(self):
        w = seen_openings.read_photo({"photoOpenings": [{"kind": "window", "style": "sliding", "leaves": 2, "aspect": 0.8, "axesRatio": [0.5],
                                                         "hAxesRatio": []}]})[0][0]
        raw = seen_openings.photo_opening(w, (0.0, 0.0), builtin.CATALOG, "VN")
        self.assertEqual((raw["openingType"], raw["unsure"]), ("window-sliding-2", ["width", "height", "sill"]))


class TestPhotoOnlyService(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="recog-photo-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.recognizers.clear()
        self.did = building_design(self.svc)
        self.src = {"kind": "photo", "imageBase64": PNG, "name": "door.png"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def recognize(self, raw, anchor):
        self.svc.recognizers["fake"] = Fake(raw)
        return self.svc.recognize(self.did, self.src, "fake", anchor=anchor)

    def test_the_door_goes_on_the_wall_that_was_clicked(self):
        raw = {"modules": [], "layout": {"schema": "recognized-runs/1", "runs": [], "joints": [], "photoOpenings": [PHOTO]}}
        r = self.recognize(raw, {"structureId": "STRUCT-wall_h05", "point": {"x": -70.0, "z": 1500.0}})
        self.assertEqual((r["status"], r["mode"]), ("ok", "opening"))
        op = r["operation"]
        self.assertEqual(op["op"], "add-opening")
        self.assertTrue(r["proposal"]["applicable"])
        self.svc.apply(self.did, op, r["baseRev"], "test", r["proposal"]["opHash"])
        spec = self.svc.store.get(self.did)[0]
        scene = geometry.compile_spec(spec)
        axes = geometry.opening_axes(spec, scene)
        door = next(o for o in openings.effective(spec.model_dump(mode="json", exclude_none=True), builtin.CATALOG, axes, spec.country)
                    if o.source == "ai")
        axis = next(a for a in axes if a.id == door.wall_axis.id)
        self.assertEqual(axis.id, "WA-WALL-FP-1")
        self.assertAlmostEqual(axis.point(door.center)[1], 1500.0, delta=1)
        self.assertEqual((door.opening_type, door.width, door.height, door.h_axes), ("door-swing-2-transom", 1650.0, 2700.0, (2208.6,)))
        self.assertIn("width", door.unsure)
        self.assertEqual(sum(1 for lf in door.leaves if lf.operation == "swing"), 2)
        self.assertIn("opening-frame", {m.type for m in scene.meshes})

    def test_without_a_clicked_wall_nothing_is_placed(self):
        r = self.recognize({"modules": [], "photoOpenings": [PHOTO]}, None)
        self.assertEqual(r["status"], "empty")
        self.assertIn("right-click", r["message"])

    def test_a_flat_draft_from_gemini_works_the_same(self):
        r = self.recognize({"modules": [], "photoOpenings": [PHOTO]}, {"structureId": "STRUCT-wall_h05", "point": {"x": -70.0, "z": 1500.0}})
        self.assertEqual(r["status"], "ok")


class TestPhotoReplaces(unittest.TestCase):
    """Inbox job 20261113-160240: "thay thế bằng cửa giống ảnh này", right-clicked on a door of the floorplan."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="recog-photo-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.recognizers.clear()
        self.did = building_design(self.svc)
        self.svc.recognizers["fake"] = Fake({"modules": [], "photoOpenings": [PHOTO]})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_click_on_a_door_turns_that_door_into_the_one_in_the_picture(self):
        before = {o["id"]: o for o in self.svc.list_openings(self.did)["openings"]}["opening_002"]      # 750 wide, on WA-WALL-FP-2
        r = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": PNG}, "fake",
                               anchor={"structureId": "STRUCT-opening_002", "point": {"x": -70.0 + 535.0 + 200.0, "z": -70.0}})
        self.assertEqual(r["status"], "ok")
        self.assertEqual((r["operation"]["op"], r["operation"]["id"]), ("update-opening", "opening_002"))
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        after = [o for o in self.svc.list_openings(self.did)["openings"] if o["sourceElement"] == "opening_002"]
        self.assertEqual(len(after), 1, "replaced, not doubled")
        door = after[0]
        self.assertEqual((door["openingType"], door["center"], door["width"], door["height"]),
                         ("door-swing-2-transom", before["center"], before["width"], before["height"]))
        self.assertEqual(door["hAxes"], [1799.6])                   # the transom at the picture's 0.818 of the hole
        self.assertTrue(any("opening-replaced-from-photo" in str(x) for x in r["summary"]))

    def test_a_click_beside_the_doors_adds_one(self):
        r = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": PNG}, "fake",
                               anchor={"structureId": "STRUCT-wall_h05", "point": {"x": -70.0, "z": 1500.0}})
        self.assertEqual(r["operation"]["op"], "add-opening")


class TestPhotoFitsTheSelection(unittest.TestCase):
    def test_a_window_selected_becomes_a_door_of_its_width(self):
        """The case seen in design mau-du-lieu-7dc0ff: the window opening_005 (1180 wide, no height in the drawing) right-clicked."""
        from kitchen.openings.contract import AxisRef
        window = openings.Opening("opening_005", "window", "window-swing-2", AxisRef("WA-1"), 2498.65, 1180.1, None, None, (), 900.0, 1200.0,
                                  None, "drawn", ("openingType", "height", "sill"), "opening_005")
        seen = seen_openings.read_photo({"photoOpenings": [PHOTO]})[0][0]
        changes = seen_openings.photo_replacement(seen, window, builtin.CATALOG)
        self.assertEqual((changes["kind"], changes["width"], changes["height"], changes["sill"], changes["unsure"]),
                         ("door", 1180.1, 1920.0, 0.0, ["height"]))               # 1180 x 1.625, standing on the floor
        self.assertEqual(changes["hAxes"], [1570.6])
        picked = seen_openings.clicked_opening((0.0, 0.0), [], [window], "opening_005")
        self.assertIs(picked, window, "the selected element is the target even far from the axis")
