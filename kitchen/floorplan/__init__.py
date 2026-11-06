"""Audited floorplan -> persistent room geometry (mm), element classification and kitchen/wall binding.

Rules that hold everywhere in this package:
* nothing is ever shifted or snapped to "fix" a drawing; a bad outline raises, an element that belongs elsewhere is reported;
* every number that was not measured in the drawing (wall thickness, wall height) is flagged ``assumed``;
* scene coordinates: x to the right, z towards the viewer of a top-down plan (up on the page = -z), y up, millimetres.

One file per responsibility (all pure, rule R1); ``from kitchen import floorplan`` keeps the whole public surface:

* ``constants``  tolerances and contract constants        * ``geom``       2-D point / polygon helpers
* ``document``   reading a document (frame, fields, hash) * ``regions``    kitchen region of a building plan
* ``trim``       trim a room outline around wall elements * ``normalize``  document -> room geometry
* ``back``       which side of a unit lies on a wall      * ``binding``    kitchen frame <-> wall, ``apply_binding``
* ``structures`` drawn elements -> 3-D structures         * ``export``     what the Three.js export takes
"""
from __future__ import annotations

from .back import detect_back, detect_element_backs
from .binding import apply_binding, bind_kitchen, kitchen_transform
from .constants import DEFAULT_WALL_HEIGHT, DEFAULT_WALL_THICKNESS, PARALLEL_DEG, SUPPORTED_CONTRACT, TOL
from .document import document_hash
from .export import finish_document, resolve_binding, room_section
from .normalize import normalize
from .regions import derive_region, list_rooms, parse_region
from .structures import STRUCTURE_COLORS, default_height, structures
from .trim import trim_room

__all__ = [
    "DEFAULT_WALL_HEIGHT", "DEFAULT_WALL_THICKNESS", "PARALLEL_DEG", "STRUCTURE_COLORS", "SUPPORTED_CONTRACT", "TOL",
    "apply_binding", "bind_kitchen", "default_height", "derive_region", "detect_back", "detect_element_backs", "document_hash",
    "finish_document", "kitchen_transform", "list_rooms", "normalize", "parse_region", "resolve_binding", "room_section",
    "structures", "trim_room",
]
