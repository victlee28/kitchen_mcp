"""Compiler: KitchenSpec -> danh sách khối hộp (AABB) trong toạ độ thế giới (mm).

Vì mọi tường đều vuông góc nên mọi chi tiết là hộp thẳng trục; viewer và renderer
chỉ cần (min, max). Mỗi chi tiết mang `module` để chọn/tô mask theo module.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .spec import ViewAngle, KitchenSpec, Module, effective_handle

COLORS = {  # màu hiển thị theo loại chi tiết (viewer 3D, mask ngữ nghĩa)
    "carcass": "#d9c3a0", "plinth": "#5b5348", "door": "#c8a273", "glass-door": "#9fc7d8", "drawer": "#b98f5e",
    "side-panel": "#c19a6b", "shelf": "#a77f55", "countertop": "#f1f0ec", "fridge": "#c9ccd1", "sink": "#2f3236",
    "faucet": "#8a8f96", "cooktop": "#121212", "hood": "#6f747a", "oven": "#3a3d42", "wall": "#ece7de", "floor": "#bdb4a6",
    "molding": "#a87542", "handle": "#2b2b2b", "wall-tile": "#dedbd4",
}


@dataclass
class Part:
    id: str
    module: str | None
    type: str
    min: tuple[float, float, float]
    max: tuple[float, float, float]
    wall: str | None = None  # tường chứa chi tiết (để suy hướng mặt trước khi xuất three.js)
    parent: str | None = None  # chi tiết cha (tay nắm -> cánh/ngăn kéo)

    def to_json(self) -> dict:
        c = [(a + b) / 2 for a, b in zip(self.min, self.max)]
        s = [b - a for a, b in zip(self.min, self.max)]
        return {"id": self.id, "module": self.module, "type": self.type, "center": [round(v, 2) for v in c],
                "size": [round(v, 2) for v in s], "color": COLORS.get(self.type, "#cccccc")}


@dataclass
class Scene:
    parts: list[Part] = field(default_factory=list)
    lsau: float = 0
    lphai: float = 0
    meshes: list = field(default_factory=list)  # lưới tam giác không thẳng trục (phào) — kitchen.moldings.MeshPart

    def bounds(self, cabinets_only: bool = True) -> tuple[list[float], list[float]]:
        ps = [p for p in self.parts if p.type != "handle" and (not cabinets_only or p.type not in ("wall", "floor"))]
        openings = [min(p.min[i] for p in ps) for i in range(3)]
        hi = [max(p.max[i] for p in ps) for i in range(3)]
        return openings, hi


BACKSPLASH_STANDARD = 600.0  # "standard" backsplash height above the countertop (mm)


def backsplash_height(spec: KitchenSpec, wall: str) -> float:
    """Height of the wall backsplash above the countertop on one wall (shared by the 3D geometry and the Three.js export).

    "standard" is a fixed 600 mm; "to-upper" reaches the underside of the lowest upper cabinet on that wall
    (common.upperBottom when the wall has none); "to-ceiling" reaches the ceiling; common.backsplashHeightMm, when set,
    overrides all three.
    """
    c = spec.common
    if c.backsplashHeightMm:
        return float(c.backsplashHeightMm)
    if c.backsplashHeight == "to-ceiling":
        return max(50.0, c.ceiling - c.countertop)
    if c.backsplashHeight != "to-upper":
        return BACKSPLASH_STANDARD
    upper_edge = min((m.y for m in spec.module if m.wall == wall and m.storey == "upper"), default=c.upperBottom)
    return max(50.0, upper_edge - c.countertop)


def _wall_length(spec: KitchenSpec) -> tuple[float, float]:
    def endAt(wall: str) -> float:
        vals = [m.endAt for m in spec.module if m.wall == wall]
        if wall == "back":
            vals += [m.backLength or 0 for m in spec.module if m.type == "corner-shelf"]
        if wall == "right":
            vals += [m.rightLength or 0 for m in spec.module if m.type == "corner-shelf"]
        return max(vals, default=0)
    lsau = (spec.room.length("back") if spec.room else None) or endAt("back") + 600
    lphai = (spec.room.length("right") if spec.room else None) or max(endAt("right"), endAt("left"), *[m.offset + m.depth for m in spec.module if m.wall == "island"], 0) + 600
    return lsau, lphai


class _Builder:
    def __init__(self, spec: KitchenSpec):
        self.spec = spec
        self.c = spec.common
        self.lsau, self.lphai = _wall_length(spec)
        self.parts: list[Part] = []
        self._n: dict[str, int] = {}
        self._isl = {m.id: (m.offset, m.depth) for m in spec.module if m.wall == "island"}  # island / peninsula: (z of the door face, depth)

    # ---- toạ độ tường -> thế giới
    def box(self, module: str | None, type: str, wall: str, s0, s1, d0, d1, y0, y1, isl: tuple[float, float] | None = None):
        if s1 - s0 <= 0.01 or d1 - d0 <= 0.01 or y1 - y0 <= 0.01:
            return
        if wall == "back":
            mn, mx = (-s1, y0, d0), (-s0, y1, d1)
        elif wall == "right":
            mn, mx = (-d1, y0, s0), (-d0, y1, s1)
        elif wall == "left":
            mn, mx = (-self.lsau + d0, y0, s0), (-self.lsau + d1, y1, s1)
        elif wall == "island":  # free-standing run along x; the door face looks towards the back wall (-z), so depth is mirrored
            z0, depth = isl or self._isl[module]
            mn, mx = (-s1, y0, z0 + depth - d1), (-s0, y1, z0 + depth - d0)
        else:
            raise ValueError(wall)
        key = f"{module or 'room'}-{type}"
        self._n[key] = self._n.get(key, 0) + 1
        self.parts.append(Part(f"{key}-{self._n[key]}", module, type, mn, mx, wall))

    def door_widths(self, m: Module, s0, s1, y0, y1, type="door"):
        """Chia dải mặt trước [s0,s1]x[y0,y1] thành cánh theo tỉ lệ m.canh, chừa khe."""
        k, dc = self.c.doorGap, self.c.doorThickness
        ws = m.doors or [s1 - s0]
        total = sum(ws)
        s = s0
        for w in ws:
            w2 = w * (s1 - s0) / total
            self.box(m.id, type, m.wall, s + k / 2, s + w2 - k / 2, m.depth - dc, m.depth, y0 + k / 2, y1 - k / 2)
            s += w2

    # ---- các loại module
    def base(self, m: Module):
        c, dc = self.c, self.c.doorThickness
        top = m.y + m.height
        y_than = max(m.y, c.plinthHeight) if m.y == 0 else m.y
        fs0, fs1 = m.fromCorner + m.blindCorner, m.endAt - m.endPanel
        if m.y == 0:
            self.box(m.id, "plinth", m.wall, m.fromCorner, m.endAt - m.endPanel, 0, m.depth - dc - 50, 0, c.plinthHeight)
        if m.endPanel:
            self.box(m.id, "side-panel", m.wall, m.endAt - m.endPanel, m.endAt, 0, m.depth, 0, top)
        if m.blindCorner:  # phần góc khuất: thân kín, không cánh
            self.box(m.id, "carcass", m.wall, m.fromCorner, fs0, 0, m.depth, y_than, top)
        if not m.frontSections:
            self.box(m.id, "carcass", m.wall, fs0, fs1, 0, m.depth - dc, y_than, top)
            self.door_widths(m, fs0, fs1, y_than, top)
            return
        cur = top
        for i, t in enumerate(m.frontSections):
            y0 = max(y_than, cur - t.height)
            if t.type == "niche":  # hộc trống: vách sau + ván nóc/đáy + hai hông
                self.box(m.id, "carcass", m.wall, fs0, fs1, 0, 60, y0, cur)
                self.box(m.id, "shelf", m.wall, fs0, fs1, 0, m.depth, cur - dc, cur)
                self.box(m.id, "shelf", m.wall, fs0, fs1, 0, m.depth, y0, y0 + dc)
                self.box(m.id, "side-panel", m.wall, fs0, fs0 + dc, 0, m.depth, y0, cur)
                self.box(m.id, "side-panel", m.wall, fs1 - dc, fs1, 0, m.depth, y0, cur)
            else:
                self.box(m.id, "carcass", m.wall, fs0, fs1, 0, m.depth - dc, y0, cur)
                if t.type == "door":
                    self.door_widths(m, fs0, fs1, y0, cur)
                else:
                    self.box(m.id, "drawer", m.wall, fs0 + c.doorGap / 2, fs1 - c.doorGap / 2, m.depth - dc, m.depth,
                             y0 + c.doorGap / 2, cur - c.doorGap / 2)
            cur = y0
        if cur - y_than > 30:  # phần còn lại phía dưới: một ngăn kéo
            self.box(m.id, "carcass", m.wall, fs0, fs1, 0, m.depth - dc, y_than, cur)
            self.box(m.id, "drawer", m.wall, fs0 + c.doorGap / 2, fs1 - c.doorGap / 2, m.depth - dc, m.depth,
                     y_than + c.doorGap / 2, cur - c.doorGap / 2)

    def upper(self, m: Module):
        dc = self.c.doorThickness
        fs0, fs1 = m.fromCorner + m.blindCorner, m.endAt - m.endPanel
        if m.type == "upper-open":  # open shelving: two sides, a thin back and n+1 boards, no doors
            top = m.y + m.height
            self.box(m.id, "side-panel", m.wall, m.fromCorner, m.fromCorner + dc, 0, m.depth, m.y, top)
            self.box(m.id, "side-panel", m.wall, m.endAt - dc, m.endAt, 0, m.depth, m.y, top)
            self.box(m.id, "carcass", m.wall, m.fromCorner + dc, m.endAt - dc, 0, 12, m.y, top)
            n = max(1, m.shelfCount)
            for i in range(n + 1):
                yb = m.y + i * (m.height - dc) / n
                self.box(m.id, "shelf", m.wall, m.fromCorner + dc, m.endAt - dc, 0, m.depth, yb, yb + dc)
            return
        self.box(m.id, "carcass", m.wall, m.fromCorner, m.endAt, 0, m.depth - dc, m.y, m.y + m.height)
        if m.endPanel:
            self.box(m.id, "side-panel", m.wall, fs1, m.endAt, 0, m.depth, m.y, m.y + m.height)
        self.door_widths(m, fs0, fs1, m.y, m.y + m.height, "glass-door" if m.type == "upper-glass" else "door")

    def tall(self, m: Module):
        dc = self.c.doorThickness
        top = m.y + m.height
        self.box(m.id, "side-panel", m.wall, m.fromCorner, m.fromCorner + dc, 0, m.depth, m.y, top)
        self.box(m.id, "side-panel", m.wall, m.endAt - dc, m.endAt, 0, m.depth, m.y, top)
        if m.niche:
            self.box(m.id, "carcass", m.wall, m.fromCorner + dc, m.endAt - dc, 0, m.depth - dc, m.niche, top)
            self.box(m.id, "carcass", m.wall, m.fromCorner + dc, m.endAt - dc, 0, 20, m.y, m.niche)  # vách sau hốc
            self.door_widths(m, m.fromCorner + dc, m.endAt - dc, m.niche, top)
        else:
            self.box(m.id, "carcass", m.wall, m.fromCorner + dc, m.endAt - dc, 0, m.depth - dc, m.y, top)
            self.door_widths(m, m.fromCorner + dc, m.endAt - dc, max(m.y, self.c.plinthHeight), top)

    def corner_shelf(self, m: Module):
        dc = self.c.doorThickness
        n = max(1, m.shelfCount)
        for wall, length in (("back", m.backLength), ("right", m.rightLength)):
            for i in range(n + 1):
                yb = m.y + i * (m.height - dc) / n
                self.box(m.id, "shelf", wall, 0, length, 0, m.depth, yb, yb + dc)
            self.box(m.id, "side-panel", wall, length - dc, length, 0, m.depth, m.y, m.y + m.height)

    def countertop(self):
        c = self.c
        groups = [(w, None) for w in ("back", "right", "left")] + \
                 [("island", z) for z in sorted({m.offset for m in self.spec.module if m.wall == "island" and m.storey == "base"})]
        for wall, z in groups:
            ms = sorted((m for m in self.spec.module if m.wall == wall and m.storey == "base" and (z is None or m.offset == z)), key=lambda m: m.fromCorner)
            run: list[list[float]] = []
            for m in ms:
                if run and m.fromCorner <= run[-1][1] + 1:
                    run[-1][1] = max(run[-1][1], m.endAt)
                    run[-1][2] = max(run[-1][2], m.depth)
                else:
                    run.append([m.fromCorner, m.endAt, m.depth])
            for s0, s1, depth in run:
                self.box(None, "countertop", wall, s0, s1, 0, depth + c.countertopOverhang,
                         c.baseTop, c.countertop, isl=(z, depth) if z is not None else None)
                if c.material.get("wallTile") and wall != "island":  # an island has no wall behind it
                    self.box(None, "wall-tile", wall, s0, s1, 0, 8, c.countertop, c.countertop + backsplash_height(self.spec, wall))

    def appliance(self):
        c = self.c
        for tb in self.spec.appliances:
            k = tb.numeric_dimensions()
            m = None
            if tb.module:
                try:
                    m = self.spec.find(tb.module)
                except KeyError:
                    continue
            if tb.type == "fridge" and m and len(k) >= 3:
                w, h, d = k[:3]
                sc = m.fromCorner + m.width / 2
                self.box(tb.id, "fridge", m.wall, sc - w / 2, sc + w / 2, max(20, m.depth - d), m.depth, 0, min(h, (m.niche or h)))
            elif tb.type == "oven" and m and len(k) >= 2:
                w, h = k[:2]
                niche_top = m.y + m.height - c.doorThickness
                sc = m.fromCorner + m.blindCorner + (m.width - m.blindCorner - m.endPanel) / 2
                niche = next((t for t in m.frontSections if t.type == "niche"), None)
                y0 = niche_top - (niche.height if niche else h) + 2 * c.doorThickness
                self.box(tb.id, "oven", m.wall, sc - w / 2, sc + w / 2, 80, m.depth - 25, y0, y0 + h)
            elif tb.type == "hood" and m and len(k) >= 2:
                w, h = k[:2]
                sc = m.fromCorner + m.width / 2
                self.box(tb.id, "hood", m.wall, sc - w / 2, sc + w / 2, 0, m.depth, m.y - h, m.y)
            elif tb.type in ("sink", "cooktop", "faucet") and tb.wall and tb.center is not None:
                dmat = c.baseDepth + c.countertopOverhang
                if tb.type == "faucet":
                    h = k[0] if k else 300
                    self.box(tb.id, "faucet", tb.wall, tb.center - 20, tb.center + 20, 40, 80, c.countertop, c.countertop + h)
                elif len(k) >= 2:
                    w, d = k[:2]
                    dc_ = dmat / 2 + 20
                    height = 4 if tb.type == "sink" else 6
                    self.box(tb.id, tb.type, tb.wall, tb.center - w / 2, tb.center + w / 2, dc_ - d / 2, dc_ + d / 2,
                             c.countertop, c.countertop + height)

    def room(self):
        ceiling = self.c.ceiling
        self.box(None, "wall", "back", -100, self.lsau, -100, 0, 0, ceiling)
        self.box(None, "wall", "right", 0, self.lphai, -100, 0, 0, ceiling)
        if any(m.wall == "left" for m in self.spec.module):
            self.box(None, "wall", "left", 0, self.lphai, -100, 0, 0, ceiling)
        self.parts.append(Part("room-floor-1", None, "floor", (-self.lsau - 100, -40, -100), (100, 0, self.lphai + 1500)))

    # ---- tay nắm (kitchen.hardware: cùng quy tắc với bộ xuất three.js)
    def _local(self, p: Part) -> tuple[float, float, float, float, float]:
        """(x0, x1, y0, y1, mặt trước) của cánh trong hệ 'nhìn từ phía trước'."""
        if p.wall == "right":
            return p.min[2], p.max[2], p.min[1], p.max[1], p.min[0]
        if p.wall == "left":
            return -p.max[2], -p.min[2], p.min[1], p.max[1], p.max[0]
        if p.wall == "island":
            return -p.max[0], -p.min[0], p.min[1], p.max[1], p.min[2]
        return p.min[0], p.max[0], p.min[1], p.max[1], p.max[2]

    def handle(self, m: Module):
        from . import hardware
        tier = hardware.TIER[m.storey]
        fronts = [p for p in self.parts if p.module == m.id and p.type in ("door", "glass-door", "drawer")]
        doors = [p for p in fronts if p.type != "drawer"]
        hinge = dict(zip((p.id for p in doors), hardware.hinges(m, [self._local(p)[:4] for p in doors])))
        for p in fronts:
            x0, x1, y0, y1, f = self._local(p)
            hg = hinge.get(p.id)
            hd = hardware.handle(effective_handle(self.c, m), x1 - x0, y1 - y0, tier, hg,
                                 horizontal=p.type == "drawer" or hg in ("Top", "Bottom"))
            if hd is None:
                continue
            (hw, hh, dd), u0, v0 = hd["size"], x0 + hd["x"], y0 + hd["y"]
            if p.wall == "right":
                mn, mx = (f - dd, v0, u0), (f, v0 + hh, u0 + hw)
            elif p.wall == "left":
                mn, mx = (f, v0, -(u0 + hw)), (f + dd, v0 + hh, -u0)
            elif p.wall == "island":
                mn, mx = (-(u0 + hw), v0, f - dd), (-u0, v0 + hh, f)
            else:
                mn, mx = (u0, v0, f), (u0 + hw, v0 + hh, f + dd)
            key = f"{m.id}-handle"
            self._n[key] = self._n.get(key, 0) + 1
            self.parts.append(Part(f"{key}-{self._n[key]}", m.id, "handle", mn, mx, p.wall, parent=p.id))

    def build(self) -> Scene:
        for m in self.spec.module:
            t = m.storey
            if t == "base":
                self.base(m)
            elif t in ("upper", "loft"):
                self.upper(m)
            elif t == "tall":
                self.tall(m)
            elif t == "corner":
                self.corner_shelf(m)
            if t != "corner":
                self.handle(m)
        self.countertop()
        self.appliance()
        self.room()
        from .moldings import meshes as molding_meshes
        return Scene(self.parts, self.lsau, self.lphai, molding_meshes(self.spec) if self.spec.moldings else [])


def compile_spec(spec: KitchenSpec) -> Scene:
    return _Builder(spec).build()


def default_views(spec: KitchenSpec, scene: Scene | None = None) -> dict[str, ViewAngle]:
    """Bộ góc nhìn chuẩn khi spec chưa khai báo gocNhin (m)."""
    scene = scene or compile_spec(spec)
    openings, hi = scene.bounds()
    cx, cz = (openings[0] + hi[0]) / 2000, (openings[2] + hi[2]) / 2000
    w, d = (hi[0] - openings[0]) / 1000, (hi[2] - openings[2]) / 1000
    span = max(w, d, 1.5)
    views = {
        "perspective": ViewAngle(name="Phối cảnh chéo", position=(cx - span * 0.9, 1.6, cz + span * 0.9), lookAt=(cx, 1.1, cz), verticalFov=55),
        "overhead": ViewAngle(name="Toàn cảnh từ trên", position=(cx - span * 0.8, 3.8, cz + span * 0.9), lookAt=(cx, 0.6, cz), verticalFov=50),
        "plan": ViewAngle(name="Mặt bằng", position=(cx, 6.5, cz + 0.001), lookAt=(cx, 0, cz), verticalFov=36),
    }
    if any(m.wall == "left" for m in spec.module):  # chữ U: ba mặt kín, máy ảnh phải đứng ở phía hở (z lớn) mới nhìn thấy cả ba dãy
        zfront = hi[2] / 1000
        views["perspective"] = ViewAngle(name="Phối cảnh chéo", position=(cx + w * 0.3, 1.6, zfront + span * 0.55), lookAt=(cx, 1.0, cz * 0.8), verticalFov=70)
        views["overhead"] = ViewAngle(name="Toàn cảnh từ trên", position=(cx, 3.8, zfront + span * 0.35), lookAt=(cx, 0.6, cz * 0.8), verticalFov=70)
    if any(m.wall == "back" for m in spec.module):
        xs = [-(m.endAt) / 1000 for m in spec.module if m.wall == "back"] + [0]
        mx = (min(xs) + max(xs)) / 2
        views["back-wall"] = ViewAngle(name="Chính diện tường sau", position=(mx, 1.35, span * 1.4 + 0.6), lookAt=(mx, 1.25, 0.2), verticalFov=48)
    if any(m.wall == "right" for m in spec.module):
        zs = [m.endAt / 1000 for m in spec.module if m.wall == "right"] + [0]
        mz = (min(zs) + max(zs)) / 2
        views["right-wall"] = ViewAngle(name="Chính diện tường phải", position=(-(span * 1.4 + 0.6), 1.35, mz), lookAt=(0, 1.25, mz), verticalFov=48)
    if any(m.wall == "left" for m in spec.module):
        zs = [m.endAt / 1000 for m in spec.module if m.wall == "left"] + [0]
        mz = (min(zs) + max(zs)) / 2
        views["left-wall"] = ViewAngle(name="Chính diện tường trái", position=(-scene.lsau / 1000 + span * 1.4 + 0.6, 1.35, mz), lookAt=(-scene.lsau / 1000, 1.25, mz), verticalFov=48)
    return views


def views_of(spec: KitchenSpec) -> dict[str, ViewAngle]:
    return dict(spec.cameraViews) if spec.cameraViews else default_views(spec)


def scene_json(spec: KitchenSpec) -> dict:
    sc = compile_spec(spec)
    openings, hi = sc.bounds()
    return {
        "version": "2.0", "units": "mm",
        "parts": [p.to_json() for p in sc.parts],
        "bounds": {"min": openings, "max": hi},
        "views": {k: v.model_dump(mode="json") for k, v in views_of(spec).items()},
        "modules": [{"id": m.id, "name": m.name, "type": m.type, "wall": m.wall} for m in spec.module],
        "moldings": [{"id": m.id, "molding": m.module, "vertices": len(m.vertices), "faces": len(m.faces)} for m in sc.meshes],
    }
