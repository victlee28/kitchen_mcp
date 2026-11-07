"""Hình học phối cảnh cho ảnh bếp chụp xiên (lõi thuần, chỉ stdlib).

Quy ước:
- Ảnh: u sang phải, v xuống dưới (pixel). Điểm chính = tâm ảnh.
- Camera: x phải, y xuống, z hướng nhìn.
- Thế giới: X dọc tường sau sang phải, Y lên, Z vuông góc tường sau hướng về phía camera.
  Camera ở gốc, sàn ở Y = -1 (đơn vị = chiều cao camera, đổi ra mm sau khi có vật chuẩn).
- Đường xiên trên ảnh: v = m*u + q.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import invalid

Vec = tuple[float, float, float]
INFINITE_SLOPE_GAP = 2e-3  # các đường gần song song trên ảnh -> điểm tụ ở vô cực


def _norm(a: Vec) -> Vec:
    n = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
    return (a[0] / n, a[1] / n, a[2] / n)


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _neg(a: Vec) -> Vec:
    return (-a[0], -a[1], -a[2])


@dataclass(frozen=True)
class VanishingPoint:
    finite: bool
    u: float
    v: float
    slope: float  # hướng chung khi ở vô cực
    residual: float


def vanishing_point(lines: list[tuple[float, float]]) -> VanishingPoint:
    """Giao điểm bình phương tối thiểu của các đường v = m u + q."""
    if len(lines) < 2:
        raise invalid("too-few-lines", "cần ít nhất 2 đường để tìm điểm tụ")
    ms = [m for m, _ in lines]
    if max(ms) - min(ms) < INFINITE_SLOPE_GAP:
        return VanishingPoint(False, 0.0, 0.0, sum(ms) / len(ms), 0.0)
    # tối thiểu Σ (m u - v + q)^2 / (m^2+1)
    a11 = a12 = a22 = b1 = b2 = 0.0
    for m, q in lines:
        w = 1.0 / (m * m + 1.0)
        a11 += w * m * m
        a12 += -w * m
        a22 += w
        b1 += -w * m * q
        b2 += w * q
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-12:
        return VanishingPoint(False, 0.0, 0.0, sum(ms) / len(ms), 0.0)
    u = (b1 * a22 - a12 * b2) / det
    v = (a11 * b2 - a12 * b1) / det
    res = math.sqrt(sum((m * u - v + q) ** 2 / (m * m + 1) for m, q in lines) / len(lines))
    return VanishingPoint(True, u, v, 0.0, res)


@dataclass(frozen=True)
class Camera:
    f: float
    cx: float
    cy: float
    ex: Vec  # trục X thế giới trong hệ camera
    ey: Vec
    ez: Vec

    def ray(self, u: float, v: float) -> Vec:
        """Tia từ camera qua pixel, biểu diễn trong hệ thế giới."""
        c = _norm((u - self.cx, v - self.cy, self.f))
        return (_dot(self.ex, c), _dot(self.ey, c), _dot(self.ez, c))

    def on_floor(self, u: float, v: float, floor_y: float = -1.0) -> Vec:
        w = self.ray(u, v)
        if w[1] >= -1e-9:
            raise invalid("above-horizon", f"pixel ({u:.0f},{v:.0f}) không nằm trên sàn")
        t = floor_y / w[1]
        return (t * w[0], t * w[1], t * w[2])

    def on_plane(self, u: float, v: float, axis: str, value: float) -> Vec:
        """Giao tia với mặt phẳng X=value hoặc Z=value."""
        w = self.ray(u, v)
        k = 0 if axis == "x" else 2
        if abs(w[k]) < 1e-9:
            raise invalid("parallel-ray", "tia song song với mặt phẳng")
        t = value / w[k]
        if t <= 0:
            raise invalid("behind-camera", "mặt phẳng nằm sau camera")
        return (t * w[0], t * w[1], t * w[2])

    def project(self, p: Vec) -> tuple[float, float]:
        c = (self.ex[0] * p[0] + self.ey[0] * p[1] + self.ez[0] * p[2],
             self.ex[1] * p[0] + self.ey[1] * p[1] + self.ez[1] * p[2],
             self.ex[2] * p[0] + self.ey[2] * p[1] + self.ez[2] * p[2])
        return (self.cx + self.f * c[0] / c[2], self.cy + self.f * c[1] / c[2])


def focal_from_vps(vb: VanishingPoint, vs: VanishingPoint, cx: float, cy: float) -> float | None:
    """Tiêu cự từ hai điểm tụ của hai hướng vuông góc (None nếu không giải được)."""
    if not (vb.finite and vs.finite):
        return None
    f2 = -((vb.u - cx) * (vs.u - cx) + (vb.v - cy) * (vs.v - cy))
    return math.sqrt(f2) if f2 > 0 else None


def build_camera(vb: VanishingPoint, vs: VanishingPoint | None, f: float, cx: float, cy: float) -> Camera:
    """vb: điểm tụ dọc tường sau; vs: điểm tụ hướng vuông góc tường sau (dọc tường bên)."""
    def cam_ray(u: float, v: float) -> Vec:
        return _norm((u - cx, v - cy, f))

    if vb.finite:
        r = cam_ray(vb.u, vb.v)
        ex = r if vb.u > cx else _neg(r)
    else:
        ex = _norm((1.0, vb.slope, 0.0))
    if vs is not None and vs.finite:
        ez0 = _neg(cam_ray(vs.u, vs.v))
    else:
        ez0 = _cross(ex, (0.0, -1.0, 0.0))  # chưa có hướng sâu: lấy vuông góc với trục đứng ảnh
        if ez0[2] > 0:
            ez0 = _neg(ez0)
    ey = _norm(_cross(ez0, ex))
    if ey[1] > 0:
        ey = _neg(ey)
    ez = _norm(_cross(ex, ey))
    if ez[2] > 0:  # Z thế giới phải hướng về camera (ngược hướng nhìn)
        raise invalid("bad-orientation", "hướng các điểm tụ không nhất quán")
    return Camera(f, cx, cy, ex, ey, ez)


def line_y(line: tuple[float, float], u: float) -> float:
    return line[0] * u + line[1]
