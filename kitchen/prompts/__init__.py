"""Every prompt the project sends to an image model, in one place.

* ``photo``       what makes a picture look like a photograph (light, camera, surfaces) and what to avoid: ``full`` / ``local``.
* ``layer``       the style sentence of a whole kitchen and the sentence for one edited layer.
* ``instruction`` the instructions for a model that takes images + text (Gemini, request package): ``gemini_text*``.

Pure functions of a design and plain values (rule R1); no I/O. Change wording here only; the golden/tests pin the shape.
"""
from __future__ import annotations

from .instruction import gemini_text, gemini_text_edit, gemini_text_geometry, gemini_text_multi, style_note
from .layer import NEGATIVE_LAYER, edit_task_prompt, global_prompt, layer_prompt
from .recognition import SCHEMA as RECOGNITION_SCHEMA, recognition_text
from .photo import LIGHTING, LIGHTING_VI, NEGATIVE_PHOTO, full, local


def negative_prompt(extra: list[str] | None = None) -> str:
    """The "do not" list of a job: what must not change in the layers, any extras, then the signs of a 3D render."""
    return ", ".join([*NEGATIVE_LAYER, *(extra or []), *NEGATIVE_PHOTO])
