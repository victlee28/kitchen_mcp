"""Yêu cầu ẢNH THẬT cho câu lệnh gửi AI (Gemini: câu văn; ComfyUI: cụm từ khoá + negative).

Một nguồn cho mọi loại job để ảnh nhất quán:
- full(spec, anh_sang)  : ảnh đầy đủ (gen-0, xuất cho AI) — ánh sáng, máy ảnh, vật liệu, bóng đổ, hậu kỳ.
- local(spec, ...)      : sửa một vùng (edit / sửa hình) — vùng sửa phải hoà vào ảnh gốc: cùng hướng sáng, nhiễu hạt, độ nét…
- tags(spec, anh_sang)  : cụm từ cho prompt ComfyUI.
- NEGATIVE              : những dấu hiệu "ảnh dựng 3D / ảnh AI" cần tránh.
Nội dung suy từ thiết kế: có cửa sổ thì có nắng chiếu qua cửa sổ, có tủ trên thì có đèn LED hắt dưới tủ, vật liệu vân gỗ /
đá / inox / kính / sơn bóng thì mô tả bề mặt tương ứng.
"""
from __future__ import annotations

from . import vocab
from .spec import KitchenSpec

ANH_SANG = {
    "ban-ngay": ("bright natural daylight on an overcast-to-sunny morning, neutral white balance around 5000K, soft large-source "
                 "light with gentle falloff across the room"),
    "nang-chieu": ("warm late-afternoon sunlight raking low across the room, around 4000K, long soft-edged shadows and a warm "
                   "glow on the cabinet fronts, balanced by cool ambient fill"),
    "toi-am": ("evening interior lighting: warm 2700–3000K recessed ceiling downlights and under-cabinet LED strips as the main "
               "light, dark window, cozy pools of light on the countertop, no harsh flash"),
}
ANH_SANG_VI = {"ban-ngay": "Ban ngày, sáng tự nhiên", "nang-chieu": "Nắng chiều ấm", "toi-am": "Buổi tối, đèn ấm"}

NEGATIVE = ["CGI", "3D render look", "video game graphics", "plastic-looking surfaces", "flat uniform lighting",
            "oversaturated colors", "HDR halos", "overexposed highlights", "crushed black shadows", "cartoon", "illustration",
            "painting", "fisheye distortion", "converging vertical lines", "wavy or melted edges", "smeared textures",
            "repeated tiling texture pattern", "floating objects without contact shadows", "fake bokeh", "lens flare",
            "clutter", "visible noise artifacts"]


def _has_window(spec: KitchenSpec) -> bool:
    return bool(spec.phong and any(lo.loai == "cua-so" for t in spec.phong.tuong for lo in t.lo))


def _ten_vat_lieu(spec: KitchenSpec) -> list[str]:
    return [*spec.chung.vatLieu.values(), *(m.vatLieu or "" for m in spec.module), spec.chung.tayNam.vatLieu or ""]


def _materials(spec: KitchenSpec | None, extra: list[str] | None = None) -> list[str]:
    """Mô tả bề mặt theo tên vật liệu (của cả thiết kế nếu có spec, cộng thêm extra), mỗi loại một câu ngắn, không lặp."""
    names = " ".join([*(_ten_vat_lieu(spec) if spec is not None else []), *(extra or [])]).lower()
    t = vocab._norm(names)  # bỏ dấu, chữ thường
    out = []
    if any(vocab._has(t, k) for k in ("vân gỗ", "gỗ", "sồi", "óc chó", "tần bì", "xoan đào", "teak", "veneer")):
        out.append("wood surfaces show natural, non-repeating grain running consistently along each panel, with true-to-scale "
                   "grain size and subtle variation between boards")
    if any(vocab._has(t, k) for k in ("laminate", "melamine")):
        out.append("laminate and melamine panels have a fine low-sheen texture with soft, broad reflections")
    if any(vocab._has(t, k) for k in ("bóng", "bóng gương", "acrylic")):
        out.append("high-gloss fronts reflect the room softly and accurately, reflections follow the panel planes without warping")
    if any(vocab._has(t, k) for k in ("mờ", "sơn")):
        out.append("matte painted fronts have an even satin finish with no plastic shine")
    if any(vocab._has(t, k) for k in ("đá", "thạch anh", "granite", "marble", "vân đá", "vân mây")):
        out.append("the stone countertop has a crisp eased edge, realistic veining that continues across the front edge, and "
                   "a light polished reflection of the wall cabinets")
    if any(vocab._has(t, k) for k in ("inox", "nhôm", "đồng", "kim loại")):
        out.append("metal handles and appliances show brushed metal with directional micro-scratches and soft specular highlights")
    if any(vocab._has(t, k) for k in ("kính",)):
        out.append("glass doors and the cooktop show faint reflections and slight transparency, not opaque flat color")
    if any(vocab._has(t, k) for k in ("gạch",)):
        out.append("tiles have thin recessed grout lines and slightly varying glaze reflections")
    return out


