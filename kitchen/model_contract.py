"""One way to ask a language model, whichever company runs it. Pure (rule R1): the request and the reply as plain data, and the
translation to and from the two wire formats every provider speaks (Anthropic Messages; the OpenAI chat format, which OpenAI, DeepSeek,
OpenRouter, Gemini's compatible endpoint and Ollama share). ``model_gateway`` sends the bytes; nothing here touches the network.

A request::

    ModelRequest(system="...", messages=[{"role": "user" | "assistant" | "tool", ...}], tools=[ToolSpec(...)], json_only=False)

Messages in the neutral form:
    {"role": "user", "text": "...", "images"?: [{"mime": "image/png", "data": base64}]}
    {"role": "assistant", "text": "...", "calls"?: [{"id", "name", "arguments": {...}}]}
    {"role": "tool", "id": <call id>, "name": <tool>, "result": <JSON-able>}
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import KitchenError
from .jsonview import as_dict, as_list

KINDS = ("anthropic", "openai")          # the two wire formats
ANTHROPIC_VERSION = "2023-06-01"


class ModelError(KitchenError):
    """A model could not answer: ``code`` model-no-key | model-no-model | model-http | model-timeout | model-bad-reply | model-budget |
    model-unknown-provider."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Mapping[str, Any]            # JSON schema of the arguments (type object)


@dataclass(frozen=True)
class ModelRequest:
    system: str
    messages: tuple[Mapping[str, Any], ...]
    tools: tuple[ToolSpec, ...] = ()
    json_only: bool = False                  # the reply must be one JSON object
    max_tokens: int = 2000
    temperature: float = 0.0
    task: str = "chat"                       # what it is for, kept in the usage ledger (edit, prompt, inbox, ...)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ModelReply:
    text: str
    calls: tuple[ToolCall, ...]
    input_tokens: int
    output_tokens: int
    stop: str                                # end | tool | length | other
    provider: str = ""
    model: str = ""
    raw_usage: Mapping[str, Any] = field(default_factory=dict[str, Any])

    def as_message(self) -> dict[str, Any]:
        """The reply as the next assistant message of the conversation."""
        out: dict[str, Any] = {"role": "assistant", "text": self.text}
        if self.calls:
            out["calls"] = [{"id": c.id, "name": c.name, "arguments": dict(c.arguments)} for c in self.calls]
        return out


def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _result_text(result: Any) -> str:
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------- Anthropic Messages
def to_anthropic(req: ModelRequest, model: str) -> dict[str, Any]:
    msgs: list[dict[str, Any]] = []
    for m in req.messages:
        role = m.get("role")
        if role == "user":
            parts: list[dict[str, Any]] = [{"type": "image", "source": {"type": "base64", "media_type": im.get("mime", "image/png"),
                                                                      "data": im.get("data", "")}} for im in (as_list(m.get("images")) or [])]
            parts.append({"type": "text", "text": str(m.get("text") or "")})
            msgs.append({"role": "user", "content": parts})
        elif role == "assistant":
            parts = [{"type": "text", "text": str(m["text"])}] if m.get("text") else []
            parts += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": dict(c.get("arguments") or {})}
                      for c in (as_list(m.get("calls")) or [])]
            msgs.append({"role": "assistant", "content": parts})
        elif role == "tool":
            block = {"type": "tool_result", "tool_use_id": m["id"], "content": _result_text(m.get("result"))}
            if msgs and msgs[-1]["role"] == "user" and all(p.get("type") == "tool_result" for p in msgs[-1]["content"]):
                msgs[-1]["content"].append(block)            # the results of one turn's calls go back in one user message
            else:
                msgs.append({"role": "user", "content": [block]})
    system = req.system + ("\n\nAnswer with ONE JSON object and nothing else." if req.json_only else "")
    body: dict[str, Any] = {"model": model, "max_tokens": req.max_tokens, "temperature": req.temperature, "system": system, "messages": msgs}
    if req.tools:
        body["tools"] = [{"name": t.name, "description": t.description, "input_schema": dict(t.parameters)} for t in req.tools]
    return body


