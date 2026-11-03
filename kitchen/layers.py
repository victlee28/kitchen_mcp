"""Danh mục layer cho sửa ảnh theo lớp.

Quy ước: layer ID = ID chi tiết do bộ biên dịch hình học sinh ra (vd `TD1-door-1`, `crown-molding-2`).
Layer nhóm: `matTruoc:<module>` (cánh + ngăn kéo + cánh kính), `module:<ma>` (mọi chi tiết của module hoặc phào),
`type:<type>` (mọi chi tiết cùng loại), `tier:<tầng>:<vai trò>` (vai trò: handle, door, drawer, front, all; tầng vật liệu: base, upper gồm cả
nóc, tall, corner) và `parts:<id>,<id>,…` (tập chi tiết cùng loại do người dùng chọn, dựng khi resolve). Không có hệ ID riêng cho layer.

Mỗi layer biết: vật liệu hiện tại (lấy từ spec), vai trò để dựng prompt, quyền sửa,
và (nếu có) thao tác sửa thiết kế tương ứng khi người dùng chọn "Áp vào thiết kế".
"""
from __future__ import annotations

from .geometry import Scene
from .spec import KitchenSpec
from . import handles, lexicon, vocab

FRONT_SECTIONS = ("door", "glass-door", "drawer")

SEMANTIC = {"carcass": "cabinet_body", "side-panel": "cabinet_body", "shelf": "cabinet_body", "plinth": "plinth",
            "door": "cabinet_front", "glass-door": "cabinet_front", "drawer": "cabinet_front",
            "countertop": "countertop", "molding": "decorations", "handle": "hardware", "wall": "room", "floor": "room",
            "fridge": "appliances", "sink": "appliances", "faucet": "appliances", "cooktop": "appliances", "hood": "appliances", "oven": "appliances"}

ROLES = {  # vai trò chi tiết -> (tiếng Việt, tiếng Anh cho prompt)
    "door": ("cánh tủ", "cabinet door front"), "glass-door": ("cánh kính", "glass cabinet door"),
    "drawer": ("mặt ngăn kéo", "drawer front"), "carcass": ("thân tủ", "cabinet carcass side"),
    "side-panel": ("tấm hông", "cabinet side panel"), "shelf": ("kệ", "open shelf"), "plinth": ("len chân tủ", "toe kick plinth"),
    "countertop": ("mặt đá", "kitchen countertop"), "molding": ("phào", "decorative molding"), "wall": ("tường", "wall"),
    "floor": ("sàn", "floor"), "fridge": ("tủ lạnh", "refrigerator"), "sink": ("chậu rửa", "kitchen sink"),
    "faucet": ("vòi nước", "kitchen faucet"), "cooktop": ("bếp", "cooktop"), "hood": ("máy hút mùi", "range hood"),
    "oven": ("lò", "built-in oven"), "handle": ("tay nắm", "cabinet handle"),
}

_DEFAULTS = {"base": "Laminate vân gỗ sồi sáng", "upper": "Trắng mờ", "carcass": "Melamine trắng", "countertop": "Đá nhân tạo trắng",
             "wall": "Sơn tường trắng ngà", "floor": "Gạch lát nền 800×800", "plinth": "Chân tủ nhựa xám đậm"}
_APPLIANCES = {"fridge": "Inox", "sink": "Chậu rửa màu tối", "faucet": "Inox", "cooktop": "Mặt kính đen bếp", "hood": "Inox", "openings": "Kính đen, khung inox"}


def _vl(spec: KitchenSpec, key: str) -> str:
    v = spec.common.material
    if key == "tall":
        return v.get("tall") or v.get("base") or _DEFAULTS["base"]
    if key == "cornerShelf":
        return v.get("cornerShelf") or v.get("base") or "Vân gỗ sồi"
    return v.get(key) or _DEFAULTS.get(key, "")


