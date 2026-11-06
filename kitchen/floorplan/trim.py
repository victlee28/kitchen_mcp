"""Trimming a room outline where wall elements sit inside it."""
from __future__ import annotations

from ..numeric import round_half_away

from .geom import Poly, Pt


# ---------------------------------------------------------------- trim a room outline where wall elements sit inside it
def _snap_orthogonal(poly: list[tuple[float, float]], slope: float = 0.1) -> list[tuple[float, float]] | None:
    """Make a nearly rectilinear outline exactly axis-parallel (edges share their coordinate); None when an edge is clearly diagonal."""
    n = len(poly)
    gx, gy = list(range(n)), list(range(n))

    def find(g: list[int], i: int) -> int:
        while g[i] != i:
            g[i] = g[g[i]]
            i = g[i]
        return i
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
        if dx == 0 and dy == 0:
            continue
        if dy <= slope * dx:
            gy[find(gy, i)] = find(gy, (i + 1) % n)
        elif dx <= slope * dy:
            gx[find(gx, i)] = find(gx, (i + 1) % n)
        else:
            return None
    sx: dict[int, list[float]] = {}
    sy: dict[int, list[float]] = {}
    for i, p in enumerate(poly):
        sx.setdefault(find(gx, i), []).append(p[0])
        sy.setdefault(find(gy, i), []).append(p[1])
    return [(sum(sx[find(gx, i)]) / len(sx[find(gx, i)]), sum(sy[find(gy, i)]) / len(sy[find(gy, i)])) for i in range(n)]


def _inside(pt: Pt, poly: Poly) -> bool:
    x, y = pt
    c = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            c = not c
    return c


def _trace(cells: set[tuple[int, int]], xs: list[float], ys: list[float]) -> list[tuple[float, float]] | None:
    """Outer boundary (counter-clockwise) of a union of grid cells; None when it has holes, several parts, or touches itself at a corner."""
    nxt: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for (i, j) in cells:
        for a, b, nb in (((i, j), (i + 1, j), (i, j - 1)), ((i + 1, j), (i + 1, j + 1), (i + 1, j)),
                         ((i + 1, j + 1), (i, j + 1), (i, j + 1)), ((i, j + 1), (i, j), (i - 1, j))):
            if nb not in cells:
                nxt.setdefault(a, []).append(b)
    if not nxt or any(len(v) != 1 for v in nxt.values()):
        return None
    start = next(iter(nxt))
    loop, cur = [], start
    while True:
        loop.append(cur)
        cur = nxt[cur][0]
        if cur == start:
            break
        if len(loop) > len(nxt):
            return None
    if len(loop) != len(nxt):
        return None
    pts = [(xs[i], ys[j]) for i, j in loop]
    out = []
    for k, p in enumerate(pts):
        a, b = pts[k - 1], pts[(k + 1) % len(pts)]
        if abs((p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0])) > 1e-9:
            out.append(p)
    return out


def trim_room(poly: list[tuple[float, float]], rects: list[tuple[str, list[float]]], snap: float, min_overlap: float = 0.6,
              max_loss: float = 0.15) -> tuple[list[tuple[float, float]], list[str]]:
    """Cut out of a rectilinear room outline the wall elements that mostly lie inside it and touch its boundary.

    ``rects``: (id, [x0, y0, x1, y1]) of wall elements, file coordinates; their sides within ``snap`` of an outline coordinate are
    taken to coincide with it. A wall is cut only when the result stays one simple region and the room loses at most ``max_loss``
    of its area overall. Returns (outline, ids cut); the original outline and [] when nothing applies.
    """
    base = _snap_orthogonal(list(poly))
    if base is None:
        return list(poly), []
    px, py = sorted({round_half_away(p[0], 6) for p in base}), sorted({round_half_away(p[1], 6) for p in base})

    def near(v: float, grid: list[float]) -> float:
        best = min(grid, key=lambda g: abs(g - v))
        return best if abs(best - v) <= snap else round_half_away(v, 6)
    snapped = [(i, [near(bb[0], px), near(bb[1], py), near(bb[2], px), near(bb[3], py)]) for i, bb in rects]
    snapped = [(i, r) for i, r in snapped if r[2] > r[0] and r[3] > r[1]]
    xs = sorted({*px, *(c for _, r in snapped for c in (r[0], r[2]))})
    ys = sorted({*py, *(c for _, r in snapped for c in (r[1], r[3]))})
    cell = {(i, j) for i in range(len(xs) - 1) for j in range(len(ys) - 1) if _inside(((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2), base)}
    area = lambda cs: sum((xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j]) for i, j in cs)   # noqa: E731
    room_area, kept, cut = area(cell), set(cell), []
    for wid, r in snapped:
        wc = {(i, j) for i in range(len(xs) - 1) for j in range(len(ys) - 1) if xs[i] >= r[0] and xs[i + 1] <= r[2] and ys[j] >= r[1] and ys[j + 1] <= r[3]}
        inside = wc & kept
        if not inside or area(inside) < min_overlap * (r[2] - r[0]) * (r[3] - r[1]):
            continue
        if not any(nb not in cell for (i, j) in inside for nb in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1))):
            continue                                   # an island inside the room, not a notch of its outline
        trial = kept - wc
        if area(cell) - area(trial) > max_loss * room_area or _trace(trial, xs, ys) is None:
            continue
        kept, cut = trial, cut + [wid]
    if not cut:
        return list(poly), []
    out = _trace(kept, xs, ys)
    if out is None:
        return list(poly), []
    sign = lambda pts: sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))   # noqa: E731
    if sign(out) * sign(list(poly)) < 0:
        out.reverse()
    return out, cut
