"""Natural-photo requirements shared by image-generation prompts.

Một nguồn cho mọi loại job để ảnh nhất quán:
- full(spec, anh_sang)  : ảnh đầy đủ (gen-0, xuất cho AI) — ánh sáng, máy ảnh, vật liệu, bóng đổ, hậu kỳ.
- local(spec, ...)      : sửa một vùng (edit / sửa hình) — vùng sửa phải hoà vào ảnh gốc: cùng hướng sáng, nhiễu hạt, độ nét…
- NEGATIVE_PHOTO        : những dấu hiệu "ảnh dựng 3D / ảnh AI" cần tránh.
Nội dung suy từ thiết kế: có cửa sổ thì có nắng chiếu qua cửa sổ, có tủ trên thì có đèn LED hắt dưới tủ, vật liệu vân gỗ /
đá / inox / kính / sơn bóng thì mô tả bề mặt tương ứng.
"""
from __future__ import annotations

from .. import vocab
from ..spec import KitchenSpec

LIGHTING = {
    "daylight": ("bright natural daylight on an overcast-to-sunny morning, neutral white balance around 5000K, soft large-source "
                 "light with gentle falloff across the room"),
    "late-afternoon": ("warm late-afternoon sunlight raking low across the room, around 4000K, long soft-edged shadows and a warm "
                   "glow on the cabinet fronts, balanced by cool ambient fill"),
    "dim-evening": ("evening interior lighting: warm 2700–3000K recessed ceiling downlights and under-cabinet LED strips as the main "
               "light, dark window, cozy pools of light on the countertop, no harsh flash"),
}
LIGHTING_VI = {"daylight": "Ban ngày, sáng tự nhiên", "late-afternoon": "Nắng chiều ấm", "dim-evening": "Buổi tối, đèn ấm"}

NEGATIVE_PHOTO = ["CGI", "3D render look", "video game graphics", "plastic-looking surfaces", "flat uniform lighting",
            "oversaturated colors", "HDR halos", "overexposed highlights", "crushed black shadows", "cartoon", "illustration",
            "painting", "fisheye distortion", "converging vertical lines", "wavy or melted edges", "smeared textures",
            "repeated tiling texture pattern", "floating objects without contact shadows", "fake bokeh", "lens flare",
            "clutter", "visible noise artifacts"]


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


def _lights(spec: KitchenSpec, lighting: str) -> list[str]:
    out = [LIGHTING.get(lighting, LIGHTING["daylight"])]
    if _has_window(spec) and lighting != "dim-evening":
        out.append("daylight enters through the window as the key light, brightest near it, with a natural exposure that keeps "
                   "the window view slightly bright but not blown out")
    if any(m.storey in ("upper", "loft") for m in spec.module):
        out.append("warm LED strip light under the wall cabinets washes the backsplash and countertop"
                   + (" (subtle in daylight)" if lighting != "dim-evening" else ""))
    return out


def full(spec: KitchenSpec, lighting: str = "daylight") -> str:
    """Đoạn yêu cầu ảnh thật cho ảnh ĐẦY ĐỦ (gen-0 / xuất cho AI)."""
    camera = ("Shoot it as a professional architectural interior photograph: full-frame camera, 24–35 mm rectilinear lens at "
           "eye level about 1.5 m, f/8 with everything in focus, vertical lines kept perfectly vertical, no fisheye.")
    light = "Lighting: " + "; ".join(_lights(spec, lighting)) + "."
    mats = _materials(spec)
    material_text = ("Materials: " + "; ".join(mats) + ".") if mats else ""
    contact = "Physically plausible detail: " + "; ".join(_contact(spec)) + "."
    post = ("Natural color, realistic dynamic range (no HDR look), very fine natural sensor grain, accurate white balance; "
            "the room looks clean and newly installed, with no people, text or clutter. It must be indistinguishable from a "
            "real photograph, not a 3D render.")
    preferences = ("Image preferences: " + "; ".join(spec.renderPreferences) + ".") if spec.renderPreferences else ""
    return " ".join(x for x in (camera, light, material_text, contact, preferences, post) if x)


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
