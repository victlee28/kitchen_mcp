"""Natural-photo requirements shared by image-generation prompts.

Một nguồn cho mọi loại job để ảnh nhất quán:
- full(spec, anh_sang)  : ảnh đầy đủ (gen-0, xuất cho AI) — ánh sáng, máy ảnh, vật liệu, bóng đổ, hậu kỳ.
- local(spec, ...)      : sửa một vùng (edit / sửa hình) — vùng sửa phải hoà vào ảnh gốc: cùng hướng sáng, nhiễu hạt, độ nét…
- NEGATIVE_PHOTO        : những dấu hiệu "ảnh dựng 3D / ảnh AI" cần tránh.
Nội dung suy từ thiết kế: có cửa sổ thì có nắng chiếu qua cửa sổ, có tủ trên thì có đèn LED hắt dưới tủ, vật liệu vân gỗ /
đá / inox / kính / sơn bóng thì mô tả bề mặt tương ứng.
"""
from __future__ import annotations

from .. import builtin, vocab
from ..catalog import Catalog
from ..i18n import pick
from ..jsonview import as_list
from ..spec import KitchenSpec

def lighting(catalog: Catalog = builtin.CATALOG) -> dict[str, str]:
    """Lighting id -> the English sentence (catalog kind ``lighting``; the workshop edits or adds them)."""
    return {it.id: str(it.data.get("prompt", "")) for it in catalog.all("lighting")}


def lighting_names(catalog: Catalog = builtin.CATALOG, lang: str = "vi") -> dict[str, str]:
    return {it.id: pick(it.data.get("name"), lang) for it in catalog.all("lighting")}


def text(id: str, catalog: Catalog = builtin.CATALOG) -> str:
    """A paragraph of the catalog kind ``prompt-text`` (``photo-camera``, ``tv-full``...)."""
    item = catalog.find("prompt-text", id) or builtin.CATALOG.find("prompt-text", id)
    return str(item.data.get("text", "")) if item else ""


def words(id: str, catalog: Catalog = builtin.CATALOG) -> list[str]:
    """A list of phrases of the catalog kind ``prompt-text`` (``negative-photo``, ``negative-layer``)."""
    item = catalog.find("prompt-text", id) or builtin.CATALOG.find("prompt-text", id)
    return [str(w) for w in (as_list(item.data.get("words")) or [])] if item else []


LIGHTING = lighting()                       # the builtin tables (the functions take the merged catalog)
LIGHTING_VI = lighting_names()
NEGATIVE_PHOTO = words("negative-photo")


def _has_window(spec: KitchenSpec) -> bool:
    return bool(spec.room and any(openings.type == "window" for t in spec.room.wall for openings in t.openings))


def _material_name(spec: KitchenSpec) -> list[str]:
    return [*spec.common.material.values(), *(m.material or "" for m in spec.module), spec.common.handle.material or "",
            *(h.material or "" for h in (spec.common.handleByStorey or {}).values()), *(m.handle.material or "" for m in spec.module if m.handle)]


def _materials(spec: KitchenSpec | None, extra: list[str] | None = None) -> list[str]:
    """Mô tả bề mặt theo tên vật liệu (của cả thiết kế nếu có spec, cộng thêm extra), mỗi loại một câu ngắn, không lặp."""
    names = " ".join([*(_material_name(spec) if spec is not None else []), *(extra or [])]).lower()
    t = vocab.norm(names)  # bỏ dấu, chữ thường
    out: list[str] = []
    if any(vocab.has(t, k) for k in ("vân gỗ", "gỗ", "sồi", "óc chó", "tần bì", "xoan đào", "teak", "veneer")):
        out.append("wood surfaces show natural, non-repeating grain running consistently along each panel, with true-to-scale "
                   "grain size and subtle variation between boards")
    if any(vocab.has(t, k) for k in ("laminate", "melamine")):
        out.append("laminate and melamine panels have a fine low-sheen texture with soft, broad reflections")
    if any(vocab.has(t, k) for k in ("bóng", "bóng gương", "acrylic")):
        out.append("high-gloss fronts reflect the room softly and accurately, reflections follow the panel planes without warping")
    if any(vocab.has(t, k) for k in ("mờ", "sơn")):
        out.append("matte painted fronts have an even satin finish with no plastic shine")
    if any(vocab.has(t, k) for k in ("đá", "thạch anh", "granite", "marble", "vân đá", "vân mây")):
        out.append("the stone countertop has a crisp eased edge, realistic veining that continues across the front edge, and "
                   "a light polished reflection of the wall cabinets")
    if any(vocab.has(t, k) for k in ("inox", "nhôm", "đồng", "kim loại")):
        out.append("metal handles and appliances show brushed metal with directional micro-scratches and soft specular highlights")
    if any(vocab.has(t, k) for k in ("kính",)):
        out.append("glass doors and the cooktop show faint reflections and slight transparency, not opaque flat color")
    if any(vocab.has(t, k) for k in ("gạch",)):
        out.append("tiles have thin recessed grout lines and slightly varying glaze reflections")
    return out


