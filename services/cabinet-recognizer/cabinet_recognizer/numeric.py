"""Số học xác định (R10): làm tròn ra xa số 0, không dùng round() trần."""
from __future__ import annotations

import math

EPS_MM = 1e-6


def round_half_away(value: float, step: float = 1.0) -> float:
    q = abs(value) / step
    return math.copysign(math.floor(q + 0.5) * step, value)


def round_int(value: float, step: int = 1) -> int:
    return int(round_half_away(value, float(step)))


def snap(value: float, options: list[int], tolerance: float) -> tuple[int, bool]:
    """Chọn giá trị chuẩn gần nhất nếu lệch <= tolerance; trả (giá trị, có_snap)."""
    best: int | None = None
    for opt in sorted(options):
        if best is None or abs(opt - value) < abs(best - value) - EPS_MM:
            best = opt
    if best is not None and abs(best - value) <= tolerance + EPS_MM:
        return best, True
    return round_int(value, 10), False