def material_slot(spec: KitchenSpec, module: str | None, type: str) -> tuple[str, str]:
    """(khóa vật liệu, tên vật liệu) của một chi tiết. Khóa dùng để biết sửa thiết kế ở đâu."""
    mods = {m.id: m for m in spec.module}
    mols = {m.id: m for m in spec.moldings}
    if type == "molding" and module in mols:
        return f"molding:{module}", mols[module].material or "Gỗ sơn"
    if type == "handle":
        return handles.material_slot(spec, module)
    if type in _APPLIANCES:
        return f"appliances:{type}", _APPLIANCES[type]
    if type in ("countertop", "wall", "floor", "plinth"):
        key = {"countertop": "countertop"}.get(type, type)
        return f"common:{key}", _vl(spec, key)
    m = mods.get(module or "")
    if m is None:
        return "common:carcass", _vl(spec, "carcass")
    storey_key = {"base": "base", "upper": "upper", "loft": "upper", "tall": "tall", "corner": "cornerShelf"}[m.storey]
    if type == "glass-door":
        return "appliances:glass", "Kính cánh tủ"
    if type in FRONT_SECTIONS or (type == "side-panel" and (m.endPanel or m.storey in ("tall", "corner"))):
        return (f"module:{m.id}", m.material) if m.material else (f"common:{storey_key}", _vl(spec, storey_key))
    if m.storey == "corner":
        return f"common:{storey_key}", _vl(spec, storey_key)
    return "common:carcass", _vl(spec, "carcass")


def design_op(spec: KitchenSpec, layer: dict, material: str, scene: Scene | None = None) -> tuple[dict, str] | None:
    """Thao tác sửa thiết kế để layer mang vật liệu mới. Trả (op, ghi chú phạm vi) hoặc None nếu không hỗ trợ.

    Tay nắm cần `scene` để biết tay nào thuộc module nào; ValueError nếu vùng chọn không biểu diễn đúng được trong spec."""
    if layer.get("type") == "handle":
        if scene is None:
            return None
        return handles.material_ops(spec, scene, layer.get("component") or [layer["id"]], material)
    key = layer["materialLocked"]
    module, type = layer.get("module"), layer.get("type")
    if type in FRONT_SECTIONS and type != "glass-door" and module and module in {m.id for m in spec.module}:
        return {"op": "update", "id": module, "changes": {"material": material}}, f"cả mặt trước module {module}"
    kind, _, ref = key.partition(":")
    if kind == "module":
        return {"op": "update", "id": ref, "changes": {"material": material}}, f"cả mặt trước module {ref}"
    if kind == "molding":
        return {"op": "molding", "id": ref, "changes": {"material": material}}, f"toàn bộ phào {ref}"
    if kind == "common":
        k = ref
        if k == "plinth":
            return None
        scope = {"countertop": "toàn bộ mặt đá", "wall": "toàn bộ tường", "floor": "toàn bộ sàn", "carcass": "thân mọi tủ",
                   "base": "mặt trước mọi tủ dưới", "upper": "mặt trước mọi tủ trên", "tall": "mặt trước mọi tủ cao",
                   "cornerShelf": "mọi kệ góc"}.get(k, k)
        return {"op": "common", "changes": {"material": {**spec.common.material, k: material}}}, scope
    return None


