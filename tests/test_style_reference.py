"""An approved image of one view guides the look of the others (materials, colours, light) without leaking its composition."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import view_sync  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

FIX = ROOT / "fixtures" / "l-shaped-kitchen.json"
FIRST, SECOND = "original-angle", "corner-shelf"


class TestStyleReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="style-ref-"))
        cls.svc = KitchenService(cls.tmp / "k.db", cls.tmp / "renders")
        cls.did = cls.svc.create_from_spec(json.loads(FIX.read_text(encoding="utf-8")))["id"]
        cls.im = cls.svc.images
        for v in (FIRST, SECOND):
            cls.im.ensure_render(cls.did, None, v, 640, 480)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _gen0(self, view, **kw):
        return self.im.create(self.did, view, kind="gen0", backend="job-package", preview=True, **kw)

    def _approve(self, view):
        j = self.im.create(self.did, view, tasks=[{"targetLayer": "type:countertop", "material": "Đá nhân tạo đen"}], mode="quick")
        self.assertEqual(j["status"], "needs-review", j["error"])
        return self.im.accept(j["id"])

    def test_1_nothing_approved_yet_means_no_style_reference(self):
        j = self._gen0(SECOND)
        self.assertNotIn("styleReference", j["request"])
        self.assertFalse((Path(j["result"]["dir"]) / "style_reference.png").exists())

    def test_2_a_first_image_takes_the_look_of_the_approved_view(self):
        approved = self._approve(FIRST)
        j = self._gen0(SECOND)
        ref = j["request"]["styleReference"]
        self.assertEqual((ref["view"], ref["jobId"], ref["auto"]), (FIRST, approved["id"], True))
        jdir = Path(j["result"]["dir"])
        self.assertEqual(Image.open(jdir / "style_reference.png").size, tuple(j["request"]["size"]), "resized to the job's frame")
        lean = json.loads((jdir / "request.json").read_text(encoding="utf-8"))
        self.assertEqual([a["role"] for a in lean["attachedImages"]], ["input-image", "style-reference"])
        self.assertIn("IMAGE 2 is a STYLE REFERENCE", lean["instruction"])
        self.assertIn(f"'{FIRST}'", lean["instruction"])
        self.assertTrue(lean["validation"]["ok"], lean["validation"])
        body = json.loads((jdir / "gemini-request.json").read_text(encoding="utf-8"))
        self.assertEqual(sum("inline_data" in p for p in body["contents"][0]["parts"]), 2, "both images reach the model")

    def test_3_it_can_be_switched_off_or_named_and_must_be_another_view(self):
        self.assertNotIn("styleReference", self._gen0(SECOND, style_from="none")["request"])
        named = self._gen0(SECOND, style_from=FIRST)["request"]["styleReference"]
        self.assertEqual((named["view"], named["auto"]), (FIRST, False))
        with self.assertRaises(InvalidInput):
            self._gen0(SECOND, style_from=SECOND)
        with self.assertRaises(InvalidInput):
            self._gen0(SECOND, style_from="plan")      # that view has no approved image
        with self.assertRaises(InvalidInput):
            self._gen0(SECOND, style_from="no-such-view")

    def test_4_an_edit_job_has_none_unless_asked(self):
        j = self.im.create(self.did, SECOND, tasks=[{"targetLayer": "type:countertop", "material": "Đá trắng"}], backend="job-package", preview=True)
        self.assertNotIn("styleReference", j["request"])
        asked = self.im.create(self.did, SECOND, tasks=[{"targetLayer": "type:countertop", "material": "Đá trắng"}], backend="job-package",
                               preview=True, style_from=FIRST)
        self.assertEqual(asked["request"]["styleReference"]["view"], FIRST)
        roles = [a["role"] for a in json.loads((Path(asked["result"]["dir"]) / "request.json").read_text(encoding="utf-8"))["attachedImages"]]
        self.assertEqual(roles[-1], "style-reference")

    def test_5_a_stale_image_is_never_the_automatic_guide(self):
        self.svc.apply(self.did, {"op": "common", "changes": {"countertop": 910, "baseTop": 850}}, None)   # geometry changes: both go stale
        self.assertEqual(view_sync.view_status(self.im, self.did)[FIRST]["status"], "stale-geometry")
        self.assertIsNone(view_sync.style_source(self.im, self.did, SECOND, "auto"))


class TestRegenerateKeepsTheLook(unittest.TestCase):
    def test_stale_views_are_redone_with_the_current_view_as_guide(self):
        tmp = Path(tempfile.mkdtemp(prefix="style-regen-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        svc = KitchenService(tmp / "k.db", tmp / "renders")
        did = svc.create_from_spec(json.loads(FIX.read_text(encoding="utf-8")))["id"]
        for v in ("original-angle", "corner-shelf"):
            svc.images.ensure_render(did, None, v, 640, 480)
            j = svc.images.create(did, v, tasks=[{"targetLayer": "type:countertop", "material": "Đá nhân tạo đen"}], mode="quick")
            svc.images.accept(j["id"])
        svc.apply(did, {"op": "common", "changes": {"material": {**svc.store.get(did)[0].common.material, "base": "Laminate xanh rêu mờ"}}}, None)
        res = svc.images.regenerate_stale(did)
        job = svc.images.get(res["jobs"][0]["jobId"])
        self.assertEqual(res["jobs"][0]["view"], "original-angle")
        self.assertEqual(job["request"]["styleReference"]["view"], "corner-shelf", "the view that is still true guides the redo")


if __name__ == "__main__":
    unittest.main()
