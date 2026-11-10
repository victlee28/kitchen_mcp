"""Chạy lại một ca hộp thư đã ghi (ảnh + câu trả lời từng bước) qua đúng quy trình nhận diện, không gọi model."""
import json
from pathlib import Path
from typing import Any

from cabinet_recognizer.errors import RecognizerError
from cabinet_recognizer.pipeline import recognize_auto


class RecordedAnswers:
    """Trả câu trả lời đã ghi theo tên bước; lần hỏi lại (câu trả lời trước sai hợp đồng) dùng "<bước>-retry" như hộp thư."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    def complete(self, step: str, prompt: str, images: list[bytes]) -> str:
        key = f"{step}-retry" if "Your previous answer was rejected" in prompt else step
        self.calls.append(key)
        if key not in self.answers:
            raise RecognizerError("not-found", "replay-missing-step", key)
        a = self.answers[key]
        return a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)


def replay_case(image: Path, case: dict[str, Any]) -> dict[str, Any]:
    return recognize_auto(image.read_bytes(), RecordedAnswers(case["answers"]), region=case.get("region", "VN"))["spec"]
