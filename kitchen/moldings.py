"""Phào cổ điển: preset mặt cắt, tính đường chạy từ module, quét mặt cắt thành lưới tam giác, kiểm tra.

Đường chạy (mặt bằng x, z; mm) đi theo thứ tự tường phải (về phía góc) -> tường sau -> tường trái, sao cho
phía phòng luôn nằm theo pháp tuyến n = (t.z, -t.x) của hướng đi t. Góc chữ L và đầu quay về tường là các
đỉnh của cùng một đường gấp khúc nên được vát góc (miter) tự động khi quét. Thuật toán quét có bản JS tương ứng
trong web/scene-loader.js (sweepRings) và được test so khớp.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .spec import KitchenSpec, Molding, MoldingProfile, Module

PRESETS: dict[str, MoldingProfile] = {p.ma: p for p in [
    MoldingProfile(ma="classic-crown-simple", ten="Phào nóc đơn giản",
                   points=[(-40, 0), (0, 0), (0, 20), (30, 50), (40, 50), (40, 60), (-40, 60)],
                   moTa="Cao 60, nhô 40. Hợp tủ trên thấp hoặc trần thấp."),
    MoldingProfile(ma="classic-crown-layered", ten="Phào nóc nhiều lớp",
                   points=[(-40, 0), (0, 0), (0, 10), (12, 14), (16, 24), (34, 42), (52, 58), (62, 70), (68, 78),
                           (68, 90), (-40, 90)],
                   moTa="Cao 90, nhô 68, có gờ chỉ ở chân. Tủ cổ điển tiêu chuẩn."),
    MoldingProfile(ma="classic-crown-cornice", ten="Phào nóc cornice lớn",
                   points=[(-50, 0), (0, 0), (0, 30), (20, 36), (24, 50), (60, 80), (90, 104), (100, 110), (100, 130), (-50, 130)],
                   moTa="Cao 130, nhô 100. Cần trần cao."),
    MoldingProfile(ma="classic-base", ten="Phào chân",
                   points=[(-70, 0), (15, 0), (15, 15), (8, 25), (5, 80), (0, 95), (-70, 95)],
                   moTa="Cao 95, ốp che chân tủ, nhô 15 trước mặt cánh."),
    MoldingProfile(ma="classic-base-low", ten="Phào chân thấp",
                   points=[(-70, 0), (10, 0), (10, 12), (4, 20), (0, 70), (-70, 70)], moTa="Cao 70."),
]}


def profile_of(spec: KitchenSpec, ma: str) -> MoldingProfile | None:
    for p in spec.moldingProfiles:
        if p.ma == ma:
            return p
    return PRESETS.get(ma)


def default_moldings(crown: bool = True, base: bool = True, crown_profile: str = "classic-crown-layered",
                     base_profile: str = "classic-base") -> list[Molding]:
    out = []
    if crown:
        out.append(Molding(ma="phao-noc", kieu="crown", profile=crown_profile))
    if base:
        out.append(Molding(ma="phao-chan", kieu="base", profile=base_profile))
    return out


# ------------------------------------------------------------------ đường chạy
@dataclass
class Run:
    molding: Molding
    profile: MoldingProfile
    y: float
    points: list[tuple[float, float]]  # (x, z) mặt bằng, mm
    modules: list[str] = field(default_factory=list)
    tuong: list[str] = field(default_factory=list)

    @property
    def length(self) -> float:
        return sum(math.dist(a, b) for a, b in zip(self.points, self.points[1:]))


def _lsau(spec: KitchenSpec) -> float:
    return (spec.phong.dai("sau") if spec.phong else None) or max([m.het for m in spec.module if m.tuong == "sau"] + [0]) + 600


def _wall_pt(tuong: str, s: float, d: float, lsau: float) -> tuple[float, float]:
    if tuong == "sau":
        return (-s, d)
    if tuong == "phai":
        return (-d, s)
    return (-lsau + d, s)


def _top(m: Module) -> float:
    return m.y + m.cao


def _intervals(spec: KitchenSpec, kieu: str) -> tuple[dict[str, list[tuple[float, float, float, str]]], float]:
    """Đoạn (s0, s1, độ sâu mặt trước, mã module) theo từng tường + cao độ đường chạy."""
    iv: dict[str, list] = {"sau": [], "phai": [], "trai": []}
    if kieu == "crown":
        cands = [m for m in spec.module if m.tang in ("tren", "noc", "cao", "goc")]
        if not cands:
            return iv, 0.0
        y = max(_top(m) for m in cands)
        for m in cands:
            if abs(_top(m) - y) > 1:
                continue
            if m.loai == "ke-goc":
                iv["sau"].append((0.0, m.canhSau, m.sau, m.ma))
                iv["phai"].append((0.0, m.canhPhai, m.sau, m.ma))
            else:
                iv[m.tuong].append((m.tu, m.het, m.sau, m.ma))
        return iv, y
    for m in spec.module:  # phào chân: tủ đặt sàn, bỏ tủ cao có hốc thiết bị sát sàn (tủ lạnh)
        if m.y == 0 and m.tuong in iv and (m.tang == "duoi" or (m.tang == "cao" and not m.hoc)):
            iv[m.tuong].append((m.tu, m.het, m.sau, m.ma))
    return iv, 0.0


def _segments(items, gap):
    segs = []
    for s0, s1, d, ma in sorted(items):
        if segs and abs(segs[-1]["d"] - d) <= 1 and s0 - segs[-1]["s1"] <= gap:
            segs[-1]["s1"] = max(segs[-1]["s1"], s1)
            segs[-1]["mods"].append(ma)
        else:
            segs.append({"s0": s0, "s1": s1, "d": d, "mods": [ma]})
    return segs


def _end_depth(seg, neighbor, ho: str) -> float | None:
    """Độ sâu mà đầu phào quay về; None = cắt phẳng (đâm vào hông tủ sâu hơn hoặc tường)."""
    if neighbor is not None:
        if neighbor["d"] > seg["d"] + 1:
            return None
        return neighbor["d"]
    return 0.0 if ho == "tra-ve-tuong" else None


def compute_runs(spec: KitchenSpec) -> list[Run]:
    lsau = _lsau(spec)
    runs: list[Run] = []
    for mol in spec.moldings:
        if not mol.bat:
            continue
        prof = profile_of(spec, mol.profile)
        if prof is None:
            continue
        iv, y = _intervals(spec, mol.kieu)
        walls = mol.tuong or ["phai", "sau", "trai"]
        segs = {w: (_segments(iv[w], mol.khoangNoi) if w in walls else []) for w in ("phai", "sau", "trai")}
        # nối góc: đoạn đầu tường phải/trái chạm đoạn đầu (cuối) tường sau
        join_r = bool(segs["phai"] and segs["sau"] and segs["phai"][0]["s0"] <= segs["sau"][0]["d"] + 1
                      and segs["sau"][0]["s0"] <= segs["phai"][0]["d"] + 1)
        join_l = bool(segs["trai"] and segs["sau"] and segs["trai"][0]["s0"] <= segs["sau"][-1]["d"] + 1
                      and segs["sau"][-1]["s1"] >= lsau - segs["trai"][0]["d"] - 1)

        def wall_polys(w):
            """Mỗi đoạn -> danh sách (s, d) theo chiều đi, kèm cờ bỏ xử lý đầu ở phía góc."""
            out = []
            ss = segs[w]
            for i, sg in enumerate(ss):
                prev_n = ss[i - 1] if i > 0 and sg["s0"] - ss[i - 1]["s1"] <= mol.khoangNoi else None
                next_n = ss[i + 1] if i + 1 < len(ss) and ss[i + 1]["s0"] - sg["s1"] <= mol.khoangNoi else None
                at_corner_start = i == 0 and ((w == "phai" and join_r) or (w == "trai" and join_l) or (w == "sau" and join_r))
                at_corner_end = (w == "sau" and i == len(ss) - 1 and join_l)
                d = sg["d"]
                # đầu phía s0
                if at_corner_start:
                    other = segs["sau"][0]["d"] if w == "phai" else segs["phai"][0]["d"] if w == "sau" else segs["sau"][-1]["d"]
                    start = [(other, d)]
                else:
                    dr = None if (sg["s0"] <= 1 and prev_n is None) else _end_depth(sg, prev_n, mol.dauHo)
                    start = [(sg["s0"], d)] if dr is None or abs(dr - d) < 1 else [(sg["s0"], dr), (sg["s0"], d)]
                if at_corner_end:
                    end = [(lsau - segs["trai"][0]["d"], d)]
                else:
                    dr = _end_depth(sg, next_n, mol.dauHo)
                    end = [(sg["s1"], d)] if dr is None or abs(dr - d) < 1 else [(sg["s1"], d), (sg["s1"], dr)]
                pts = start + end  # theo chiều s tăng
                if w == "phai":
                    pts = pts[::-1]  # tường phải đi về phía góc (s giảm)
                out.append({"pts": [_wall_pt(w, s, dd, lsau) for s, dd in pts], "mods": sg["mods"], "w": w,
                            "corner_start": at_corner_start, "corner_end": at_corner_end})
            return out

        polys = {w: wall_polys(w) for w in ("phai", "sau", "trai")}
        chains: list[dict] = []
        if join_r:
            r_last = polys["phai"].pop(0)  # đoạn chạm góc (s nhỏ nhất); theo chiều đi nó kết thúc ở góc
            b_first = polys["sau"].pop(0)
            chains.append({"pts": r_last["pts"] + b_first["pts"][1:], "mods": r_last["mods"] + b_first["mods"], "w": ["phai", "sau"],
                           "tail": b_first})
        for w in ("phai", "sau", "trai"):
            for p in polys[w]:
                chains.append({"pts": p["pts"], "mods": p["mods"], "w": [w], "tail": p})
        if join_l:
            # nối chuỗi chứa đoạn cuối tường sau với đoạn đầu tường trái
            l_first = next(c for c in chains if c["w"] == ["trai"])
            b_last = next(c for c in chains if c["tail"].get("corner_end"))
            if b_last is not l_first:
                b_last["pts"] = b_last["pts"] + l_first["pts"][1:]
                b_last["mods"] += l_first["mods"]
                b_last["w"] = b_last["w"] + ["trai"]
                chains.remove(l_first)
        for ch in chains:
            pts = [p for i, p in enumerate(ch["pts"]) if i == 0 or math.dist(p, ch["pts"][i - 1]) > 0.5]
            if len(pts) >= 2:
                runs.append(Run(mol, prof, y, pts, ch["mods"], ch["w"]))
    return runs


# ------------------------------------------------------------------ quét mặt cắt
def _normals(pts):
    ts = []
    for a, b in zip(pts, pts[1:]):
        L = math.dist(a, b)
        ts.append(((b[0] - a[0]) / L, (b[1] - a[1]) / L))
    return [(t[1], -t[0]) for t in ts], ts


def sweep_rings(profile: list[tuple[float, float]], pts: list[tuple[float, float]], y: float) -> list[list[tuple[float, float, float]]]:
    """Vòng đỉnh 3D tại mỗi đỉnh đường chạy (miter ở đỉnh giữa). Bản JS: sweepRings trong scene-loader.js."""
    ns, _ = _normals(pts)
    rings = []
    for i, p in enumerate(pts):
        if i == 0:
            m = ns[0]
        elif i == len(pts) - 1:
            m = ns[-1]
        else:
            a, b = ns[i - 1], ns[i]
            k = 1 + a[0] * b[0] + a[1] * b[1]
            m = ((a[0] + b[0]) / k, (a[1] + b[1]) / k) if k > 1e-6 else b
        rings.append([(p[0] + m[0] * u, y + v, p[1] + m[1] * u) for u, v in profile])
    return rings


def _ear_clip(poly: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
    idx = list(range(len(poly)))
    tris = []

    def area2(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if area2(a, b, c) <= 1e-9:
                continue
            if any(area2(a, b, poly[j]) >= 0 and area2(b, c, poly[j]) >= 0 and area2(c, a, poly[j]) >= 0
                   for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


@dataclass
class MeshPart:
    id: str
    module: str  # mã phào (để tô mask theo từng phào)
    loai: str
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]


def run_mesh(run: Run, idx: int) -> MeshPart:
    prof = run.profile.points
    rings = sweep_rings(prof, run.points, run.y)
    n = len(prof)
    verts = [v for r in rings for v in r]
    faces = []
    for k in range(len(rings) - 1):
        for j in range(n):
            a, b = k * n + j, k * n + (j + 1) % n
            c, d = (k + 1) * n + (j + 1) % n, (k + 1) * n + j
            faces += [(a, b, c), (a, c, d)]
    cap = _ear_clip(prof)
    last = (len(rings) - 1) * n
    faces += [(c, b, a) for a, b, c in cap] + [(last + a, last + b, last + c) for a, b, c in cap]
    return MeshPart(f"{run.molding.ma}-{idx}", run.molding.ma, "phao", verts, faces)


def meshes(spec: KitchenSpec) -> list[MeshPart]:
    return [run_mesh(r, i + 1) for i, r in enumerate(compute_runs(spec))]


# ------------------------------------------------------------------ kiểm tra
def _flap(m: Module) -> bool:
    return (m.moCanh[:1] == ["tren"]) or (not m.moCanh and m.tang == "noc" and m.rong > m.cao * 1.2)


def check(spec: KitchenSpec) -> list[dict]:
    c = spec.chung
    out = []
    by_ma = {m.ma: m for m in spec.module}
    runs = compute_runs(spec)
    for mol in spec.moldings:
        if not mol.bat:
            continue
        prof = profile_of(spec, mol.profile)
        if prof is None:
            out.append({"quyTac": "MOLDING-PROFILE-001", "mucDo": "error", "module": [mol.ma],
                        "noiDung": f"Phào {mol.ma}: không có mặt cắt '{mol.profile}'"})
            continue
        mine = [r for r in runs if r.molding.ma == mol.ma]
        if not mine:
            out.append({"quyTac": "MOLDING-RUN-001", "mucDo": "info", "module": [mol.ma],
                        "noiDung": f"Phào {mol.ma}: không có dãy tủ phù hợp để chạy phào"})
            continue
        if mol.kieu == "crown":
            top = mine[0].y + prof.cao
            if top > c.tran + 0.5:
                dinh_moi = math.floor((c.tran - prof.cao) / 5) * 5
                delta = c.dinhTu - dinh_moi
                actions = []
                if delta > 0 and _can_lower(spec, delta):
                    actions.append({"nhan": f"Hạ đỉnh tủ {delta:g} mm ({c.dinhTu:g} → {dinh_moi:g})",
                                    "op": {"op": "ha-dinh", "dinhMoi": dinh_moi}})
                if not mol.boQuaTran:
                    actions.append({"nhan": "Để nguyên", "op": {"op": "phao", "ma": mol.ma, "thayDoi": {"boQuaTran": True}}})
                    out.append({"quyTac": "MOLDING-TRAN-001", "mucDo": "error", "module": [mol.ma] + mine[0].modules[:3],
                                "noiDung": f"Phào nóc {mol.ma} cao tới {top:g} mm, vượt trần {c.tran:g} mm",
                                "doDuoc": top, "gioiHan": c.tran, "hanhDong": actions})
                else:
                    out.append({"quyTac": "MOLDING-TRAN-001", "mucDo": "info", "module": [mol.ma],
                                "noiDung": f"Phào nóc {mol.ma} vượt trần {top - c.tran:g} mm — đã chọn để nguyên",
                                "doDuoc": top, "gioiHan": c.tran,
                                "hanhDong": actions + [{"nhan": "Bỏ chọn để nguyên", "op": {"op": "phao", "ma": mol.ma, "thayDoi": {"boQuaTran": False}}}]})
            flaps = sorted({ma for r in mine for ma in r.modules if ma in by_ma and _flap(by_ma[ma])})
            if flaps and prof.nho > 0:
                out.append({"quyTac": "MOLDING-CANH-LAT-001", "mucDo": "warning", "module": flaps,
                            "noiDung": f"Cánh lật lên của {', '.join(flaps)} có thể chạm phào nóc nhô {prof.nho:g} mm; "
                                       "cân nhắc cánh mở ngang hoặc tay nâng có góc mở nhỏ"})
        else:
            if prof.cao > c.lenChan + 2:
                out.append({"quyTac": "MOLDING-CHAN-001", "mucDo": "warning", "module": [mol.ma],
                            "noiDung": f"Phào chân cao {prof.cao:g} mm > chân tủ {c.lenChan:g} mm: che mép dưới cánh",
                            "doDuoc": prof.cao, "gioiHan": c.lenChan})
    return out


def _can_lower(spec: KitchenSpec, delta: float) -> bool:
    try:
        lower_top(spec, spec.chung.dinhTu - delta)
        return True
    except ValueError:
        return False


def lower_top(spec: KitchenSpec, dinh_moi: float) -> KitchenSpec:
    """Hạ đỉnh tủ: rút chiều cao các module đang chạm đỉnh (tủ nóc, tủ cao, kệ góc, tủ trên nếu không có nóc)."""
    data = spec.model_dump(mode="json")
    old = spec.chung.dinhTu
    delta = old - dinh_moi
    if delta <= 0:
        raise ValueError("Đỉnh mới phải thấp hơn đỉnh hiện tại")
    for m in data["module"]:
        if abs(m["y"] + m["cao"] - old) > 1:
            continue
        new_h = m["cao"] - delta
        min_h = 150 if m["loai"] == "tren-noc" else 300
        if new_h < min_h:
            raise ValueError(f"{m['ma']} còn {new_h:g} mm, thấp hơn mức tối thiểu {min_h}")
        if m.get("hoc") and m["y"] + new_h < m["hoc"] + 150:
            raise ValueError(f"{m['ma']}: phần trên hốc thiết bị còn quá thấp")
        m["cao"] = new_h
    c = data["chung"]
    if abs(c["chiaTangTren"] - old) <= 1:
        c["chiaTangTren"] = dinh_moi
    c["dinhTu"] = dinh_moi
    return KitchenSpec.model_validate(data)
