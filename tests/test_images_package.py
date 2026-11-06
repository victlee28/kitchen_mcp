"""kitchen/images: the clock, ids and seeds are values passed in; a worker that fails unexpectedly never leaves a job 'running'."""
from __future__ import annotations

import dataclasses
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen.images import Runtime  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

FIX = ROOT / "fixtures" / "l-shaped-kitchen.json"
VIEW = "original-angle"


class TestImagesPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="images-pkg-"))
        cls.svc = KitchenService(cls.tmp / "k.db", cls.tmp / "renders")
        cls.did = cls.svc.create_from_spec(json.loads(FIX.read_text(encoding="utf-8")))["id"]
        cls.svc.images.ensure_render(cls.did, None, VIEW, 640, 480)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_clock_id_and_seed_come_from_the_runtime(self):
        im = self.svc.images
        old = im.runtime
        im.runtime = Runtime(now=lambda: "2026-01-02T03:04:05+00:00", new_id=lambda: "fixed-id", new_seed=lambda: 1234)
        try:
            j = im.create(self.did, VIEW, "TD1-door-1", "Walnut", mode="quick", backend="recolor")
        finally:
            im.runtime = old
        self.assertEqual(j["id"], "job-fixed-id")
        self.assertEqual(j["request"]["seed"], 1234)

    def test_an_unexpected_worker_failure_marks_the_job_failed_and_is_still_logged(self):
        im = self.svc.images

        def boom(jid, jdir, req):
            raise RuntimeError("worker blew up")

        logged = []
        old_hook, old_run = threading.excepthook, im._run_gemini
        threading.excepthook = lambda args: logged.append(args.exc_value)
        im._run_gemini = boom
        try:
            j = im.create(self.did, VIEW, "TD1-door-1", "Walnut", mode="quick", backend="gemini")
            j = im.wait(j["id"], 30)
        finally:
            threading.excepthook, im._run_gemini = old_hook, old_run
        self.assertEqual(j["status"], "error:generation-failed")
        self.assertIn("worker blew up", j["error"])
        self.assertEqual([str(e) for e in logged], ["worker blew up"], "the traceback still reaches the thread excepthook")

    def test_backend_settings_come_from_the_config_value(self):
        im = self.svc.images
        im.config = dataclasses.replace(im.config, gemini_api_key=None, gemini_env_file=None)
        try:
            j = im.wait(im.create(self.did, VIEW, "TD1-door-1", "Walnut", mode="quick", backend="gemini")["id"], 30)
        finally:
            im.config = self.svc.config
        self.assertEqual(j["status"], "error:unsupported", "no key in the Config means no key, whatever the process environment holds")


if __name__ == "__main__":
    unittest.main()
