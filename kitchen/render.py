"""Render AI control maps: edges, depth, normals and masks without a GPU or browser.

- Software rasterizer using compiler-generated boxes:
- lines.png      : black outlines on white (part boundaries and box edges)
- depth.png      : 8-bit, nearer surfaces are brighter; depth16.png: 16-bit depth in millimetres
- normal.png     : camera-space normals, RGB = n*0.5+0.5 (x right, y up, z toward camera)
- seg.png        : mask by part type (fixed colors; see legend.json)
- seg_module.png : mask by module (one color per module; see legend.json)
- seg_structure.png : mask for imported floorplan objects (walls, columns, doors, stairs, etc.)
- camera.json    : camera intrinsics and extrinsics for back-projection
- instance.png   : 16-bit part index + 1 (0 = background); lookup in instances.json (part IDs are layer IDs)
- albedo.png     : material colors with simple shading, pixel-aligned with masks (initial image / preview)
- manifest.json  : designId, revision, renderKey (geometry + camera + dimensions hash), and file list
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import builtin, runs, two_point
from .catalog import Catalog
from .errors import InvalidInput
from .geometry import Scene, compile_spec, views_of
from .palette import SEGMENT_COLORS, module_color as _module_color
from .spec import ViewAngle, KitchenSpec
from .wall_surfaces import FaceRef, face_owner, face_part_id

NEAR = 0.05  # m


# 6 mặt của hộp: (chỉ số đỉnh, normal)
_FACES = [
    ((0, 2, 6, 4), (-1, 0, 0)), ((1, 5, 7, 3), (1, 0, 0)),
    ((0, 4, 5, 1), (0, -1, 0)), ((2, 3, 7, 6), (0, 1, 0)),
    ((0, 1, 3, 2), (0, 0, -1)), ((4, 6, 7, 5), (0, 0, 1)),
]


def _face_normals(part) -> np.ndarray:
    """Outward normals of the 6 faces in world axes; the faces of a part in an angled run are turned with its run."""
    base = np.array([n for _, n in _FACES], float)
    if part.frame is None:
        return base
    c, sn = runs.trig(part.frame[2])
    out = base.copy()
    out[:, 0] = base[:, 0] * c + base[:, 2] * sn          # world x = s*cos + d*sin
    out[:, 2] = -base[:, 0] * sn + base[:, 2] * c         # world z = -s*sin + d*cos
    return out


class Camera:
    """A pinhole camera for a view. Eye-level views are two-point perspective (``two_point``): the camera is level and the principal point
    is moved (``cy``) so the point the view aims at stays in the middle; vertical edges stay vertical.
    A view with ``orthoHeight`` is orthographic (the plan): parallel rays along the view direction, ``scale`` pixels per metre, so the
    picture is to scale everywhere; ``focal`` is then that scale and depth is the distance along the view direction."""
    def __init__(self, view: ViewAngle, width: int, height: int):
        self.p = np.array(view.position, float)
        t = np.array(view.lookAt, float)
        self.ortho = view.orthoHeight is not None
        lv = None if self.ortho else two_point.level(view.position, view.lookAt)
        f = np.array(lv.forward, float) if lv else t - self.p
        f /= np.linalg.norm(f)
        up = np.array([0.0, 1.0, 0.0])
        if abs(f @ up) > 0.999:  # nhìn thẳng xuống/lên: lấy trục -z làm "lên" của ảnh
            up = np.array([0.0, 0.0, -1.0])
        r = np.cross(f, up); r /= np.linalg.norm(r)
        u = np.cross(r, f)
        self.f, self.r, self.u = f, r, u
        self.w, self.h = width, height
        if self.ortho:
            self.focal = height / float(view.orthoHeight or 1.0)      # pixels per metre
        else:
            self.focal = (height / 2) / math.tan(math.radians(view.verticalFov) / 2)
        self.cx, self.cy = width / 2, height / 2 + (self.focal * lv.shift if lv else 0.0)     # image row of the horizon (two-point)

    def to_camera(self, pts: np.ndarray) -> np.ndarray:
        d = pts - self.p
        return np.stack([d @ self.r, d @ self.u, d @ self.f], axis=-1)

    def project(self, P: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Camera-frame points -> (pixel x, pixel y, the value interpolated linearly across a triangle: 1/z in perspective, z in ortho)."""
        if self.ortho:
            return self.cx + self.focal * P[:, 0], self.cy - self.focal * P[:, 1], P[:, 2]
        return self.cx + self.focal * P[:, 0] / P[:, 2], self.cy - self.focal * P[:, 1] / P[:, 2], 1.0 / P[:, 2]

    def depth(self, interpolated: np.ndarray) -> np.ndarray:
        """The depth of a pixel from the interpolated value of ``project``."""
        return interpolated if self.ortho else 1.0 / interpolated

    def toward(self, point: np.ndarray) -> np.ndarray:
        """A vector from a world point towards the camera (back-face test): to the eye, or against the view direction in ortho."""
        return -self.f if self.ortho else self.p - point

    def unproject(self, px: np.ndarray, py: np.ndarray, z: np.ndarray) -> np.ndarray:
        """World points (metres) of pixel centres ``px``, ``py`` at depth ``z``."""
        if self.ortho:
            xc, yc = (px - self.cx) / self.focal, -(py - self.cy) / self.focal
        else:
            xc, yc = (px - self.cx) / self.focal * z, -(py - self.cy) / self.focal * z
        return self.p + xc[..., None] * self.r + yc[..., None] * self.u + z[..., None] * self.f

    def json(self) -> dict:
        R = np.stack([self.r, -self.u, self.f])  # hàng: trục camera (x phải, y xuống, z tới) theo OpenCV
        out = {"width": self.w, "height": self.h, "fx": self.focal, "fy": self.focal, "cx": self.cx, "cy": self.cy,
               "R_world_to_cam": R.tolist(), "t": (-R @ self.p).tolist(), "position_m": self.p.tolist(),
               "convention": "OpenCV: x right, y down, z along the view; world coordinates in metres"}
        if self.ortho:      # u = cx + fx * x_cam, v = cy + fy * y_cam (no division by z): fx = pixels per metre
            out["projection"] = "orthographic"
        return out


