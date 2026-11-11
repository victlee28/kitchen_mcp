"""What a kind of catalog entry is. The table itself is data (``data/kinds.json``); this module only gives it a type."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..errors import InvalidInput
from ..jsonview import as_dict, as_list

ROLES = ("workshop", "user")


@dataclass(frozen=True)
class KindInfo:
    """``writers``: roles that may edit it in the app (empty: builtin files only); ``locked``: no layer may override it (mask colours);
    ``refs``: (path in an item, kind it names), e.g. ``("front", "material")`` or ``("parts[].material", "material")``;
    ``used_by``: paths in a design (spec data) that name items of this kind, e.g. ``"appliances[].model"`` (for revision snapshots)."""
    name: str
    label: Mapping[str, str]
    writers: frozenset[str]
    locked: bool = False
    refs: tuple[tuple[str, str], ...] = ()
    used_by: tuple[str, ...] = ()
    schema: str = ""


def kind_info(name: str, raw: Any) -> KindInfo:
    """One entry of ``data/kinds.json`` as a ``KindInfo`` (raises ``InvalidInput`` on a malformed entry)."""
    d = as_dict(raw)
    if d is None:
        raise InvalidInput(f"kind {name}: not an object", code="catalog-kind-invalid")
    writers = [str(w) for w in as_list(d.get("writers")) or []]
    bad = [w for w in writers if w not in ROLES]
    if bad:
        raise InvalidInput(f"kind {name}: unknown role {bad}", code="catalog-kind-invalid")
    refs: list[tuple[str, str]] = []
    for r in as_list(d.get("refs")) or []:
        pair = as_list(r)
        if pair is None or len(pair) != 2:
            raise InvalidInput(f"kind {name}: a ref is [path, kind]", code="catalog-kind-invalid")
        refs.append((str(pair[0]), str(pair[1])))
    label = as_dict(d.get("label")) or {}
    return KindInfo(name, {str(k): str(v) for k, v in label.items()}, frozenset(writers), bool(d.get("locked", False)), tuple(refs),
                    tuple(str(p) for p in as_list(d.get("usedBy")) or []), str(d.get("schema") or f"{name}.schema.json"))
