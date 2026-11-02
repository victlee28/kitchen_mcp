"""Danh mục layer cho sửa ảnh theo lớp.

Quy ước: layer ID = ID chi tiết do bộ biên dịch hình học sinh ra (vd `TD1-canh-1`, `phao-noc-2`).
Layer nhóm: `matTruoc:<module>` (cánh + ngăn kéo + cánh kính), `module:<ma>` (mọi chi tiết của module hoặc phào),
`loai:<loai>` (mọi chi tiết cùng loại). Không có hệ ID riêng cho layer, nên không cần bảng ánh xạ.

Mỗi layer biết: vật liệu hiện tại (lấy từ spec), vai trò để dựng prompt, quyền sửa,
và (nếu có) thao tác sửa thiết kế tương ứng khi người dùng chọn "Áp vào thiết kế".
"""
from __future__ import annotations

from .geometry import Scene
from .spec import KitchenSpec
from . import vocab

MAT_TRUOC = ("canh", "canh-kinh", "ngan-keo")

SEMANTIC = {"than": "cabinet_body", "hong": "cabinet_body", "ke": "cabinet_body", "chan": "plinth",
            "canh": "cabinet_front", "canh-kinh": "cabinet_front", "ngan-keo": "cabinet_front",
            "mat-da": "countertop", "phao": "decorations", "tay-nam": "hardware", "tuong": "room", "san": "room",
            "tu-lanh": "appliances", "chau": "appliances", "voi": "appliances", "bep": "appliances", "hut-mui": "appliances", "lo": "appliances"}

VAI_TRO = {  # vai trò chi tiết -> (tiếng Việt, tiếng Anh cho prompt)
    "canh": ("cánh tủ", "cabinet door front"), "canh-kinh": ("cánh kính", "glass cabinet door"),
    "ngan-keo": ("mặt ngăn kéo", "drawer front"), "than": ("thân tủ", "cabinet carcass side"),
    "hong": ("tấm hông", "cabinet side panel"), "ke": ("kệ", "open shelf"), "chan": ("len chân tủ", "toe kick plinth"),
    "mat-da": ("mặt đá", "kitchen countertop"), "phao": ("phào", "decorative molding"), "tuong": ("tường", "wall"),
    "san": ("sàn", "floor"), "tu-lanh": ("tủ lạnh", "refrigerator"), "chau": ("chậu rửa", "kitchen sink"),
    "voi": ("vòi nước", "kitchen faucet"), "bep": ("bếp", "cooktop"), "hut-mui": ("máy hút mùi", "range hood"),
    "lo": ("lò", "built-in oven"), "tay-nam": ("tay nắm", "cabinet handle"),
}

_MAC_DINH = {"tuDuoi": "Laminate vân gỗ sồi sáng", "tuTren": "Trắng mờ", "than": "Melamine trắng", "matDa": "Đá nhân tạo trắng",
             "tuong": "Sơn tường trắng ngà", "san": "Gạch lát nền 800×800", "chan": "Chân tủ nhựa xám đậm"}
_THIET_BI = {"tu-lanh": "Inox", "chau": "Chậu rửa màu tối", "voi": "Inox", "bep": "Mặt kính đen bếp", "hut-mui": "Inox", "lo": "Kính đen, khung inox"}


def _vl(spec: KitchenSpec, key: str) -> str:
    v = spec.chung.vatLieu
    if key == "tuCao":
        return v.get("tuCao") or v.get("tuDuoi") or _MAC_DINH["tuDuoi"]
    if key == "keGoc":
        return v.get("keGoc") or v.get("tuDuoi") or "Vân gỗ sồi"
    return v.get(key) or _MAC_DINH.get(key, "")


