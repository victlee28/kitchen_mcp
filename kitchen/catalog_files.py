"""Shell: the builtin catalog layer and the wording tables, read from ``data/`` once at start-up and checked before anything uses them.

Layout of ``data/``:
  kinds.json                  {kind: {label, writers, locked?, refs?, usedBy?, schema?}}
  schemas/<kind>.schema.json  JSON Schema of one item's data
  items/<kind>.json           [{"id": ..., ...data}] the builtin items of a kind
  i18n/<lang>.json            {key: template}
A malformed file stops the start (a wrong catalog is never used); the message names the file, the item and the field.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import i18n
from .catalog import BUILTIN, Entry, KindInfo, check_refs, kind_info, merge
from .errors import InvalidInput


class CatalogInvalid(InvalidInput):
    default_code = "catalog-invalid"


@dataclass(frozen=True)
class Builtin:
    kinds: dict[str, KindInfo] = field(default_factory=dict[str, KindInfo])
    schemas: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    entries: list[Entry] = field(default_factory=list[Entry])
    messages: i18n.Messages = field(default_factory=lambda: i18n.Messages({}))


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise CatalogInvalid(f"{path}: {err}") from err


def schema_errors(schema: dict[str, Any], data: Any) -> list[str]:
    """Every way ``data`` breaks ``schema``, as "<path>: <message>" (empty when it is valid)."""
    out: list[str] = []
    for e in sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in e.absolute_path) or "(item)"
        out.append(f"{where}: {e.message}")
    return out


def load_builtin(data_dir: Path) -> Builtin:
    """Read and check the builtin layer. Raises ``CatalogInvalid`` with every problem found."""
    data_dir = Path(data_dir)
    problems: list[str] = []
    kinds: dict[str, KindInfo] = {}
    schemas: dict[str, dict[str, Any]] = {}
    entries: list[Entry] = []
    kinds_file = data_dir / "kinds.json"
    raw_kinds = _read(kinds_file) if kinds_file.is_file() else {}
    for name, raw in (raw_kinds.items() if isinstance(raw_kinds, dict) else []):
        info = kind_info(str(name), raw)
        kinds[info.name] = info
        schema_path = data_dir / "schemas" / info.schema
        if not schema_path.is_file():
            problems.append(f"{schema_path}: missing schema of kind {info.name}")
            continue
        schemas[info.name] = _read(schema_path)
        items_path = data_dir / "items" / f"{info.name}.json"
        items = _read(items_path) if items_path.is_file() else []
        if not isinstance(items, list):
            problems.append(f"{items_path}: must be a list of items")
            continue
        seen: set[str] = set()
        for n, raw_item in enumerate(items):
            if not isinstance(raw_item, dict) or not isinstance(raw_item.get("id"), str) or not raw_item["id"]:
                problems.append(f"{items_path} [{n}]: an item is an object with a non-empty string id")
                continue
            item_id = raw_item["id"]
            if item_id in seen:
                problems.append(f"{items_path}: id {item_id!r} appears twice")
            seen.add(item_id)
            data = {k: v for k, v in raw_item.items() if k != "id"}
            problems += [f"{items_path} {item_id}: {m}" for m in schema_errors(schemas[info.name], data)]
            entries.append(Entry(info.name, item_id, BUILTIN, data))
    problems += [f"{p.kind} {p.id}: {p.path}: {p.message}" for p in check_refs(merge(entries), kinds)]
    tables: dict[str, dict[str, str]] = {}
    for lang in i18n.LANGS:
        path = data_dir / "i18n" / f"{lang}.json"
        table = _read(path) if path.is_file() else {}
        if not isinstance(table, dict) or not all(isinstance(v, str) for v in table.values()):
            problems.append(f"{path}: must map keys to strings")
            continue
        tables[lang] = {str(k): v for k, v in table.items()}
    if problems:
        raise CatalogInvalid("The builtin catalog is invalid:\n" + "\n".join(problems[:50]))
    return Builtin(kinds, schemas, entries, i18n.Messages(tables))
