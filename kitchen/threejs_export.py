"""KitchenSpec -> tài liệu "Complete Kitchen Three.js Scene Schema" (schemas/kitchen-threejs.schema.json, v1.1.0).

Quy ước (ghi cả trong coordinateSystem.notes):
- Đơn vị mm, trục Y lên, gốc ở góc trong giữa tường sau và tường phải (kitchen_inner_corner).
- positionAnchor = bottom_back_left: transform.position là góc dưới - sau - trái (nhìn từ phía trước) của vật thể.
- Hệ cục bộ của module: x dọc bề rộng (trái -> phải), y lên, z từ hậu ra mặt trước. Vật thể con (part, cánh, ngăn kéo)
  dùng toạ độ cục bộ của module; tay nắm dùng toạ độ cục bộ của cánh/ngăn kéo.
- Tường sau: rotationY 0 (mặt tủ nhìn +Z); tường phải: -90 (nhìn -X); tường trái: +90 (nhìn +X).
File xuất ra hợp lệ với CẢ schema gốc v1.0.0 lẫn bản mở rộng v1.2.0.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from collections import defaultdict

from . import hardware, regions, vocab
from .geometry import Part, backsplash_height, compile_spec, views_of
from .render import SEGMENT_COLORS, _module_color
from .spec import Handle, KitchenSpec, Module, effective_handle

ROT = {"back": 0.0, "right": -90.0, "left": 90.0, "corner": 0.0, "island": 180.0}
TIER = {"base": "base", "upper": "wall", "loft": "top", "tall": "tall", "corner": "corner"}
MODULE_TYPE = {"base": "base_cabinet", "upper": "wall_cabinet", "loft": "wall_cabinet", "tall": "tall_pantry", "corner": "open_shelf"}
SEMANTIC = {"carcass": "carcass", "plinth": "plinth", "door": "door", "glass-door": "glass_door", "drawer": "drawer", "side-panel": "panel",
            "shelf": "shelf", "countertop": "countertop", "fridge": "refrigerator", "sink": "sink", "faucet": "faucet", "cooktop": "cooktop",
            "hood": "range_hood", "oven": "microwave", "wall": "wall", "floor": "floor", "wall-tile": "backsplash", "handle": "handle",
            "molding": "molding"}


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb)


def _v(x, y, z) -> dict:
    return {"x": round(float(x), 2), "y": round(float(y), 2), "z": round(float(z), 2)}


def _tf(pos, rot_y=0.0) -> dict:
    return {"position": _v(*pos), "rotation": {"x": 0, "y": round(rot_y, 4), "z": 0, "unit": "deg"}}


def _dims(w, h, d) -> dict:
    return {"width": round(max(w, 0.01), 2), "height": round(max(h, 0.01), 2), "depth": round(max(d, 0.01), 2)}


def _rot(v, deg):
    """Quay véc-tơ quanh Y theo quy ước three.js (rotation.y)."""
    t = math.radians(deg)
    x, y, z = v
    return (x * math.cos(t) + z * math.sin(t), y, -x * math.sin(t) + z * math.cos(t))


class Frame:
    """Khung cục bộ (anchor bottom-back-left) của module hoặc vật đặt theo tường."""

    def __init__(self, pos, rot_y):
        self.pos, self.rot = tuple(pos), rot_y

    def to_local(self, p):
        d = (p[0] - self.pos[0], p[1] - self.pos[1], p[2] - self.pos[2])
        return _rot(d, -self.rot)

    def box_local(self, mn, mx):
        pts = [self.to_local((x, y, z)) for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
        openings = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        return openings, hi

    @staticmethod
    def for_aabb(mn, mx, wall):
        """Khung đặt vật thẳng trục theo hướng của tường: anchor = góc dưới-sau-trái."""
        r = ROT.get(wall or "back", 0.0)
        if r == 0:
            pos = (mn[0], mn[1], mn[2])
        elif r == -90:
            pos = (mx[0], mn[1], mn[2])
        elif r == 180:
            pos = (mx[0], mn[1], mx[2])
        else:
            pos = (mn[0], mn[1], mx[2])
        return Frame(pos, r)


def _module_frame(m: Module, lsau: float) -> tuple[Frame, tuple[float, float, float]]:
    if m.type == "corner-shelf":
        return Frame((-m.backLength, m.y, 0), 0.0), (m.backLength, m.height, m.rightLength)
    if m.wall == "back":
        return Frame((-(m.fromCorner + m.width), m.y, 0), 0.0), (m.width, m.height, m.depth)
    if m.wall == "right":
        return Frame((0, m.y, m.fromCorner), -90.0), (m.width, m.height, m.depth)
    if m.wall == "island":  # faces the back wall: local +z points to world -z, anchor = back-left corner seen from the front
        return Frame((-m.fromCorner, m.y, m.offset + m.depth), 180.0), (m.width, m.height, m.depth)
    return Frame((-lsau, m.y, m.fromCorner + m.width), 90.0), (m.width, m.height, m.depth)


# ------------------------------------------------------------------ vật liệu
def _guess(text: str) -> dict:
    g = _guess_base(text)
    w = vocab._find(text, vocab.WOOD)  # loài gỗ nêu rõ (óc chó, teak…) quyết định màu gỗ
    if w and "transmission" not in g:
        g = {**g, "color": w[1]}
    c = vocab.explicit_color(text)  # màu nêu rõ (xanh rêu, kem, xám…) ghi đè màu mặc định của chất liệu
    if c and "transmission" not in g:
        g = {**g, "color": c}
    return g


def _guess_base(text: str) -> dict:
    t = (text or "").lower()
    if "kính" in t or "glass" in t:
        return {"threeMaterialType": "MeshPhysicalMaterial", "color": "#dfe9ec", "roughness": 0.05, "metalness": 0, "transmission": 0.9,
                "ior": 1.5, "opacity": 0.35, "transparent": True, "side": "DoubleSide"}
    if "marble" in t or "cẩm thạch" in t:
        return {"color": "#ecebe7", "roughness": 0.2, "clearcoat": 0.4, "threeMaterialType": "MeshPhysicalMaterial"}
    if "terrazzo" in t:
        return {"color": "#cfc9bf", "roughness": 0.35, "clearcoat": 0.2, "threeMaterialType": "MeshPhysicalMaterial"}
    if "acrylic" in t or "bóng gương" in t:
        return {"color": "#e9e7e2", "roughness": 0.08, "clearcoat": 0.8, "threeMaterialType": "MeshPhysicalMaterial"}
    if "zellige" in t:
        return {"color": "#e4ded0", "roughness": 0.25, "clearcoat": 0.3, "threeMaterialType": "MeshPhysicalMaterial"}
    if "đồng" in t or "brass" in t:
        return {"color": "#b5913f", "roughness": 0.35, "metalness": 0.9}
    if "inox" in t or "nhôm" in t or "thép" in t:
        return {"color": "#b9bdc2" if "đen" not in t else "#2b2b2b", "roughness": 0.35, "metalness": 0.9}
    if "granite" in t or "đen" in t or "tối" in t:
        return {"color": "#3a3a3c", "roughness": 0.3}
    if "sồi" in t or "oak" in t or "gỗ" in t:
        return {"color": "#c49a6c", "roughness": 0.6}
    if "đá" in t or "quartz" in t or "thạch anh" in t:
        return {"color": "#f1f0ec", "roughness": 0.25, "clearcoat": 0.3, "threeMaterialType": "MeshPhysicalMaterial"}
    if "gạch" in t:
        return {"color": "#f5f4f0", "roughness": 0.4}
    if "trắng" in t:
        return {"color": "#f2f2f0", "roughness": 0.7}
    return {"color": "#d9c3a0", "roughness": 0.6}


def _materials(spec: KitchenSpec) -> tuple[list[dict], dict[str, str]]:
    vl = spec.common.material
    defs = {  # vai trò -> (id, tên, mô tả nguồn)
        "base": ("MAT-FRONT-BASE", vl.get("base", "Laminate vân gỗ sồi sáng"), "front"),
        "upper": ("MAT-FRONT-WALL", vl.get("upper", "Trắng mờ"), "front"),
        "tall": ("MAT-FRONT-TALL", vl.get("tall", vl.get("base", "Laminate vân gỗ sồi sáng")), "front"),
        "cornerShelf": ("MAT-SHELF-CORNER", vl.get("cornerShelf", vl.get("base", "Vân gỗ sồi")), "shelf"),
        "carcass": ("MAT-CARCASS", vl.get("carcass", "Melamine trắng"), "carcass"),
        "countertop": ("MAT-COUNTERTOP", vl.get("countertop", "Đá nhân tạo trắng"), "countertop"),
        "wallTile": ("MAT-BACKSPLASH", vl.get("wallTile", "Gạch thẻ trắng"), "backsplash"),
        "glass": ("MAT-GLASS", "Kính cánh tủ", "glass_door"),
        "handle": ("MAT-HANDLE", spec.common.handle.material, "handle"),
        "sink": ("MAT-SINK", "Chậu rửa màu tối", "sink"),
        "inox": ("MAT-STEEL", "Inox", "appliance"),
        "cooktop": ("MAT-COOKTOP-GLASS", "Mặt kính đen bếp", "cooktop"),
        "wall": ("MAT-WALL", vl.get("wall", "Sơn tường trắng ngà"), "wall"),
        "floor": ("MAT-FLOOR", vl.get("floor", "Gạch lát nền 800×800"), "floor"),
        "plinth": ("MAT-PLINTH", "Chân tủ nhựa xám đậm", "plinth"),
    }
    out, ids = [], {}
    for key, (mid, name, sem) in defs.items():
        g = {"threeMaterialType": "MeshStandardMaterial", "roughness": 0.5, "metalness": 0.0, **_guess(name)}
        if key == "sink":
            g.update(color="#2f3236", roughness=0.35, metalness=0.2)
        if key == "cooktop":
            g.update(color="#121212", roughness=0.08, metalness=0.0)
        if key == "wall":
            g.update(color="#ece7de", roughness=0.9)
        if key == "floor":
            g.update(color="#bdb4a6", roughness=0.6)
        if key == "plinth":
            g.update(color="#4a4740", roughness=0.8)
        material_text = {"id": mid, "name": name, **g, "semanticClass": sem}
        if key == "wallTile" and spec.common.model_extra and spec.common.model_extra.get("wallTile"):
            a, b = spec.common.model_extra["wallTile"][:2]
            material_text["textureRepeat"] = {"u": round(1000 / a, 3), "v": round(1000 / b, 3)}  # số viên trên mỗi mét
        if key == "wallTile" and spec.common.wallTilePattern:
            material_text["pattern"] = spec.common.wallTilePattern  # kiểu xếp gạch (chưa vẽ từng viên)
        if key == "floor" and spec.common.model_extra and spec.common.model_extra.get("floorTile"):
            a, b = spec.common.model_extra["floorTile"][:2]
            material_text["textureRepeat"] = {"u": round(1000 / a, 3), "v": round(1000 / b, 3)}
        out.append(material_text)
        ids[key] = mid
    for m in spec.module:  # vật liệu mặt trước riêng từng module
        if m.material:
            mid = "MAT-FRONT-" + re.sub(r"[^A-Za-z0-9_.:-]", "-", m.id)
            out.append({"id": mid, "name": m.material, "threeMaterialType": "MeshStandardMaterial", "roughness": 0.5, "metalness": 0.0,
                        **_guess(m.material), "semanticClass": "front"})
            ids[f"module:{m.id}"] = mid
    for m in spec.module:  # handle material of a module that differs from the common one
        hm = effective_handle(spec.common, m).material
        if hm != spec.common.handle.material:
            mid = "MAT-HANDLE-" + re.sub(r"[^A-Za-z0-9_.:-]", "-", m.id)
            out.append({"id": mid, "name": hm, "threeMaterialType": "MeshStandardMaterial", "roughness": 0.5, "metalness": 0.0,
                        **_guess(hm), "semanticClass": "handle"})
            ids[f"handle:{m.id}"] = mid
    return out, ids


ASSETS = [
    {"id": "ASSET-PANEL", "category": "carcase", "geometryType": "panel", "defaultDimensions": _dims(600, 720, 18)},
    {"id": "ASSET-DOOR-SLAB", "category": "door_front", "geometryType": "box", "defaultDimensions": _dims(400, 700, 18)},
    {"id": "ASSET-DOOR-GLASS", "category": "door_front", "geometryType": "procedural", "defaultDimensions": _dims(400, 700, 18),
     "parameters": {"frameWidth": 50, "glassThickness": 4}},
    {"id": "ASSET-DRAWER-FRONT", "category": "drawer_front", "geometryType": "box", "defaultDimensions": _dims(600, 180, 18)},
    {"id": "ASSET-SHELF", "category": "shelf", "geometryType": "panel", "defaultDimensions": _dims(560, 18, 300)},
    {"id": "ASSET-PLINTH", "category": "plinth", "geometryType": "box", "defaultDimensions": _dims(600, 100, 480)},
    {"id": "ASSET-COUNTERTOP", "category": "countertop", "geometryType": "extrusion", "defaultDimensions": _dims(1000, 60, 600)},
    {"id": "ASSET-HANDLE-BAR", "category": "handle", "geometryType": "procedural", "defaultDimensions": _dims(12, 160, 30),
     "parameters": {"profile": "bar"}},
    {"id": "ASSET-HANDLE-KNOB", "category": "handle", "geometryType": "procedural", "defaultDimensions": _dims(30, 30, 25)},
    {"id": "ASSET-SINK", "category": "sink", "geometryType": "box", "defaultDimensions": _dims(780, 200, 430)},
    {"id": "ASSET-FAUCET", "category": "faucet", "geometryType": "procedural", "defaultDimensions": _dims(40, 300, 200)},
    {"id": "ASSET-APPLIANCE-BOX", "category": "appliance", "geometryType": "box", "defaultDimensions": _dims(600, 850, 600)},
]


# ------------------------------------------------------------------ chi tiết module
def _split_carcass(openings, hi, t, b) -> list[tuple[str, str | None, list, list]]:
    """Thân hộp -> hông trái/phải, đáy, nóc, hậu (toạ độ cục bộ)."""
    (x0, y0, z0), (x1, y1, z1) = openings, hi
    if x1 - x0 < 3 * t or y1 - y0 < 3 * t or z1 - z0 < 80:
        return [("back" if z1 - z0 < 80 else "custom", "niche_back" if z1 - z0 < 80 else None, openings, hi)]
    return [("left_side", None, [x0, y0, z0], [x0 + t, y1, z1]),
            ("right_side", None, [x1 - t, y0, z0], [x1, y1, z1]),
            ("bottom", None, [x0 + t, y0, z0 + b], [x1 - t, y0 + t, z1]),
            ("top", None, [x0 + t, y1 - t, z0 + b], [x1 - t, y1, z1]),
            ("back", None, [x0 + t, y0 + t, z0], [x1 - t, y1 - t, z0 + b])]


def _handle(hn: Handle, material_id: str, w, h, d, tier, hinge, horizontal=False, source: str | None = None) -> dict | None:
    hd = hardware.handle(hn, w, h, tier, hinge, horizontal)
    if hd is None:
        return None
    out = {"type": hd["type"], "assetId": hd["assetId"], "materialId": material_id,
           "transform": _tf((hd["x"], hd["y"], d)), "dimensions": _dims(*hd["size"])}
    if source:
        out["sourceRef"] = source  # ID chi tiết tay nắm trong bộ biên dịch (= layer sửa ảnh)
    return out


def _module_entry(spec: KitchenSpec, m: Module, parts: list[Part], frame: Frame, size, mats: dict, led: bool) -> dict:
    c = spec.common
    storey = m.storey
    tier = TIER[storey]
    hn, hmat = effective_handle(c, m), mats.get(f"handle:{m.id}", mats["handle"])
    front = {"base": "base", "upper": "upper", "loft": "upper", "tall": "tall", "corner": "cornerShelf"}[storey]
    if m.material:  # vật liệu mặt trước riêng của module (vd đổi màu một tủ từ ảnh AI)
        front = f"module:{m.id}"
    entry = {
        "id": f"MOD-{m.id}", "moduleType": "corner_cabinet" if m.blindCorner else ("appliance_cabinet" if m.type == "tall-fridge" else MODULE_TYPE[storey]),
        "name": m.name or m.id, "dimensions": _dims(*size), "transform": _tf(frame.pos, frame.rot),
        "carcaseMaterialId": mats["cornerShelf"] if storey == "corner" else mats["carcass"], "frontMaterialId": mats[front],
        "frontStyle": {"glass": "glass", "frame": "shaker", "flat": "slab"}.get(m.doorStyle or "", "glass" if m.type == "upper-glass" else "slab"),
        "sourceRef": m.id, "storey": storey,
        "placement": {**({} if m.wall == "island" else {"wallId": "WALL-BACK" if m.wall == "corner" else f"WALL-{m.wall.upper()}"}),
                      "alignment": "floor" if m.y == 0 else "wall", "offset": m.fromCorner, "elevation": m.y},
        "construction": {"panelThickness": c.doorThickness, "backThickness": c.backThickness, "plinthHeight": c.plinthHeight if m.y == 0 else 0,
                         "doorOverlay": "full", "gap": c.doorGap, "grainDirection": "vertical",
                         "edgeBanding": {"thickness": 1, "materialId": mats[front]}},
        "doors": [], "drawers": [], "shelves": [], "parts": [], "visible": True,
    }
    if m.blindCorner:
        entry["blindCorner"] = {"side": "left", "width": m.blindCorner}
    if m.endPanel:
        entry["endPanel"] = {"side": "right", "thickness": m.endPanel}
    if led and storey in ("upper", "corner"):
        entry["led"] = True
    t = c.doorThickness
    door_parts, n = [], defaultdict(int)

    def pid(role):
        n[role] += 1
        return f"{m.id}-{role}-{n[role]}"

    handle_of = {p.parent: p.id for p in parts if p.type == "handle" and p.parent}
    for p in parts:
        if p.type == "handle":
            continue  # tay nắm xuất ở doors[].hardware / drawers[].hardware
        openings, hi = frame.box_local(p.min, p.max)
        if p.type == "carcass":
            for role, crole, a, b in _split_carcass(openings, hi, t, c.backThickness):
                e = {"id": pid(role), "role": role, "assetId": "ASSET-PANEL", "dimensions": _dims(b[0] - a[0], b[1] - a[1], b[2] - a[2]),
                     "transform": _tf(a), "materialId": mats["carcass"], "semanticClass": "carcass", "sourceRef": p.id}
                if crole:
                    e["customRole"] = crole
                entry["parts"].append(e)
        elif p.type in ("door", "glass-door"):
            door_parts.append((openings, hi, p.type == "glass-door", p.id))
        elif p.type == "drawer":
            w, h, d = (hi[i] - openings[i] for i in range(3))
            entry["drawers"].append({"id": pid("drawer"), "assetId": "ASSET-DRAWER-FRONT", "height": round(h, 2), "materialId": mats[front],
                                     "dimensions": _dims(w, h, d), "transform": _tf(openings), "sourceRef": p.id,
                                     "hardware": _handle(hn, hmat, w, h, d, tier, None, horizontal=True, source=handle_of.get(p.id))})
            if entry["drawers"][-1]["hardware"] is None:
                entry["drawers"][-1].pop("hardware")
        else:
            role, crole, material_text, sem = {
                "plinth": ("plinth", None, mats["plinth"], "plinth"),
                "shelf": ("shelf", "niche_board" if storey == "base" else None, mats["cornerShelf"] if storey == "corner" else mats["carcass"], "shelf"),
            }.get(p.type, (None, None, None, None))
            if p.type == "side-panel":
                sz = size[0]
                if m.endPanel and openings[0] >= sz - m.endPanel - 1:
                    role, crole, material_text = "custom", "end_panel", mats[front]
                elif openings[0] <= 1:
                    role, material_text = "left_side", mats[front] if storey in ("tall", "corner") else mats["carcass"]
                elif hi[0] >= sz - 1:
                    role, material_text = "right_side", mats[front] if storey in ("tall", "corner") else mats["carcass"]
                else:
                    role, material_text = "divider", mats["carcass"]
                sem = "panel"
            if role is None:
                role, crole, material_text, sem = "custom", None, mats["carcass"], SEMANTIC.get(p.type, "custom")
            e = {"id": pid(role), "role": role, "assetId": "ASSET-PLINTH" if role == "plinth" else "ASSET-SHELF" if role == "shelf" else "ASSET-PANEL",
                 "dimensions": _dims(*(hi[i] - openings[i] for i in range(3))), "transform": _tf(openings), "materialId": material_text, "semanticClass": sem,
                 "sourceRef": p.id}
            if crole:
                e["customRole"] = crole
            entry["parts"].append(e)
            if role == "shelf":
                entry["shelves"].append({"id": e["id"], "heightOffset": round(openings[1], 2), "materialId": material_text})

    # cánh: bản lề theo moCanh hoặc tự suy (kitchen.hardware, dùng chung với bộ biên dịch hình học)
    door_parts.sort(key=lambda x: (x[0][1], x[0][0]))
    rows = defaultdict(list)
    for d in door_parts:
        rows[round(d[0][1])].append(d)
    flat = [d for _, ds in sorted(rows.items()) for d in sorted(ds, key=lambda x: x[0][0])]
    hinge_of = hardware.hinges(m, [(openings[0], hi[0], openings[1], hi[1]) for openings, hi, _, _ in flat])
    for k, (openings, hi, glass, src) in enumerate(flat):
        w, h, d = (hi[j] - openings[j] for j in range(3))
        hinge = hinge_of[k]
        door = {"id": pid("door"), "assetId": "ASSET-DOOR-GLASS" if glass else "ASSET-DOOR-SLAB", "hingeSide": hinge,
                "materialId": mats["glass"] if glass else mats[front], "dimensions": _dims(w, h, d), "transform": _tf(openings),
                "glass": glass, "frontStyle": "glass" if glass else entry["frontStyle"], "openingAngle": 0, "sourceRef": src,
                "hinges": [{"offset": 100}, {"offset": round(h - 100, 1)}] + ([{"offset": round(h / 2, 1)}] if h > 1200 else [])}
        hw = _handle(hn, hmat, w, h, d, tier, hinge, horizontal=hinge in ("Top", "Bottom"), source=handle_of.get(src))
        if hw:
            door["hardware"] = hw
        entry["doors"].append(door)
    entry["construction"]["hingeCountPerDoor"] = max((len(dd["hinges"]) for dd in entry["doors"]), default=0)
    return entry


# ------------------------------------------------------------------ xuất toàn cảnh
def export(spec: KitchenSpec, design_id: str = "design", rev: int = 1, kb_rows: list[dict] | None = None,
           country: str | None = None) -> dict:
    from .rules import default_rows
    from .rules_kb import select

    scene = compile_spec(spec)
    c = spec.common
    mats_list, mats = _materials(spec)
    qg, kv = regions.normalize(country or spec.country, spec.region)
    sel = select(kb_rows if kb_rows is not None else default_rows(), qg, kv)
    by_mod = defaultdict(list)
    for p in scene.parts:
        by_mod[p.module].append(p)
    has_led = any(t.type == "light" for t in spec.appliances)

    # phòng
    lsau, lphai = scene.lsau, scene.lphai
    walls = [{"id": "WALL-BACK", "start": _v(0, 0, 0), "end": _v(-lsau, 0, 0), "height": c.ceiling, "thickness": 100,
              "materialId": mats["wall"], "interiorNormal": _v(0, 0, 1), "openings": []},
             {"id": "WALL-RIGHT", "start": _v(0, 0, 0), "end": _v(0, 0, lphai), "height": c.ceiling, "thickness": 100,
              "materialId": mats["wall"], "interiorNormal": _v(-1, 0, 0), "openings": []}]
    if any(m.wall == "left" for m in spec.module):
        walls.append({"id": "WALL-LEFT", "start": _v(-lsau, 0, 0), "end": _v(-lsau, 0, lphai), "height": c.ceiling, "thickness": 100,
                      "materialId": mats["wall"], "interiorNormal": _v(1, 0, 0), "openings": []})
    if spec.room:
        for tw in spec.room.wall:
            wall_entry = next((w for w in walls if w["id"] == f"WALL-{tw.id.upper()}"), None)
            if wall_entry:
                wall_entry["thickness"] = tw.thickness
                for i, openings in enumerate(tw.openings):
                    wall_entry["openings"].append({"id": f"{wall_entry['id']}-LO{i + 1}", "type": "window" if openings.type == "window" else "door",
                                             "offset": openings.fromCorner, "width": openings.width, "height": openings.height, "sillHeight": openings.sillHeight})
    room = {"dimensions": _dims(lsau, c.ceiling, lphai), "walls": walls, "floor": {"materialId": mats["floor"], "thickness": 0},
            "ceiling": {"height": c.ceiling, "materialId": mats["wall"], "render": False}}

    # module
    modules = []
    for m in spec.module:
        frame, size = _module_frame(m, lsau)
        modules.append(_module_entry(spec, m, by_mod.get(m.id, []), frame, size, mats, has_led))

    # thiết bị & phụ kiện
    app_type = {"fridge": "Refrigerator", "hood": "Range_Hood_Insert", "oven": "Microwave"}
    appliances, accessories = [], []
    for tb in spec.appliances:
        ps = by_mod.get(tb.id, [])
        if not ps:
            continue
        p = ps[0]
        host = spec.find(tb.module) if tb.module else next((mm for mm in spec.module if mm.wall == tb.wall and mm.storey == "base"
                                                          and tb.center is not None and mm.fromCorner <= tb.center < mm.endAt), None)
        wall = host.wall if host and host.wall != "corner" else (tb.wall or "back")
        fr = Frame.for_aabb(p.min, p.max, wall)
        openings, hi = fr.box_local(p.min, p.max)
        dims = _dims(*(hi[i] - openings[i] for i in range(3)))
        name = (tb.name or "").lower()
        if tb.type in app_type or tb.type == "cooktop":
            t = "Cooktop_Gas" if "gas" in name else "Cooktop_Induction" if tb.type == "cooktop" else app_type[tb.type]
            a = {"id": f"APP-{tb.id}", "type": t, "name": tb.name or tb.id, "assetId": "ASSET-APPLIANCE-BOX", "dimensions": dims,
                 "transform": _tf(fr.pos, fr.rot), "materialId": mats["cooktop"] if tb.type == "cooktop" else mats["inox"], "sourceRef": tb.id,
                 "energy": "gas" if "gas" in name else ("induction" if tb.type == "cooktop" else "electric"),
                 "installation": {"mountType": {"fridge": "freestanding", "cooktop": "built_in", "hood": "built_in", "oven": "built_in"}[tb.type]}}
            if host:
                a["parentModuleId"] = f"MOD-{host.id}"
            if tb.type == "cooktop" and "hood" in sel:
                a["clearances"] = {"top": sel["hood"]["params"].get("gap_min", 650)}
            appliances.append(a)
        elif tb.type in ("sink", "faucet"):
            accessories.append({"id": f"ACC-{tb.id}", "type": ("Sink_Double" if "đôi" in name else "Sink_Single") if tb.type == "sink" else "Faucet_Classic",
                                "assetId": "ASSET-SINK" if tb.type == "sink" else "ASSET-FAUCET",
                                **({"parentId": f"MOD-{host.id}"} if host else {}), "dimensions": dims, "transform": _tf(fr.pos, fr.rot),
                                "materialId": mats["sink"] if tb.type == "sink" else mats["inox"], "sourceRef": tb.id})

    # mặt đá (+ lỗ khoét ước lượng) và ốp tường
    cut_targets = [x for x in appliances if x["type"].startswith("Cooktop")] + [x for x in accessories if x["type"].startswith("Sink")]
    for i, p in enumerate([p for p in scene.parts if p.type == "countertop"]):
        fr = Frame.for_aabb(p.min, p.max, p.wall)
        openings, hi = fr.box_local(p.min, p.max)
        w, h, d = (hi[k] - openings[k] for k in range(3))
        cutouts = []
        for tgt in cut_targets:
            src = next(pp for pp in scene.parts if pp.module == tgt["sourceRef"])
            if src.wall == p.wall and all(p.min[k] - 1 <= src.min[k] and src.max[k] <= p.max[k] + 1 for k in (0, 2)):
                llo, lhi = fr.box_local(src.min, src.max)
                cw, cd = lhi[0] - llo[0] - 20, lhi[2] - llo[2] - 20
                cutouts.append({"forId": tgt["id"], "type": "cooktop" if tgt["id"].startswith("APP") else "sink",
                                "dimensions": _dims(cw, h, cd), "transform": _tf((llo[0] + 10, 0, llo[2] + 10)), "estimated": True})
        accessories.append({"id": f"ACC-COUNTERTOP-{i + 1}", "type": "Countertop", "assetId": "ASSET-COUNTERTOP", "dimensions": _dims(w, h, d),
                            "transform": _tf(fr.pos, fr.rot), "materialId": mats["countertop"], "edgeProfile": "eased", "overhang": c.countertopOverhang,
                            "cutouts": cutouts, "sourceRef": f"countertop-{p.wall}"})
        height = backsplash_height(spec, p.wall)  # cùng một hàm với hình học 3D
        if c.material.get("wallTile") and height >= 50:  # ốp tường giữa mặt đá và tủ trên, sát tường
            accessories.append({"id": f"ACC-BACKSPLASH-{i + 1}", "type": "Backsplash_Tile", "assetId": "ASSET-PANEL",
                                "dimensions": _dims(w, height, 8), "materialId": mats["wallTile"],
                                "transform": _tf((fr.pos[0], c.countertop, fr.pos[2]), fr.rot), "sourceRef": f"wall-tile-{p.wall}"})

    # phào: mặt cắt -> assets (dùng chung), đường chạy -> decorations
    from . import moldings as _mol
    decorations, assets = [], list(ASSETS)
    seen_prof = set()
    for i, run in enumerate(_mol.compute_runs(spec)):
        mol, prof = run.molding, run.profile
        aid = f"ASSET-MOLDING-{prof.id}"
        us = [u for u, _ in prof.points]
        if prof.id not in seen_prof:
            seen_prof.add(prof.id)
            assets.append({"id": aid, "category": "cornice" if mol.variant == "crown" else "molding", "geometryType": "extrusion",
                           "defaultDimensions": _dims(1000, prof.height, max(us) - min(us)),
                           "parameters": {"profileId": prof.id, "name": prof.name, "profile": [[round(u, 2), round(v, 2)] for u, v in prof.points],
                                          "convention": "u: nhô ra phía phòng từ mặt trước tủ (âm = lùi vào); v: lên từ đường chạy; đa giác kín, ngược chiều kim đồng hồ"}})
        if mol.material:
            mid = f"MAT-MOLDING-{mol.id}"
            if all(m["id"] != mid for m in mats_list):
                mats_list.append({"id": mid, "name": mol.material, "threeMaterialType": "MeshStandardMaterial", "roughness": 0.5,
                                  "metalness": 0.0, **_guess(mol.material), "semanticClass": "molding"})
        else:
            mid = mats["upper"] if mol.variant == "crown" else mats["base"]
        decorations.append({
            "id": f"MOLD-{mol.id}-{i + 1}", "type": "Crown_Molding" if mol.variant == "crown" else "Base_Molding",
            "name": f"{'Phào nóc' if mol.variant == 'crown' else 'Phào chân'} ({', '.join(run.wall)})", "assetId": aid,
            "dimensions": _dims(run.length, prof.height, max(us) - min(us)), "transform": _tf((0, 0, 0)), "materialId": mid,
            "path": {"type": "polyline", "points": [_v(x, run.y, z) for x, z in run.points], "joints": "miter", "ends": "flush",
                     "normalRule": "pháp tuyến phía phòng n = (t.z, 0, -t.x), t = hướng đi của đoạn"},
            "sourceRef": mol.id, "semanticClass": "molding", "modules": [f"MOD-{m}" for m in dict.fromkeys(run.modules)]})

    # đèn
    lo_b, hi_b = scene.bounds()
    cx, cz = (lo_b[0] + hi_b[0]) / 2, (lo_b[2] + hi_b[2]) / 2
    lighting = [{"id": "LIGHT-HEMI", "type": "HemisphereLight", "color": "#ffffff", "groundColor": "#8a8170", "intensity": 1.2},
                {"id": "LIGHT-SUN", "type": "DirectionalLight", "color": "#fff6e8", "intensity": 1.4, "position": _v(cx - 3000, 4000, cz + 3000),
                 "target": _v(cx, 800, cz), "castShadow": True}]
    if has_led:
        for mod in modules:
            if mod.get("led") and mod["storey"] == "upper":
                w = mod["dimensions"]["width"]
                f = Frame((mod["transform"]["position"]["x"], mod["transform"]["position"]["y"], mod["transform"]["position"]["z"]),
                          mod["transform"]["rotation"]["y"])
                local = (w / 2, 0, mod["dimensions"]["depth"] - 40)
                r = _rot(local, f.rot)
                lighting.append({"id": f"LIGHT-LED-{mod['sourceRef']}", "type": "RectAreaLight", "color": "#ffd9a0", "intensity": 3,
                                 "width": w - 40, "height": 20, "position": _v(f.pos[0] + r[0], f.pos[1] - 2, f.pos[2] + r[2]),
                                 "target": _v(f.pos[0] + r[0], 0, f.pos[2] + r[2]), "parentId": mod["id"]})

    # camera (gocNhin: m -> mm)
    cameras = []
    for key, v in views_of(spec).items():
        pos = [x * 1000 for x in v.position]
        tgt = [x * 1000 for x in v.lookAt]
        d = [b - a for a, b in zip(pos, tgt)]
        n = math.sqrt(sum(x * x for x in d)) or 1
        up = _v(0, 0, -1) if abs(d[1] / n) > 0.999 else _v(0, 1, 0)
        cameras.append({"id": f"CAM-{key}", "name": v.name or key, "position": _v(*pos), "target": _v(*tgt), "projection": "perspective",
                        "fov": v.verticalFov, "fovAxis": "vertical", "near": 50, "far": 50000, "up": up, "aspect": round(4 / 3, 4)})

    p_cb = (sel.get("sink-cooktop") or {}).get("params", {})
    p_ld = (sel.get("walkway") or {}).get("params", {})
    p_kt = (sel.get("upper-gap") or {}).get("params", {})
    p_hm = (sel.get("hood") or {}).get("params", {})
    constraints = {"allowTouching": True, "overlapTolerance": 1, "minimumSinkCooktopDistance": p_cb.get("sink_cooktop_min", 300),
                   "minimumWalkwayWidth": p_ld.get("walkway_min", p_ld.get("walkway_1person", 900)), "enforceRoomBounds": True,
                   "minimumCountertopToWallCabinet": p_kt.get("upper_gap_min", 450), "minimumHoodClearance": p_hm.get("gap_min", 650),
                   "sources": {k: sel[t]["code"] for k, t in (("minimumSinkCooktopDistance", "sink-cooktop"), ("minimumWalkwayWidth", "walkway"),
                                                              ("minimumCountertopToWallCabinet", "upper-gap"), ("minimumHoodClearance", "hood"))
                               if t in sel}}
    palette = {SEMANTIC.get(k, k): _hex(v) for k, v in SEGMENT_COLORS.items()}
    palette.update({f"module:{m.id}": _hex(_module_color(m.id)) for m in spec.module})

    doc = {
        "schemaVersion": "1.2.0",
        "metadata": {"designId": re.sub(r"[^A-Za-z0-9_.:-]", "-", design_id) or "design", "projectName": spec.name,
                     "description": spec.source or "", "style": spec.style, "revision": max(1, rev), "author": "kitchen-design-mcp",
                     "createdAt": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
                     "region": {"countryCode": qg, "regionCode": kv, "appliedRules": {t: v["code"] for t, v in sel.items()}},
                     "source": {"generator": "kitchen.threejs_export", "specSchemaVersion": spec.schemaVersion, "specRevision": rev},
                     **({"styleTags": list(spec.styleTags)} if spec.styleTags else {}),
                     **({"aiHints": list(spec.aiHints)} if spec.aiHints else {}),
                     **({"renderPreferences": list(spec.renderPreferences)} if spec.renderPreferences else {}),
                     **({"promptInterpretation": list(spec.promptInterpretation)} if spec.promptInterpretation else {})},
        "units": "mm",
        "coordinateSystem": {"upAxis": "+Y", "forwardAxis": "+Z", "handedness": "right", "origin": "kitchen_inner_corner",
                             "positionAnchor": "bottom_back_left", "metersPerUnit": 0.001,
                             "wallFrames": [{"wallId": "WALL-BACK", "origin": _v(0, 0, 0), "alongAxis": _v(-1, 0, 0), "frontAxis": _v(0, 0, 1), "rotationY": 0},
                                            {"wallId": "WALL-RIGHT", "origin": _v(0, 0, 0), "alongAxis": _v(0, 0, 1), "frontAxis": _v(-1, 0, 0), "rotationY": -90},
                                            {"wallId": "WALL-LEFT", "origin": _v(-lsau, 0, 0), "alongAxis": _v(0, 0, 1), "frontAxis": _v(1, 0, 0), "rotationY": 90}],
                             "notes": "Gốc ở góc trong tường sau/tường phải. Anchor = góc dưới-sau-trái nhìn từ phía trước. Hệ cục bộ module: "
                                      "x dọc bề rộng, y lên, z từ hậu ra trước. part/cánh/ngăn kéo theo hệ module; tay nắm theo hệ cánh."},
        "room": room, "lighting": lighting, "materials": mats_list, "assets": assets, "modules": modules, "appliances": appliances,
        "accessories": accessories, "decorations": decorations, "cameras": cameras, "constraints": constraints,
        "renderSettings": {"backgroundColor": "#FFFFFF", "exposure": 1.0, "shadows": True, "antialias": True, "toneMapping": "ACESFilmicToneMapping",
                           "outputWidth": 1920, "outputHeight": 1080, "pixelRatio": 1, "environment": "room",
                           "controlPasses": ["lines", "depth", "normal", "seg", "seg_module", "instance", "albedo"], "segmentationPalette": palette},
    }
    return doc


def integrity(doc: dict) -> list[str]:
    """Kiểm tra tham chiếu mà JSON Schema không diễn đạt được (materialId/assetId/parentId tồn tại, id duy nhất)."""
    errs = []
    mats = {m["id"] for m in doc["materials"]}
    assets = {a["id"] for a in doc.get("assets", [])}
    ids: list[str] = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("materialId", "carcaseMaterialId", "frontMaterialId", "defaultMaterialId") and v not in mats:
                    errs.append(f"{path}.{k}={v} không có trong materials")
                if k == "assetId" and v not in assets:
                    errs.append(f"{path}.{k}={v} không có trong assets")
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")

    walk(doc, "$")
    for sect in ("modules", "appliances", "accessories", "decorations", "cameras", "lighting", "materials", "assets"):
        ids += [x["id"] for x in doc.get(sect, [])]
    for m in doc["modules"]:
        ids += [x["id"] for x in m["parts"] + m["doors"] + m["drawers"]]
    dup = {i for i in ids if ids.count(i) > 1}
    shelf_ids = {s["id"] for m in doc["modules"] for s in m["shelves"]}
    dup -= shelf_ids  # shelf trong shelves[] trỏ tới part cùng id, có chủ đích
    if dup:
        errs.append(f"id trùng: {sorted(dup)[:10]}")
    mod_ids = {m["id"] for m in doc["modules"]}
    for x in doc.get("appliances", []) + doc.get("accessories", []):
        for k in ("parentModuleId", "parentId"):
            if k in x and x[k] not in mod_ids:
                errs.append(f"{x['id']}.{k}={x[k]} không phải module")
    return errs
