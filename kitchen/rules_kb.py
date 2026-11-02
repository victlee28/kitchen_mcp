"""Bộ kiểm tra theo CHỦ ĐỀ, tham số lấy từ kho tri thức theo khu vực/quốc gia.

Với mỗi chủ đề (vd "hut-mui"), chọn đúng MỘT mục tri thức ưu tiên nhất cho quốc gia của thiết kế
(xem kitchen/regions.py), rồi kiểm theo `params` của mục đó. Issue ghi mã mục đã dùng, mức ưu tiên
và mức độ suy từ loại nguồn (bắt buộc -> error, tiêu chuẩn/khuyến nghị -> warning, thực hành -> info).
Nếu chỉ có tiêu chuẩn nước khác thì vẫn kiểm nhưng hạ xuống info và đánh dấu "thamKhao".
"""
from __future__ import annotations

import math

from . import regions
from .spec import KitchenSpec, ThietBi

CHU_DE = {
    "mat-da-cao": "Chiều cao mặt bàn", "sau-tu-duoi": "Chiều sâu tủ dưới", "sau-mat-da": "Chiều sâu mặt bàn",
    "chau-bep": "Khoảng cách chậu – bếp", "loi-di": "Lối đi làm việc", "ban-chau": "Mặt bàn hai bên chậu",
    "ban-bep": "Mặt bàn hai bên bếp", "ban-tu-lanh": "Mặt bàn cạnh tủ lạnh", "hut-mui": "Máy hút mùi – mặt bếp",
    "tren-bep": "Khoảng trên bếp khi không có hút mùi", "khoang-tu-tren": "Mặt bàn – đáy tủ trên",
    "sau-tu-tren": "Chiều sâu tủ trên", "chan-tu": "Chiều cao chân tủ", "lo-vi-song": "Vị trí lò vi sóng",
    "tam-giac": "Tam giác làm việc", "chieu-cao-thong-thuy": "Chiều cao thông thủy bếp",
}


def select(rows: list[dict], quoc_gia: str | None, khu_vuc: str | None) -> dict[str, dict]:
    """rows: các mục tri thức (đã parse metadata). Trả {chủ đề: {code, params, mucDo, uuTien, thamKhao}}."""
    out: dict[str, dict] = {}
    for r in regions.sap_xep(rows, quoc_gia, khu_vuc):
        meta = r.get("metadata") or {}
        for topic in meta.get("kiemTra") or []:
            if topic in out or topic not in CHU_DE:
                continue
            diem = regions.diem_uu_tien(r, quoc_gia, khu_vuc)
            muc = regions.MUC_DO_THEO_NGUON.get(meta.get("loaiNguon", "chua-ro"), "warning")
            tham_khao = diem < 10  # tiêu chuẩn của nước khác (hoặc chưa chọn quốc gia): chỉ tham khảo -> info
            nhan = regions.nhan_uu_tien(diem) if (quoc_gia or khu_vuc) or diem >= 10 else "tham khảo (chưa chọn quốc gia)"
            out[topic] = {"code": r["code"], "params": meta.get("params") or {}, "mucDo": "info" if tham_khao else muc,
                          "uuTien": nhan, "thamKhao": tham_khao,
                          "vung": f"{r.get('khu_vuc') or 'GLOBAL'}{'/' + r['quoc_gia'] if r.get('quoc_gia') else ''}"}
    return out


class _Ctx:
    def __init__(self, spec: KitchenSpec, sel: dict[str, dict]):
        self.spec, self.sel, self.out = spec, sel, []

    def p(self, topic):
        s = self.sel.get(topic)
        return s["params"] if s else None

    def add(self, topic, mods, msg, measured=None, limit=None):
        s = self.sel[topic]
        d = {"quyTac": s["code"], "chuDe": topic, "mucDo": s["mucDo"], "module": list(mods), "noiDung": msg,
             "theo": f"{s['vung']} · {s['uuTien']}"}
        if s["thamKhao"]:
            d["thamKhao"] = True
        if measured is not None:
            d["doDuoc"] = round(measured, 1) if isinstance(measured, float) else measured
        if limit is not None:
            d["gioiHan"] = limit
        self.out.append(d)


