"""The image backend ``openai`` (kitchen.backends.OpenAIImages): the request it sends and how it reads the reply. No network."""
from __future__ import annotations

import base64
import io
import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import backends  # noqa: E402
from kitchen.config import Config  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestOpenAIImages(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "reference.png").write_bytes(b"\x89PNG-ref")
        self.cfg = replace(Config.from_env({}, root=self.tmp), openai_api_key="k-o", openai_image_model="img-x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sends_the_images_and_instruction_and_saves_the_result(self):
        sent = {}

        def opener(req, timeout):
            sent.update(url=req.full_url, headers=dict(req.header_items()), body=req.data)
            return FakeResponse(json.dumps({"data": [{"b64_json": base64.b64encode(b"PNGOUT").decode()}], "usage": {"total_tokens": 42}}).encode())
        info = backends.OpenAIImages(self.cfg, opener).generate("đổi tủ dưới sang xanh rêu", [self.tmp / "reference.png"], self.tmp / "raw.png", (1600, 1000))
        self.assertEqual(sent["url"], "https://api.openai.com/v1/images/edits")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer k-o")
        self.assertIn(b'name="model"\r\n\r\nimg-x', sent["body"])
        self.assertIn("đổi tủ dưới sang xanh rêu".encode(), sent["body"])
        self.assertIn(b"\x89PNG-ref", sent["body"])
        self.assertEqual((self.tmp / "raw.png").read_bytes(), b"PNGOUT")
        self.assertEqual((info["model"], info["size"], info["tokens"]), ("img-x", "1536x1024", 42))

    def test_errors_and_missing_key(self):
        with self.assertRaises(backends.BackendError) as e:
            backends.OpenAIImages(replace(self.cfg, openai_api_key=None))
        self.assertEqual(e.exception.code, "unsupported")
        with self.assertRaises(backends.BackendError) as e:
            backends.OpenAIImages(self.cfg, lambda req, timeout: FakeResponse(b'{"data": []}')).generate("x", [self.tmp / "reference.png"], self.tmp / "o.png", (800, 800))
        self.assertEqual(e.exception.code, "generation-failed")
        self.assertEqual([backends.openai_size(*s) for s in ((1000, 1000), (1600, 900), (900, 1600))], ["1024x1024", "1536x1024", "1024x1536"])

    def test_offered_in_the_catalog(self):
        self.assertIn("openai", backends.table())
        self.assertTrue(backends.table()["openai"]["async"])


if __name__ == "__main__":
    unittest.main()
