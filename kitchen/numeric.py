"""Number conventions shared by the core (rule R10). Written so a Rust port is a line-for-line translation.

* All reals are IEEE-754 binary64 (Python ``float`` = Rust ``f64``).
* ``EPS_MM`` is the tolerance for comparing lengths in millimetres; never compare reals with ``==`` in logic.
* ``round_half_away`` is the only rounding used for values written out: Python's builtin ``round`` rounds halves to even
  (``round(0.5) == 0``) while Rust's ``f64::round`` rounds them away from zero.
"""
from __future__ import annotations

import math

EPS_MM = 1e-6
EPS_DEG = 1e-9


def round_half_away(x: float, ndigits: int = 0) -> float:
    """Round to ``ndigits`` decimals, halves away from zero; the same operations as Rust's ``(x * 10^n).round() / 10^n``.

    Not the decimal answer for numbers that are not exactly representable: ``round_half_away(1.005, 2) == 1.0`` because
    ``1.005 * 100`` is ``100.49999999999999``. That is intended: both languages then agree bit for bit.
    """
    p = 10.0 ** ndigits
    y = abs(x) * p
    t = math.floor(y)
    r = t + 1.0 if y - t >= 0.5 else float(t)      # y - t is exact; avoids the floor(y + 0.5) error at 0.49999999999999994
    return math.copysign(r / p, x)


def round_int(x: float) -> int:
    """Nearest integer, halves away from zero (Rust: ``x.round() as i64``)."""
    return int(round_half_away(x, 0))


def near(a: float, b: float, eps: float = EPS_MM) -> bool:
    return abs(a - b) <= eps


def polygon_centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    """The area centroid of a simple polygon ``[(x, z), ...]``; the mean of its corners when it has no area (a line, a point). No points:
    ``InvalidInput`` (``empty-polygon``)."""
    a = cx = cz = 0.0
    n = len(points)
    if n == 0:
        from .errors import InvalidInput
        raise InvalidInput("A polygon needs at least one point", code="empty-polygon")
    for i in range(n):
        (x0, z0), (x1, z1) = points[i], points[(i + 1) % n]
        c = x0 * z1 - x1 * z0
        a += c; cx += (x0 + x1) * c; cz += (z0 + z1) * c
    if abs(a) < 1e-9:
        return sum(p[0] for p in points) / n, sum(p[1] for p in points) / n
    return cx / (3 * a), cz / (3 * a)
