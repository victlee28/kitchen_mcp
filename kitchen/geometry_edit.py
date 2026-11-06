"""Sửa ẢNH khi HÌNH HỌC đổi (xóa / thêm / thay vật) và bảng thao tác (operation) chọn sẵn cấu hình AI.

Nguyên tắc: Three.js / KitchenSpec là nguồn sự thật. Thao tác được áp lên thiết kế TRƯỚC, render lại các pass của thiết kế
mới với ĐÚNG camera cũ, rồi so instance/albedo/nét cũ–mới để ra mask vùng thay đổi. Model chỉ vẽ lại vùng đó, theo
nét/depth CỦA THIẾT KẾ MỚI (vật đã xóa không còn trong ảnh điều khiển nên không mọc lại). Chấp nhận ảnh = ghi rev mới.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from . import edit, geometry, handles, imaging, layers, vocab
from .spec import KitchenSpec
from .errors import InvalidInput

# ------------------------------------------------------------------ bảng thao tác
# workflow + trọng số ControlNet (ComfyUI) và kiểu chỉ dẫn (Gemini) theo loại thao tác. params người dùng truyền vẫn ghi đè.
OPERATIONS = {
    "change-material": {"name": "Đổi vật liệu / màu", "kind": "edit", "workflow": "inpaint-lineart",
                     "params": {"cn_strength": 0.45}, "description": "Giữ biên, cho đổi màu và chất liệu"},
    "replace-item": {"name": "Thay kiểu vật (giữ chỗ)", "kind": "geometry_edit", "workflow": "inpaint-lineart",
                 "params": {"cn_strength": 0.7}, "description": "Nét mới bám chặt để ra đúng hình mới"},
    "remove-item": {"name": "Xóa vật", "kind": "geometry_edit", "workflow": "inpaint-lineart",
                "params": {"cn_strength": 0.55}, "description": "Vẽ phần nền sau vật (tường, sàn, hông tủ bên cạnh)"},
    "add-item": {"name": "Thêm vật", "kind": "geometry_edit", "workflow": "inpaint-lineart",
                 "params": {"cn_strength": 0.7}, "description": "Vẽ vật mới theo nét của thiết kế mới"},
    "change-style": {"name": "Đổi phong cách toàn ảnh", "kind": "gen0", "workflow": "gen0-lineart-depth",
                       "params": {"cn_strength": 0.4, "depth_strength": 0.55}, "description": "Giữ bố cục, cho đổi vật liệu/trang trí nhiều"},
}

_TYPE_EN = {"base": "base cabinet", "base-sink": "sink base cabinet", "base-corner-sink": "corner sink base cabinet",
            "base-cooktop": "cooktop base cabinet", "base-oven": "oven base cabinet", "base-end": "end base cabinet",
            "base-drawers": "drawer base cabinet", "upper": "wall cabinet", "upper-glass": "glass wall cabinet", "upper-open": "open shelving unit",
            "upper-hood": "range hood wall cabinet", "upper-loft": "top-row wall cabinet", "tall-fridge": "tall fridge cabinet",
            "tall": "tall cabinet", "corner-shelf": "corner open shelf"}
_HANDLE_EN = {"bar": "slim bar pull handles", "knob": "round knob handles", "concealed": "recessed finger-pull handles",
           "none": "handleless push-to-open fronts (no handles)"}
_DOOR_EN = {"flat": "flat slab doors", "frame": "shaker-style framed doors (recessed center panel)", "glass": "glass-front doors"}
_DOOR_VI = {"flat": "cánh phẳng", "frame": "cánh khung (shaker)", "glass": "cánh kính"}


def module_en(m) -> str:
    return _TYPE_EN.get(m.type, "cabinet module")


def build_ops(spec: KitchenSpec, items: list[dict]) -> tuple[list[dict], list[dict], str]:
    """items -> (ops thiết kế, mô tả từng việc, thao tác suy ra).

    Mỗi item một trong:
      {"type": "remove-module", "id": "TD3", "closeGap": false}
      {"type": "add-module", "module": {...}, "afterModule": "TD3", "closeGap": true}
      {"type": "door-style", "id": "TD1" | "*", "variant": "phang|khung|kinh"}
      {"type": "handle", "variant": "thanh|num|am|khong", "length"?: 160}
      {"type": "op", "op": {...}}      # thao tác thiết kế bất kỳ (xem edit.apply_op)
    Mô tả: {"vi", "en", "operation", "required": [mã module có vùng bắt buộc vẽ lại dù hình học không đổi]}."""
    if not items:
        raise InvalidInput("Cần ít nhất một thao tác hình học")
    ops, desc = [], []
    cur = spec
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            raise InvalidInput(f"Thao tác {i} không hợp lệ")
        k = it.get("type")
        extra_ops: list[dict] = []
        if k == "remove-module":
            m = cur.find(str(it.get("id")))
            op = {"op": "remove", "id": m.id, "closeGap": bool(it.get("closeGap", False))}
            d = {"vi": f"xóa {m.id} ({m.name or m.type})", "en": f"remove the {module_en(m)}", "operation": "remove-item"}
        elif k == "add-module":
            mod = it.get("module") or {}
            op = {"op": "add", "module": mod, "afterModule": it.get("afterModule"), "closeGap": bool(it.get("closeGap", True))}
            nxt = edit.apply_op(cur, op)
            m = nxt.find(mod.get("id"))
            material_text = layers.material_slot(nxt, m.id, "door")[1]
            face_en = vocab.to_english(material_text or "")
            d = {"vi": f"thêm {m.id} ({m.type})", "en": f"add a new {module_en(m)}" + (f" with {face_en} fronts" if face_en else ""),
                 "operation": "add-item"}
        elif k == "door-style":
            variant = it.get("variant")
            if variant not in _DOOR_EN:
                raise InvalidInput(f"Thao tác {i}: kieu phải là {', '.join(_DOOR_EN)}")
            mas = [m.id for m in cur.module if m.doors or m.frontSections] if it.get("id") in (None, "", "*") else [cur.find(it["id"]).id]
            sub = [{"op": "update", "id": id, "changes": {"doorStyle": variant}} for id in mas]
            op = sub[0] if len(sub) == 1 else {"op": "multi", "ops": sub}
            place = "mọi module" if len(mas) > 1 else mas[0]
            d = {"vi": f"đổi {place} sang {_DOOR_VI[variant]}", "en": f"change the cabinet doors to {_DOOR_EN[variant]}",
                 "operation": "replace-item", "required": mas, "doorStyle": variant}
        elif k == "handle":
            variant = it.get("variant")
            if variant not in _HANDLE_EN:
                raise InvalidInput(f"Thao tác {i}: kieu tay nắm phải là {', '.join(_HANDLE_EN)}")
            tn = {**cur.common.handle.model_dump(mode="json"), "variant": variant, **({"length": float(it["length"])} if it.get("length") else {})}
            common_changes, extra_ops = handles.clear_overrides(cur, ("variant", "length"))  # "all cabinets" must also reset overrides
            op = {"op": "common", "changes": {"handle": tn, **common_changes}}
            d = {"vi": f"đổi tay nắm sang kiểu {variant}", "en": f"replace the handles with {_HANDLE_EN[variant]}"
                 + (f" in {vocab.to_english(tn['material'])}" if vocab.to_english(tn.get("material") or "") and variant != "none" else ""),
                 "operation": "replace-item"}
        elif k == "op":
            op = it.get("op")
            if not isinstance(op, dict) or op.get("op") in (None, "replace"):
                raise InvalidInput(f"Thao tác {i}: cần 'op' hợp lệ (không nhận replace)")
            d = {"vi": str(it.get("description") or op.get("op")), "en": str(it.get("descriptionEn") or "apply the design change shown in image 3"),
                 "operation": it.get("operation") or "replace-item"}
        else:
            raise InvalidInput(f"Thao tác {i}: type phải là remove-module | add-module | door-style | handle | op")
        cur = edit.apply_op(cur, op)
        ops.append(op)
        for extra in extra_ops:
            cur = edit.apply_op(cur, extra)
            ops.append(extra)
        desc.append(d)
    kinds = {d["operation"] for d in desc}
    tt = kinds.pop() if len(kinds) == 1 else "replace-item"
    return ops, desc, tt


def pin_cameras(spec: KitchenSpec, nxt: KitchenSpec) -> dict | None:
    """Góc nhìn mặc định tính theo khung bao thiết kế: xóa/thêm tủ làm camera dịch. Ghim camera cũ vào thiết kế mới
    để ảnh trước/sau cùng khung hình (op trả về được ghi cùng rev khi chấp nhận)."""
    old, new = geometry.views_of(spec), geometry.views_of(nxt)
    if {k: v.model_dump(mode="json") for k, v in old.items()} == {k: v.model_dump(mode="json") for k, v in new.items()}:
        return None
    return {"op": "set-views", "cameraViews": {k: v.model_dump(mode="json") for k, v in old.items()}}


# ------------------------------------------------------------------ so sánh render cũ / mới
def _ids(d: Path) -> tuple[np.ndarray, list[str]]:
    inst, meta = imaging.load_instances(d)
    names = {x["value"]: x["id"] for x in meta["instances"]}
    return inst, names


def diff_mask(old_dir: Path, new_dir: Path) -> tuple[np.ndarray, dict]:
    """Vùng ảnh khác nhau giữa hai render cùng camera: khác chi tiết (instance), khác màu phẳng (albedo) hoặc khác nét."""
    a, na = _ids(old_dir)
    b, nb = _ids(new_dir)
    allid = sorted(set(na.values()) | set(nb.values()))
    idx = {s: k + 1 for k, s in enumerate(allid)}
    lut_a = np.zeros(int(a.max()) + 1, np.int32)
    for v, s in na.items():
        if v <= a.max():
            lut_a[v] = idx[s]
    lut_b = np.zeros(int(b.max()) + 1, np.int32)
    for v, s in nb.items():
        if v <= b.max():
            lut_b[v] = idx[s]
    ga, gb = lut_a[a], lut_b[b]
    by_id = ga != gb
    alb = np.abs(imaging.read(old_dir / "albedo.png").astype(np.int16) - imaging.read(new_dir / "albedo.png").astype(np.int16)).max(-1) > 10
    la, lb = imaging.read(old_dir / "lines.png", "L") < 128, imaging.read(new_dir / "lines.png", "L") < 128
    by_line = la ^ lb
    m = by_id | alb | by_line
    # bỏ chấm nhiễu lẻ, rồi nở 2 px phủ mép khử răng cưa
    m = imaging.grow(imaging.shrink(imaging.grow(m, 1), 1), 2)
    removed = sorted({na[v] for v in np.unique(a[by_id]) if v in na} - set(nb.values()))
    added = sorted({nb[v] for v in np.unique(b[by_id]) if v in nb} - set(na.values()))
    changed = sorted({nb[v] for v in np.unique(b[m]) if v in nb} | {na[v] for v in np.unique(a[m]) if v in na})
    return m, {"pixels": int(m.sum()), "xoa": removed, "them": added, "part": changed,
               "partDifferences": int(by_id.sum()), "colorDifferences": int(alb.sum()), "lineDifferences": int(by_line.sum())}


def front_mask(d: Path, spec: KitchenSpec, scene, mas: list[str]) -> tuple[np.ndarray, list[np.ndarray]]:
    """Mask mặt trước (cánh, ngăn kéo) của các module — dùng khi thao tác không đổi hình trong render nhanh (kiểu cánh)."""
    inst, meta = imaging.load_instances(d)
    val = {x["id"]: x["value"] for x in meta["instances"]}
    fronts = [p for p in scene.parts if p.module in set(mas) and p.type in layers.FRONT_SECTIONS]
    each = [inst == val[p.id] for p in fronts if p.id in val]
    each = [x for x in each if x.sum() > 30]
    out = np.zeros(inst.shape, bool)
    for x in each:
        out |= x
    return out, each


def shaker_lines(lines: np.ndarray, doors: list[np.ndarray]) -> np.ndarray:
    """Vẽ khung cánh shaker lên ảnh nét (render nhanh chưa dựng khung): đường viền trong cách mép ~9% cạnh ngắn của cánh."""
    out = lines.copy()
    for m in doors:
        b = imaging.bbox(m)
        if b is None:
            continue
        k = max(2, int(min(b[2] - b[0], b[3] - b[1]) * 0.09))
        inner = imaging.shrink(m, k)
        if inner.sum() < 20:
            continue
        edge = inner & ~imaging.shrink(inner, 1)
        out[edge] = 0
    return out


def preview(new_dir: Path, lines: np.ndarray | None = None) -> np.ndarray:
    """Ảnh 'hình mẫu' của thiết kế mới: màu phẳng (albedo) + nét đen — model nhìn để biết vùng phải thành hình gì."""
    img = imaging.read(new_dir / "albedo.png").copy()
    ln = imaging.read(new_dir / "lines.png", "L") if lines is None else lines
    img[ln < 128] = (25, 25, 25)
    return img


def save_json(p: Path, data) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def to_image(a: np.ndarray, p: Path) -> None:
    Image.fromarray(a).save(p)
