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
    comfyui_url: str = "http://127.0.0.1:8188"
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, root: Path = ROOT) -> "Config":
        env = os.environ if environ is None else environ
        return cls(db_path=Path(env.get("KITCHEN_DB") or root / "kitchen.db"), render_dir=Path(env.get("KITCHEN_RENDERS") or root / "renders"),
                   default_backend=env.get("KITCHEN_IMAGE_BACKEND") or "recolor", comfyui_url=env.get("COMFYUI_URL") or "http://127.0.0.1:8188",
                   deepseek_api_key=env.get("DEEPSEEK_API_KEY") or None, deepseek_model=env.get("DEEPSEEK_MODEL") or "deepseek-chat",
                   deepseek_base_url=env.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com")