def _runs(spec: KitchenSpec, tuong: str) -> list[tuple[float, float]]:
    ms = sorted((m for m in spec.module if m.tuong == tuong and m.tang == "duoi"), key=lambda m: m.tu)
    runs: list[list[float]] = []
    for m in ms:
        if runs and m.tu <= runs[-1][1] + 1:
            runs[-1][1] = max(runs[-1][1], m.het)
        else:
            runs.append([m.tu, m.het])
    return [(a, b) for a, b in runs]


def _span(tb: ThietBi) -> tuple[float, float]:
    w = (tb.kich_thuoc_so() or [0])[0]
    return tb.tam - w / 2, tb.tam + w / 2


def _landing(spec: KitchenSpec, tb: ThietBi):
    s0, s1 = _span(tb)
    run = next(((a, b) for a, b in _runs(spec, tb.tuong) if a - 1 <= s0 and s1 <= b + 1), None)
    if not run:
        return None
    left, right = run
    for o in spec.thietBi:
        if o is tb or o.tuong != tb.tuong or o.tam is None or o.loai not in ("chau", "bep"):
            continue
        o0, o1 = _span(o)
        if o1 <= s0:
            left = max(left, o1)
        elif o0 >= s1:
            right = min(right, o0)
    return s0 - left, right - s1


def _plan_point(spec, tuong, s, d):
    if tuong == "sau":
        return -s, d
    if tuong == "phai":
        return -d, s
    lsau = (spec.phong.dai("sau") if spec.phong else None) or max([m.het for m in spec.module if m.tuong == "sau"] + [0]) + 600
    return -lsau + d, s


def _range(ctx, topic, value, lo_key, hi_key, label, mods=()):
    p = ctx.p(topic)
    if not p:
        return
    lo, hi = p.get(lo_key), p.get(hi_key)
    if (lo is not None and value < lo - 1) or (hi is not None and value > hi + 1):
        lim = f"{lo if lo is not None else '…'}–{hi if hi is not None else '…'}"
        ctx.add(topic, mods, f"{label} {value:g} mm ngoài {lim} mm", value, [lo, hi])


