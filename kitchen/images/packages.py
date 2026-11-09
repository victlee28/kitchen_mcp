"""Packages and files handed to a model or a person: request.json, the AI prompt, the full export."""
from __future__ import annotations

from pathlib import Path
import json
import shutil

from PIL import Image

from .. import request_check, backends, edit, imaging, prompts
from ..errors import KitchenError
from .request import JobRequest, size_of
from .common import Component, GROW_PX, ZONE_COLORS


class Packages(Component):
    def export_package(self, jid: str, jdir: Path, req: JobRequest) -> dict:
        self.export_request(jid)
        package = sorted(p.name for p in jdir.iterdir() if p.is_file())
        return self.store.update_job(jid, "awaiting-result", {"package": package})

    def ai_input(self, job: dict, jdir: Path, req: JobRequest) -> tuple[str, list[tuple[str, Path]]]:
        """Chỉ dẫn dạng câu + ảnh gửi model nhận chỉ dẫn (Gemini, gói request). Một nguồn cho cả gọi API lẫn file xuất.
        Có ``styleReference`` thì ảnh đã duyệt của góc khác được đính kèm cuối cùng kèm một câu nói rõ chỉ lấy phong cách."""
        text, images = self._ai_input_core(job, jdir, req)
        style = jdir / "style_reference.png"
        ref = req.get("styleReference")
        if ref and style.exists():
            images = [*images, ("style-reference", style)]
            text = f"{text}\n{prompts.style_note(len(images), ref['view'])}"
        return text, images

    def _ai_input_core(self, job: dict, jdir: Path, req: JobRequest) -> tuple[str, list[tuple[str, Path]]]:
        if req["kind"] == "gen0":
            d = self.view_dir(job["design_id"], job["rev"], job["view"])
            src = d / "beauty.png" if (d / "beauty.png").exists() else d / "albedo.png"
            spec, _ = self.store.get(job["design_id"], job["rev"])
            real = req.get("photoImage") or prompts.full(spec, req.get("lighting") or "daylight")
            return prompts.gemini_text("gen0", "", req.get("instruction", ""), req["globalPrompt"], realism=real), [("input-image", src)]
        if req["kind"] == "geometry_edit":
            t = req.get("tasks", [{}])[0]
            text = prompts.gemini_text_geometry(req.get("operation") or t.get("operation") or "replace-item", [x["en"] for x in req.get("description", [])],
                                             (t.get("position") or {}).get("en"), t.get("instruction") or "", self._local_real(job))
            return text, [("marked-base-image", jdir / "reference_marked.png"), ("mask", jdir / "mask.png"),
                          ("new-geometry", jdir / "new_geometry.png")]
        tasks = req.get("tasks", [])
        multi = len(tasks) > 1
        marked = jdir / "reference_marked.png"
        if not marked.exists():  # job tạo trước khi có ảnh đánh dấu
            ref = imaging.read(jdir / "reference.png", "RGB")
            marks = [(imaging.read(jdir / f"target_{i}.png", "L") > 127, ZONE_COLORS[(i - 1) % len(ZONE_COLORS)][1], str(i))
                     for i in range(1, len(tasks) + 1) if (jdir / f"target_{i}.png").exists()]
            Image.fromarray(imaging.mark_regions(ref, marks, gap=GROW_PX + 2)).save(marked)
        regions = []
        for i, t in enumerate(tasks, 1):
            extra = " ".join(x for x in (t.get("instruction"), None if multi else req.get("instruction")) if x)
            regions.append({"n": i, "color": ZONE_COLORS[(i - 1) % len(ZONE_COLORS)][0], "role": t.get("roleEn") or "kitchen element",
                            "material_text": t.get("materialText") or t.get("prompt", ""), "extra": extra,
                            "where": (t.get("position") or {}).get("en"), "others": t.get("remaining") or 0,
                            "kind": t.get("typeEn") or t.get("roleEn") or "element"})
        text = prompts.gemini_text_edit(regions, req.get("instruction", "") if multi else "", self._local_real(job))
        return text, [("marked-base-image", marked), ("color-mask" if multi else "mask", jdir / ("mask_color.png" if multi else "mask.png"))]

    def _local_real(self, job: dict) -> str:
        """Yêu cầu ảnh thật khi sửa vùng; vật liệu lấy theo thiết kế sau sửa nếu có (sửa hình) để mô tả bề mặt đúng."""
        spec, _ = self.store.get(job["design_id"], job["rev"])
        op = job["request"].get("designOp")
        if op:
            try:
                spec = edit.apply_op(spec, op)
            except (KitchenError, ValueError, KeyError):  # the edit does not apply: describe the surface from the original design
                pass
        if op:
            return prompts.local(spec)
        mats = [t.get("material") for t in job["request"].get("tasks") or [] if t.get("material")]
        return prompts.local(None, mats)

    def export_request(self, jid: str) -> Path:
        """Xuất request gửi AI, đã LỌC bỏ thông tin hệ thống AI không dùng (renderKey, id chi tiết, số pixel, prompt kiểu tag…).

        - request.json        : bản gọn cho người / AI đọc: chỉ dẫn, danh sách việc, ảnh đính kèm theo thứ tự (base64 để xem, lưu).
        - gemini-request.json : thân request Gemini API (generateContent): ảnh ở phần inline_data -> Gemini TỰ GIẢI MÃ và dùng ảnh.
        - image-1-*.png, image-2-*.png + AI-CHAT-GUIDE.txt : for ChatGPT, Claude or Gemini web; attach images in order and paste the prompt.
        Chat AI KHÔNG tự giải mã chuỗi base64 dán dưới dạng chữ, nên với giao diện chat phải đính kèm file ảnh.
        Thông tin đầy đủ để truy vết vẫn ở job.json (không gửi AI)."""
        import base64
        job = self.store.get_job(jid)
        jdir = Path(job["result"]["dir"])
        req = job["request"]
        text, imgs = self.ai_input(job, jdir, req)
        size = size_of(req)
        image_name = {"base-image": "anh goc can sua", "marked-base-image": "anh goc can sua, vung sua co vien mau + so",
                   "mask": "mask (trang = vung sua)", "new-geometry": "hinh mau thiet ke moi (mau phang + net, chi de lay hinh)", "color-mask": "mask mau (moi mau mot viec)", "input-image": "anh dau vao",
                   "style-reference": "anh da duyet cua goc khac (chi lay vat lieu, mau, anh sang; khong chep bo cuc)"}
        for old in jdir.glob("image-*.png"):  # bỏ bản đánh số của lần xuất trước (tên vai trò có thể đã đổi)
            old.unlink()
        attached = []
        for k, (role, pth) in enumerate(imgs, 1):
            fname = f"image-{k}-{role}.png"
            shutil.copyfile(pth, jdir / fname)
            attached.append({"order": k, "role": role, "description": image_name.get(role, role), "file": fname,
                             "dataUrl": "data:image/png;base64," + base64.b64encode(pth.read_bytes()).decode()})
        task = []
        for i, t in enumerate(req.get("tasks") or [], 1):
            vt = t.get("position") or {}
            task.append({k: v for k, v in {
                "task": i, "label": str(i), "borderColor": ZONE_COLORS[(i - 1) % len(ZONE_COLORS)][0],
                "zoneColor": ZONE_COLORS[(i - 1) % len(ZONE_COLORS)][0] if len(req.get("tasks", [])) > 1 else "WHITE",
                "name": t.get("name"), "target": t.get("roleEn"), "position": vt.get("vi"), "boxPercent": vt.get("frame"),
                "sameTypeUnchanged": t.get("remaining"),
                "material": t.get("material"), "english": t.get("materialText"), "request": t.get("instruction")}.items() if v})
        lean = {
            "schema": "kitchen-ai-edit-request/2.0",
            "jobId": jid,
            "type": {"geometry_edit": "geometry_edit", "gen0": "gen0"}.get(req["kind"], "material"),
            **({"operation": req["operation"]} if req.get("operation") else {}),
            "cachDung": ("For Gemini API, send gemini-request.json with its inline image data. For ChatGPT, Claude, or Gemini web, "
                         "attach the files listed in attachedImages in order and paste instruction. Do not paste base64 as chat text."),
            "instruction": text,
            "attachedImages": attached,
            "task": task,
            "notAllowed": req.get("negativePrompt"),
            "dimensions": list(size),
        }
        lean["validation"] = request_check.check_lean(lean)
        (jdir / "request.json").write_text(json.dumps(lean, ensure_ascii=False, indent=1), encoding="utf-8")
        (jdir / "gemini-request.json").write_text(json.dumps(backends.gemini_body(text, [p for _, p in imgs], size),
                                                             ensure_ascii=False), encoding="utf-8")
        steps = "\n".join(f"  {d['order']}. {d['file']}  ({d['description']})" for d in attached)
        kt = lean["validation"]
        doors = "".join(f"  ! {x}\n" for x in kt["errors"] + kt["warning"])
        (jdir / "AI-CHAT-GUIDE.txt").write_text(
            f"Job {jid} — use with ChatGPT, Claude or Gemini web\n"
            + (f"Validation: {'passed' if kt['ok'] else 'failed; resolve before sending'}\n{doors}" )
            + "\nDo not paste JSON or base64 into the chat; attach the image files directly.\n"
            f"1. Attach the image files in this order:\n{steps}\n"
            "   The marked reference identifies edit areas; the mask shows the allowed edit region.\n"
            "2. Paste the following instruction as text:\n\n"
            f"{text}\n\nAvoid: {req.get('negativePrompt')}\n\n"
            f"3. Return an edited image with dimensions {size[0]}x{size[1]}. Import it in the image-editing job or call "
            f"submit_image_result('{jid}', image_path).\n", encoding="utf-8")
        return jdir / "request.json"

    def export_full(self, jid: str) -> Path:
        """Bản ĐẦY ĐỦ để kiểm tra (không gửi AI): toàn bộ yêu cầu nội bộ (renderKey, chi tiết bị sửa, thao tác thiết kế chờ ghi,
        prompt từng việc…), trạng thái job, kết quả/báo cáo nếu có, và mọi ảnh của job nhúng base64 (ảnh gốc, mask, mask màu,
        mask đích + mask nở của từng việc, ảnh AI thô, ảnh ghép)."""
        import base64
        self.export_request(jid)  # bảo đảm các file gửi AI đã có
        job = self.store.get_job(jid)
        jdir = Path(job["result"]["dir"])
        image = {}
        for f in sorted(jdir.glob("*.png")):
            if f.name.startswith(("image-", f"{jid}_")):  # bản sao đánh số / tên upload: trùng nội dung, bỏ cho gọn
                continue
            image[f.stem] = "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode()
        res = {k: v for k, v in job["result"].items() if k != "dir"}
        out = {"schema": "kitchen-ai-edit-request-full/1.0",
               "note": "Bản đầy đủ để kiểm tra — KHÔNG gửi AI (gửi request.json / gemini-request.json).",
               "job": {k: job[k] for k in ("id", "status", "kind", "mode", "backend", "design_id", "rev", "view", "render_key",
                                           "target", "created_at", "updated_at", "error")},
               "request": job["request"], "result": res, "image": image,
               "aiRequestFile": ["request.json", "gemini-request.json", "AI-CHAT-GUIDE.txt"]}
        p = jdir / "request.full.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return p
