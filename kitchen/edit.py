"""Lệnh sửa thiết kế: hàm thuần, nhận spec cũ trả spec mới (không sửa tại chỗ).

"Dồn dãy" (don_day=True): các module cùng tường, cùng dải cao độ, nằm phía sau điểm thay đổi
được dịch theo để không chồng/hở. Tủ cao (cao*) chắn cả tầng dưới lẫn tầng trên nên được tính chung.
"""
from __future__ import annotations

from typing import Any

from .spec import KitchenSpec, Module


def _clone(spec: KitchenSpec) -> KitchenSpec:
    return KitchenSpec.model_validate(spec.model_dump(mode="json"))


def _cung_dai(a: Module, b: Module) -> bool:
    """Hai module cùng tường và chồng nhau theo phương đứng."""
    return a.tuong == b.tuong and a.tuong != "goc" and min(a.y + a.cao, b.y + b.cao) - max(a.y, b.y) > 1


def _dich(spec: KitchenSpec, ref: Module, tu_tu: float, delta: float, bo_qua: set[str]):
    if not delta:
        return
    moved = [m for m in spec.module if m.ma not in bo_qua and _cung_dai(m, ref) and m.tu >= tu_tu - 1]
    # tủ cao bị dịch thì kéo theo mọi module cùng tường phía sau nó (mọi tầng)
    for tall in [m for m in moved if m.tang == "cao"]:
        moved += [m for m in spec.module if m.tuong == tall.tuong and m.tu >= tall.tu - 1
                  and m.ma not in bo_qua and m not in moved]
    for m in moved:
        m.tu = max(0.0, m.tu + delta)
    for tb in spec.thietBi:  # thiết bị gắn vị trí trên tường dịch cùng
        if tb.tuong == ref.tuong and tb.tam is not None and ref.tang == "duoi" and tb.tam >= tu_tu - 1:
            tb.tam += delta


def ma_moi(spec: KitchenSpec, tien_to: str) -> str:
    used = {m.ma for m in spec.module}
    i = 1
    while f"{tien_to}{i}" in used:
        i += 1
    return f"{tien_to}{i}"


def add_module(spec: KitchenSpec, module: dict[str, Any], sau_module: str | None = None, don_day: bool = True) -> KitchenSpec:
    """Thêm module. Nếu có `sau_module`, đặt ngay sau module đó (cùng tường, cùng tầng nếu không nói khác)."""
    s = _clone(spec)
    data = dict(module)
    if sau_module:
        ref = s.tim(sau_module)
        data.setdefault("tuong", ref.tuong)
        data.setdefault("y", ref.y)
        data.setdefault("cao", ref.cao)
        data.setdefault("sau", ref.sau)
        data.setdefault("loai", ref.loai if ref.tang != "goc" else "duoi")
        data["tu"] = ref.het
    if not data.get("ma"):
        tang = data.get("loai", "duoi")
        data["ma"] = ma_moi(s, "TC" if tang.startswith("cao") else "TT" if tang.startswith("tren") else "TD")
    new = Module.model_validate(data)
    if don_day:
        _dich(s, new, new.tu, new.rong, set())
    s.module.append(new)
    return KitchenSpec.model_validate(s.model_dump(mode="json"))


def remove_module(spec: KitchenSpec, ma: str, don_day: bool = True) -> KitchenSpec:
    s = _clone(spec)
    m = s.tim(ma)
    s.module = [x for x in s.module if x.ma != ma]
    s.thietBi = [t for t in s.thietBi if t.module != ma]
    if don_day and m.tuong != "goc":
        _dich(s, m, m.het, -m.rong, set())
    return KitchenSpec.model_validate(s.model_dump(mode="json"))


