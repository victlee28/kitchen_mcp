"""Data zone: the builtin catalog layer and the wording, read once from ``data/`` (next to the package) when the program starts.

This is the default every core function falls back to when it is not handed the merged catalog (tests, golden cases, scripts); the
service always passes the merged catalog (builtin + workshop + user). The Rust port embeds the same files (``include_str!``).
Only JSON is parsed here; the full check (schemas, references) is ``kitchen.catalog_files.load_builtin``, run by the service at start.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import i18n
from .catalog import BUILTIN, Catalog, Entry, KindInfo, kind_info, merge

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Raw:
    """What ``data/`` holds, parsed but not checked. ``problems``: files that could not be read as expected."""
    kinds: dict[str, KindInfo] = field(default_factory=dict[str, KindInfo])
    schemas: dict[str, Any] = field(default_factory=dict[str, Any])
    items: dict[str, list[Any]] = field(default_factory=dict[str, list[Any]])
    tables: dict[str, dict[str, str]] = field(default_factory=dict[str, dict[str, str]])
    problems: list[str] = field(default_factory=list[str])


def _json(path: Path, problems: list[str], default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        problems.append(f"{path}: {err}")
        return default


def read(data_dir: Path = DATA_DIR) -> Raw:
    data_dir = Path(data_dir)
    problems: list[str] = []
    raw = _json(data_dir / "kinds.json", problems, {})
    kinds = {str(k): kind_info(str(k), v) for k, v in (raw.items() if isinstance(raw, dict) else [])}
    schemas: dict[str, Any] = {}
    items: dict[str, list[Any]] = {}
    for name, info in kinds.items():
        schema_path = data_dir / "schemas" / info.schema
        if not schema_path.is_file():
            problems.append(f"{schema_path}: missing schema of kind {name}")
        schemas[name] = _json(schema_path, problems, {})
        got = _json(data_dir / "items" / f"{name}.json", problems, [])
        if not isinstance(got, list):
            problems.append(f"{data_dir / 'items' / f'{name}.json'}: must be a list of items")
            got = []
        items[name] = got
    tables: dict[str, dict[str, str]] = {}
    for lang in i18n.LANGS:
        table = _json(data_dir / "i18n" / f"{lang}.json", problems, {})
        if not isinstance(table, dict) or not all(isinstance(v, str) for v in table.values()):
            problems.append(f"{data_dir / 'i18n' / f'{lang}.json'}: must map keys to strings")
            table = {}
        tables[lang] = {str(k): str(v) for k, v in table.items()}
    return Raw(kinds, schemas, items, tables, problems)


def entries(raw: Raw) -> list[Entry]:
    """The builtin rows (items without a usable id are skipped here; ``catalog_files`` reports them)."""
    out: list[Entry] = []
    for kind, items in raw.items.items():
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("id"), str) and it["id"]:
                out.append(Entry(kind, it["id"], BUILTIN, {k: v for k, v in it.items() if k != "id"}))
    return out


RAW = read()
KINDS: dict[str, KindInfo] = RAW.kinds
CATALOG: Catalog = merge(entries(RAW))
MESSAGES = i18n.Messages(RAW.tables)
