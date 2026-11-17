"""Live checks of door and window recognition with real vision models (proposals P4 and P5). Skipped unless a key is set, so they cost
nothing in the normal run; when keys come, run:

    python -m pytest -q tests/test_opening_live.py -s

- The second look (P4) uses the kitchen's model gateway: KITCHEN_OPENING_CHECK_PROVIDER, else KITCHEN_LLM_PROVIDER, with its API key.
- The recognizer replay (P5) uses cabinet-recognizer's own client: RECOG_PROVIDER with RECOG_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))

from kitchen.service import KitchenService  # noqa: E402
import test_recognition_openings as tro  # noqa: E402

PICTURE = ROOT / "services" / "cabinet-recognizer" / "tests" / "data" / "cua-truot-4-canh-o-thoang.png"
BASELINE = json.loads((ROOT / "tests" / "data" / "openings" / "baseline.json").read_text(encoding="utf-8"))


class TestLiveSecondLook(unittest.TestCase):
    """A deliberately wrong first read (a two-leaf swing door) of the four-leaf sliding door picture: the second look must correct it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="opening-live-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        if not self.svc.models.available(self.svc.config.opening_check_provider):
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.skipTest("no vision model key (KITCHEN_OPENING_CHECK_PROVIDER / KITCHEN_LLM_PROVIDER and its key)")
        self.svc.recognizers.clear()
        doc = json.loads((ROOT / "tests" / "data" / "floorplan-sliding-hole.json").read_text(encoding="utf-8"))
        self.did = self.svc.create_from_spec(doc)["id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_wrong_first_read_is_corrected(self):
        wrong = {"kind": "door", "style": "swing", "leaves": 2, "edgesSeen": "hole", "aspect": 1.4, "axesRatio": [0.5],
                 "hAxesRatio": [0.86], "transomPanes": 1, "confidence": 0.9}
        self.svc.recognizers["fake"] = tro.Fake({"modules": [], "layout": {"schema": "recognized-runs/1", "runs": [], "joints": [],
                                                                           "photoOpenings": [wrong]}})
        import base64
        r = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": base64.b64encode(PICTURE.read_bytes()).decode("ascii")}, "fake",
                               anchor=tro.TestAskWhenUnsure.AT)
        print("\n".join(str(x) for x in r.get("summary", [])))
        self.assertTrue(any("opening-checked: corrected" in str(x) for x in r["summary"]), r.get("summary"))
        self.assertEqual(r.get("operation", {}).get("opening", {}).get("openingType"), "door-sliding-4-transom")


class TestLiveRecognizer(unittest.TestCase):
    """Every case of tests/data/openings/cases.json asked again of the real recognizer model; at most one opening worse than the kept answers."""

    def test_the_cases_with_a_live_model(self):
        import measure_openings as mo
        client = mo.live_client()
        if client is None:
            self.skipTest("no recognizer key (RECOG_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY)")
        doc = json.loads(mo.CASES.read_text(encoding="utf-8"))
        result = mo.measure(doc["cases"], client)
        print(json.dumps(result["total"], ensure_ascii=False))
        self.assertGreaterEqual(result["total"]["typeRight"], BASELINE["typeRight"] - 1)


if __name__ == "__main__":
    unittest.main()
