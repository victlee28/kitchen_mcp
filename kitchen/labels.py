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


# Style presets of a whole cabinet system (system_replace.STYLES): id -> (name, front finish, door, handle, handle material).
# Door and handle are ASCII codes; the names and finishes are the Vietnamese the designs use (vocab reads them).
STYLE_PRESETS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("modern-white", "Hiện đại trắng bóng", "Acrylic trắng bóng", "flat", "concealed", "Nhôm"),
    ("warm-oak", "Gỗ sồi ấm", "Laminate vân gỗ sồi sáng", "flat", "bar", "Nhôm đen mờ"),
    ("classic-sage", "Cổ điển xanh rêu", "Sơn xanh rêu mờ", "frame", "knob", "Đồng thau"),
    ("minimal-grey", "Tối giản xám đậm", "Acrylic xám đậm", "flat", "concealed", "Nhôm"),
    ("shaker-cream", "Shaker kem", "Sơn kem mờ", "frame", "bar", "Đồng thau xước"),
    ("walnut-luxe", "Gỗ óc chó sang trọng", "Veneer gỗ óc chó", "flat", "bar", "Đồng vàng"),
)

OBLIQUE_VIEW = "{name} (chéo)"     # the name of a run's oblique camera view
