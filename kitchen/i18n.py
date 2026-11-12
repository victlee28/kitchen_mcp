"""Wording in several languages (vi, en). The tables are data (``data/i18n/<lang>.json``) passed in by the shell; this module only picks
and fills. A missing English text falls back to Vietnamese, a missing key to the key itself."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from string import Formatter
from typing import Any

from .jsonview import as_dict

LANGS = ("vi", "en")
DEFAULT_LANG = "vi"


def lang_of(value: str | None) -> str:
    """``value`` when it is a supported language, else the default."""
    return value if value in LANGS else DEFAULT_LANG


def pick(value: Any, lang: str) -> str:
    """The text of a localised value ``{"vi": ..., "en": ...}`` (a plain string is the same in every language)."""
    if isinstance(value, str):
        return value
    d = as_dict(value) or {}
    for key in (lang, DEFAULT_LANG, *LANGS):
        text = d.get(key)
        if isinstance(text, str) and text:
            return text
    return ""


class _Keep(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass(frozen=True)
class Messages:
    """``tables``: language -> key -> template (``"No cabinet {id}"``)."""
    tables: Mapping[str, Mapping[str, str]]

    def text(self, key: str, lang: str, **params: Any) -> str:
        template = (self.tables.get(lang) or {}).get(key) or (self.tables.get(DEFAULT_LANG) or {}).get(key) or key
        return template.format_map(_Keep(params))

    def table(self, lang: str) -> dict[str, str]:
        """Every key in ``lang``, the default language filling what it lacks."""
        return {**(self.tables.get(DEFAULT_LANG) or {}), **(self.tables.get(lang) or {})}

    def has(self, key: str) -> bool:
        return any(key in (t or {}) for t in self.tables.values())

    def error(self, code: str, params: Mapping[str, Any], lang: str, fallback: str) -> str:
        """The words of an error for a reader of ``lang``: ``error.<code>`` filled with ``params``, else ``fallback`` (the English message)."""
        key = f"error.{code}"
        if not self.has(key):
            return fallback
        template = (self.tables.get(lang) or {}).get(key) or (self.tables.get(DEFAULT_LANG) or {}).get(key) or ""
        names = {name for _, name, _, _ in Formatter().parse(template) if name}
        return self.text(key, lang, **dict(params)) if names <= set(params) else fallback   # a value the template names is missing: say it plainly

    def missing(self) -> dict[str, list[str]]:
        """Keys each language lacks compared with all the keys any language has."""
        keys = {k for t in self.tables.values() for k in t}
        return {lang: sorted(keys - set(self.tables.get(lang) or {})) for lang in LANGS}
