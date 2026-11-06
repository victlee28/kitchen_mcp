"""Constants and pure helpers shared by the image-job modules."""
from __future__ import annotations

import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .. import imaging
from ..config import Config
from .runtime import Runtime

GROW_PX = 12     # nở mask gửi model (ngữ cảnh quanh mép)
FEATHER_PX = 2   # viền mềm khi ghép, chỉ vào trong mask
VIEW_COLORS = 1280, 960
MAX_TASKS = 8
ZONE_COLORS = [("RED", (255, 0, 0)), ("GREEN", (0, 200, 0)), ("BLUE", (0, 80, 255)), ("YELLOW", (255, 220, 0)),
            ("MAGENTA", (255, 0, 255)), ("CYAN", (0, 230, 230)), ("ORANGE", (255, 140, 0)), ("PURPLE", (140, 60, 200))]


def describe_position(mask: np.ndarray) -> dict | None:
    """Vị trí vùng bằng chữ, tính từ mask: vùng ảnh (trái/giữa/phải × trên/giữa/dưới) + khung theo % kích thước ảnh."""
    b = imaging.bbox(mask)
    if b is None:
        return None
    H, W = mask.shape
    x0, y0, x1, y1 = b
    pc = [round(100 * x0 / W), round(100 * y0 / H), round(100 * x1 / W), round(100 * y1 / H)]
    cx, cy = (x0 + x1) / 2 / W, (y0 + y1) / 2 / H
    h_en, h_vi = ("left", "trái") if cx < 1 / 3 else (("right", "phải") if cx > 2 / 3 else ("center", "giữa"))
    v_en, v_vi = ("upper", "trên") if cy < 1 / 3 else (("lower", "dưới") if cy > 2 / 3 else ("middle", "giữa"))
    if (x1 - x0) > 0.75 * W:
        h_en, h_vi = "across the full width", "chạy gần hết chiều ngang"
        zone_en, zone_vi = f"{v_en} part of the image, {h_en}", f"phần {v_vi} ảnh, {h_vi}"
    else:
        zone_en = "center of the image" if (h_en, v_en) == ("center", "middle") else f"{v_en}-{h_en} area of the image"
        zone_vi = "giữa ảnh" if (h_vi, v_vi) == ("giữa", "giữa") else f"góc {v_vi} bên {h_vi}" if "giữa" not in (h_vi, v_vi) \
            else f"vùng {v_vi} {h_vi}"
    span = f"x {pc[0]}–{pc[2]}%, y {pc[1]}–{pc[3]}%"
    return {"frame": pc, "en": f"{zone_en} (about {span} of the image width/height)", "vi": f"{zone_vi} (khoảng {span} chiều ngang/dọc ảnh)"}


MOLDING_EN = {"crown": "crown molding along the top of the cabinets", "base": "base molding at the bottom of the cabinets"}


@dataclass
class JobEnv:
    """What every part of the image-job package shares: the store, where renders live, the callback that writes a design edit,
    the settings and the clock/id/seed sources, and the worker threads by job id. One value, created by ``ImageJobs``."""
    store: Any
    render_dir: Path
    apply: Callable[..., dict[str, Any]]
    config: Config
    runtime: Runtime
    threads: dict[str, threading.Thread] = field(default_factory=dict)


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
