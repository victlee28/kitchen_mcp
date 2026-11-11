"""Vietnamese labels the core writes into designs (cabinet and appliance names shown to the user): a constant table, data zone like
the catalog (``data/``) (rule R12: Vietnamese text lives in the interface / dictionary layer, keys are ASCII)."""
from __future__ import annotations

NAMES: dict[str, str] = {
    "tv-console": "Kệ tivi",
    "tv-column": "Cột tủ tivi",
    "tv-side-tall": "Tủ cao vách tivi",
    "tv-upper": "Tủ trên hốc tivi",
    "tv-shelf-over": "Kệ treo trên tivi",
    "tv-shelf-side": "Kệ treo cạnh tivi",
    "upper-hood": "Tủ trên hút mùi",
}


DEFAULT_FRONT = "Laminate vân gỗ sồi sáng"   # the design's default base / tall front finish (threejs_export._materials uses the same name)


OBLIQUE_VIEW = "{name} (chéo)"     # the name of a run's oblique camera view
