"""Who may write which kind in which layer, and references between items (a style naming a material that does not exist)."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..errors import InvalidInput
from ..jsonview import as_dict, as_list
from .kinds import KindInfo
from .merge import WORKSHOP, user_scope
from .model import Catalog


@dataclass(frozen=True)
class Problem:
    kind: str
    id: str
    path: str
    message: str

    def to_data(self) -> dict[str, str]:
        return {"kind": self.kind, "id": self.id, "path": self.path, "message": self.message}


def scope_for(role: str, user: str = "default") -> str:
    """The layer a role writes: the workshop its own, a user theirs."""
    if role == "workshop":
        return WORKSHOP
    if role == "user":
        return user_scope(user)
    raise InvalidInput(f"Unknown role {role!r}", code="bad-role")


def check_write(info: KindInfo, role: str) -> None:
    """Raises when ``role`` may not edit kind ``info`` (locked kinds and kinds without that role among their writers)."""
    if info.locked or role not in info.writers:
        raise InvalidInput(f"The role {role} may not edit {info.name}", code="catalog-not-allowed")


def values_at(data: Any, path: str) -> list[Any]:
    """The values a dotted path reaches; a segment ending in ``[]`` walks every element of a list (``parts[].material``)."""
    current: list[Any] = [data]
    for segment in (s for s in path.split(".") if s):
        many = segment.endswith("[]")
        name = segment[:-2] if many else segment
        nxt: list[Any] = []
        for value in current:
            obj = as_dict(value)
            if obj is None or name not in obj:
                continue
            got = obj[name]
            if many:
                nxt.extend(as_list(got) or [])
            else:
                nxt.append(got)
        current = nxt
    out: list[Any] = []
    for v in current:
        seq = as_list(v)
        out.extend(seq if seq is not None else [v])
    return [v for v in out if v is not None and v != ""]


def check_refs(catalog: Catalog, kinds: Mapping[str, KindInfo], only: Iterable[str] | None = None) -> list[Problem]:
    """Every reference that names an item missing from ``catalog``; ``only``: check the items of these kinds only."""
    wanted = set(only) if only is not None else None
    problems: list[Problem] = []
    for item in catalog.items:
        info = kinds.get(item.kind)
        if info is None or (wanted is not None and item.kind not in wanted):
            continue
        for path, target in info.refs:
            for value in values_at(item.data, path):
                if catalog.find(target, str(value)) is None:
                    problems.append(Problem(item.kind, item.id, path, f"{target} {value!r} does not exist"))
    return problems
