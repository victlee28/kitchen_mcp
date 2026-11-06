"""Small 2-D geometry helpers on points and polygons (millimetres). Pure; no knowledge of floorplans."""
from __future__ import annotations

import math


# ---------------------------------------------------------------- small geometry helpers
Pt = tuple[float, float]
Poly = list[Pt]


def vsub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def vdot(a: Pt, b: Pt) -> float:
    return a[0] * b[0] + a[1] * b[1]


def vcross(a: Pt, b: Pt) -> float:
    return a[0] * b[1] - a[1] * b[0]


def vnorm(a: Pt) -> Pt:
    n = math.hypot(*a)
    return (a[0] / n, a[1] / n) if n > 1e-9 else (0.0, 0.0)


def area2(poly: Poly) -> float:
    return sum(vcross(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def seg_dist(p: Pt, a: Pt, b: Pt) -> float:
    ab = vsub(b, a)
    L2 = vdot(ab, ab)
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, vdot(vsub(p, a), ab) / L2))
    q = (a[0] + ab[0] * t, a[1] + ab[1] * t)
    return math.hypot(p[0] - q[0], p[1] - q[1])


def boundary_dist(p: Pt, poly: Poly) -> float:
    return min(seg_dist(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def point_in_poly(p: Pt, poly: Poly) -> bool:
    x, y = p
    inside = False
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def proper_cross(a: Pt, b: Pt, c: Pt, d: Pt) -> bool:
    """Segments ab and cd cross at a single interior point of both (touching/collinear does not count)."""
    d1, d2 = vcross(vsub(b, a), vsub(c, a)), vcross(vsub(b, a), vsub(d, a))
    d3, d4 = vcross(vsub(d, c), vsub(a, c)), vcross(vsub(d, c), vsub(b, c))
    return d1 * d2 < -1e-9 and d3 * d4 < -1e-9


def polys_cross(p: Poly, q: Poly) -> bool:
    return any(proper_cross(p[i], p[(i + 1) % len(p)], q[j], q[(j + 1) % len(q)]) for i in range(len(p)) for j in range(len(q)))


def poly_dist(p: Poly, q: Poly) -> float:
    """Distance between two polygon boundaries (0 when they touch or cross)."""
    if polys_cross(p, q):
        return 0.0
    return min([seg_dist(v, q[j], q[(j + 1) % len(q)]) for v in p for j in range(len(q))] +
               [seg_dist(v, p[j], p[(j + 1) % len(p)]) for v in q for j in range(len(p))])


def self_intersects(poly: Poly) -> bool:
    n = len(poly)
    for i in range(n):
        for j in range(i + 1, n):
            if (j + 1) % n == i or (i + 1) % n == j:
                continue
            if proper_cross(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]):
                return True
    return False


def angle_between(d1: Pt, d2: Pt) -> float:
    """Smallest angle (deg) between two undirected lines."""
    return math.degrees(math.atan2(abs(vcross(d1, d2)), abs(vdot(d1, d2))))


def long_dir(pts: Poly) -> Pt:
    best, d = 0.0, (1.0, 0.0)
    for i in range(len(pts)):
        v = vsub(pts[(i + 1) % len(pts)], pts[i])
        if math.hypot(*v) > best:
            best, d = math.hypot(*v), vnorm(v)
    return d
