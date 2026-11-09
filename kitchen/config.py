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
                   default_recognizer=(env.get("KITCHEN_RECOGNIZER") or "").strip() or None)
