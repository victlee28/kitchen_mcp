"""The one door to language models (I/O shell): which provider and model, the key, the HTTP call, the usage ledger, the daily budget and
the fallback provider. ``model_contract`` builds and reads the messages; every model call of the app goes through ``ModelGateway.ask``.

Providers (``KITCHEN_LLM_PROVIDER``, or ``provider:model``):
    anthropic   Anthropic Messages API            ANTHROPIC_API_KEY
    openai      OpenAI                            OPENAI_API_KEY
    deepseek    DeepSeek (OpenAI format)          DEEPSEEK_API_KEY   (the provider used before, kept when nothing else is set)
    openrouter  OpenRouter (OpenAI format)        OPENROUTER_API_KEY
    ollama      a local Ollama (OpenAI format)    no key
``KITCHEN_LLM_BASE_URL`` points the chosen provider at another endpoint of the same format (a proxy, a server on the LAN).
Keys never reach the ledger, the logs or the replies.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from . import model_contract as mc
from .config import Config

logger = logging.getLogger("kitchen.models")

Transport = Callable[[str, Mapping[str, str], Mapping[str, Any], float], Any]
DEFAULT_MODEL = {"anthropic": "claude-sonnet-5-5"}       # others: KITCHEN_LLM_MODEL (or the provider's own setting, e.g. DEEPSEEK_MODEL)


def _http(url: str, headers: Mapping[str, str], body: Mapping[str, Any], timeout: float) -> Any:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:400].decode("utf-8", "replace")
        raise mc.ModelError(f"The model service answered {e.code}: {detail}", code="model-http", params={"status": e.code}) from e
    except TimeoutError as e:
        raise mc.ModelError(f"The model did not answer within {timeout:.0f} s", code="model-timeout") from e
    except (urllib.error.URLError, ConnectionError) as e:
        raise mc.ModelError(f"Cannot reach the model service: {getattr(e, 'reason', e)}", code="model-http") from e


class ModelGateway:
    def __init__(self, config: Config, ledger: str | Path, prices: Mapping[str, Any] | None = None, transport: Transport | None = None,
                 clock: Callable[[], str] | None = None):
        self.config = config
        self.ledger = Path(ledger)
        self.prices = dict(prices or {})
        self.transport = transport or _http
        self.clock = clock or (lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    # ---------------------------------------------------------------- which model
    def _providers(self) -> dict[str, dict[str, Any]]:
        c = self.config
        return {"anthropic": {"kind": "anthropic", "base": "https://api.anthropic.com/v1", "key": c.anthropic_api_key},
                "openai": {"kind": "openai", "base": "https://api.openai.com/v1", "key": c.openai_api_key},
                "deepseek": {"kind": "openai", "base": c.deepseek_base_url, "key": c.deepseek_api_key, "model": c.deepseek_model},
                "openrouter": {"kind": "openai", "base": "https://openrouter.ai/api/v1", "key": c.openrouter_api_key},
                "ollama": {"kind": "openai", "base": "http://localhost:11434/v1", "key": "ollama"}}

    def primary(self) -> str | None:
        """``provider[:model]`` used when a call names none: KITCHEN_LLM_PROVIDER, else DeepSeek when its key is set (as before)."""
        c = self.config
        if c.llm_provider:
            return c.llm_provider + (f":{c.llm_model}" if c.llm_model and ":" not in c.llm_provider else "")
        return "deepseek" if c.deepseek_api_key else None

    def resolve(self, spec: str) -> dict[str, Any]:
        """``provider[:model]`` -> {name, kind, base, key, model}; refuses an unknown provider, a missing key or model."""
        name, _, model = spec.partition(":")
        p = self._providers().get(name)
        if p is None:
            raise mc.ModelError(f"Unknown model provider {name!r}", code="model-unknown-provider", params={"provider": name})
        base = self.config.llm_base_url if (self.config.llm_base_url and name == (self.config.llm_provider or "").partition(":")[0]) else p["base"]
        model = model or (self.config.llm_model if name == (self.config.llm_provider or "").partition(":")[0] else None) \
            or p.get("model") or DEFAULT_MODEL.get(name)
        if not p["key"]:
            raise mc.ModelError(f"No API key for {name}: set it in .env", code="model-no-key", params={"provider": name})
        if not model:
            raise mc.ModelError(f"No model chosen for {name}: set KITCHEN_LLM_MODEL", code="model-no-model", params={"provider": name})
        return {"name": name, "kind": p["kind"], "base": base, "key": p["key"], "model": model}

    def available(self, spec: str | None = None) -> bool:
        target = spec or self.primary()
        if not target:
            return False
        try:
            self.resolve(target)
            return True
        except mc.ModelError:
            return False

    # ---------------------------------------------------------------- asking
    def ask(self, req: mc.ModelRequest, spec: str | None = None) -> mc.ModelReply:
        """The reply of ``spec`` (default: the primary provider); when it fails, the fallback provider's (KITCHEN_LLM_FALLBACK), said in
        the reply's ``provider``. Raises ModelError when no provider could answer. Every attempt goes into the usage ledger."""
        first = spec or self.primary()
        if not first:
            raise mc.ModelError("No model provider is set: KITCHEN_LLM_PROVIDER and its API key in .env", code="model-no-key")
        tries = [first] + ([self.config.llm_fallback] if self.config.llm_fallback and self.config.llm_fallback != first else [])
        last: mc.ModelError | None = None
        for target in tries:
            try:
                return self._call(target, req)
            except mc.ModelError as error:
                if error.code == "model-budget":
                    raise
                logger.warning("[MODEL] %s failed (%s): %s", target, error.code, error)
                last = error
        assert last is not None
        raise last

    def _call(self, spec: str, req: mc.ModelRequest) -> mc.ModelReply:
        p = self.resolve(spec)
        self._check_budget()
        if p["kind"] == "anthropic":
            url, headers, body = (p["base"] + "/messages", {"x-api-key": p["key"], "anthropic-version": mc.ANTHROPIC_VERSION},
                                  mc.to_anthropic(req, p["model"]))
        else:
            url, headers, body = p["base"] + "/chat/completions", {"Authorization": f"Bearer {p['key']}"}, mc.to_openai(req, p["model"])
        started = time.monotonic()
        try:
            data = self.transport(url, headers, body, self.config.llm_timeout)
            reply = mc.from_anthropic(data) if p["kind"] == "anthropic" else mc.from_openai(data)
        except mc.ModelError as error:
            self._record(req.task, p["name"], p["model"], 0, 0, time.monotonic() - started, error.code)
            raise
        self._record(req.task, p["name"], p["model"], reply.input_tokens, reply.output_tokens, time.monotonic() - started, None)
        return mc.ModelReply(reply.text, reply.calls, reply.input_tokens, reply.output_tokens, reply.stop, p["name"],
                             reply.model or p["model"], reply.raw_usage)

    # ---------------------------------------------------------------- usage, cost and the daily budget
    def _price(self, provider: str, model: str) -> Mapping[str, Any] | None:
        by_provider = self.prices.get(provider)
        return by_provider.get(model) if isinstance(by_provider, dict) else None

    def _record(self, task: str, provider: str, model: str, tin: int, tout: int, seconds: float, error: str | None) -> None:
        line = {"at": self.clock(), "task": task, "provider": provider, "model": model, "inputTokens": tin, "outputTokens": tout,
                "usd": mc.cost(tin, tout, self._price(provider, model)), "seconds": round(seconds, 2), "ok": error is None,
                **({"error": error} if error else {})}
        try:
            self.ledger.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as e:          # a ledger that cannot be written must not stop the work
            logger.warning("[MODEL] usage ledger not written: %s", e)

    def usage(self, day: str | None = None) -> dict[str, Any]:
        """Totals of one day (UTC, ``YYYY-MM-DD``; default today): calls, tokens, dollars (calls with a known price), per provider."""
        day = day or self.clock()[:10]
        out: dict[str, Any] = {"day": day, "calls": 0, "failed": 0, "inputTokens": 0, "outputTokens": 0, "usd": 0.0, "byProvider": {}}
        if not self.ledger.exists():
            return out
        for raw in self.ledger.read_text(encoding="utf-8").splitlines():
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if not str(line.get("at", "")).startswith(day):
                continue
            out["calls"] += 1
            out["failed"] += 0 if line.get("ok") else 1
            out["inputTokens"] += int(line.get("inputTokens") or 0)
            out["outputTokens"] += int(line.get("outputTokens") or 0)
            out["usd"] += float(line.get("usd") or 0)
            per = out["byProvider"].setdefault(line.get("provider", "?"), {"calls": 0, "tokens": 0, "usd": 0.0})
            per["calls"] += 1
            per["tokens"] += int(line.get("inputTokens") or 0) + int(line.get("outputTokens") or 0)
            per["usd"] += float(line.get("usd") or 0)
        out["usd"] = round(out["usd"], 4)
        return out

    def _check_budget(self) -> None:
        c = self.config
        if not c.model_budget_tokens and not c.model_budget_usd:
            return
        today = self.usage()
        tokens = today["inputTokens"] + today["outputTokens"]
        if c.model_budget_tokens and tokens >= c.model_budget_tokens:
            raise mc.ModelError(f"Today's model budget is used up ({tokens} of {c.model_budget_tokens} tokens)", code="model-budget",
                                params={"used": tokens, "budget": c.model_budget_tokens})
        if c.model_budget_usd and today["usd"] >= c.model_budget_usd:
            raise mc.ModelError(f"Today's model budget is used up (${today['usd']:.2f} of ${c.model_budget_usd:.2f})", code="model-budget",
                                params={"used": today["usd"], "budget": c.model_budget_usd})
