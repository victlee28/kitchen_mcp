"""Default names the core writes into designs (cabinet names, view names): worded from ``name.*`` keys of ``data/i18n`` (``words.say``);
the shell words them again in the reader's language (``i18n.Names``)."""
from __future__ import annotations
from .words import say

NAMES: dict[str, str] = {k: say(f"name.cabinet.{k}") for k in ("tv-console", "tv-column", "tv-side-tall", "tv-upper", "tv-shelf-over",
                                                                  "tv-shelf-side", "upper-hood")}


DEFAULT_FRONT = "Laminate vân gỗ sồi sáng"   # the design's default base / tall front finish (threejs_export._materials uses the same name)


def oblique_view(name: str) -> str:
    """The name of a run's oblique camera view."""
    return say("name.view.oblique", name=name)
