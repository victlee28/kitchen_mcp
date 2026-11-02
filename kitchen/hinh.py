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

from . import edit, geometry, imaging, layers, vocab
from .spec import KitchenSpec

# ------------------------------------------------------------------ bảng thao tác
# workflow + trọng số ControlNet (ComfyUI) và kiểu chỉ dẫn (Gemini) theo loại thao tác. params người dùng truyền vẫn ghi đè.
THAO_TAC = {
    "doi-vat-lieu": {"ten": "Đổi vật liệu / màu", "kind": "edit", "workflow": "inpaint-lineart",
                     "params": {"cn_strength": 0.45}, "moTa": "Giữ biên, cho đổi màu và chất liệu"},
    "thay-vat": {"ten": "Thay kiểu vật (giữ chỗ)", "kind": "hinh", "workflow": "inpaint-lineart",
                 "params": {"cn_strength": 0.7}, "moTa": "Nét mới bám chặt để ra đúng hình mới"},
    "xoa-vat": {"ten": "Xóa vật", "kind": "hinh", "workflow": "inpaint-lineart",
                "params": {"cn_strength": 0.55}, "moTa": "Vẽ phần nền sau vật (tường, sàn, hông tủ bên cạnh)"},
    "them-vat": {"ten": "Thêm vật", "kind": "hinh", "workflow": "inpaint-lineart",
                 "params": {"cn_strength": 0.7}, "moTa": "Vẽ vật mới theo nét của thiết kế mới"},
    "doi-phong-cach": {"ten": "Đổi phong cách toàn ảnh", "kind": "gen0", "workflow": "gen0-lineart-depth",
                       "params": {"cn_strength": 0.4, "depth_strength": 0.55}, "moTa": "Giữ bố cục, cho đổi vật liệu/trang trí nhiều"},
}

_LOAI_EN = {"duoi": "base cabinet", "duoi-chau": "sink base cabinet", "duoi-chau-goc": "corner sink base cabinet",
            "duoi-bep": "cooktop base cabinet", "duoi-lo": "oven base cabinet", "duoi-cuoi": "end base cabinet",
            "duoi-ngan-keo": "drawer base cabinet", "tren": "wall cabinet", "tren-kinh": "glass wall cabinet",
            "tren-hut-mui": "range hood wall cabinet", "tren-noc": "top-row wall cabinet", "cao-tu-lanh": "tall fridge cabinet",
            "cao": "tall cabinet", "ke-goc": "corner open shelf"}
_TAY_EN = {"thanh": "slim bar pull handles", "num": "round knob handles", "am": "recessed finger-pull handles",
           "khong": "handleless push-to-open fronts (no handles)"}
_CANH_EN = {"phang": "flat slab doors", "khung": "shaker-style framed doors (recessed center panel)", "kinh": "glass-front doors"}
_CANH_VI = {"phang": "cánh phẳng", "khung": "cánh khung (shaker)", "kinh": "cánh kính"}


def module_en(m) -> str:
    return _LOAI_EN.get(m.loai, "cabinet module")


