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


def near(a: float, b: float, eps: float = EPS_MM) -> bool:
    return abs(a - b) <= eps
