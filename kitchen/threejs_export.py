"""KitchenSpec -> tài liệu "Complete Kitchen Three.js Scene Schema" (schemas/kitchen-threejs.schema.json, v1.1.0).

Quy ước (ghi cả trong coordinateSystem.notes):
- Đơn vị mm, trục Y lên, gốc ở góc trong giữa tường sau và tường phải (kitchen_inner_corner).
- positionAnchor = bottom_back_left: transform.position là góc dưới - sau - trái (nhìn từ phía trước) của vật thể.
- Hệ cục bộ của module: x dọc bề rộng (trái -> phải), y lên, z từ hậu ra mặt trước. Vật thể con (part, cánh, ngăn kéo)
  dùng toạ độ cục bộ của module; tay nắm dùng toạ độ cục bộ của cánh/ngăn kéo.
- Tường sau: rotationY 0 (mặt tủ nhìn +Z); tường phải: -90 (nhìn -X); tường trái: +90 (nhìn +X).
File xuất ra hợp lệ với CẢ schema gốc v1.0.0 lẫn bản mở rộng v1.1.0.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from collections import defaultdict

from . import hardware, regions, vocab
from .geometry import Part, compile_spec, views_of
from .render import SEG_MAU, _mau_module
from .spec import KitchenSpec, Module

ROT = {"sau": 0.0, "phai": -90.0, "trai": 90.0, "goc": 0.0}
TIER = {"duoi": "base", "tren": "wall", "noc": "top", "cao": "tall", "goc": "corner"}
MODULE_TYPE = {"duoi": "base_cabinet", "tren": "wall_cabinet", "noc": "wall_cabinet", "cao": "tall_pantry", "goc": "open_shelf"}
SEMANTIC = {"than": "carcass", "chan": "plinth", "canh": "door", "canh-kinh": "glass_door", "ngan-keo": "drawer", "hong": "panel",
            "ke": "shelf", "mat-da": "countertop", "tu-lanh": "refrigerator", "chau": "sink", "voi": "faucet", "bep": "cooktop",
            "hut-mui": "range_hood", "lo": "microwave", "tuong": "wall", "san": "floor", "op-tuong": "backsplash", "tay-nam": "handle",
            "phao": "molding"}


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
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        return lo, hi

    @staticmethod
    def for_aabb(mn, mx, tuong):
        """Khung đặt vật thẳng trục theo hướng của tường: anchor = góc dưới-sau-trái."""
        r = ROT.get(tuong or "sau", 0.0)
        if r == 0:
            pos = (mn[0], mn[1], mn[2])
        elif r == -90:
            pos = (mx[0], mn[1], mn[2])
        else:
            pos = (mn[0], mn[1], mx[2])
        return Frame(pos, r)


def _module_frame(m: Module, lsau: float) -> tuple[Frame, tuple[float, float, float]]:
    if m.loai == "ke-goc":
        return Frame((-m.canhSau, m.y, 0), 0.0), (m.canhSau, m.cao, m.canhPhai)
    if m.tuong == "sau":
        return Frame((-(m.tu + m.rong), m.y, 0), 0.0), (m.rong, m.cao, m.sau)
    if m.tuong == "phai":
        return Frame((0, m.y, m.tu), -90.0), (m.rong, m.cao, m.sau)
    return Frame((-lsau, m.y, m.tu + m.rong), 90.0), (m.rong, m.cao, m.sau)


# ------------------------------------------------------------------ vật liệu
def _guess(text: str) -> dict:
    g = _guess_base(text)
    c = vocab.mau_ro(text)  # màu nêu rõ (xanh rêu, kem, xám…) ghi đè màu mặc định của chất liệu
    if c and "transmission" not in g:
        g = {**g, "color": c}
    return g


def _guess_base(text: str) -> dict:
    t = (text or "").lower()
    if "kính" in t or "glass" in t:
        return {"threeMaterialType": "MeshPhysicalMaterial", "color": "#dfe9ec", "roughness": 0.05, "metalness": 0, "transmission": 0.9,
                "ior": 1.5, "opacity": 0.35, "transparent": True, "side": "DoubleSide"}
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
    vl = spec.chung.vatLieu
    defs = {  # vai trò -> (id, tên, mô tả nguồn)
        "tuDuoi": ("MAT-FRONT-BASE", vl.get("tuDuoi", "Laminate vân gỗ sồi sáng"), "front"),
        "tuTren": ("MAT-FRONT-WALL", vl.get("tuTren", "Trắng mờ"), "front"),
        "tuCao": ("MAT-FRONT-TALL", vl.get("tuCao", vl.get("tuDuoi", "Laminate vân gỗ sồi sáng")), "front"),
        "keGoc": ("MAT-SHELF-CORNER", vl.get("keGoc", vl.get("tuDuoi", "Vân gỗ sồi")), "shelf"),
        "than": ("MAT-CARCASS", vl.get("than", "Melamine trắng"), "carcass"),
        "matDa": ("MAT-COUNTERTOP", vl.get("matDa", "Đá nhân tạo trắng"), "countertop"),
        "opTuong": ("MAT-BACKSPLASH", vl.get("opTuong", "Gạch thẻ trắng"), "backsplash"),
        "kinh": ("MAT-GLASS", "Kính cánh tủ", "glass_door"),
        "tayNam": ("MAT-HANDLE", spec.chung.tayNam.vatLieu, "handle"),
        "chau": ("MAT-SINK", "Chậu rửa màu tối", "sink"),
        "inox": ("MAT-STEEL", "Inox", "appliance"),
        "bep": ("MAT-COOKTOP-GLASS", "Mặt kính đen bếp", "cooktop"),
        "tuong": ("MAT-WALL", vl.get("tuong", "Sơn tường trắng ngà"), "wall"),
        "san": ("MAT-FLOOR", vl.get("san", "Gạch lát nền 800×800"), "floor"),
        "chan": ("MAT-PLINTH", "Chân tủ nhựa xám đậm", "plinth"),
    }
    out, ids = [], {}
    for key, (mid, name, sem) in defs.items():
        g = {"threeMaterialType": "MeshStandardMaterial", "roughness": 0.5, "metalness": 0.0, **_guess(name)}
        if key == "chau":
            g.update(color="#2f3236", roughness=0.35, metalness=0.2)
        if key == "bep":
            g.update(color="#121212", roughness=0.08, metalness=0.0)
        if key == "tuong":
            g.update(color="#ece7de", roughness=0.9)
        if key == "san":
            g.update(color="#bdb4a6", roughness=0.6)
        if key == "chan":
            g.update(color="#4a4740", roughness=0.8)
        mat = {"id": mid, "name": name, **g, "semanticClass": sem}
        if key == "opTuong" and spec.chung.model_extra and spec.chung.model_extra.get("gachOp"):
            a, b = spec.chung.model_extra["gachOp"][:2]
            mat["textureRepeat"] = {"u": round(1000 / a, 3), "v": round(1000 / b, 3)}  # số viên trên mỗi mét
        if key == "san" and spec.chung.model_extra and spec.chung.model_extra.get("gachNen"):
            a, b = spec.chung.model_extra["gachNen"][:2]
            mat["textureRepeat"] = {"u": round(1000 / a, 3), "v": round(1000 / b, 3)}
        out.append(mat)
        ids[key] = mid
    for m in spec.module:  # vật liệu mặt trước riêng từng module
        if m.vatLieu:
            mid = "MAT-FRONT-" + re.sub(r"[^A-Za-z0-9_.:-]", "-", m.ma)
            out.append({"id": mid, "name": m.vatLieu, "threeMaterialType": "MeshStandardMaterial", "roughness": 0.5, "metalness": 0.0,
                        **_guess(m.vatLieu), "semanticClass": "front"})
            ids[f"module:{m.ma}"] = mid
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
def _split_carcass(lo, hi, t, b) -> list[tuple[str, str | None, list, list]]:
    """Thân hộp -> hông trái/phải, đáy, nóc, hậu (toạ độ cục bộ)."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    if x1 - x0 < 3 * t or y1 - y0 < 3 * t or z1 - z0 < 80:
        return [("back" if z1 - z0 < 80 else "custom", "niche_back" if z1 - z0 < 80 else None, lo, hi)]
    return [("left_side", None, [x0, y0, z0], [x0 + t, y1, z1]),
            ("right_side", None, [x1 - t, y0, z0], [x1, y1, z1]),
            ("bottom", None, [x0 + t, y0, z0 + b], [x1 - t, y0 + t, z1]),
            ("top", None, [x0 + t, y1 - t, z0 + b], [x1 - t, y1, z1]),
            ("back", None, [x0 + t, y0 + t, z0], [x1 - t, y1 - t, z0 + b])]


