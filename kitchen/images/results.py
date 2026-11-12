"""What comes back: raw result, strict compositing, review, accept / reject / regenerate, listing."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import json

from PIL import Image

from .. import edit, geometry, imaging, layers, view_sync
from ..errors import InvalidInput
from ..errors import KitchenError
from .base_images import BaseImages
from .common import Component, JobEnv, FEATHER_PX
if TYPE_CHECKING:
    from .jobs import ImageJobs
from .request import JobRequest, NewJob, task_inputs


class Results(Component):
    def __init__(self, env: JobEnv, base: BaseImages, owner: "ImageJobs") -> None:
        super().__init__(env)
        self.base = base
        self.owner = owner      # the assembled ImageJobs: regenerate creates jobs through it and view_sync takes it

    def submit_result(self, jid: str, image: bytes) -> dict:
        job = self.store.get_job(jid)
        if job["status"] in ("accepted", "rejected", "running"):
            raise InvalidInput(f"The job is {job['status']}; it takes no image", code="job-takes-no-image", params={"status": job["status"]})
        jdir = Path(job["result"]["dir"])
        import io
        try:
            im = Image.open(io.BytesIO(image)).convert("RGB")
        except (OSError, ValueError) as e:
            raise InvalidInput("The image cannot be read (PNG/JPEG needed)", code="bad-image") from e
        im.save(jdir / "raw.png")
        return self.finish(jid, {"backend": {"name": job["backend"], "submitManual": True}})

    def finish(self, jid: str, extra: dict) -> dict:
        job = self.store.get_job(jid)
        jdir = Path(job["result"]["dir"])
        req = job["request"]
        W, H = req["size"]
        raw, resized = imaging.load_rgb(jdir / "raw.png", (W, H))
        if job["kind"] == "gen0":
            Image.fromarray(raw).save(jdir / "composite.png")
            rep = {"variant": "gen0", "resize": resized}
            lp = self.view_dir(job["design_id"], job["rev"], job["view"]) / "lines.png"
            if lp.exists():
                rep["lineMatch"] = imaging.edge_alignment(raw, imaging.read(lp, "L"))
                if rep["lineMatch"].get("khop") is False:
                    rep["warning"] = "Ảnh AI có vẻ lệch hình học so với bản vẽ: mask các lần sửa sau có thể không khớp"
            (jdir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
            return self.store.update_job(jid, "needs-review", {**extra, "report": rep}, error=rep.get("warning"))
        ref = imaging.read(jdir / "reference.png", "RGB")
        lines_p = jdir / "lines_moi.png" if (jdir / "lines_moi.png").exists() else \
            self.view_dir(job["design_id"], job["rev"], job["view"]) / "lines.png"  # sửa hình: so biên với nét MỚI
        lines = imaging.read(lines_p, "L") if lines_p.exists() else None
        tasks = req.get("tasks") or [{"targetLayer": job["target"]}]
        comp = ref.copy()
        per = []
        raws = []
        for i, t in enumerate(tasks, 1):
            tp, mp = jdir / f"target_{i}.png", jdir / f"mask_{i}.png"
            if not tp.exists():  # job cũ (trước khi có nhiều việc)
                tp, mp = jdir / "target.png", jdir / "mask.png"
            raw_i, _ = imaging.load_rgb(jdir / f"raw_{i}.png", (W, H)) if (jdir / f"raw_{i}.png").exists() else (raw, resized)
            tm = imaging.read(tp, "L") > 127
            comp = imaging.composite(comp, raw_i, imaging.alpha(tm, FEATHER_PX))
            raws.append((raw_i, tm, imaging.read(mp, "L") > 127))
        Image.fromarray(comp).save(jdir / "composite.png")
        for i, (t, (raw_i, tm, region)) in enumerate(zip(tasks, raws), 1):
            c = imaging.check(ref, raw_i, comp, tm, region, lines)
            per.append({"task": i, "targetLayer": t["targetLayer"], "maskPixels": int(tm.sum()), "insideMask": c["insideMask"],
                        **({"bien": c["bien"]} if "bien" in c else {}), "rawImage": c["rawImage"]})
        union = imaging.read(jdir / "target.png", "L") > 127
        region_all = imaging.read(jdir / "mask.png", "L") > 127
        overall = imaging.check(ref, raw, comp, union, region_all, lines)
        rep = {"variant": "edit", "resize": resized, "renderKey": job["render_key"], "rev": job["rev"],
               "targetLayer": job["target"], "maskPixels": int(union.sum()), "preserveMode": "strict", **overall, "task": per}
        unchanged = [p["task"] for p in per if not p["insideMask"]["changed"]]
        if unchanged and len(unchanged) == len(per):
            rep["warning"] = "Vùng đích gần như không đổi — model có thể đã bỏ qua mask/prompt"
        elif unchanged:
            rep["warning"] = f"Việc {', '.join(map(str, unchanged))} gần như không đổi; các việc khác đã đổi"
        ok = rep["outsideMask"]["setPreserve"] and len(unchanged) < len(per)
        status = "needs-review" if ok else "error:check-failed"
        (jdir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.store.update_job(jid, status, {**extra, "report": rep}, error=rep.get("warning"))

    def accept(self, jid: str, apply_to_design: bool = False, base_rev: int | None = None) -> dict:
        job = self.store.get_job(jid)
        if job["status"] != "needs-review":
            raise InvalidInput(f"Only a job waiting for review can be accepted (now: {job['status']})", code="job-not-in-review", params={"status": job["status"]})
        req = job["request"]
        design = None
        if job["kind"] == "geometry_edit":  # sửa hình: ảnh chỉ đúng khi thiết kế đổi theo -> luôn ghi rev
            res = self.env.apply(job["design_id"], req["designOp"], base_rev if base_rev is not None else job["rev"], f"image-job:{jid}")
            W, H = req["size"]
            _, _, _, _, man = self.base.ensure_render(job["design_id"], res["rev"], job["view"], W, H)
            if man["renderKey"] != req["newRenderKey"]:
                raise InvalidInput("The new revision renders differently from the job's sample (renderKey differs)", code="render-key-mismatch")
            design = {"rev": res["rev"], "op": req["designOp"], "scope": req.get("scope")}
        elif job["mode"] == "design" or apply_to_design:
            tasks = req.get("tasks") or [{"targetLayer": job["target"], "material": req.get("material"),
                                          "pendingOp": req.get("pendingOp"), "scope": req.get("scope")}]
            ops, scope, skip = [], [], []
            spec, latest = self.store.get(job["design_id"])
            scene = geometry.compile_spec(spec, self.env.design_catalog(job["design_id"], latest))
            cur = spec
            for i, t in enumerate(tasks, 1):
                op, pv = t.get("pendingOp"), t.get("scope")
                if op is None:
                    if not t.get("material"):
                        skip.append(f"việc {i}: không nêu vật liệu")
                        continue
                    r = layers.design_op(cur, layers.resolve(layers.catalogue(cur, scene), t["targetLayer"])[0], t["material"], scene)
                    if r is None:
                        skip.append(f"việc {i}: layer chưa sửa được trong thiết kế")
                        continue
                    op, pv = r
                cur = edit.apply_op(cur, op, self.env.catalog())
                ops.append(op)
                scope.append(pv)
            if not ops:
                why = "; ".join(skip)
                raise InvalidInput(f"No task could be applied to the design ({why})", code="nothing-applied", params={"reasons": why})
            op = edit.combine_ops(ops)
            res = self.env.apply(job["design_id"], op, base_rev if base_rev is not None else job["rev"], f"image-job:{jid}")
            design = {"rev": res["rev"], "op": op, "scope": "; ".join(scope), **({"skip": skip} if skip else {})}
        now = self.runtime.now()
        try:  # what the approved image shows, for the multi-view consistency check (see view_sync)
            appearance = view_sync.snapshot(self.owner, job["design_id"], job["view"], design["rev"] if design else job["rev"], req.get("size"))
        except (KitchenError, ValueError, KeyError, OSError):  # acceptance must not fail because the snapshot could not be taken
            appearance = None
        return self.store.update_job(jid, "accepted", {"acceptNow": now, **({"design": design} if design else {}),
                                                      **({"appearance": appearance} if appearance else {})})

    def view_status(self, did: str, rev: int | None = None) -> dict:
        return view_sync.view_status(self.owner, did, rev)

    def regenerate_stale(self, did: str, views: list[str] | None = None, backend: str = "recolor", base_rev: int | None = None) -> dict:
        return view_sync.regenerate_stale(self.owner, did, views, backend, base_rev)

    def reject(self, jid: str) -> dict:
        job = self.store.get_job(jid)
        if job["status"] == "accepted":
            raise InvalidInput("The job was already accepted", code="job-already-accepted")
        return self.store.update_job(jid, "rejected")

    def regenerate(self, jid: str, seed: int | None = None) -> dict[str, Any]:
        """A new job with the same request (and a new seed when given)."""
        j = self.store.get_job(jid)
        r: JobRequest = j["request"]
        ref = r.get("referenceImage") or {}
        reference = ref.get("jobId") or (ref.get("type") if ref.get("type") in ("albedo", "beauty", "imported") else None)
        preview = bool(j["result"].get("preview"))
        if j["kind"] == "geometry_edit":
            first = (r.get("tasks") or [None])[0]
            return self.owner.submit(NewJob(j["design_id"], j["view"], instruction=(first or {}).get("instruction") or "", mode="design",
                                      backend=j["backend"], reference=reference, kind="geometry_edit", seed=seed,
                                      params=r.get("params"), preview=preview, geometry_items=r.get("originalGeometry"),
                                      operation=r.get("operation"), lighting=r.get("lighting")))
        tasks = [dict(t) for t in task_inputs(r.get("tasks") or [])] or None
        return self.owner.submit(NewJob(j["design_id"], j["view"], target=None if tasks else r.get("targetLayer"), instruction=r.get("instruction", ""),
                                  mode=j["mode"], material=None if tasks else r.get("material"), backend=j["backend"], reference=reference,
                                  kind=j["kind"], seed=seed, params=r.get("params"), tasks=tasks,
                                  preview=preview, lighting=r.get("lighting")))

    def get(self, jid: str) -> dict:
        self.store.mark_stale_jobs()
        return self.store.get_job(jid)

    def list(self, did: str | None = None, view: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
        self.store.mark_stale_jobs()
        return self.store.list_jobs(did, view, status, limit)
