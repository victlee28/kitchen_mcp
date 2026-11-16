"""The model gateway: one request shape for every provider (``model_contract``), the provider / key / fallback / budget / ledger logic
(``model_gateway``) and the callers moved onto it (``llm``). No network: a fake transport answers."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import llm  # noqa: E402
from kitchen import model_contract as mc  # noqa: E402
from kitchen.config import Config  # noqa: E402
from kitchen.model_gateway import ModelGateway  # noqa: E402

TOOL = mc.ToolSpec("get_design", "Read a design", {"type": "object", "properties": {"design_id": {"type": "string"}}})


def anthropic_reply(text="", calls=(), tin=10, tout=5, stop="end_turn"):
    content = ([{"type": "text", "text": text}] if text else []) + [{"type": "tool_use", "id": i, "name": n, "input": a} for i, n, a in calls]
    return {"model": "claude-x", "content": content, "stop_reason": "tool_use" if calls else stop, "usage": {"input_tokens": tin, "output_tokens": tout}}


def openai_reply(text="", calls=(), tin=10, tout=5):
    msg = {"role": "assistant", "content": text or None}
    if calls:
        msg["tool_calls"] = [{"id": i, "type": "function", "function": {"name": n, "arguments": json.dumps(a)}} for i, n, a in calls]
    return {"model": "gpt-x", "choices": [{"message": msg, "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": tin, "completion_tokens": tout}}


class FakeTransport:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.sent = []

    def __call__(self, url, headers, body, timeout):
        self.sent.append((url, dict(headers), body))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


class TestContract(unittest.TestCase):
    def conversation(self):
        return (
            {"role": "user", "text": "xóa TD3", "images": [{"mime": "image/png", "data": "AAA"}]},
            {"role": "assistant", "text": "", "calls": [{"id": "c1", "name": "get_design", "arguments": {"design_id": "d1"}}]},
            {"role": "tool", "id": "c1", "name": "get_design", "result": {"rev": 3}},
        )

    def test_anthropic_wire_format(self):
        body = mc.to_anthropic(mc.ModelRequest("sys", self.conversation(), (TOOL,), json_only=True), "claude-x")
        self.assertEqual(body["model"], "claude-x")
        self.assertIn("ONE JSON object", body["system"])
        self.assertEqual(body["tools"][0]["input_schema"]["type"], "object")
        self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant", "user"])
        self.assertEqual(body["messages"][0]["content"][0]["type"], "image")
        self.assertEqual(body["messages"][1]["content"], [{"type": "tool_use", "id": "c1", "name": "get_design", "input": {"design_id": "d1"}}])
        self.assertEqual(body["messages"][2]["content"][0], {"type": "tool_result", "tool_use_id": "c1", "content": '{"rev": 3}'})
        r = mc.from_anthropic(anthropic_reply("ok", [("c2", "get_design", {"design_id": "d1"})], 7, 3))
        self.assertEqual((r.stop, r.input_tokens, r.output_tokens, r.calls[0].name, r.calls[0].arguments), ("tool", 7, 3, "get_design", {"design_id": "d1"}))
        self.assertEqual(r.as_message()["calls"][0]["id"], "c2")

    def test_openai_wire_format(self):
        body = mc.to_openai(mc.ModelRequest("sys", self.conversation(), (TOOL,), json_only=True), "gpt-x")
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "tool"])
        self.assertTrue(body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(json.loads(body["messages"][2]["tool_calls"][0]["function"]["arguments"]), {"design_id": "d1"})
        self.assertEqual(body["messages"][3], {"role": "tool", "tool_call_id": "c1", "content": '{"rev": 3}'})
        self.assertEqual(body["response_format"], {"type": "json_object"})
        r = mc.from_openai(openai_reply("", [("c9", "get_design", {"design_id": "d2"})], 4, 2))
        self.assertEqual((r.stop, r.input_tokens, r.calls[0].arguments), ("tool", 4, {"design_id": "d2"}))

    def test_bad_replies_and_helpers(self):
        for bad in ({}, {"choices": []}, None):
            with self.assertRaises(mc.ModelError):
                mc.from_openai(bad)
        with self.assertRaises(mc.ModelError):
            mc.from_anthropic({"usage": {}})
        self.assertEqual(mc.first_json('Đây: ```json\n{"op": "remove", "id": "TD3"}\n```'), {"op": "remove", "id": "TD3"})
        with self.assertRaises(mc.ModelError):
            mc.first_json("không có json")
        self.assertAlmostEqual(mc.cost(1_000_000, 500_000, {"inputPerMTok": 3, "outputPerMTok": 15}), 10.5)
        self.assertIsNone(mc.cost(10, 10, {}))


class TestGateway(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base = Config.from_env({}, root=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def gw(self, transport, prices=None, **cfg):
        return ModelGateway(replace(self.base, **cfg), self.tmp / "logs" / "usage.jsonl", prices, transport, lambda: "2026-11-16T10:00:00Z")

    def test_provider_by_settings(self):
        t = FakeTransport(anthropic_reply("xin chào"), openai_reply("hello"))
        g = self.gw(t, llm_provider="anthropic", anthropic_api_key="k-a")
        r = g.ask(mc.ModelRequest("s", ({"role": "user", "text": "hi"},)))
        self.assertEqual((r.text, r.provider, r.model), ("xin chào", "anthropic", "claude-x"))
        url, headers, body = t.sent[0]
        self.assertEqual((url, headers["x-api-key"], body["model"]), ("https://api.anthropic.com/v1/messages", "k-a", "claude-sonnet-5-5"))
        g = self.gw(t, llm_provider="openai", llm_model="gpt-x", openai_api_key="k-o")
        self.assertEqual(g.ask(mc.ModelRequest("s", ({"role": "user", "text": "hi"},))).provider, "openai")
        self.assertEqual((t.sent[1][0], t.sent[1][1]["Authorization"]), ("https://api.openai.com/v1/chat/completions", "Bearer k-o"))

    def test_deepseek_stays_the_default_and_lan_endpoints(self):
        g = self.gw(FakeTransport(), deepseek_api_key="k-d")
        self.assertEqual(g.primary(), "deepseek")
        t = FakeTransport(openai_reply("ok"))
        g = self.gw(t, llm_provider="ollama", llm_model="qwen", llm_base_url="http://192.168.1.20:11434/v1")
        g.ask(mc.ModelRequest("s", ({"role": "user", "text": "hi"},)))
        self.assertEqual(t.sent[0][0], "http://192.168.1.20:11434/v1/chat/completions")

    def test_what_is_missing_is_said(self):
        g = self.gw(FakeTransport())
        self.assertFalse(g.available())
        with self.assertRaises(mc.ModelError) as e:
            g.ask(mc.ModelRequest("s", ()))
        self.assertEqual(e.exception.code, "model-no-key")
        with self.assertRaises(mc.ModelError) as e:
            self.gw(FakeTransport(), llm_provider="openai", openai_api_key="k").ask(mc.ModelRequest("s", ()))
        self.assertEqual(e.exception.code, "model-no-model")
        with self.assertRaises(mc.ModelError) as e:
            self.gw(FakeTransport(), llm_provider="nope").ask(mc.ModelRequest("s", ()))
        self.assertEqual(e.exception.code, "model-unknown-provider")

    def test_fallback_and_ledger(self):
        t = FakeTransport(mc.ModelError("down", code="model-http"), openai_reply("từ hãng phụ", tin=100, tout=50))
        g = self.gw(t, {"openai": {"gpt-x": {"inputPerMTok": 1, "outputPerMTok": 2}}}, llm_provider="anthropic", anthropic_api_key="k-a",
                    llm_fallback="openai:gpt-x", openai_api_key="k-o")
        r = g.ask(mc.ModelRequest("s", ({"role": "user", "text": "hi"},), task="edit"))
        self.assertEqual((r.text, r.provider), ("từ hãng phụ", "openai"))
        lines = [json.loads(x) for x in (self.tmp / "logs" / "usage.jsonl").read_text().splitlines()]
        self.assertEqual([(x["provider"], x["ok"], x["task"]) for x in lines], [("anthropic", False, "edit"), ("openai", True, "edit")])
        self.assertNotIn("k-a", (self.tmp / "logs" / "usage.jsonl").read_text(), "keys never reach the ledger")
        u = g.usage()
        self.assertEqual((u["calls"], u["failed"], u["inputTokens"], u["outputTokens"], u["usd"]), (2, 1, 100, 50, 0.0002))
        self.assertEqual(g.usage("2026-11-15")["calls"], 0)

    def test_daily_budget(self):
        t = FakeTransport(anthropic_reply("a", tin=60, tout=50), anthropic_reply("b"))
        g = self.gw(t, llm_provider="anthropic", anthropic_api_key="k", model_budget_tokens=100, llm_fallback="anthropic")
        g.ask(mc.ModelRequest("s", ()))
        with self.assertRaises(mc.ModelError) as e:
            g.ask(mc.ModelRequest("s", ()))
        self.assertEqual(e.exception.code, "model-budget")
        self.assertEqual(len(t.sent), 1, "nothing is sent once the budget is used up")


class TestCallers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_edit_and_prompt_through_any_provider(self):
        from kitchen.spec import KitchenSpec
        spec = KitchenSpec.model_validate(json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8")))
        for provider, reply in (("anthropic", anthropic_reply('{"op": "remove", "id": "TD3"}')), ("openai", openai_reply('{"op": "remove", "id": "TD3"}'))):
            cfg = replace(Config.from_env({}, root=self.tmp), llm_provider=provider, llm_model="m", anthropic_api_key="a", openai_api_key="o")
            g = ModelGateway(cfg, self.tmp / "u.jsonl", transport=FakeTransport(reply, reply))
            op, status = llm.edit_operation_llm("bỏ cái tủ thứ ba", spec, g)
            self.assertEqual((op, status["status"], status["provider"]), ({"op": "remove", "id": "TD3"}, "ok", provider))
        g = ModelGateway(Config.from_env({}, root=self.tmp), self.tmp / "u.jsonl", transport=FakeTransport())
        self.assertEqual(llm.edit_operation_llm("x", spec, g)[1]["status"], "skipped")
        cfg = replace(Config.from_env({}, root=self.tmp), llm_provider="anthropic", anthropic_api_key="a")
        g = ModelGateway(cfg, self.tmp / "u.jsonl", transport=FakeTransport(anthropic_reply('{"geometry_edit": "L"}')))
        template, status = llm.parse_prompt_llm("bếp chữ L", g)
        self.assertEqual((status["status"], template.geometry_edit if template else None), ("ok", "L"))


if __name__ == "__main__":
    unittest.main()
