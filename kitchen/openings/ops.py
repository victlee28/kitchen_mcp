"""Pure data operations on a design's opening records (``spec.openings``)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import InvalidInput, NotFound
from ..jsonview import as_dict, as_list


def _items(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [as_dict(item) or {} for item in as_list(data.get("openings")) or []]


def add(data: Mapping[str, Any], opening: Mapping[str, Any]) -> dict[str, Any]:
    items = _items(data)
    if any(item.get("id") == opening.get("id") for item in items):
        raise InvalidInput(f"Opening id {opening.get('id')!r} already exists", code="opening-id-duplicate", params={"id": str(opening.get("id"))})
    element = opening.get("sourceElement")
    if element and any(item.get("sourceElement") == element for item in items):
        raise InvalidInput(f"Floorplan opening {element!r} already has a record", code="opening-source-duplicate", params={"id": str(element)})
    return {**data, "openings": [*items, dict(opening)]}


def update(data: Mapping[str, Any], opening_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
    if changes.get("id", opening_id) != opening_id:
        raise InvalidInput("update-opening cannot change an opening id", code="opening-id-change")
    items = _items(data)
    for index, item in enumerate(items):
        if item.get("id") == opening_id:
            items[index] = {**item, **changes, "id": opening_id}
            return {**data, "openings": items}
    raise NotFound(f"No opening {opening_id!r}", code="opening-not-found", params={"id": opening_id})


def remove(data: Mapping[str, Any], opening_id: str) -> dict[str, Any]:
    items = _items(data)
    kept = [item for item in items if item.get("id") != opening_id]
    if len(kept) == len(items):
        raise NotFound(f"No opening {opening_id!r}", code="opening-not-found", params={"id": opening_id})
    return {**data, "openings": kept}


def reset(data: Mapping[str, Any], source_element: str) -> dict[str, Any]:
    """Drop the design's record for a floorplan opening: it is again exactly as drawn."""
    items = _items(data)
    kept = [item for item in items if item.get("sourceElement") != source_element]
    if len(kept) == len(items):
        raise NotFound(f"Floorplan opening {source_element!r} has no record in this design", code="opening-not-found", params={"id": source_element})
    return {**data, "openings": kept}


def replace(data: Mapping[str, Any], opening_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """Put a whole new record in place of ``opening_id`` (no field of the old one survives)."""
    items = _items(data)
    for index, item in enumerate(items):
        if item.get("id") == opening_id:
            items[index] = {**record, "id": opening_id}
            return {**data, "openings": items}
    raise NotFound(f"No opening {opening_id!r}", code="opening-not-found", params={"id": opening_id})