def _clip_near(poly: list[np.ndarray]) -> list[np.ndarray]:
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ia, ib = a[2] >= NEAR, b[2] >= NEAR
        if ia:
            out.append(a)
        if ia != ib:
            t = (NEAR - a[2]) / (b[2] - a[2])
            out.append(a + t * (b - a))
    return out


def rasterize(scene: Scene, camera: Camera):
    W, H = camera.w, camera.h
    zbuf = np.full((H, W), np.inf)
    pid = np.full((H, W), -1, np.int32)
    nid = np.full((H, W), -1, np.int8)
    ys, xs = np.mgrid[0:H, 0:W]
    pxc, pyc = xs + 0.5, ys + 0.5
    for k, part in enumerate(scene.parts):
        corners = np.array(part.corners(), float) / 1000
        fnormals = _face_normals(part)
        cc = camera.to_camera(corners)
        if (cc[:, 2] < NEAR).all():
            continue
        for fi, (idx, normal) in enumerate(_FACES):
            # bỏ mặt quay lưng
            center = corners[list(idx)].mean(0)
            if np.dot(fnormals[fi], camera.toward(center)) <= 0:
                continue
            poly = _clip_near([cc[i] for i in idx])
            if len(poly) < 3:
                continue
            P = np.array(poly)
            sx, sy, iz = camera.project(P)
            for t in range(1, len(P) - 1):
                tri = [0, t, t + 1]
                x0, x1 = int(max(0, math.floor(sx[tri].min()))), int(min(W, math.ceil(sx[tri].max()) + 1))
                y0, y1 = int(max(0, math.floor(sy[tri].min()))), int(min(H, math.ceil(sy[tri].max()) + 1))
                if x0 >= x1 or y0 >= y1:
                    continue
                (ax, bx, cx), (ay, by, cy) = sx[tri], sy[tri]
                den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
                if abs(den) < 1e-12:
                    continue
                X, Y = pxc[y0:y1, x0:x1], pyc[y0:y1, x0:x1]
                w0 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / den
                w1 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / den
                w2 = 1 - w0 - w1
                inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
                if not inside.any():
                    continue
                z = camera.depth(w0 * iz[tri[0]] + w1 * iz[tri[1]] + w2 * iz[tri[2]])
                zb = zbuf[y0:y1, x0:x1]
                win = inside & (z < zb - 1e-7)
                zb[win] = z[win]
                pid[y0:y1, x0:x1][win] = k
                nid[y0:y1, x0:x1][win] = fi
    mesh_n = np.zeros((H, W, 3), np.float32)
    base = len(scene.parts)
    for mi, mesh in enumerate(scene.meshes):
        V = np.asarray(mesh.vertices, float) / 1000
        VC = camera.to_camera(V)
        nprof = _profile_len(mesh)
        for f_idx, (a, b, c) in enumerate(mesh.faces):
            tri_w = V[[a, b, c]]
            n = np.cross(tri_w[1] - tri_w[0], tri_w[2] - tri_w[0])
            ln = np.linalg.norm(n)
            if ln < 1e-12:
                continue
            n = n / ln
            if np.dot(n, camera.toward(tri_w.mean(0))) < 0:
                n = -n  # pháp tuyến hướng về camera
            poly = _clip_near([VC[a], VC[b], VC[c]])
            if len(poly) < 3:
                continue
            P = np.array(poly)
            sx, sy, iz = camera.project(P)
            group = _face_group(f_idx, nprof, len(mesh.faces))
            for t in range(1, len(P) - 1):
                tri = [0, t, t + 1]
                x0, x1 = int(max(0, math.floor(sx[tri].min()))), int(min(W, math.ceil(sx[tri].max()) + 1))
                y0, y1 = int(max(0, math.floor(sy[tri].min()))), int(min(H, math.ceil(sy[tri].max()) + 1))
                if x0 >= x1 or y0 >= y1:
                    continue
                (ax, bx, cx), (ay, by, cy) = sx[tri], sy[tri]
                den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
                if abs(den) < 1e-12:
                    continue
                X, Y = pxc[y0:y1, x0:x1], pyc[y0:y1, x0:x1]
                w0 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / den
                w1 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / den
                w2 = 1 - w0 - w1
                inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
                if not inside.any():
                    continue
                z = camera.depth(w0 * iz[tri[0]] + w1 * iz[tri[1]] + w2 * iz[tri[2]])
                zb = zbuf[y0:y1, x0:x1]
                win = inside & (z < zb - 1e-7)
                zb[win] = z[win]
                pid[y0:y1, x0:x1][win] = base + mi
                nid[y0:y1, x0:x1][win] = group
                mesh_n[y0:y1, x0:x1][win] = n
    return zbuf, pid, nid, mesh_n


