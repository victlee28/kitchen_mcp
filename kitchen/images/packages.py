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
    def values(self, req: JobRequest, wf: dict) -> dict:
        W, H = req["size"]
        return {**wf.get("kitchen", {}).get("default", {}), **req.get("params", {}),
                "prompt": req["prompt"], "negative": req["negativePrompt"], "seed": req["seed"], "width": W, "height": H}

    def export_package(self, jid: str, jdir: Path, req: JobRequest) -> dict:
        wf = backends.load_workflow(req["workflow"])
        tasks = req.get("tasks") or []
        if len(tasks) > 1:
            return self._export_package_multi(jid, jdir, req, wf, tasks)
        imgs = {k: f"{jid}_{k}.png" for k in wf["kitchen"].get("image", [])}
        files = {"reference": "reference.png", "mask": "mask.png", "lines": "lines_inv.png", "depth": "depth.png"}
        for k, name in imgs.items():
            shutil.copyfile(jdir / files[k], jdir / name)
        prompt = backends.build_prompt(wf, imgs, self.values(req, wf), backends.model_defaults(self.config))
        (jdir / "workflow_api.json").write_text(json.dumps(prompt, ensure_ascii=False, indent=1), encoding="utf-8")
        (jdir / "INSTRUCTIONS.txt").write_text(
            f"Job {jid} ({req['kind']}, workflow {req['workflow']})\n"
            f"1. Chép {', '.join(imgs.values())} vào thư mục input của ComfyUI.\n"
            "2. ComfyUI > Workflow > Open (hoặc kéo thả) workflow_api.json, sửa tên model nếu cần, bấm Queue.\n"
            f"3. Nộp ảnh kết quả: web (nút Nộp ảnh) hoặc MCP submit_image_result('{jid}', đường_dẫn_ảnh).\n"
            f"Prompt: {req['prompt']}\nNegative: {req['negativePrompt']}\n", encoding="utf-8")
        return self.store.update_job(jid, "awaiting-result", {"package": sorted(p.name for p in jdir.iterdir())})

    def _export_package_multi(self, jid, jdir, req, wf, tasks) -> dict:
        files = {"lines": "lines_inv.png", "depth": "depth.png"}
        steps = []
        for i, t in enumerate(tasks, 1):
            imgs = {}
            for k in wf["kitchen"].get("image", []):
                if k == "reference":
                    imgs[k] = f"{jid}reference.png" if i == 1 else f"{jid}_ket_qua_{i - 1}.png"
                elif k == "mask":
                    imgs[k] = f"{jid}_mask_{i}.png"
                    shutil.copyfile(jdir / f"mask_{i}.png", jdir / imgs[k])
                else:
                    imgs[k] = f"{jid}_{k}.png"
                    shutil.copyfile(jdir / files[k], jdir / imgs[k])
            vals = {**self.values(req, wf), "prompt": t.get("prompt", ""), "seed": req["seed"] + i - 1}
            name = f"workflow_api_{i}.json"
            (jdir / name).write_text(json.dumps(backends.build_prompt(wf, imgs, vals, backends.model_defaults(self.config)), ensure_ascii=False, indent=1), encoding="utf-8")
            steps.append(f"  Việc {i} [{ZONE_COLORS[(i - 1) % 8][0]}] {t['targetLayer']}: {name}, ảnh vào {imgs.get('reference', '-')}, "
                         f"lưu ảnh ra thành {jid}_ket_qua_{i}.png\n     Prompt: {t['prompt']}")
        shutil.copyfile(jdir / "reference.png", jdir / f"{jid}reference.png")
        (jdir / "INSTRUCTIONS.txt").write_text(
            f"Job {jid}: {len(tasks)} việc, workflow {req['workflow']}\n"
            "Cách 1 (ComfyUI): chép các file PNG vào thư mục input, chạy lần lượt từng workflow; ảnh ra của việc trước là ảnh vào của việc sau.\n"
            + "\n".join(steps) +
            "\nCách 2 (công cụ sửa theo chỉ dẫn): dùng reference.png + mask_color.png, mỗi màu là một việc như trên.\n"
            f"Nộp ẢNH CUỐI (đã đủ mọi việc): web (nút Nộp ảnh) hoặc MCP submit_image_result('{jid}', đường_dẫn_ảnh).\n",
            encoding="utf-8")
        return self.store.update_job(jid, "awaiting-result", {"package": sorted(p.name for p in jdir.iterdir())})

    def ai_input(self, job: dict, jdir: Path, req: JobRequest) -> tuple[str, list[tuple[str, Path]]]:
        """Chỉ dẫn dạng câu + ảnh gửi model nhận chỉ dẫn (Gemini, gói request). Một nguồn cho cả gọi API lẫn file xuất."""
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
        - image-1-*.png, image-2-*.png + GEMINI-WEB-GUIDE.txt : cho Gemini web / chat: đính kèm ảnh theo thứ tự + dán chỉ dẫn.
        Chat AI KHÔNG tự giải mã chuỗi base64 dán dưới dạng chữ, nên với giao diện chat phải đính kèm file ảnh.
        Thông tin đầy đủ để truy vết vẫn ở job.json (không gửi AI)."""
        import base64
        job = self.store.get_job(jid)
        jdir = Path(job["result"]["dir"])
        req = job["request"]
        text, imgs = self.ai_input(job, jdir, req)
        size = size_of(req)
        image_name = {"base-image": "anh goc can sua", "marked-base-image": "anh goc can sua, vung sua co vien mau + so",
                   "mask": "mask (trang = vung sua)", "new-geometry": "hinh mau thiet ke moi (mau phang + net, chi de lay hinh)", "color-mask": "mask mau (moi mau mot viec)", "input-image": "anh dau vao"}
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
            "cachDung": ("Gemini API: gửi nguyên file gemini-request.json (ảnh trong inline_data được Gemini tự giải mã). "
                         "Gemini web / chat: đính kèm các ảnh trong 'anhDinhKem' ĐÚNG THỨ TỰ rồi dán 'chiDan' — "
                         "không dán chuỗi base64 vào khung chat (AI sẽ đọc như chữ, không thấy ảnh)."),
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
        (jdir / "GEMINI-WEB-GUIDE.txt").write_text(
            f"Job {jid} — gửi bằng Gemini web (không cần API)\n"
            + (f"KIỂM TRA: {'đạt' if kt['ok'] else 'CHƯA ĐẠT — sửa trước khi gửi'}\n{doors}" )
            + "\nKHÔNG dán file JSON vào khung chat: chat AI đọc base64 như chữ (thường bị cắt) và không thấy ảnh.\n"
            f"1. Mở gemini.google.com, đính kèm ĐÚNG THỨ TỰ các ảnh (dạng file ảnh):\n{steps}\n"
            "   Ảnh 1 có viền màu + số quanh vùng cần sửa; ảnh 2 là mask của đúng vùng đó.\n"
            "2. Dán nguyên đoạn chỉ dẫn dưới đây (chỉ phần chữ) rồi gửi:\n\n"
            f"{text}\n\nKhông được: {req.get('negativePrompt')}\n\n"
            "3. Tải ảnh kết quả, nộp lại ở tab Sửa ảnh theo lớp > job > Nộp ảnh.\n", encoding="utf-8")
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
               "aiRequestFile": ["request.json", "gemini-request.json", "GEMINI-WEB-GUIDE.txt"]}
        p = jdir / "request.full.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return p
