"""What a recognizer receives and what it must return. The implementations (a vision model, a CAD reader) live outside the core."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any, Literal, Protocol

SOURCE_KINDS = ("photo", "drawing")
SourceKind = Literal["photo", "drawing"]


@dataclass(frozen=True)
class RecognitionInput:
    kind: SourceKind
    data: bytes
    name: str = ""
    media_type: str = ""
    note: str = ""                       # the user's free-text hint ("white shaker doors", "fridge on the left"): data for the model, never instructions


class Deferred(Exception):
    """Raised by a recognizer that cannot answer NOW (a human or another assistant has to answer first): it carries the ``job`` to ask again
    with and the ``step`` it is waiting on. The service turns it into the status ``pending``, not into a failure."""

    def __init__(self, job: str, step: str = ""):
        super().__init__(f"waiting on {step or 'an answer'} (job {job})")
        self.job, self.step = job, step


class Recognizer(Protocol):
    """Return a raw draft (JSON-able dict)::

        {"modules": [{"type": "base", "wall": "back", "width": 600, "fromCorner"?: 0, "height"?: .., "depth"?: .., "confidence"?: 0..1, "label"?: ".."}],
         "room"?: {"ceiling": 2640}, "materials"?: {"base": "Trắng mờ"}, "confidence"?: 0..1, "notes"?: ["..."]}

    Anything may be wrong or missing: ``build_draft`` checks it. A recognizer that cannot read the source returns ``{"modules": []}`` or raises.
    """

    def recognize(self, source: RecognitionInput) -> dict[str, Any]: ...


PREFERENCE = ("inbox", "cabinet", "gemini")       # which plugged-in recognizer answers when nothing is asked for: Claude Desktop by chat first (to debug), then a model with an API key


def choose_recognizer(available: Sequence[str], requested: str | None, default: str | None) -> str | None:
    """The recognizer to use: the one asked for (None when it is not plugged in), else ``default`` when plugged in, else the first of PREFERENCE
    that is, else the only one. None = no choice can be made."""
    if requested:
        return requested if requested in available else None
    if default and default in available:
        return default
    for name in PREFERENCE:
        if name in available:
            return name
    return available[0] if len(available) == 1 else None