def catalogue(spec: KitchenSpec, scene: Scene) -> list[dict]:
    """Mọi chi tiết đơn + layer nhóm. Không gồm số pixel (phụ thuộc góc nhìn)."""
    out = []
    storey_of = {m.id: m.storey for m in spec.module}
    for p in list(scene.parts) + list(scene.meshes):
        key, name = material_slot(spec, p.module, p.type)
        vt = ROLES.get(p.type, (p.type, p.type))
        out.append({"id": p.id, "variant": "part", "module": p.module, "type": p.type, "semanticClass": SEMANTIC.get(p.type, "custom"),
                    "name": f"{vt[0]} {p.module or ''}".strip(), "material": name, "materialLocked": key,
                    "storey": storey_of.get(p.module), "parent": getattr(p, "parent", None),
                    "selectable": True, "allowAppearanceChange": True,
                    "allowGeometryChange": False, "allowPositionChange": False})
    by_id = {x["id"]: x for x in out}
    groups = []
    for m in spec.module:
        fronts = [x["id"] for x in out if x["module"] == m.id and x["type"] in FRONT_SECTIONS]
        if fronts:
            first = by_id[fronts[0]]
            groups.append({"id": f"frontSections:{m.id}", "variant": "group", "module": m.id, "type": "door", "semanticClass": "cabinet_front",
                           "name": f"mặt trước {m.id}", "material": first["material"], "materialLocked": first["materialLocked"], "component": fronts})
        hs = [x["id"] for x in out if x["module"] == m.id and x["type"] == "handle"]
        if hs:
            groups.append({"id": f"handle:{m.id}", "variant": "group", "module": m.id, "type": "handle", "semanticClass": "hardware",
                           "name": f"tay nắm {m.id}", "material": by_id[hs[0]]["material"], "materialLocked": "common:handle",
                           "component": hs})
        allp = [x["id"] for x in out if x["module"] == m.id]
        if allp:
            groups.append({"id": f"module:{m.id}", "variant": "group", "module": m.id, "type": "module", "semanticClass": "cabinet",
                           "name": f"module {m.id}", "material": None, "materialLocked": "", "component": allp})
    for mol in spec.moldings:
        ids = [x["id"] for x in out if x["module"] == mol.id and x["type"] == "molding"]
        if ids:
            first = by_id[ids[0]]
            groups.append({"id": f"module:{mol.id}", "variant": "group", "module": mol.id, "type": "molding", "semanticClass": "decorations",
                           "name": f"phào {mol.id}", "material": first["material"], "materialLocked": first["materialLocked"], "component": ids})
    for type in dict.fromkeys(x["type"] for x in out):
        ids = [x["id"] for x in out if x["type"] == type]
        if len(ids) > 1:
            first = by_id[ids[0]]
            same = len({by_id[i]["materialLocked"] for i in ids}) == 1
            groups.append({"id": f"type:{type}", "variant": "group", "module": None, "type": type, "semanticClass": SEMANTIC.get(type, "custom"),
                           "name": f"mọi {ROLES.get(type, (type,))[0]}", "material": first["material"] if same else None,
                           "materialLocked": "common:handle" if type == "handle" else (first["materialLocked"] if same else ""), "component": ids})
    groups.extend(_tier_groups(out))
    for g in groups:
        g.update(selectable=True, allowAppearanceChange=True, allowGeometryChange=False, allowPositionChange=False)
    return out + groups


TIER_NAME = {"base": "tủ dưới", "upper": "tủ trên", "tall": "tủ cao", "corner": "kệ góc"}
TIER_OF = {"base": "base", "upper": "upper", "loft": "upper", "tall": "tall", "corner": "corner"}  # storey -> material tier (loft shares upper)


def _tier_groups(parts: list[dict]) -> list[dict]:
    """Groups of one role within one tier: handle, door (door + glass door), drawer, front (all fronts), all (fronts + handles)."""
    out = []
    for tier, tname in TIER_NAME.items():
        members = [x for x in parts if x.get("storey") and TIER_OF[x["storey"]] == tier]
        doors = [x for x in members if x["type"] in ("door", "glass-door")]
        drawers = [x for x in members if x["type"] == "drawer"]
        hs = [x for x in members if x["type"] == "handle"]
        roles = [("handle", "handle", f"tay nắm {tname}", hs), ("door", "door", f"cánh {tname}", doors),
                 ("drawer", "drawer", f"mặt ngăn kéo {tname}", drawers), ("front", "door", f"mặt trước {tname}", doors + drawers),
                 ("all", "module", f"{tname}: mặt trước và tay nắm", doors + drawers + hs)]
        seen: list[frozenset] = []
        for role, type, name, xs in roles:
            ids = [x["id"] for x in xs]
            if not ids or frozenset(ids) in seen:
                continue
            seen.append(frozenset(ids))
            keys, mats = {x["materialLocked"] for x in xs}, {x["material"] for x in xs}
            out.append({"id": f"tier:{tier}:{role}", "variant": "group", "module": None, "type": type, "semanticClass": SEMANTIC.get(type, "cabinet"),
                        "name": name, "material": mats.pop() if len(mats) == 1 else None,
                        "materialLocked": "common:handle" if type == "handle" else (keys.pop() if len(keys) == 1 and type != "module" else ""),
                        "component": ids})
    return out


def changed_parts(old: KitchenSpec, new: KitchenSpec, scene: Scene) -> list[str]:
    """Chi tiết đổi vật liệu giữa hai spec cùng hình học (để mask đúng phạm vi thao tác sửa thiết kế)."""
    return [p.id for p in list(scene.parts) + list(scene.meshes)
            if material_slot(old, p.module, p.type)[1] != material_slot(new, p.module, p.type)[1]]


