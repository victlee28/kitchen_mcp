"""Wording of what the core reports to people (findings, summaries, default names): the core names a key and its values, the words are
data (``data/i18n``, key -> template). ``say`` gives the Vietnamese text the API has always returned; the shell re-words a ``{key, params}``
in the reader's language (``service``)."""
from __future__ import annotations

from typing import Any

from . import builtin
from .i18n import DEFAULT_LANG


def say(key: str, **params: Any) -> str:
    """The text of ``key`` filled with ``params``, in the default language (Vietnamese)."""
    return builtin.MESSAGES.text(key, DEFAULT_LANG, **params)


def finding(rule: str, severity: str, modules: list[str], key: str, **params: Any) -> dict[str, Any]:
    """A finding of a check: what it always held (rule, severity, modules, content) plus the key and values it was worded from."""
    return {"rule": rule, "severity": severity, "module": modules, "content": say(key, **params), "key": key, "params": params}