def material_slot(spec: KitchenSpec, module: str | None, loai: str) -> tuple[str, str]:
    """(khóa vật liệu, tên vật liệu) của một chi tiết. Khóa dùng để biết sửa thiết kế ở đâu."""
    mods = {m.ma: m for m in spec.module}
    mols = {m.ma: m for m in spec.moldings}
    if loai == "phao" and module in mols:
        return f"phao:{module}", mols[module].vatLieu or "Gỗ sơn"
    if loai == "tay-nam":
        return "chung:tayNam", spec.chung.tayNam.vatLieu
    if loai in _THIET_BI:
        return f"thietBi:{loai}", _THIET_BI[loai]
    if loai in ("mat-da", "tuong", "san", "chan"):
        key = {"mat-da": "matDa"}.get(loai, loai)
        return f"chung:{key}", _vl(spec, key)
    m = mods.get(module or "")
    if m is None:
        return "chung:than", _vl(spec, "than")
    tang_key = {"duoi": "tuDuoi", "tren": "tuTren", "noc": "tuTren", "cao": "tuCao", "goc": "keGoc"}[m.tang]
    if loai == "canh-kinh":
        return "thietBi:kinh", "Kính cánh tủ"
    if loai in MAT_TRUOC or (loai == "hong" and (m.tamHong or m.tang in ("cao", "goc"))):
        return (f"module:{m.ma}", m.vatLieu) if m.vatLieu else (f"chung:{tang_key}", _vl(spec, tang_key))
    if m.tang == "goc":
        return f"chung:{tang_key}", _vl(spec, tang_key)
    return "chung:than", _vl(spec, "than")


def design_op(spec: KitchenSpec, layer: dict, vat_lieu: str) -> tuple[dict, str] | None:
    """Thao tác sửa thiết kế để layer mang vật liệu mới. Trả (op, ghi chú phạm vi) hoặc None nếu không hỗ trợ."""
    key = layer["vatLieuKhoa"]
    module, loai = layer.get("module"), layer.get("loai")
    if loai in MAT_TRUOC and loai != "canh-kinh" and module and module in {m.ma for m in spec.module}:
        return {"op": "update", "ma": module, "thayDoi": {"vatLieu": vat_lieu}}, f"cả mặt trước module {module}"
    if key.startswith("module:"):
        return {"op": "update", "ma": key[7:], "thayDoi": {"vatLieu": vat_lieu}}, f"cả mặt trước module {key[7:]}"
    if key.startswith("phao:"):
        return {"op": "phao", "ma": key[5:], "thayDoi": {"vatLieu": vat_lieu}}, f"toàn bộ phào {key[5:]}"
    if key == "chung:tayNam":
        tn = spec.chung.tayNam.model_dump(mode="json")
        return {"op": "chung", "thayDoi": {"tayNam": {**tn, "vatLieu": vat_lieu}}}, "mọi tay nắm"
    if key.startswith("chung:"):
        k = key[6:]
        if k == "chan":
            return None
        pham_vi = {"matDa": "toàn bộ mặt đá", "tuong": "toàn bộ tường", "san": "toàn bộ sàn", "than": "thân mọi tủ",
                   "tuDuoi": "mặt trước mọi tủ dưới", "tuTren": "mặt trước mọi tủ trên", "tuCao": "mặt trước mọi tủ cao",
                   "keGoc": "mọi kệ góc"}.get(k, k)
        return {"op": "chung", "thayDoi": {"vatLieu": {**spec.chung.vatLieu, k: vat_lieu}}}, pham_vi
    return None