def from_anthropic(data: Any) -> ModelReply:
    d = as_dict(data)
    if d is None or not isinstance(d.get("content"), list):
        raise ModelError("The model's reply has no content", code="model-bad-reply")
    texts: list[str] = []
    calls: list[ToolCall] = []
    for part in as_list(d.get("content")) or []:
        p = as_dict(part) or {}
        if p.get("type") == "text":
            texts.append(str(p.get("text") or ""))
        elif p.get("type") == "tool_use":
            calls.append(ToolCall(str(p.get("id") or ""), str(p.get("name") or ""), as_dict(p.get("input")) or {}))
    usage = as_dict(d.get("usage")) or {}
    stop = {"end_turn": "end", "tool_use": "tool", "max_tokens": "length", "stop_sequence": "end"}.get(str(d.get("stop_reason")), "other")
    return ModelReply("".join(texts), tuple(calls), _int(usage.get("input_tokens")), _int(usage.get("output_tokens")), stop,
                      model=str(d.get("model") or ""), raw_usage=usage)


# ---------------------------------------------------------------- OpenAI chat format
def to_openai(req: ModelRequest, model: str) -> dict[str, Any]:
    msgs: list[dict[str, Any]] = [{"role": "system", "content": req.system}] if req.system else []
    for m in req.messages:
        role = m.get("role")
        if role == "user":
            images = as_list(m.get("images")) or []
            if images:
                content: Any = [{"type": "text", "text": str(m.get("text") or "")}] + [
                    {"type": "image_url", "image_url": {"url": f"data:{im.get('mime', 'image/png')};base64,{im.get('data', '')}"}} for im in images]
            else:
                content = str(m.get("text") or "")
            msgs.append({"role": "user", "content": content})
        elif role == "assistant":
            out: dict[str, Any] = {"role": "assistant", "content": str(m.get("text") or "")}
            calls = as_list(m.get("calls")) or []
            if calls:
                out["tool_calls"] = [{"id": c["id"], "type": "function",
                                      "function": {"name": c["name"], "arguments": json.dumps(c.get("arguments") or {}, ensure_ascii=False)}}
                                     for c in calls]
            msgs.append(out)
        elif role == "tool":
            msgs.append({"role": "tool", "tool_call_id": m["id"], "content": _result_text(m.get("result"))})
    body: dict[str, Any] = {"model": model, "temperature": req.temperature, "max_tokens": req.max_tokens, "messages": msgs}
    if req.tools:
        body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": dict(t.parameters)}}
                         for t in req.tools]
    if req.json_only:
        body["response_format"] = {"type": "json_object"}
    return body


def from_openai(data: Any) -> ModelReply:
    d = as_dict(data) or {}
    choices = as_list(d.get("choices"))
    if not choices:
        raise ModelError("The model's reply has no choices", code="model-bad-reply")
    first = as_dict(choices[0]) or {}
    msg = as_dict(first.get("message")) or {}
    calls: list[ToolCall] = []
    for c in as_list(msg.get("tool_calls")) or []:
        cd = as_dict(c) or {}
        fn = as_dict(cd.get("function")) or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = {}
        calls.append(ToolCall(str(cd.get("id") or ""), str(fn.get("name") or ""), as_dict(args) or {}))
    usage = as_dict(d.get("usage")) or {}
    stop = {"stop": "end", "tool_calls": "tool", "length": "length"}.get(str(first.get("finish_reason")), "other")
    return ModelReply(str(msg.get("content") or ""), tuple(calls), _int(usage.get("prompt_tokens")), _int(usage.get("completion_tokens")),
                      stop, model=str(d.get("model") or ""), raw_usage=usage)


def first_json(text: str) -> dict[str, Any]:
    """The JSON object a model wrote (alone, or inside prose / a code fence)."""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        value = json.loads(m.group(0) if m else text)
    except ValueError as error:
        raise ModelError("The model did not answer with JSON", code="model-bad-reply") from error
    obj = as_dict(value)
    if obj is None:
        raise ModelError("The model did not answer with a JSON object", code="model-bad-reply")
    return dict(obj)


def cost(input_tokens: int, output_tokens: int, price: Mapping[str, Any] | None) -> float | None:
    """US dollars for one call at ``price`` ({"inputPerMTok", "outputPerMTok"}); None when the price is not known."""
    p = as_dict(price) or {}
    a, b = p.get("inputPerMTok"), p.get("outputPerMTok")
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return None
    return (input_tokens * float(a) + output_tokens * float(b)) / 1_000_000
