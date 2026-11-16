"""Application facade for listing and previewing room openings (shell: reads the store)."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import geometry, openings, roomctx
from .catalog import Catalog
from .openings.types import for_kind
from .spec import to_data
from .store import Store


class OpeningService:
    """Resolve opening data against a stored design and its catalog snapshot."""

    def __init__(
        self,
        store: Store,
        catalog: Callable[[], Catalog],
        catalog_for_revision: Callable[[str, int], Catalog],
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._catalog_for_revision = catalog_for_revision

    def list_openings(self, design_id: str, revision: int | None = None, country: str | None = None) -> dict[str, Any]:
        """Every opening the design has (floorplan ones, overridden ones, its own), each with its wall axis, the side it opens to
        seen from the kitchen, and whether it is still drawn as imported."""
        spec, stored_revision = self._store.get(design_id, revision)
        catalog = self._catalog_for_revision(design_id, stored_revision)
        lsau, lphai = geometry.wall_length(spec)
        data = to_data(spec)
        axes = openings.wall_axes.for_spec(data, lsau, lphai)
        own = openings.overridden(data) | {o.id for o in spec.openings}
        items = []
        problems: list[str] = []
        for item in openings.effective(data, catalog, axes, country or spec.country, problems=problems):
            axis = openings.wall_axes.find(item.wall_axis, axes)
            items.append({**item.to_data(), "asDrawn": item.id not in own and (item.source_element or "") not in own,
                          "opens": [openings.facing(leaf.side, axis) for leaf in item.leaves]})
        return {"id": design_id, "rev": stored_revision, "openings": items, "problems": problems,
                "wallAxes": [{"id": a.id, "start": list(a.start), "dir": list(a.dir), "length": a.length, "frame": a.frame,
                              "walls": list(a.sources()), **self._room_stretch(a)} for a in axes]}

    @staticmethod
    def _room_stretch(axis: Any) -> dict[str, Any]:
        """``room: [s0, s1]``: the stretch of a floorplan axis between the room's inner corners (the axis may run on past them)."""
        if axis.frame != "room" or not axis.segments:
            return {}
        return {"room": [axis.segments[0].s0, axis.segments[-1].s1]}

    def opening_types(self, country: str | None = None) -> dict[str, Any]:
        catalog = self._catalog()
        return {"country": country, "items": [*for_kind(catalog, "door"), *for_kind(catalog, "window"), *for_kind(catalog, "passage")]}

    def preview_opening(
        self,
        design_id: str,
        raw: Mapping[str, Any],
        revision: int | None = None,
        country: str | None = None,
    ) -> dict[str, Any]:
        """Normalize a draft opening and derive its shape (kitchen frame) without saving it."""
        spec, stored_revision = self._store.get(design_id, revision)
        catalog = self._catalog_for_revision(design_id, stored_revision)
        scene = geometry.compile_spec(spec, catalog)
        data = to_data(spec)
        axes = openings.wall_axes.for_spec(data, scene.lsau, scene.lphai)
        opening, notes = openings.normalize(raw, str(raw.get("source") or "human"), catalog, axes, country or spec.country)
        axis = openings.wall_axes.find(opening.wall_axis, axes)
        if axis is not None and axis.frame == "room":
            context = roomctx.for_spec(spec, scene.lsau, scene.lphai)
            axis = axis.in_kitchen(context.placement.to_kitchen) if context is not None else None
        shaped = openings.shape(opening, axis, catalog.data("opening-type", opening.opening_type)) if axis is not None else None
        return {"id": design_id, "rev": stored_revision, "opening": opening.to_data(), "shape": shaped, "notes": notes}
