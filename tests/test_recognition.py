"""Recognition plug-in point: the draft is checked, becomes one replace operation, and only ever previews until applied."""
import base64
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import recognition  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402
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
        self.assertEqual(r["operation"]["op"], "replace")
        ids = [m["id"] for m in r["operation"]["spec"]["module"]]
        self.assertEqual(ids, ["TD1", "TD2", "TT1", "TC1"])
        back = [m for m in r["operation"]["spec"]["module"] if m["wall"] == "back" and m["id"].startswith("TD")]
        self.assertEqual([m["fromCorner"] for m in back], [0, 900])            # the second follows the first
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
