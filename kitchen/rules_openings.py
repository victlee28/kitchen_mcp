"""Checks of the cabinets against the room's doors and windows (``openings``): a doorway wide and high enough (also for a wheelchair),
nothing standing in it, a door that sweeps clear of the cabinets, no cooktop under a window, no wall cabinet over one, a worktop below
its sill. Pure: openings and cabinet bodies in, findings out (``rules_kb`` words and grades them by the knowledge it selected).

A body is a cabinet's (or an appliance's) floor footprint, kitchen frame, with the heights it spans: ``{"id", "kind", "storey",
"footprint", "y0", "y1"}`` (``kind``: ``module`` | ``cooktop``). The sizes come from the ``defaults`` item (``openings``):
``clearAllowance`` (drawn opening -> clear width: the frame and the door leaf), ``doorZone`` / ``windowZone`` (how far in front of an
opening counts as in it), ``near`` (an opening further than this from every cabinet is another room's).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .floorplan.geom import poly_dist
from .numeric import round_int
from .openings import Opening
from .runs import Point, penetration

TOUCH = 5.0      # mm two outlines may overlap and still count as touching


@dataclass(frozen=True)
class Finding:
    topic: str
    modules: tuple[str, ...]
    key: str
    params: Mapping[str, Any]
    measured: Any = None
    limit: Any = None


def _bodies_in(zone: list[Point], bodies: Sequence[Mapping[str, Any]], y0: float, y1: float, storeys: tuple[str, ...]) -> list[str]:
    return [str(b["id"]) for b in bodies if b.get("storey") in storeys and float(b["y0"]) < y1 - 1 and float(b["y1"]) > y0 + 1
            and penetration(zone, [tuple(p) for p in b["footprint"]]) > TOUCH]


def check(openings: list[Opening], bodies: Sequence[Mapping[str, Any]], params: Mapping[str, Mapping[str, Any]],
          settings: Mapping[str, float]) -> list[Finding]:
    """``params``: the parameters of each topic checked (the topic left out is not checked); ``settings``: ``defaults.openings``.
    Findings in opening order, then topic order."""
    allowance = float(settings.get("clearAllowance", 60))
    door_zone, window_zone, near = float(settings.get("doorZone", 300)), float(settings.get("windowZone", 650)), float(settings.get("near", 2000))
    cabinets = [b for b in bodies if b.get("kind") == "module"]
    out: list[Finding] = []
    for op in openings:
        if not cabinets or min(poly_dist(list(op.outline), [tuple(p) for p in b["footprint"]]) for b in cabinets) > near:
            continue                                                     # a door or window of another room
        if op.tag == "door":
            clear = op.width - allowance
            low = None
            if (p := params.get("doorway-width")) is not None and "doorway_clear_min" in p and clear < float(p["doorway_clear_min"]) - 1:
                low = p["doorway_clear_min"]
                out.append(Finding("doorway-width", (), "finding.doorway-narrow", {"id": op.id, "clear": round_int(clear), "min": low},
                                   round_int(clear), low))
            if (p := params.get("doorway-width-accessible")) is not None and "accessible_clear_min" in p and low is None \
                    and clear < float(p["accessible_clear_min"]) - 1:
                out.append(Finding("doorway-width-accessible", (), "finding.doorway-narrow-accessible",
                                   {"id": op.id, "clear": round_int(clear), "min": p["accessible_clear_min"]}, round_int(clear), p["accessible_clear_min"]))
            if (p := params.get("doorway-height")) is not None and "doorway_height_min" in p and op.measured and op.height < float(p["doorway_height_min"]) - 1:
                out.append(Finding("doorway-height", (), "finding.doorway-low", {"id": op.id, "height": round_int(op.height), "min": p["doorway_height_min"]},
                                   round_int(op.height), p["doorway_height_min"]))
            if "doorway-blocked" in params:
                hit = _bodies_in(op.zone(door_zone), cabinets, op.base, op.base + op.height, ("base", "tall", "upper", "loft", "corner"))
                if hit:
                    out.append(Finding("doorway-blocked", tuple(hit), "finding.doorway-blocked", {"id": op.id, "cabinets": ", ".join(hit)}))
            if "door-interference" in params and op.swing:
                hit = [str(b["id"]) for b in cabinets if b.get("storey") in ("base", "tall")
                       and penetration(list(op.swing), [tuple(p) for p in b["footprint"]]) > TOUCH]
                if hit:
                    out.append(Finding("door-interference", tuple(hit), "finding.door-interference", {"id": op.id, "cabinets": ", ".join(hit)}))
        else:
            top = op.base + op.height
            if (p := params.get("cooktop-window")) is not None:
                gap = float(p.get("cooktop_window_gap", 0))
                hit = [str(b["id"]) for b in bodies if b.get("kind") == "cooktop" and float(b["y0"]) < top - 1
                       and penetration(op.zone(window_zone, gap), [tuple(q) for q in b["footprint"]]) > TOUCH]
                if hit:
                    out.append(Finding("cooktop-window", tuple(hit), "finding.cooktop-window", {"id": op.id, "cooktop": ", ".join(hit), "gap": gap}))
            if "window-upper" in params:
                hit = _bodies_in(op.zone(window_zone), cabinets, op.base, top, ("upper", "loft", "tall"))
                if hit:
                    out.append(Finding("window-upper", tuple(hit), "finding.window-upper", {"id": op.id, "cabinets": ", ".join(hit)}))
                worktop = [b for b in cabinets if b.get("storey") == "base" and float(b["y1"]) > op.base + 1
                           and penetration(op.zone(window_zone), [tuple(q) for q in b["footprint"]]) > TOUCH]
                if worktop:
                    high = max(float(b["y1"]) for b in worktop)
                    out.append(Finding("window-upper", tuple(str(b["id"]) for b in worktop), "finding.window-sill",
                                       {"id": op.id, "top": round_int(high), "sill": round_int(op.base)}, round_int(high), round_int(op.base)))
    return out
