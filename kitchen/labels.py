"""Vietnamese labels the core writes into designs (cabinet and appliance names shown to the user): a constant table, data zone like
``appliance_catalog`` (rule R12: Vietnamese text lives in the interface / dictionary layer, keys are ASCII)."""
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


def tv_name(inch: str) -> str:
    """The name of a wall-mounted TV of ``inch`` inches."""
    return f"Tivi {inch} inch treo tường"


DEFAULT_FRONT = "Laminate vân gỗ sồi sáng"   # the design's default base / tall front finish (threejs_export._materials uses the same name)