def _adhoc(cat: list[dict], layer_id: str) -> tuple[dict, list[str]]:
    """`parts:<id>,<id>,…` -> a layer built from parts of one type chosen by the user (a task keeps one role for its prompt)."""
    ids = list(dict.fromkeys(i for i in layer_id[len("parts:"):].split(",") if i))
    by_id = {x["id"]: x for x in cat if x["variant"] == "part"}
    missing = [i for i in ids if i not in by_id]
    if not ids or missing:
        raise KeyError(f"Không có chi tiết: {', '.join(missing[:3]) or '(danh sách trống)'}")
    types = sorted({by_id[i]["type"] for i in ids})
    if len(types) > 1:
        raise ValueError("Một việc chỉ gồm chi tiết cùng loại; đang chọn: " + ", ".join(ROLES.get(t, (t,))[0] for t in types)
                         + ". Tách thành nhiều việc.")
    first = by_id[ids[0]]
    keys, mats = {by_id[i]["materialLocked"] for i in ids}, {by_id[i]["material"] for i in ids}
    layer = {"id": layer_id, "variant": "group", "module": None, "type": first["type"], "semanticClass": first["semanticClass"],
             "name": f"{len(ids)} × {ROLES.get(first['type'], (first['type'],))[0]}", "material": mats.pop() if len(mats) == 1 else None,
             "materialLocked": "common:handle" if first["type"] == "handle" else (keys.pop() if len(keys) == 1 else ""),
             "component": ids, "selectable": True, "allowAppearanceChange": True, "allowGeometryChange": False, "allowPositionChange": False}
    return layer, ids


def resolve(cat: list[dict], layer_id: str) -> tuple[dict, list[str]]:
    """Layer -> (mô tả, danh sách ID chi tiết)."""
    if layer_id.startswith("parts:"):
        return _adhoc(cat, layer_id)
    for x in cat:
        if x["id"] == layer_id:
            return x, x.get("component") or [x["id"]]
    raise KeyError(f"Không có layer: {layer_id}")


# ------------------------------------------------------------------ prompt
NEGATIVE = ["distorted geometry", "warped cabinet doors", "changed perspective", "extra handles", "text", "watermark",
            "blurry", "low quality", "people"]

_STYLES = {"Modern": "modern", "Classic": "classic", "Neoclassical": "neoclassical", "Transitional": "transitional",
               "Minimalist": "minimalist"}


def global_prompt(spec: KitchenSpec) -> str:
    style = _STYLES.get(spec.style or "", (spec.style or "modern").lower())
    v = spec.common.material
    mats = ", ".join(x for x in (vocab.to_english(v.get("base", "")) and f"base cabinets {vocab.to_english(v.get('base', ''))}",
                                 vocab.to_english(v.get("upper", "")) and f"wall cabinets {vocab.to_english(v.get('upper', ''))}",
                                 vocab.to_english(v.get("countertop", "")) and f"countertop {vocab.to_english(v.get('countertop', ''))}") if x)
    wall_tile = v.get("wallTile", "")
    if wall_tile and wall_tile != "Đá ốp tường đồng bộ mặt bàn" and vocab.to_english(wall_tile):
        mats = ", ".join(x for x in (mats, f"backsplash {vocab.to_english(wall_tile)}") if x)
    extra = ", ".join(dict.fromkeys([*lexicon.tag_phrases(spec.styleTags), *(spec.aiHints or [])]))
    return (f"photorealistic interior photograph of a {style} kitchen, {mats}, "
            + (f"{extra}, " if extra else "") + "realistic materials, sharp details, architectural photography").replace(", ,", ",")


def layer_prompt(spec: KitchenSpec, layer: dict, instruction: str = "", material: str | None = None) -> str:
    role = ROLES.get(layer.get("type") or "", (None, "kitchen element"))[1]
    material_text = material or layer.get("material") or ""
    en = vocab.to_english(material_text)
    parts = [role, en and f"made of {en}", material_text and f"({material_text})", instruction.strip(),
             "keep exactly the same shape, edges, panel gaps and perspective", "consistent lighting with the surrounding scene"]
    return ", ".join(p for p in parts if p)
