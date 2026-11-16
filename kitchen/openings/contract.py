"""Portable data contract ``kitchen-opening/1``: a room door, window or passage located by its own axes (ADR 0005).

Rule summary (docs/adr/0005-opening-contract.md):

* ``wall_axis`` names the wall axis (the centreline of a whole straight wall) the opening sits on; ``center`` is the distance (mm)
  of the opening's centre along that axis from the axis start. Moving an opening only changes ``center``.
* ``width`` is always the hole in the wall; ``clear_width`` always the clear passage. Frames, leaves and sweeps are never stored.
* Vertical axes: the two outer ones are the hole edges (``-width/2`` and ``+width/2`` from the centre, derived); ``axes`` holds the
  middle ones relative to the centre. Horizontal axes: the outer ones are the sill (0) and the head (``height``); ``h_axes`` holds the
  middle ones measured up from the sill. ``None`` means "as the opening type's template", so a width or height change rescales them.
* Leaves tile the grid of bays: a leaf covers columns ``cols[0]..cols[1]`` and rows ``rows[0]..rows[1]`` (axis indices). A hinge
  sits on one axis of the leaf's edge; ``side`` (``+`` / ``-``) is the side of the wall axis the leaf opens to (``+`` = the axis normal
  ``(-dir.z, dir.x)``). In / out is derived from the side and the kitchen, never stored.
* Heights are relative to the finished floor of the building level (``spec.level``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

KINDS = ("door", "window", "passage")
SOURCES = ("drawn", "ai", "human")
OPERATIONS = ("swing", "top-hung", "bottom-hung", "tilt-turn", "sliding", "folding", "fixed")
HINGED = ("swing", "top-hung", "bottom-hung", "tilt-turn")      # operations that turn about a hinge axis and sweep a side
SIDES = ("+", "-")

Pt = tuple[float, float]


@dataclass(frozen=True)
class AxisRef:
    """The wall axis an opening sits on: its id plus, for a floorplan axis, the fingerprint it had when the opening was placed
    (room frame, mm) so a later change of the floorplan is noticed instead of silently moving the opening."""
    id: str
    start: Pt | None = None
    dir: Pt | None = None
    length: float | None = None

    def to_data(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id}
        if self.start is not None:
            out["start"] = [self.start[0], self.start[1]]
        if self.dir is not None:
            out["dir"] = [self.dir[0], self.dir[1]]
        if self.length is not None:
            out["length"] = self.length
        return out


@dataclass(frozen=True)
class Hinge:
    axis: str            # "v" (vertical axis) | "h" (horizontal axis)
    index: int           # index among the opening's axes of that direction, outer ones included, counted from the start / the sill

    def to_data(self) -> dict[str, Any]:
        return {"axis": self.axis, "index": self.index}


@dataclass(frozen=True)
class Leaf:
    cols: tuple[int, int]
    rows: tuple[int, int]
    operation: str
    hinge: Hinge | None = None
    side: str | None = None
    active: bool = False

    def to_data(self) -> dict[str, Any]:
        return {"cols": [self.cols[0], self.cols[1]], "rows": [self.rows[0], self.rows[1]], "operation": self.operation,
                "hinge": self.hinge.to_data() if self.hinge is not None else None, "side": self.side, "active": self.active}


@dataclass(frozen=True)
class Opening:
    id: str
    kind: str
    opening_type: str
    wall_axis: AxisRef
    center: float
    width: float
    axes: tuple[float, ...] | None
    h_axes: tuple[float, ...] | None
    leaves: tuple[Leaf, ...]
    sill: float
    height: float
    clear_width: float | None
    source: str
    unsure: tuple[str, ...] = ()
    source_element: str | None = None
    removed: bool = False
    oversize: bool = False

    def to_data(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "openingType": self.opening_type,
            "wallAxis": self.wall_axis.to_data(),
            "center": self.center,
            "width": self.width,
            "axes": list(self.axes) if self.axes is not None else None,
            "hAxes": list(self.h_axes) if self.h_axes is not None else None,
            "leaves": [leaf.to_data() for leaf in self.leaves],
            "sill": self.sill,
            "height": self.height,
            "clearWidth": self.clear_width,
            "source": self.source,
            "unsure": list(self.unsure),
            "sourceElement": self.source_element,
            "removed": self.removed,
            **({"oversize": True} if self.oversize else {}),
        }
