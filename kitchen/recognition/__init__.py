"""Recognition (photo or drawing -> draft kitchen), as a plug-in point.

* ``contract``  the ``Recognizer`` interface and its input. No model is wired here: a recognizer is anything with ``recognize(input) -> dict``.
* ``draft``     checks and normalises what a recognizer returned (types, walls, sizes, confidence) into a ``Draft`` with the reasons for every rejection.
* ``operation`` turns a ``Draft`` into ONE ``replace`` operation for the current design.

Pure (rule R1): nothing here reads files, the network or the store. The output is an operation; the service sends it through ``propose``,
so a recognised kitchen is only a preview until the user confirms it.
"""
from __future__ import annotations

from . import gemini_wire, recognizer_wire
from .contract import Deferred, RecognitionInput, Recognizer, choose_recognizer
from .draft import Draft, build_draft
from .operation import draft_operation

__all__ = ["gemini_wire", "recognizer_wire", "Draft", "Deferred", "RecognitionInput", "Recognizer", "choose_recognizer", "build_draft", "draft_operation"]
