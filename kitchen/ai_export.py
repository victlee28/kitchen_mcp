"""Gói xuất cho AI tạo ảnh: một file JSON "cuối cùng" của thiết kế (rev mới nhất) để gửi sang Gemini / ComfyUI / dịch vụ khác.

Gồm: thông tin thiết kế, vật liệu (tên gốc + tiếng Anh + màu), kiểu cánh, prompt chung + negative, từng góc nhìn
(camera, kích thước, prompt riêng dạng câu, đường dẫn ảnh điều khiển) và toàn bộ cảnh three.js.
Ghi ra renders/<id>/rev<N>/ai/ai-request.json (+ ảnh điều khiển và ai-package.zip khi chọn kèm ảnh).
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import zipfile
from collections import Counter
from pathlib import Path

from . import backends, geometry, layers, prompts, vocab

SCHEMA = "kitchen-ai-image-request/1.0"

_HANDLE_TEXT = {"bar": "slim bar pull handles", "knob": "round knob handles", "concealed": "recessed finger-pull handles",
                "none": "handleless push-to-open fronts"}
_STOREY_TEXT = {"base": "base cabinets", "upper": "wall cabinets", "loft": "top-row cabinets", "tall": "tall cabinets", "corner": "corner shelves"}


def _hardware_text(spec) -> str:
    """Handle description for the prompt: one sentence when every cabinet has the same handle, otherwise one clause per storey."""
    from .spec import effective_handle
    per_storey: dict[str, list[str]] = {}
    for m in spec.module:
        h = effective_handle(spec.common, m)
        text = _HANDLE_TEXT[h.variant] + (f" in {vocab.to_english(h.material)}" if h.variant != "none" and vocab.to_english(h.material) else "")
        if text not in per_storey.setdefault(m.storey, []):
            per_storey[m.storey].append(text)
    distinct = {t for texts in per_storey.values() for t in texts}
    if len(distinct) <= 1:
        return next(iter(distinct), _HANDLE_TEXT[spec.common.handle.variant])
    return "; ".join(f"{_STOREY_TEXT[s]}: {' / '.join(texts)}" for s, texts in per_storey.items())
IMAGE = ("beauty.png", "albedo.png", "lines.png", "depth.png", "normal.png", "seg.png", "instance.png")
_DOOR_STYLES = {"slab": "flat slab cabinet doors without frames or panels", "shaker": "shaker-style framed cabinet doors",
              "glass": "glass-front cabinet doors"}


def _material(doc: dict) -> list[dict]:
    out = []
    for m in doc.get("materials", []):
        out.append({"id": m["id"], "role": m.get("semanticClass"), "name": m.get("name"), "english": vocab.to_english(m.get("name", "")),
                    "color": m.get("color"), "roughness": m.get("roughness"), "metalness": m.get("metalness")})
    return out


def _door_style(doc: dict) -> str:
    c = Counter(d.get("frontStyle") or m.get("frontStyle") or "slab" for m in doc.get("modules", []) for d in m.get("doors", []))
    if not c:
        return "slab"
    return c.most_common(1)[0][0]


def build(svc, did: str, rev: int | None = None, views: list[str] | None = None, country: str | None = None,
          with_images: bool = False, embed: bool = False, lighting: str = "daylight") -> dict:
    """with_images: chép ảnh + zip. embed: nhúng ảnh nên gửi của từng góc (base64) ngay trong JSON -> một file tự chứa."""
    import base64
    spec, r = svc.store.get(did, rev)
    doc = svc.threejs(did, r, country)
    all_views = geometry.views_of(spec)
    chosen = views or list(all_views)
    bad = [v for v in chosen if v not in all_views]
    if bad:
        raise ValueError(f"Không có góc nhìn: {bad}. Có: {list(all_views)}")
    out_dir = svc.render_dir / did / f"rev{r}" / "ai"
    out_dir.mkdir(parents=True, exist_ok=True)

    style = _door_style(doc)
    tn = spec.common.handle
    part = (f"Door style: {_DOOR_STYLES.get(style, style)}. Hardware: {_hardware_text(spec)}. "
                + ("Classic crown and base moldings as drawn. " if spec.moldings else "No crown molding. "))
    common = prompts.global_prompt(spec)
    negative = ", ".join(prompts.NEGATIVE_LAYER + ["changed door style", "extra cabinets", "missing cabinets", "different layout"] + prompts.NEGATIVE_PHOTO)
    lighting = lighting if lighting in prompts.LIGHTING else "daylight"
    photo_image = prompts.full(spec, lighting)

    from . import view_sync
    try:  # approved image per view: current or out of date (see view_sync)
        sync = view_sync.view_status(svc.images, did, r)
    except Exception:  # noqa: BLE001 — the package must still build
        sync = {}
    v_out = []
    for v in chosen:
        g = all_views[v]
        files = {}
        rd = svc.render_dir / did / f"rev{r}" / v
        if with_images or embed:
            svc.images.ensure_render(did, r, v)
        if with_images:
            vd = out_dir / v
            vd.mkdir(exist_ok=True)
            for f in IMAGE:
                if (rd / f).exists():
                    shutil.copyfile(rd / f, vd / f)
                    files[f.removesuffix(".png")] = f"{v}/{f}"
        else:
            for f in IMAGE:
                if (rd / f).exists():
                    files[f.removesuffix(".png")] = f"../{v}/{f}"
        man = json.loads((rd / "manifest.json").read_text(encoding="utf-8")) if (rd / "manifest.json").exists() else {}
        camera = next((c for c in doc["cameras"] if c["id"] == f"CAM-{v}"), None)
        v_out.append({
            "id": v, "name": g.name or v, "dimensions": [man.get("width", 1280), man.get("height", 960)],
            "renderKey": man.get("renderKey"), "camera": camera,
            "suggestedInputImages": "beauty" if "beauty" in files else ("albedo" if "albedo" in files else "lines"),
            "prompt": prompts.gemini_text("gen0", "", part, common, realism=photo_image),
            "image": files,
            **({"approvedImage": {k: x for k, x in sync[v].items() if k in ("status", "changed", "approvedJob")}} if v in sync else {}),
        })
        if embed:
            src = rd / ("beauty.png" if (rd / "beauty.png").exists() else "albedo.png")
            v_out[-1]["embeddedImages"] = {"role": "input-image", "type": src.stem, "file": src.name,
                                     "dataUrl": "data:image/png;base64," + base64.b64encode(src.read_bytes()).decode()}

    req = {
        "schema": SCHEMA,
        "createdAt": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "design": {"id": did, "revision": r, "name": spec.name, "style": spec.style, "country": spec.country,
                    "moduleCount": len(spec.module), "doorStyle": style, "handle": {"variant": tn.variant, "material": tn.material},
                    "molding": [m.id for m in spec.moldings if m.enabled]},
        "instructions": ("Gửi views[].anhNhung (nếu có, ảnh đã nhúng sẵn) hoặc ảnh trong views[].anh theo anhDauVaoGoiY (beauty = render three.js, albedo = màu phẳng, lines = nét) "
                     "kèm views[].prompt cho AI tạo ảnh (Gemini, ComfyUI img2img/ControlNet…). Ảnh kết quả nộp lại qua "
                     "tab 'Sửa ảnh theo lớp' (job gen-0, backend job-package) hoặc MCP submit_image_result."),
        "commonPrompt": common,
        "lighting": lighting,
        "photoRequest": photo_image,
        "promptComfyUI": f"{common}, {prompts.tags(spec, lighting)}",
        "part": part.strip(),
        "negativePrompt": negative,
        "material": _material(doc),
        "views": v_out,
        "threejs": doc,
    }
    if embed:
        # Bản GỬI AI đã lọc: chỉ chỉ dẫn + ảnh đính kèm từng góc (bỏ cảnh three.js, camera, renderKey… AI không dùng)
        gem = out_dir / "gemini"
        gem.mkdir(exist_ok=True)
        lean_views = []
        for x in v_out:
            a = x.pop("embeddedImages")
            src = svc.render_dir / did / f"rev{r}" / x["id"] / a["file"]
            fname = f"{x['id']}-image-1-{a['type']}.png"
            shutil.copyfile(src, gem / fname)
            (gem / f"{x['id']}.json").write_text(json.dumps(backends.gemini_body(x["prompt"], [src], tuple(x["dimensions"])),
                                                             ensure_ascii=False), encoding="utf-8")
            lean_views.append({"id": x["id"], "name": x["name"], "dimensions": x["dimensions"], "instruction": x["prompt"],
                               "attachedImages": [{"order": 1, "role": "input-image", "type": a["type"], "file": f"gemini/{fname}",
                                               "dataUrl": a["dataUrl"]}],
                               "geminiApi": f"gemini/{x['id']}.json"})
        lean = {"schema": "kitchen-ai-image-request-lite/1.0", "designId": did, "revision": r, "createdAt": req["createdAt"],
                "lighting": lighting,
                "usage": ("Gemini API: gửi nguyên gemini/<góc>.json (ảnh trong inline_data được Gemini tự giải mã). "
                             "Gemini web / chat: đính kèm ảnh 'anhDinhKem' của góc cần tạo rồi dán 'chiDan' — không dán chuỗi base64 "
                             "vào khung chat (AI đọc như chữ, không thấy ảnh)."),
                "notAllowed": negative, "views": lean_views}
        p = out_dir / "ai-request-short.json"
        p.write_text(json.dumps(lean, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        p = out_dir / "ai-request.json"
        p.write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
    res = {"id": did, "rev": r, "file": str(p), "dir": str(out_dir), "views": [x["id"] for x in v_out],
           "withImage": with_images, "embedImages": embed, "createdAt": req["createdAt"]}
    if with_images:
        z = out_dir / "ai-package.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(p, "ai-request.json")
            for x in v_out:
                for rel in x["image"].values():
                    zf.write(out_dir / rel, rel)
        res["zip"] = str(z)
    return res
