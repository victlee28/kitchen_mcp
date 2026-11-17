"""Settings the service needs, read from the environment ONCE (rule R2) and passed down as a value.

Only this module and the I/O shell (service, backends, adapters) may read ``os.environ``; core modules receive values, not the environment.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    db_path: Path
    render_dir: Path
    default_backend: str = "recolor"
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    gemini_api_key: str | None = None
    gemini_env_file: str | None = None      # a .env whose GEMINI_API_KEY / GEMINI_IMAGE_MODEL fill what the environment leaves empty
    gemini_model: str | None = None
    gemini_vision_model: str | None = None   # reads photos/drawings for recognition (text out); defaults in recognizers.py
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_timeout: float = 300.0
    gemini_image_size: str = ""
    cabinet_recognizer_url: str | None = None      # base URL of the stand-alone cabinet-recognizer service (its API keys stay in that process)
    cabinet_recognizer_timeout: float = 240.0      # the service asks the model up to three times, each with retries
    default_recognizer: str | None = None          # name used when a request names none (see recognition.choose_recognizer)
    data_dir: Path | None = None                   # the builtin catalog layer and wording (data/); None: <root>/data
    fixed_role: str | None = None                  # KITCHEN_FIXED_ROLE: every request acts as this catalog role (see kitchen.identity)
    llm_provider: str | None = None                # KITCHEN_LLM_PROVIDER: anthropic | openai | deepseek | openrouter | ollama (None: deepseek when its key is set)
    llm_model: str | None = None                   # KITCHEN_LLM_MODEL: the model of that provider (None: its default, when it has one)
    llm_base_url: str | None = None                # KITCHEN_LLM_BASE_URL: another endpoint of the same wire format (a proxy, a LAN server)
    llm_fallback: str | None = None                # KITCHEN_LLM_FALLBACK: provider[:model] tried when the first one fails
    llm_timeout: float = 60.0                      # KITCHEN_LLM_TIMEOUT (s)
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    model_budget_tokens: int = 0                   # KITCHEN_MODEL_BUDGET_TOKENS: tokens per day for all model calls (0 = no limit)
    model_budget_usd: float = 0.0                  # KITCHEN_MODEL_BUDGET_USD: dollars per day, counted with data/model-prices.json (0 = no limit)
    inbox_worker: str = "auto"                     # KITCHEN_INBOX_WORKER: auto (a model carries out the command inbox when one is set, else Claude by chat) | on | off
    inbox_provider: str | None = None              # KITCHEN_INBOX_PROVIDER: provider[:model] for the inbox worker
    openai_image_model: str | None = None          # OPENAI_IMAGE_MODEL: the image backend "openai"
    menu_commands: str = "inbox"                   # KITCHEN_MENU_COMMANDS: inbox (right-click sentences go to Claude's command inbox) | direct
    command_inbox: Path | None = None              # KITCHEN_COMMAND_INBOX: the inbox folder; None: command-inbox/ beside the database
    opening_check: str = "auto"                    # KITCHEN_OPENING_CHECK auto | on | off: a vision model takes a second look at a door built from a picture (auto: when one is set)
    opening_check_provider: str | None = None      # KITCHEN_OPENING_CHECK_PROVIDER: e.g. "anthropic" or "openai:gpt-4.1"; None = KITCHEN_LLM_PROVIDER
    mcp_token: str | None = None                   # KITCHEN_MCP_TOKEN: the key every HTTP request of the MCP server must carry (server.py --http)
    mcp_host: str = "127.0.0.1"                    # KITCHEN_MCP_HOST: where the HTTP MCP server listens (0.0.0.0: the whole LAN)
    mcp_port: int = 8766                           # KITCHEN_MCP_PORT

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, root: Path = ROOT) -> "Config":
        env = os.environ if environ is None else environ
        return cls(db_path=Path(env.get("KITCHEN_DB") or root / "kitchen.db"), render_dir=Path(env.get("KITCHEN_RENDERS") or root / "renders"),
                   default_backend=env.get("KITCHEN_IMAGE_BACKEND") or "recolor",
                   deepseek_api_key=env.get("DEEPSEEK_API_KEY") or None, deepseek_model=env.get("DEEPSEEK_MODEL") or "deepseek-chat",
                   deepseek_base_url=env.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
                   gemini_api_key=env.get("GEMINI_API_KEY") or None, gemini_env_file=env.get("GEMINI_ENV_FILE") or None,
                   gemini_model=env.get("GEMINI_IMAGE_MODEL") or None, gemini_vision_model=env.get("GEMINI_VISION_MODEL") or None,
                   gemini_base_url=(env.get("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/"),
                   gemini_timeout=float(env.get("GEMINI_TIMEOUT") or 300), gemini_image_size=env.get("GEMINI_IMAGE_SIZE") or "",
                   cabinet_recognizer_url=(env.get("CABINET_RECOGNIZER_URL") or "").strip().rstrip("/") or None,
                   cabinet_recognizer_timeout=float(env.get("CABINET_RECOGNIZER_TIMEOUT") or 240),
                   default_recognizer=(env.get("KITCHEN_RECOGNIZER") or "").strip() or None,
                   data_dir=Path(env.get("KITCHEN_DATA") or root / "data"),
                   fixed_role=(env.get("KITCHEN_FIXED_ROLE") or "").strip().lower() or None,
                   llm_provider=(env.get("KITCHEN_LLM_PROVIDER") or "").strip().lower() or None,
                   llm_model=(env.get("KITCHEN_LLM_MODEL") or "").strip() or None,
                   llm_base_url=(env.get("KITCHEN_LLM_BASE_URL") or "").strip().rstrip("/") or None,
                   llm_fallback=(env.get("KITCHEN_LLM_FALLBACK") or "").strip() or None,
                   llm_timeout=float(env.get("KITCHEN_LLM_TIMEOUT") or 60),
                   anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None, openai_api_key=env.get("OPENAI_API_KEY") or None,
                   openrouter_api_key=env.get("OPENROUTER_API_KEY") or None,
                   model_budget_tokens=int(float(env.get("KITCHEN_MODEL_BUDGET_TOKENS") or 0)),
                   model_budget_usd=float(env.get("KITCHEN_MODEL_BUDGET_USD") or 0),
                   inbox_worker={"on": "on", "1": "on", "true": "on", "yes": "on", "off": "off", "0": "off", "false": "off", "no": "off"}.get(
                       (env.get("KITCHEN_INBOX_WORKER") or "").strip().lower(), "auto"),
                   inbox_provider=(env.get("KITCHEN_INBOX_PROVIDER") or "").strip() or None,
                   openai_image_model=(env.get("OPENAI_IMAGE_MODEL") or "").strip() or None,
                   menu_commands="direct" if (env.get("KITCHEN_MENU_COMMANDS") or "").strip().lower() == "direct" else "inbox",
                   command_inbox=Path(env["KITCHEN_COMMAND_INBOX"]) if env.get("KITCHEN_COMMAND_INBOX") else None,
                   opening_check=(env.get("KITCHEN_OPENING_CHECK") or "auto").strip().lower() if (env.get("KITCHEN_OPENING_CHECK") or "auto").strip().lower() in ("auto", "on", "off") else "auto",
                   opening_check_provider=(env.get("KITCHEN_OPENING_CHECK_PROVIDER") or "").strip() or None,
                   mcp_token=(env.get("KITCHEN_MCP_TOKEN") or "").strip() or None,
                   mcp_host=(env.get("KITCHEN_MCP_HOST") or "").strip() or "127.0.0.1",
                   mcp_port=int(env.get("KITCHEN_MCP_PORT") or 8766))
