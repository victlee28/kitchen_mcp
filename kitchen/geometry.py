"""Compiler: KitchenSpec -> danh sách khối hộp (AABB) trong toạ độ thế giới (mm).

Vì mọi tường đều vuông góc nên mọi chi tiết là hộp thẳng trục; viewer và renderer
chỉ cần (min, max). Mỗi chi tiết mang `module` để chọn/tô mask theo module.
"""
from __future__ import annotations

from typing import Any

from dataclasses import dataclass, field

from .numeric import round_half_away
from . import camera_plan, roomctx, runs as runmod, structure_mesh, tv_system
from .spec import ViewAngle, KitchenSpec, Module, effective_handle, to_data
from .errors import InvalidInput, require

COLORS = {  # màu hiển thị theo loại chi tiết (viewer 3D, mask ngữ nghĩa)
    "carcass": "#d9c3a0", "plinth": "#5b5348", "door": "#c8a273", "glass-door": "#9fc7d8", "drawer": "#b98f5e",
    "side-panel": "#c19a6b", "shelf": "#a77f55", "countertop": "#f1f0ec", "fridge": "#c9ccd1", "sink": "#2f3236",
    "faucet": "#8a8f96", "cooktop": "#121212", "tv": "#0b0d10", "hood": "#6f747a", "oven": "#3a3d42", "wall": "#ece7de", "floor": "#bdb4a6",
    "molding": "#a87542", "handle": "#2b2b2b", "wall-tile": "#dedbd4",
    "structure-wall": "#E7E2D5", "structure-column": "#F2B65D", "structure-opening": "#55C6A9", "structure-furniture": "#D38662",
    "structure-shaft": "#8C83D6", "structure-stair": "#CFAE52", "structure-area": "#7D9EAA", "structure-swing": "#9AD9C6",  # = floorplan.STRUCTURE_COLORS
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
    face: str | None = None  # hướng mặt trước (back/right/left/island) khi khác tường: dãy tự do quay ra một trong bốn hướng
    frame: tuple[float, float, float] | None = None  # explicit run at any angle: (x, z, yaw) of the run origin; min / max are then the world AABB of the box
    lmin: tuple[float, float, float] | None = None   # with frame: the box in run coordinates (s, y, d)
    lmax: tuple[float, float, float] | None = None
    run: str | None = None

    @property
    def run_frame(self) -> "runmod.RunFrame | None":
        return runmod.RunFrame(self.run or "", *self.frame) if self.frame is not None else None

    def corners(self) -> list[tuple[float, float, float]]:
        """8 world corners, bit 0 = x (s), bit 1 = y, bit 2 = z (d); oriented parts follow their run frame."""
        fr = self.run_frame
        if fr is not None and self.lmin is not None and self.lmax is not None:
            return fr.corners(self.lmin, self.lmax)
        return [(self.max[0] if i & 1 else self.min[0], self.max[1] if i & 2 else self.min[1], self.max[2] if i & 4 else self.min[2]) for i in range(8)]

    @property
    def orient(self) -> str:
        return "back" if self.frame is not None else (self.face or self.wall or "back")

    def to_json(self) -> dict[str, Any]:
        c = [(a + b) / 2 for a, b in zip(self.min, self.max)]
        s = [b - a for a, b in zip(self.min, self.max)]
        if self.frame is not None and self.lmin is not None and self.lmax is not None:  # oriented: centre of the real box, size in run axes, yaw
            fr = self.run_frame
            assert fr is not None
            cx, cz = fr.to_world((self.lmin[0] + self.lmax[0]) / 2, (self.lmin[2] + self.lmax[2]) / 2)
            c = [cx, c[1], cz]
            s = [self.lmax[0] - self.lmin[0], self.lmax[1] - self.lmin[1], self.lmax[2] - self.lmin[2]]
            return {"id": self.id, "module": self.module, "type": self.type, "center": [round_half_away(v, 2) for v in c],
                    "size": [round_half_away(v, 2) for v in s], "color": COLORS.get(self.type, "#cccccc"), "yaw": round_half_away(self.frame[2], 4)}
        return {"id": self.id, "module": self.module, "type": self.type, "center": [round_half_away(v, 2) for v in c],
                "size": [round_half_away(v, 2) for v in s], "color": COLORS.get(self.type, "#cccccc")}


@dataclass
class Scene:
    parts: list[Part] = field(default_factory=list[Part])
    lsau: float = 0
    lphai: float = 0
    meshes: list[Any] = field(default_factory=list[Any])  # lưới tam giác không thẳng trục (phào) — kitchen.moldings.MeshPart

    def bounds(self, cabinets_only: bool = True) -> tuple[list[float], list[float]]:
        ps = [p for p in self.parts if p.type != "handle" and (not cabinets_only or p.type not in ("wall", "floor"))]
        if not ps:  # room-only design (imported floorplan, no cabinets yet)
            return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        openings = [min(p.min[i] for p in ps) for i in range(3)]
        hi = [max(p.max[i] for p in ps) for i in range(3)]
        return openings, hi


HOOD_GAP_MM = 650.0             # worktop to the canopy of a hood hanging over the hob (mm)
HOOD_CANOPY_MM = 150.0          # height of that canopy
CHIMNEY_MM = (300.0, 250.0)     # width, depth of its chimney
BACKSPLASH_STANDARD = 600.0  # "standard" backsplash height above the countertop (mm)


def backsplash_height(spec: KitchenSpec, wall: str, run: str | None = None) -> float:
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
    upper_edge = min((m.y for m in spec.module if m.wall == wall and (m.run or None) == run and m.storey == "upper"), default=c.upperBottom)   # of that row only
    return max(50.0, upper_edge - c.countertop)


def _wall_length(spec: KitchenSpec) -> tuple[float, float]:
    def endAt(wall: str) -> float:
        vals = [m.endAt for m in spec.module if m.wall == wall]
        if wall == "back":
            vals += [m.backLength or 0 for m in spec.module if m.type == "corner-shelf" and not m.run]
        if wall == "right":
            vals += [m.rightLength or 0 for m in spec.module if m.type == "corner-shelf" and not m.run]
        return max(vals, default=0)
    reach_x, reach_z = _run_reach(spec)
    lsau = (spec.room.length("back") if spec.room else None) or max(endAt("back") + 600, reach_x)
    lphai = (spec.room.length("right") if spec.room else None) or max(endAt("right"), endAt("left"), reach_z, *[m.offset + m.depth for m in spec.module if m.wall == "island" and not m.run and (m.facing or "-z") in ("-z", "+z")], 0) + 600
    return lsau, lphai


def _run_reach(spec: KitchenSpec) -> tuple[float, float]:
    """How far the explicit runs reach along the back wall (-x) and into the room (+z), so a kitchen made only of runs still gets walls and a
    floor that hold it. (0, 0) with an imported floor plan: there the room is the plan's, and the walls' lengths anchor the kitchen in it."""
    if isinstance(getattr(spec, "floorplan", None), dict):
        return 0.0, 0.0
    pts = [p for m in spec.module if (fr := runmod.frame_of(spec, m)) is not None for p in fr.footprint(m.fromCorner, m.endAt, 0.0, m.depth)]
    return max((-x for x, _ in pts), default=0.0), max((z for _, z in pts), default=0.0)


def run_wall(fr: "runmod.RunFrame", lsau: float) -> str | None:
    return runmod.run_wall(fr, lsau)


def wall_reach(spec: KitchenSpec, lsau: float) -> dict[str, float]:
    """How far the cabinets reach along each wall that has any, measured from the back corner as the walls are (mm): the cabinets that follow the
    wall and those of explicit runs standing against it."""
    out: dict[str, float] = {}
    for m in spec.module:
        if m.wall in ("back", "right", "left"):
            out[m.wall] = max(out.get(m.wall, 0.0), m.endAt)
    for m in spec.module:
        fr = runmod.frame_of(spec, m)
        wall = run_wall(fr, lsau) if fr is not None else None
        if fr is None or wall is None:
            continue
        pts = fr.footprint(m.fromCorner, m.endAt, 0.0, m.depth)
        out[wall] = max(out.get(wall, 0.0), max(-x for x, _ in pts) if wall == "back" else max(z for _, z in pts))
    return out


class _Builder:
    def __init__(self, spec: KitchenSpec):
        self.spec = spec
        self.c = spec.common
        self.lsau, self.lphai = _wall_length(spec)
        self.parts: list[Part] = []
        self._n: dict[str, int] = {}
        self._isl = {m.id: (m.offset, m.depth, m.facing or "-z") for m in spec.module if m.wall == "island" and not m.run}  # free run: (door face position, depth, facing)
        self._run = {m.id: fr for m in spec.module if (fr := runmod.frame_of(spec, m)) is not None}
        self._joints = runmod.corner_joints(spec)   # explicit run frames by module (or appliance) id

    # ---- row coordinates (s, d) -> world
    def seat(self, wall: str, module: str | None = None, isl: tuple[float, float, str] | None = None) -> "runmod.Seat":
        """The seat of an axis-aligned row: a wall's, or a legacy free run's (``isl`` = (door face position, depth, facing), else that of ``module``)."""
        if wall == "island":
            return runmod.free_seat(*(isl or self._isl[require(module, "island part module")]))
        seat = runmod.wall_seat(wall, self.lsau)
        if seat is None:
            raise InvalidInput(wall)
        return seat

    def box(self, module: str | None, type: str, wall: str, s0, s1, d0, d1, y0, y1, isl: tuple[float, float, str] | None = None, fr: "runmod.RunFrame | None" = None):
        if s1 - s0 <= 0.01 or d1 - d0 <= 0.01 or y1 - y0 <= 0.01:
            return
        fr = fr or self._run.get(module or "")
        if fr is not None:                     # explicit run at any angle: keep the local box, store its world AABB
            lmn, lmx = (s0, y0, d0), (s1, y1, d1)
            pts = fr.footprint(s0, s1, d0, d1)
            (ax, az), (bx, bz) = runmod.aabb(pts)
            key = f"{module or 'room'}-{type}"
            self._n[key] = self._n.get(key, 0) + 1
            self.parts.append(Part(f"{key}-{self._n[key]}", module, type, (ax, y0, az), (bx, y1, bz), wall, frame=(fr.x, fr.z, fr.yaw), lmin=lmn, lmax=lmx, run=fr.id))
            return
        seat = self.seat(wall, module, isl)
        mn, mx = seat.box(s0, s1, d0, d1, y0, y1)
        face = seat.front if wall == "island" else None
        key = f"{module or 'room'}-{type}"
        self._n[key] = self._n.get(key, 0) + 1
        self.parts.append(Part(f"{key}-{self._n[key]}", module, type, mn, mx, wall, face=face if wall == "island" else None))

    def wall_behind(self, fr: "runmod.RunFrame") -> str | None:
        return run_wall(fr, self.lsau)

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
        fs0, fs1 = m.fronts
        (p0, p1), (b0, b1) = m.panel_span, m.blind_span
        if m.y == 0:
            self.box(m.id, "plinth", m.wall, min(fs0, b0), max(fs1, b1), 0, m.depth - dc - 50, 0, c.plinthHeight)      # under all but the end panel
        if m.endPanel:
            self.box(m.id, "side-panel", m.wall, p0, p1, 0, m.depth, 0, top)
        if m.blindCorner:  # phần góc khuất: thân kín, không cánh
            self.box(m.id, "carcass", m.wall, b0, b1, 0, m.depth, y_than, top)
        if not m.frontSections:
            self.box(m.id, "carcass", m.wall, fs0, fs1, 0, m.depth - dc, y_than, top)
            self.door_widths(m, fs0, fs1, y_than, top)
            self._back_panel(m)
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
        self._back_panel(m)
        if cur - y_than > 30:  # phần còn lại phía dưới: một ngăn kéo
            self.box(m.id, "carcass", m.wall, fs0, fs1, 0, m.depth - dc, y_than, cur)
            self.box(m.id, "drawer", m.wall, fs0 + c.doorGap / 2, fs1 - c.doorGap / 2, m.depth - dc, m.depth,
                     y_than + c.doorGap / 2, cur - c.doorGap / 2)

    def _back_panel(self, m: Module) -> None:
        """A TV unit's panel on the wall behind the TV (``Module.backPanel``: s0 / s1 along the run from the cabinet's start, y0 / y1)."""
        bp = m.backPanel
        if bp is not None and bp.s1 > bp.s0 and bp.y1 > bp.y0:
            self.box(m.id, "side-panel", m.wall, m.fromCorner + bp.s0, m.fromCorner + bp.s1, 0, tv_system.PANEL_THICKNESS_MM, bp.y0, bp.y1)

    def upper(self, m: Module):
        dc = self.c.doorThickness
        fs0, fs1 = m.fronts
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
            self.box(m.id, "side-panel", m.wall, *m.panel_span, 0, m.depth, m.y, m.y + m.height)
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
        """Open shelves round an inside corner: two legs, each with its boards and a side panel at the end away from the corner. On the walls
        the legs lie along the back and the right wall from their corner; by runs, the first leg is the cabinet's own place at the end of its
        run and the second lies at the start of the run it turns into."""
        dc = self.c.doorThickness
        n = max(1, m.shelfCount)
        legs: list[tuple[str, float, float, bool, "runmod.RunFrame | None"]] = []     # (wall, s0, s1, panel at the low end, run frame)
        if m.run:
            other = runmod.frames(self.spec).get(m.turnsInto or "")
            legs.append(("island", m.fromCorner, m.endAt, True, self._run.get(m.id)))
            if other is not None:
                legs.append(("island", 0.0, require(m.rightLength, f"{m.id}.rightLength"), False, other))
        else:
            legs = [("back", 0, require(m.backLength, f"{m.id}.backLength"), False, None), ("right", 0, require(m.rightLength, f"{m.id}.rightLength"), False, None)]
        for wall, s0, s1, low, fr in legs:
            for i in range(n + 1):
                yb = m.y + i * (m.height - dc) / n
                self.box(m.id, "shelf", wall, s0, s1, 0, m.depth, yb, yb + dc, fr=fr)
            if low:
                self.box(m.id, "side-panel", wall, s0, s0 + dc, 0, m.depth, m.y, m.y + m.height, fr=fr)
            else:
                self.box(m.id, "side-panel", wall, s1 - dc, s1, 0, m.depth, m.y, m.y + m.height, fr=fr)

    def countertop(self):
        c = self.c
        groups: list[tuple[str, tuple[float, str] | str | None]] = [(w, None) for w in ("back", "right", "left")]
        for key in sorted({(m.offset, m.facing or "-z") for m in self.spec.module if m.wall == "island" and not m.run and m.storey == "base"}):
            groups.append(("island", key))
        for r in self.spec.runs:
            if tv_system.is_tv_run(r):      # a TV unit: its console has its own top, no worktop and no wall tile
                continue
            if any(m.run == r.id and m.storey == "base" for m in self.spec.module):
                groups.append(("island", r.id))
        for wall, z in groups:
            if isinstance(z, str):          # an explicit run: one countertop per continuous stretch, in the run frame
                ms = sorted((m for m in self.spec.module if m.run == z and m.storey == "base"), key=lambda m: m.fromCorner)
            else:
                ms = sorted((m for m in self.spec.module if m.wall == wall and not m.run and m.storey == "base" and (z is None or (m.offset, m.facing or "-z") == z)), key=lambda m: m.fromCorner)
            run: list[list[float]] = []
            for m in ms:
                if run and m.fromCorner <= run[-1][1] + 1:
                    run[-1][1] = max(run[-1][1], m.endAt)
                    run[-1][2] = max(run[-1][2], m.depth)
                else:
                    run.append([m.fromCorner, m.endAt, m.depth])
            if isinstance(z, str) and run:
                self._close_corner(z, run)
            for s0, s1, depth in run:
                if isinstance(z, str):
                    fr = self._run[ms[0].id]
                    self.box(None, "countertop", wall, s0, s1, 0, depth + c.countertopOverhang, c.baseTop, c.countertop, fr=fr)
                    if c.material.get("wallTile") and self.wall_behind(fr):     # a run standing against a wall of the room is tiled like a wall row
                        self.box(None, "wall-tile", wall, s0, s1, 0, 8, c.countertop, c.countertop + backsplash_height(self.spec, wall, fr.id), fr=fr)
                    continue
                self.box(None, "countertop", wall, s0, s1, 0, depth + c.countertopOverhang,
                         c.baseTop, c.countertop, isl=(z[0], depth, z[1]) if z is not None else None)
                if c.material.get("wallTile") and wall != "island":  # an island has no wall behind it
                    self.box(None, "wall-tile", wall, s0, s1, 0, 8, c.countertop, c.countertop + backsplash_height(self.spec, wall))

    def _close_corner(self, run_id: str, stretches: list[list[float]]) -> None:
        """Where this run ends in an inside corner with another run (``runs.corner_joints``) and neither run's cabinets fill the corner, the
        worktop of this run carries on to the corner, so the two worktops meet instead of leaving a square hole."""
        c = self.c
        for joint in self._joints:
            if joint.a != run_id or not joint.square:        # a corner that is not square is closed by a wedge (``corner_tops``)
                continue
            other = sorted((m for m in self.spec.module if m.run == joint.b and m.storey == "base"), key=lambda m: m.fromCorner)
            last = stretches[-1]
            if not other or last[1] >= joint.at - 1:
                continue
            reach = max(m.depth for m in other) + c.countertopOverhang          # how far the other run's worktop covers, measured back from the corner
            if joint.at - last[1] <= reach + 1 and 1 < other[0].fromCorner <= last[2] + c.countertopOverhang + 1:    # b starting AT the corner fills it itself
                last[1] = joint.at

    def corner_tops(self) -> list[Any]:
        """The wedge of worktop that closes a corner which is NOT square between two explicit runs: from the end of a's worktop, round the point
        where the two front edges cross, to the start of b's worktop. A box cannot be that shape, so it is a mesh (as the moldings are)."""
        from .moldings import MeshPart
        c = self.c
        out: list[Any] = []
        for joint in self._joints:
            if joint.square:
                continue
            a = sorted((m for m in self.spec.module if m.run == joint.a and m.storey == "base"), key=lambda m: m.endAt)
            b = sorted((m for m in self.spec.module if m.run == joint.b and m.storey == "base"), key=lambda m: m.fromCorner)
            if not a or not b:
                continue
            fa, fb = self._run[a[-1].id], self._run[b[0].id]
            end, start = a[-1].endAt, b[0].fromCorner
            da, db = a[-1].depth + c.countertopOverhang, b[0].depth + c.countertopOverhang
            cross = runmod.front_cross(fa, da, fb, db)
            if cross is None or end > cross[0] + 1 or start < cross[1] - 1:       # the two worktops already run into each other
                continue
            poly = [fa.to_world(end, 0.0), fa.to_world(end, da), cross[2], fb.to_world(start, db), fb.to_world(start, 0.0), fb.to_world(0.0, 0.0)]
            poly = [p for k, p in enumerate(poly) if all(abs(p[0] - q[0]) + abs(p[1] - q[1]) > 0.5 for q in poly[:k])]
            if len(poly) < 3:
                continue
            verts, faces = structure_mesh.prism(poly, c.baseTop, c.countertop)
            out.append(MeshPart(f"room-countertop-corner-{len(out) + 1}", f"countertop-{joint.a}-{joint.b}", "countertop", verts, faces))
        return out

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
            if m is not None and m.run:
                self._run[tb.id] = self._run[m.id]       # an appliance stands in the run of its module
            if tb.type == "fridge" and m and len(k) >= 3 and not m.niche and tb.mount == "built_in":
                continue                                   # an integrated fridge: hidden behind the tall cabinet's doors
            if tb.type == "fridge" and m and len(k) >= 3:
                w, h, d = k[:3]
                sc = m.fromCorner + m.width / 2
                self.box(tb.id, "fridge", m.wall, sc - w / 2, sc + w / 2, max(20, m.depth - d), m.depth, 0, min(h, (m.niche or h)))
            elif tb.type == "oven" and m and len(k) >= 2:
                w, h = k[:2]
                niche_top = m.y + m.height - c.doorThickness
                sc = m.fronts[0] + (m.width - m.blindCorner - m.endPanel) / 2
                niche = next((t for t in m.frontSections if t.type == "niche"), None)
                y0 = niche_top - (niche.height if niche else h) + 2 * c.doorThickness
                self.box(tb.id, "oven", m.wall, sc - w / 2, sc + w / 2, 80, m.depth - 25, y0, y0 + h)
            elif tb.type == "hood" and m and len(k) >= 2 and m.storey == "base":     # hanging over the hob: canopy + chimney (appliance_kind)
                w = k[0]
                sc = m.fromCorner + m.width / 2
                d = float((tb.size or {}).get("d") or 480.0)
                island = "island" in (tb.model or "")
                d0 = (m.depth - d) / 2 if island else 0.0                  # an island hood hangs over the middle of the worktop
                y0 = c.countertop + HOOD_GAP_MM
                self.box(tb.id, "hood", m.wall, sc - w / 2, sc + w / 2, d0, d0 + d, y0, y0 + HOOD_CANOPY_MM)
                top = c.ceiling if island else max(c.cabinetTop, y0 + HOOD_CANOPY_MM + 100)
                cd0 = d0 + (d - CHIMNEY_MM[1]) / 2 if island else 0.0
                self.box(tb.id, "hood", m.wall, sc - CHIMNEY_MM[0] / 2, sc + CHIMNEY_MM[0] / 2, cd0, cd0 + CHIMNEY_MM[1], y0 + HOOD_CANOPY_MM, top)
            elif tb.type == "hood" and m and len(k) >= 2:
                w, h = k[:2]
                sc = m.fromCorner + m.width / 2
                self.box(tb.id, "hood", m.wall, sc - w / 2, sc + w / 2, 0, m.depth, m.y - h, m.y)
            elif tb.type == "tv" and m and len(k) >= 2:      # a flat TV on the wall above its console, ``center`` from the start of that cabinet
                w, h = k[:2]
                sc = m.fromCorner + (tb.center if tb.center is not None else m.width / 2)      # a TV's centre is measured from its cabinet
                d = k[2] if len(k) >= 3 else tv_system.TV_DEPTH_MM
                y0 = max(m.y + m.height + 100.0, tv_system.TV_CENTER_MM - h / 2)
                d0 = tv_system.PANEL_THICKNESS_MM + 2      # in front of the panel behind it, if any
                self.box(tb.id, "tv", m.wall, sc - w / 2, sc + w / 2, d0, d0 + d, y0, y0 + h)
            elif tb.type in ("sink", "cooktop", "faucet") and (at := runmod.spot(self.spec, tb)) is not None:
                host = m if tb.wall is None else None                      # placed by its module: it stands in that module's row
                wall = tb.wall or (host.wall if host else "back")
                isl = self._isl.get(host.id) if host is not None else None
                dmat = c.baseDepth + c.countertopOverhang
                if tb.type == "faucet":
                    h = k[0] if k else 300
                    self.box(tb.id, "faucet", wall, at.center - 20, at.center + 20, 40, 80, c.countertop, c.countertop + h, isl=isl)
                elif len(k) >= 2:
                    w, d = k[:2]
                    dc_ = dmat / 2 + 20
                    height = 4 if tb.type == "sink" else 6
                    self.box(tb.id, tb.type, wall, at.center - w / 2, at.center + w / 2, dc_ - d / 2, dc_ + d / 2,
                             c.countertop, c.countertop + height, isl=isl)

    def structures(self) -> list[Any]:
        """Meshes of the imported floorplan's elements in the kitchen frame (none without a floorplan or when the kitchen fits no wall)."""
        try:
            ctx = roomctx.for_spec(self.spec, self.lsau, self.lphai)
        except ValueError:
            return []
        return structure_mesh.meshes(ctx.structures, ctx.placement.to_kitchen) if ctx else []

    def room(self):
        ceiling = self.c.ceiling
        if not isinstance(getattr(self.spec, "floorplan", None), dict):  # an imported plan brings its own (real) walls
            self.box(None, "wall", "back", -100, self.lsau, -100, 0, 0, ceiling)
            self.box(None, "wall", "right", 0, self.lphai, -100, 0, 0, ceiling)
            if any(m.wall == "left" for m in self.spec.module) or any(self.wall_behind(fr) == "left" for fr in runmod.frames(self.spec).values()):
                self.box(None, "wall", "left", 0, self.lphai, -100, 0, 0, ceiling)
        self.parts.append(Part("room-floor-1", None, "floor", (-self.lsau - 100, -40, -100), (100, 0, self.lphai + 1500)))

    # ---- tay nắm (kitchen.hardware: cùng quy tắc với bộ xuất three.js)
    def _local(self, p: Part) -> tuple[float, float, float, float, float]:
        """(x0, x1, y0, y1, mặt trước) của cánh trong hệ 'nhìn từ phía trước'."""
        if p.frame is not None and p.lmin is not None and p.lmax is not None:
            return p.lmin[0], p.lmax[0], p.lmin[1], p.lmax[1], p.lmax[2]
        u0, u1, f = runmod.front_span(p.orient, p.min, p.max)
        return u0, u1, p.min[1], p.max[1], f

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
            if p.frame is not None:           # run coordinates: the handle is a box in the same frame
                fr = p.run_frame
                assert fr is not None
                lmn, lmx = (u0, v0, f), (u0 + hw, v0 + hh, f + dd)
                (ax, az), (bx, bz) = runmod.aabb(fr.footprint(lmn[0], lmx[0], lmn[2], lmx[2]))
                key = f"{m.id}-handle"
                self._n[key] = self._n.get(key, 0) + 1
                self.parts.append(Part(f"{key}-{self._n[key]}", m.id, "handle", (ax, v0, az), (bx, v0 + hh, bz), p.wall, parent=p.id,
                                       frame=p.frame, lmin=lmn, lmax=lmx, run=p.run))
                continue
            mn, mx = runmod.front_box(p.orient, u0, u0 + hw, v0, v0 + hh, f, dd)
            key = f"{m.id}-handle"
            self._n[key] = self._n.get(key, 0) + 1
            self.parts.append(Part(f"{key}-{self._n[key]}", m.id, "handle", mn, mx, p.wall, parent=p.id, face=p.face))

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
        meshes = molding_meshes(self.spec) if self.spec.moldings else []
        return Scene(self.parts, self.lsau, self.lphai, meshes + self.corner_tops() + self.structures())


def compile_spec(spec: KitchenSpec) -> Scene:
    return _Builder(spec).build()


def cabinet_faces(spec: KitchenSpec, scene: Scene) -> list[camera_plan.Face]:
    """The front of every run of cabinets (wall runs and explicit runs) in the kitchen frame, for the camera planner."""
    faces: list[camera_plan.Face] = []

    def face(key: str, name: str, mods: list[Any], center, normal, owner: str) -> None:
        lo, hi = min(m.fromCorner for m in mods), max(m.endAt for m in mods)
        faces.append(camera_plan.Face(key, name, center(lo, hi, max(m.depth for m in mods)), normal, hi - lo, max(m.y + m.height for m in mods), owner))

    for wall, name in (("back", "Chính diện tường sau"), ("right", "Chính diện tường phải"), ("left", "Chính diện tường trái")):
        mods = [m for m in spec.module if m.wall == wall]
        seat = runmod.wall_seat(wall, scene.lsau)
        if mods and seat is not None:
            face(f"{wall}-wall", name, mods, lambda lo, hi, d, seat=seat: seat.to_world((lo + hi) / 2, d), seat.normal(), wall)
    for run in spec.runs:
        mods = [m for m in spec.module if m.run == run.id and m.storey != "corner"]      # a corner shelf is not a front
        if mods:
            fr = runmod.RunFrame(run.id, run.x, run.z, run.yaw)
            (ox, oz), (nx, nz) = fr.to_world(0, 0), fr.to_world(0, 1)
            wall = run_wall(fr, scene.lsau)
            if wall is not None and not any(f.key == f"{wall}-wall" for f in faces):     # a run standing against a wall is that wall's front
                key, name = f"{wall}-wall", {"back": "Chính diện tường sau", "right": "Chính diện tường phải", "left": "Chính diện tường trái"}[wall]
            else:
                key, name = f"run-{run.id}", f"Chính diện dãy tủ {run.id}"
            face(key, name, mods, lambda lo, hi, d, fr=fr: fr.to_world((lo + hi) / 2, d), (nx - ox, nz - oz), run.id)
    return faces


def cabinet_bodies(spec: KitchenSpec) -> list[camera_plan.Obstacle]:
    """The floor footprint of every cabinet standing in a run, up to its top (kind ``cabinet:<run>``): cameras stand clear of them."""
    frames = runmod.frames(spec)
    out = []
    for m in spec.module:
        fr = frames.get(m.run) if m.run else None
        if fr is not None and m.storey in ("base", "tall"):
            out.append(camera_plan.Obstacle(m.id, f"cabinet:{m.run}", tuple(runmod.module_footprint(fr, m)), float(m.y), float(m.y + m.height)))
    return out


def room_solids(spec: KitchenSpec, scene: Scene) -> tuple[list[tuple[float, float]] | None, list[camera_plan.Obstacle]]:
    """The room's floor outline and the solids of the imported floorplan that are not cabinets, in the kitchen frame; ``(None, [])`` without a floorplan."""
    try:
        ctx = roomctx.for_spec(spec, scene.lsau, scene.lphai)
    except ValueError:
        ctx = None
    if ctx is None:   # no floorplan: the room is the box the floor of the scene covers (walls behind the cabinets, open on the viewer's side)
        return [(-scene.lsau, 0.0), (0.0, 0.0), (0.0, scene.lphai + 3000.0), (-scene.lsau, scene.lphai + 3000.0)], []
    to_kitchen = ctx.placement.to_kitchen
    room = [to_kitchen(float(q["x"]), float(q["z"])) for q in ctx.floorplan.get("outline", [])]
    solids = []
    for st in ctx.structures:
        outline = tuple(to_kitchen(float(p["x"]), float(p["z"])) for p in st["outline"])
        if len(outline) >= 3 and float(st.get("height") or 0) > 0:
            base = float(st.get("base") or 0.0)
            solids.append(camera_plan.Obstacle(st["id"], st["kind"], outline, base, base + float(st["height"])))
    return (room if len(room) >= 3 else None), solids


def default_views(spec: KitchenSpec, scene: Scene | None = None) -> dict[str, ViewAngle]:
    """Bộ góc nhìn chuẩn khi spec chưa khai báo gocNhin (m). Camera ở độ cao mắt 1,6 m; khi có mặt bằng hoặc dãy tủ tự do thì mỗi dãy có góc chính
    diện + góc chéo đặt trong phòng, và những vật thể không phải tủ (tường, cột, đồ) chắn giữa camera và tủ nằm trong ``hide`` của góc đó."""
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
    reach = wall_reach(spec, scene.lsau)
    if "left" in reach:  # chữ U: ba mặt kín, máy ảnh phải đứng ở phía hở (z lớn) mới nhìn thấy cả ba dãy
        zfront = hi[2] / 1000
        views["perspective"] = ViewAngle(name="Phối cảnh chéo", position=(cx + w * 0.3, 1.6, zfront + span * 0.55), lookAt=(cx, 1.0, cz * 0.8), verticalFov=70)
        views["overhead"] = ViewAngle(name="Toàn cảnh từ trên", position=(cx, 3.8, zfront + span * 0.35), lookAt=(cx, 0.6, cz * 0.8), verticalFov=70)
    if "back" in reach:
        xs = [-reach["back"] / 1000, 0]
        mx = (min(xs) + max(xs)) / 2
        views["back-wall"] = ViewAngle(name="Chính diện tường sau", position=(mx, camera_plan.EYE / 1000, span * 1.4 + 0.6), lookAt=(mx, 1.25, 0.2), verticalFov=48)
    if "right" in reach:
        zs = [reach["right"] / 1000, 0]
        mz = (min(zs) + max(zs)) / 2
        views["right-wall"] = ViewAngle(name="Chính diện tường phải", position=(-(span * 1.4 + 0.6), camera_plan.EYE / 1000, mz), lookAt=(0, 1.25, mz), verticalFov=48)
    if "left" in reach:
        zs = [reach["left"] / 1000, 0]
        mz = (min(zs) + max(zs)) / 2
        views["left-wall"] = ViewAngle(name="Chính diện tường trái", position=(-scene.lsau / 1000 + span * 1.4 + 0.6, camera_plan.EYE / 1000, mz), lookAt=(-scene.lsau / 1000, 1.25, mz), verticalFov=48)
    room, solids = room_solids(spec, scene)
    faces = cabinet_faces(spec, scene)
    if faces and room is not None:
        planned = camera_plan.plan_views(faces, room, solids, cabinet_bodies(spec))
        views.update({key: ViewAngle(**v) for key, v in planned.items()})
        biggest = max(faces, key=lambda f: f.length)
        if "left" not in reach:  # a U sees all three runs only from the open side: keep its own overview
            views["perspective"] = ViewAngle(**{**planned[f"{biggest.key}-oblique"], "name": "Phối cảnh chéo"})
    if solids and faces:
        for key in ("overhead", "plan"):
            v = views[key]
            views[key] = ViewAngle(name=v.name, position=v.position, lookAt=v.lookAt, verticalFov=v.verticalFov,
                                   hide=camera_plan.hidden_for(v.position, faces, solids))
    return views


def views_of(spec: KitchenSpec) -> dict[str, ViewAngle]:
    return dict(spec.cameraViews) if spec.cameraViews else default_views(spec)


def scene_json(spec: KitchenSpec) -> dict[str, Any]:
    sc = compile_spec(spec)
    openings, hi = sc.bounds()
    return {
        "version": "2.0", "units": "mm",
        "parts": [p.to_json() for p in sc.parts],
        "bounds": {"min": openings, "max": hi},
        "views": {k: to_data(v) for k, v in views_of(spec).items()},
        "modules": [{"id": m.id, "name": m.name, "type": m.type, "wall": m.wall} for m in spec.module],
        "moldings": [{"id": m.id, "molding": m.module, "vertices": len(m.vertices), "faces": len(m.faces)} for m in sc.meshes],
    }
