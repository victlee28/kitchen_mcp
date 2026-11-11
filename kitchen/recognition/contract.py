"""What a recognizer receives and what it must return. The implementations (a vision model, a CAD reader) live outside the core."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any, Literal, Protocol

from .. import builtin
from ..catalog import Catalog

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


def _rank(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else float("inf")


def preference(catalog: Catalog = builtin.CATALOG) -> list[str]:
    """Which plugged-in recognizer answers when nothing is asked for, best first: the catalog kind ``recognizer`` by ``rank`` (builtin:
    Claude Desktop by chat first, to debug, then a model with an API key)."""
    items = catalog.all("recognizer")
    order = sorted(range(len(items)), key=lambda i: (_rank(items[i].data.get("rank")), i))
    return [items[i].id for i in order]


def choose_recognizer(available: Sequence[str], requested: str | None, default: str | None, catalog: Catalog = builtin.CATALOG) -> str | None:
    """The recognizer to use: the one asked for (None when it is not plugged in or hidden), else ``default`` when plugged in, else the first
    of ``preference`` that is, else the only one. None = no choice can be made. A builtin recognizer the catalog no longer lists (the workshop
    hid it) is not used; one plugged in under another name (a test, a plug-in) is."""
    allowed = preference(catalog)
    hidden = set(builtin.CATALOG.ids("recognizer")) - set(allowed)
    available = [a for a in available if a not in hidden]
    if requested:
        return requested if requested in available else None
    if default and default in available:
        return default
    for name in allowed:
        if name in available:
            return name
    return available[0] if len(available) == 1 else None