def catalogue(spec: KitchenSpec, scene: Scene) -> list[dict]:
    """Mọi chi tiết đơn + layer nhóm. Không gồm số pixel (phụ thuộc góc nhìn)."""
    out = []
    for p in list(scene.parts) + list(scene.meshes):
        key, name = material_slot(spec, p.module, p.loai)
        vt = VAI_TRO.get(p.loai, (p.loai, p.loai))
        out.append({"id": p.id, "kieu": "chi-tiet", "module": p.module, "loai": p.loai, "semanticClass": SEMANTIC.get(p.loai, "custom"),
                    "ten": f"{vt[0]} {p.module or ''}".strip(), "vatLieu": name, "vatLieuKhoa": key,
                    "selectable": True, "allowAppearanceChange": True,
                    "allowGeometryChange": False, "allowPositionChange": False})
    by_id = {x["id"]: x for x in out}
    groups = []
    for m in spec.module:
        fronts = [x["id"] for x in out if x["module"] == m.ma and x["loai"] in MAT_TRUOC]
        if fronts:
            first = by_id[fronts[0]]
            groups.append({"id": f"matTruoc:{m.ma}", "kieu": "nhom", "module": m.ma, "loai": "canh", "semanticClass": "cabinet_front",
                           "ten": f"mặt trước {m.ma}", "vatLieu": first["vatLieu"], "vatLieuKhoa": first["vatLieuKhoa"], "thanhPhan": fronts})
        hs = [x["id"] for x in out if x["module"] == m.ma and x["loai"] == "tay-nam"]
        if hs:
            groups.append({"id": f"tayNam:{m.ma}", "kieu": "nhom", "module": m.ma, "loai": "tay-nam", "semanticClass": "hardware",
                           "ten": f"tay nắm {m.ma}", "vatLieu": by_id[hs[0]]["vatLieu"], "vatLieuKhoa": "chung:tayNam",
                           "thanhPhan": hs})
        allp = [x["id"] for x in out if x["module"] == m.ma]
        if allp:
            groups.append({"id": f"module:{m.ma}", "kieu": "nhom", "module": m.ma, "loai": "module", "semanticClass": "cabinet",
                           "ten": f"module {m.ma}", "vatLieu": None, "vatLieuKhoa": "", "thanhPhan": allp})
    for mol in spec.moldings:
        ids = [x["id"] for x in out if x["module"] == mol.ma and x["loai"] == "phao"]
        if ids:
            first = by_id[ids[0]]
            groups.append({"id": f"module:{mol.ma}", "kieu": "nhom", "module": mol.ma, "loai": "phao", "semanticClass": "decorations",
                           "ten": f"phào {mol.ma}", "vatLieu": first["vatLieu"], "vatLieuKhoa": first["vatLieuKhoa"], "thanhPhan": ids})
    for loai in dict.fromkeys(x["loai"] for x in out):
        ids = [x["id"] for x in out if x["loai"] == loai]
        if len(ids) > 1:
            first = by_id[ids[0]]
            same = len({by_id[i]["vatLieuKhoa"] for i in ids}) == 1
            groups.append({"id": f"loai:{loai}", "kieu": "nhom", "module": None, "loai": loai, "semanticClass": SEMANTIC.get(loai, "custom"),
                           "ten": f"mọi {VAI_TRO.get(loai, (loai,))[0]}", "vatLieu": first["vatLieu"] if same else None,
                           "vatLieuKhoa": first["vatLieuKhoa"] if same else "", "thanhPhan": ids})
    for g in groups:
        g.update(selectable=True, allowAppearanceChange=True, allowGeometryChange=False, allowPositionChange=False)
    return out + groups


def changed_parts(old: KitchenSpec, new: KitchenSpec, scene: Scene) -> list[str]:
    """Chi tiết đổi vật liệu giữa hai spec cùng hình học (để mask đúng phạm vi thao tác sửa thiết kế)."""
    return [p.id for p in list(scene.parts) + list(scene.meshes)
            if material_slot(old, p.module, p.loai)[1] != material_slot(new, p.module, p.loai)[1]]


def resolve(cat: list[dict], layer_id: str) -> tuple[dict, list[str]]:
    """Layer -> (mô tả, danh sách ID chi tiết)."""
    for x in cat:
        if x["id"] == layer_id:
            return x, x.get("thanhPhan") or [x["id"]]
    raise KeyError(f"Không có layer: {layer_id}")


# ------------------------------------------------------------------ prompt
NEGATIVE = ["distorted geometry", "warped cabinet doors", "changed perspective", "extra handles", "text", "watermark",
            "blurry", "low quality", "people"]

_PHONG_CACH = {"Modern": "modern", "Classic": "classic", "Neoclassical": "neoclassical", "Transitional": "transitional",
               "Minimalist": "minimalist"}


def global_prompt(spec: KitchenSpec) -> str:
    style = _PHONG_CACH.get(spec.phongCach or "", (spec.phongCach or "modern").lower())
    v = spec.chung.vatLieu
    mats = ", ".join(x for x in (vocab.tieng_anh(v.get("tuDuoi", "")) and f"base cabinets {vocab.tieng_anh(v.get('tuDuoi', ''))}",
                                 vocab.tieng_anh(v.get("tuTren", "")) and f"wall cabinets {vocab.tieng_anh(v.get('tuTren', ''))}",
                                 vocab.tieng_anh(v.get("matDa", "")) and f"countertop {vocab.tieng_anh(v.get('matDa', ''))}") if x)
    return (f"photorealistic interior photograph of a {style} kitchen, {mats}, "
            f"realistic materials, sharp details, architectural photography").replace(", ,", ",")


def layer_prompt(spec: KitchenSpec, layer: dict, instruction: str = "", vat_lieu: str | None = None) -> str:
    role = VAI_TRO.get(layer.get("loai") or "", (None, "kitchen element"))[1]
    mat = vat_lieu or layer.get("vatLieu") or ""
    en = vocab.tieng_anh(mat)
    parts = [role, en and f"made of {en}", mat and f"({mat})", instruction.strip(),
             "keep exactly the same shape, edges, panel gaps and perspective", "consistent lighting with the surrounding scene"]
    return ", ".join(p for p in parts if p)
