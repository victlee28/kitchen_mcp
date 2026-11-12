"""Building the request of a job: tasks, masks, prompt inputs, geometry edits."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import json
import shutil

from PIL import Image
import numpy as np

from .. import appliance_models, view_sync, edit, geometry, geometry_edit, imaging, layers, prompts, render, vocab
from ..errors import InvalidInput
if TYPE_CHECKING:
    from .jobs import ImageJobs
from .request import JobRequest, NewJob, Task, TaskInput
from .base_images import BaseImages
from .common import Component, JobEnv, GROW_PX, MAX_TASKS, ZONE_COLORS, MOLDING_EN, describe_position

class RequestBuilder(Component):
    def __init__(self, env: JobEnv, base: BaseImages, owner: "ImageJobs") -> None:
        super().__init__(env)
        self.base = base
        self.owner = owner      # the assembled ImageJobs (view_sync looks at the other views through it)

    @staticmethod
    def norm_tasks(tasks: list[dict[str, Any]] | None, target: str | None, material: str | None, instruction: str) -> list[TaskInput]:
        if not tasks:
            if not target:
                raise InvalidInput("targetLayer or a list of tasks is needed", code="no-task")
            tasks = [{"targetLayer": target, "material": material, "instruction": instruction}]
        if not isinstance(tasks, list) or len(tasks) > MAX_TASKS:
            raise InvalidInput(f"tasks must be a list of at most {MAX_TASKS}", code="too-many-tasks", params={"max": MAX_TASKS})
        out: list[TaskInput] = []
        for i, t in enumerate(tasks, 1):
            if not isinstance(t, dict):
                raise InvalidInput(f"Task {i} is not valid", code="bad-task", params={"n": i})
            tl = t.get("targetLayer") or t.get("target") or t.get("target_layer")
            if not tl:
                raise InvalidInput(f"Task {i} has no targetLayer", code="task-no-layer", params={"n": i})
            out.append({"targetLayer": str(tl), "material": (t.get("material") or t.get("material") or None),
                        "instruction": str(t.get("instruction") or "").strip()})
        return out

    def prepare(self, jid: str, jdir: Path, d: Path, spec: Any, rev: int, scene: Any, man: dict[str, Any], new: NewJob,
                 tasks: list[TaskInput]) -> JobRequest:
        """``new`` carries the already-resolved mode, params and lighting; ``tasks`` the normalised task inputs."""
        did, view, instruction, mode, backend, reference, kind = new.did, new.view, new.instruction, new.mode, new.backend, new.reference, new.kind
        seed, params, geometry_items, operation, lighting = new.seed, new.params, new.geometry_items, new.operation, new.lighting or "daylight"
        W, H = man["width"], man["height"]
        req: JobRequest = {"designId": did, "baseRevision": rev, "view": view, "renderKey": man["renderKey"], "kind": kind, "mode": mode,
               "instruction": instruction, "backend": backend,
               "seed": int(seed if seed is not None else self.runtime.new_seed()), "params": params or {},
               "size": [W, H], "preserve": "strict", "negativePrompt": prompts.negative_prompt(None, self.env.catalog()),
               "lighting": lighting,  # ánh sáng cho ảnh đầy đủ (gen-0); sửa vùng thì bám ánh sáng ảnh gốc
               "prompt": "", "globalPrompt": ""}  # both filled by the branch of the kind below
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
                    raise InvalidInput(f"Task {i}: layer {t['targetLayer']!r} is locked", code="layer-locked", params={"n": i, "layer": t["targetLayer"]})
                rec: Task = {"targetLayer": t["targetLayer"], "material": t["material"], "instruction": t["instruction"]}
                if mode == "design":
                    if not t["material"]:
                        raise InvalidInput(f"Task {i} ({t['targetLayer']}): design mode needs a material", code="task-no-material", params={"n": i, "layer": t["targetLayer"]})
                    op = layers.design_op(cur, layers.resolve(layers.catalogue(cur, scene), t["targetLayer"])[0], t["material"], scene)
                    if op is None:
                        raise InvalidInput(f"Task {i}: {layer['name']!r} cannot be changed in the design yet; use quick mode", code="layer-not-editable",
                                   params={"n": i, "name": layer["name"]})
                    nxt = edit.apply_op(cur, op[0], self.env.catalog())
                    if render.scene_hash(geometry.compile_spec(nxt)) != render.scene_hash(scene):
                        raise InvalidInput(f"Task {i}: the change alters the geometry; an image edit only takes material changes", code="task-changes-geometry", params={"n": i})
                    selected = list(ids)
                    ids = layers.changed_parts(cur, nxt, scene)
                    if set(ids) != set(selected):  # the spec can only express a wider or different scope: say so instead of hiding it
                        rec["scopeNote"] = f"Thiết kế đổi {len(ids)} chi tiết, vùng chọn có {len(selected)}"
                    if not ids:
                        raise InvalidInput(f"Task {i}: the new material is the current one", code="same-material", params={"n": i})
                    rec["pendingOp"] = op[0]
                    rec["scope"] = op[1]
                    cur = nxt
                clash = sorted({owner[p] for p in ids if p in owner})
                if clash:
                    both = [p for p in ids if p in owner]
                    raise InvalidInput(f"Tasks {i} and {clash[0]} change the same parts {', '.join(both[:4])}", code="tasks-overlap",
                                   params={"n": i, "other": clash[0], "parts": ', '.join(both[:4])})
                tmask = imaging.mask_of(d, ids)
                if not tmask.any():
                    raise InvalidInput(f"Task {i}: layer {t['targetLayer']!r} is not seen from view {view!r}", code="layer-not-visible",
                                   params={"n": i, "layer": t["targetLayer"], "view": view})
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
                rec["materialText"] = " ".join(x for x in (vocab.to_english(material_text, self.env.catalog()), material_text and f"({material_text})") if x)
                touched = self._appliances_in(d, imaging.grow(tmask, GROW_PX), cur)      # plan A5: the AI must know the appliances it redraws
                if touched:
                    rec["appliances"] = touched
                    rec["prompt"] = f"{rec['prompt']} " + " ".join(appliance_models.sentence(f) for f in touched)
                recs.append(rec)
            ref_path, ref_info = self.base.pick_reference(did, view, man["renderKey"], d, reference)
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
            req["globalPrompt"] = prompts.global_prompt(cur, self.env.catalog())
            req["targetLayer"] = first["targetLayer"] + (f" +{len(recs) - 1}" if len(recs) > 1 else "")
            # Keep the single-task prompt field for request consumers.
            req["prompt"] = first.get("prompt", "") if len(recs) == 1 else "; ".join(f"[{k + 1}] {r.get('prompt', '')}" for k, r in enumerate(recs))
            req["material"] = first["material"] if len(recs) == 1 else None
            req["targetParts"] = [p for r in recs for p in r.get("targetParts", [])]
            req["scope"] = "; ".join(r.get("scope", "") for r in recs if r.get("scope")) or None
        else:
            req["globalPrompt"] = prompts.global_prompt(spec, self.env.catalog())
            req["photoImage"] = prompts.full(spec, lighting, self.env.catalog())
            req["prompt"] = " ".join(x for x in (prompts.global_prompt(spec, self.env.catalog()), prompts.full(spec, lighting, self.env.catalog()), instruction.strip()) if x)
        self._attach_style(jdir, req, new, (W, H))
        (jdir / "job.json").write_text(json.dumps({"id": jid, **req}, ensure_ascii=False, indent=2), encoding="utf-8")
        return req

    def _attach_style(self, jdir: Path, req: JobRequest, new: NewJob, size: tuple[int, int]) -> None:
        """Copy the approved image of another view next to the job (``style_reference.png``) as a guide for materials and light.

        ``style_from``: "none" never; a view name; "auto" the newest approved image of another view that is still true to the design.
        Left out (None) it is automatic for a first image (gen0), where the views would otherwise be made independently, and off otherwise."""
        wanted = new.style_from
        if wanted == "none" or (wanted is None and new.kind != "gen0"):
            return
        src = view_sync.style_source(self.owner, new.did, new.view, wanted or "auto")
        if src is None:
            return
        job = self.store.get_job(src["jobId"])
        img, _ = imaging.load_rgb(Path(job["result"]["dir"]) / "composite.png", size)
        Image.fromarray(img).save(jdir / "style_reference.png")
        req["styleReference"] = src

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
            nxt = edit.apply_op(nxt, op, self.env.catalog())
        pin = geometry_edit.pin_cameras(spec, nxt)
        if pin:
            nxt = edit.apply_op(nxt, pin, self.env.catalog())
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
            raise InvalidInput(f"The change alters nothing seen from view {view!r}", code="change-not-visible", params={"view": view})
        if m.mean() > 0.85:
            raise InvalidInput("The change alters almost the whole image (did the camera or framing change?); use gen-0", code="change-too-large")
        imaging.save_mask(m, jdir / "target_1.png")
        imaging.save_mask(m, jdir / "target.png")
        region = imaging.grow(m, GROW_PX)
        imaging.save_mask(region, jdir / "mask_1.png")
        imaging.save_mask(region, jdir / "mask.png")
        self._color_mask(jdir, 1)
        Image.fromarray(lines_new).save(jdir / "lines_moi.png")
        Image.fromarray(geometry_edit.preview(nd, lines_new)).save(jdir / "new_geometry.png")
        ref_path, ref_info = self.base.pick_reference(did, view, man["renderKey"], d, reference)
        ref, _ = imaging.load_rgb(ref_path, (W, H))
        Image.fromarray(ref).save(jdir / "reference.png")
        Image.fromarray(imaging.mark_regions(ref, [(m, ZONE_COLORS[0][1], "1")], gap=GROW_PX + 2)).save(jdir / "reference_marked.png")
        en = "; ".join(x["en"] for x in desc)
        vi = "; ".join(x["vi"] for x in desc)
        common = prompts.global_prompt(nxt, self.env.catalog())
        task: Task = {"targetLayer": "geometry_edit", "name": vi, "roleEn": en, "position": describe_position(m), "instruction": instruction, "material": None,
                      "operation": tt, "targetParts": info["part"], "maskPixels": int(m.sum()),
                      "prompt": ", ".join(x for x in (en, instruction, common) if x)}
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

    def _appliances_in(self, d: Path, region: Any, spec: Any) -> list[dict[str, Any]]:
        """``appliance_models.ai_facts`` of every appliance the region of the picture covers (its pixels in instances.png)."""
        try:
            inst, meta = imaging.load_instances(d)
        except (OSError, ValueError, KeyError):
            return []
        values = set(int(v) for v in np.unique(inst[region]))
        modules = {x.get("module") for x in meta.get("instances", []) if int(x.get("value", -1)) in values}
        out = []
        catalog = self.env.catalog()
        by_id = appliance_models.models(catalog)
        for a in spec.appliances:
            if a.id in modules:
                rendering = "model-3d" if by_id.get(appliance_models.model_id(a, catalog) or "", {}).get("asset3d") else "box-placeholder"
                out.append(appliance_models.ai_facts(spec, a, rendering, catalog))
        return out

    @staticmethod
    def _color_mask(jdir: Path, n: int) -> None:
        """Ảnh mask màu (mỗi việc một màu) để mô tả nhiều vùng cho model nhận chỉ dẫn (Gemini, sửa tay)."""
        first = imaging.read(jdir / "mask_1.png", "L")
        out = np.zeros((*first.shape, 3), np.uint8)
        for i in range(1, n + 1):
            m = imaging.read(jdir / f"target_{i}.png", "L") > 127
            out[m] = ZONE_COLORS[(i - 1) % len(ZONE_COLORS)][1]
        Image.fromarray(out).save(jdir / "mask_color.png")
