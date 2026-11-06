"""What a recognizer receives and what it must return. The implementations (a vision model, a CAD reader) live outside the core."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

SOURCE_KINDS = ("photo", "drawing")
SourceKind = Literal["photo", "drawing"]


@dataclass(frozen=True)
class RecognitionInput:
    kind: SourceKind
    data: bytes
    name: str = ""
    media_type: str = ""


class Recognizer(Protocol):
    """Return a raw draft (JSON-able dict)::

        {"modules": [{"type": "base", "wall": "back", "width": 600, "fromCorner"?: 0, "height"?: .., "depth"?: .., "confidence"?: 0..1, "label"?: ".."}],
         "room"?: {"ceiling": 2640}, "materials"?: {"base": "Trắng mờ"}, "confidence"?: 0..1, "notes"?: ["..."]}

    Anything may be wrong or missing: ``build_draft`` checks it. A recognizer that cannot read the source returns ``{"modules": []}`` or raises.
    """

    def recognize(self, source: RecognitionInput) -> dict: ...
