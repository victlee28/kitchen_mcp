"""Recognition plug-in point: the draft is checked, becomes one replace operation, and only ever previews until applied."""
import base64
import json
import shutil
import sys
import tempfile
import dataclasses
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import recognition  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402
from kitchen.backends import BackendError  # noqa: E402
from kitchen.config import Config  # noqa: E402
from kitchen.recognizers import GeminiRecognizer  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.store import ConflictError  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
PNG = base64.b64encode(b"\x89PNG fake").decode()
GOOD = {"modules": [
    {"type": "base-sink", "wall": "back", "width": 900, "confidence": 0.9, "label": "Chậu"},
    {"type": "base", "wall": "back", "width": 600},
    {"type": "upper", "wall": "back", "width": 600, "confidence": 0.3},
    {"type": "tall-fridge", "wall": "left", "width": 700},
], "room": {"ceiling": 2700}, "materials": {"base": "Trắng mờ", "bogus": "x"}}


class Fake:
    def __init__(self, raw=None, boom=False):
        self.raw, self.boom, self.seen = raw if raw is not None else GOOD, boom, None

    def recognize(self, source):
        self.seen = source
        if self.boom:
            raise RuntimeError("model offline")
        return self.raw


class TestDraft(unittest.TestCase):
    def test_bad_entries_are_rejected_with_reasons(self):
        d = recognition.build_draft({"modules": [
            {"type": "spaceship", "width": 600}, {"type": "base", "wall": "ceiling", "width": 600}, {"type": "base", "width": 5},
            {"type": "base", "width": 600, "height": -1}, "nope", {"type": "corner-shelf", "wall": "corner", "width": 900},
            {"type": "base", "width": 601.4, "confidence": 7}]})
        self.assertEqual([m.width for m in d.modules], [601.0])
        self.assertEqual(d.modules[0].confidence, 1.0)
        self.assertEqual(len(d.rejected), 6)
        self.assertTrue(all(r["reason"] for r in d.rejected))

    def test_garbage_never_raises(self):
        for raw in (None, [], "x", {"modules": "x"}, {"modules": [None]}):
            self.assertEqual(recognition.build_draft(raw).modules, [])

    def test_low_confidence_is_flagged_not_dropped(self):
        d = recognition.build_draft(GOOD)
        self.assertEqual([m.needs_review for m in d.modules], [False, False, True, False])
        self.assertEqual(d.materials, {"base": "Trắng mờ"})
        self.assertEqual(d.ceiling, 2700)


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="recog-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.recognizers.clear()     # a real key in the environment wires Gemini; these tests plug in fakes
        self.did = self.svc.create_from_spec(json.loads(json.dumps(FIX)))["id"]
        self.rev = self.svc.store.get(self.did)[1]
        self.src = {"kind": "photo", "imageBase64": PNG, "name": "a.png"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_recognizer_is_reported_not_faked(self):
        self.assertEqual(self.svc.recognize(self.did, self.src)["status"], "unavailable")

    def test_ok_previews_a_replace_and_saves_nothing(self):
        fake = Fake()
        self.svc.register_recognizer("fake", fake)
        r = self.svc.recognize(self.did, self.src)
        self.assertEqual(r["status"], "ok")
        self.assertEqual((fake.seen.kind, fake.seen.name, fake.seen.data), ("photo", "a.png", b"\x89PNG fake"))
        ops = r["operation"]["ops"]
        adds = [o["module"] for o in ops if o["op"] == "add"]
        self.assertEqual(sorted(m["type"] for m in adds), sorted(m["type"] for m in r["draft"]["modules"]), "every cabinet of the draft is placed, by runs")
        self.assertTrue(all(m["wall"] == "island" and m["run"] for m in adds))
        self.assertEqual(r["mode"], "replace")
        self.assertTrue(r["proposal"]["applicable"])
        self.assertEqual(len(self.svc.history(self.did)), 1)                    # still only the original revision

    def test_confirm_applies_exactly_the_preview(self):
        self.svc.register_recognizer("fake", Fake())
        r = self.svc.recognize(self.did, self.src)
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        spec, rev = self.svc.store.get(self.did)
        self.assertEqual((rev, len(spec.module), spec.common.ceiling), (self.rev + 1, 4, 2700))

    def test_failures_are_statuses(self):
        self.svc.register_recognizer("fake", Fake(boom=True))
        self.assertEqual(self.svc.recognize(self.did, self.src)["status"], "failed")
        self.svc.recognizers["fake"] = Fake({"modules": []})
        self.assertEqual(self.svc.recognize(self.did, self.src)["status"], "empty")

    def test_bad_input_and_stale_revision(self):
        self.svc.register_recognizer("fake", Fake())
        for bad in ({"kind": "video", "imageBase64": PNG}, {"kind": "photo", "imageBase64": "%%%"}, {"kind": "photo", "imageBase64": ""}):
            with self.assertRaises(InvalidInput):
                self.svc.recognize(self.did, bad)
        with self.assertRaises(InvalidInput):
            self.svc.recognize(self.did, self.src, recognizer="other")
        with self.assertRaises(ConflictError):
            self.svc.recognize(self.did, self.src, base_revision=self.rev + 3)


if __name__ == "__main__":
    unittest.main()


REAL_PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 20


class _FakeVision(BaseHTTPRequestHandler):
    calls: list = []
    mode = "ok"

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeVision.calls.append({"path": self.path, "key": self.headers.get("x-goog-api-key"), "body": body})
        if _FakeVision.mode == "429":
            out, code = b"quota", 429
        elif _FakeVision.mode == "text":
            out, code = json.dumps({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}).encode(), 200
        else:
            out, code = json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(GOOD)}]}}]}).encode(), 200
        self.send_response(code); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)


