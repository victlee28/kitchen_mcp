"""The catalog items a design uses, kept with each revision (``revisions.catalog_json``) so editing the catalog never changes an old design."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .check import values_at
from .kinds import KindInfo
from .model import Catalog, Item


def used_items(spec_data: Mapping[str, Any], catalog: Catalog, kinds: Mapping[str, KindInfo]) -> list[Item]:
    """Items named by the design (the ``usedBy`` paths of each kind), plus what they reference in turn (a style's material), in catalog order."""
    wanted: set[tuple[str, str]] = set()
    for info in kinds.values():
        for path in info.used_by:
            wanted.update((info.name, str(v)) for v in values_at(spec_data, path))
    todo = list(wanted)
    while todo:
        kind, id = todo.pop()
        item = catalog.find(kind, id)
        info = kinds.get(kind)
        if item is None or info is None:
            continue
        for path, target in info.refs:
            for v in values_at(item.data, path):
                key = (target, str(v))
                if key not in wanted:
                    wanted.add(key)
                    todo.append(key)
    return [i for i in catalog.items if (i.kind, i.id) in wanted]


def with_snapshot(catalog: Catalog, snapshot: Iterable[Item]) -> Catalog:
    """The catalog an old revision is built with: its saved items replace the current ones, items it did not use stay current."""
    saved = {(i.kind, i.id): Item(i.kind, i.id, i.data, "snapshot", i.version) for i in snapshot}
    items = [saved.pop((i.kind, i.id), i) for i in catalog.items]
    return Catalog.of([*items, *saved.values()])
