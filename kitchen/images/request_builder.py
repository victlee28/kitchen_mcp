"""Building the request of a job: tasks, masks, prompt inputs, geometry edits."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import shutil

from PIL import Image
import numpy as np

from .. import backends, edit, geometry, geometry_edit, imaging, layers, prompts, render, vocab
from ..errors import InvalidInput
from .request import JobRequest, NewJob, Task, TaskInput
from .common import JobsContext, GROW_PX, MAX_TASKS, ZONE_COLORS, MOLDING_EN, describe_position

class RequestBuilder(JobsContext):
    @staticmethod
    def _norm_tasks(tasks: list[dict[str, Any]] | None, target: str | None, material: str | None, instruction: str) -> list[TaskInput]:
        if not tasks:
            if not target:
                raise InvalidInput("Cần targetLayer hoặc danh sách tasks")
            tasks = [{"targetLayer": target, "material": material, "instruction": instruction}]
        if not isinstance(tasks, list) or len(tasks) > MAX_TASKS:
            raise InvalidInput(f"tasks phải là danh sách tối đa {MAX_TASKS} việc")
        out: list[TaskInput] = []
        for i, t in enumerate(tasks, 1):
            if not isinstance(t, dict):
                raise InvalidInput(f"Việc {i} không hợp lệ")
            tl = t.get("targetLayer") or t.get("target") or t.get("target_layer")
            if not tl:
                raise InvalidInput(f"Việc {i} thiếu targetLayer")
            out.append({"targetLayer": str(tl), "material": (t.get("material") or t.get("material") or None),
                        "instruction": str(t.get("instruction") or "").strip()})
        return out

    def _prepare(self, jid: str, jdir: Path, d: Path, spec: Any, rev: int, scene: Any, man: dict[str, Any], new: NewJob,
                 tasks: list[TaskInput]) -> JobRequest:
        """``new`` carries the already-resolved mode, workflow, params and lighting; ``tasks`` the normalised task inputs."""
        did, view, instruction, mode, backend, reference, kind = new.did, new.view, new.instruction, new.mode, new.backend, new.reference, new.kind
        workflow, seed, params, geometry_items, operation, lighting = new.workflow, new.seed, new.params, new.geometry_items, new.operation, new.lighting or "daylight"
        W, H = man["width"], man["height"]
        req: JobRequest = {"designId": did, "baseRevision": rev, "view": view, "renderKey": man["renderKey"], "kind": kind, "mode": mode,
               "instruction": instruction, "backend": backend,
               "workflow": workflow or {"gen0": "gen0-lineart-depth", "geometry_edit": "inpaint-lineart"}.get(kind, "inpaint"),
               "seed": int(seed if seed is not None else self.runtime.new_seed()), "params": params or {},
               "size": [W, H], "preserve": "strict", "negativePrompt": ", ".join(prompts.NEGATIVE_LAYER + prompts.NEGATIVE_PHOTO),
               "lighting": lighting,  # ánh sáng cho ảnh đầy đủ (gen-0); sửa vùng thì bám ánh sáng ảnh gốc
               "prompt": "", "globalPrompt": ""}  # both filled by the branch of the kind below
        lines = imaging.read(d / "lines.png", "L")
        Image.fromarray(255 - lines).save(jdir / "lines_inv.png")  # ControlNet lineart: nét trắng nền đen
        shutil.copyfile(d / "depth.png", jdir / "depth.png")
        if operation:
            req["operation"] = operation
        if kind == "geometry_edit":
            self._prepare_geometry(jdir, d, spec, man, did, view, geometry_items, instruction, reference, req)
        elif kind == "edit":
            cat = layers.catalogue(spec, scene)
            cur = spec
            inst, meta = imaging.load_instances(d)
            present = set(int(v) for v in np.unique(inst))
            visible = {x["id"] for x in meta["instances"] if x["value"] in present}
            owner: dict[str, int] = {}
            union = np.zeros((H, W), bool)
            recs: list[Task] = []
            for i, t in enumerate(tasks, 1):
                layer, ids = layers.resolve(cat, t["targetLayer"])
                if not layer.get("allowAppearanceChange"):
                    raise InvalidInput(f"Việc {i}: layer '{t['targetLayer']}' bị khóa")
                rec: Task = {"targetLayer": t["targetLayer"], "material": t["material"], "instruction": t["instruction"]}
                if mode == "design":
                    if not t["material"]:
                        raise InvalidInput(f"Việc {i} ({t['targetLayer']}): chế độ design cần material (vd 'Laminate xanh rêu mờ')")
                    op = layers.design_op(cur, layers.resolve(layers.catalogue(cur, scene), t["targetLayer"])[0], t["material"], scene)
                    if op is None:
                        raise InvalidInput(f"Việc {i}: '{layer['name']}' chưa sửa được trong thiết kế; dùng chế độ quick")
                    nxt = edit.apply_op(cur, op[0])
                    if render.scene_hash(geometry.compile_spec(nxt)) != render.scene_hash(scene):
                        raise InvalidInput(f"Việc {i}: thao tác làm đổi hình học; sửa ảnh chỉ nhận thay đổi vật liệu")
                    selected = list(ids)
                    ids = layers.changed_parts(cur, nxt, scene)
                    if set(ids) != set(selected):  # the spec can only express a wider or different scope: say so instead of hiding it
                        rec["scopeNote"] = f"Thiết kế đổi {len(ids)} chi tiết, vùng chọn có {len(selected)}"
                    if not ids:
                        raise InvalidInput(f"Việc {i}: vật liệu mới trùng vật liệu hiện tại")
                    rec["pendingOp"] = op[0]
                    rec["scope"] = op[1]
                    cur = nxt
                clash = sorted({owner[p] for p in ids if p in owner})
                if clash:
                    both = [p for p in ids if p in owner]
                    raise InvalidInput(f"Việc {i} và việc {clash[0]} cùng sửa chi tiết {', '.join(both[:4])}; tách layer hoặc gộp thành một việc")
                tmask = imaging.mask_of(d, ids)
                if not tmask.any():
                    raise InvalidInput(f"Việc {i}: layer '{t['targetLayer']}' không nhìn thấy ở góc '{view}'")
                for p in ids:
                    owner[p] = i
                union |= tmask
                imaging.save_mask(tmask, jdir / f"target_{i}.png")
                imaging.save_mask(imaging.grow(tmask, GROW_PX), jdir / f"mask_{i}.png")
                lay_new = layers.resolve(layers.catalogue(cur, scene), t["targetLayer"])[0]
                material_text = t["material"] or lay_new.get("material") or ""
                type = lay_new.get("type") or ""
                role_en = layers.ROLES.get(type, (None, "kitchen element"))[1]
                if type == "molding":
                    variant = {m.id: m.variant for m in cur.moldings}.get(lay_new.get("module") or "")
                    role_en = MOLDING_EN.get(variant or "", role_en)
                rec["targetParts"] = ids
                rec["maskPixels"] = int(tmask.sum())
                rec["name"] = lay_new.get("name")
                rec["prompt"] = prompts.edit_task_prompt(cur, lay_new, " ".join(x for x in (t["instruction"], instruction) if x), t["material"])
                rec["roleEn"] = role_en
                rec["position"] = describe_position(tmask)
                rec["remaining"] = self._others(cat, visible, ids, type)
                rec["typeEn"] = layers.ROLES.get(type, (None, "element"))[1]
                rec["materialText"] = " ".join(x for x in (vocab.to_english(material_text), material_text and f"({material_text})") if x)
                recs.append(rec)
            ref_path, ref_info = self._pick_reference(did, view, man["renderKey"], d, reference)
            ref, _ = imaging.load_rgb(ref_path, (W, H))
            Image.fromarray(ref).save(jdir / "reference.png")
            imaging.save_mask(union, jdir / "target.png")
            region = np.zeros((H, W), bool)
            for i in range(1, len(recs) + 1):
                region |= imaging.read(jdir / f"mask_{i}.png", "L") > 127
            imaging.save_mask(region, jdir / "mask.png")
            self._color_mask(jdir, len(recs))
            marks = [(imaging.read(jdir / f"target_{i}.png", "L") > 127, ZONE_COLORS[(i - 1) % len(ZONE_COLORS)][1], str(i))
                     for i in range(1, len(recs) + 1)]
            Image.fromarray(imaging.mark_regions(ref, marks, gap=GROW_PX + 2)).save(jdir / "reference_marked.png")
            first = recs[0]
            req["tasks"] = recs
            req["referenceImage"] = ref_info
            req["maskPixels"] = int(union.sum())
            req["globalPrompt"] = prompts.global_prompt(cur)
            req["targetLayer"] = first["targetLayer"] + (f" +{len(recs) - 1}" if len(recs) > 1 else "")
            # trường cũ (1 việc) giữ để workflow/công cụ cũ đọc được
            req["prompt"] = first.get("prompt", "") if len(recs) == 1 else "; ".join(f"[{k + 1}] {r.get('prompt', '')}" for k, r in enumerate(recs))
            req["material"] = first["material"] if len(recs) == 1 else None
            req["targetParts"] = [p for r in recs for p in r.get("targetParts", [])]
            req["scope"] = "; ".join(r.get("scope", "") for r in recs if r.get("scope")) or None
        else:
            req["globalPrompt"] = prompts.global_prompt(spec)
            req["photoImage"] = prompts.full(spec, lighting)
            req["prompt"] = ", ".join(x for x in (prompts.global_prompt(spec), prompts.tags(spec, lighting), instruction.strip()) if x)
        if backend in ("job-package", "comfyui"):
            backends.load_workflow(req["workflow"])  # tên workflow sai -> báo ngay
        (jdir / "job.json").write_text(json.dumps({"id": jid, **req}, ensure_ascii=False, indent=2), encoding="utf-8")
        return req

    @staticmethod
    def _others(cat: list[dict], visible: set[str], ids: list[str], type: str) -> int:
        """Số vật CÙNG LOẠI khác vẫn thấy trong ảnh mà không thuộc việc này (để dặn model giữ nguyên chúng)."""
        if not type or type in ("module", "wall", "floor"):
            return 0
        mine = set(ids)
        kinds = {type} | ({"drawer", "glass-door"} if type == "door" else set())
        rest = [x for x in cat if x["variant"] == "part" and x["type"] in kinds and x["id"] in visible and x["id"] not in mine]
        if type == "molding":  # một đường phào gồm nhiều đoạn: đếm theo đường phào
            return len({x["module"] for x in rest})
        return len(rest)

    def _prepare_geometry(self, jdir: Path, d: Path, spec: Any, man: dict[str, Any], did: str, view: str, items: list[dict[str, Any]] | None,
                          instruction: str, reference: str | None, req: JobRequest) -> None:
        """Áp thao tác hình học lên bản sao thiết kế, render lại ĐÚNG camera cũ, so cũ/mới ra vùng thay đổi.
        Nét/depth gửi model là của thiết kế MỚI; ảnh 'hình mẫu' (màu phẳng + nét) cho model nhận chỉ dẫn."""
        W, H = man["width"], man["height"]
        ops, desc, tt = geometry_edit.build_ops(spec, items or [])
        nxt = spec
        for op in ops:
            nxt = edit.apply_op(nxt, op)
        pin = geometry_edit.pin_cameras(spec, nxt)
        if pin:
            nxt = edit.apply_op(nxt, pin)
            ops.append(pin)
        design_op = edit.combine_ops(ops)
        render.render_views(nxt, jdir / "moi", [view], W, H, meta={"designId": did, "rev": "unspecified"})
        nd = jdir / "moi" / view
        key_new = json.loads((nd / "manifest.json").read_text(encoding="utf-8"))["renderKey"]
        m, info = geometry_edit.diff_mask(d, nd)
        lines_new = imaging.read(nd / "lines.png", "L")
        forced = [id for x in desc for id in x.get("required", [])]
        if forced:  # đổi kiểu cánh: render nhanh không dựng khung -> bắt buộc vẽ lại mặt trước các module đó
            fm, doors = geometry_edit.front_mask(nd, nxt, geometry.compile_spec(nxt), forced)
            m |= fm
            if any(x.get("doorStyle") == "frame" for x in desc):
                lines_new = geometry_edit.shaker_lines(lines_new, doors)
        if not m.any():
            raise InvalidInput(f"Thao tác không làm đổi gì nhìn thấy ở góc '{view}'")
        if m.mean() > 0.85:
            raise InvalidInput("Thao tác đổi gần như toàn ảnh (camera/khung hình đổi?); dùng gen-0 cho thiết kế mới")
        imaging.save_mask(m, jdir / "target_1.png")
        imaging.save_mask(m, jdir / "target.png")
        region = imaging.grow(m, GROW_PX)
        imaging.save_mask(region, jdir / "mask_1.png")
        imaging.save_mask(region, jdir / "mask.png")
        self._color_mask(jdir, 1)
        Image.fromarray(lines_new).save(jdir / "lines_moi.png")
        Image.fromarray(255 - lines_new).save(jdir / "lines_inv.png")  # ControlNet: nét của thiết kế MỚI
        shutil.copyfile(nd / "depth.png", jdir / "depth.png")
        Image.fromarray(geometry_edit.preview(nd, lines_new)).save(jdir / "new_geometry.png")
        ref_path, ref_info = self._pick_reference(did, view, man["renderKey"], d, reference)
        ref, _ = imaging.load_rgb(ref_path, (W, H))
        Image.fromarray(ref).save(jdir / "reference.png")
        Image.fromarray(imaging.mark_regions(ref, [(m, ZONE_COLORS[0][1], "1")], gap=GROW_PX + 2)).save(jdir / "reference_marked.png")
        en = "; ".join(x["en"] for x in desc)
        vi = "; ".join(x["vi"] for x in desc)
        common = prompts.global_prompt(nxt)
        task: Task = {"targetLayer": "geometry_edit", "name": vi, "roleEn": en, "position": describe_position(m), "instruction": instruction, "material": None,
                      "operation": tt, "targetParts": info["part"], "maskPixels": int(m.sum()),
                      "prompt": ", ".join(x for x in (en, instruction, common, prompts.tags(nxt, req.get("lighting") or "daylight")) if x)}
        if "operation" not in req:  # trọng số mặc định theo thao tác suy ra (params người dùng vẫn ghi đè)
            req["params"] = {**geometry_edit.OPERATIONS[tt]["params"], **req["params"]}
        req["originalGeometry"] = items or []
        req["tasks"] = [task]
        req["designOp"] = design_op
        req["description"] = desc
        req["operation"] = req.get("operation") or tt
        req["newRenderKey"] = key_new
        req["different"] = info
        req["pinCamera"] = bool(pin)
        req["referenceImage"] = ref_info
        req["maskPixels"] = int(m.sum())
        req["globalPrompt"] = common
        req["targetLayer"] = f"geometry: {vi}"[:120]
        req["prompt"] = task["prompt"]
        req["targetParts"] = info["part"]
        req["scope"] = vi
        req["instruction"] = ""
        if instruction:
            task["instruction"] = instruction

    @staticmethod
    def _color_mask(jdir: Path, n: int) -> None:
        """Ảnh mask màu (mỗi việc một màu) để mô tả nhiều vùng cho model nhận chỉ dẫn (Gemini, sửa tay)."""
        first = imaging.read(jdir / "mask_1.png", "L")
        out = np.zeros((*first.shape, 3), np.uint8)
        for i in range(1, n + 1):
            m = imaging.read(jdir / f"target_{i}.png", "L") > 127
            out[m] = ZONE_COLORS[(i - 1) % len(ZONE_COLORS)][1]
        Image.fromarray(out).save(jdir / "mask_color.png")