def _contact(spec: KitchenSpec) -> list[str]:
    out = ["thin dark shadow lines in the 2–3 mm reveal gaps between doors and drawers",
           "soft ambient-occlusion contact shadows where cabinets meet the wall, floor and ceiling, and in inside corners",
           "a soft shadow under the countertop overhang and inside the toe-kick recess",
           "door and panel edges have tiny rounded bevels that catch a thin line of light"]
    if any(m.storey in ("upper", "loft") for m in spec.module):
        out.append("a soft shadow band on the backsplash under the wall cabinets")
    return out


def _lights(spec: KitchenSpec, light: str, catalog: Catalog = builtin.CATALOG) -> list[str]:
    table = lighting(catalog)
    lighting_id = light
    out = [table.get(lighting_id) or table.get("daylight") or LIGHTING["daylight"]]
    if _has_window(spec) and lighting_id != "dim-evening":
        out.append("daylight enters through the window as the key light, brightest near it, with a natural exposure that keeps "
                   "the window view slightly bright but not blown out")
    if any(m.storey in ("upper", "loft") for m in spec.module):
        out.append("warm LED strip light under the wall cabinets washes the backsplash and countertop"
                   + (" (subtle in daylight)" if lighting_id != "dim-evening" else ""))
    return out


def full(spec: KitchenSpec, light: str = "daylight", catalog: Catalog = builtin.CATALOG) -> str:
    """Đoạn yêu cầu ảnh thật cho ảnh ĐẦY ĐỦ (gen-0 / xuất cho AI). Câu chữ: catalog kinds ``lighting`` và ``prompt-text``."""
    camera = text("photo-camera", catalog)
    light_text = "Lighting: " + "; ".join(_lights(spec, light, catalog)) + "."
    mats = _materials(spec)
    material_text = ("Materials: " + "; ".join(mats) + ".") if mats else ""
    contact = "Physically plausible detail: " + "; ".join(_contact(spec)) + "."
    post = text("photo-post", catalog)
    preferences = ("Image preferences: " + "; ".join(spec.renderPreferences) + ".") if spec.renderPreferences else ""
    return " ".join(x for x in (camera, light_text, material_text, contact, preferences, post) if x)


def local(spec: KitchenSpec | None, extra_materials: list[str] | None = None) -> str:
    """Đoạn yêu cầu ảnh thật cho SỬA VÙNG: phần mới phải hoà vào ảnh gốc như được chụp cùng lúc.
    Đổi vật liệu: spec=None, extra = vật liệu mới của các việc (chỉ mô tả bề mặt vùng sửa). Sửa hình: spec = thiết kế mới."""
    mats = _materials(spec, extra_materials)
    return ("Make the edited area photographically consistent with image 1, as if captured in the same shot: same light direction, "
            "color temperature, exposure, contrast, sharpness, depth of field and sensor grain; correct perspective-matched "
            "texture scale; reflections and highlights that agree with the light sources visible in image 1; soft contact and "
            "ambient-occlusion shadows where the edited parts meet neighbouring surfaces; thin dark reveal gaps between doors "
            "and drawers; no visible seam, halo or blur along the region boundary."
            + (" Surface detail: " + "; ".join(mats) + "." if mats else ""))
