"""Stored rows (``Entry``) of every layer -> one ``Catalog``: a later layer replaces an item of an earlier one with the same id, and a
disabled row hides it."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .model import Catalog, Item

BUILTIN = "builtin"
WORKSHOP = "workshop"
USER_PREFIX = "user:"


def user_scope(name: str = "default") -> str:
    return USER_PREFIX + name


def layer_rank(scope: str) -> int:
    """builtin 0 < workshop 1 < user 2; anything else is not a layer (-1)."""
    if scope == BUILTIN:
        return 0
    if scope == WORKSHOP:
        return 1
    return 2 if scope.startswith(USER_PREFIX) else -1


@dataclass(frozen=True)
class Entry:
    """One row of one layer. ``disabled``: hides the item of a lower layer (and this row's own data is ignored)."""
    kind: str
    id: str
    scope: str
    data: Mapping[str, Any]
    version: int = 1
    disabled: bool = False


def merge(entries: Iterable[Entry], scopes: Iterable[str] | None = None) -> Catalog:
    """The catalog seen through ``scopes`` (default: every scope given). Order: the first layer an item appears in decides its place,
    so builtin order is kept and items a workshop or user adds come after."""
    wanted = set(scopes) if scopes is not None else None
    rows = [e for e in entries if layer_rank(e.scope) >= 0 and (wanted is None or e.scope in wanted)]
    order: dict[tuple[str, str], int] = {}
    top: dict[tuple[str, str], Entry] = {}
    for n, e in enumerate(sorted(rows, key=lambda e: layer_rank(e.scope))):
        key = (e.kind, e.id)
        order.setdefault(key, n)
        top[key] = e
    items = [Item(e.kind, e.id, e.data, e.scope, e.version) for _, e in sorted(top.items(), key=lambda kv: order[kv[0]]) if not e.disabled]
    return Catalog.of(items)
