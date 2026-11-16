"""Bước ``openings``: cửa đi / cửa sổ trong ảnh -> mm dọc tường, cùng hệ toạ độ với tủ, rồi sang khung dãy (recognized-runs/1)."""
import json
import unittest
from pathlib import Path

from cabinet_recognizer import pipeline
from cabinet_recognizer.contract_openings import parse_openings
from cabinet_recognizer.errors import RecognizerError
from cabinet_recognizer.pipeline import recognize_auto
from cabinet_recognizer.to_runs import to_runs
from cabinet_recognizer.vision import ReplayClient

HERE = Path(__file__).parent
NAME = "bep-chu-L-trang"
IMAGE = (HERE / "data" / f"{NAME}.png").read_bytes()
ANSWERS = json.loads((HERE / "data" / f"{NAME}.answers.json").read_text(encoding="utf-8"))
GOLDEN = json.loads((HERE / "golden" / f"{NAME}.spec.json").read_text(encoding="utf-8"))
# (wall, x0, x1, sill, head, middle axes, transoms): what the photo "shows" on the walls of the L kitchen
TRUTH = [("back", 600, 1800, 1100, 2000, [1200], [1700]), ("left", 1500, 2400, 0, 2100, [], [])]


def wall_point():
    """The camera of the recorded L case, as the inverse of the opening measurement: (wall, x mm, h mm) -> image fractions."""
    debug: dict = {}
    recognize_auto(IMAGE, ReplayClient({**ANSWERS, "openings": {"openings": []}}), debug=debug)
    w, h = debug["measure"]["imageSize"]

    def frac(wall, x, hh):
        u, v = debug["wallPoint"](wall, x, hh)
        return [u / w, v / h]
    return frac


def answer(frac, **extra):
    out = []
    for wall, x0, x1, sill, head, mids, lows in TRUTH:
        cx = (x0 + x1) / 2
        out.append({"kind": "window" if sill else "door", "wall": wall,
                    "corners": {"topLeft": frac(wall, x0 if wall == "back" else x1, head), "topRight": frac(wall, x1 if wall == "back" else x0, head),
                                "bottomRight": frac(wall, x1 if wall == "back" else x0, sill), "bottomLeft": frac(wall, x0 if wall == "back" else x1, sill)},
                    "edgesSeen": "hole", "style": "swing", "leaves": len(mids) + 1,
                    "verticals": [frac(wall, m, (sill + head) / 2) for m in mids], "horizontals": [frac(wall, cx, t) for t in lows],
                    "confidence": 0.9, **extra})
    return {"openings": out}


class RoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frac = staticmethod(wall_point())

    def recognize(self, openings):
        client = ReplayClient({**ANSWERS, "openings": openings})
        return recognize_auto(IMAGE, client)["spec"]

    def test_openings_come_back_in_mm_along_the_walls(self):
        spec = self.recognize(answer(self.frac))
        got = {o["wall"]: o for o in spec.pop("openings")}
        for wall, x0, x1, sill, head, mids, lows in TRUTH:
            o = got[wall]
            self.assertLessEqual(abs(o["x"] - x0), 10, o)
            self.assertLessEqual(abs(o["x"] + o["width"] - x1), 10, o)
            self.assertLessEqual(abs(o["sill"] - sill), 10, o)
            self.assertLessEqual(abs(o["head"] - head), 10, o)
            self.assertEqual(len(o.get("axes", [])), len(mids))
            for a, b in zip(o.get("axes", []), mids):
                self.assertLessEqual(abs(a - b), 10)
            for a, b in zip(o.get("hAxes", []), lows):
                self.assertLessEqual(abs(a - b), 10)
        self.assertEqual(spec, GOLDEN, "the cabinets are measured as before")

    def test_runs_carry_the_openings_in_the_ai_form_of_the_kitchen(self):
        spec = self.recognize(answer(self.frac))
        runs = {r["id"]: r for r in to_runs(spec)["runs"]}
        back = runs["back"]["openings"][0]
        self.assertEqual([a["s"] for a in back["axes"]][0], spec["openings"][0]["x"])          # back run: s = x
        left = runs["left"]["openings"][0]
        length = runs["left"]["length"]
        o = next(x for x in spec["openings"] if x["wall"] == "left")
        self.assertEqual([a["s"] for a in left["axes"]], [length - o["x"] - o["width"], length - o["x"]])   # left run: mirrored
        self.assertEqual((left["sill"], left["head"], left["edgesSeen"]), (o["sill"], o["head"], "hole"))
        self.assertTrue(all(a["s"] < b["s"] for a, b in zip(back["axes"], back["axes"][1:])))

    def test_a_hidden_edge_is_measured_but_unsure(self):
        spec = self.recognize(answer(self.frac, hidden=["bottom", "right"]))
        back = next(o for o in spec["openings"] if o["wall"] == "back")
        self.assertNotIn("sill", back)
        self.assertEqual(back["unsure"], ["end", "sill"])
        left = next(o for o in spec["openings"] if o["wall"] == "left")
        self.assertEqual(left["unsure"], ["sill", "start"], "left wall: x grows to the left of the image")
        run = next(r for r in to_runs(spec)["runs"] if r["id"] == "back")
        self.assertEqual([a["confidence"] for a in run["openings"][0]["axes"]], [0.9, 0.9, 0.3])

    def test_old_recordings_have_no_openings(self):
        spec = recognize_auto(IMAGE, ReplayClient(ANSWERS))["spec"]
        self.assertNotIn("openings", spec)
        self.assertTrue(all("openings" not in r for r in to_runs(spec)["runs"]))

    def test_a_bad_answer_does_not_spoil_the_cabinets(self):
        bad = {"openings": [{"kind": "door", "wall": "right", "corners": {}}]}
        spec = recognize_auto(IMAGE, ReplayClient({**ANSWERS, "openings": bad}))["spec"]
        self.assertEqual(spec.pop("openings"), [])
        self.assertEqual(spec["warnings"][-1]["code"], "openings-rejected")
        spec["warnings"].pop()
        self.assertEqual(spec, GOLDEN)

    def test_an_implausible_opening_is_dropped_with_a_warning(self):
        tiny = answer(self.frac)
        tiny["openings"][0]["corners"]["topRight"] = [tiny["openings"][0]["corners"]["topLeft"][0] + 0.001, tiny["openings"][0]["corners"]["topRight"][1]]
        tiny["openings"][0]["corners"]["bottomRight"] = [tiny["openings"][0]["corners"]["bottomLeft"][0] + 0.001, tiny["openings"][0]["corners"]["bottomRight"][1]]
        spec = self.recognize(tiny)
        self.assertEqual([o["wall"] for o in spec["openings"]], ["left"])
        self.assertIn("opening-implausible", [w["code"] for w in spec["warnings"]])


class ContractTest(unittest.TestCase):
    def ok(self, **kw):
        base = {"kind": "window", "wall": "back", "corners": {"topLeft": [0.2, 0.2], "topRight": [0.4, 0.2], "bottomRight": [0.4, 0.4],
                                                                 "bottomLeft": [0.2, 0.4]}}
        return parse_openings({"openings": [{**base, **kw}]}, ("back",))

    def test_defaults(self):
        o = self.ok()[0]
        self.assertEqual((o["edgesSeen"], o["style"], o["leaves"], o["hidden"], o["confidence"]), ("casing", "swing", 1, [], 1.0))
        self.assertEqual(parse_openings({"openings": []}, ("back",)), [])

    def test_rejections(self):
        for kw in ({"wall": "left"}, {"kind": "gate"}, {"leaves": 9}, {"hidden": ["front"]}, {"confidence": 2},
                   {"corners": {"topLeft": [0.4, 0.2], "topRight": [0.2, 0.2], "bottomRight": [0.2, 0.4], "bottomLeft": [0.4, 0.4]}},
                   {"corners": {"topLeft": [0.2, 0.5], "topRight": [0.4, 0.5], "bottomRight": [0.4, 0.4], "bottomLeft": [0.2, 0.4]}},
                   {"verticals": [[0.3, 0.3]] * 5}):
            with self.subTest(kw=kw), self.assertRaises(RecognizerError):
                self.ok(**kw)


