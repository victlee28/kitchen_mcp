"""Base images of a view: render, layers, masks, imported and approved base photographs."""
from __future__ import annotations

from pathlib import Path
import json

from PIL import Image
import numpy as np

from .. import geometry, imaging, layers, render
from ..errors import InvalidInput
from .common import JobsContext, VIEW_COLORS


class BaseImages(JobsContext):
    def ensure_render(self, did: str, rev: int | None, view: str, width: int | None = None, height: int | None = None):
        spec, r = self.store.get(did, rev)
        views = geometry.views_of(spec)
        if view not in views:
            raise InvalidInput(f"Không có góc nhìn '{view}'. Có: {', '.join(views)}")
        d = self._render_dir(did, r, view)
        man = d / "manifest.json"
        scene = geometry.compile_spec(spec)
        if man.exists():
            m = json.loads(man.read_text(encoding="utf-8"))
            w, h = width or m["width"], height or m["height"]
            if m.get("renderKey") == render.render_key(scene, views[view], w, h) and (d / "instance.png").exists():
                return spec, r, scene, d, m
        w, h = width or VIEW_COLORS[0], height or VIEW_COLORS[1]
        if not (256 <= w <= 4096 and 256 <= h <= 4096):
            raise InvalidInput("width/height phải trong 256–4096")
        render.render_views(spec, d.parent, [view], w, h, meta={"designId": did, "rev": r})
        return spec, r, scene, d, json.loads(man.read_text(encoding="utf-8"))

    def layers(self, did: str, view: str, rev: int | None = None, all_layers: bool = False) -> dict:
        spec, r, scene, d, man = self.ensure_render(did, rev, view)
        _, meta = imaging.load_instances(d)
        px = {i["id"]: i["pixels"] for i in meta["instances"]}
        out = []
        for x in layers.catalogue(spec, scene):
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
                "dir": str(d), "layers": out, "baseImage": self._reference(did, view, man["renderKey"], d)[1]}

    def mask_png(self, did: str, view: str, layer_id: str, rev: int | None = None) -> bytes:
        import io
        spec, r, scene, d, _ = self.ensure_render(did, rev, view)
        _, ids = layers.resolve(layers.catalogue(spec, scene), layer_id)
        buf = io.BytesIO()
        Image.fromarray(imaging.mask_of(d, ids).astype(np.uint8) * 255, "L").save(buf, "PNG")
        return buf.getvalue()

    def pick(self, did: str, view: str, x: int, y: int, rev: int | None = None, radius: int = 0) -> dict:
        spec, r, scene, d, _ = self.ensure_render(did, rev, view)
        hit = imaging.pick(d, x, y, max(0, min(int(radius), 24)))
        if not hit:
            return {"part": None, "layers": []}
        cat = layers.catalogue(spec, scene)
        groups = [g["id"] for g in cat if g["id"] == hit["id"] or hit["id"] in (g.get("component") or [])]
        return {"part": hit, "layers": groups}

    def save_beauty(self, did: str, view: str, image: bytes, rev: int | None = None) -> dict:
        """Ảnh render three.js (trình duyệt) -> beauty.png của rev/góc; dùng làm ảnh gốc khi chưa có ảnh AI đã duyệt."""
        import io
        spec, r, scene, d, man = self.ensure_render(did, rev, view)
        im = self._fit_to_render(image, man)
        W, H = man["width"], man["height"]
        im.save(d / "beauty.png")
        k = imaging.edge_alignment(np.array(im), imaging.read(d / "lines.png", "L"))
        info = {"designId": did, "rev": r, "view": view, "renderKey": man["renderKey"], "size": [W, H], "lineMatch": k,
                "source": "three.js (trình duyệt)"}
        (d / "beauty.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**info, "dir": str(d)}

    @staticmethod
    def _fit_to_render(image: bytes, man: dict, fit: str = "reject") -> Image.Image:
        """Decode an uploaded image and fit it to the control-render size.

        fit="reject" refuses a different aspect ratio; "crop" cuts the centre to the render ratio; "pad" keeps the whole
        image and fills the border with its edge colour. Crop/pad change the scale, so the line check may report a mismatch.
        """
        if fit not in ("reject", "crop", "pad"):
            raise InvalidInput("fit phải là reject, crop hoặc pad")
        import io
        try:
            with Image.open(io.BytesIO(image)) as f:
                im = f.convert("RGB")
        except (OSError, ValueError) as e:  # PIL: UnidentifiedImageError, truncated or malformed data
            raise InvalidInput("Ảnh không đọc được (cần PNG/JPEG)") from e
        W, H = man["width"], man["height"]
        if im.size != (W, H):
            iw, ih = im.size
            if abs(iw / ih - W / H) > 0.01:
                if fit == "reject":
                    raise InvalidInput(f"Ảnh {iw}×{ih} khác tỉ lệ ảnh điều khiển {W}×{H}; chọn cắt/thêm viền hoặc tạo lại đúng tỉ lệ")
                if fit == "crop":
                    cw, ch = (round(ih * W / H), ih) if iw / ih > W / H else (iw, round(iw * H / W))
                    left, top = (iw - cw) // 2, (ih - ch) // 2
                    im = im.crop((left, top, left + cw, top + ch))
                else:
                    cw, ch = (iw, round(iw * H / W)) if iw / ih > W / H else (round(ih * W / H), ih)
                    arr = np.array(im)
                    edge = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]]).mean(axis=0).astype(np.uint8)
                    canvas = Image.new("RGB", (cw, ch), tuple(int(v) for v in edge))
                    canvas.paste(im, ((cw - iw) // 2, (ch - ih) // 2))
                    im = canvas
            im = im.resize((W, H), Image.LANCZOS)
        return im

    def import_base(self, did: str, view: str, image: bytes, rev: int | None = None, source: str = "external image", fit: str = "reject") -> dict:
        """Replace the base image of a rev/view with an externally generated image (e.g. a fully lit ChatGPT render).

        The image is stored as base_imported.png next to the control renders. It is used as the base image until a job
        accepted after the import takes over (see _reference).
        """
        spec, r, scene, d, man = self.ensure_render(did, rev, view)
        im = self._fit_to_render(image, man, fit)
        im.save(d / "base_imported.png")
        match = imaging.edge_alignment(np.array(im), imaging.read(d / "lines.png", "L"))
        info = {"designId": did, "rev": r, "view": view, "renderKey": man["renderKey"], "size": [man["width"], man["height"]],
                "lineMatch": match, "source": source, "fit": fit, "importedAt": self.runtime.now()}
        (d / "base_imported.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**info, "dir": str(d)}

    def clear_imported_base(self, did: str, view: str, rev: int | None = None) -> dict:
        """Drop the imported base image of a rev/view so the default base image order applies again."""
        spec, r, scene, d, man = self.ensure_render(did, rev, view)
        removed = False
        for name in ("base_imported.png", "base_imported.json"):
            if (d / name).exists():
                (d / name).unlink()
                removed = True
        return {"designId": did, "rev": r, "view": view, "removed": removed, "dir": str(d)}

    @staticmethod
    def _imported_meta(d: Path) -> dict | None:
        """Metadata of the imported base image in a render folder, or None when there is no valid import."""
        if not (d / "base_imported.png").exists():
            return None
        try:
            meta = json.loads((d / "base_imported.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return meta if meta.get("importedAt") else None

    @staticmethod
    def _key_of(j: dict) -> str:
        """renderKey hình học mà ẢNH KẾT QUẢ của job khớp: job sửa hình cho ảnh của thiết kế mới."""
        return (j["result"] or {}).get("newRenderKey") or j["render_key"] if j["kind"] == "geometry_edit" else j["render_key"]

    def _reference(self, did: str, view: str, key: str, d: Path) -> tuple[Path, dict]:
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

    def _pick_reference(self, did, view, key, d, reference):
        if reference in (None, "", "auto"):
            return self._reference(did, view, key, d)
        if reference == "albedo":
            return d / "albedo.png", {"type": "albedo"}
        if reference == "imported":
            if self._imported_meta(d) is None:
                raise InvalidInput("Chưa có ảnh nền nhập từ ngoài cho góc này (dùng nút “Nhập ảnh kết quả từ ChatGPT”)")
            return d / "base_imported.png", {"type": "imported"}
        if reference == "beauty":
            if not (d / "beauty.png").exists():
                raise InvalidInput("Chưa có ảnh render three.js cho góc này (mở trang render.html, chọn thiết kế, bấm Render)")
            return d / "beauty.png", {"type": "beauty"}
        j = self.store.get_job(reference)
        if j["design_id"] != did or j["view"] != view:
            raise InvalidInput("Ảnh gốc thuộc thiết kế/góc nhìn khác")
        if self._key_of(j) != key:
            raise InvalidInput("Ảnh gốc thuộc hình học/camera khác (renderKey lệch); hãy dùng ảnh mới hoặc albedo")
        if j["status"] not in ("accepted", "needs-review"):
            raise InvalidInput(f"Job {reference} chưa có ảnh dùng được (trạng thái {j['status']})")
        return Path(j["result"]["dir"]) / "composite.png", {"type": "job", "jobId": j["id"]}
