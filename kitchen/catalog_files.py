"""Shell: the builtin catalog layer and the wording tables, read from ``data/`` once at start-up and checked before anything uses them.

Layout of ``data/``:
  kinds.json                  {kind: {label, writers, locked?, refs?, usedBy?, schema?}}
  schemas/<kind>.schema.json  JSON Schema of one item's data
  items/<kind>.json           [{"id": ..., ...data}] the builtin items of a kind
  i18n/<lang>.json            {key: template}
A malformed file stops the start (a wrong catalog is never used); the message names the file, the item and the field.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import builtin, i18n
from .catalog import BUILTIN, Entry, KindInfo, check_refs, merge
from .errors import InvalidInput


class CatalogInvalid(InvalidInput):
    default_code = "catalog-invalid"


@dataclass(frozen=True)
class Builtin:
    kinds: dict[str, KindInfo] = field(default_factory=dict[str, KindInfo])
    schemas: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    entries: list[Entry] = field(default_factory=list[Entry])
    messages: i18n.Messages = field(default_factory=lambda: i18n.Messages({}))


def schema_errors(schema: dict[str, Any], data: Any) -> list[str]:
    """Every way ``data`` breaks ``schema``, as "<path>: <message>" (empty when it is valid)."""
    out: list[str] = []
    for e in sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in e.absolute_path) or "(item)"
        out.append(f"{where}: {e.message}")
    return out


def load_builtin(data_dir: Path) -> Builtin:
    """Read and check the builtin layer. Raises ``CatalogInvalid`` with every problem found."""
    raw = builtin.read(Path(data_dir))
    problems = list(raw.problems)
    entries: list[Entry] = []
    for kind, items in raw.items.items():
        seen: set[str] = set()
        for n, item in enumerate(items):
            where = f"items/{kind}.json"
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                problems.append(f"{where} [{n}]: an item is an object with a non-empty string id")
                continue
            item_id = item["id"]
            if item_id in seen:
                problems.append(f"{where}: id {item_id!r} appears twice")
            seen.add(item_id)
            data = {k: v for k, v in item.items() if k != "id"}
            problems += [f"{where} {item_id}: {m}" for m in schema_errors(raw.schemas.get(kind) or {}, data)]
            entries.append(Entry(kind, item_id, BUILTIN, data))
    problems += [f"{p.kind} {p.id}: {p.path}: {p.message}" for p in check_refs(merge(entries), raw.kinds)]
    if problems:
        raise CatalogInvalid("The builtin catalog is invalid:\n" + "\n".join(problems[:50]))
    return Builtin(raw.kinds, raw.schemas, entries, i18n.Messages(raw.tables))