def _contact(spec: KitchenSpec) -> list[str]:
    out = ["thin dark shadow lines in the 2–3 mm reveal gaps between doors and drawers",
           "soft ambient-occlusion contact shadows where cabinets meet the wall, floor and ceiling, and in inside corners",
           "a soft shadow under the countertop overhang and inside the toe-kick recess",
           "door and panel edges have tiny rounded bevels that catch a thin line of light"]
    if any(m.tang in ("tren", "noc") for m in spec.module):
        out.append("a soft shadow band on the backsplash under the wall cabinets")
    return out


def _lights(spec: KitchenSpec, anh_sang: str) -> list[str]:
    out = [ANH_SANG.get(anh_sang, ANH_SANG["ban-ngay"])]
    if _has_window(spec) and anh_sang != "toi-am":
        out.append("daylight enters through the window as the key light, brightest near it, with a natural exposure that keeps "
                   "the window view slightly bright but not blown out")
    if any(m.tang in ("tren", "noc") for m in spec.module):
        out.append("warm LED strip light under the wall cabinets washes the backsplash and countertop"
                   + (" (subtle in daylight)" if anh_sang != "toi-am" else ""))
    return out


def full(spec: KitchenSpec, anh_sang: str = "ban-ngay") -> str:
    """Đoạn yêu cầu ảnh thật cho ảnh ĐẦY ĐỦ (gen-0 / xuất cho AI)."""
    cam = ("Shoot it as a professional architectural interior photograph: full-frame camera, 24–35 mm rectilinear lens at "
           "eye level about 1.5 m, f/8 with everything in focus, vertical lines kept perfectly vertical, no fisheye.")
    light = "Lighting: " + "; ".join(_lights(spec, anh_sang)) + "."
    mats = _materials(spec)
    mat = ("Materials: " + "; ".join(mats) + ".") if mats else ""
    contact = "Physically plausible detail: " + "; ".join(_contact(spec)) + "."
    post = ("Natural color, realistic dynamic range (no HDR look), very fine natural sensor grain, accurate white balance; "
            "the room looks clean and newly installed, with no people, text or clutter. It must be indistinguishable from a "
            "real photograph, not a 3D render.")
    return " ".join(x for x in (cam, light, mat, contact, post) if x)


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


def tags(spec: KitchenSpec, anh_sang: str = "ban-ngay") -> str:
    """Cụm từ khoá ảnh thật cho prompt ComfyUI (SD/SDXL/Flux hiểu dạng tag tốt hơn câu dài)."""
    light = {"ban-ngay": "soft natural daylight, 5000K", "nang-chieu": "warm late afternoon sunlight, long soft shadows",
             "toi-am": "warm evening downlights, under-cabinet LED, 2700K"}.get(anh_sang, "soft natural daylight")
    return ("RAW photo, professional architectural interior photography, 24mm rectilinear lens, eye level, f/8, "
            f"{light}, global illumination, soft contact shadows, ambient occlusion in corners, realistic material textures, "
            "fine wood grain, subtle reflections, straight vertical lines, natural color grading, fine film grain, 8k detail")
