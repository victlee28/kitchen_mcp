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

from . import backends, geometry, layers, realism, vocab

SCHEMA = "kitchen-ai-image-request/1.0"
ANH = ("beauty.png", "albedo.png", "lines.png", "depth.png", "normal.png", "seg.png", "instance.png")
_KIEU_CANH = {"slab": "flat slab cabinet doors without frames or panels", "shaker": "shaker-style framed cabinet doors",
              "glass": "glass-front cabinet doors"}


def _vat_lieu(doc: dict) -> list[dict]:
    out = []
    for m in doc.get("materials", []):
        out.append({"id": m["id"], "vaiTro": m.get("semanticClass"), "ten": m.get("name"), "tiengAnh": vocab.tieng_anh(m.get("name", "")),
                    "mau": m.get("color"), "roughness": m.get("roughness"), "metalness": m.get("metalness")})
    return out


def _door_style(doc: dict) -> str:
    c = Counter(d.get("frontStyle") or m.get("frontStyle") or "slab" for m in doc.get("modules", []) for d in m.get("doors", []))
    if not c:
        return "slab"
    return c.most_common(1)[0][0]


def build(svc, did: str, rev: int | None = None, views: list[str] | None = None, quoc_gia: str | None = None,
          with_images: bool = False, embed: bool = False, anh_sang: str = "ban-ngay") -> dict:
    """with_images: chép ảnh + zip. embed: nhúng ảnh nên gửi của từng góc (base64) ngay trong JSON -> một file tự chứa."""
    import base64
    spec, r = svc.store.get(did, rev)
    doc = svc.threejs(did, r, quoc_gia)
    all_views = geometry.views_of(spec)
    chosen = views or list(all_views)
    bad = [v for v in chosen if v not in all_views]
    if bad:
        raise ValueError(f"Không có góc nhìn: {bad}. Có: {list(all_views)}")
    out_dir = svc.render_dir / did / f"rev{r}" / "ai"
    out_dir.mkdir(parents=True, exist_ok=True)

    style = _door_style(doc)
    tn = spec.chung.tayNam
    handle = {"thanh": "slim bar pull handles", "num": "round knob handles", "am": "recessed finger-pull handles",
              "khong": "handleless push-to-open fronts"}[tn.kieu]
    tn_en = vocab.tieng_anh(tn.vatLieu)
    chi_tiet = (f"Door style: {_KIEU_CANH.get(style, style)}. Hardware: {handle}" + (f" in {tn_en}" if tn_en else "") + ". "
                + ("Classic crown and base moldings as drawn. " if spec.moldings else "No crown molding. "))
    chung = layers.global_prompt(spec)
    negative = ", ".join(layers.NEGATIVE + ["changed door style", "extra cabinets", "missing cabinets", "different layout"] + realism.NEGATIVE)
    anh_sang = anh_sang if anh_sang in realism.ANH_SANG else "ban-ngay"
    anh_that = realism.full(spec, anh_sang)

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
            for f in ANH:
                if (rd / f).exists():
                    shutil.copyfile(rd / f, vd / f)
                    files[f.removesuffix(".png")] = f"{v}/{f}"
        else:
            for f in ANH:
                if (rd / f).exists():
                    files[f.removesuffix(".png")] = f"../{v}/{f}"
        man = json.loads((rd / "manifest.json").read_text(encoding="utf-8")) if (rd / "manifest.json").exists() else {}
        cam = next((c for c in doc["cameras"] if c["id"] == f"CAM-{v}"), None)
        v_out.append({
            "id": v, "ten": g.ten or v, "kichThuoc": [man.get("width", 1280), man.get("height", 960)],
            "renderKey": man.get("renderKey"), "camera": cam,
            "anhDauVaoGoiY": "beauty" if "beauty" in files else ("albedo" if "albedo" in files else "lines"),
            "prompt": backends.gemini_text("gen0", "", chi_tiet, chung, realism=anh_that),
            "anh": files,
        })
        if embed:
            src = rd / ("beauty.png" if (rd / "beauty.png").exists() else "albedo.png")
            v_out[-1]["anhNhung"] = {"vaiTro": "anh-dau-vao", "loai": src.stem, "file": src.name,
                                     "dataUrl": "data:image/png;base64," + base64.b64encode(src.read_bytes()).decode()}

    req = {
        "schema": SCHEMA,
        "taoLuc": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "thietKe": {"id": did, "revision": r, "ten": spec.ten, "phongCach": spec.phongCach, "quocGia": spec.quocGia,
                    "soModule": len(spec.module), "kieuCanh": style, "tayNam": {"kieu": tn.kieu, "vatLieu": tn.vatLieu},
                    "phao": [m.ma for m in spec.moldings if m.bat]},
        "huongDan": ("Gửi views[].anhNhung (nếu có, ảnh đã nhúng sẵn) hoặc ảnh trong views[].anh theo anhDauVaoGoiY (beauty = render three.js, albedo = màu phẳng, lines = nét) "
                     "kèm views[].prompt cho AI tạo ảnh (Gemini, ComfyUI img2img/ControlNet…). Ảnh kết quả nộp lại qua "
                     "tab 'Sửa ảnh theo lớp' (job gen-0, backend goi-job) hoặc MCP submit_image_result."),
        "promptChung": chung,
        "anhSang": anh_sang,
        "yeuCauAnhThat": anh_that,
        "promptComfyUI": f"{chung}, {realism.tags(spec, anh_sang)}",
        "chiTiet": chi_tiet.strip(),
        "negativePrompt": negative,
        "vatLieu": _vat_lieu(doc),
        "views": v_out,
        "threejs": doc,
    }
    if embed:
        # Bản GỬI AI đã lọc: chỉ chỉ dẫn + ảnh đính kèm từng góc (bỏ cảnh three.js, camera, renderKey… AI không dùng)
        gem = out_dir / "gemini"
        gem.mkdir(exist_ok=True)
        lean_views = []
        for x in v_out:
            a = x.pop("anhNhung")
            src = svc.render_dir / did / f"rev{r}" / x["id"] / a["file"]
            fname = f"{x['id']}-anh-1-{a['loai']}.png"
            shutil.copyfile(src, gem / fname)
            (gem / f"{x['id']}.json").write_text(json.dumps(backends.gemini_body(x["prompt"], [src], tuple(x["kichThuoc"])),
                                                             ensure_ascii=False), encoding="utf-8")
            lean_views.append({"id": x["id"], "ten": x["ten"], "kichThuoc": x["kichThuoc"], "chiDan": x["prompt"],
                               "anhDinhKem": [{"thuTu": 1, "vaiTro": "anh-dau-vao", "loai": a["loai"], "file": f"gemini/{fname}",
                                               "dataUrl": a["dataUrl"]}],
                               "geminiApi": f"gemini/{x['id']}.json"})
        lean = {"schema": "kitchen-ai-image-request-lite/1.0", "designId": did, "revision": r, "taoLuc": req["taoLuc"],
                "anhSang": anh_sang,
                "cachDung": ("Gemini API: gửi nguyên gemini/<góc>.json (ảnh trong inline_data được Gemini tự giải mã). "
                             "Gemini web / chat: đính kèm ảnh 'anhDinhKem' của góc cần tạo rồi dán 'chiDan' — không dán chuỗi base64 "
                             "vào khung chat (AI đọc như chữ, không thấy ảnh)."),
                "khongDuoc": negative, "views": lean_views}
        p = out_dir / "gui-ai.json"
        p.write_text(json.dumps(lean, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        p = out_dir / "ai-request.json"
        p.write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
    res = {"id": did, "rev": r, "file": str(p), "dir": str(out_dir), "views": [x["id"] for x in v_out],
           "kemAnh": with_images, "nhungAnh": embed, "taoLuc": req["taoLuc"]}
    if with_images:
        z = out_dir / "ai-package.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(p, "ai-request.json")
            for x in v_out:
                for rel in x["anh"].values():
                    zf.write(out_dir / rel, rel)
        res["zip"] = str(z)
    return res
