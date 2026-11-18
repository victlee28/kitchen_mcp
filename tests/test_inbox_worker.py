"""The command inbox carried out by a model (``kitchen.inbox_worker``): a scripted model of either wire format calls the tools; the guard
rails hold whatever it says."""
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
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import model_contract as mc  # noqa: E402
from kitchen.intent import KitchenTemplate  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from test_models import anthropic_reply, openai_reply  # noqa: E402

FLOOR = {"kind": "floor", "point": {"x": -1500, "z": -50}}


def last_tool_result(body):
    """The last tool result the worker sent, as JSON (either wire format)."""
    for m in reversed(body["messages"]):
        if m.get("role") == "tool":
            return json.loads(m["content"])
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            for part in m["content"]:
                if part.get("type") == "tool_result":
                    return json.loads(part["content"])
    return None


def op_hash(result):
    return (result.get("proposal") or result).get("opHash")


class Scripted:
    """A model that plays ``steps``: each step gets the request body and returns (tool name, arguments) or a plain reply dict."""

    def __init__(self, fmt, steps):
        self.fmt, self.steps, self.bodies = fmt, list(steps), []

    def __call__(self, url, headers, body, timeout):
        self.bodies.append(body)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        name, args = step(body) if callable(step) else step
        reply = anthropic_reply if self.fmt == "anthropic" else openai_reply
        return reply("", [(f"call{len(self.bodies)}", name, args)])


