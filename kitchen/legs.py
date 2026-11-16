"""The legs of a kitchen laid out from a template, each one a run from the start.

A layout template (``layout_solver``) describes a kitchen leg by leg: the back wall, the right wall, the left wall, and rows standing free
(an island, a peninsula). Within a leg, positions ``f`` are counted from the leg's own start: from the back-right corner along a wall, from
the free row's own origin for a free row. That is how a template thinks; a design keeps cabinets only in runs (``Run``, ``runs.RunFrame``).

A ``Leg`` is the run a leg is laid into. ``at(f, width)`` gives the place of a cabinet in the run (``fromCorner`` along the run), ``f_of``
the way back, so the generator can lay a leg in the leg's own terms and every cabinet it makes already stands in its run. Runs whose
start is at the far end of the leg (the back wall, the left wall: someone facing the doors reads them from the far end) keep their end
(``anchor: "end"``): their end is the corner.

Run origins are fixed at the end (``place``): the back wall's length is known only once the whole kitchen is laid out (the left wall
stands at its end). Until then a reversed leg's run counts s from ``FAR`` along the leg (s = FAR - f - width) and ``place`` moves each
origin to the first cabinet, so every run starts at s = 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import runs
from .spec import Run

WALLS = ("back", "right", "left")
FAR = 100000.0          # mm: where s = 0 lies along a reversed leg until ``place`` (a cabinet's fromCorner is never negative)


@dataclass
class Leg:
    """One leg of a laid-out kitchen and the run it is laid into. ``wall``: back / right / left; else a free row (``offset`` of its door
    face, ``depth``, ``facing`` as ``runs.free_seat`` reads them)."""
    run: str
    wall: str | None = None
    offset: float = 0.0
    depth: float = 0.0
    facing: str = "-z"
    reversed: bool = False
    yaw: float = 0.0
    ends: list[float] = field(default_factory=list[float])       # how far along the leg its cabinets reach (for the room's size)

    def seat(self, back_length: float) -> runs.Seat:
        if self.wall is not None:
            seat = runs.wall_seat(self.wall, back_length)
            assert seat is not None
            return seat
        return runs.free_seat(self.offset, self.depth, self.facing)

    def at(self, f: float, width: float) -> float:
        """``fromCorner`` in the run of a cabinet at ``f`` along the leg, ``width`` wide (before ``place`` moves the run's origin)."""
        self.ends.append(f + width)
        return FAR - f - width if self.reversed else f

    def f_of(self, s: float, width: float) -> float:
        """The way back: where along the leg a cabinet of the run at ``s`` stands."""
        return FAR - s - width if self.reversed else s

    def doors(self, doors: list[float]) -> list[float]:
        """Door widths listed along the leg, as the run lists them (hinge sides are told as seen from the front: they stay)."""
        return list(reversed(doors)) if self.reversed else list(doors)

    def corner_end(self) -> str:
        """Which end of a cabinet in this run is at the leg's start (its corner): ``Module.blindSide``."""
        return "end" if self.reversed else "start"


class Legs:
    """The legs of one kitchen, made as they are first used: R1, R2… in that order."""

    def __init__(self) -> None:
        self.legs: dict[str, Leg] = {}

    def wall(self, wall: str) -> Leg:
        return self._leg(wall, wall=wall)

    def free(self, offset: float, depth: float, facing: str = "-z") -> Leg:
        return self._leg(f"free:{offset:g}:{facing}", offset=offset, depth=depth, facing=facing)

    def _leg(self, key: str, **kw: Any) -> Leg:
        leg = self.legs.get(key)
        if leg is None:
            leg = Leg(f"R{len(self.legs) + 1}", **kw)
            seat = leg.seat(1000.0)                      # which way a leg runs does not depend on how long the back wall is
            leg.reversed = seat.left_end(0.0, 1.0) == 1.0
            leg.yaw = seat.yaw
            self.legs[key] = leg
        return leg

    def of_run(self, run: str | None) -> Leg | None:
        return next((g for g in self.legs.values() if g.run == run), None)

    def lengths(self, back: float | None, right: float | None) -> tuple[float, float]:
        """(back wall, right wall): the room's, else 600 mm past the cabinets (as a kitchen laid by wall always was)."""
        def reach(wall: str) -> float:
            leg = self.legs.get(wall)
            return max(leg.ends, default=0.0) if leg else 0.0
        free = [g.offset + g.depth for g in self.legs.values() if g.wall is None and g.facing in ("-z", "+z")]
        return back or reach("back") + 600, right or max(reach("right"), reach("left"), *free, 0.0) + 600

    def place(self, modules: list[Any], back_length: float) -> list[Run]:
        """The runs, each origin where its first cabinet starts (``modules``' ``fromCorner`` are moved to match, in place)."""
        out: list[Run] = []
        for leg in self.legs.values():
            mine = [m for m in modules if m.run == leg.run]
            if not mine:
                continue
            lo = min(m.fromCorner for m in mine)
            seat = leg.seat(back_length)
            ox, oz = seat.to_world(FAR if leg.reversed else 0.0, 0.0)        # where s = 0 is until now
            fr = runs.RunFrame(leg.run, float(ox), float(oz), leg.yaw)
            x, z = fr.to_world(lo, 0.0)
            for m in mine:
                m.fromCorner = m.fromCorner - lo
            out.append(Run(id=leg.run, x=float(x) + 0.0, z=float(z) + 0.0, yaw=leg.yaw, anchor="end" if leg.reversed else None))
        return out
