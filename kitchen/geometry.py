"""Compiler: KitchenSpec -> danh sách khối hộp (AABB) trong toạ độ thế giới (mm).

Vì mọi tường đều vuông góc nên mọi chi tiết là hộp thẳng trục; viewer và renderer
chỉ cần (min, max). Mỗi chi tiết mang `module` để chọn/tô mask theo module.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .spec import GocNhin, KitchenSpec, Module

MAU = {  # màu hiển thị theo loại chi tiết (viewer 3D, mask ngữ nghĩa)
    "than": "#d9c3a0", "chan": "#5b5348", "canh": "#c8a273", "canh-kinh": "#9fc7d8", "ngan-keo": "#b98f5e",
    "hong": "#c19a6b", "ke": "#a77f55", "mat-da": "#f1f0ec", "tu-lanh": "#c9ccd1", "chau": "#2f3236",
    "voi": "#8a8f96", "bep": "#121212", "hut-mui": "#6f747a", "lo": "#3a3d42", "tuong": "#ece7de", "san": "#bdb4a6",
    "phao": "#a87542", "tay-nam": "#2b2b2b",
}


@dataclass
class Part:
    id: str
    module: str | None
    loai: str
    min: tuple[float, float, float]
    max: tuple[float, float, float]
    tuong: str | None = None  # tường chứa chi tiết (để suy hướng mặt trước khi xuất three.js)
    parent: str | None = None  # chi tiết cha (tay nắm -> cánh/ngăn kéo)

    def to_json(self) -> dict:
        c = [(a + b) / 2 for a, b in zip(self.min, self.max)]
        s = [b - a for a, b in zip(self.min, self.max)]
        return {"id": self.id, "module": self.module, "loai": self.loai, "center": [round(v, 2) for v in c],
                "size": [round(v, 2) for v in s], "color": MAU.get(self.loai, "#cccccc")}


@dataclass
class Scene:
    parts: list[Part] = field(default_factory=list)
    lsau: float = 0
    lphai: float = 0
    meshes: list = field(default_factory=list)  # lưới tam giác không thẳng trục (phào) — kitchen.moldings.MeshPart

    def bounds(self, chi_tu: bool = True) -> tuple[list[float], list[float]]:
        ps = [p for p in self.parts if p.loai != "tay-nam" and (not chi_tu or p.loai not in ("tuong", "san"))]
        lo = [min(p.min[i] for p in ps) for i in range(3)]
        hi = [max(p.max[i] for p in ps) for i in range(3)]
        return lo, hi


def _dai_tuong(spec: KitchenSpec) -> tuple[float, float]:
    def het(tuong: str) -> float:
        vals = [m.het for m in spec.module if m.tuong == tuong]
        if tuong == "sau":
            vals += [m.canhSau or 0 for m in spec.module if m.loai == "ke-goc"]
        if tuong == "phai":
            vals += [m.canhPhai or 0 for m in spec.module if m.loai == "ke-goc"]
        return max(vals, default=0)
    lsau = (spec.phong.dai("sau") if spec.phong else None) or het("sau") + 600
    lphai = (spec.phong.dai("phai") if spec.phong else None) or max(het("phai"), het("trai")) + 600
    return lsau, lphai


class _Builder:
    def __init__(self, spec: KitchenSpec):
        self.spec = spec
        self.c = spec.chung
        self.lsau, self.lphai = _dai_tuong(spec)
        self.parts: list[Part] = []
        self._n: dict[str, int] = {}

    # ---- toạ độ tường -> thế giới
    def box(self, module: str | None, loai: str, tuong: str, s0, s1, d0, d1, y0, y1):
        if s1 - s0 <= 0.01 or d1 - d0 <= 0.01 or y1 - y0 <= 0.01:
            return
        if tuong == "sau":
            mn, mx = (-s1, y0, d0), (-s0, y1, d1)
        elif tuong == "phai":
            mn, mx = (-d1, y0, s0), (-d0, y1, s1)
        elif tuong == "trai":
            mn, mx = (-self.lsau + d0, y0, s0), (-self.lsau + d1, y1, s1)
        else:
            raise ValueError(tuong)
        key = f"{module or 'phong'}-{loai}"
        self._n[key] = self._n.get(key, 0) + 1
        self.parts.append(Part(f"{key}-{self._n[key]}", module, loai, mn, mx, tuong))

    def cac_canh(self, m: Module, s0, s1, y0, y1, loai="canh"):
        """Chia dải mặt trước [s0,s1]x[y0,y1] thành cánh theo tỉ lệ m.canh, chừa khe."""
        k, dc = self.c.kheCanh, self.c.dayCanh
        ws = m.canh or [s1 - s0]
        tong = sum(ws)
        s = s0
        for w in ws:
            w2 = w * (s1 - s0) / tong
            self.box(m.ma, loai, m.tuong, s + k / 2, s + w2 - k / 2, m.sau - dc, m.sau, y0 + k / 2, y1 - k / 2)
            s += w2

    # ---- các loại module
    def tu_duoi(self, m: Module):
        c, dc = self.c, self.c.dayCanh
        top = m.y + m.cao
        y_than = max(m.y, c.lenChan) if m.y == 0 else m.y
        fs0, fs1 = m.tu + m.gocKhuat, m.het - m.tamHong
        if m.y == 0:
            self.box(m.ma, "chan", m.tuong, m.tu, m.het - m.tamHong, 0, m.sau - dc - 50, 0, c.lenChan)
        if m.tamHong:
            self.box(m.ma, "hong", m.tuong, m.het - m.tamHong, m.het, 0, m.sau, 0, top)
        if m.gocKhuat:  # phần góc khuất: thân kín, không cánh
            self.box(m.ma, "than", m.tuong, m.tu, fs0, 0, m.sau, y_than, top)
        if not m.matTruoc:
            self.box(m.ma, "than", m.tuong, fs0, fs1, 0, m.sau - dc, y_than, top)
            self.cac_canh(m, fs0, fs1, y_than, top)
            return
        cur = top
        for i, t in enumerate(m.matTruoc):
            y0 = max(y_than, cur - t.cao)
            if t.loai == "hoc":  # hộc trống: vách sau + ván nóc/đáy + hai hông
                self.box(m.ma, "than", m.tuong, fs0, fs1, 0, 60, y0, cur)
                self.box(m.ma, "ke", m.tuong, fs0, fs1, 0, m.sau, cur - dc, cur)
                self.box(m.ma, "ke", m.tuong, fs0, fs1, 0, m.sau, y0, y0 + dc)
                self.box(m.ma, "hong", m.tuong, fs0, fs0 + dc, 0, m.sau, y0, cur)
                self.box(m.ma, "hong", m.tuong, fs1 - dc, fs1, 0, m.sau, y0, cur)
            else:
                self.box(m.ma, "than", m.tuong, fs0, fs1, 0, m.sau - dc, y0, cur)
                if t.loai == "canh":
                    self.cac_canh(m, fs0, fs1, y0, cur)
                else:
                    self.box(m.ma, "ngan-keo", m.tuong, fs0 + c.kheCanh / 2, fs1 - c.kheCanh / 2, m.sau - dc, m.sau,
                             y0 + c.kheCanh / 2, cur - c.kheCanh / 2)
            cur = y0
        if cur - y_than > 30:  # phần còn lại phía dưới: một ngăn kéo
            self.box(m.ma, "than", m.tuong, fs0, fs1, 0, m.sau - dc, y_than, cur)
            self.box(m.ma, "ngan-keo", m.tuong, fs0 + c.kheCanh / 2, fs1 - c.kheCanh / 2, m.sau - dc, m.sau,
                     y_than + c.kheCanh / 2, cur - c.kheCanh / 2)

    def tu_tren(self, m: Module):
        dc = self.c.dayCanh
        fs0, fs1 = m.tu + m.gocKhuat, m.het - m.tamHong
        self.box(m.ma, "than", m.tuong, m.tu, m.het, 0, m.sau - dc, m.y, m.y + m.cao)
        if m.tamHong:
            self.box(m.ma, "hong", m.tuong, fs1, m.het, 0, m.sau, m.y, m.y + m.cao)
        self.cac_canh(m, fs0, fs1, m.y, m.y + m.cao, "canh-kinh" if m.loai == "tren-kinh" else "canh")

    def tu_cao(self, m: Module):
        dc = self.c.dayCanh
        top = m.y + m.cao
        self.box(m.ma, "hong", m.tuong, m.tu, m.tu + dc, 0, m.sau, m.y, top)
        self.box(m.ma, "hong", m.tuong, m.het - dc, m.het, 0, m.sau, m.y, top)
        if m.hoc:
            self.box(m.ma, "than", m.tuong, m.tu + dc, m.het - dc, 0, m.sau - dc, m.hoc, top)
            self.box(m.ma, "than", m.tuong, m.tu + dc, m.het - dc, 0, 20, m.y, m.hoc)  # vách sau hốc
            self.cac_canh(m, m.tu + dc, m.het - dc, m.hoc, top)
        else:
            self.box(m.ma, "than", m.tuong, m.tu + dc, m.het - dc, 0, m.sau - dc, m.y, top)
            self.cac_canh(m, m.tu + dc, m.het - dc, max(m.y, self.c.lenChan), top)

    def ke_goc(self, m: Module):
        dc = self.c.dayCanh
        n = max(1, m.soNgan)
        for tuong, dai in (("sau", m.canhSau), ("phai", m.canhPhai)):
            for i in range(n + 1):
                yb = m.y + i * (m.cao - dc) / n
                self.box(m.ma, "ke", tuong, 0, dai, 0, m.sau, yb, yb + dc)
            self.box(m.ma, "hong", tuong, dai - dc, dai, 0, m.sau, m.y, m.y + m.cao)

    def mat_da(self):
        c = self.c
        for tuong in ("sau", "phai", "trai"):
            ms = sorted((m for m in self.spec.module if m.tuong == tuong and m.tang == "duoi"), key=lambda m: m.tu)
            run: list[list[float]] = []
            for m in ms:
                if run and m.tu <= run[-1][1] + 1:
                    run[-1][1] = max(run[-1][1], m.het)
                    run[-1][2] = max(run[-1][2], m.sau)
                else:
                    run.append([m.tu, m.het, m.sau])
            for s0, s1, sau in run:
                self.box(None, "mat-da", tuong, s0, s1, 0, sau + c.nhoMatDa,
                         c.deMatDa, c.matDa)

    def thiet_bi(self):
        c = self.c
        for tb in self.spec.thietBi:
            k = tb.kich_thuoc_so()
            m = None
            if tb.module:
                try:
                    m = self.spec.tim(tb.module)
                except KeyError:
                    continue
            if tb.loai == "tu-lanh" and m and len(k) >= 3:
                w, h, d = k[:3]
                sc = m.tu + m.rong / 2
                self.box(tb.ma, "tu-lanh", m.tuong, sc - w / 2, sc + w / 2, max(20, m.sau - d), m.sau, 0, min(h, (m.hoc or h)))
            elif tb.loai == "lo" and m and len(k) >= 2:
                w, h = k[:2]
                niche_top = m.y + m.cao - c.dayCanh
                sc = m.tu + m.gocKhuat + (m.rong - m.gocKhuat - m.tamHong) / 2
                hoc = next((t for t in m.matTruoc if t.loai == "hoc"), None)
                y0 = niche_top - (hoc.cao if hoc else h) + 2 * c.dayCanh
                self.box(tb.ma, "lo", m.tuong, sc - w / 2, sc + w / 2, 80, m.sau - 25, y0, y0 + h)
            elif tb.loai == "hut-mui" and m and len(k) >= 2:
                w, h = k[:2]
                sc = m.tu + m.rong / 2
                self.box(tb.ma, "hut-mui", m.tuong, sc - w / 2, sc + w / 2, 0, m.sau, m.y - h, m.y)
            elif tb.loai in ("chau", "bep", "voi") and tb.tuong and tb.tam is not None:
                dmat = c.sauTuDuoi + c.nhoMatDa
                if tb.loai == "voi":
                    h = k[0] if k else 300
                    self.box(tb.ma, "voi", tb.tuong, tb.tam - 20, tb.tam + 20, 40, 80, c.matDa, c.matDa + h)
                elif len(k) >= 2:
                    w, d = k[:2]
                    dc_ = dmat / 2 + 20
                    cao = 4 if tb.loai == "chau" else 6
                    self.box(tb.ma, tb.loai, tb.tuong, tb.tam - w / 2, tb.tam + w / 2, dc_ - d / 2, dc_ + d / 2,
                             c.matDa, c.matDa + cao)

    def phong(self):
        tran = self.c.tran
        self.box(None, "tuong", "sau", -100, self.lsau, -100, 0, 0, tran)
        self.box(None, "tuong", "phai", 0, self.lphai, -100, 0, 0, tran)
        if any(m.tuong == "trai" for m in self.spec.module):
            self.box(None, "tuong", "trai", 0, self.lphai, -100, 0, 0, tran)
        self.parts.append(Part("phong-san-1", None, "san", (-self.lsau - 100, -40, -100), (100, 0, self.lphai + 1500)))

    # ---- tay nắm (kitchen.hardware: cùng quy tắc với bộ xuất three.js)
    def _local(self, p: Part) -> tuple[float, float, float, float, float]:
        """(x0, x1, y0, y1, mặt trước) của cánh trong hệ 'nhìn từ phía trước'."""
        if p.tuong == "phai":
            return p.min[2], p.max[2], p.min[1], p.max[1], p.min[0]
        if p.tuong == "trai":
            return -p.max[2], -p.min[2], p.min[1], p.max[1], p.max[0]
        return p.min[0], p.max[0], p.min[1], p.max[1], p.max[2]

    def tay_nam(self, m: Module):
        from . import hardware
        tier = hardware.TIER[m.tang]
        fronts = [p for p in self.parts if p.module == m.ma and p.loai in ("canh", "canh-kinh", "ngan-keo")]
        doors = [p for p in fronts if p.loai != "ngan-keo"]
        hinge = dict(zip((p.id for p in doors), hardware.hinges(m, [self._local(p)[:4] for p in doors])))
        for p in fronts:
            x0, x1, y0, y1, f = self._local(p)
            hg = hinge.get(p.id)
            hd = hardware.handle(self.c.tayNam, x1 - x0, y1 - y0, tier, hg,
                                 horizontal=p.loai == "ngan-keo" or hg in ("Top", "Bottom"))
            if hd is None:
                continue
            (hw, hh, dd), u0, v0 = hd["size"], x0 + hd["x"], y0 + hd["y"]
            if p.tuong == "phai":
                mn, mx = (f - dd, v0, u0), (f, v0 + hh, u0 + hw)
            elif p.tuong == "trai":
                mn, mx = (f, v0, -(u0 + hw)), (f + dd, v0 + hh, -u0)
            else:
                mn, mx = (u0, v0, f), (u0 + hw, v0 + hh, f + dd)
            key = f"{m.ma}-tay-nam"
            self._n[key] = self._n.get(key, 0) + 1
            self.parts.append(Part(f"{key}-{self._n[key]}", m.ma, "tay-nam", mn, mx, p.tuong, parent=p.id))

    def build(self) -> Scene:
        for m in self.spec.module:
            t = m.tang
            if t == "duoi":
                self.tu_duoi(m)
            elif t in ("tren", "noc"):
                self.tu_tren(m)
            elif t == "cao":
                self.tu_cao(m)
            elif t == "goc":
                self.ke_goc(m)
            if t != "goc":
                self.tay_nam(m)
        self.mat_da()
        self.thiet_bi()
        self.phong()
        from .moldings import meshes as molding_meshes
        return Scene(self.parts, self.lsau, self.lphai, molding_meshes(self.spec) if self.spec.moldings else [])


def compile_spec(spec: KitchenSpec) -> Scene:
    return _Builder(spec).build()


def default_views(spec: KitchenSpec, scene: Scene | None = None) -> dict[str, GocNhin]:
    """Bộ góc nhìn chuẩn khi spec chưa khai báo gocNhin (m)."""
    scene = scene or compile_spec(spec)
    lo, hi = scene.bounds()
    cx, cz = (lo[0] + hi[0]) / 2000, (lo[2] + hi[2]) / 2000
    w, d = (hi[0] - lo[0]) / 1000, (hi[2] - lo[2]) / 1000
    span = max(w, d, 1.5)
    views = {
        "phoi-canh": GocNhin(ten="Phối cảnh chéo", viTri=(cx - span * 0.9, 1.6, cz + span * 0.9), nhinVao=(cx, 1.1, cz), fovDoc=55),
        "tren-cao": GocNhin(ten="Toàn cảnh từ trên", viTri=(cx - span * 0.8, 3.8, cz + span * 0.9), nhinVao=(cx, 0.6, cz), fovDoc=50),
        "mat-bang": GocNhin(ten="Mặt bằng", viTri=(cx, 6.5, cz + 0.001), nhinVao=(cx, 0, cz), fovDoc=36),
    }
    if any(m.tuong == "sau" for m in spec.module):
        xs = [-(m.het) / 1000 for m in spec.module if m.tuong == "sau"] + [0]
        mx = (min(xs) + max(xs)) / 2
        views["tuong-sau"] = GocNhin(ten="Chính diện tường sau", viTri=(mx, 1.35, span * 1.4 + 0.6), nhinVao=(mx, 1.25, 0.2), fovDoc=48)
    if any(m.tuong == "phai" for m in spec.module):
        zs = [m.het / 1000 for m in spec.module if m.tuong == "phai"] + [0]
        mz = (min(zs) + max(zs)) / 2
        views["tuong-phai"] = GocNhin(ten="Chính diện tường phải", viTri=(-(span * 1.4 + 0.6), 1.35, mz), nhinVao=(0, 1.25, mz), fovDoc=48)
    return views


def views_of(spec: KitchenSpec) -> dict[str, GocNhin]:
    return dict(spec.gocNhin) if spec.gocNhin else default_views(spec)


def scene_json(spec: KitchenSpec) -> dict:
    sc = compile_spec(spec)
    lo, hi = sc.bounds()
    return {
        "version": "2.0", "units": "mm",
        "parts": [p.to_json() for p in sc.parts],
        "bounds": {"min": lo, "max": hi},
        "views": {k: v.model_dump(mode="json") for k, v in views_of(spec).items()},
        "modules": [{"ma": m.ma, "ten": m.ten, "loai": m.loai, "tuong": m.tuong} for m in spec.module],
        "moldings": [{"id": m.id, "molding": m.module, "vertices": len(m.vertices), "faces": len(m.faces)} for m in sc.meshes],
    }
