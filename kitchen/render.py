"""Render ảnh điều khiển (control maps) cho AI: nét, depth, normal, mask — không cần GPU/trình duyệt.

Rasterizer phần mềm bằng numpy trên các khối hộp do compiler sinh ra:
- lines.png      : nét đen trên nền trắng (biên chi tiết + cạnh gãy khối)
- depth.png      : 8-bit, gần = sáng (quy ước ControlNet depth); depth16.png: 16-bit, mm
- normal.png     : normal trong hệ camera, RGB = n*0.5+0.5 (x phải, y lên, z hướng về camera)
- seg.png        : mask theo loại chi tiết (màu cố định, xem legend.json)
- seg_module.png : mask theo module (mỗi module một màu, xem legend.json)
- seg_structure.png : mask riêng cho phần tử của mặt bằng đã nhập (tường, cột, cửa, thang… theo loại; còn lại đen)
- camera.json    : nội/ngoại tham số camera để chiếu ngược sau này
- instance.png   : 16-bit, giá trị = chỉ số chi tiết + 1 (0 = nền); bảng tra trong instances.json (ID chi tiết = layer ID)
- albedo.png     : màu vật liệu × đổ bóng đơn giản, cùng rasterizer nên khớp mask từng pixel (ảnh khởi tạo / xem trước)
- manifest.json  : designId, rev, renderKey (băm hình học + camera + kích thước), danh sách file
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from . import runs
from .geometry import Scene, compile_spec, views_of
from .palette import SEGMENT_COLORS, module_color as _module_color
from .spec import ViewAngle, KitchenSpec

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
    def __init__(self, view: ViewAngle, width: int, height: int):
        self.p = np.array(view.position, float)
        t = np.array(view.lookAt, float)
        f = t - self.p
        f /= np.linalg.norm(f)
        up = np.array([0.0, 1.0, 0.0])
        if abs(f @ up) > 0.999:  # nhìn thẳng xuống/lên: lấy trục -z làm "lên" của ảnh
            up = np.array([0.0, 0.0, -1.0])
        r = np.cross(f, up); r /= np.linalg.norm(r)
        u = np.cross(r, f)
        self.f, self.r, self.u = f, r, u
        self.w, self.h = width, height
        self.focal = (height / 2) / math.tan(math.radians(view.verticalFov) / 2)

    def to_camera(self, pts: np.ndarray) -> np.ndarray:
        d = pts - self.p
        return np.stack([d @ self.r, d @ self.u, d @ self.f], axis=-1)

    def json(self) -> dict:
        R = np.stack([self.r, -self.u, self.f])  # hàng: trục camera (x phải, y xuống, z tới) theo OpenCV
        return {"width": self.w, "height": self.h, "fx": self.focal, "fy": self.focal, "cx": self.w / 2, "cy": self.h / 2,
                "R_world_to_cam": R.tolist(), "t": (-R @ self.p).tolist(), "position_m": self.p.tolist(),
                "convention": "OpenCV: x phải, y xuống, z hướng nhìn; toạ độ thế giới tính bằng mét"}


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
            if np.dot(fnormals[fi], camera.p - center) <= 0:
                continue
            poly = _clip_near([cc[i] for i in idx])
            if len(poly) < 3:
                continue
            P = np.array(poly)
            sx = W / 2 + camera.focal * P[:, 0] / P[:, 2]
            sy = H / 2 - camera.focal * P[:, 1] / P[:, 2]
            iz = 1.0 / P[:, 2]
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
                z = 1.0 / (w0 * iz[tri[0]] + w1 * iz[tri[1]] + w2 * iz[tri[2]])
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
            if np.dot(n, camera.p - tri_w.mean(0)) < 0:
                n = -n  # pháp tuyến hướng về camera
            poly = _clip_near([VC[a], VC[b], VC[c]])
            if len(poly) < 3:
                continue
            P = np.array(poly)
            sx = W / 2 + camera.focal * P[:, 0] / P[:, 2]
            sy = H / 2 - camera.focal * P[:, 1] / P[:, 2]
            iz = 1.0 / P[:, 2]
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
                z = 1.0 / (w0 * iz[tri[0]] + w1 * iz[tri[1]] + w2 * iz[tri[2]])
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


def render_key(scene: Scene, view: ViewAngle, width: int, height: int) -> str:
    v = json.dumps(view.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(f"{scene_hash(scene)}|{v}|{width}x{height}".encode()).hexdigest()[:16]


_DARK = np.array([0.35, 0.85, 0.40]) / np.linalg.norm([0.35, 0.85, 0.40])


def render_view(scene: Scene, view: ViewAngle, out_dir: Path, width: int = 1280, height: int = 960,
                legend: dict | None = None, colors: list | None = None, meta: dict | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
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
    if len(all_parts) >= 65535:
        raise ValueError("Quá nhiều chi tiết cho instance 16-bit")
    inst = (pid + 1).astype(np.uint16)
    Image.fromarray(inst).save(out_dir / "instance.png")
    vals, counts = np.unique(pid[hit], return_counts=True)
    instances = []
    for v, n in zip(vals.tolist(), counts.tolist()):
        ys, xs = np.nonzero(pid == v)
        p = all_parts[v]
        instances.append({"value": v + 1, "id": p.id, "module": p.module, "type": p.type, "pixels": n,
                          "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]})
    (out_dir / "instances.json").write_text(json.dumps({"encoding": "instance.png 16-bit: giá trị = value, 0 = nền",
                                                        "width": width, "height": height, "instances": instances},
                                                       ensure_ascii=False, indent=1), encoding="utf-8")

    # albedo: màu vật liệu × đổ bóng Lambert đơn giản, nét làm tối nhẹ
    col = np.array(colors if colors is not None else [_hex_rgb_part(p) for p in all_parts], float).reshape(-1, 3)
    nw = np.zeros((height, width, 3))
    nw[box_hit] = normals_world[pid[box_hit], nid[box_hit]]
    if mesh_hit.any():
        nw[mesh_hit] = mesh_n[mesh_hit]
    shade = 0.74 + 0.26 * np.clip(nw @ _DARK, 0, 1)
    alb = np.full((height, width, 3), 244.0)
    alb[hit] = col[pid[hit]] * shade[hit][:, None]
    alb[lines] *= 0.72
    Image.fromarray(alb.clip(0, 255).astype(np.uint8), "RGB").save(out_dir / "albedo.png")

    files = ["lines.png", "depth.png", "depth16.png", "normal.png", "seg.png", "seg_module.png", "seg_structure.png", "camera.json",
             "instance.png", "instances.json", "albedo.png"]
    key = render_key(scene, view, width, height)
    manifest = {**(meta or {}), "view": out_dir.name, "renderKey": key, "sceneHash": scene_hash(scene)[:16],
                "width": width, "height": height, "files": files + ["manifest.json"], "camera": "camera.json",
                "instanceEncoding": "uint16 = chỉ số chi tiết + 1"}
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
        c = vocab.color(name) if p.type not in ("sink", "cooktop", "oven", "glass-door", "plinth", "fridge", "faucet", "hood") else None
        out.append(vocab.hex_rgb(c) if c else _hex_rgb_part(p))
    return out


def render_views(spec: KitchenSpec, out_root: Path, views: list[str] | None = None,
                 width: int = 1280, height: int = 960, meta: dict | None = None) -> dict:
    scene = compile_spec(spec)
    colors = part_colors(spec, scene)
    all_views = views_of(spec)
    chosen = views or list(all_views)
    unknown = [v for v in chosen if v not in all_views]
    if unknown:
        raise ValueError(f"Không có góc nhìn: {unknown}. Có: {list(all_views)}")
    out_root.mkdir(parents=True, exist_ok=True)
    legend = {"seg": {k: list(v) for k, v in SEGMENT_COLORS.items()},
              "seg_structure": {k: list(v) for k, v in SEGMENT_COLORS.items() if k.startswith("structure-")},
              "seg_module": {**{m.id: list(_module_color(m.id)) for m in spec.module},
                             **{x.id: list(_module_color(x.id)) for x in spec.moldings}}}
    (out_root / "legend.json").write_text(json.dumps(legend, ensure_ascii=False, indent=2), encoding="utf-8")
    results = {v: render_view(scene, all_views[v], out_root / v, width, height, colors=colors, meta=meta) for v in chosen}
    return {"outDir": str(out_root), "views": results, "legend": "legend.json"}
