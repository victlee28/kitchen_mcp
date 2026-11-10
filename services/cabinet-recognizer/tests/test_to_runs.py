"""Hợp đồng theo dãy (recognized-runs/1): s đo từ đầu trái khi đứng trước cánh; các dãy nối nhau ở góc trong."""
import json
import unittest
from pathlib import Path

from cabinet_recognizer.to_runs import SCHEMA, check_runs, to_runs

HERE = Path(__file__).parent
GOLDEN = sorted([*(HERE / "golden").glob("*.spec.json"), *(HERE / "golden" / "jobs").glob("*.spec.json")])


def load(name):
    return json.loads((HERE / "golden" / f"{name}.spec.json").read_text(encoding="utf-8"))


def run(doc, rid):
    return next(r for r in doc["runs"] if r["id"] == rid)


def mod(doc, rid, mid):
    return next(m for m in run(doc, rid)["modules"] if m["id"] == mid)


class ToRunsTest(unittest.TestCase):
    def test_every_recorded_result_converts_cleanly(self):
        self.assertGreaterEqual(len(GOLDEN), 8)
        for path in GOLDEN:
            with self.subTest(case=path.name):
                doc = to_runs(json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(doc["schema"], SCHEMA)
                self.assertEqual(check_runs(doc), [])
                self.assertEqual([r["id"] for r in doc["runs"]], [w for w in ("left", "back", "right") if w in {r["id"] for r in doc["runs"]}])

    def test_straight_run_keeps_left_to_right(self):
        rec = load("bep-chu-I-xam")
        doc = to_runs(rec)
        self.assertEqual(doc["joints"], [])
        src = {m["id"]: m for m in rec["modules"]}
        for m in run(doc, "back")["modules"]:
            self.assertEqual(m["s"], src[m["id"]]["x"])
        self.assertEqual(mod(doc, "back", "TD4")["frontSections"], [{"type": "drawer", "height": 345}, {"type": "drawer", "height": 345}])
        self.assertEqual(mod(doc, "back", "TD2")["appliances"][0]["type"], "sink")

    def test_left_run_is_mirrored_and_ends_at_the_corner(self):
        rec = load("bep-chu-L-trang")
        doc = to_runs(rec)
        self.assertEqual(doc["joints"], [{"a": "left", "b": "back", "angle": 90}])
        left, src = run(doc, "left"), {m["id"]: m for m in rec["modules"]}
        for m in left["modules"]:
            if m["id"] in src:
                s = src[m["id"]]
                self.assertEqual(m["s"], left["length"] - s["x"] - s["width"])
                if s.get("doors"):
                    self.assertEqual(m["doors"], list(reversed(s["doors"])))
        # tủ dưới của dãy trái dừng trước ô góc (sâu 600); ô góc thuộc tủ góc khuất của dãy sau
        base_end = max(m["s"] + m["width"] for m in left["modules"] if m["storey"] == "base")
        self.assertLessEqual(base_end, left["length"] - 590)
        corner = mod(doc, "back", "TD1")
        self.assertEqual((corner["s"], corner["blindCorner"] > 0), (0, True))
        self.assertEqual(sum(corner["doors"]) + corner["blindCorner"], corner["width"])

    def test_u_shape_right_corner_goes_to_the_next_run_or_stays_a_gap(self):
        doc = to_runs(load("u-frontal-render"))
        self.assertEqual([j["a"] + ">" + j["b"] for j in doc["joints"]], ["left>back", "back>right"])
        back = run(doc, "back")
        td5 = mod(doc, "back", "TD5")                       # tủ góc phải: chỉ còn phần nhìn thấy, không còn phần khuất ở cuối dãy
        self.assertNotIn("blindCorner", td5)
        self.assertLess(td5["s"] + td5["width"], back["length"] - 500)
        self.assertEqual(run(doc, "right")["modules"][0]["type"], "tall-fridge")
        self.assertNotIn("blindCorner", run(doc, "right")["modules"][0])   # tủ cao không nhận ô góc
        self.assertIn("corner-gap", [i["code"] for i in doc["issues"]])

    def test_tall_fridge_carries_niche_but_not_a_second_fridge(self):
        doc = to_runs(load("bep-chu-L-trang"))
        fridge = next(m for m in run(doc, "back")["modules"] if m["type"] == "tall-fridge")
        self.assertGreater(fridge["niche"], 1500)
        self.assertFalse([d for d in fridge.get("appliances", []) if d["type"] == "fridge"])


class SharedContractTest(unittest.TestCase):
    """tests/data/recognized_runs/*.json ở gốc repo là các tài liệu mẫu mà kitchen service kiểm tra phía NHẬN; phía GỬI phải sinh ra đúng chúng."""
    SHARED = HERE.parents[2] / "tests" / "data" / "recognized_runs"

    @unittest.skipUnless(SHARED.is_dir(), "chạy ngoài repo mcp-imagev2")
    def test_service_still_produces_the_shared_fixtures(self):
        files = sorted(self.SHARED.glob("*.json"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(fixture=path.name):
                doc = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(to_runs(load(doc["source"])), doc["runs"])


if __name__ == "__main__":
    unittest.main()
