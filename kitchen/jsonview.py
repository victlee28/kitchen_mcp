"""Typed views of untyped JSON values (rule R5).

Data read from a file or a request is ``Any``; these give it a checked shape without copying. In Rust this is
``serde_json::Value::as_object`` / ``as_array``.
"""
from __future__ import annotations

from typing import Any, cast


def as_dict(value: Any) -> dict[str, Any] | None:
    """``value`` as a JSON object, or None when it is not one."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def as_list(value: Any) -> list[Any] | None:
    """``value`` as a JSON array, or None when it is not one."""
    return cast(list[Any], value) if isinstance(value, list) else None
