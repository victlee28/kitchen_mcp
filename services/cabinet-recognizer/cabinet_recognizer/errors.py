"""Lỗi có kiểu (R14). Lõi chỉ ném RecognizerError."""
from __future__ import annotations

from typing import Literal

Kind = Literal["validation", "conflict", "not-found", "unsupported", "infrastructure"]


class RecognizerError(ValueError):
    def __init__(self, kind: Kind, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.kind: Kind = kind
        self.code = code
        self.message = message

    def to_data(self) -> dict[str, str]:
        return {"kind": self.kind, "code": self.code, "message": self.message}


def invalid(code: str, message: str) -> RecognizerError:
    return RecognizerError("validation", code, message)


def http_status(err: RecognizerError) -> int:
    return {"validation": 422, "conflict": 409, "not-found": 404,
            "unsupported": 501, "infrastructure": 502}[err.kind]