class FrontalTest(unittest.TestCase):
    def test_frontal_photo_measures_back_wall_openings(self):
        image = (HERE / "data" / "bep-chu-I-xam.png").read_bytes()
        answers = json.loads((HERE / "data" / "bep-chu-I-xam.answers.json").read_text(encoding="utf-8"))
        door = parse_openings({"openings": [{"kind": "door", "wall": "back", "corners": {
            "topLeft": [0.05, 0.2], "topRight": [0.15, 0.2], "bottomRight": [0.15, 0.7], "bottomLeft": [0.05, 0.7]}}]}, ("back",))
        spec = pipeline.recognize(image, ReplayClient(answers), openings=door)["spec"]
        o = spec["openings"][0]
        self.assertGreater(o["width"], 300)
        self.assertGreater(o["head"], o.get("sill", 0) + 1000)
        self.assertIn("openings-frontal-approximate", [w["code"] for w in spec["warnings"]])


if __name__ == "__main__":
    unittest.main()


class PhotoOnlyTest(unittest.TestCase):
    """A photo of a wall with a door and no cabinets (inbox job 20261113-154907): no scale reference, so only the kind and the ratios."""
    NAME = "cua-2-canh-o-fix"

    def answers(self):
        return json.loads((HERE / "data" / f"{self.NAME}.answers.json").read_text(encoding="utf-8"))

    def recognize(self, answers):
        return recognize_auto((HERE / "data" / f"{self.NAME}.png").read_bytes(), ReplayClient(answers))["spec"]

    def test_the_door_comes_back_as_ratios(self):
        spec = self.recognize(self.answers())
        self.assertEqual((spec["layout"], spec["modules"]), ("none", []))
        door = spec["photoOpenings"][0]
        self.assertEqual((door["kind"], door["style"], door["leaves"], door["edgesSeen"]), ("door", "swing", 2, "hole"))
        self.assertAlmostEqual(door["aspect"], 1.625, delta=0.01)
        self.assertEqual(door["axesRatio"], [0.503])
        self.assertEqual(door["hAxesRatio"], [0.818])

    def test_a_slanted_shot_gives_the_same_ratios(self):
        a = self.answers()
        o = a["openings"]["openings"][0]
        # the same door seen from the side: the far edge shorter; the dividers drawn where perspective puts them
        o["corners"] = {"topLeft": [0.2, 0.05], "topRight": [0.6, 0.15], "bottomRight": [0.6, 0.8], "bottomLeft": [0.2, 0.9]}
        from cabinet_recognizer.compute_openings import _to_unit
        inv = _to_unit([(0.2, 0.05), (0.6, 0.15), (0.6, 0.8), (0.2, 0.9)])
        # find the image point of unit (0.5, 0.82) by search on the picture: invert numerically
        best = min(((x / 400, y / 400) for x in range(80, 241) for y in range(20, 361)),
                   key=lambda p: (inv(*p)[0] - 0.5) ** 2 + (inv(*p)[1] - 0.82) ** 2)
        o["verticals"], o["horizontals"] = [[best[0], 0.5]], [[best[0], best[1]]]
        door = self.recognize(a)["photoOpenings"][0]
        self.assertAlmostEqual(door["hAxesRatio"][0], 0.82, delta=0.01)

    def test_runs_and_kitchen_conversion_carry_no_cabinets(self):
        spec = self.recognize(self.answers())
        runs = to_runs(spec)
        self.assertEqual((runs["runs"], runs["photoOpenings"][0]["kind"]), ([], "door"))
        from cabinet_recognizer.to_kitchen import to_kitchen_spec
        self.assertEqual(to_kitchen_spec(spec)["issues"][0]["code"], "no-cabinets")

    def test_no_cabinets_and_no_door_is_an_error(self):
        a = self.answers()
        a["openings"] = {"openings": []}
        with self.assertRaises(RecognizerError) as e:
            self.recognize(a)
        self.assertEqual(e.exception.code, "no-cabinets-no-openings")