class TestWorker(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "r")
        self.did = self.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3600}), "t")["id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def use(self, fmt, steps, **cfg):
        self.svc.models.config = replace(self.svc.models.config, llm_provider="anthropic" if fmt == "anthropic" else "openai",
                                         llm_model="m", anthropic_api_key="a", openai_api_key="o", **cfg)
        self.svc.models.transport = Scripted(fmt, steps)
        return self.svc.inbox_worker()

    def window_steps(self):
        return [("opening_command", {"text": "tạo cửa sổ"}),
                lambda body: ("apply_change", {"expect": op_hash(last_tool_result(body))}),
                ("answer", {"status": "done", "reply": "Đã thêm cửa sổ cách sàn 900 mm"})]

    def test_a_window_is_made_saved_and_answered_by_either_provider(self):
        for fmt in ("openai", "anthropic"):
            with self.subTest(fmt=fmt):
                rev = self.svc.get(self.did)["rev"]
                cmd = self.svc.command_put(self.did, "tạo cửa sổ", FLOOR, rev, "vi")
                worker = self.use(fmt, self.window_steps())
                (done,) = worker.run_once()
                self.assertEqual((done["id"], done["status"], done["revision"]), (cmd["id"], "done", rev + 1))
                windows = [o for o in self.svc.get(self.did)["spec"]["openings"] if o.get("kind") == "window" and not o.get("removed")]
                self.assertEqual(windows[-1]["sill"], 900.0)
                self.assertIn("tạo cửa sổ", json.dumps(self.svc.models.transport.bodies[0], ensure_ascii=False))
                self.assertIn("# Kitchen design: the command inbox", json.dumps(self.svc.models.transport.bodies[0]), "the kitchen-inbox skill is sent")

    def test_only_a_previewed_operation_can_be_saved(self):
        rev = self.svc.get(self.did)["rev"]
        self.svc.command_put(self.did, "xóa TD3", {"kind": "module", "id": "TD3", "module": "TD3"}, rev, "vi")
        worker = self.use("openai", [("apply_change", {"expect": "made-up-hash"}),
                                     lambda body: ("answer", {"status": "failed", "reply": last_tool_result(body)["error"]})])
        (closed,) = worker.run_once()
        self.assertEqual(closed["status"], "failed")
        self.assertIn("previewed in this command", closed["reply"])
        self.assertEqual(self.svc.get(self.did)["rev"], rev, "nothing was saved")

    def test_a_cabinet_edit_through_interpret(self):
        rev = self.svc.get(self.did)["rev"]
        self.svc.command_put(self.did, "rộng 800", {"kind": "module", "id": "TD1", "module": "TD1"}, rev, "vi")
        worker = self.use("anthropic", [("interpret_edit", {"text": "rộng 800", "scope_modules": ["TD1"]}),
                                        lambda body: ("apply_change", {"expect": op_hash(last_tool_result(body))}),
                                        ("answer", {"status": "done", "reply": "TD1 rộng 800"})])
        (done,) = worker.run_once()
        self.assertEqual(done["status"], "done")
        self.assertEqual(next(m for m in self.svc.get(self.did)["spec"]["module"] if m["id"] == "TD1")["width"], 800.0)

    def test_questions_errors_and_runaway_models_close_the_command(self):
        rev = self.svc.get(self.did)["rev"]
        cmd = self.svc.command_put(self.did, "to ra một chút", {"kind": "module", "id": "TD1"}, rev, "vi")
        (asked,) = self.use("openai", [("answer", {"status": "question", "reply": "Rộng thêm bao nhiêu mm?"})]).run_once()
        self.assertEqual((asked["status"], asked["reply"]), ("question", "Rộng thêm bao nhiêu mm?"))
        self.assertEqual(self.svc.command_list("pending"), [], "a question is not pending: the user answers it")
        waiting = self.svc.command_put(self.did, "xóa TD3", {}, rev, "vi")
        worker = self.use("openai", [mc.ModelError("down", code="model-http")])
        self.assertEqual(worker.run_once(), [], "the model could not answer: nothing closed")
        self.assertEqual(self.svc.command_get(waiting["id"])["status"], "pending", "left for Claude by chat")
        self.assertEqual(worker.run_once(), [], "and the worker waits before asking the model again")
        self.svc.command_drop(waiting["id"])
        self.svc.command_put(self.did, "xóa TD3", {}, rev, "vi")
        (looped,) = self.use("openai", [("get_design", {})] * 8).run_once()
        self.assertEqual((looped["status"], looped["reply"]), ("failed", "No answer after 8 steps"))
        self.assertEqual(self.svc.get(self.did)["rev"], rev)
        self.assertEqual(self.svc.command_get(cmd["id"])["status"], "question")

    def test_the_queue_is_done_in_order_and_a_command_claude_took_is_left_alone(self):
        rev = self.svc.get(self.did)["rev"]
        first = self.svc.command_put(self.did, "rộng 800", {"kind": "module", "id": "TD1"}, rev, "vi")
        mine = self.svc.command_put(self.did, "xóa TD3", {"kind": "module", "id": "TD3"}, rev, "vi")
        last = self.svc.command_put(self.did, "rộng 700", {"kind": "module", "id": "TD2"}, rev, "vi")
        self.assertEqual(self.svc.command_take(mine["id"], "claude")["status"], "working")
        worker = self.use("openai", [("answer", {"status": "question", "reply": "A?"}), ("answer", {"status": "question", "reply": "B?"})])
        done = worker.run_once()
        self.assertEqual([(d["id"], d["reply"]) for d in done], [(first["id"], "A?"), (last["id"], "B?")])
        self.assertEqual(self.svc.command_get(mine["id"])["worker"], "claude", "still Claude's")

    def test_a_command_the_model_cannot_reach_is_given_back(self):
        rev = self.svc.get(self.did)["rev"]
        cmd = self.svc.command_put(self.did, "xóa TD3", {}, rev, "vi")
        self.assertEqual(self.use("openai", [mc.ModelError("down", code="model-http")]).run_once(), [])
        self.assertEqual(self.svc.command_take(cmd["id"], "claude")["worker"], "claude", "pending again, Claude can take it")

    def test_it_starts_by_itself_when_a_model_is_set_else_claude_by_chat(self):
        self.assertEqual(self.svc.config.inbox_worker, "auto")
        self.svc.models.config = replace(self.svc.models.config, llm_provider=None, deepseek_api_key=None)
        self.assertIn("no model", self.svc.start_inbox_worker()["why"])
        self.assertFalse(self.svc.command_worker(), "no API: the inbox waits for Claude by chat")
        self.svc.config = replace(self.svc.config, inbox_worker="off")
        self.svc.models.config = replace(self.svc.models.config, llm_provider="anthropic", anthropic_api_key="k")
        self.assertIn("off", self.svc.start_inbox_worker()["why"])
        self.svc.config = replace(self.svc.config, inbox_worker="auto")
        started = self.svc.start_inbox_worker(every=3600)
        try:
            self.assertEqual((started["started"], started["provider"]), (True, "anthropic"))
            self.assertTrue(self.svc.command_worker())
        finally:
            self.svc._worker.stop()


if __name__ == "__main__":
    unittest.main()
