"""Catalog items <-> CSV (one row per item), so the workshop can keep a list (its real appliances) in a spreadsheet.

Columns are the dotted paths of the item's fields (``size.w``, ``name.vi``); a list or an object that is not split further is written as JSON
in its cell. Reading back, the kind's JSON Schema says what each column holds (number, true/false, list, text); an empty cell leaves the
field out. The first column is ``id``.
"""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Mapping
from typing import Any

from .errors import InvalidInput


def _flatten(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, Mapping) and value:
            out.update(_flatten(value, path + "."))  # pyright: ignore[reportUnknownArgumentType]
        else:
            out[path] = value
    return out


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def to_csv(items: Iterable[tuple[str, Mapping[str, Any]]]) -> str:
    """``(id, data)`` pairs as CSV text; the columns are every path any item has, in first-seen order."""
    rows = [(id, _flatten(data)) for id, data in items]
    columns: list[str] = []
    for _, flat in rows:
        columns.extend(c for c in flat if c not in columns)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", *columns])
    for id, flat in rows:
        w.writerow([id, *(_cell(flat.get(c)) for c in columns)])
    return buf.getvalue()


def _resolve(schema: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any]:
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        node: Any = root
        for part in ref[2:].split("/"):
            node = node.get(part, {}) if isinstance(node, Mapping) else {}
        return node if isinstance(node, Mapping) else {}  # pyright: ignore[reportUnknownVariableType]
    return schema


def _schema_at(root: Mapping[str, Any], path: list[str]) -> Mapping[str, Any]:
    node: Mapping[str, Any] = root
    for part in path:
        props = _resolve(node, root).get("properties")
        nxt = props.get(part) if isinstance(props, Mapping) else None
        if not isinstance(nxt, Mapping):
            return {}
        node = nxt  # pyright: ignore[reportUnknownVariableType]
    return _resolve(node, root)


def _types(schema: Mapping[str, Any]) -> set[str]:
    t = schema.get("type")
    if isinstance(t, str):
        return {t}
    if isinstance(t, list):
        return {str(x) for x in t}  # pyright: ignore[reportUnknownVariableType]
    enum = schema.get("enum")
    if isinstance(enum, list):
        return {"number" if isinstance(v, (int, float)) and not isinstance(v, bool) else "boolean" if isinstance(v, bool) else "string" for v in enum}  # pyright: ignore[reportUnknownVariableType]
    return set()


def _value(text: str, schema: Mapping[str, Any], where: str) -> Any:
    types = _types(schema)
    try:
        if types & {"array", "object"} or (not types and text[:1] in "[{"):
            return json.loads(text)
        if types <= {"integer"} and types:
            return int(text)
        if types & {"number", "integer"} and not types & {"string"}:
            n = float(text)
            return int(n) if n.is_integer() else n
        if types == {"boolean"}:
            if text.lower() not in ("true", "false", "1", "0", "có", "không"):
                raise ValueError(text)
            return text.lower() in ("true", "1", "có")
    except ValueError as err:
        raise InvalidInput(f"{where}: {text!r} is not a {'/'.join(sorted(types))} ({err})", code="catalog-bad-csv") from err
    if not types:
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


def from_csv(text: str, schema: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """CSV text back to ``(id, data)`` pairs (InvalidInput ``catalog-bad-csv`` names the row and column of a cell that does not fit)."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    rows = list(reader)
    if not rows or not rows[0] or rows[0][0].strip() != "id":
        raise InvalidInput("The first column of the CSV must be 'id'", code="catalog-bad-csv")
    header = [h.strip() for h in rows[0]]
    out: list[tuple[str, dict[str, Any]]] = []
    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        id = row[0].strip()
        data: dict[str, Any] = {}
        for col, cell in zip(header[1:], row[1:]):
            if not col or not cell.strip():
                continue
            path = col.split(".")
            node = data
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = _value(cell.strip(), _schema_at(schema, path), f"row {n}, column {col}")
        out.append((id, data))
    return out
