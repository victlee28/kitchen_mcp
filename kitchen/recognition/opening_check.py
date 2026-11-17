"""A second look at a door or window built from a picture (proposal "nhận diện cửa chính xác hơn", P4). Pure (rule R1).

The preview's opening is drawn (the line render of its camera view) and shown to a vision model next to the picture, with what was built
said in words. The model answers what differs, as corrections of what was seen (``Correction``); the corrected opening is matched and
placed again, once. The wording of the question is the catalog text ``prompt-text/opening-check``; this module only fills it and reads
the answer. Nothing here calls a model.

Answer::

    {"same": true | false, "corrections": {"style"?, "leaves"?, "transomPanes"?, "handles"?: [leaf index], "fronts"?: [leaf index],
     "axesRatio"?: [0..1], "hAxesRatio"?: [0..1]}, "notes"?: ["..."]}
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..jsonview import as_dict, as_list
from . import opening_match
from .openings import PANEL_OPS, STYLES, Panel, PhotoOpening

MAX_LEAVES = 8


@dataclass(frozen=True)
class Correction:
    same: bool
    style: str | None = None
    leaves: int | None = None
    transom_panes: int | None = None
    handles: tuple[int, ...] | None = None
    fronts: tuple[int, ...] | None = None
    axes_ratio: tuple[float, ...] | None = None
    h_axes_ratio: tuple[float, ...] | None = None
    notes: tuple[str, ...] = ()

    def changes(self) -> list[str]:
        """What it changes, in words (for the preview's notes)."""
        out: list[str] = []
        for name, value in (("style", self.style), ("leaves", self.leaves), ("transomPanes", self.transom_panes), ("handles", self.handles),
                            ("fronts", self.fronts), ("axesRatio", self.axes_ratio), ("hAxesRatio", self.h_axes_ratio)):
            if value is not None:
                out.append(f"{name}={list(value) if isinstance(value, tuple) else value}")
        return out


def describe(seen: PhotoOpening, type_id: str, label: str) -> str:
    """What was built, in words the model compares with the picture."""
    f = opening_match.Features(seen.kind, seen.style, seen.leaves, bool(seen.h_axes_ratio), seen.transom_panes,
                               seen.axes_ratio, *_panel_lists(seen.panels))
    return (f"{label} ({type_id}): {opening_match.describe(f)}; vertical dividers at {list(seen.axes_ratio)} of the width from the left; "
            f"horizontal dividers at {list(seen.h_axes_ratio)} of the height from the sill.")


def question(template: str, seen: PhotoOpening, type_id: str, label: str) -> str:
    """The catalog text with ``{built}`` replaced by what was built."""
    return template.replace("{built}", describe(seen, type_id, label))


def _ints(value: Any, top: int) -> tuple[int, ...] | None:
    items = as_list(value)
    if items is None:
        return None
    got = [v for v in items if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < top]
    return tuple(sorted(set(got))) if len(got) == len(items) else None


def _ratios(value: Any) -> tuple[float, ...] | None:
    items = as_list(value)
    if items is None:
        return None
    got = [float(v) for v in items if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 < float(v) < 1.0]
    return tuple(sorted(got)) if len(got) == len(items) else None


def parse(answer: Any) -> Correction | None:
    """The model's answer, checked; None when it is not one (the preview then stays as it is). Malformed corrections are dropped one by one."""
    d = as_dict(answer)
    if d is None or not isinstance(d.get("same"), bool):
        return None
    c = as_dict(d.get("corrections")) or {}
    style = c.get("style") if c.get("style") in STYLES else None
    leaves = c.get("leaves") if isinstance(c.get("leaves"), int) and not isinstance(c.get("leaves"), bool) and 0 <= c["leaves"] <= MAX_LEAVES else None
    panes = c.get("transomPanes")
    panes = panes if isinstance(panes, int) and not isinstance(panes, bool) and 1 <= panes <= 8 else None
    notes = tuple(str(n)[:200] for n in as_list(d.get("notes")) or [] if isinstance(n, str))[:5]
    return Correction(d["same"], style, leaves, panes, _ints(c.get("handles"), MAX_LEAVES), _ints(c.get("fronts"), MAX_LEAVES),
                      _ratios(c.get("axesRatio")), _ratios(c.get("hAxesRatio")), notes)


def _panel_lists(panels: tuple[Panel, ...] | None) -> tuple[tuple[int, ...] | None, tuple[int, ...] | None]:
    if panels is None:
        return None, None
    main = [p for p in panels if p.row == 0]
    return tuple(i for i, p in enumerate(main) if p.handle), tuple(i for i, p in enumerate(main) if p.front) or None


def correct(seen: PhotoOpening, c: Correction) -> PhotoOpening:
    """The opening as seen, with the model's corrections: leaves, style, transom panes, dividers; handles and fronts rewrite the main row
    of ``panels`` (made from the leaves when the recognizer gave none)."""
    if c.same:
        return seen
    style = c.style or seen.style
    leaves = c.leaves if c.leaves is not None else seen.leaves
    panels = seen.panels
    if c.handles is not None or c.fronts is not None or (c.leaves is not None and c.leaves != seen.leaves):
        main = [p for p in (panels or ()) if p.row == 0]
        upper = [p for p in (panels or ()) if p.row > 0]
        op = style if style in PANEL_OPS else "fixed"
        if len(main) != leaves:
            main = [Panel(0, op, False, False) for _ in range(leaves)]
        handles = set(c.handles) if c.handles is not None else {i for i, p in enumerate(main) if p.handle}
        fronts = set(c.fronts) if c.fronts is not None else {i for i, p in enumerate(main) if p.front}
        panels = tuple([Panel(0, p.operation, i in handles, i in fronts) for i, p in enumerate(main)] + upper)
    return replace(seen, style=style, leaves=leaves, panels=panels,
                   transom_panes=c.transom_panes if c.transom_panes is not None else seen.transom_panes,
                   axes_ratio=c.axes_ratio if c.axes_ratio is not None else seen.axes_ratio,
                   h_axes_ratio=c.h_axes_ratio if c.h_axes_ratio is not None else seen.h_axes_ratio)
