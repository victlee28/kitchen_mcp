"""The command inbox carried out by a language model, without a chat (I/O shell; ``KITCHEN_INBOX_WORKER=on``).

For each pending command the model (``KITCHEN_INBOX_PROVIDER``, else ``KITCHEN_LLM_PROVIDER``; Claude, OpenAI or any provider of
``model_gateway``) gets the sentence, what was clicked and a short list of tools: the same service calls the MCP server offers Claude.
The guard rails do not depend on the model:

* only the listed tools exist; arguments are checked by the service as for any caller;
* ``apply_change`` saves only an operation previewed in THIS command (its ``opHash``), exactly as previewed — the model cannot write
  anything else, and every save can be undone (revert);
* at most ``MAX_STEPS`` model turns per command (then ``failed``);
* the model cannot be reached (no key, network, the daily budget): the command stays pending for Claude by chat, and the worker waits
  ``PAUSE_S`` before trying the model again;
* the command is closed with ``answer``: done (with the revision), question (the user must say more) or failed.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from . import model_contract as mc
from .errors import KitchenError
from .jsonview import as_dict

logger = logging.getLogger("kitchen.inbox_worker")

MAX_STEPS = 8
PAUSE_S = 300.0              # after the model could not be reached
RESULT_CHARS = 6000          # a tool result longer than this is cut (the model sees that it was)


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


STR, INT = {"type": "string"}, {"type": "integer"}
OBJ = {"type": "object"}
IDS = {"type": "array", "items": {"type": "string"}}
TOOLS = (
    mc.ToolSpec("get_design", "The design as it is now: revision, cabinets (id, type, run, width, height, storey), runs, openings, common levels.",
                _schema({}, [])),
    mc.ToolSpec("opening_command", "Preview a sentence about a room door, window or passage at the clicked place (make, replace, edit size or "
                "sill, remove), or save the clicked door / cabinet system to the catalog. Returns status ok (operation + proposal), ask "
                "(a question), saved, not-opening or unsupported.", _schema({"text": STR}, ["text"])),
    mc.ToolSpec("interpret_edit", "Preview an edit sentence about cabinets (remove, width, doors, handles, colours, worktop, moldings...). "
                "scope_modules: the cabinets it is about (the clicked one or group). Returns status ok (operation + proposal), clarify "
                "(question + choices) or unsupported.", _schema({"text": STR, "scope_modules": IDS}, ["text"])),
    mc.ToolSpec("propose_change", "Preview an operation you write yourself (kitchen edit operation JSON, e.g. {\"op\": \"update\", \"id\": "
                "\"TD1\", \"changes\": {\"width\": 600}}). Returns the proposal with its opHash.", _schema({"op": OBJ, "scope_modules": IDS}, ["op"])),
    mc.ToolSpec("propose_template", "Preview a cabinet template against a floorplan object, e.g. {\"kind\": \"run-i\", \"structureId\": "
                "\"STRUCT-...\", \"point\": {\"x\", \"z\"}}.", _schema({"template": OBJ}, ["template"])),
    mc.ToolSpec("apply_change", "Save the operation of a preview made in this command, exactly as previewed. expect = that preview's opHash.",
                _schema({"expect": STR}, ["expect"])),
    mc.ToolSpec("answer", "Close the command: status done (reply = one line on what changed), question (reply = what the user must "
                "answer) or failed (reply = why). choices: up to 6 short answers the user can pick (a question's options, or with done "
                "the other ways it could have gone when you had to choose). Always the last call.",
                _schema({"status": {"type": "string", "enum": ["done", "question", "failed"]}, "reply": STR,
                         "choices": {"type": "array", "items": STR}}, ["status", "reply"])),
)


class InboxWorker:
    def __init__(self, svc: Any, provider: str | None = None, instructions: Callable[[], str] | None = None):
        self.svc = svc
        self.provider = provider
        self.instructions = instructions or (lambda: "")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._paused_until = 0.0

    def running(self) -> bool:
        """Started, not stopped, and not waiting after the model could not be reached."""
        return self._thread is not None and not self._stop.is_set() and time.monotonic() >= self._paused_until

    # ---------------------------------------------------------------- the loop
    def start(self, every: float = 5.0) -> None:
        """Carry out new commands every ``every`` seconds in a daemon thread (the web server's process)."""
        if self._thread is not None:
            return

        def loop() -> None:
            while not self._stop.wait(every):
                try:
                    self.run_once()
                except Exception:              # a worker loop must outlive one bad command
                    logger.exception("[INBOX] loop error")
        self._thread = threading.Thread(target=loop, daemon=True, name="inbox-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> list[dict[str, Any]]:
        """Carry out the pending commands; stop at the first one the model cannot be reached for (it stays pending)."""
        if time.monotonic() < self._paused_until:
            return []
        done = []
        for c in self.svc.command_list("pending"):
            out = self.handle(c)
            if out is None:
                self._paused_until = time.monotonic() + PAUSE_S
                break
            done.append(out)
        return done

    # ---------------------------------------------------------------- one command
    def handle(self, command: Mapping[str, Any]) -> dict[str, Any] | None:
        """The command closed (done / question / failed), or None when the model could not be reached and nothing was saved yet."""
        cid, did = str(command["id"]), str(command["designId"])
        place = dict(command.get("place") or {})
        previews: dict[str, tuple[dict[str, Any], int]] = {}
        state: dict[str, Any] = {"revision": None, "fromRev": None}
        said: dict[str, Any] = {"command": command.get("text"), "language": command.get("lang", "vi"), "clicked": place, "designId": did,
                                "revision": command.get("baseRev")}
        if command.get("replyTo"):          # the user's answer to an earlier answer: what was said and answered then
            said["answering"] = command.get("context")
        messages: list[dict[str, Any]] = [{"role": "user", "text": json.dumps(said, ensure_ascii=False)}]
        for _ in range(MAX_STEPS):
            try:
                reply = self.svc.models.ask(mc.ModelRequest(self.instructions(), tuple(messages), TOOLS, max_tokens=1500, task="inbox"),
                                            self.provider)
            except mc.ModelError as error:
                if state["revision"] is None:          # nothing saved: leave it for Claude by chat, try the model again later
                    logger.warning("[INBOX] %s left pending, the model could not answer: %s", cid, error)
                    return None
                return self._close(cid, "failed", f"Model: {error}", state["revision"])
            messages.append(reply.as_message())
            if not reply.calls:
                return self._close(cid, "failed", reply.text.strip()[:300] or "The model stopped without an answer", state["revision"])
            for call in reply.calls:
                if call.name == "answer":
                    status = call.arguments.get("status")
                    return self._close(cid, status if status in ("done", "question", "failed") else "failed",
                                       str(call.arguments.get("reply") or ""), state["revision"], call.arguments.get("choices"),
                                       state["fromRev"])
                result = self._tool(call, did, place, previews, state)
                text = json.dumps(result, ensure_ascii=False, default=str)
                messages.append({"role": "tool", "id": call.id, "name": call.name,
                                 "result": text if len(text) <= RESULT_CHARS else text[:RESULT_CHARS] + " …(cut)"})
        return self._close(cid, "failed", f"No answer after {MAX_STEPS} steps", state["revision"])

    def _close(self, cid: str, status: str, reply: str, revision: int | None, choices: Any = None,
               from_rev: int | None = None) -> dict[str, Any]:
        logger.info("[INBOX] %s -> %s: %s", cid, status, reply[:120])
        return self.svc.command_answer(cid, status, reply, revision, choices, from_rev)

    def _remember(self, out: Any, previews: dict[str, tuple[dict[str, Any], int]]) -> None:
        """Keep the operation of every preview a tool returned, by its opHash (what apply_change may save)."""
        got = as_dict(out)
        if got is None:
            return
        proposal = as_dict(got.get("proposal")) or got
        op = as_dict(got.get("operation")) or as_dict(proposal.get("operation"))
        h, base = proposal.get("opHash"), proposal.get("baseRev")
        if isinstance(h, str) and op is not None and isinstance(base, int):
            previews[h] = (dict(op), base)

    def _tool(self, call: mc.ToolCall, did: str, place: Mapping[str, Any], previews: dict[str, tuple[dict[str, Any], int]],
              state: dict[str, Any]) -> Any:
        a, s = call.arguments, self.svc
        try:
            if call.name == "get_design":
                return self._summary(did)
            if call.name == "opening_command":
                where = {k: place[k] for k in ("point", "structureId", "module") if k in place}
                out = s.opening_command(did, str(a.get("text") or ""), where, "user")
            elif call.name == "interpret_edit":
                scope = [str(x) for x in a.get("scope_modules") or []] or None
                out = s.interpret(did, str(a.get("text") or ""), None, scope, None, False, place.get("surfaces"))
            elif call.name == "propose_change":
                scope = [str(x) for x in a.get("scope_modules") or []] or None
                out = s.propose(did, dict(a.get("op") or {}), None, scope)
            elif call.name == "propose_template":
                out = s.template(did, dict(a.get("template") or {}), None)
            elif call.name == "apply_change":
                kept = previews.get(str(a.get("expect") or ""))
                if kept is None:
                    return {"error": "apply_change saves only an operation previewed in this command: give its opHash"}
                op, base = kept
                saved = s.apply(did, op, base, "inbox-worker", str(a["expect"]))
                if state["fromRev"] is None:
                    state["fromRev"] = base                 # the revision before this command's first change: the menu's undo
                state["revision"] = saved.get("rev")
                return {"saved": True, "rev": saved.get("rev")}
            else:
                return {"error": f"No tool {call.name}"}
        except KitchenError as error:
            return {"error": str(error), "code": getattr(error, "code", None)}
        except (KeyError, ValueError) as error:
            return {"error": str(error)}
        self._remember(out, previews)
        return out

    def _summary(self, did: str) -> dict[str, Any]:
        got = self.svc.get(did)
        spec = got["spec"]
        return {"revision": got["rev"],
                "cabinets": [{k: m.get(k) for k in ("id", "type", "run", "storey", "fromCorner", "width", "height", "doorStyle") if m.get(k) is not None}
                             for m in spec.get("module", [])],
                "runs": [{k: r.get(k) for k in ("id", "x", "z", "yaw") if k in r} for r in spec.get("runs", []) or []],
                "openings": [{k: o.get(k) for k in ("id", "kind", "openingType", "width", "height", "sill", "sourceElement", "removed") if k in o}
                             for o in spec.get("openings", []) or []],
                "common": {k: v for k, v in (spec.get("common") or {}).items() if k != "material"},
                "materials": (spec.get("common") or {}).get("material")}
