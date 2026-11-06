"""The three things a job takes from the outside world, as values: a clock, an id source, a seed source.

Tests (and, one day, a Rust port) pass their own; the defaults are the real clock and the system random generator.
"""
from __future__ import annotations

import datetime as _dt
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _new_seed() -> int:
    return random.randint(1, 2**31 - 1)


@dataclass(frozen=True)
class Runtime:
    now: Callable[[], str] = _now
    new_id: Callable[[], str] = _new_id
    new_seed: Callable[[], int] = _new_seed