def _handle(spec: KitchenSpec, w, h, d, tier, hinge, horizontal=False, source: str | None = None) -> dict | None:
    hd = hardware.handle(spec.chung.tayNam, w, h, tier, hinge, horizontal)
    if hd is None:
        return None
    out = {"type": hd["type"], "assetId": hd["assetId"], "materialId": "MAT-HANDLE",
           "transform": _tf((hd["x"], hd["y"], d)), "dimensions": _dims(*hd["size"])}
    if source:
        out["sourceRef"] = source  # ID chi tiết tay nắm trong bộ biên dịch (= layer sửa ảnh)
    return out


def _module_entry(spec: KitchenSpec, m: Module, parts: list[Part], frame: Frame, size, mats: dict, led: bool) -> dict:
    c = spec.chung
    tang = m.tang
    tier = TIER[tang]
    front = {"duoi": "tuDuoi", "tren": "tuTren", "noc": "tuTren", "cao": "tuCao", "goc": "keGoc"}[tang]
    if m.vatLieu:  # vật liệu mặt trước riêng của module (vd đổi màu một tủ từ ảnh AI)
        front = f"module:{m.ma}"
    entry = {
        "id": f"MOD-{m.ma}", "moduleType": "corner_cabinet" if m.gocKhuat else ("appliance_cabinet" if m.loai == "cao-tu-lanh" else MODULE_TYPE[tang]),
        "name": m.ten or m.ma, "dimensions": _dims(*size), "transform": _tf(frame.pos, frame.rot),
        "carcaseMaterialId": mats["keGoc"] if tang == "goc" else mats["than"], "frontMaterialId": mats[front],
        "frontStyle": {"kinh": "glass", "khung": "shaker", "phang": "slab"}.get(m.kieuCanh or "", "glass" if m.loai == "tren-kinh" else "slab"),
        "sourceRef": m.ma, "tier": tier,
        "placement": {"wallId": "WALL-SAU" if m.tuong == "goc" else f"WALL-{m.tuong.upper()}",
                      "alignment": "floor" if m.y == 0 else "wall", "offset": m.tu, "elevation": m.y},
        "construction": {"panelThickness": c.dayCanh, "backThickness": c.dayHau, "toeKickHeight": c.lenChan if m.y == 0 else 0,
                         "doorOverlay": "full", "gap": c.kheCanh, "grainDirection": "vertical",
                         "edgeBanding": {"thickness": 1, "materialId": mats[front]}},
        "doors": [], "drawers": [], "shelves": [], "parts": [], "visible": True,
    }
    if m.gocKhuat:
        entry["blindCorner"] = {"side": "left", "width": m.gocKhuat}
    if m.tamHong:
        entry["endPanel"] = {"side": "right", "thickness": m.tamHong}
    if led and tang in ("tren", "goc"):
        entry["led"] = True
    t = c.dayCanh
    door_parts, n = [], defaultdict(int)

    def pid(role):
        n[role] += 1
        return f"{m.ma}-{role}-{n[role]}"

    handle_of = {p.parent: p.id for p in parts if p.loai == "tay-nam" and p.parent}
    for p in parts:
        if p.loai == "tay-nam":
            continue  # tay nắm xuất ở doors[].hardware / drawers[].hardware
        lo, hi = frame.box_local(p.min, p.max)
        if p.loai == "than":
            for role, crole, a, b in _split_carcass(lo, hi, t, c.dayHau):
                e = {"id": pid(role), "role": role, "assetId": "ASSET-PANEL", "dimensions": _dims(b[0] - a[0], b[1] - a[1], b[2] - a[2]),
                     "transform": _tf(a), "materialId": mats["than"], "semanticClass": "carcass", "sourceRef": p.id}
                if crole:
                    e["customRole"] = crole
                entry["parts"].append(e)
        elif p.loai in ("canh", "canh-kinh"):
            door_parts.append((lo, hi, p.loai == "canh-kinh", p.id))
        elif p.loai == "ngan-keo":
            w, h, d = (hi[i] - lo[i] for i in range(3))
            entry["drawers"].append({"id": pid("drawer"), "assetId": "ASSET-DRAWER-FRONT", "height": round(h, 2), "materialId": mats[front],
                                     "dimensions": _dims(w, h, d), "transform": _tf(lo), "sourceRef": p.id,
                                     "hardware": _handle(spec, w, h, d, tier, None, horizontal=True, source=handle_of.get(p.id))})
            if entry["drawers"][-1]["hardware"] is None:
                entry["drawers"][-1].pop("hardware")
        else:
            role, crole, mat, sem = {
                "chan": ("plinth", None, mats["chan"], "plinth"),
                "ke": ("shelf", "niche_board" if tang == "duoi" else None, mats["keGoc"] if tang == "goc" else mats["than"], "shelf"),
            }.get(p.loai, (None, None, None, None))
            if p.loai == "hong":
                sz = size[0]
                if m.tamHong and lo[0] >= sz - m.tamHong - 1:
                    role, crole, mat = "custom", "end_panel", mats[front]
                elif lo[0] <= 1:
                    role, mat = "left_side", mats[front] if tang in ("cao", "goc") else mats["than"]
                elif hi[0] >= sz - 1:
                    role, mat = "right_side", mats[front] if tang in ("cao", "goc") else mats["than"]
                else:
                    role, mat = "divider", mats["than"]
                sem = "panel"
            if role is None:
                role, crole, mat, sem = "custom", None, mats["than"], SEMANTIC.get(p.loai, "custom")
            e = {"id": pid(role), "role": role, "assetId": "ASSET-PLINTH" if role == "plinth" else "ASSET-SHELF" if role == "shelf" else "ASSET-PANEL",
                 "dimensions": _dims(*(hi[i] - lo[i] for i in range(3))), "transform": _tf(lo), "materialId": mat, "semanticClass": sem,
                 "sourceRef": p.id}
            if crole:
                e["customRole"] = crole
            entry["parts"].append(e)
            if role == "shelf":
                entry["shelves"].append({"id": e["id"], "heightOffset": round(lo[1], 2), "materialId": mat})

    # cánh: bản lề theo moCanh hoặc tự suy (kitchen.hardware, dùng chung với bộ biên dịch hình học)
    door_parts.sort(key=lambda x: (x[0][1], x[0][0]))
    rows = defaultdict(list)
    for d in door_parts:
        rows[round(d[0][1])].append(d)
    flat = [d for _, ds in sorted(rows.items()) for d in sorted(ds, key=lambda x: x[0][0])]
    hinge_of = hardware.hinges(m, [(lo[0], hi[0], lo[1], hi[1]) for lo, hi, _, _ in flat])
    for k, (lo, hi, glass, src) in enumerate(flat):
        w, h, d = (hi[j] - lo[j] for j in range(3))
        hinge = hinge_of[k]
        door = {"id": pid("door"), "assetId": "ASSET-DOOR-GLASS" if glass else "ASSET-DOOR-SLAB", "hingeSide": hinge,
                "materialId": mats["kinh"] if glass else mats[front], "dimensions": _dims(w, h, d), "transform": _tf(lo),
                "glass": glass, "frontStyle": "glass" if glass else entry["frontStyle"], "openingAngle": 0, "sourceRef": src,
                "hinges": [{"offset": 100}, {"offset": round(h - 100, 1)}] + ([{"offset": round(h / 2, 1)}] if h > 1200 else [])}
        hw = _handle(spec, w, h, d, tier, hinge, horizontal=hinge in ("Top", "Bottom"), source=handle_of.get(src))
        if hw:
            door["hardware"] = hw
        entry["doors"].append(door)
    entry["construction"]["hingeCountPerDoor"] = max((len(dd["hinges"]) for dd in entry["doors"]), default=0)
    return entry


