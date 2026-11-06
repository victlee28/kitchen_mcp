"""Multi-view consistency: an approved image goes stale when a material it shows changes, and only then."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import view_sync  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

FIX = ROOT / "fixtures" / "l-shaped-kitchen.json"
SEES_BASE, NO_BASE = "original-angle", "corner-shelf"  # the corner-shelf view shows no base cabinet, plinth or floor
NEW = "Laminate xanh rêu mờ"


class TestViewSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="viewsync-"))
        cls.svc = KitchenService(cls.tmp / "k.db", cls.tmp / "renders")
        cls.did = cls.svc.create_from_spec(json.loads(FIX.read_text(encoding="utf-8")))["id"]
        cls.im = cls.svc.images
        for v in (SEES_BASE, NO_BASE):
            cls.im.ensure_render(cls.did, None, v, 640, 480)
            j = cls.im.create(cls.did, v, tasks=[{"targetLayer": "type:countertop", "material": "Đá nhân tạo đen"}], mode="quick")
            assert j["status"] == "needs-review", j["error"]
            cls.im.accept(j["id"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_1_nothing_changed_everything_is_current(self):
        st = view_sync.view_status(self.im, self.did)
        self.assertEqual(st[SEES_BASE]["status"], "current")
        self.assertEqual(st[NO_BASE]["status"], "current")
        self.assertEqual(st["plan"]["status"], "none", "a view with no approved image")

    def test_2_material_change_only_stales_views_that_show_it(self):
        self.svc.apply(self.did, {"op": "common", "changes": {"material": {**self.svc.store.get(self.did)[0].common.material, "base": NEW}}}, None)
        st = view_sync.view_status(self.im, self.did)
        self.assertEqual(st[SEES_BASE]["status"], "stale-appearance")
        self.assertTrue(st[SEES_BASE]["changed"] and all(c["now"] == NEW for c in st[SEES_BASE]["changed"]))
        self.assertEqual(st[NO_BASE]["status"], "current", "this view never shows the base cabinets")

    def test_3_regenerate_stale_prepares_a_review_job_for_the_stale_view_only(self):
        res = view_sync.regenerate_stale(self.im, self.did)
        self.assertEqual([j["view"] for j in res["jobs"]], [SEES_BASE])
        job = self.im.get(res["jobs"][0]["jobId"])
        self.assertEqual(job["status"], "awaiting-send", "nothing is sent before the user decides")
        self.assertTrue(all(t["material"] == NEW for t in job["request"]["tasks"]))

    def test_4_accepting_the_new_image_makes_the_view_current_again(self):
        jid = next(j["id"] for j in self.im.list(self.did, SEES_BASE, "awaiting-send"))
        sent = self.im.send(jid)
        self.assertEqual(sent["status"], "needs-review", sent["error"])
        self.im.accept(jid)
        self.assertEqual(view_sync.view_status(self.im, self.did)[SEES_BASE]["status"], "current")

    def test_5_geometry_change_is_reported_as_stale_geometry(self):
        self.svc.apply(self.did, {"op": "common", "changes": {"countertop": 910, "baseTop": 850}}, None)
        st = view_sync.view_status(self.im, self.did)
        self.assertEqual(st[SEES_BASE]["status"], "stale-geometry")



class TestBeforeSnapshots(unittest.TestCase):
    def test_images_accepted_without_a_snapshot_are_unknown_not_current(self):
        tmp = Path(tempfile.mkdtemp(prefix="viewsync-old-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        svc = KitchenService(tmp / "k.db", tmp / "renders")
        did = svc.create_from_spec(json.loads(FIX.read_text(encoding="utf-8")))["id"]
        svc.images.ensure_render(did, None, NO_BASE, 640, 480)
        j = svc.images.create(did, NO_BASE, tasks=[{"targetLayer": "type:countertop", "material": "Đá nhân tạo đen"}], mode="quick")
        real, view_sync.snapshot = view_sync.snapshot, lambda *a, **k: (_ for _ in ()).throw(OSError("old job"))
        try:
            svc.images.accept(j["id"])
        finally:
            view_sync.snapshot = real
        self.assertEqual(view_sync.view_status(svc.images, did)[NO_BASE]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
