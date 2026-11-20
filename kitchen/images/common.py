"""Constants and pure helpers shared by the image-job modules."""
from __future__ import annotations

import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .. import imaging, palette
from .. import builtin
from ..words import say
from ..catalog import Catalog
from ..config import Config
from .runtime import Runtime

GROW_PX = 12     # nở mask gửi model (ngữ cảnh quanh mép)
FEATHER_PX = 2   # viền mềm khi ghép, chỉ vào trong mask
VIEW_COLORS = 1280, 960
MAX_TASKS = 8
ZONE_COLORS = palette.ZONE_COLORS   # catalog kind palette, item zone


def describe_position(mask: np.ndarray) -> dict[str, Any] | None:
    """Where a region is, in words, from its mask: the image zone (left/centre/right x upper/middle/lower) and its frame in % of the image."""
    b = imaging.bbox(mask)
    if b is None:
        return None
    H, W = mask.shape
    x0, y0, x1, y1 = b
    pc = [round(100 * x0 / W), round(100 * y0 / H), round(100 * x1 / W), round(100 * y1 / H)]
    cx, cy = (x0 + x1) / 2 / W, (y0 + y1) / 2 / H
    h = "left" if cx < 1 / 3 else ("right" if cx > 2 / 3 else "center")
    v = "upper" if cy < 1 / 3 else ("lower" if cy > 2 / 3 else "middle")
    hv, vv = say(f"image.where.{h}"), say(f"image.where.{v}")
    if (x1 - x0) > 0.75 * W:
        zone_en = f"{v} part of the image, across the full width"
        zone_vi = say("image.where.part", v=vv, h=say("image.where.full-width"))
    elif (h, v) == ("center", "middle"):
        zone_en, zone_vi = "center of the image", say("image.where.center-of-image")
    else:
        zone_en = f"{v}-{h} area of the image"
        zone_vi = say("image.where.zone" if "center" == h or "middle" == v else "image.where.corner", v=vv, h=hv)
    span = f"x {pc[0]}–{pc[2]}%, y {pc[1]}–{pc[3]}%"
    return {"frame": pc, "en": f"{zone_en} (about {span} of the image width/height)", "vi": say("image.where.about", zone=zone_vi, span=span)}




@dataclass
class JobEnv:
    """What every part of the image-job package shares: the store, where renders live, the callback that writes a design edit,
    the settings and the clock/id/seed sources, and the worker threads by job id. One value, created by ``ImageJobs``."""
    store: Any
    render_dir: Path
    apply: Callable[..., dict[str, Any]]
    config: Config
    runtime: Runtime
    threads: dict[str, threading.Thread] = field(default_factory=dict[str, threading.Thread])
    catalog: Callable[[], Catalog] = lambda: builtin.CATALOG     # the merged catalog (the service passes its own)
    design_catalog: Callable[[str, int], Catalog] = lambda did, rev: builtin.CATALOG   # what a stored revision is built with (its snapshot)


class Component:
    """A part of the package. It holds the shared ``JobEnv`` (so a replaced ``config`` or ``runtime`` is seen by every part) and,
    in its own ``__init__``, the other parts it calls: parts are composed, not inherited."""

    def __init__(self, env: JobEnv) -> None:
        self.env = env

    @property
    def store(self) -> Any:
        return self.env.store

    @property
    def render_dir(self) -> Path:
        return self.env.render_dir

    @property
    def config(self) -> Config:
        return self.env.config

    @property
    def runtime(self) -> Runtime:
        return self.env.runtime

    def view_dir(self, did: str, rev: int, view: str) -> Path:
        """Where the renders of one view of one revision live."""
        return self.env.render_dir / did / f"rev{rev}" / view
