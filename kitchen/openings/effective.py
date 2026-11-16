"""The openings a design really has (plan §3): the floorplan's, replaced or removed by the design's records that name them
(``sourceElement``), plus the design's own. Every reader of openings goes through ``effective``. Pure."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..catalog import Catalog
from ..errors import InvalidInput
from ..numeric import round_half_away
from ..palette import STRUCTURE_COLORS, STRUCTURE_FALLBACK
from ..jsonview import as_dict, as_list
from .contract import Opening
from .floorplan import raw_from_floorplan
from .normalize import normalize, upgrade_first_form
from .wall_axes import WallAxis


def own_records(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [as_dict(x) or {} for x in as_list(spec.get("openings")) or []]


def _current(record: dict[str, Any], axes: Sequence[WallAxis]) -> dict[str, Any]:
    """A record in the contract form (records saved in the first, axis-less form are upgraded on reading)."""
    if record.get("wallAxis") is None and "host" in record and not record.get("removed"):
        return upgrade_first_form(record, axes)[0]
    return record


def effective(spec: Mapping[str, Any], catalog: Catalog, axes: Sequence[WallAxis], country: str | None = None,
              with_removed: bool = False, problems: list[str] | None = None) -> list[Opening]:
    """Inherited floorplan openings first (in floorplan order), then the design's own. An override is the inherited opening with
    the record's fields laid over it; a record with ``removed: true`` hides it (kept in the list only with ``with_removed``).
    A saved record that can no longer be read (its wall axis is gone, its type unknown) is left out and named in ``problems``, so
    one stale opening never stops the design from opening."""
    def read(raw: Mapping[str, Any], source: str) -> Opening | None:
        try:
            return normalize(raw, source, catalog, axes, country, reading=True)[0]
        except InvalidInput as err:
            if problems is not None:
                problems.append(f"{raw.get('id') or raw.get('sourceElement') or '?'}: {err.code}: {err}")
            return None

    fp = as_dict(spec.get("floorplan"))
    own = [_current(r, axes) for r in own_records(spec)]
    by_source = {str(r["sourceElement"]): r for r in own if r.get("sourceElement")}
    used: set[str] = set()
    out: list[Opening] = []
    for raw, _ in (raw_from_floorplan(fp, axes, catalog) if fp else []):
        element = str(raw.get("sourceElement") or "")
        record = by_source.get(element)
        if record is None:
            found = read(raw, "drawn")
            if found is not None:
                out.append(found)
            continue
        used.add(element)
        if record.get("removed") is True:
            gone = read(record, str(record.get("source") or "human")) if with_removed else None
            if gone is not None:
                out.append(gone)
            continue
        merged = {**raw, **{k: v for k, v in record.items() if k != "unsure"}, "sourceElement": element}
        new_type = "openingType" in record and record["openingType"] != raw.get("openingType")
        new_grid = "axes" in record and len(record.get("axes") or []) != len(raw.get("axes") or [])
        if "leaves" not in record and (new_type or new_grid):
            merged.pop("leaves", None)
        found = read(merged, str(record.get("source") or "human"))
        if found is not None:
            out.append(found)
    for record in own:
        element = str(record.get("sourceElement") or "")
        if element and element in used:
            continue
        if record.get("removed") is True and not with_removed:
            continue
        found = read(record, str(record.get("source") or "human"))
        if found is not None:
            out.append(found)
    return out


def overridden(spec: Mapping[str, Any]) -> set[str]:
    """Floorplan elements the design replaces or removes."""
    return {str(r["sourceElement"]) for r in own_records(spec) if r.get("sourceElement")}


def infill_structures(spec: Mapping[str, Any], catalog: Catalog, axes: Sequence[WallAxis]) -> list[dict[str, Any]]:
    """Wall pieces that close the holes of floorplan openings the design removes (records with ``removed: true``), as floorplan
    structure records (room frame, the shape ``floorplan.structures`` gives) so both renderers draw them like the walls around."""
    fp = as_dict(spec.get("floorplan"))
    gone = {str(r["sourceElement"]) for r in own_records(spec) if r.get("removed") is True and r.get("sourceElement")}
    if not fp or not gone:
        return []
    height = float(fp.get("height") or 3000.0)
    out: list[dict[str, Any]] = []
    for raw, _ in raw_from_floorplan(fp, axes, catalog):
        element = str(raw.get("sourceElement") or "")
        if element not in gone:
            continue
        axis = next((a for a in axes if a.id == str((as_dict(raw.get("wallAxis")) or {}).get("id") or "")), None)
        if axis is None:
            continue
        center, width = float(raw["center"]), float(raw["width"])
        half = axis.thickness_at(center) / 2
        pts = [axis.point(center - width / 2, -half), axis.point(center + width / 2, -half), axis.point(center + width / 2, half),
               axis.point(center - width / 2, half)]
        out.append({"id": f"STRUCT-{element}-infill", "sourceElement": f"{element}-infill", "kind": "wall", "tag": "wall",
                    "outline": [{"x": round_half_away(p[0], 3), "z": round_half_away(p[1], 3)} for p in pts], "base": 0.0, "height": height,
                    "heightSource": "assumed", "membership": "adjacent", "color": STRUCTURE_COLORS.get("wall", STRUCTURE_FALLBACK)})
    return out
