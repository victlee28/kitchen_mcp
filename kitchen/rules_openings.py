"""Kept for callers of the old path: the checks against doors and windows now live in ``kitchen/openings/checks.py``."""
from __future__ import annotations

from .openings.checks import Finding, check

__all__ = ["Finding", "check"]