# ------------------------------------------------------------------ xuất toàn cảnh
def export(spec: KitchenSpec, design_id: str = "design", rev: int = 1, kb_rows: list[dict] | None = None,
           quoc_gia: str | None = None) -> dict:
    from .rules import default_rows
    from .rules_kb import select

    scene = compile_spec(spec)
    c = spec.chung
    mats_list, mats = _materials(spec)
    qg, kv = regions.chuan_hoa(quoc_gia or spec.quocGia, spec.khuVuc)
    sel = select(kb_rows if kb_rows is not None else default_rows(), qg, kv)
    by_mod = defaultdict(list)
    for p in scene.parts:
        by_mod[p.module].append(p)
    has_led = any(t.loai == "den" for t in spec.thietBi)

    # phòng
    lsau, lphai = scene.lsau, scene.lphai
    walls = [{"id": "WALL-SAU", "start": _v(0, 0, 0), "end": _v(-lsau, 0, 0), "height": c.tran, "thickness": 100,
              "materialId": mats["tuong"], "interiorNormal": _v(0, 0, 1), "openings": []},
             {"id": "WALL-PHAI", "start": _v(0, 0, 0), "end": _v(0, 0, lphai), "height": c.tran, "thickness": 100,
              "materialId": mats["tuong"], "interiorNormal": _v(-1, 0, 0), "openings": []}]
    if any(m.tuong == "trai" for m in spec.module):
        walls.append({"id": "WALL-TRAI", "start": _v(-lsau, 0, 0), "end": _v(-lsau, 0, lphai), "height": c.tran, "thickness": 100,
                      "materialId": mats["tuong"], "interiorNormal": _v(1, 0, 0), "openings": []})
    if spec.phong:
        for tw in spec.phong.tuong:
            wall = next((w for w in walls if w["id"] == f"WALL-{tw.ma.upper()}"), None)
            if wall:
                wall["thickness"] = tw.day
                for i, lo in enumerate(tw.lo):
                    wall["openings"].append({"id": f"{wall['id']}-LO{i + 1}", "type": "window" if lo.loai == "cua-so" else "door",
                                             "offset": lo.tu, "width": lo.rong, "height": lo.cao, "sillHeight": lo.caoBauCua})
    room = {"dimensions": _dims(lsau, c.tran, lphai), "walls": walls, "floor": {"materialId": mats["san"], "thickness": 0},
            "ceiling": {"height": c.tran, "materialId": mats["tuong"], "render": False}}

    # module
    modules = []
    for m in spec.module:
        frame, size = _module_frame(m, lsau)
        modules.append(_module_entry(spec, m, by_mod.get(m.ma, []), frame, size, mats, has_led))

    # thiết bị & phụ kiện
    app_type = {"tu-lanh": "Refrigerator", "hut-mui": "Range_Hood_Insert", "lo": "Microwave"}
    appliances, accessories = [], []
    for tb in spec.thietBi:
        ps = by_mod.get(tb.ma, [])
        if not ps:
            continue
        p = ps[0]
        host = spec.tim(tb.module) if tb.module else next((mm for mm in spec.module if mm.tuong == tb.tuong and mm.tang == "duoi"
                                                          and tb.tam is not None and mm.tu <= tb.tam < mm.het), None)
        tuong = host.tuong if host and host.tuong != "goc" else (tb.tuong or "sau")
        fr = Frame.for_aabb(p.min, p.max, tuong)
        lo, hi = fr.box_local(p.min, p.max)
        dims = _dims(*(hi[i] - lo[i] for i in range(3)))
        name = (tb.ten or "").lower()
        if tb.loai in app_type or tb.loai == "bep":
            t = "Cooktop_Gas" if "gas" in name else "Cooktop_Induction" if tb.loai == "bep" else app_type[tb.loai]
            a = {"id": f"APP-{tb.ma}", "type": t, "name": tb.ten or tb.ma, "assetId": "ASSET-APPLIANCE-BOX", "dimensions": dims,
                 "transform": _tf(fr.pos, fr.rot), "materialId": mats["bep"] if tb.loai == "bep" else mats["inox"], "sourceRef": tb.ma,
                 "energy": "gas" if "gas" in name else ("induction" if tb.loai == "bep" else "electric"),
                 "installation": {"mountType": {"tu-lanh": "freestanding", "bep": "built_in", "hut-mui": "built_in", "lo": "built_in"}[tb.loai]}}
            if host:
                a["parentModuleId"] = f"MOD-{host.ma}"
            if tb.loai == "bep" and "hut-mui" in sel:
                a["clearances"] = {"top": sel["hut-mui"]["params"].get("khoang_min", 650)}
            appliances.append(a)
        elif tb.loai in ("chau", "voi"):
            accessories.append({"id": f"ACC-{tb.ma}", "type": ("Sink_Double" if "đôi" in name else "Sink_Single") if tb.loai == "chau" else "Faucet_Classic",
                                "assetId": "ASSET-SINK" if tb.loai == "chau" else "ASSET-FAUCET",
                                **({"parentId": f"MOD-{host.ma}"} if host else {}), "dimensions": dims, "transform": _tf(fr.pos, fr.rot),
                                "materialId": mats["chau"] if tb.loai == "chau" else mats["inox"], "sourceRef": tb.ma})

    # mặt đá (+ lỗ khoét ước lượng) và ốp tường
    cut_targets = [x for x in appliances if x["type"].startswith("Cooktop")] + [x for x in accessories if x["type"].startswith("Sink")]
    for i, p in enumerate([p for p in scene.parts if p.loai == "mat-da"]):
        fr = Frame.for_aabb(p.min, p.max, p.tuong)
        lo, hi = fr.box_local(p.min, p.max)
        w, h, d = (hi[k] - lo[k] for k in range(3))
        cutouts = []
        for tgt in cut_targets:
            src = next(pp for pp in scene.parts if pp.module == tgt["sourceRef"])
            if src.tuong == p.tuong and all(p.min[k] - 1 <= src.min[k] and src.max[k] <= p.max[k] + 1 for k in (0, 2)):
                llo, lhi = fr.box_local(src.min, src.max)
                cw, cd = lhi[0] - llo[0] - 20, lhi[2] - llo[2] - 20
                cutouts.append({"forId": tgt["id"], "type": "cooktop" if tgt["id"].startswith("APP") else "sink",
                                "dimensions": _dims(cw, h, cd), "transform": _tf((llo[0] + 10, 0, llo[2] + 10)), "estimated": True})
        accessories.append({"id": f"ACC-COUNTERTOP-{i + 1}", "type": "Countertop", "assetId": "ASSET-COUNTERTOP", "dimensions": _dims(w, h, d),
                            "transform": _tf(fr.pos, fr.rot), "materialId": mats["matDa"], "edgeProfile": "eased", "overhang": c.nhoMatDa,
                            "cutouts": cutouts, "sourceRef": f"mat-da-{p.tuong}"})
        uppers = [mm for mm in spec.module if mm.tuong == p.tuong and mm.tang in ("tren", "cao")]
        top = min([mm.y for mm in uppers if mm.tang == "tren"] + [c.dayTuTren]) if uppers else c.matDa + 600
        if c.vatLieu.get("opTuong") and top > c.matDa + 50:  # ốp tường giữa mặt đá và tủ trên, sát tường
            accessories.append({"id": f"ACC-BACKSPLASH-{i + 1}", "type": "Backsplash_Tile", "assetId": "ASSET-PANEL",
                                "dimensions": _dims(w, top - c.matDa, 8), "materialId": mats["opTuong"],
                                "transform": _tf((fr.pos[0], c.matDa, fr.pos[2]), fr.rot), "sourceRef": f"op-tuong-{p.tuong}"})

    # phào: mặt cắt -> assets (dùng chung), đường chạy -> decorations
    from . import moldings as _mol
    decorations, assets = [], list(ASSETS)
    seen_prof = set()
    for i, run in enumerate(_mol.compute_runs(spec)):
        mol, prof = run.molding, run.profile
        aid = f"ASSET-MOLDING-{prof.ma}"
        us = [u for u, _ in prof.points]
        if prof.ma not in seen_prof:
            seen_prof.add(prof.ma)
            assets.append({"id": aid, "category": "cornice" if mol.kieu == "crown" else "molding", "geometryType": "extrusion",
                           "defaultDimensions": _dims(1000, prof.cao, max(us) - min(us)),
                           "parameters": {"profileId": prof.ma, "name": prof.ten, "profile": [[round(u, 2), round(v, 2)] for u, v in prof.points],
                                          "convention": "u: nhô ra phía phòng từ mặt trước tủ (âm = lùi vào); v: lên từ đường chạy; đa giác kín, ngược chiều kim đồng hồ"}})
        if mol.vatLieu:
            mid = f"MAT-MOLDING-{mol.ma}"
            if all(m["id"] != mid for m in mats_list):
                mats_list.append({"id": mid, "name": mol.vatLieu, "threeMaterialType": "MeshStandardMaterial", "roughness": 0.5,
                                  "metalness": 0.0, **_guess(mol.vatLieu), "semanticClass": "molding"})
        else:
            mid = mats["tuTren"] if mol.kieu == "crown" else mats["tuDuoi"]
        decorations.append({
            "id": f"MOLD-{mol.ma}-{i + 1}", "type": "Crown_Molding" if mol.kieu == "crown" else "Base_Molding",
            "name": f"{'Phào nóc' if mol.kieu == 'crown' else 'Phào chân'} ({', '.join(run.tuong)})", "assetId": aid,
            "dimensions": _dims(run.length, prof.cao, max(us) - min(us)), "transform": _tf((0, 0, 0)), "materialId": mid,
            "path": {"type": "polyline", "points": [_v(x, run.y, z) for x, z in run.points], "joints": "miter", "ends": "flush",
                     "normalRule": "pháp tuyến phía phòng n = (t.z, 0, -t.x), t = hướng đi của đoạn"},
            "sourceRef": mol.ma, "semanticClass": "molding", "modules": [f"MOD-{m}" for m in dict.fromkeys(run.modules)]})

    # đèn
    lo_b, hi_b = scene.bounds()
    cx, cz = (lo_b[0] + hi_b[0]) / 2, (lo_b[2] + hi_b[2]) / 2
    lighting = [{"id": "LIGHT-HEMI", "type": "HemisphereLight", "color": "#ffffff", "groundColor": "#8a8170", "intensity": 1.2},
                {"id": "LIGHT-SUN", "type": "DirectionalLight", "color": "#fff6e8", "intensity": 1.4, "position": _v(cx - 3000, 4000, cz + 3000),
                 "target": _v(cx, 800, cz), "castShadow": True}]
    if has_led:
        for mod in modules:
            if mod.get("led") and mod["tier"] == "wall":
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
        pos = [x * 1000 for x in v.viTri]
        tgt = [x * 1000 for x in v.nhinVao]
        d = [b - a for a, b in zip(pos, tgt)]
        n = math.sqrt(sum(x * x for x in d)) or 1
        up = _v(0, 0, -1) if abs(d[1] / n) > 0.999 else _v(0, 1, 0)
        cameras.append({"id": f"CAM-{key}", "name": v.ten or key, "position": _v(*pos), "target": _v(*tgt), "projection": "perspective",
                        "fov": v.fovDoc, "fovAxis": "vertical", "near": 50, "far": 50000, "up": up, "aspect": round(4 / 3, 4)})

    p_cb = (sel.get("chau-bep") or {}).get("params", {})
    p_ld = (sel.get("loi-di") or {}).get("params", {})
    p_kt = (sel.get("khoang-tu-tren") or {}).get("params", {})
    p_hm = (sel.get("hut-mui") or {}).get("params", {})
    constraints = {"allowTouching": True, "overlapTolerance": 1, "minimumSinkCooktopDistance": p_cb.get("chau_bep_min", 300),
                   "minimumWalkwayWidth": p_ld.get("loiDi_min", p_ld.get("loiDi_1nguoi", 900)), "enforceRoomBounds": True,
                   "minimumCountertopToWallCabinet": p_kt.get("khoang_tren_min", 450), "minimumHoodClearance": p_hm.get("khoang_min", 650),
                   "sources": {k: sel[t]["code"] for k, t in (("minimumSinkCooktopDistance", "chau-bep"), ("minimumWalkwayWidth", "loi-di"),
                                                              ("minimumCountertopToWallCabinet", "khoang-tu-tren"), ("minimumHoodClearance", "hut-mui"))
                               if t in sel}}
    palette = {SEMANTIC.get(k, k): _hex(v) for k, v in SEG_MAU.items()}
    palette.update({f"module:{m.ma}": _hex(_mau_module(m.ma)) for m in spec.module})

    doc = {
        "schemaVersion": "1.1.0",
        "metadata": {"designId": re.sub(r"[^A-Za-z0-9_.:-]", "-", design_id) or "design", "projectName": spec.ten,
                     "description": spec.nguon or "", "style": spec.phongCach, "revision": max(1, rev), "author": "kitchen-design-mcp",
                     "createdAt": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
                     "region": {"countryCode": qg, "regionCode": kv, "appliedRules": {t: v["code"] for t, v in sel.items()}},
                     "source": {"generator": "kitchen.threejs_export", "specSchemaVersion": spec.schemaVersion, "specRevision": rev}},
        "units": "mm",
        "coordinateSystem": {"upAxis": "+Y", "forwardAxis": "+Z", "handedness": "right", "origin": "kitchen_inner_corner",
                             "positionAnchor": "bottom_back_left", "metersPerUnit": 0.001,
                             "wallFrames": [{"wallId": "WALL-SAU", "origin": _v(0, 0, 0), "alongAxis": _v(-1, 0, 0), "frontAxis": _v(0, 0, 1), "rotationY": 0},
                                            {"wallId": "WALL-PHAI", "origin": _v(0, 0, 0), "alongAxis": _v(0, 0, 1), "frontAxis": _v(-1, 0, 0), "rotationY": -90},
                                            {"wallId": "WALL-TRAI", "origin": _v(-lsau, 0, 0), "alongAxis": _v(0, 0, 1), "frontAxis": _v(1, 0, 0), "rotationY": 90}],
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
