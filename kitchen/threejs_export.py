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

from collections.abc import Sequence
from typing import Any

import math
import re
from collections import defaultdict

from .numeric import round_half_away, round_int
from . import appliance_models, builtin, runs, floorplan as fpmod, roomctx, hardware, regions, vocab
from .geometry import Part, backsplash_height, compile_spec, views_of
from .catalog import Catalog
from .errors import InvalidInput, require
from .jsonview import as_dict, as_list
from .palette import SEGMENT_COLORS, module_color as _module_color
from .spec import Handle, KitchenSpec, Module, effective_handle

ROT = {"back": 0.0, "right": -90.0, "left": 90.0, "corner": 0.0, "island": 180.0}
TIER = {"base": "base", "upper": "wall", "loft": "top", "tall": "tall", "corner": "corner"}
MODULE_TYPE = {"base": "base_cabinet", "upper": "wall_cabinet", "loft": "wall_cabinet", "tall": "tall_pantry", "corner": "open_shelf"}
SEMANTIC = {"carcass": "carcass", "plinth": "plinth", "door": "door", "glass-door": "glass_door", "drawer": "drawer", "side-panel": "panel",
            "shelf": "shelf", "countertop": "countertop", "fridge": "refrigerator", "sink": "sink", "faucet": "faucet", "cooktop": "cooktop",
            "hood": "range_hood", "oven": "microwave", "tv": "television", "wall": "wall", "floor": "floor", "wall-tile": "backsplash", "handle": "handle",
            "molding": "molding"}


Vec3 = tuple[float, float, float]
Box = tuple[list[float], list[float]]          # (low corner, high corner) of a local box


def _hex(rgb: Sequence[float]) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb)


def _v(x: float, y: float, z: float) -> dict[str, Any]:
    return {"x": round_half_away(float(x), 2), "y": round_half_away(float(y), 2), "z": round_half_away(float(z), 2)}


def _tf(pos: Sequence[float], rot_y: float = 0.0) -> dict[str, Any]:
    return {"position": _v(pos[0], pos[1], pos[2]), "rotation": {"x": 0, "y": round_half_away(rot_y, 4), "z": 0, "unit": "deg"}}


def _dims(w: float, h: float, d: float) -> dict[str, Any]:
    return {"width": round_half_away(max(w, 0.01), 2), "height": round_half_away(max(h, 0.01), 2), "depth": round_half_away(max(d, 0.01), 2)}


def _rot(v: Sequence[float], deg: float) -> Vec3:
    """Quay véc-tơ quanh Y theo quy ước three.js (rotation.y)."""
    t = math.radians(deg)
    x, y, z = v
    return (x * math.cos(t) + z * math.sin(t), y, -x * math.sin(t) + z * math.cos(t))


