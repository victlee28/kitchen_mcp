"""Cổng gọi model thị giác (vỏ). Một Protocol nhỏ + các bản cài đặt.

- AnthropicClient: Claude Messages API
- OpenAICompatClient: /chat/completions kiểu OpenAI (OpenAI, Gemini qua endpoint
  OpenAI-compatible, OpenRouter, vLLM...)
- ReplayClient: trả câu trả lời đã ghi sẵn (test, chạy lại không tốn tiền)
Chỉ dùng stdlib (urllib) để không kéo thêm SDK.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any, Protocol

from .config import Config
from .errors import RecognizerError


class VisionClient(Protocol):
    def complete(self, step: str, prompt: str, images: list[bytes]) -> str:
        """Gửi câu lệnh + ảnh PNG, trả văn bản trả lời của model."""
        ...


def _post(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"content-type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RecognizerError("infrastructure", "vision-http-error", f"{e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RecognizerError("infrastructure", "vision-unreachable", str(e)) from e


def _b64(img: bytes) -> str:
    return base64.b64encode(img).decode("ascii")


class AnthropicClient:
    def __init__(self, config: Config) -> None:
        if not config.api_key:
            raise RecognizerError("infrastructure", "missing-api-key", "thiếu ANTHROPIC_API_KEY / RECOG_API_KEY")
        self.c = config

    def complete(self, step: str, prompt: str, images: list[bytes]) -> str:
        content: list[dict[str, Any]] = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(i)}}
            for i in images
        ]
        content.append({"type": "text", "text": prompt})
        data = _post(f"{self.c.base_url}/v1/messages",
                     {"x-api-key": self.c.api_key, "anthropic-version": "2023-06-01"},
                     {"model": self.c.model, "max_tokens": 4096, "temperature": 0,
                      "messages": [{"role": "user", "content": content}]},
                     self.c.timeout_s)
        parts = [p.get("text", "") for p in data.get("content", []) if p.get("type") == "text"]
        return "".join(parts)


class OpenAICompatClient:
    def __init__(self, config: Config) -> None:
        local = "localhost" in config.base_url or "127.0.0.1" in config.base_url
        if not config.api_key and not local:  # máy chủ cục bộ (Ollama, LM Studio, vLLM) không cần khóa
            raise RecognizerError("infrastructure", "missing-api-key", "thiếu RECOG_API_KEY / OPENAI_API_KEY")
        self.c = config

    def complete(self, step: str, prompt: str, images: list[bytes]) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content += [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(i)}"}}
                    for i in images]
        data = _post(f"{self.c.base_url}/chat/completions",
                     {"authorization": f"Bearer {self.c.api_key or 'local'}"},
                     {"model": self.c.model, "temperature": 0,
                      "messages": [{"role": "user", "content": content}]},
                     self.c.timeout_s)
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as e:
            raise RecognizerError("infrastructure", "vision-bad-response", str(data)[:300]) from e


class ReplayClient:
    """Trả lời theo tên bước từ một dict {step: answer_object_or_text}."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    def complete(self, step: str, prompt: str, images: list[bytes]) -> str:
        self.calls.append(step)
        if step not in self.answers:
            raise RecognizerError("not-found", "replay-missing-step", step)
        a = self.answers[step]
        return a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)


class InboxClient:
    """Chạy không cần API key: mỗi bước cần AI được ghi ra thư mục để người/AI khác trả lời.

    <dir>/pending/<step>/prompt.txt + image-1.png ...   câu hỏi đang chờ
    <dir>/answers/<step>.json                          câu trả lời (JSON) do người/AI ghi vào
    Bước chưa có câu trả lời -> ném RecognizerError(code="awaiting-answer"); chạy lại lệnh sẽ đi tiếp
    vì quy trình xác định (cùng ảnh -> cùng đường ứng viên, cùng id).
    Lần hỏi lại do câu trả lời sai hợp đồng dùng tên bước "<step>-retry".
    """

    def __init__(self, folder: str) -> None:
        from pathlib import Path
        self.dir = Path(folder)
        self.calls: list[str] = []

    def complete(self, step: str, prompt: str, images: list[bytes]) -> str:
        key = f"{step}-retry" if "Your previous answer was rejected" in prompt else step
        self.calls.append(key)
        ans = self.dir / "answers" / f"{key}.json"
        if ans.exists():
            return ans.read_text(encoding="utf-8")
        pend = self.dir / "pending" / key
        pend.mkdir(parents=True, exist_ok=True)
        (pend / "prompt.txt").write_text(prompt, encoding="utf-8")
        for i, img in enumerate(images, 1):
            (pend / f"image-{i}.png").write_bytes(img)
        raise RecognizerError("infrastructure", "awaiting-answer",
                              f"chờ câu trả lời cho bước '{key}': đọc {pend}, ghi JSON vào {ans} rồi chạy lại")


def make_client(config: Config) -> VisionClient:
    if config.provider == "anthropic":
        return AnthropicClient(config)
    if config.provider in ("openai", "gemini", "openrouter", "ollama"):
        return OpenAICompatClient(config)
    raise RecognizerError("unsupported", "unknown-provider", config.provider)
