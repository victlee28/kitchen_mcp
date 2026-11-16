"""The sample right-click sentences (tests/data/commands/commands.json) measured with tools/measure_commands.py: the rules may only read
more of them right, and a model of any provider is asked only for what the rules cannot read."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("measure_commands", ROOT / "tools" / "measure_commands.py")
mcmd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcmd)

from kitchen.service import KitchenService  # noqa: E402

CASES = json.loads((ROOT / "tests" / "data" / "commands" / "commands.json").read_text(encoding="utf-8"))
BASELINE = json.loads((ROOT / "tests" / "data" / "commands" / "baseline.json").read_text(encoding="utf-8"))


class TestMatching(unittest.TestCase):
    def test_subset_contains_and_tolerance(self):
        self.assertTrue(mcmd.matches({"op": "update", "changes": {"width": 800}}, {"op": "update", "id": "TD1", "changes": {"width": 800.4}}))
        self.assertTrue(mcmd.matches({"material": {"base": "trắng"}}, {"material": {"base": "Trắng", "wallTile": "x"}}))
        self.assertFalse(mcmd.matches({"op": "remove"}, {"op": "update"}))
        self.assertFalse(mcmd.matches({"sill": 900}, {"sill": 902}))
        self.assertTrue(mcmd.judge("clarify", "clarify", None))
        self.assertFalse(mcmd.judge({"op": "remove"}, "clarify", None))


class TestCases(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "r")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_rules_do_not_get_worse(self):
        result = mcmd.measure(self.svc, CASES, use_llm=False)
        self.assertEqual(result["modelCalls"], 0)
        self.assertGreaterEqual(result["right"], BASELINE["rulesRight"],
                                "\n".join(f"{r['text']}: {r['kind']} {r['operation']}" for r in result["rows"] if not r["right"]))
        if result["right"] > BASELINE["rulesRight"]:
            print(f"\nThe rules read {result['right']} sentences right: raise rulesRight in tests/data/commands/baseline.json")

    def test_no_sentence_that_does_not_say_remove_removes_a_cabinet(self):
        """Words that only look like "gỡ" / "loại" without their accents (gỗ, loại tủ) and the door of a cabinet ("xóa cánh cửa") once
        removed the whole cabinet."""
        for text in ("đổi màu cánh tủ này sang gỗ sồi", "cánh gỗ óc chó", "đổi loại tủ sang ngăn kéo", "xóa cánh cửa"):
            with self.subTest(text=text):
                result = mcmd.measure(self.svc, {**CASES, "cases": [{"text": text, "scope": ["TD3"], "expect": "clarify"}]}, use_llm=False)
                row = result["rows"][0]
                self.assertFalse(row["kind"] == "ok" and (row["operation"] or {}).get("op") == "remove", row)
        result = mcmd.measure(self.svc, {**CASES, "cases": [{"text": "xóa cánh cửa xóa cả tủ", "scope": ["TD3"], "expect": {"op": "remove", "id": "TD3"}}]},
                              use_llm=False)
        self.assertTrue(result["rows"][0]["right"], "the answer to the question removes it")

    def test_a_model_is_asked_only_for_what_the_rules_cannot_read(self):
        from test_models import FakeTransport, openai_reply   # noqa: E402  (tests folder on the path when run by unittest/pytest)
        replies = [openai_reply('{"op": "update", "id": "TT2", "changes": {"height": 800}}') for _ in range(5)]
        self.svc.models.config = replace(self.svc.models.config, llm_provider="openai", llm_model="gpt-x", openai_api_key="k")
        self.svc.models.transport = FakeTransport(*replies)
        doc = {**CASES, "cases": [c for c in CASES["cases"] if c["text"] in ("TT2 cao 800", "xóa TD3")]}
        result = mcmd.measure(self.svc, doc, use_llm=True)
        self.assertEqual(result["modelCalls"], 1, "only the sentence the rules could not read")
        self.assertEqual(result["right"], 2)
        self.assertEqual(result["provider"], "openai:gpt-x")


if __name__ == "__main__":
    unittest.main()