def _profile_len(mesh) -> int:
    """Số điểm mặt cắt: lưới quét có (vòng × điểm) đỉnh; mặt bên = (vòng-1) × điểm × 2."""
    nf, nv = len(mesh.faces), len(mesh.vertices)
    for n in range(3, 200):
        rings = nv // n
        if nv % n == 0 and rings >= 2 and nf == (rings - 1) * n * 2 + 2 * (n - 2):
            return n
    return 0


def _face_group(f_idx: int, nprof: int, nfaces: int) -> int:
    """Nhóm mặt để vẽ nét: mỗi cạnh mặt cắt một nhóm (đường gân phào), hai nắp hai nhóm riêng."""
    if not nprof:
        return 120
    side = nfaces - 2 * (nprof - 2)
    if f_idx < side:
        return 6 + (f_idx // 2) % nprof % 100
    return 120 if f_idx < side + (nprof - 2) else 121


_JOINED_FACE = ("countertop", "wall", "floor", "carcass", "plinth")  # bề mặt liền: không vẽ đường nối giữa các mảnh đồng phẳng


def _edges(pid: np.ndarray, nid: np.ndarray, zbuf: np.ndarray, type: np.ndarray) -> np.ndarray:  # noqa: C901
    """Nét = biên giữa hai chi tiết khác nhau hoặc hai mặt khác nhau của cùng chi tiết.
    Riêng các bề mặt liền (mặt đá, tường, sàn, thân, chân) đồng phẳng thì không vẽ đường nối."""
    e = np.zeros(pid.shape, bool)
    key = pid.astype(np.int64) * 256 + nid
    joined = np.isin(type, [i for i, _ in enumerate(_JOINED_FACE)])
    with np.errstate(invalid="ignore"):
        for a, b in (((slice(None), slice(1, None)), (slice(None), slice(None, -1))),
                     ((slice(1, None), slice(None)), (slice(None, -1), slice(None)))):
            diff = key[a] != key[b]
            coplanar = (nid[a] == nid[b]) & (type[a] == type[b]) & joined[a] & \
                (np.abs(zbuf[a] - zbuf[b]) < 0.0008 * np.minimum(zbuf[a], zbuf[b]))
            e[a] |= diff & ~coplanar
    return e


def scene_hash(scene: Scene) -> str:
    """Băm hình học đã biên dịch (không gồm vật liệu): đổi màu không đổi băm, nên mask cũ dùng lại được."""
    h = hashlib.sha256()
    for p in scene.parts:
        h.update(f"{p.id}|{p.type}|{p.module}|{[round(v, 2) for v in p.min]}|{[round(v, 2) for v in p.max]}\n".encode())
        if p.frame is not None:                    # an angled part is not described by its AABB alone: add its run frame and local box
            h.update(f"{[round(v, 2) for v in p.frame]}|{[round(v, 2) for v in p.lmin or ()]}|{[round(v, 2) for v in p.lmax or ()]}\n".encode())
    for m in scene.meshes:
        h.update(f"{m.id}|{m.type}|{m.module}|{len(m.faces)}|".encode())
        h.update(np.round(np.asarray(m.vertices, float), 2).tobytes())
    return h.hexdigest()


PLAN_ONLY = ("structure-swing", "opening-sweep")    # the floor a door leaf sweeps: drawn on the plan only, never in a perspective view


def view_scene(scene: Scene, view: ViewAngle) -> Scene:
    """What ``view`` shows of ``scene``: without the structures it hides (``view.hide``) and, unless it is the plan (orthographic),
    without the door sweeps (``PLAN_ONLY``). Idempotent."""
    plan = view.orthoHeight is not None
    meshes = [m for m in scene.meshes if m.module not in view.hide and (plan or m.type not in PLAN_ONLY)]
    return scene if len(meshes) == len(scene.meshes) else replace(scene, meshes=meshes)


def render_key(scene: Scene, view: ViewAngle, width: int, height: int) -> str:
    scene = view_scene(scene, view)
    v = json.dumps(view.model_dump(mode="json", exclude={"orthoHeight"} if view.orthoHeight is None else None), sort_keys=True)
    return hashlib.sha256(f"{scene_hash(scene)}|{v}|{width}x{height}|{two_point.PROJECTION}".encode()).hexdigest()[:16]


_DARK = np.array([0.35, 0.85, 0.40]) / np.linalg.norm([0.35, 0.85, 0.40])


@dataclass(frozen=True)
class FaceColor:
    """A wall face with a finish of its own (``spec.surfaceMaterials``): the parts it lies on (a default wall's box by its ``wall``,
    a floorplan wall's meshes by their structure id), its outward normal (kitchen frame) and the colour."""
    wall: str | None             # default wall: back / right / left
    structure: str | None        # floorplan wall: the structure id its meshes carry as ``module``
    normal: tuple[float, float, float]
    rgb: tuple[int, int, int]
    span: tuple[float, float, float, float, float, float, float, float, float] | None = None     # a reveal (FaceRef.span)


FACE_NORMAL_COS = 0.95
INSTANCE_FORMAT = 3           # 2: each wall face is an instance of its own; 3: the reveals of openings too. An older render is redone (same renderKey)
REVEAL_EPS_MM = 5.0           # a reveal's box is grown this much when its pixels are looked for
REVEAL_SIDE_COS = 0.5         # a reveal pixel's normal is across the wall's (jamb, head, sill), never along it


def _span_kitchen(sf: dict[str, Any], ctx: Any) -> tuple[float, float, float, float, float, float, float, float, float] | None:
    """A reveal's box (``sf["span"]``, document frame) in the render's kitchen frame; None for a face that is not a reveal."""
    sp = sf.get("span")
    if not isinstance(sp, dict):
        return None
    try:
        (sx, sz), (dx, dz) = [float(v) for v in sp["start"]][:2], [float(v) for v in sp["dir"]][:2]
        e0, e1, y0, y1, half = (float(sp[k]) for k in ("e0", "e1", "y0", "y1", "half"))
    except (KeyError, TypeError, ValueError):
        return None
    if ctx is not None:
        a, b = ctx.placement.to_kitchen(0.0, 0.0), ctx.placement.to_kitchen(dx, dz)
        dx, dz = b[0] - a[0], b[1] - a[1]
        sx, sz = ctx.placement.to_kitchen(sx, sz)
    return (sx, sz, dx, dz, e0, e1, y0, y1, half)


def _in_span(world: np.ndarray, nw: np.ndarray, span: tuple[float, ...]) -> np.ndarray:
    """Which of the points (``world``, mm, with normals ``nw``) lie on the reveal of ``span``: inside the hole's box, facing across the wall."""
    sx, sz, dx, dz, e0, e1, y0, y1, half = span
    rx, rz = world[..., 0] - sx, world[..., 2] - sz
    along, across = rx * dx + rz * dz, rx * -dz + rz * dx
    e = REVEAL_EPS_MM
    inside = (along > e0 - e) & (along < e1 + e) & (world[..., 1] > y0 - e) & (world[..., 1] < y1 + e) & (np.abs(across) < half + e)
    return inside & (np.abs(nw[..., 0] * -dz + nw[..., 2] * dx) < REVEAL_SIDE_COS)
FACE_PLANE_MM = 25.0          # a pixel lies on a wall face when it is this close to the face's plane (an opening's reveal is not)


def wall_faces(spec: KitchenSpec, catalog: Catalog = builtin.CATALOG, scene: Scene | None = None, views: dict[str, Any] | None = None) -> list[FaceRef]:
    """Every face of every wall (the three.js export's ``room.surfaces``) in the render's kitchen frame, for the instance image to give
    each face a layer of its own. ``views``: the camera views when the caller has them (else the export plans them again, ~1 s)."""
    from . import roomctx
    from .threejs_export import export
    doc = export(spec, catalog=catalog, views=views)
    scene = scene or compile_spec(spec, catalog)
    ctx = roomctx.for_spec(spec, scene.lsau, scene.lphai) if isinstance(spec.floorplan, dict) else None
    out: list[FaceRef] = []
    for sf in (doc.get("room") or {}).get("surfaces") or []:
        n = [float(v) for v in sf.get("normal") or (0.0, 0.0, 0.0)] + [0.0, 0.0, 0.0]
        nx, ny, nz = n[0], n[1], n[2]
        if sf.get("outline"):
            first = sf["outline"][0]
            px, py, pz = float(first.get("x") or 0.0), float(sf.get("y") or 0.0), float(first.get("z") or 0.0)
        else:
            px, py, pz = (float(v) for v in (list(sf.get("origin") or []) + [0.0, 0.0, 0.0])[:3])
        sid, face = str(sf.get("id")), str(sf.get("face") or "")
        room = str(sf["room"]) if sf.get("room") else None
        span = _span_kitchen(sf, ctx)
        if ctx is not None:
            a, b = ctx.placement.to_kitchen(0.0, 0.0), ctx.placement.to_kitchen(nx, nz)
            nx, nz = b[0] - a[0], b[1] - a[1]
            px, pz = ctx.placement.to_kitchen(px, pz)
            out.append(FaceRef(sid, face, None, str(sf.get("structure") or ""), (nx, ny, nz), (px, py, pz), room, span))
        else:
            out.append(FaceRef(sid, face, str(sf.get("wall") or "").removeprefix("WALL-").lower(), None, (nx, ny, nz), (px, py, pz), room, span))
    return out


def _split_faces(pid: np.ndarray, hit: np.ndarray, nw: np.ndarray, world: np.ndarray, all_parts: list,
                 faces: list[FaceRef]) -> tuple[np.ndarray, list[tuple[int, FaceRef]]]:
    """The instance index with each wall face's pixels moved to an index of their own (part, face): pixels of the face's wall whose
    normal is the face's and that lie on its plane. Returns the new index (−1 = background) and the added (wall part index, face)."""
    out = pid.copy()
    added: list[tuple[int, FaceRef]] = []
    nxt = len(all_parts)
    for fc in sorted(faces, key=lambda f: f.span is not None):      # reveals last: a hole's inside is theirs whatever plane it lies near
        own = np.array([face_owner(p, fc) for p in all_parts] + [False], bool)
        n = np.asarray(fc.normal, float)
        if not own.any() or (fc.span is None and (not np.isfinite(n).all() or float(np.linalg.norm(n)) < 0.5)):
            continue
        ys, xs = np.nonzero(hit & own[pid])        # only the pixels of the face's wall are tested (the whole image per face was ~2 s)
        if not len(ys):
            continue
        if fc.span is not None:
            on = _in_span(world[ys, xs], nw[ys, xs], fc.span)
        else:
            on = ((nw[ys, xs] @ n) > FACE_NORMAL_COS) & (np.abs((world[ys, xs] - np.asarray(fc.point, float)) @ n) < FACE_PLANE_MM)
        ys, xs = ys[on], xs[on]
        parts = pid[ys, xs]
        for part in np.unique(parts).tolist():
            sel = parts == part
            out[ys[sel], xs[sel]] = nxt
            added.append((int(part), fc))
            nxt += 1
    return out, added


def _paint_faces(alb: np.ndarray, hit: np.ndarray, pid: np.ndarray, nw: np.ndarray, shade: np.ndarray, all_parts: list,
                 faces: list[FaceColor], world: np.ndarray | None = None) -> None:
    """Give the pixels of each finished face its colour (the albedo's shading kept): pixels of the face's wall whose normal is the face's;
    a reveal's: the pixels of its hole's inside (``world``: the pixels' points, mm; reveals are skipped without it). Reveals go last."""
    for fc in sorted(faces, key=lambda f: f.span is not None):
        own = np.array([face_owner(p, fc) for p in all_parts] + [False], bool)
        if fc.span is not None:
            if world is None:
                continue
            ys, xs = np.nonzero(hit & own[pid])
            on = _in_span(world[ys, xs], nw[ys, xs], fc.span)
            ys, xs = ys[on], xs[on]
            alb[ys, xs] = np.asarray(fc.rgb, float) * shade[ys, xs][:, None]
            continue
        n = np.asarray(fc.normal, float)
        mask = hit & own[pid] & ((nw @ n) > FACE_NORMAL_COS)
        alb[mask] = np.asarray(fc.rgb, float) * shade[mask][:, None]


def render_view(scene: Scene, view: ViewAngle, out_dir: Path, width: int = 1280, height: int = 960,
                legend: dict | None = None, colors: list | None = None, meta: dict | None = None,
                faces: list[FaceColor] | None = None, wall_face_refs: list[FaceRef] | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    scene = view_scene(scene, view)   # structures standing between this camera and the cabinets, door sweeps outside the plan
    camera = Camera(view, width, height)
    zbuf, pid, nid, mesh_n = rasterize(scene, camera)
    nparts = len(scene.parts)
    all_parts = list(scene.parts) + list(scene.meshes)
    hit = pid >= 0

    # nét
    lut = np.array([_JOINED_FACE.index(p.type) if p.type in _JOINED_FACE else 99 for p in all_parts] + [98], np.int16)
    lines = _edges(pid, nid, zbuf, lut[pid])
    if width >= 1600:
        lines[1:, :] |= lines[:-1, :]
        lines[:, 1:] |= lines[:, :-1]
    Image.fromarray(np.where(lines, 0, 255).astype(np.uint8), "L").save(out_dir / "lines.png")

    # depth
    dep8 = np.zeros(zbuf.shape, np.uint8)
    dep16 = np.zeros(zbuf.shape, np.uint16)
    if hit.any():
        z = zbuf[hit]
        zmin, zmax = float(z.min()), float(z.max())
        dep8[hit] = (255 * (1 - (z - zmin) / max(zmax - zmin, 1e-6)) ** 1.0).clip(0, 255).astype(np.uint8)
        dep8[hit] = np.maximum(dep8[hit], 8)
        dep16[hit] = np.clip(z * 1000, 0, 65535).astype(np.uint16)
    Image.fromarray(dep8, "L").save(out_dir / "depth.png")
    Image.fromarray(dep16).save(out_dir / "depth16.png")

    # normal (hệ camera)
    normals_world = np.array([_face_normals(p) for p in scene.parts], float).reshape(-1, 6, 3) if nparts else np.zeros((0, 6, 3))
    ncam = np.stack([normals_world @ camera.r, normals_world @ camera.u, -(normals_world @ camera.f)], axis=-1)
    nimg = np.zeros((height, width, 3), np.uint8)
    box_hit = hit & (pid < nparts)
    nimg[box_hit] = ((ncam[pid[box_hit], nid[box_hit]] * 0.5 + 0.5) * 255).astype(np.uint8)
    mesh_hit = hit & (pid >= nparts)
    if mesh_hit.any():
        nw = mesh_n[mesh_hit].astype(float)
        nc = np.stack([nw @ camera.r, nw @ camera.u, -(nw @ camera.f)], axis=-1)
        nimg[mesh_hit] = ((nc * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)
    Image.fromarray(nimg, "RGB").save(out_dir / "normal.png")

    # mask
    seg = np.zeros((height, width, 3), np.uint8)
    segm = np.zeros((height, width, 3), np.uint8)
    type_lut = np.array([SEGMENT_COLORS.get(p.type, (128, 128, 128)) for p in all_parts], np.uint8)
    mod_lut = np.array([_module_color(p.module) if p.module else (0, 0, 0) for p in all_parts], np.uint8)
    seg[hit] = type_lut[pid[hit]]
    segm[hit] = mod_lut[pid[hit]]
    Image.fromarray(seg, "RGB").save(out_dir / "seg.png")
    Image.fromarray(segm, "RGB").save(out_dir / "seg_module.png")
    # structures of an imported floorplan: their own mask (colour by kind), everything else black; one file so a view can be edited layer by layer
    is_struct = np.array([p.type.startswith("structure-") for p in all_parts] + [False], bool)
    segs = np.zeros((height, width, 3), np.uint8)
    sm = hit & is_struct[pid]
    segs[sm] = type_lut[pid[sm]]
    Image.fromarray(segs, "RGB").save(out_dir / "seg_structure.png")

    camera_info = {"view": view.model_dump(mode="json"), **camera.json()}
    (out_dir / "camera.json").write_text(json.dumps(camera_info, ensure_ascii=False, indent=2), encoding="utf-8")
    visible = sorted({all_parts[i].module for i in np.unique(pid[hit]) if all_parts[i].module})

    # instance: số nguyên, không khử răng cưa, đã qua z-buffer (chỉ phần nhìn thấy)
    nw = np.zeros((height, width, 3))
    nw[box_hit] = normals_world[pid[box_hit], nid[box_hit]]
    if mesh_hit.any():
        nw[mesh_hit] = mesh_n[mesh_hit]
    ipid, split = pid, []
    world = None
    if wall_face_refs or any(f.span is not None for f in faces or []):     # the pixels' points (mm): wall faces and reveals are found by them
        ys0, xs0 = np.mgrid[0:height, 0:width]
        zc = np.where(hit, zbuf, 0.0)
        world = camera.unproject(xs0 + 0.5, ys0 + 0.5, zc) * 1000
    if wall_face_refs and world is not None:    # each wall face its own instance (layer): "<wall part>#<face>", with the face's id
        ipid, split = _split_faces(pid, hit, nw, world, all_parts, wall_face_refs)
    if len(all_parts) + len(split) >= 65535:
        raise InvalidInput("Too many parts for a 16-bit instance image", code="too-many-parts")
    inst = (ipid + 1).astype(np.uint16)
    Image.fromarray(inst).save(out_dir / "instance.png")
    vals, counts = np.unique(ipid[hit], return_counts=True)
    instances = []
    for v, n in zip(vals.tolist(), counts.tolist()):
        ys, xs = np.nonzero(ipid == v)
        box = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        if v < len(all_parts):
            p = all_parts[v]
            instances.append({"value": v + 1, "id": p.id, "module": p.module, "type": p.type, "pixels": n, "bbox": box})
        else:
            wall_part, fc = split[v - len(all_parts)]
            p = all_parts[wall_part]
            instances.append({"value": v + 1, "id": face_part_id(p.id, fc.face), "module": p.module, "type": "wall-face", "pixels": n, "bbox": box,
                              "surface": fc.id, "parent": p.id, "parentType": p.type})
    (out_dir / "instances.json").write_text(json.dumps({"encoding": "instance.png 16-bit: pixel = value, 0 = background",
                                                        "width": width, "height": height, "instances": instances},
                                                       ensure_ascii=False, indent=1), encoding="utf-8")

    # albedo: màu vật liệu × đổ bóng Lambert đơn giản, nét làm tối nhẹ
    col = np.array(colors if colors is not None else [_hex_rgb_part(p) for p in all_parts], float).reshape(-1, 3)
    shade = 0.74 + 0.26 * np.clip(nw @ _DARK, 0, 1)
    alb = np.full((height, width, 3), 244.0)
    alb[hit] = col[pid[hit]] * shade[hit][:, None]
    if faces:
        _paint_faces(alb, hit, pid, nw, shade, all_parts, faces, world)
    alb[lines] *= 0.72
    Image.fromarray(alb.clip(0, 255).astype(np.uint8), "RGB").save(out_dir / "albedo.png")

    files = ["lines.png", "depth.png", "depth16.png", "normal.png", "seg.png", "seg_module.png", "seg_structure.png", "camera.json",
             "instance.png", "instances.json", "albedo.png"]
    key = render_key(scene, view, width, height)
    manifest = {**(meta or {}), "view": out_dir.name, "renderKey": key, "sceneHash": scene_hash(scene)[:16],
                "width": width, "height": height, "files": files + ["manifest.json"], "camera": "camera.json",
                "instanceEncoding": "uint16 = part index + 1", "instanceFormat": INSTANCE_FORMAT}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"dir": str(out_dir), "files": files + ["manifest.json"], "renderKey": key,
            "imageOverlay": round(float(hit.mean()), 3), "editableModule": visible}


def _hex_rgb_part(p) -> tuple[int, int, int]:
    from .geometry import COLORS
    h = COLORS.get(p.type, "#c0c0c0").lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def part_colors(spec: KitchenSpec, scene: Scene) -> list[tuple[int, int, int]]:
    """Màu albedo từng chi tiết theo vật liệu trong spec (cùng nguồn với prompt và three.js)."""
    from . import layers, vocab
    out = []
    for p in list(scene.parts) + list(scene.meshes):
        if p.type.startswith("structure-"):
            out.append(_hex_rgb_part(p))
            continue
        _, name = layers.material_slot(spec, p.module, p.type)
        c = vocab.color(name) if p.type not in ("sink", "cooktop", "oven", "glass-door", "plinth", "fridge", "faucet", "hood", "painting") else None
        out.append(vocab.hex_rgb(c) if c else _hex_rgb_part(p))
    return out


def render_views(spec: KitchenSpec, out_root: Path, views: list[str] | None = None,
                 width: int = 1280, height: int = 960, meta: dict[str, Any] | None = None, catalog: Catalog = builtin.CATALOG,
                 view_angles: dict[str, Any] | None = None) -> dict[str, Any]:
    """``view_angles``: the camera views of ``spec`` when the caller has them already (planning them again costs about a second)."""
    scene = compile_spec(spec, catalog)
    colors = part_colors(spec, scene)
    all_views = view_angles if view_angles is not None else views_of(spec, catalog)
    chosen = views or list(all_views)
    unknown = [v for v in chosen if v not in all_views]
    if unknown:
        raise InvalidInput(f"No view {unknown}; there are {list(all_views)}", code="view-not-found", params={"view": ", ".join(unknown), "views": ", ".join(all_views)})
    out_root.mkdir(parents=True, exist_ok=True)
    legend = {"seg": {k: list(v) for k, v in SEGMENT_COLORS.items()},
              "seg_structure": {k: list(v) for k, v in SEGMENT_COLORS.items() if k.startswith("structure-")},
              "seg_module": {**{m.id: list(_module_color(m.id)) for m in spec.module},
                             **{x.id: list(_module_color(x.id)) for x in spec.moldings}}}
    (out_root / "legend.json").write_text(json.dumps(legend, ensure_ascii=False, indent=2), encoding="utf-8")
    faces = face_colors(spec, catalog, all_views)
    refs = wall_faces(spec, catalog, scene, all_views)
    results = {v: render_view(scene, all_views[v], out_root / v, width, height, colors=colors, meta=meta, faces=faces, wall_face_refs=refs)
               for v in chosen}
    return {"outDir": str(out_root), "views": results, "legend": "legend.json"}


def face_colors(spec: KitchenSpec, catalog: Catalog = builtin.CATALOG, views: dict[str, Any] | None = None) -> list[FaceColor]:
    """The wall faces with a finish of their own and its colour (the three.js export's surface materials), in the render's kitchen
    frame. Empty without ``spec.surfaceMaterials``."""
    if not spec.surfaceMaterials:
        return []
    from . import roomctx
    from .threejs_export import export
    doc = export(spec, catalog=catalog, views=views)
    room = doc.get("room") or {}
    colours = {m.get("id"): m.get("color") for m in doc.get("materials") or [] if isinstance(m, dict)}
    scene = compile_spec(spec, catalog)
    ctx = roomctx.for_spec(spec, scene.lsau, scene.lphai) if isinstance(spec.floorplan, dict) else None
    out: list[FaceColor] = []
    for sf in room.get("surfaces") or []:
        hexc = colours.get(sf.get("materialId")) if str(sf.get("materialId") or "").startswith("MAT-SURFACE-") else None
        if not isinstance(hexc, str) or not hexc.startswith("#") or len(hexc) < 7:
            continue
        rgb = (int(hexc[1:3], 16), int(hexc[3:5], 16), int(hexc[5:7], 16))
        n = [float(v) for v in sf.get("normal") or (0.0, 0.0, 0.0)]
        nx, ny, nz = (n + [0.0, 0.0, 0.0])[:3] if len(n) == 3 else (n[0], 0.0, n[1]) if len(n) == 2 else (0.0, 0.0, 0.0)
        span = _span_kitchen(sf, ctx)
        if ctx is not None:
            a = ctx.placement.to_kitchen(0.0, 0.0)
            b = ctx.placement.to_kitchen(nx, nz)
            nx, nz = b[0] - a[0], b[1] - a[1]
            out.append(FaceColor(None, str(sf.get("structure") or ""), (nx, ny, nz), rgb, span))
        else:
            wall = str(sf.get("wall") or "").removeprefix("WALL-").lower()
            out.append(FaceColor(wall, None, (nx, ny, nz), rgb, span))
    return out
