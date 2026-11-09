"""POST /jobs: no API is called; the job waits for answers written into its inbox, resume continues, and a finished job carries the KitchenSpec."""
import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from cabinet_recognizer.config import Config
from cabinet_recognizer.errors import RecognizerError
from cabinet_recognizer.http_server import NoModelClient, client_or_none, make_handler
from cabinet_recognizer.vision import ReplayClient

HERE = Path(__file__).parent
NAME = "bep-chu-L-trang"
IMAGE = (HERE / "data" / f"{NAME}.png").read_bytes()
ANSWERS = json.loads((HERE / "data" / f"{NAME}.answers.json").read_text(encoding="utf-8"))


class JobsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Config.from_env(), ReplayClient({}), cls.root))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def call(self, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data, {"content-type": "application/json"}, method="POST" if payload is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_job_waits_then_finishes_with_the_kitchen_spec(self):
        status, job = self.call("/jobs", {"kind": "photo", "imageBase64": base64.b64encode(IMAGE).decode(), "note": "hint"})
        self.assertEqual((status, job["state"], job["step"]), (202, "waiting", "scene"))
        jid = job["id"]
        folder = self.root / jid / "inbox"
        self.assertIn("hint", (folder / "pending" / "scene" / "prompt.txt").read_text(encoding="utf-8"))
        self.assertEqual(self.call(f"/jobs/{jid}")[1]["state"], "waiting", "no answer yet: still waiting")
        for step, answer in ANSWERS.items():                                   # what Claude Desktop does: answer the steps
            (folder / "answers" / f"{step}.json").write_text(answer if isinstance(answer, str) else json.dumps(answer), encoding="utf-8")
        status, done = self.call(f"/jobs/{jid}/resume", {})
        self.assertEqual((status, done["state"]), (200, "done"))
        self.assertEqual(done["kitchen"]["spec"]["schemaVersion"], 2)
        self.assertTrue(done["kitchen"]["spec"]["module"])
        self.assertIsInstance(done["kitchen"]["issues"], list)

    def test_unknown_or_malformed_job_id_is_not_found(self):
        for bad in ("20990101-000000", "..", "x"):
            status, body = self.call(f"/jobs/{bad}")
            self.assertEqual((status, body["error"]["code"]), (404, "no-such-job"), bad)

    def test_bad_image_creates_no_job(self):
        before = set(self.root.iterdir())
        status, body = self.call("/jobs", {"imageBase64": base64.b64encode(b"nope").decode()})
        self.assertEqual((status, body["error"]["code"]), (422, "bad-image"))
        self.assertEqual(set(self.root.iterdir()), before)


class NoKeyTest(unittest.TestCase):
    def test_service_starts_without_an_api_key_and_still_opens_jobs(self):
        env = {"RECOG_PROVIDER": "openai", "RECOG_API_KEY": "", "OPENAI_API_KEY": ""}
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, env):
            config = Config.from_env()
            client = client_or_none(config)
        self.assertIsInstance(client, NoModelClient)
        with self.assertRaises(RecognizerError):
            client.complete("scene", "q", [])
        with tempfile.TemporaryDirectory() as tmp:
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(config, client, Path(tmp)))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/jobs", json.dumps({"imageBase64": base64.b64encode(IMAGE).decode()}).encode(),
                                             {"content-type": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    self.assertEqual((r.status, json.load(r)["state"]), (202, "waiting"))
            finally:
                server.shutdown(); server.server_close()


if __name__ == "__main__":
    unittest.main()
