"""Rule engine tất định. LLM chỉ được đề xuất; mọi kết luận đúng/sai hình học đi qua đây.

Mỗi issue: {quyTac, mucDo (error|warning|info), module[], noiDung, doDuoc?, gioiHan?}
Quy tắc trong KB (bảng knowledge) có thể mang tham số máy đọc được ở metadata_json.params;
code nào có bộ kiểm tra thì dùng tham số đó, code chưa có bộ kiểm tra được liệt kê ở `chuaKiemTra`.
"""
from __future__ import annotations

from itertools import combinations

from . import knowledge_seed, moldings, regions, rules_kb
from .spec import KitchenSpec, Module

TOL = 1.0  # mm


def _issue(code, muc, mods, msg, measured=None, limit=None):
    d = {"quyTac": code, "mucDo": muc, "module": list(mods), "noiDung": msg}
    if measured is not None:
        d["doDuoc"] = measured
    if limit is not None:
        d["gioiHan"] = limit
    return d


def _envelopes(spec: KitchenSpec) -> list[tuple[str, tuple, tuple]]:
    """Khối bao của từng module (ke-goc tách 2 cánh) trong toạ độ thế giới."""
    out = []
    lsau = (spec.phong.dai("sau") if spec.phong else None) or max([m.het for m in spec.module if m.tuong == "sau"] + [0]) + 600
    for m in spec.module:
        y0, y1 = m.y, m.y + m.cao
        if m.loai == "ke-goc":
            out.append((m.ma, (-m.canhSau, y0, 0), (0, y1, m.sau)))
            out.append((m.ma, (-m.sau, y0, 0), (0, y1, m.canhPhai)))
        elif m.tuong == "sau":
            out.append((m.ma, (-m.het, y0, 0), (-m.tu, y1, m.sau)))
        elif m.tuong == "phai":
            out.append((m.ma, (-m.sau, y0, m.tu), (0, y1, m.het)))
        else:
            out.append((m.ma, (-lsau, y0, m.tu), (-lsau + m.sau, y1, m.het)))
    return out


def _overlap(a, b) -> float:
    v = 1.0
    for i in range(3):
        v *= max(0.0, min(a[1][i], b[1][i]) - max(a[0][i], b[0][i]) - TOL)
    return v