class Frame:
    """Khung cục bộ (anchor bottom-back-left) của module hoặc vật đặt theo tường."""

    def __init__(self, pos: Sequence[float], rot_y: float, origin: Sequence[float] = (0.0, 0.0, 0.0), run: str | None = None):
        self.pos: Vec3 = (pos[0], pos[1], pos[2])
        self.rot = rot_y
        self.run = run                   # id of the run whose coordinates ``origin`` is in (None: any part with run coordinates is in this frame's run)
        self.origin: Vec3 = (origin[0], origin[1], origin[2])     # run coordinates (s, y, d) of ``pos`` for a frame inside an angled run; unused otherwise

    def part_box(self, p: Part) -> Box:
        """Local box of a part: from its run coordinates when it stands in an angled run, else from its world AABB."""
        if p.frame is not None and p.lmin is not None and p.lmax is not None and (self.run is None or p.run == self.run):
            return [p.lmin[i] - self.origin[i] for i in range(3)], [p.lmax[i] - self.origin[i] for i in range(3)]
        return self.box_local(p.min, p.max)                               # a part of another run (the far leg of a corner shelf): from its world box

    @staticmethod
    def for_part(p: Part, wall: str | None) -> "Frame":
        """Frame at the anchor corner of a part: its run frame for an angled part, else the axis frame of its wall."""
        if p.frame is not None and p.lmin is not None and p.run_frame is not None:
            x, z = p.run_frame.to_world(p.lmin[0], p.lmin[2])
            return Frame((x, p.lmin[1], z), p.frame[2], p.lmin)
        return Frame.for_aabb(p.min, p.max, wall)

    def to_local(self, p: Sequence[float]) -> Vec3:
        d = (p[0] - self.pos[0], p[1] - self.pos[1], p[2] - self.pos[2])
        return _rot(d, -self.rot)

    def box_local(self, mn: Sequence[float], mx: Sequence[float]) -> Box:
        pts = [self.to_local((x, y, z)) for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
        openings = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        return openings, hi

    @staticmethod
    def for_aabb(mn: Sequence[float], mx: Sequence[float], wall: str | None) -> "Frame":
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


def _module_frame(m: Module, lsau: float, fr: "runs.RunFrame | None" = None) -> tuple[Frame, tuple[float, float, float]]:
    if fr is not None:               # explicit run at any angle: the module frame is the run frame moved to s = fromCorner
        x, z = fr.to_world(m.fromCorner, 0.0)
        if m.turnsInto:                  # a corner shelf by runs: as wide as its first leg, as deep as its second leg is long
            return Frame((x, m.y, z), fr.yaw, (m.fromCorner, m.y, 0.0), fr.id), (m.width, m.height, require(m.rightLength, f"{m.id}.rightLength"))
        return Frame((x, m.y, z), fr.yaw, (m.fromCorner, m.y, 0.0)), (m.width, m.height, m.depth)
    if m.type == "corner-shelf":
        bl, rl = require(m.backLength, f"{m.id}.backLength"), require(m.rightLength, f"{m.id}.rightLength")
        return Frame((-bl, m.y, 0), 0.0), (bl, m.height, rl)
    seat = runs.seat_of(m, lsau) or runs.wall_seat("left", lsau)   # anchor = the back-left corner seen from the front, whatever seats the cabinet
    assert seat is not None
    x, z = seat.to_world(seat.left_end(m.fromCorner, m.fromCorner + m.width), 0)
    return Frame((x, m.y, z), seat.yaw), (m.width, m.height, m.depth)


def _guess(text: str, catalog: Catalog) -> dict[str, Any]:
    g = _guess_base(text, catalog)
    w = vocab.find(text, vocab.woods(catalog))  # loài gỗ nêu rõ (óc chó, teak…) quyết định màu gỗ
    if w and "transmission" not in g:
        g = {**g, "color": w[1]}
    c = vocab.explicit_color(text, catalog)  # màu nêu rõ (xanh rêu, kem, xám…) ghi đè màu mặc định của chất liệu
    if c and "transmission" not in g:
        g = {**g, "color": c}
    return g


_NO_LOOK: dict[str, Any] = {"color": "#d9c3a0", "roughness": 0.6}


def _guess_base(text: str, catalog: Catalog) -> dict[str, Any]:
    """The 3D look of a material name: the first ``material-look`` rule whose words are in the name (plain substring, lower case)."""
    t = (text or "").lower()
    for it in catalog.all("material-look"):
        d = it.data
        any_of = [str(w).lower() for w in as_list(d.get("any")) or []]
        all_of = [str(w).lower() for w in as_list(d.get("all")) or []]
        if (not any_of or any(w in t for w in any_of)) and all(w in t for w in all_of):
            return dict(as_dict(d.get("look")) or _NO_LOOK)
    return dict(_NO_LOOK)


def _materials(spec: KitchenSpec, catalog: Catalog) -> tuple[list[dict[str, Any]], dict[str, str]]:
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
    out: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    for key, (mid, name, sem) in defs.items():
        g: dict[str, Any] = {"threeMaterialType": "MeshStandardMaterial", "roughness": 0.5, "metalness": 0.0, **_guess(name, catalog)}
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
        material_text: dict[str, Any] = {"id": mid, "name": name, **g, "semanticClass": sem}
        if key == "wallTile" and spec.common.model_extra and spec.common.model_extra.get("wallTile"):
            a, b = spec.common.model_extra["wallTile"][:2]
            material_text["textureRepeat"] = {"u": round_half_away(1000 / a, 3), "v": round_half_away(1000 / b, 3)}  # số viên trên mỗi mét
        if key == "wallTile" and spec.common.wallTilePattern:
            material_text["pattern"] = spec.common.wallTilePattern  # kiểu xếp gạch (chưa vẽ từng viên)
        if key == "floor" and spec.common.model_extra and spec.common.model_extra.get("floorTile"):
            a, b = spec.common.model_extra["floorTile"][:2]
            material_text["textureRepeat"] = {"u": round_half_away(1000 / a, 3), "v": round_half_away(1000 / b, 3)}
        out.append(material_text)
        ids[key] = mid
    for m in spec.module:  # vật liệu mặt trước riêng từng module
        if m.material:
            mid = "MAT-FRONT-" + re.sub(r"[^A-Za-z0-9_.:-]", "-", m.id)
            out.append({"id": mid, "name": m.material, "threeMaterialType": "MeshStandardMaterial", "roughness": 0.5, "metalness": 0.0,
                        **_guess(m.material, catalog), "semanticClass": "front"})
            ids[f"module:{m.id}"] = mid
    for m in spec.module:  # handle material of a module that differs from the common one
        hm = effective_handle(spec.common, m).material
        if hm != spec.common.handle.material:
            mid = "MAT-HANDLE-" + re.sub(r"[^A-Za-z0-9_.:-]", "-", m.id)
            out.append({"id": mid, "name": hm, "threeMaterialType": "MeshStandardMaterial", "roughness": 0.5, "metalness": 0.0,
                        **_guess(hm, catalog), "semanticClass": "handle"})
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
def _split_carcass(openings: list[float], hi: list[float], t: float, b: float) -> list[tuple[str, str | None, list[float], list[float]]]:
    """Thân hộp -> hông trái/phải, đáy, nóc, hậu (toạ độ cục bộ)."""
    (x0, y0, z0), (x1, y1, z1) = openings, hi
    if x1 - x0 < 3 * t or y1 - y0 < 3 * t or z1 - z0 < 80:
        return [("back" if z1 - z0 < 80 else "custom", "niche_back" if z1 - z0 < 80 else None, openings, hi)]
    return [("left_side", None, [x0, y0, z0], [x0 + t, y1, z1]),
            ("right_side", None, [x1 - t, y0, z0], [x1, y1, z1]),
            ("bottom", None, [x0 + t, y0, z0 + b], [x1 - t, y0 + t, z1]),
            ("top", None, [x0 + t, y1 - t, z0 + b], [x1 - t, y1, z1]),
            ("back", None, [x0 + t, y0 + t, z0], [x1 - t, y1 - t, z0 + b])]


def _handle(hn: Handle, material_id: str, w: float, h: float, d: float, tier: str, hinge: str | None, horizontal: bool = False,
            source: str | None = None) -> dict[str, Any] | None:
    hd = hardware.handle(hn, w, h, tier, hinge, horizontal)
    if hd is None:
        return None
    out: dict[str, Any] = {"type": hd["type"], "assetId": hd["assetId"], "materialId": material_id,
           "transform": _tf((hd["x"], hd["y"], d)), "dimensions": _dims(hd["size"][0], hd["size"][1], hd["size"][2])}
    if source:
        out["sourceRef"] = source  # ID chi tiết tay nắm trong bộ biên dịch (= layer sửa ảnh)
    return out


def _module_entry(spec: KitchenSpec, m: Module, parts: list[Part], frame: Frame, size: Vec3, mats: dict[str, Any], led: bool) -> dict[str, Any]:
    c = spec.common
    storey = m.storey
    tier = TIER[storey]
    hn, hmat = effective_handle(c, m), mats.get(f"handle:{m.id}", mats["handle"])
    front = {"base": "base", "upper": "upper", "loft": "upper", "tall": "tall", "corner": "cornerShelf"}[storey]
    if m.material:  # vật liệu mặt trước riêng của module (vd đổi màu một tủ từ ảnh AI)
        front = f"module:{m.id}"
    entry: dict[str, Any] = {
        "id": f"MOD-{m.id}", "moduleType": "corner_cabinet" if m.blindCorner else ("appliance_cabinet" if m.type == "tall-fridge" else MODULE_TYPE[storey]),
        "name": m.name or m.id, "dimensions": _dims(size[0], size[1], size[2]), "transform": _tf(frame.pos, frame.rot),
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
        entry["blindCorner"] = {"side": "left" if m.blindSide == "start" else "right", "width": m.blindCorner}
    if m.endPanel:
        entry["endPanel"] = {"side": "right" if m.blindSide == "start" else "left", "thickness": m.endPanel}
    if led and storey in ("upper", "corner"):
        entry["led"] = True
    t = c.doorThickness
    door_parts: list[tuple[list[float], list[float], bool, str]] = []
    n: defaultdict[str, int] = defaultdict(int)

    def pid(role: str) -> str:
        n[role] += 1
        return f"{m.id}-{role}-{n[role]}"

    handle_of = {p.parent: p.id for p in parts if p.type == "handle" and p.parent}
    for p in parts:
        if p.type == "handle":
            continue  # tay nắm xuất ở doors[].hardware / drawers[].hardware
        openings, hi = frame.part_box(p)
        if p.type == "carcass":
            for role, crole, a, b in _split_carcass(openings, hi, t, c.backThickness):
                e: dict[str, Any] = {"id": pid(role), "role": role, "assetId": "ASSET-PANEL", "dimensions": _dims(b[0] - a[0], b[1] - a[1], b[2] - a[2]),
                     "transform": _tf(a), "materialId": mats["carcass"], "semanticClass": "carcass", "sourceRef": p.id}
                if crole:
                    e["customRole"] = crole
                entry["parts"].append(e)
        elif p.type in ("door", "glass-door"):
            door_parts.append((openings, hi, p.type == "glass-door", p.id))
        elif p.type == "drawer":
            w, h, d = (hi[i] - openings[i] for i in range(3))
            entry["drawers"].append({"id": pid("drawer"), "assetId": "ASSET-DRAWER-FRONT", "height": round_half_away(h, 2), "materialId": mats[front],
                                     "dimensions": _dims(w, h, d), "transform": _tf(openings), "sourceRef": p.id,
                                     "hardware": _handle(hn, hmat, w, h, d, tier, None, horizontal=True, source=handle_of.get(p.id))})
            if entry["drawers"][-1]["hardware"] is None:
                entry["drawers"][-1].pop("hardware")
        else:
            spec_of: dict[str, tuple[str | None, str | None, str | None, str | None]] = {
                "plinth": ("plinth", None, mats["plinth"], "plinth"),
                "shelf": ("shelf", "niche_board" if storey == "base" else None, mats["cornerShelf"] if storey == "corner" else mats["carcass"], "shelf"),
            }
            role, crole, material_text, sem = spec_of.get(p.type, (None, None, None, None))
            if p.type == "side-panel":
                sz = size[0]
                if m.endPanel and (openings[0] >= sz - m.endPanel - 1 if m.blindSide == "start" else hi[0] <= m.endPanel + 1):
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
                 "dimensions": _dims(hi[0] - openings[0], hi[1] - openings[1], hi[2] - openings[2]), "transform": _tf(openings), "materialId": material_text,
                 "semanticClass": sem,
                 "sourceRef": p.id}
            if crole:
                e["customRole"] = crole
            entry["parts"].append(e)
            if role == "shelf":
                entry["shelves"].append({"id": e["id"], "heightOffset": round_half_away(openings[1], 2), "materialId": material_text})

    # cánh: bản lề theo moCanh hoặc tự suy (kitchen.hardware, dùng chung với bộ biên dịch hình học)
    door_parts.sort(key=lambda x: (x[0][1], x[0][0]))
    rows: defaultdict[int, list[tuple[list[float], list[float], bool, str]]] = defaultdict(list)
    for d in door_parts:
        rows[round_int(d[0][1])].append(d)
    flat = [d for _, ds in sorted(rows.items()) for d in sorted(ds, key=lambda x: x[0][0])]
    hinge_of = hardware.hinges(m, [(openings[0], hi[0], openings[1], hi[1]) for openings, hi, _, _ in flat])
    for k, (openings, hi, glass, src) in enumerate(flat):
        w, h, d = (hi[j] - openings[j] for j in range(3))
        hinge = hinge_of[k]
        door: dict[str, Any] = {"id": pid("door"), "assetId": "ASSET-DOOR-GLASS" if glass else "ASSET-DOOR-SLAB", "hingeSide": hinge,
                "materialId": mats["glass"] if glass else mats[front], "dimensions": _dims(w, h, d), "transform": _tf(openings),
                "glass": glass, "frontStyle": "glass" if glass else entry["frontStyle"], "openingAngle": 0, "sourceRef": src,
                "hinges": [{"offset": 100}, {"offset": round_half_away(h - 100, 1)}] + ([{"offset": round_half_away(h / 2, 1)}] if h > 1200 else [])}
        hw = _handle(hn, hmat, w, h, d, tier, hinge, horizontal=hinge in ("Top", "Bottom"), source=handle_of.get(src))
        if hw:
            door["hardware"] = hw
        entry["doors"].append(door)
    for kind, items in (("door", entry["doors"]), ("drawer", entry["drawers"])):   # v1.4: what a click on this mesh means
        for item in items:
            item["partRef"] = {"kind": kind, "module": m.id}
            if item.get("hardware"):
                item["hardware"]["partRef"] = {"kind": "handle", "module": m.id}
    entry["construction"]["hingeCountPerDoor"] = max((len(dd["hinges"]) for dd in entry["doors"]), default=0)
    return entry


def _run_docs(spec: KitchenSpec, modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """runs[]: one group per explicit run. Each module of a run gets placement.runId and a localTransform; its ``transform`` stays the world one
    and is checked to equal run.transform composed with localTransform (a mismatch is a bug in the exporter, so it raises)."""
    by_ref = {m["sourceRef"]: m for m in modules}
    out: list[dict[str, Any]] = []
    for r in spec.runs:
        fr = runs.RunFrame(r.id, r.x, r.z, r.yaw)
        members = sorted((m for m in spec.module if m.run == r.id), key=lambda m: (m.fromCorner, m.y))
        if not members:
            continue
        ids: list[str] = []
        for m in members:
            entry = by_ref[m.id]
            entry["placement"]["runId"] = f"RUN-{r.id}"
            entry["localTransform"] = _tf((m.fromCorner, m.y, 0.0), 0.0)
            x, z = fr.to_world(m.fromCorner, 0.0)
            pos = entry["transform"]["position"]
            if abs(pos["x"] - round_half_away(x, 2)) > 0.02 or abs(pos["z"] - round_half_away(z, 2)) > 0.02:
                raise InvalidInput(f"{m.id}: transform differs from run∘localTransform", code="export-run-mismatch")
            ids.append(entry["id"])
        nx, nz = fr.normal()
        out.append({"id": f"RUN-{r.id}", "sourceRef": r.id, "transform": _tf((r.x, 0.0, r.z), r.yaw), "modules": ids, "frontAxis": _v(nx, 0, nz)})
    return out


# ------------------------------------------------------------------ xuất toàn cảnh
UNSET_TIME = "1970-01-01T00:00:00+00:00"   # what an export made without a clock says; the service always passes the real time


def export(spec: KitchenSpec, design_id: str = "design", rev: int = 1, kb_rows: list[dict[str, Any]] | None = None,
           country: str | None = None, created_at: str = UNSET_TIME, catalog: Catalog = builtin.CATALOG) -> dict[str, Any]:
    """Scene document for ``spec``. Pure: ``created_at`` (ISO-8601 UTC) comes from the caller's clock, never from the wall clock here."""
    from .rules import default_rows
    from .rules_kb import select

    scene = compile_spec(spec)
    c = spec.common
    mats_list, mats = _materials(spec, catalog)
    qg, kv = regions.normalize(country or spec.country, spec.region)
    sel = select(kb_rows if kb_rows is not None else default_rows(), qg, kv)
    by_mod: defaultdict[str | None, list[Part]] = defaultdict(list)
    for p in scene.parts:
        by_mod[p.module].append(p)
    has_led = any(t.type == "light" for t in spec.appliances)

    # phòng
    lsau, lphai = scene.lsau, scene.lphai
    walls: list[dict[str, Any]] = [{"id": "WALL-BACK", "start": _v(0, 0, 0), "end": _v(-lsau, 0, 0), "height": c.ceiling, "thickness": 100,
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
    room: dict[str, Any] = {"dimensions": _dims(lsau, c.ceiling, lphai), "walls": walls, "floor": {"materialId": mats["floor"], "thickness": 0},
            "ceiling": {"height": c.ceiling, "materialId": mats["wall"], "render": False}}
    ctx = roomctx.for_spec(spec, lsau, lphai)   # imported floorplan: its room, real walls and elements replace the default room
    floorplan = ctx.floorplan if ctx else None
    binding = ctx.binding if ctx else None
    if ctx and floorplan is not None:
        sec = fpmod.room_section(floorplan, binding, mats["wall"], ctx.structures)
        room.update(walls=sec["walls"], structures=sec["structures"], dimensions=_dims(sec["width"], c.ceiling, sec["depth"]))
        room["floor"]["outline"] = sec["floorOutline"]

    # module
    modules: list[dict[str, Any]] = []
    system_of = runs.systems(spec)
    for m in spec.module:
        frame, size = _module_frame(m, lsau, runs.frame_of(spec, m))
        modules.append(_module_entry(spec, m, by_mod.get(m.id, []), frame, size, mats, has_led))
        modules[-1]["placement"]["cabinetSystemId"] = system_of[m.id]     # the cabinet system (runs.systems): a floorplan element id, auto-…, or design

    run_docs = _run_docs(spec, modules)

    # thiết bị & phụ kiện
    app_type = {"fridge": "Refrigerator", "hood": "Range_Hood_Insert", "oven": "BuiltIn_Oven", "tv": "Television"}
    appliances: list[dict[str, Any]] = []
    accessories: list[dict[str, Any]] = []
    for tb in spec.appliances:
        ps = by_mod.get(tb.id, [])
        if not ps:
            continue
        p = ps[0]
        host = spec.find(tb.module) if tb.module else next((mm for mm in spec.module if mm.wall == tb.wall and mm.storey == "base"
                                                          and tb.center is not None and mm.fromCorner <= tb.center < mm.endAt), None)
        wall = host.orient if host and host.wall != "corner" else (tb.wall or "back")
        fr = Frame.for_part(p, wall)
        openings, hi = fr.part_box(p)
        dims = _dims(hi[0] - openings[0], hi[1] - openings[1], hi[2] - openings[2])
        mid = appliance_models.model_id(tb, catalog)              # its model, or (old designs) the guess from its name
        cat: dict[str, Any] = appliance_models.models(catalog).get(mid or "", {})
        energy = tb.energy or cat.get("energy")
        look = {k: v for k, v in (("model", mid), ("rendering", "model-3d" if cat.get("asset3d") else "box-placeholder"),
                                  ("box", cat.get("box"))) if v is not None}
        if tb.type in app_type or tb.type == "cooktop":
            hanging = tb.type == "hood" and host is not None and host.storey == "base"      # over the hob, out of a cabinet (appliance_kind)
            t = ("Cooktop_Gas" if energy in ("gas", "mixed") else "Cooktop_Induction") if tb.type == "cooktop" else "Range_Hood_Canopy" if hanging else \
                ("Microwave" if cat.get("box", {}).get("kind") == "microwave" else "BuiltIn_Oven") if tb.type == "oven" else app_type[tb.type]
            a: dict[str, Any] = {"id": f"APP-{tb.id}", "type": t, "name": tb.name or tb.id, "assetId": "ASSET-APPLIANCE-BOX", "dimensions": dims,
                 "transform": _tf(fr.pos, fr.rot), "materialId": mats["cooktop"] if tb.type in ("cooktop", "tv") else mats["inox"], "sourceRef": tb.id,
                 "energy": energy or ("induction" if tb.type == "cooktop" else "electric"),
                 "installation": {"mountType": "wall_mounted" if hanging else {"fridge": "freestanding" if (tb.mount or "freestanding") != "built_in" else "built_in",
                                                                                  "cooktop": "built_in", "hood": "built_in", "oven": "built_in", "tv": "wall_mounted"}[tb.type]}, **look}
            if cat.get("asset3d"):
                a["modelUrl"] = cat["asset3d"]
            if host:
                a["parentModuleId"] = f"MOD-{host.id}"
            if tb.type == "cooktop" and "hood" in sel:
                a["clearances"] = {"top": sel["hood"]["params"].get("gap_min", 650)}
            appliances.append(a)
            for i, extra in enumerate(ps[1:], start=2):                 # more boxes of the same appliance (a hood's chimney)
                efr = Frame.for_part(extra, wall)
                lo, hi2 = efr.part_box(extra)
                appliances.append({**a, "id": f"APP-{tb.id}-{i}", "dimensions": _dims(hi2[0] - lo[0], hi2[1] - lo[1], hi2[2] - lo[2]),
                                   "transform": _tf(efr.pos, efr.rot), "name": f"{a['name']} (ống khói)"})
        elif tb.type in ("sink", "faucet"):
            accessories.append({"id": f"ACC-{tb.id}", "type": ("Sink_Double" if cat.get("box", {}).get("basins") == 2 else "Sink_Single") if tb.type == "sink" else "Faucet_Classic", **look,
                                "assetId": "ASSET-SINK" if tb.type == "sink" else "ASSET-FAUCET",
                                **({"parentId": f"MOD-{host.id}"} if host else {}), "dimensions": dims, "transform": _tf(fr.pos, fr.rot),
                                "materialId": mats["sink"] if tb.type == "sink" else mats["inox"], "sourceRef": tb.id})

    # mặt đá (+ lỗ khoét ước lượng) và ốp tường
    cut_targets = [x for x in appliances if x["type"].startswith("Cooktop")] + [x for x in accessories if x["type"].startswith("Sink")]
    for i, p in enumerate([p for p in scene.parts if p.type == "countertop"]):
        fr = Frame.for_part(p, p.orient)
        openings, hi = fr.part_box(p)
        w, h, d = (hi[k] - openings[k] for k in range(3))
        cutouts: list[dict[str, Any]] = []
        for tgt in cut_targets:
            src = next(pp for pp in scene.parts if pp.module == tgt["sourceRef"])
            inside = (src.run == p.run and src.lmin is not None and src.lmax is not None and p.lmin is not None and p.lmax is not None and
                      all(p.lmin[k] - 1 <= src.lmin[k] and src.lmax[k] <= p.lmax[k] + 1 for k in (0, 2))) if p.frame is not None else \
                (src.wall == p.wall and src.frame is None and all(p.min[k] - 1 <= src.min[k] and src.max[k] <= p.max[k] + 1 for k in (0, 2)))
            if inside:
                llo, lhi = fr.part_box(src)
                own = next((a.cutout for a in spec.appliances if a.id == tgt["sourceRef"] and a.cutout), None)
                if own:                                            # the model's own hole, centred on the appliance
                    cw, cd = float(own["w"]), float(own["d"])
                    cx, cz = (llo[0] + lhi[0]) / 2, (llo[2] + lhi[2]) / 2
                    cutouts.append({"forId": tgt["id"], "type": "cooktop" if tgt["id"].startswith("APP") else "sink",
                                    "dimensions": _dims(cw, h, cd), "transform": _tf((cx - cw / 2, 0, cz - cd / 2)), "estimated": False})
                    continue
                cw, cd = lhi[0] - llo[0] - 20, lhi[2] - llo[2] - 20
                cutouts.append({"forId": tgt["id"], "type": "cooktop" if tgt["id"].startswith("APP") else "sink",
                                "dimensions": _dims(cw, h, cd), "transform": _tf((llo[0] + 10, 0, llo[2] + 10)), "estimated": True})
        accessories.append({"id": f"ACC-COUNTERTOP-{i + 1}", "type": "Countertop", "assetId": "ASSET-COUNTERTOP", "dimensions": _dims(w, h, d),
                            "transform": _tf(fr.pos, fr.rot), "materialId": mats["countertop"], "edgeProfile": "eased", "overhang": c.countertopOverhang,
                            "cutouts": cutouts, "sourceRef": f"countertop-{p.run or p.wall}",
                            "partRef": {"kind": "countertop", "wall": p.wall, **({"run": p.run} if p.run else {})}})
        height = backsplash_height(spec, require(p.wall, "countertop wall"), p.run)  # cùng một hàm với hình học 3D
        if c.material.get("wallTile") and height >= 50:  # ốp tường giữa mặt đá và tủ trên, sát tường
            accessories.append({"id": f"ACC-BACKSPLASH-{i + 1}", "type": "Backsplash_Tile", "assetId": "ASSET-PANEL",
                                "dimensions": _dims(w, height, 8), "materialId": mats["wallTile"],
                                "transform": _tf((fr.pos[0], c.countertop, fr.pos[2]), fr.rot), "sourceRef": f"wall-tile-{p.run or p.wall}"})

    for i, wedge in enumerate(m for m in scene.meshes if m.type == "countertop"):      # the wedge of worktop that closes a corner which is not square
        half = len(wedge.vertices) // 2                                                # a prism: the floor polygon first, then the same polygon at the top
        ring = wedge.vertices[:half]
        xs, zs = [v[0] for v in ring], [v[2] for v in ring]
        accessories.append({"id": f"ACC-COUNTERTOP-CORNER-{i + 1}", "type": "Countertop", "assetId": "ASSET-COUNTERTOP",
                            "dimensions": _dims(max(xs) - min(xs), c.countertop - c.baseTop, max(zs) - min(zs)),
                            "transform": _tf((0, c.baseTop, 0), 0.0), "materialId": mats["countertop"], "edgeProfile": "eased",
                            "outline": [_v(x, 0, z) for x, _, z in ring], "sourceRef": wedge.module,
                            "partRef": {"kind": "countertop", "wall": "island"}})

    # phào: mặt cắt -> assets (dùng chung), đường chạy -> decorations
    from . import moldings as _mol
    decorations: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = list(ASSETS)
    seen_prof: set[str] = set()
    for i, run in enumerate(_mol.compute_runs(spec)):
        mol, prof = run.molding, run.profile
        aid = f"ASSET-MOLDING-{prof.id}"
        us = [u for u, _ in prof.points]
        if prof.id not in seen_prof:
            seen_prof.add(prof.id)
            assets.append({"id": aid, "category": "cornice" if mol.variant == "crown" else "molding", "geometryType": "extrusion",
                           "defaultDimensions": _dims(1000, prof.height, max(us) - min(us)),
                           "parameters": {"profileId": prof.id, "name": prof.name, "profile": [[round_half_away(u, 2), round_half_away(v, 2)] for u, v in prof.points],
                                          "convention": "u: nhô ra phía phòng từ mặt trước tủ (âm = lùi vào); v: lên từ đường chạy; đa giác kín, ngược chiều kim đồng hồ"}})
        if mol.material:
            mid = f"MAT-MOLDING-{mol.id}"
            if all(m["id"] != mid for m in mats_list):
                mats_list.append({"id": mid, "name": mol.material, "threeMaterialType": "MeshStandardMaterial", "roughness": 0.5,
                                  "metalness": 0.0, **_guess(mol.material, catalog), "semanticClass": "molding"})
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
    lighting: list[dict[str, Any]] = [{"id": "LIGHT-HEMI", "type": "HemisphereLight", "color": "#ffffff", "groundColor": "#8a8170", "intensity": 1.2},
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
    cameras: list[dict[str, Any]] = []
    for key, v in views_of(spec).items():
        pos = [x * 1000 for x in v.position]
        tgt = [x * 1000 for x in v.lookAt]
        d = [b - a for a, b in zip(pos, tgt)]
        n = math.sqrt(sum(x * x for x in d)) or 1
        up = _v(0, 0, -1) if abs(d[1] / n) > 0.999 else _v(0, 1, 0)
        cameras.append({"id": f"CAM-{key}", "name": v.name or key, "position": _v(pos[0], pos[1], pos[2]), "target": _v(tgt[0], tgt[1], tgt[2]), "projection": "perspective",
                        "fov": v.verticalFov, "fovAxis": "vertical", "near": 50, "far": 50000, "up": up, "aspect": round_half_away(4 / 3, 4),
                        **({"hide": list(v.hide)} if v.hide else {})})

    def params(topic: str) -> dict[str, Any]:
        return (sel.get(topic) or {}).get("params", {})
    p_cb, p_ld, p_kt, p_hm = params("sink-cooktop"), params("walkway"), params("upper-gap"), params("hood")
    constraints: dict[str, Any] = {"allowTouching": True, "overlapTolerance": 1, "minimumSinkCooktopDistance": p_cb.get("sink_cooktop_min", 300),
                   "minimumWalkwayWidth": p_ld.get("walkway_min", p_ld.get("walkway_1person", 900)), "enforceRoomBounds": True,
                   "minimumCountertopToWallCabinet": p_kt.get("upper_gap_min", 450), "minimumHoodClearance": p_hm.get("gap_min", 650),
                   "sources": {k: sel[t]["code"] for k, t in (("minimumSinkCooktopDistance", "sink-cooktop"), ("minimumWalkwayWidth", "walkway"),
                                                              ("minimumCountertopToWallCabinet", "upper-gap"), ("minimumHoodClearance", "hood"))
                               if t in sel}}
    palette = {SEMANTIC.get(k, k): _hex(v) for k, v in SEGMENT_COLORS.items()}
    palette.update({f"module:{m.id}": _hex(_module_color(m.id)) for m in spec.module})

    doc: dict[str, Any] = {
        "schemaVersion": "1.5.0",
        "metadata": {"designId": re.sub(r"[^A-Za-z0-9_.:-]", "-", design_id) or "design", "projectName": spec.name,
                     "description": spec.source or "", "style": spec.style, "revision": max(1, rev), "author": "kitchen-design-mcp",
                     "createdAt": created_at,
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
        **({"runs": run_docs} if run_docs else {}),
        "accessories": accessories, "decorations": decorations, "cameras": cameras, "constraints": constraints,
        "renderSettings": {"backgroundColor": "#FFFFFF", "exposure": 1.0, "shadows": True, "antialias": True, "toneMapping": "ACESFilmicToneMapping",
                           "outputWidth": 1920, "outputHeight": 1080, "pixelRatio": 1, "environment": "room",
                           "controlPasses": ["lines", "depth", "normal", "seg", "seg_module", "instance", "albedo"], "segmentationPalette": palette},
    }
    if isinstance(floorplan, dict):
        doc = fpmod.finish_document(doc, floorplan, binding)
    return doc


def integrity(doc: dict[str, Any]) -> list[str]:
    """Kiểm tra tham chiếu mà JSON Schema không diễn đạt được (materialId/assetId/parentId tồn tại, id duy nhất)."""
    errs: list[str] = []
    mats = {m["id"] for m in doc["materials"]}
    assets = {a["id"] for a in doc.get("assets", [])}
    ids: list[str] = []

    def walk(o: Any, path: str) -> None:
        if (obj := as_dict(o)) is not None:
            for k, v in obj.items():
                if k in ("materialId", "carcaseMaterialId", "frontMaterialId", "defaultMaterialId") and v not in mats:
                    errs.append(f"{path}.{k}={v} không có trong materials")
                if k == "assetId" and v not in assets:
                    errs.append(f"{path}.{k}={v} không có trong assets")
                walk(v, f"{path}.{k}")
        elif (seq := as_list(o)) is not None:
            for i, v in enumerate(seq):
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
