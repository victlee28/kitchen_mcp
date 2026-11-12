"""Export the latest design revision as an image-generation request for Gemini or an external chat model.

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

from .catalog import Catalog
from . import appliance_models, backends, builtin, geometry, layers, prompts, vocab
from .errors import InvalidInput

SCHEMA = "kitchen-ai-image-request/1.0"

_HANDLE_TEXT = {"bar": "slim bar pull handles", "knob": "round knob handles", "concealed": "recessed finger-pull handles",
                "none": "handleless push-to-open fronts"}
_STOREY_TEXT = {"base": "base cabinets", "upper": "wall cabinets", "loft": "top-row cabinets", "tall": "tall cabinets", "corner": "corner shelves"}


def _hardware_text(spec, catalog: Catalog) -> str:
    """Handle description for the prompt: one sentence when every cabinet has the same handle, otherwise one clause per storey."""
    from .spec import effective_handle
    per_storey: dict[str, list[str]] = {}
    for m in spec.module:
        h = effective_handle(spec.common, m)
        text = _HANDLE_TEXT[h.variant] + (f" in {vocab.to_english(h.material, catalog)}" if h.variant != "none" and vocab.to_english(h.material, catalog) else "")
        if text not in per_storey.setdefault(m.storey, []):
            per_storey[m.storey].append(text)
    distinct = {t for texts in per_storey.values() for t in texts}
    if len(distinct) <= 1:
        return next(iter(distinct), _HANDLE_TEXT[spec.common.handle.variant])
    return "; ".join(f"{_STOREY_TEXT[s]}: {' / '.join(texts)}" for s, texts in per_storey.items())
IMAGE = ("beauty.png", "albedo.png", "lines.png", "depth.png", "normal.png", "seg.png", "instance.png")
_DOOR_STYLES = {"slab": "flat slab cabinet doors without frames or panels", "shaker": "shaker-style framed cabinet doors",
              "glass": "glass-front cabinet doors"}


def _material(doc: dict, catalog: Catalog) -> list[dict]:
    out = []
    for m in doc.get("materials", []):
        out.append({"id": m["id"], "role": m.get("semanticClass"), "name": m.get("name"), "english": vocab.to_english(m.get("name", ""), catalog),
                    "color": m.get("color"), "roughness": m.get("roughness"), "metalness": m.get("metalness")})
    return out


def _door_style(doc: dict) -> str:
    c = Counter(d.get("frontStyle") or m.get("frontStyle") or "slab" for m in doc.get("modules", []) for d in m.get("doors", []))
    if not c:
        return "slab"
    return c.most_common(1)[0][0]


def _visible_appliances(rd, facts: dict) -> list[dict]:
    """The appliances the render of one view shows (its instances.json): ``[{id, layer, bbox, pixels}]``. Without a render every appliance
    is listed with ``visibility: "unknown"``."""
    path = rd / "instances.json"
    if not path.exists():
        return [{"id": i, "visibility": "unknown"} for i in facts]
    meta = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for x in meta.get("instances", []):
        if x.get("module") in facts and int(x.get("pixels") or 0) >= MIN_APPLIANCE_PIXELS:
            out.append({"id": x["module"], "layer": x["id"], "bbox": x.get("bbox"), "pixels": x.get("pixels")})
    return out


def _appliance_text(seen: list[dict], facts: dict) -> str:
    """Sentences for the view's prompt: one per appliance it shows (what to draw instead of the stand-in box, and where in the picture)."""
    lines = []
    for e in seen:
        f = facts.get(e["id"])
        if f is None:
            continue
        lines.append(appliance_models.sentence(f, e.get("bbox")))
    return (" Appliances: " + " ".join(lines)) if lines else ""


MIN_APPLIANCE_PIXELS = int(builtin.CATALOG.data("image-rules", "default")["minAppliancePixels"])   # fewer pixels: the appliance is not described (image-rules)


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
        raise InvalidInput(f"No view {bad}; there are {list(all_views)}", code="view-not-found", params={"view": ", ".join(bad), "views": ", ".join(all_views)})
    catalog = svc.catalog_for_revision(did, r)
    out_dir = svc.render_dir / did / f"rev{r}" / "ai"
    out_dir.mkdir(parents=True, exist_ok=True)

    style = _door_style(doc)
    tn = spec.common.handle
    part = (f"Door style: {_DOOR_STYLES.get(style, style)}. Hardware: {_hardware_text(spec, catalog)}. "
                + ("Classic crown and base moldings as drawn. " if spec.moldings else "No crown molding. "))
    common = prompts.global_prompt(spec, catalog)
    negative = prompts.negative_prompt(["changed door style", "extra cabinets", "missing cabinets", "different layout"], catalog)
    lighting = lighting if lighting in prompts.lighting(catalog) else "daylight"
    photo_image = prompts.full(spec, lighting, catalog)

    from . import view_sync
    try:  # approved image per view: current or out of date (see view_sync)
        sync = view_sync.view_status(svc.images, did, r)
    except Exception:  # noqa: BLE001 — the package must still build
        sync = {}
    by_id = appliance_models.models(catalog)
    facts = {a.id: appliance_models.ai_facts(spec, a, "model-3d" if by_id.get(appliance_models.model_id(a, catalog) or "", {}).get("asset3d")
                                             else "box-placeholder", catalog) for a in spec.appliances}      # plan A5: the AI must know each appliance
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
        seen = _visible_appliances(rd, facts)
        v_out.append({
            "id": v, "name": g.name or v, "dimensions": [man.get("width", 1280), man.get("height", 960)],
            "renderKey": man.get("renderKey"), "camera": camera,
            "suggestedInputImages": "beauty" if "beauty" in files else ("albedo" if "albedo" in files else "lines"),
            "prompt": prompts.gemini_text("gen0", "", part, common, realism=photo_image) + _appliance_text(seen, facts),
            "image": files,
            "appliances": seen,
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
        "instructions": ("Attach the suggested input image for each view and include its prompt when sending it to Gemini, ChatGPT, Claude, "
                         "or another image model. Import the generated image through an image job or MCP submit_image_result."),
        "commonPrompt": common,
        "lighting": lighting,
        "photoRequest": photo_image,
        "part": part.strip(),
        "negativePrompt": negative,
        "material": _material(doc, catalog),
        "appliances": list(facts.values()),
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
                               "appliances": [{**facts[e["id"]], **e} for e in x["appliances"] if e["id"] in facts],
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