class TestGeminiRecognizer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeVision)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.cfg = dataclasses.replace(Config.from_env({}), gemini_api_key="k1", gemini_vision_model="vis-test",
                                      gemini_base_url=f"http://127.0.0.1:{cls.srv.server_address[1]}/v1beta")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        _FakeVision.mode, _FakeVision.calls = "ok", []

    def test_request_shape_and_draft(self):
        raw = GeminiRecognizer(self.cfg).recognize(recognition.RecognitionInput("drawing", REAL_PNG, "a.png", "image/png"))
        call = _FakeVision.calls[0]
        self.assertEqual(call["key"], "k1")
        self.assertIn("/models/vis-test:generateContent", call["path"])
        parts = call["body"]["contents"][0]["parts"]
        self.assertIn("technical drawing", parts[0]["text"])
        self.assertEqual(parts[1]["inline_data"]["mime_type"], "image/png")
        self.assertEqual(base64.b64decode(parts[1]["inline_data"]["data"]), REAL_PNG)
        self.assertEqual(len(recognition.build_draft(raw).modules), 4)

    def test_not_an_image_and_errors_are_backend_errors(self):
        rec = GeminiRecognizer(self.cfg)
        with self.assertRaises(BackendError):
            rec.recognize(recognition.RecognitionInput("photo", b"not an image"))
        _FakeVision.mode = "429"
        with self.assertRaises(BackendError) as c:
            rec.recognize(recognition.RecognitionInput("photo", REAL_PNG))
        self.assertEqual(c.exception.code, "overloaded")
        _FakeVision.mode = "text"
        with self.assertRaises(BackendError):
            rec.recognize(recognition.RecognitionInput("photo", REAL_PNG))

    def test_service_reports_failure_not_crash(self):
        tmp = Path(tempfile.mkdtemp(prefix="recog-g-"))
        try:
            svc = KitchenService(tmp / "k.db", tmp / "r")
            svc.recognizers.clear(); svc.recognizers["gemini"] = GeminiRecognizer(self.cfg)
            did = svc.create_from_spec(json.loads(json.dumps(FIX)))["id"]
            _FakeVision.mode = "429"
            out = svc.recognize(did, {"kind": "photo", "imageBase64": base64.b64encode(REAL_PNG).decode()})
            self.assertEqual(out["status"], "failed")
            _FakeVision.mode = "ok"
            out = svc.recognize(did, {"kind": "photo", "imageBase64": base64.b64encode(REAL_PNG).decode()})
            self.assertEqual(out["status"], "ok")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_key_means_unavailable(self):
        with self.assertRaises(BackendError):
            GeminiRecognizer(dataclasses.replace(self.cfg, gemini_api_key=None, gemini_env_file=None))
