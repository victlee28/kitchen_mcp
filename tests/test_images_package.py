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
from kitchen.images.request import JobRequest, NewJob  # noqa: E402
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
            j = im.create(self.did, VIEW, "TD1-door-1", instruction="Walnut", mode="quick", backend="recolor")
        finally:
            im.runtime = old
        self.assertEqual(j["id"], "job-fixed-id")
        self.assertEqual(j["request"]["seed"], 1234)

    def test_an_unexpected_worker_failure_marks_the_job_failed_and_is_still_logged(self):
        im = self.svc.images

        def boom(jid, jdir, req):
            raise RuntimeError("worker blew up")

        logged = []
        old_hook, old_run = threading.excepthook, im.runners._run_gemini
        threading.excepthook = lambda args: logged.append(args.exc_value)
        im.runners._run_gemini = boom
        try:
            j = im.create(self.did, VIEW, "TD1-door-1", instruction="Walnut", mode="quick", backend="gemini")
            j = im.wait(j["id"], 30)
        finally:
            threading.excepthook, im.runners._run_gemini = old_hook, old_run
        self.assertEqual(j["status"], "error:generation-failed")
        self.assertIn("worker blew up", j["error"])
        self.assertEqual([str(e) for e in logged], ["worker blew up"], "the traceback still reaches the thread excepthook")

    def test_backend_settings_come_from_the_config_value(self):
        im = self.svc.images
        im.config = dataclasses.replace(im.config, gemini_api_key=None, gemini_env_file=None)
        try:
            j = im.wait(im.create(self.did, VIEW, "TD1-door-1", instruction="Walnut", mode="quick", backend="gemini")["id"], 30)
        finally:
            im.config = self.svc.config
        self.assertEqual(j["status"], "error:unsupported", "no key in the Config means no key, whatever the process environment holds")

    def test_every_stored_request_has_the_core_keys_of_job_request(self):
        im = self.svc.images
        core = set(JobRequest.__required_keys__)
        edit = im.create(self.did, VIEW, "TD1-door-1", material="Walnut", backend="recolor")["request"]
        gen0 = im.create(self.did, VIEW, kind="gen0", backend="job-package")["request"]
        geo = im.create(self.did, VIEW, kind="geometry_edit", backend="recolor", geometry_items=[{"type": "remove-module", "id": "TD3"}])["request"]
        for name, req in (("edit", edit), ("gen0", gen0), ("geometry_edit", geo)):
            self.assertEqual(core - set(req), set(), name)
            unknown = set(req) - set(JobRequest.__required_keys__) - set(JobRequest.__optional_keys__)
            self.assertEqual(unknown, set(), f"{name}: keys the JobRequest type does not know")
        self.assertNotIn("tasks", gen0)
        self.assertEqual(len(geo["tasks"]), 1)
        for t in edit["tasks"]:
            self.assertTrue({"targetLayer", "material", "instruction"} <= set(t))

    def test_submit_takes_a_new_job_value_and_create_is_the_keyword_form(self):
        im = self.svc.images
        new = NewJob(self.did, VIEW, target="TD1-door-1", material="Walnut", backend="recolor")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            new.view = "x"  # type: ignore[misc]
        a = im.submit(new)
        b = im.create(self.did, VIEW, "TD1-door-1", material="Walnut", backend="recolor")
        for key in ("tasks", "kind", "mode", "backend", "workflow"):
            self.assertEqual(a["request"].get(key), b["request"].get(key), key)
        with self.assertRaises(TypeError):  # more than (did, view, target) by position is refused: the 19-argument form is gone
            im.create(self.did, VIEW, "TD1-door-1", "Walnut")

    def test_regenerate_keeps_the_request(self):
        im = self.svc.images
        j = im.create(self.did, VIEW, backend="recolor", tasks=[{"targetLayer": "TD1-door-1", "material": "Walnut"},
                                                                   {"targetLayer": "type:countertop", "material": "Đá đen"}])
        k = im.regenerate(j["id"], seed=7)
        self.assertEqual(k["request"]["seed"], 7)
        self.assertEqual([(t["targetLayer"], t["material"]) for t in k["request"]["tasks"]],
                         [(t["targetLayer"], t["material"]) for t in j["request"]["tasks"]])

    def test_the_parts_are_composed_not_inherited_and_share_one_environment(self):
        from kitchen.images import ImageJobs
        from kitchen.images.common import Component
        im = self.svc.images
        self.assertEqual(ImageJobs.__mro__, (ImageJobs, object), "ImageJobs forwards to its parts; it does not inherit from them")
        parts = [im.base, im.builder, im.packages, im.results, im.runners]
        for part in parts:
            self.assertEqual(part.__class__.__mro__, (part.__class__, Component, object), f"{type(part).__name__} should only extend Component")
            self.assertIs(part.env, im.env)
        old = im.config
        try:
            im.config = dataclasses.replace(old, comfyui_url="http://example.invalid:1")
            self.assertTrue(all(part.config.comfyui_url == "http://example.invalid:1" for part in parts), "a replaced config reaches every part")
        finally:
            im.config = old


if __name__ == "__main__":
    unittest.main()
