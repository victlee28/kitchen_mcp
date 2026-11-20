"""Danh mục layer cho sửa ảnh theo lớp.

Quy ước: layer ID = ID chi tiết do bộ biên dịch hình học sinh ra (vd `TD1-door-1`, `crown-molding-2`).
Layer nhóm: `matTruoc:<module>` (cánh + ngăn kéo + cánh kính), `module:<ma>` (mọi chi tiết của module hoặc phào),
`type:<type>` (mọi chi tiết cùng loại), `tier:<tầng>:<vai trò>` (vai trò: handle, door, drawer, front, all; tầng vật liệu: base, upper gồm cả
nóc, tall, corner) và `parts:<id>,<id>,…` (tập chi tiết cùng loại do người dùng chọn, dựng khi resolve). Không có hệ ID riêng cho layer.

Mỗi layer biết: vật liệu hiện tại (lấy từ spec), vai trò để dựng prompt, quyền sửa,
và (nếu có) thao tác sửa thiết kế tương ứng khi người dùng chọn "Áp vào thiết kế".
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .geometry import Scene
from .spec import TIER_OF_STOREY, KitchenSpec
from . import builtin, defaults, handles
from .errors import InvalidInput, NotFound, require
from .wall_surfaces import FaceRef, face_owner, face_part_id
from .words import say

FRONT_SECTIONS = ("door", "glass-door", "drawer")

SEMANTIC = {"carcass": "cabinet_body", "side-panel": "cabinet_body", "shelf": "cabinet_body", "plinth": "plinth",
            "door": "cabinet_front", "glass-door": "cabinet_front", "drawer": "cabinet_front",
            "countertop": "countertop", "molding": "decorations", "handle": "hardware", "wall": "room", "floor": "room",
            "fridge": "appliances", "sink": "appliances", "faucet": "appliances", "cooktop": "appliances", "hood": "appliances", "oven": "appliances",
            "opening-frame": "room_opening", "opening-leaf": "room_opening", "opening-leaf-frame": "room_opening", "opening-glass": "room_opening", "opening-sweep": "room_opening",
            "opening-handle": "room_opening"}

def _roles() -> dict[str, tuple[str, str]]:
    """Part kind -> (name shown to people: the ``part.<kind>`` key of data/i18n, prompt words: the builtin ``prompt-text`` table
    ``part-roles``). The image-edit prompts read the words of the merged catalog (``prompts.table("part-roles", catalog)``)."""
    from .prompts.photo import table
    return {k: (say(f"part.{k}"), en) for k, en in table("part-roles").items()}


ROLES = _roles()   # part kind -> (name shown to people, builtin prompt words); the kinds the layers name

_MATERIALS = defaults.BUILTIN.materials   # finish names drawn where the design names none (data: the ``defaults`` item)
_DEFAULTS = {k: _MATERIALS[k] for k in ("base", "upper", "carcass", "countertop", "wall", "floor", "plinth", "openingFrame", "openingLeaf",
                                        "openingGlass", "openingHandle") if k in _MATERIALS}
OPENING_KEYS = {"opening-frame": "openingFrame", "opening-leaf": "openingLeaf", "opening-leaf-frame": "openingFrame", "opening-glass": "openingGlass", "opening-sweep": "floor",
                "opening-handle": "openingHandle"}
OPENING_GROUPS = (("leaves", ("opening-leaf", "opening-leaf-frame", "opening-glass"), "name.layer.opening-leaves"),     # (layer id prefix, part types, name key)
                  ("frame", ("opening-frame",), "name.layer.opening-frame"),
                  ("handle", ("opening-handle",), "name.layer.opening-handles"))
_APPLIANCES = {"fridge": _MATERIALS["steel"], "sink": _MATERIALS["sink"], "faucet": _MATERIALS["steel"], "cooktop": _MATERIALS["cooktop"],
               "hood": _MATERIALS["steel"], "openings": _MATERIALS["openings"]}


def _vl(spec: KitchenSpec, key: str) -> str:
    v = spec.common.material
    if key == "tall":
        return v.get("tall") or v.get("base") or _DEFAULTS["base"]
    if key == "cornerShelf":
        return v.get("cornerShelf") or v.get("base") or _MATERIALS["cornerShelf"]
    return v.get(key) or _DEFAULTS.get(key, "")


def material_slot(spec: KitchenSpec, module: str | None, type: str) -> tuple[str, str]:
    """(khóa vật liệu, tên vật liệu) của một chi tiết. Khóa dùng để biết sửa thiết kế ở đâu."""
    mods = {m.id: m for m in spec.module}
    mols = {m.id: m for m in spec.moldings}
    if type == "molding" and module in mols:
        return f"molding:{module}", mols[module].material or _MATERIALS["molding"]
    if type == "handle":
        return handles.material_slot(spec, module)
    if type.startswith("structure-"):  # drawn from the imported floorplan: not a material of the kitchen
        return f"structure:{type[len('structure-'):]}", ""
    if type in OPENING_KEYS:            # room doors and windows the design places: one finish each for frames, leaves, glass
        key = OPENING_KEYS[type]
        return f"common:{key}", _vl(spec, key)
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
        return "appliances:glass", _MATERIALS["glass"]
    if type in FRONT_SECTIONS or (type == "side-panel" and (m.endPanel or m.storey in ("tall", "corner"))):
        return (f"module:{m.id}", m.material) if m.material else (f"common:{storey_key}", _vl(spec, storey_key))
    if m.storey == "corner":
        return f"common:{storey_key}", _vl(spec, storey_key)
    return "common:carcass", _vl(spec, "carcass")


def design_op(spec: KitchenSpec, layer: dict[str, Any], material: str, scene: Scene | None = None) -> tuple[dict[str, Any], str] | None:
    """Thao tác sửa thiết kế để layer mang vật liệu mới. Trả (op, ghi chú phạm vi) hoặc None nếu không hỗ trợ.

    Tay nắm cần `scene` để biết tay nào thuộc module nào; ValueError nếu vùng chọn không biểu diễn đúng được trong spec."""
    if layer.get("type") == "handle":
        if scene is None:
            return None
        return handles.material_ops(spec, scene, layer.get("component") or [layer["id"]], material)
    if layer.get("type") == "wall-face":          # one wall face or several: their own finish (spec.surfaceMaterials)
        faces = list(dict.fromkeys(layer.get("surfaces") or ([layer["surface"]] if layer.get("surface") else [])))
        if not faces:
            return None
        return {"op": "surface-material", "surfaces": faces, "material": material}, say("scope.surfaces", surfaces=", ".join(faces))
    key = layer["materialLocked"]
    module, type = layer.get("module"), layer.get("type")
    if type in FRONT_SECTIONS and type != "glass-door" and module and module in {m.id for m in spec.module}:
        return {"op": "update", "id": module, "changes": {"material": material}}, say("scope.module-front", module=module)
    kind, _, ref = key.partition(":")
    if kind == "common" and type in FRONT_SECTIONS and scene is not None:
        partial = _front_updates(spec, scene, layer, ref, material)
        if partial is not None:
            return partial
    if kind == "module":
        return {"op": "update", "id": ref, "changes": {"material": material}}, say("scope.module-front", module=ref)
    if kind == "molding":
        return {"op": "molding", "id": ref, "changes": {"material": material}}, say("scope.molding", id=ref)
    if kind == "common":
        k: str = require(ref, "common layer")
        if k == "plinth":
            return None
        what: str = say(f"scope.common.{k}") if builtin.MESSAGES.has(f"scope.common.{k}") else k
        return {"op": "common", "changes": {"material": {**spec.common.material, k: material}}}, what
    return None


def catalogue(spec: KitchenSpec, scene: Scene, faces: Sequence[FaceRef] = ()) -> list[dict[str, Any]]:
    """Mọi chi tiết đơn + layer nhóm. Không gồm số pixel (phụ thuộc góc nhìn). ``faces``: the wall faces the render splits out
    (``render.wall_faces``): each gets a part per wall part it lies on and a layer ``surface:<id>``."""
    out: list[dict[str, Any]] = []
    storey_of = {m.id: m.storey for m in spec.module}
    appliance_ids = {a.id for a in spec.appliances}
    from . import runs
    system_of: dict[str, str] = runs.systems(spec)
    run_system = runs.run_systems(spec)
    for p in list(scene.parts) + list(scene.meshes):
        key, name = material_slot(spec, p.module, p.type)
        vt = ROLES.get(p.type, (p.type, p.type))
        out.append({"id": p.id, "variant": "part", "module": p.module, "type": p.type, "semanticClass": SEMANTIC.get(p.type, "structure" if p.type.startswith("structure-") else "custom"),
                    "name": say("name.layer.part", part=vt[0], module=p.module) if p.module else say("name.layer.part-alone", part=vt[0]), "material": name, "materialLocked": key,
                    "storey": storey_of.get(p.module or ""), "tier": TIER_OF_STOREY.get(storey_of.get(p.module or "") or ""),
                    "appliance": (p.module or "") in appliance_ids, "parent": getattr(p, "parent", None),
                    "cabinetSystemId": system_of.get(p.module or "") or run_system.get(getattr(p, "run", None) or ""),
                    "selectable": True, "allowAppearanceChange": not p.type.startswith("structure-"),
                    "allowGeometryChange": False, "allowPositionChange": False})
    out += _face_parts(spec, scene, faces)
    by_id: dict[str, dict[str, Any]] = {x["id"]: x for x in out}
    groups: list[dict[str, Any]] = []
    for m in spec.module:
        fronts: list[str] = [x["id"] for x in out if x["module"] == m.id and x["type"] in FRONT_SECTIONS]
        if fronts:
            first = by_id[fronts[0]]
            groups.append({"id": f"frontSections:{m.id}", "variant": "group", "module": m.id, "type": "door", "semanticClass": "cabinet_front",
                           "name": say("name.layer.fronts", module=m.id), "material": first["material"], "materialLocked": first["materialLocked"], "component": fronts})
        hs: list[str] = [x["id"] for x in out if x["module"] == m.id and x["type"] == "handle"]
        if hs:
            groups.append({"id": f"handle:{m.id}", "variant": "group", "module": m.id, "type": "handle", "semanticClass": "hardware",
                           "name": say("name.layer.handles", module=m.id), "material": by_id[hs[0]]["material"], "materialLocked": "common:handle",
                           "component": hs})
        allp: list[str] = [x["id"] for x in out if x["module"] == m.id]
        if allp:
            groups.append({"id": f"module:{m.id}", "variant": "group", "module": m.id, "type": "module", "semanticClass": "cabinet",
                           "name": say("name.layer.cabinet", module=m.id), "material": None, "materialLocked": "", "component": allp})
    for oid in dict.fromkeys(str(x["module"]) for x in out if str(x["type"]).startswith("opening-") and x["module"]):
        mine = [x for x in out if x["module"] == oid and str(x["type"]).startswith("opening-")]
        for prefix, types, name in OPENING_GROUPS:        # a door / window: its leaves, its frame, its handles, then the whole of it
            ids = [str(x["id"]) for x in mine if x["type"] in types]
            if ids:
                first = by_id[ids[0]]
                same = len({by_id[i]["materialLocked"] for i in ids}) == 1
                groups.append({"id": f"{prefix}:{oid}", "variant": "group", "module": oid, "type": first["type"], "semanticClass": "room_opening",
                               "name": say(name, module=oid), "material": first["material"] if same else None,
                               "materialLocked": first["materialLocked"] if same else "", "component": ids})
        groups.append({"id": f"module:{oid}", "variant": "group", "module": oid, "type": "opening", "semanticClass": "room_opening",
                       "name": say("name.layer.opening", module=oid), "material": None, "materialLocked": "",
                       "component": [str(x["id"]) for x in mine]})
    for mol in spec.moldings:
        ids: list[str] = [x["id"] for x in out if x["module"] == mol.id and x["type"] == "molding"]
        if ids:
            first = by_id[ids[0]]
            groups.append({"id": f"module:{mol.id}", "variant": "group", "module": mol.id, "type": "molding", "semanticClass": "decorations",
                           "name": say("name.layer.molding", module=mol.id), "material": first["material"], "materialLocked": first["materialLocked"], "component": ids})
    for type in dict.fromkeys(str(x["type"]) for x in out):
        ids = [str(x["id"]) for x in out if x["type"] == type]
        if len(ids) > 1:
            first = by_id[ids[0]]
            same = len({by_id[i]["materialLocked"] for i in ids}) == 1
            groups.append({"id": f"type:{type}", "variant": "group", "module": None, "type": type, "semanticClass": SEMANTIC.get(type, "custom"),
                           "name": say("name.layer.every", part=ROLES.get(type, (type,))[0]), "material": first["material"] if same else None,
                           "materialLocked": "common:handle" if type == "handle" else (first["materialLocked"] if same else ""), "component": ids})
    groups.extend(_tier_groups(out))
    groups.extend(_face_groups(out))
    for g in groups:
        g.update(selectable=True, allowAppearanceChange=not str(g.get("type", "")).startswith("structure-"),
                 allowGeometryChange=False, allowPositionChange=False)
    return out + groups


TIER_NAME = {t: say(f"tier.{t}") for t in ("base", "upper", "tall", "corner")}
TIER_OF = TIER_OF_STOREY  # storey -> material tier (loft shares upper): one table, kitchen/spec.py


def _tier_groups(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Groups of one role within one tier: handle, door (door + glass door), drawer, front (all fronts), all (fronts + handles).

    ``tier:<tier>:<role>`` covers the whole design (saved image jobs refer to these ids). When the design has more than one cabinet system
    (``runs.systems``), the same groups are made once more per system: ``sys:<system>:tier:<tier>:<role>``, what Shift-click selects."""
    out = _role_groups(parts, "tier", "")
    systems = sorted({x["cabinetSystemId"] for x in parts if x.get("storey") and x.get("cabinetSystemId")})
    if len(systems) > 1:
        for system in systems:
            out += _role_groups([x for x in parts if x.get("cabinetSystemId") == system], f"sys:{system}:tier", system, system)
    return out