def check_geometry(spec: KitchenSpec) -> list[dict]:
    c = spec.chung
    issues = []
    env = _envelopes(spec)
    for (ma, mn, mx), (mb, nn, nx) in combinations(env, 2):
        if ma != mb and _overlap((mn, mx), (nn, nx)) > 0:
            issues.append(_issue("GEO-VA-CHAM", "error", [ma, mb], f"{ma} và {mb} chồng lên nhau"))
    muc_tang = {"duoi": c.deMatDa, "tren": c.chiaTangTren, "noc": c.dinhTu, "cao": c.dinhTu, "goc": None}
    for m in spec.module:
        top = m.y + m.cao
        lim = muc_tang[m.tang]
        if lim is not None and abs(top - lim) > TOL:
            issues.append(_issue("GEO-CAO-DO", "warning", [m.ma], f"{m.ma}: đỉnh {top:g} lệch cao độ tầng {m.tang} ({lim:g})", top, lim))
        if m.tang == "tren" and m.loai != "tren-hut-mui" and abs(m.y - c.dayTuTren) > TOL:
            issues.append(_issue("GEO-CAO-DO", "warning", [m.ma], f"{m.ma}: đáy {m.y:g} khác dayTuTren {c.dayTuTren:g}", m.y, c.dayTuTren))
        if m.canh:
            tong = sum(m.canh) + m.gocKhuat + m.tamHong
            if abs(tong - m.rong) > TOL:
                issues.append(_issue("GEO-CANH", "warning", [m.ma],
                                     f"{m.ma}: tổng cánh + góc khuất + tấm hông = {tong:g} ≠ rộng {m.rong:g}", tong, m.rong))
        if spec.phong and m.tuong in ("sau", "phai", "trai"):
            L = spec.phong.dai(m.tuong)
            if L and m.het > L + TOL:
                issues.append(_issue("GEO-TUONG", "error", [m.ma], f"{m.ma} vượt chiều dài tường {m.tuong} ({m.het:g} > {L:g})", m.het, L))
    if c.dinhTu > c.tran + TOL:
        issues.append(_issue("GEO-TRAN", "error", [], f"Đỉnh tủ {c.dinhTu:g} cao hơn trần {c.tran:g}", c.dinhTu, c.tran))
    if abs(c.matDa - (c.deMatDa + c.dayMatDa)) > TOL:
        issues.append(_issue("GEO-MAT-DA", "warning", [], f"matDa {c.matDa:g} ≠ deMatDa + dayMatDa = {c.deMatDa + c.dayMatDa:g}"))
    # khe hở giữa các module liền kề trong cùng tường/tầng
    for tuong in ("sau", "phai", "trai"):
        for tang in ("duoi", "tren", "noc"):
            ms = sorted((m for m in spec.module if m.tuong == tuong and m.tang in (tang, "cao")), key=lambda m: m.tu)
            for a, b in zip(ms, ms[1:]):
                if a.tang == b.tang == "cao":
                    continue
                gap = b.tu - a.het
                if gap > TOL:
                    issues.append(_issue("GEO-KHE-HO", "info", [a.ma, b.ma], f"Khe hở {gap:g} mm giữa {a.ma} và {b.ma} (tường {tuong})", gap))
    # thiết bị lọt module
    for tb in spec.thietBi:
        k = tb.kich_thuoc_so()
        if not tb.module:
            continue
        try:
            m = spec.tim(tb.module)
        except KeyError:
            issues.append(_issue("TB-MODULE", "error", [], f"{tb.ma}: module '{tb.module}' không tồn tại"))
            continue
        if tb.loai == "tu-lanh" and len(k) >= 3:
            w, h, d = k[:3]
            inner = m.rong - 2 * c.dayCanh
            if w > inner + TOL or (m.hoc and h > m.hoc + TOL) or d > m.sau + TOL:
                issues.append(_issue("TB-LOT-HOC", "error", [m.ma, tb.ma], f"{tb.ma} {w:g}×{h:g}×{d:g} không lọt hốc {m.ma}"))
        if tb.loai == "lo" and len(k) >= 2:
            w, h = k[:2]
            hoc = next((t.cao for t in m.matTruoc if t.loai == "hoc"), None)
            if w > m.rong - 2 * c.dayCanh + TOL or (hoc and h > hoc - 2 * c.dayCanh + TOL):
                issues.append(_issue("TB-LOT-HOC", "error", [m.ma, tb.ma], f"{tb.ma} không lọt hộc {m.ma}"))
    return issues


def default_rows() -> list[dict]:
    """Kho nền dùng khi không có DB (test, hàm thuần)."""
    return [{"id": i + 1, **k} for i, k in enumerate(knowledge_seed.KNOWLEDGE) if k["kind"] in ("rule", "standard")]


def validate(spec: KitchenSpec, kb_rules: list[dict] | None = None, quoc_gia: str | None = None,
             khu_vuc: str | None = None) -> dict:
    """kb_rules: các dòng tri thức kind rule/standard đang active (đã parse metadata); None -> kho nền.
    Quốc gia/khu vực: tham số > spec.quocGia/spec.khuVuc > không chỉ định (ưu tiên mục toàn cầu, rồi nguồn mạnh nhất)."""
    qg, kv = regions.chuan_hoa(quoc_gia or spec.quocGia, khu_vuc or spec.khuVuc)
    rows = default_rows() if kb_rules is None else kb_rules
    sel = rules_kb.select(rows, qg, kv)
    issues = check_geometry(spec) + rules_kb.check(spec, sel) + moldings.check(spec)
    if not (qg or kv):
        issues.append({"quyTac": "VUNG", "mucDo": "info", "module": [], "noiDung": "Chưa chọn quốc gia/khu vực (spec.quocGia): "
                       "chỉ tiêu chuẩn toàn cầu được áp, tiêu chuẩn của các nước chỉ để tham khảo"})
    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order[i["mucDo"]])
    dem = {k: sum(i["mucDo"] == k for i in issues) for k in order}
    dung = {t: f"{v['code']} ({v['vung']}, {v['uuTien']})" for t, v in sel.items()}
    chua = [r["code"] for r in rows if not (r.get("metadata") or {}).get("kiemTra")]
    return {"hopLe": dem["error"] == 0, "dem": dem, "issues": issues, "quocGia": qg, "khuVuc": kv,
            "quyTacDaDung": dung, "chuaKiemTra": chua}