def update_module(spec: KitchenSpec, ma: str, thay_doi: dict[str, Any], don_day: bool = True) -> KitchenSpec:
    s = _clone(spec)
    old = s.tim(ma)
    if "ma" in thay_doi and thay_doi["ma"] != ma:
        raise ValueError("Không đổi mã module bằng update; hãy xóa rồi thêm")
    merged = {**old.model_dump(mode="json"), **thay_doi}
    if "rong" in thay_doi and "canh" not in thay_doi and old.canh:  # giữ tỉ lệ cánh khi đổi rộng
        free_old = old.rong - old.gocKhuat - old.tamHong
        free_new = merged["rong"] - merged.get("gocKhuat", 0) - merged.get("tamHong", 0)
        merged["canh"] = [round(w * free_new / free_old, 1) for w in old.canh]
    new = Module.model_validate(merged)
    if don_day and new.tuong == old.tuong and new.tuong != "goc":
        if new.het != old.het:
            _dich(s, old, old.het, new.het - old.het, {ma})
    s.module = [new if x.ma == ma else x for x in s.module]
    return KitchenSpec.model_validate(s.model_dump(mode="json"))


def update_chung(spec: KitchenSpec, thay_doi: dict[str, Any]) -> KitchenSpec:
    s = _clone(spec)
    data = s.model_dump(mode="json")
    data["chung"].update(thay_doi)
    return KitchenSpec.model_validate(data)


def apply_op(spec: KitchenSpec, op: dict[str, Any]) -> KitchenSpec:
    """Lệnh dạng dữ liệu (dùng chung cho MCP và HTTP).
    {"op": "add", "module": {...}, "sauModule": "TD3"} | {"op": "remove", "ma": "TD3"}
    {"op": "update", "ma": "TD3", "thayDoi": {...}} | {"op": "chung", "thayDoi": {...}}
    {"op": "replace", "spec": {...}}  — thay toàn bộ (vd nhập file)
    {"op": "ha-dinh", "dinhMoi": 2550} | {"op": "phao", "ma": "phao-noc", "thayDoi": {"boQuaTran": true}}
    {"op": "phao-dat", "moldings": [...], "moldingProfiles"?: [...], "phongCach"?: "Classic"}
    {"op": "goc-nhin", "gocNhin": {...}}  — ghim góc nhìn
    {"op": "nhieu", "ops": [...]}  — nhiều thao tác áp lần lượt, ghi thành một rev (vd job sửa ảnh nhiều việc)"""
    kind = op.get("op")
    dd = op.get("donDay", True)
    if kind == "add":
        return add_module(spec, op["module"], op.get("sauModule"), dd)
    if kind == "remove":
        return remove_module(spec, op["ma"], dd)
    if kind == "update":
        return update_module(spec, op["ma"], op.get("thayDoi", {}), dd)
    if kind == "chung":
        return update_chung(spec, op.get("thayDoi", {}))
    if kind == "replace":
        return KitchenSpec.model_validate(op["spec"])
    if kind == "ha-dinh":  # hạ đỉnh tủ (vd để phào nóc lọt trần)
        from .moldings import lower_top
        return lower_top(spec, float(op["dinhMoi"]))
    if kind == "phao":  # sửa một phào: {"ma": "phao-noc", "thayDoi": {...}}
        data = spec.model_dump(mode="json")
        hit = [m for m in data["moldings"] if m["ma"] == op["ma"]]
        if not hit:
            raise KeyError(f"Không có phào '{op['ma']}'")
        hit[0].update(op.get("thayDoi", {}))
        return KitchenSpec.model_validate(data)
    if kind == "phao-dat":  # thay toàn bộ phào (+ mặt cắt riêng) và phong cách
        data = spec.model_dump(mode="json")
        data["moldings"] = op.get("moldings", [])
        if "moldingProfiles" in op:
            data["moldingProfiles"] = op["moldingProfiles"]
        if op.get("phongCach"):
            data["phongCach"] = op["phongCach"]
        return KitchenSpec.model_validate(data)
    if kind == "goc-nhin":  # ghim / thay bộ góc nhìn (vd giữ camera cũ khi xóa tủ làm khung bao đổi)
        data = spec.model_dump(mode="json")
        data["gocNhin"] = op.get("gocNhin") or {}
        return KitchenSpec.model_validate(data)
    if kind == "nhieu":
        ops = op.get("ops") or []
        if not ops or any(o.get("op") == "nhieu" for o in ops):
            raise ValueError("op 'nhieu' cần danh sách ops (không lồng 'nhieu')")
        for o in ops:
            spec = apply_op(spec, o)
        return spec
    raise ValueError(f"op không hợp lệ: {kind!r}")