def build_ops(spec: KitchenSpec, items: list[dict]) -> tuple[list[dict], list[dict], str]:
    """items -> (ops thiết kế, mô tả từng việc, thao tác suy ra).

    Mỗi item một trong:
      {"loai": "xoa-module", "ma": "TD3", "donDay": false}
      {"loai": "them-module", "module": {...}, "sauModule": "TD3", "donDay": true}
      {"loai": "kieu-canh", "ma": "TD1" | "*", "kieu": "phang|khung|kinh"}
      {"loai": "tay-nam", "kieu": "thanh|num|am|khong", "dai"?: 160}
      {"loai": "op", "op": {...}}      # thao tác thiết kế bất kỳ (xem edit.apply_op)
    Mô tả: {"vi", "en", "thaoTac", "batBuoc": [mã module có vùng bắt buộc vẽ lại dù hình học không đổi]}."""
    if not items:
        raise ValueError("Cần ít nhất một thao tác hình học")
    ops, desc = [], []
    cur = spec
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            raise ValueError(f"Thao tác {i} không hợp lệ")
        k = it.get("loai")
        if k == "xoa-module":
            m = cur.tim(str(it.get("ma")))
            op = {"op": "remove", "ma": m.ma, "donDay": bool(it.get("donDay", False))}
            d = {"vi": f"xóa {m.ma} ({m.ten or m.loai})", "en": f"remove the {module_en(m)}", "thaoTac": "xoa-vat"}
        elif k == "them-module":
            mod = it.get("module") or {}
            op = {"op": "add", "module": mod, "sauModule": it.get("sauModule"), "donDay": bool(it.get("donDay", True))}
            nxt = edit.apply_op(cur, op)
            m = nxt.tim(mod.get("ma"))
            mat = layers.material_slot(nxt, m.ma, "canh")[1]
            mat_en = vocab.tieng_anh(mat or "")
            d = {"vi": f"thêm {m.ma} ({m.loai})", "en": f"add a new {module_en(m)}" + (f" with {mat_en} fronts" if mat_en else ""),
                 "thaoTac": "them-vat"}
        elif k == "kieu-canh":
            kieu = it.get("kieu")
            if kieu not in _CANH_EN:
                raise ValueError(f"Thao tác {i}: kieu phải là {', '.join(_CANH_EN)}")
            mas = [m.ma for m in cur.module if m.canh or m.matTruoc] if it.get("ma") in (None, "", "*") else [cur.tim(it["ma"]).ma]
            sub = [{"op": "update", "ma": ma, "thayDoi": {"kieuCanh": kieu}} for ma in mas]
            op = sub[0] if len(sub) == 1 else {"op": "nhieu", "ops": sub}
            noi = "mọi module" if len(mas) > 1 else mas[0]
            d = {"vi": f"đổi {noi} sang {_CANH_VI[kieu]}", "en": f"change the cabinet doors to {_CANH_EN[kieu]}",
                 "thaoTac": "thay-vat", "batBuoc": mas, "kieuCanh": kieu}
        elif k == "tay-nam":
            kieu = it.get("kieu")
            if kieu not in _TAY_EN:
                raise ValueError(f"Thao tác {i}: kieu tay nắm phải là {', '.join(_TAY_EN)}")
            tn = {**cur.chung.tayNam.model_dump(mode="json"), "kieu": kieu, **({"dai": float(it["dai"])} if it.get("dai") else {})}
            op = {"op": "chung", "thayDoi": {"tayNam": tn}}
            d = {"vi": f"đổi tay nắm sang kiểu {kieu}", "en": f"replace the handles with {_TAY_EN[kieu]}"
                 + (f" in {vocab.tieng_anh(tn['vatLieu'])}" if vocab.tieng_anh(tn.get("vatLieu") or "") and kieu != "khong" else ""),
                 "thaoTac": "thay-vat"}
        elif k == "op":
            op = it.get("op")
            if not isinstance(op, dict) or op.get("op") in (None, "replace"):
                raise ValueError(f"Thao tác {i}: cần 'op' hợp lệ (không nhận replace)")
            d = {"vi": str(it.get("moTa") or op.get("op")), "en": str(it.get("moTaEn") or "apply the design change shown in image 3"),
                 "thaoTac": it.get("thaoTac") or "thay-vat"}
        else:
            raise ValueError(f"Thao tác {i}: loai phải là xoa-module | them-module | kieu-canh | tay-nam | op")
        cur = edit.apply_op(cur, op)
        ops.append(op)
        desc.append(d)
    kinds = {d["thaoTac"] for d in desc}
    tt = kinds.pop() if len(kinds) == 1 else "thay-vat"
    return ops, desc, tt


def pin_cameras(spec: KitchenSpec, nxt: KitchenSpec) -> dict | None:
    """Góc nhìn mặc định tính theo khung bao thiết kế: xóa/thêm tủ làm camera dịch. Ghim camera cũ vào thiết kế mới
    để ảnh trước/sau cùng khung hình (op trả về được ghi cùng rev khi chấp nhận)."""
    old, new = geometry.views_of(spec), geometry.views_of(nxt)
    if {k: v.model_dump(mode="json") for k, v in old.items()} == {k: v.model_dump(mode="json") for k, v in new.items()}:
        return None
    return {"op": "goc-nhin", "gocNhin": {k: v.model_dump(mode="json") for k, v in old.items()}}


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
    return m, {"pixels": int(m.sum()), "xoa": removed, "them": added, "chiTiet": changed,
               "khacChiTiet": int(by_id.sum()), "khacMau": int(alb.sum()), "khacNet": int(by_line.sum())}


def front_mask(d: Path, spec: KitchenSpec, scene, mas: list[str]) -> tuple[np.ndarray, list[np.ndarray]]:
    """Mask mặt trước (cánh, ngăn kéo) của các module — dùng khi thao tác không đổi hình trong render nhanh (kiểu cánh)."""
    inst, meta = imaging.load_instances(d)
    val = {x["id"]: x["value"] for x in meta["instances"]}
    fronts = [p for p in scene.parts if p.module in set(mas) and p.loai in layers.MAT_TRUOC]
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
