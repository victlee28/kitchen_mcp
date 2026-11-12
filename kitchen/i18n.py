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


NAME_PREFIX = "name."
WORD_FIELDS = {"part": "part.", "tier": "tier."}   # a field of a default name that is itself a word of the table
NAME_FIELDS = ("name",)                             # a field that is itself a default name
ID = r"[\w.-]+"
FREE_FIELDS = {"walls": ".+?"}                      # any other field is an id or a number (TD1, R2, 3)


class Names:
    """Default names the core writes into designs and views ("Tủ chậu", "Chính diện dãy tủ R1", "mặt trước TD1"): the text, not a key, is
    what designs keep, so a name is recognised by its wording (every ``name.*`` template of ``messages``) and worded again in another language.
    A name nobody wrote from a template (one the user typed) is not recognised and stays as it is."""

    def __init__(self, messages: Messages) -> None:
        self.messages = messages
        self._cache: dict[str, tuple[dict[str, str], list[tuple[Any, str, list[str]]]]] = {}

    def _table(self, lang: str) -> tuple[dict[str, str], list[tuple[Any, str, list[str]]]]:
        if lang in self._cache:
            return self._cache[lang]
        import re
        table = self.messages.table(lang)
        fixed: dict[str, str] = {}
        patterns: list[tuple[int, Any, str, list[str]]] = []
        for key, template in table.items():
            if not key.startswith(NAME_PREFIX):
                continue
            parts = list(Formatter().parse(template))
            fields = [f for _, f, _, _ in parts if f]
            if not fields:
                fixed.setdefault(template, key)
                continue
            rx, literal = "", 0
            for text, field, _, _ in parts:
                rx += re.escape(text)
                literal += len(text)
                if not field:
                    continue
                if field in WORD_FIELDS:
                    words = sorted((t for k, t in table.items() if k.startswith(WORD_FIELDS[field])), key=len, reverse=True)
                    rx += f"(?P<{field}>{'|'.join(re.escape(w) for w in words)})"
                    literal += 100                      # a closed list of words: tried before a free field
                else:
                    free = ".+" if field in NAME_FIELDS else FREE_FIELDS.get(field, ID)
                    rx += f"(?P<{field}>{free})"
            patterns.append((literal, re.compile(rx), key, fields))
        patterns.sort(key=lambda p: -p[0])
        out = (fixed, [(rx, key, fields) for _, rx, key, fields in patterns])
        self._cache[lang] = out
        return out

    def _word(self, text: str, prefix: str, src: str, dst: str) -> str | None:
        for key, t in self.messages.table(src).items():
            if key.startswith(prefix) and t == text:
                return self.messages.text(key, dst)
        return None

    def translate(self, text: str, src: str, dst: str) -> str | None:
        """``text`` worded in ``dst`` when it is a default name in ``src``, else None."""
        if src == dst or not text:
            return None
        fixed, patterns = self._table(src)
        if text in fixed:
            return self.messages.text(fixed[text], dst)
        for rx, key, fields in patterns:
            hit = rx.fullmatch(text)
            if hit is None:
                continue
            params: dict[str, str] = {}
            for field in fields:
                value = hit.group(field)
                if field in WORD_FIELDS:
                    word = self._word(value, WORD_FIELDS[field], src, dst)
                elif field in NAME_FIELDS:
                    word = self.translate(value, src, dst)
                else:
                    word = value
                if word is None:
                    break
                params[field] = word
            else:
                return self.messages.text(key, dst, **params)
        return None
