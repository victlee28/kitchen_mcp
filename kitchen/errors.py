"""Typed errors (rule R14). The core raises only these; adapters turn ``kind`` into an HTTP status / MCP error in one place.

Kinds are a closed set, ``code`` is a stable kebab-case string clients may match on, ``message`` is for people.
The classes also derive from the builtin they replaced (``ValueError``, ``KeyError``, ``RuntimeError``) so code that still
catches the builtin keeps working during the migration; new code should catch the kitchen class.
"""
from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")

VALIDATION = "validation"
CONFLICT = "conflict"
NOT_FOUND = "not-found"
UNSUPPORTED = "unsupported"
INFRASTRUCTURE = "infrastructure"
KINDS = (VALIDATION, CONFLICT, NOT_FOUND, UNSUPPORTED, INFRASTRUCTURE)

HTTP_STATUS = {VALIDATION: 400, CONFLICT: 409, NOT_FOUND: 404, UNSUPPORTED: 400, INFRASTRUCTURE: 502}


class KitchenError(Exception):
    kind = VALIDATION
    default_code = "error"

    def __init__(self, message: str = "", code: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code

    def __str__(self) -> str:                  # KeyError would otherwise show repr(message) with quotes
        return self.message

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "code": self.code, "message": self.message}


class InvalidInput(KitchenError, ValueError):
    """The request is well-formed JSON but not acceptable: a value out of range, an unknown id in a field, a rule the design breaks."""
    kind = VALIDATION
    default_code = "invalid-input"


class Conflict(KitchenError):
    """The state changed under the caller (stale base revision, operation differs from the one previewed). Reload and retry."""
    kind = CONFLICT
    default_code = "conflict"


class NotFound(KitchenError, KeyError):
    kind = NOT_FOUND
    default_code = "not-found"


class Unsupported(KitchenError, ValueError):
    """Valid request for something this build does not do (a backend that cannot take the job, a source format)."""
    kind = UNSUPPORTED
    default_code = "unsupported"


class Infrastructure(KitchenError, RuntimeError):
    """The environment failed: the database, the disk, a remote service. Not the caller's fault."""
    kind = INFRASTRUCTURE
    default_code = "infrastructure"


def kind_of(exc: BaseException) -> str | None:
    """Kind of any exception the adapters expect, including the builtins the core still raises in places; None = unexpected (a bug)."""
    if isinstance(exc, KitchenError):
        return exc.kind
    if isinstance(exc, (KeyError, FileNotFoundError)):
        return NOT_FOUND
    if isinstance(exc, ValueError):
        return VALIDATION
    return None


def http_status(exc: BaseException) -> int | None:
    kind = kind_of(exc)
    return HTTP_STATUS[kind] if kind else None


def require(value: T | None, what: str) -> T:
    """Narrow an optional field that the caller's context guarantees (R5): ``None`` becomes a typed validation error, not a TypeError."""
    if value is None:
        raise InvalidInput(f"{what} is required", code="missing-value")
    return value
