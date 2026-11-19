"""Base images of a view: render, layers, masks, imported and approved base photographs."""
from __future__ import annotations

from typing import Any

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import threading

from PIL import Image
import numpy as np
import numpy.typing as npt

from .. import geometry, imaging, layers, render, roomctx
from ..errors import InvalidInput
from ..jsonview import as_dict
from .common import Component, VIEW_COLORS


@dataclass(frozen=True)
class _Built:
    """What every base-image request of one stored revision needs, computed once: the spec, its catalog, the compiled scene, the
    camera views (planning them is the slow part: ~1 s), the wall faces and the layer catalogue. Callers must not mutate these."""
    spec: Any
    rev: int
    catalog: Any
    scene: Any
    views: dict[str, Any]
    faces: list[Any]
    catalogue: list[dict[str, Any]]
    placement: Any = None           # an imported floorplan: kitchen frame -> its room frame (the 3D view's), else None (the same frame)


class BaseImages(Component):
    CACHE_SIZE = 8          # revisions kept built (each a few MB at most)

    def __init__(self, env: Any) -> None:
        super().__init__(env)
        self._cache: OrderedDict[tuple[Any, ...], _Built] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._build_locks: dict[tuple[Any, ...], threading.Lock] = {}    # one build per revision at a time; same for each view's render
        self._render_locks: dict[tuple[Any, ...], threading.Lock] = {}

    @staticmethod
    def _lock_of(table: dict[tuple[Any, ...], threading.Lock], guard: threading.Lock, key: tuple[Any, ...]) -> threading.Lock:
        with guard:
            return table.setdefault(key, threading.Lock())

    def built(self, did: str, rev: int | None) -> _Built:
        """The revision built for base-image work, from the cache when the stored spec and the catalog have not changed since.
        Requests arriving together (a view switch fires layers, masks and picks at once) wait for one build instead of each doing it."""
        spec, r = self.store.get(did, rev)
        stamp_of = getattr(self.store, "catalog_stamp", None)
        stamp = stamp_of() if callable(stamp_of) else None
        digest = hashlib.sha1(spec.model_dump_json().encode("utf-8")).hexdigest()
        key = (did, r, stamp, digest)
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
        with self._lock_of(self._build_locks, self._cache_lock, key):
            with self._cache_lock:
                hit = self._cache.get(key)
                if hit is not None:
                    return hit
            dc = self.env.design_catalog(did, r)          # the catalog this revision is built with (its snapshot)
            scene = geometry.compile_spec(spec, dc)
            views = geometry.views_of(spec, dc)
            faces = render.wall_faces(spec, dc, scene, views)    # the same catalog the render's instance image is made with
            try:
                ctx = roomctx.for_spec(spec, scene.lsau, scene.lphai) if isinstance(spec.floorplan, dict) else None
            except ValueError:
                ctx = None
            out = _Built(spec, r, dc, scene, views, faces, layers.catalogue(spec, scene, faces), ctx.placement if ctx else None)
            with self._cache_lock:
                self._cache[key] = out
                self._cache.move_to_end(key)
                while len(self._cache) > self.CACHE_SIZE:
                    old, _ = self._cache.popitem(last=False)
                    self._build_locks.pop(old, None)
            return out

    def ensure_render(self, did: str, rev: int | None, view: str, width: int | None = None, height: int | None = None):
        b = self.built(did, rev)
        spec, r, dc, scene, views = b.spec.model_copy(deep=True), b.rev, b.catalog, b.scene, b.views    # callers get their own spec, as before
        if view not in views:
            raise InvalidInput(f"No view {view!r}; there are: {', '.join(views)}", code="view-not-found", params={"view": view, "views": ', '.join(views)})
        d = self.view_dir(did, r, view)
        man = d / "manifest.json"

        def current() -> dict[str, Any] | None:
            if not man.exists():
                return None
            m = json.loads(man.read_text(encoding="utf-8"))
            w, h = width or m["width"], height or m["height"]
            if m.get("renderKey") == render.render_key(scene, views[view], w, h) and (d / "instance.png").exists() \
                    and m.get("instanceFormat", 1) >= render.INSTANCE_FORMAT:
                return m
            return None

        m = current()
        if m is not None:
            return spec, r, scene, d, m
        w, h = width or VIEW_COLORS[0], height or VIEW_COLORS[1]
        if not (256 <= w <= 4096 and 256 <= h <= 4096):
            raise InvalidInput("width/height must be 256-4096", code="bad-image-size")
        with self._lock_of(self._render_locks, self._cache_lock, (str(d),)):   # one render of a view at a time; the others reuse it
            m = current()
            if m is not None:
                return spec, r, scene, d, m
            render.render_views(spec, d.parent, [view], w, h, meta={"designId": did, "rev": r}, catalog=dc, view_angles=views)
            return spec, r, scene, d, json.loads(man.read_text(encoding="utf-8"))

    def layers(self, did: str, view: str, rev: int | None = None, all_layers: bool = False) -> dict[str, Any]:
        spec, r, scene, d, man = self.ensure_render(did, rev, view)
        cat = self.built(did, r).catalogue
        _, meta = imaging.load_instances(d)
        px: dict[str, int] = {}
        for i in meta["instances"]:           # a wall face's pixels also count for the wall part they were split from
            for key in (i["id"], i.get("parent")):
                if key:
                    px[key] = px.get(key, 0) + int(i["pixels"])
        out: list[dict[str, Any]] = []
        for x in cat:
            ids = x.get("component") or [x["id"]]
            n = sum(px.get(i, 0) for i in ids)
            if n or all_layers:
                note = None
                try:
                    op = layers.design_op(spec, x, "?", scene) if x.get("materialLocked") else None
                except ValueError as e:  # not expressible in the spec: tell the UI why
                    op, note = None, str(e)
                out.append({**x, "pixels": n, "designEdit": op[1] if op else None, **({"designEditNote": note} if note else {})})
        return {"id": did, "rev": r, "view": view, "renderKey": man["renderKey"], "width": man["width"], "height": man["height"],
                "dir": str(d), "layers": out, "baseImage": self.reference(did, view, man["renderKey"], d)[1]}

    def mask_png(self, did: str, view: str, layer_id: str, rev: int | None = None) -> bytes:
        import io
        _spec, r, _scene, d, _ = self.ensure_render(did, rev, view)
        _, ids = layers.resolve(self.built(did, r).catalogue, layer_id)
        buf = io.BytesIO()
        Image.fromarray(imaging.mask_of(d, ids).astype(np.uint8) * 255, "L").save(buf, "PNG")
        return buf.getvalue()

    def pick(self, did: str, view: str, x: int, y: int, rev: int | None = None, radius: int = 0) -> dict[str, Any]:
        """The part at a pixel and the layers holding it, with ``point``: where the pixel lies on the floor plan ({x, z}, mm, in the frame
        of the 3D view, as its right click gives it; None when the pixel's ray never meets the floor) and ``floor``: true when the pixel
        shows the floor or nothing (a run can be drawn there)."""
        _spec, r, _scene, d, man = self.ensure_render(did, rev, view)
        hit = imaging.pick(d, x, y, max(0, min(int(radius), 24)))
        point = self.floor_point(did, r, view, d, man, x, y, hit is not None)
        floor = hit is None or hit.get("type") == "floor"
        if not hit:
            return {"part": None, "layers": [], "point": point, "floor": floor}
        cat = self.built(did, r).catalogue
        groups = [g["id"] for g in cat if g["id"] == hit["id"] or hit["id"] in (g.get("component") or [])]
        groups.sort(key=lambda g: not g.startswith("surface:"))      # a wall face: its own layer first
        return {"part": hit, "layers": groups, "point": point, "floor": floor}

    def floor_point(self, did: str, rev: int, view: str, d: Path, man: dict[str, Any], x: int, y: int, on_part: bool) -> dict[str, float] | None:
        """The pixel's point on the plan (x, z; mm; the 3D view's frame): where its ray meets what it shows (``depth16.png``), or the floor
        (y = 0) when it shows nothing. The render's camera is rebuilt from its view, so the point is exact for the picture's own pixels."""
        b = self.built(did, rev)
        cam = render.Camera(b.views[view], int(man["width"]), int(man["height"]))
        px, py = np.array([x + 0.5]), np.array([y + 0.5])
        z = 0.0
        if on_part:
            with Image.open(d / "depth16.png") as im:
                z = float(np.asarray(im)[y, x]) / 1000.0
        if z > 0:
            p = cam.unproject(px, py, np.array([z]))[0]
        else:
            a, e = cam.unproject(px, py, np.array([0.0]))[0], cam.unproject(px, py, np.array([1.0]))[0]
            ray = e - a
            if ray[1] > -1e-9:          # looking level or up: the ray never meets the floor
                return None
            p = a + ray * (-a[1] / ray[1])
        mx, mz = float(p[0]) * 1000, float(p[2]) * 1000
        if b.placement is not None:
            mx, mz = b.placement.to_room(mx, mz)
        return {"x": round(mx, 1), "z": round(mz, 1)}

    def save_beauty(self, did: str, view: str, image: bytes, rev: int | None = None) -> dict[str, Any]:
        """Ảnh render three.js (trình duyệt) -> beauty.png của rev/góc; dùng làm ảnh gốc khi chưa có ảnh AI đã duyệt."""
        _spec, r, _scene, d, man = self.ensure_render(did, rev, view)
        im = self._fit_to_render(image, man)
        W, H = man["width"], man["height"]
        im.save(d / "beauty.png")
        k = imaging.edge_alignment(np.array(im), imaging.read(d / "lines.png", "L"))
        info = {"designId": did, "rev": r, "view": view, "renderKey": man["renderKey"], "size": [W, H], "lineMatch": k,
                "source": "three.js (trình duyệt)"}
        (d / "beauty.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**info, "dir": str(d)}

    @staticmethod
    def _fit_to_render(image: bytes, man: dict[str, Any], fit: str = "reject") -> Image.Image:
        """Decode an uploaded image and fit it to the control-render size.

        fit="reject" refuses a different aspect ratio; "crop" cuts the centre to the render ratio; "pad" keeps the whole
        image and fills the border with its edge colour. Crop/pad change the scale, so the line check may report a mismatch.
        """
        if fit not in ("reject", "crop", "pad"):
            raise InvalidInput("fit must be reject, crop or pad", code="bad-fit")
        import io
        try:
            with Image.open(io.BytesIO(image)) as f:
                im = f.convert("RGB")
        except (OSError, ValueError) as e:  # PIL: UnidentifiedImageError, truncated or malformed data
            raise InvalidInput("The image cannot be read (PNG/JPEG needed)", code="bad-image") from e
        W, H = man["width"], man["height"]
        if im.size != (W, H):
            iw, ih = im.size
            if abs(iw / ih - W / H) > 0.01:
                if fit == "reject":
                    raise InvalidInput(f"Image {iw}x{ih} has another aspect ratio than the control images {W}x{H}", code="bad-image-ratio",
                                           params={"size": f"{iw}×{ih}", "control": f"{W}×{H}"})
                if fit == "crop":
                    cw, ch = (round(ih * W / H), ih) if iw / ih > W / H else (iw, round(iw * H / W))
                    left, top = (iw - cw) // 2, (ih - ch) // 2
                    im = im.crop((left, top, left + cw, top + ch))
                else:
                    cw, ch = (iw, round(iw * H / W)) if iw / ih > W / H else (round(ih * W / H), ih)
                    arr: npt.NDArray[np.uint8] = np.asarray(im, dtype=np.uint8)
                    edge = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]]).mean(axis=0).astype(np.uint8)  # pyright: ignore[reportUnknownMemberType] (numpy stubs)
                    canvas = Image.new("RGB", (cw, ch), tuple(int(v) for v in edge))
                    canvas.paste(im, ((cw - iw) // 2, (ch - ih) // 2))
                    im = canvas
            im = im.resize((W, H), Image.Resampling.LANCZOS)
        return im

    def import_base(self, did: str, view: str, image: bytes, rev: int | None = None, source: str = "external image", fit: str = "reject") -> dict[str, Any]:
        """Replace the base image of a rev/view with an externally generated image (e.g. a fully lit ChatGPT render).

        The image is stored as base_imported.png next to the control renders. It is used as the base image until a job
        accepted after the import takes over (see reference).
        """
        _spec, r, _scene, d, man = self.ensure_render(did, rev, view)
        im = self._fit_to_render(image, man, fit)
        im.save(d / "base_imported.png")
        match = imaging.edge_alignment(np.array(im), imaging.read(d / "lines.png", "L"))
        info = {"designId": did, "rev": r, "view": view, "renderKey": man["renderKey"], "size": [man["width"], man["height"]],
                "lineMatch": match, "source": source, "fit": fit, "importedAt": self.runtime.now()}
        (d / "base_imported.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**info, "dir": str(d)}

    def clear_imported_base(self, did: str, view: str, rev: int | None = None) -> dict[str, Any]:
        """Drop the imported base image of a rev/view so the default base image order applies again."""
        _spec, r, _scene, d, _man = self.ensure_render(did, rev, view)
        removed = False
        for name in ("base_imported.png", "base_imported.json"):
            if (d / name).exists():
                (d / name).unlink()
                removed = True
        return {"designId": did, "rev": r, "view": view, "removed": removed, "dir": str(d)}

    @staticmethod
    def _imported_meta(d: Path) -> dict[str, Any] | None:
        """Metadata of the imported base image in a render folder, or None when there is no valid import."""
        if not (d / "base_imported.png").exists():
            return None
        try:
            meta: dict[str, Any] = json.loads((d / "base_imported.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return meta if meta.get("importedAt") else None

    @staticmethod
    def _key_of(j: dict[str, Any]) -> str:
        """renderKey hình học mà ẢNH KẾT QUẢ của job khớp: job sửa hình cho ảnh của thiết kế mới."""
        result: dict[str, Any] = as_dict(j["result"]) or {}
        return str(result.get("newRenderKey") or j["render_key"]) if j["kind"] == "geometry_edit" else str(j["render_key"])

    def reference(self, did: str, view: str, key: str, d: Path) -> tuple[Path, dict[str, Any]]:
        acc = [j for j in self.store.list_jobs(did, view, "accepted", 200) if self._key_of(j) == key]
        acc.sort(key=lambda j: (j["result"].get("acceptNow", ""), j["updated_at"]), reverse=True)
        imported = self._imported_meta(d)
        if acc and not (imported and acc[0]["result"].get("acceptNow", "") <= imported["importedAt"]):
            j = acc[0]  # the newest accepted job wins unless a base image was imported after it
            return Path(j["result"]["dir"]) / "composite.png", {"type": "job", "jobId": j["id"]}
        if imported:
            return d / "base_imported.png", {"type": "imported", "lineMatch": imported.get("lineMatch"), "importedAt": imported["importedAt"]}
        if (d / "beauty.png").exists():
            return d / "beauty.png", {"type": "beauty"}
        return d / "albedo.png", {"type": "albedo"}

    def pick_reference(self, did: str, view: str, key: str, d: Path, reference: str | None) -> tuple[Path, dict[str, Any]]:
        if reference in (None, "", "auto"):
            return self.reference(did, view, key, d)
        if reference == "albedo":
            return d / "albedo.png", {"type": "albedo"}
        if reference == "imported":
            if self._imported_meta(d) is None:
                raise InvalidInput("No imported base image for this view yet", code="no-imported-image")
            return d / "base_imported.png", {"type": "imported"}
        if reference == "beauty":
            if not (d / "beauty.png").exists():
                raise InvalidInput("No three.js render for this view yet", code="no-beauty-image")
            return d / "beauty.png", {"type": "beauty"}
        j = self.store.get_job(reference)
        if j["design_id"] != did or j["view"] != view:
            raise InvalidInput("The reference image belongs to another design or view", code="reference-other-view")
        if self._key_of(j) != key:
            raise InvalidInput("The reference image was made from other geometry or camera (renderKey differs)", code="reference-stale")
        if j["status"] not in ("accepted", "needs-review"):
            raise InvalidInput(f"Job {reference} has no usable image yet (status {j['status']})", code="reference-not-ready", params={"job": reference, "status": j["status"]})
        return Path(j["result"]["dir"]) / "composite.png", {"type": "job", "jobId": j["id"]}
