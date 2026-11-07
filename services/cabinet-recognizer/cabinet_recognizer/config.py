"""Đọc môi trường MỘT lần thành Config bất biến (R2). Chỉ module này đọc env."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    provider: str            # anthropic | openai (OpenAI-compatible: OpenAI, Gemini, OpenRouter...) | ollama (cục bộ)
    model: str
    api_key: str
    base_url: str
    region: str
    timeout_s: float
    max_retries: int

    @staticmethod
    def from_env() -> "Config":
        provider = os.getenv("RECOG_PROVIDER", "anthropic").strip().lower()
        default_model = {"anthropic": "claude-sonnet-5-5", "ollama": "qwen2.5vl:7b"}.get(provider, "gpt-4.1")
        default_url = {"anthropic": "https://api.anthropic.com",
                       "ollama": "http://localhost:11434/v1"}.get(provider, "https://api.openai.com/v1")
        key = os.getenv("RECOG_API_KEY") or (
            os.getenv("ANTHROPIC_API_KEY", "") if provider == "anthropic" else os.getenv("OPENAI_API_KEY", ""))
        return Config(
            provider=provider,
            model=os.getenv("RECOG_MODEL", default_model),
            api_key=key,
            base_url=os.getenv("RECOG_BASE_URL", default_url).rstrip("/"),
            region=os.getenv("RECOG_REGION", "VN"),
            timeout_s=float(os.getenv("RECOG_TIMEOUT_S", "120")),
            max_retries=int(os.getenv("RECOG_MAX_RETRIES", "1")),
        )