def _role_groups(parts: list[dict[str, Any]], prefix: str, in_system: str, system: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tier, tname in TIER_NAME.items():
        members = [x for x in parts if x.get("storey") and TIER_OF[x["storey"]] == tier]
        doors = [x for x in members if x["type"] in ("door", "glass-door")]
        drawers = [x for x in members if x["type"] == "drawer"]
        hs = [x for x in members if x["type"] == "handle"]
        roles = [("handle", "handle", say("name.layer.tier-handles", tier=tname), hs), ("door", "door", say("name.layer.tier-doors", tier=tname), doors),
                 ("drawer", "drawer", say("name.layer.tier-drawers", tier=tname), drawers),
                 ("front", "door", say("name.layer.tier-fronts", tier=tname), doors + drawers),
                 ("all", "module", say("name.layer.tier-all", tier=tname), doors + drawers + hs)]
        seen: list[frozenset[str]] = []
        for role, type, name, xs in roles:
            ids: list[str] = [x["id"] for x in xs]
            if not ids or frozenset(ids) in seen:
                continue
            seen.append(frozenset(ids))
            keys, mats = {x["materialLocked"] for x in xs}, {x["material"] for x in xs}
            out.append({"id": f"{prefix}:{tier}:{role}", "variant": "group", "module": None, "type": type, "semanticClass": SEMANTIC.get(type, "cabinet"),
                        "name": say("name.layer.in-system", name=name, system=in_system) if in_system else name, "material": mats.pop() if len(mats) == 1 else None, **({"cabinetSystemId": system} if system else {}),
                        "materialLocked": "common:handle" if type == "handle" else (keys.pop() if len(keys) == 1 and type != "module" else ""),
                        "component": ids})
    return out


def _front_updates(spec: KitchenSpec, scene: Scene, layer: dict[str, Any], slot: str, material: str) -> tuple[dict[str, Any], str] | None:
    """The fronts of a group that covers the fronts of only SOME of the modules using a common material slot (one cabinet system of
    several, a hand-picked selection): a material of their own on each of those modules, so the other modules keep theirs. The spec keeps
    a front material per module, so a module with doors and drawers gets it on both. None when the group reaches every module of the slot:
    changing ``common`` then changes exactly those modules, as before."""
    chosen = set(layer.get("component") or [layer["id"]])
    touched: set[str] = set()
    users: set[str] = set()
    for p in list(scene.parts):
        if not (p.module and p.type in FRONT_SECTIONS and p.type != "glass-door"):
            continue
        if material_slot(spec, p.module, p.type)[0] == f"common:{slot}":
            users.add(p.module)
            if p.id in chosen:
                touched.add(p.module)
    if not touched or users <= touched:
        return None
    mods = sorted(touched)
    ops = [{"op": "update", "id": m, "changes": {"material": material}, "closeGap": False} for m in mods]
    return (ops[0] if len(ops) == 1 else {"op": "multi", "ops": ops}), say("scope.fronts-own", n=len(mods), modules=", ".join(mods))


def changed_parts(old: KitchenSpec, new: KitchenSpec, scene: Scene) -> list[str]:
    """Chi tiết đổi vật liệu giữa hai spec cùng hình học (để mask đúng phạm vi thao tác sửa thiết kế)."""
    return [p.id for p in list(scene.parts) + list(scene.meshes)
            if material_slot(old, p.module, p.type)[1] != material_slot(new, p.module, p.type)[1]]


def _adhoc(cat: list[dict[str, Any]], layer_id: str) -> tuple[dict[str, Any], list[str]]:
    """`parts:<id>,<id>,…` -> a layer built from parts of one type chosen by the user (a task keeps one role for its prompt)."""
    ids = list(dict.fromkeys(i for i in layer_id[len("parts:"):].split(",") if i))
    by_id = {x["id"]: x for x in cat if x["variant"] == "part"}
    missing = [i for i in ids if i not in by_id]
    if not ids or missing:
        raise NotFound(f"No part: {', '.join(missing[:3]) or '(empty list)'}", code="part-not-found", params={"ids": ', '.join(missing[:3]) or '-'})
    types = sorted({by_id[i]["type"] for i in ids})
    if len(types) > 1:
        raise InvalidInput("One task holds parts of one kind only; selected: " + ", ".join(sorted(types)) + ". Split it into several tasks.",
                           code="mixed-part-kinds", params={"kinds": ", ".join(ROLES.get(t, (t,))[0] for t in types)})
    first = by_id[ids[0]]
    keys, mats = {by_id[i]["materialLocked"] for i in ids}, {by_id[i]["material"] for i in ids}
    layer = {"id": layer_id, "variant": "group", "module": None, "type": first["type"], "semanticClass": first["semanticClass"],
             "name": say("name.layer.count", n=len(ids), part=ROLES.get(first['type'], (first['type'],))[0]), "material": mats.pop() if len(mats) == 1 else None,
             "materialLocked": "common:handle" if first["type"] == "handle" else (keys.pop() if len(keys) == 1 else ""),
             "component": ids, "selectable": True, "allowAppearanceChange": True, "allowGeometryChange": False, "allowPositionChange": False}
    if first["type"] == "wall-face":
        layer["surfaces"] = list(dict.fromkeys(str(by_id[i]["surface"]) for i in ids))
    return layer, ids


def _face_parts(spec: KitchenSpec, scene: Scene, faces: Sequence[FaceRef]) -> list[dict[str, Any]]:
    """Each wall part's share of each wall face (the render's ``<part>#<face>`` instances), so faces are picked, grouped and recoloured
    like any part: ``surface`` = the face's id (``spec.surfaceMaterials`` key)."""
    out: list[dict[str, Any]] = []
    parts = list(scene.parts) + list(scene.meshes)
    finishes = spec.surfaceMaterials or {}
    for fc in faces:
        for p in parts:
            if face_owner(p, fc):
                out.append({"id": face_part_id(p.id, fc.face), "variant": "part", "module": p.module, "type": "wall-face",
                            "semanticClass": "wall", "surface": fc.id, "room": fc.room, "name": say("layer.surface", surface=fc.id),
                            "material": finishes.get(fc.id), "materialLocked": f"surface:{fc.id}", "storey": None, "parent": p.id,
                            "cabinetSystemId": None, "selectable": True, "allowAppearanceChange": True,
                            "allowGeometryChange": False, "allowPositionChange": False})
    return out


def _face_groups(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One layer per wall face: its shares on every part of the wall."""
    out: dict[str, dict[str, Any]] = {}
    for x in parts:
        if x["type"] != "wall-face":
            continue
        g = out.setdefault(x["surface"], {**x, "id": f"surface:{x['surface']}", "variant": "group", "component": [], "parent": None,
                                          "surfaces": [x["surface"]]})
        g["component"].append(x["id"])
    return list(out.values())


def resolve(cat: list[dict[str, Any]], layer_id: str) -> tuple[dict[str, Any], list[str]]:
    """Layer -> (mô tả, danh sách ID chi tiết)."""
    if layer_id.startswith("parts:"):
        return _adhoc(cat, layer_id)
    for x in cat:
        if x["id"] == layer_id:
            return x, x.get("component") or [x["id"]]
    raise NotFound(f"No layer: {layer_id}", code="layer-not-found", params={"id": layer_id})