def check(spec: KitchenSpec, sel: dict[str, dict]) -> list[dict]:
    c = spec.chung
    ctx = _Ctx(spec, sel)
    chau = [t for t in spec.thietBi if t.loai == "chau" and t.tuong and t.tam is not None]
    bep = [t for t in spec.thietBi if t.loai == "bep" and t.tuong and t.tam is not None]
    tu_lanh = [t for t in spec.thietBi if t.loai == "tu-lanh" and t.module]
    lows = [m for m in spec.module if m.tang == "duoi"]
    ups = [m for m in spec.module if m.tang in ("tren", "noc")]

    # kích thước
    if (p := ctx.p("mat-da-cao")):
        _range(ctx, "mat-da-cao", c.matDa, "matDa_min", "matDa_max", "Cao mặt bàn")
        allowed = p.get("matDa_cho_phep")
        if allowed and all(abs(c.matDa - a) > 1 for a in allowed) and p.get("matDa_min", 0) - 1 <= c.matDa <= p.get("matDa_max", 1e9) + 1:
            ctx.add("mat-da-cao", [], f"Cao mặt bàn {c.matDa:g} mm không thuộc các mức phối hợp {allowed}", c.matDa, allowed)
    if (p := ctx.p("sau-tu-duoi")):
        bad = [m.ma for m in lows if not p.get("sauTuDuoi_min", 0) - 1 <= m.sau <= p.get("sauTuDuoi_max", 1e9) + 1]
        if bad:
            ctx.add("sau-tu-duoi", bad, f"Sâu tủ dưới ngoài {p.get('sauTuDuoi_min')}–{p.get('sauTuDuoi_max')} mm",
                    sorted({spec.tim(b).sau for b in bad}), [p.get("sauTuDuoi_min"), p.get("sauTuDuoi_max")])
    if (p := ctx.p("sau-mat-da")) and lows:
        d = max(m.sau for m in lows) + c.nhoMatDa
        if d < p.get("sauMatDa_min", 0) - 1:
            ctx.add("sau-mat-da", [], f"Mặt bàn sâu {d:g} mm < {p['sauMatDa_min']}", d, p["sauMatDa_min"])
    if (p := ctx.p("sau-tu-tren")):
        bad = [m.ma for m in ups if not p.get("sauTuTren_min", 0) - 1 <= m.sau <= p.get("sauTuTren_max", 1e9) + 1]
        if bad:
            ctx.add("sau-tu-tren", bad, f"Sâu tủ trên ngoài {p.get('sauTuTren_min')}–{p.get('sauTuTren_max')} mm",
                    sorted({spec.tim(b).sau for b in bad}), [p.get("sauTuTren_min"), p.get("sauTuTren_max")])
    if ups:
        _range(ctx, "khoang-tu-tren", c.dayTuTren - c.matDa, "khoang_tren_min", "khoang_tren_max", "Mặt bàn tới đáy tủ trên")
    if lows:
        _range(ctx, "chan-tu", c.lenChan, "lenChan_min", "lenChan_max", "Chân tủ cao")
    _range(ctx, "chieu-cao-thong-thuy", c.tran, "tran_min", None, "Chiều cao thông thủy (trần)")

    # chậu – bếp
    if (p := ctx.p("chau-bep")):
        for a in chau:
            for b in bep:
                if a.tuong == b.tuong:
                    gap = abs(a.tam - b.tam) - (a.kich_thuoc_so() or [0])[0] / 2 - (b.kich_thuoc_so() or [0])[0] / 2
                    if gap < p["chau_bep_min"] - 1:
                        ctx.add("chau-bep", [a.ma, b.ma], f"Chậu {a.ma} cách bếp {b.ma} {gap:g} mm < {p['chau_bep_min']}", gap, p["chau_bep_min"])
    # mặt bàn thao tác
    for topic, items, ten in (("ban-chau", chau, "chậu"), ("ban-bep", bep, "bếp")):
        if (p := ctx.p(topic)):
            for t in items:
                sides = _landing(spec, t)
                if not sides:
                    continue
                a, b = sorted(sides, reverse=True)
                if a < p["ben_lon"] - 1 or b < p["ben_nho"] - 1:
                    ctx.add(topic, [t.ma], f"Mặt bàn trống hai bên {ten} {t.ma}: {sides[0]:.0f} / {sides[1]:.0f} mm "
                            f"(cần ≥{p['ben_lon']} một bên, ≥{p['ben_nho']} bên kia)", [round(sides[0]), round(sides[1])],
                            [p["ben_lon"], p["ben_nho"]])
    if (p := ctx.p("ban-tu-lanh")):
        for t in tu_lanh:
            try:
                m = spec.tim(t.module)
            except KeyError:
                continue
            best = 0.0
            for a, b in _runs(spec, m.tuong):
                if abs(a - m.het) <= 1 or abs(b - m.tu) <= 1:
                    near_start = abs(a - m.het) <= 1
                    free = b - a
                    for o in spec.thietBi:
                        if o.tuong == m.tuong and o.tam is not None and o.loai in ("chau", "bep"):
                            o0, o1 = _span(o)
                            if a - 1 <= o0 and o1 <= b + 1:
                                free = min(free, (o0 - a) if near_start else (b - o1))
                    best = max(best, free)
            if best < p["mat_dat_min"] - 1:
                ctx.add("ban-tu-lanh", [m.ma, t.ma], f"Mặt bàn cạnh tủ lạnh {t.ma} chỉ {best:.0f} mm (cần ≥{p['mat_dat_min']})",
                        best, p["mat_dat_min"])
    # phía trên bếp
    hut = {t.module: t for t in spec.thietBi if t.loai == "hut-mui" and t.module}
    for t in bep:
        s0, s1 = _span(t)
        above = [m for m in ups if m.tuong == t.tuong and m.tu < s1 and m.het > s0]
        if not above:
            continue
        direct = [m for m in above if m.tu <= t.tam < m.het]
        lowest = min(direct or above, key=lambda m: m.y)
        if lowest.ma in hut and (p := ctx.p("hut-mui")):
            h = (hut[lowest.ma].kich_thuoc_so() + [0, 0])[1]
            gap = lowest.y - h - c.matDa
            if gap < p["khoang_min"] - 1:
                ctx.add("hut-mui", [lowest.ma, t.ma, hut[lowest.ma].ma], f"Đáy máy hút mùi cách mặt bếp {gap:.0f} mm < {p['khoang_min']}",
                        gap, p["khoang_min"])
        elif lowest.ma not in hut and (p := ctx.p("tren-bep")):
            gap = lowest.y - c.matDa
            if gap < p["khong_hut_mui_min"] - 1:
                ctx.add("tren-bep", [lowest.ma, t.ma], f"Tủ trên {lowest.ma} ngay trên bếp {t.ma}, cách {gap:.0f} mm, không có hút mùi "
                        f"(cần ≥{p['khong_hut_mui_min']})", gap, p["khong_hut_mui_min"])
    # lò vi sóng
    if (p := ctx.p("lo-vi-song")):
        from .geometry import compile_spec
        parts = None
        for t in spec.thietBi:
            if t.loai != "lo" or not t.module:
                continue
            parts = parts or compile_spec(spec).parts
            ps = [x for x in parts if x.module == t.ma]
            if ps:
                y0 = ps[0].min[1]
                if y0 < c.deMatDa and y0 < p["day_duoi_mat_da_min"] - 1:
                    ctx.add("lo-vi-song", [t.module, t.ma], f"Đáy lò {t.ma} cao {y0:.0f} mm (dưới mặt bàn cần ≥{p['day_duoi_mat_da_min']})",
                            y0, p["day_duoi_mat_da_min"])
                elif y0 > p["day_max"] + 1:
                    ctx.add("lo-vi-song", [t.module, t.ma], f"Đáy lò {t.ma} cao {y0:.0f} mm > {p['day_max']}", y0, p["day_max"])
    # tam giác làm việc
    if (p := ctx.p("tam-giac")) and chau and bep and tu_lanh:
        try:
            m = spec.tim(tu_lanh[0].module)
            dm = c.sauTuDuoi / 2
            pts = {"chậu": _plan_point(spec, chau[0].tuong, chau[0].tam, dm), "bếp": _plan_point(spec, bep[0].tuong, bep[0].tam, dm),
                   "tủ lạnh": _plan_point(spec, m.tuong, m.tu + m.rong / 2, m.sau)}
            names = list(pts)
            legs = {f"{a}–{b}": math.dist(pts[a], pts[b]) for i, a in enumerate(names) for b in names[i + 1:]}
            tong = sum(legs.values())
            bad = [k for k, v in legs.items() if not p.get("canh_min", 0) - 1 <= v <= p.get("canh_max", 1e9) + 1]
            if bad or tong > p.get("tong_max", 1e9) + 1:
                ctx.add("tam-giac", [chau[0].ma, bep[0].ma, tu_lanh[0].ma],
                        f"Tam giác làm việc: {', '.join(f'{k} {v:.0f}' for k, v in legs.items())} mm, tổng {tong:.0f} "
                        f"(cạnh {p.get('canh_min', 0)}–{p.get('canh_max', '…')}, tổng ≤{p.get('tong_max', '…')})",
                        {k: round(v) for k, v in legs.items()}, {k: p.get(k) for k in ("canh_min", "canh_max", "tong_max")})
        except KeyError:
            pass
    # lối đi
    if (p := ctx.p("loi-di")):
        lim = p.get("loiDi_min", p.get("loiDi_1nguoi"))
        if not spec.phong or spec.phong.loiDi is None:
            s = sel["loi-di"]
            ctx.out.append({"quyTac": s["code"], "chuDe": "loi-di", "mucDo": "info", "module": [],
                            "noiDung": f"Không kiểm được lối đi (cần ≥{lim} mm): spec chưa có phong.loiDi", "theo": f"{s['vung']} · {s['uuTien']}"})
        elif lim and spec.phong.loiDi < lim - 1:
            ctx.add("loi-di", [], f"Lối đi {spec.phong.loiDi:g} mm < {lim}", spec.phong.loiDi, lim)
    return ctx.out
