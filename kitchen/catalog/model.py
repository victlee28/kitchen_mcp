"""``Item`` (one catalog entry after the layers are merged) and the read-only ``Catalog`` that core functions receive."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..errors import NotFound


@dataclass(frozen=True)
class Item:
    """One entry: ``data`` is its JSON object (validated against the kind's schema by the shell); ``source`` the layer it comes from
    (``builtin``, ``workshop``, ``user:<name>`` or ``snapshot``); ``version`` counts the edits of that entry in its layer."""
    kind: str
    id: str
    data: Mapping[str, Any]
    source: str = "builtin"
    version: int = 1

    def to_data(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id, "data": dict(self.data), "source": self.source, "version": self.version}


@dataclass(frozen=True)
class Catalog:
    """Items by kind, in a stable order (builtin order first, added items after). Never changed after it is built."""
    items: tuple[Item, ...] = ()
    _index: Mapping[tuple[str, str], Item] = field(default_factory=lambda: dict[tuple[str, str], Item](), repr=False, compare=False)

    @staticmethod
    def of(items: Iterable[Item]) -> "Catalog":
        all_items = tuple(items)
        return Catalog(all_items, {(i.kind, i.id): i for i in all_items})

    def find(self, kind: str, id: str) -> Item | None:
        return self._index.get((kind, id))

    def get(self, kind: str, id: str) -> Item:
        item = self.find(kind, id)
        if item is None:
            raise NotFound(f"No {kind} {id!r} in the catalog", code="catalog-item-not-found")
        return item

    def data(self, kind: str, id: str) -> Mapping[str, Any]:
        return self.get(kind, id).data

    def all(self, kind: str) -> list[Item]:
        return [i for i in self.items if i.kind == kind]

    def ids(self, kind: str) -> list[str]:
        return [i.id for i in self.items if i.kind == kind]

    def kinds(self) -> list[str]:
        return list(dict.fromkeys(i.kind for i in self.items))


EMPTY = Catalog.of(())
