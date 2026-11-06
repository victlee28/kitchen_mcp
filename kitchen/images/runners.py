"""Running a job on a backend (recolor, job-package, ComfyUI, Gemini). Workers run in a thread and never leave a job stuck on "running"."""
from __future__ import annotations

from pathlib import Path
import shutil
import threading

from PIL import Image

from .. import backends, imaging, vocab
from ..backends import BackendError
from ..errors import InvalidInput
from .common import JobsContext, FEATHER_PX


class Runners(JobsContext):
    def _dispatch(self, job: dict) -> dict:
        jid, b = job["id"], job["backend"]
        jdir = Path(self.store.get_job(jid)["result"]["dir"])
        req = job["request"]
        try:
            if b == "recolor" and req["kind"] == "geometry_edit":  # không AI: dán hình mẫu (màu phẳng + nét) vào vùng đổi để xem nhanh
                shutil.copyfile(jdir / "new_geometry.png", jdir / "raw.png")
                return self._finish(jid, {"backend": {"name": "recolor", "sampleGeometry": True}})
            if b == "recolor":
                img = imaging.read(jdir / "reference.png", "RGB")
                used = []
                for i, t in enumerate(req["tasks"], 1):
                    rgb = vocab.color(t.get("material") or "") or vocab.color(t.get("instruction") or "")
                    if not rgb:
                        raise BackendError("unsupported", f"Việc {i} ({t['targetLayer']}): không suy được màu từ vật liệu/yêu cầu; "
                                                           "ghi rõ màu (vd 'xanh rêu') hoặc dùng backend AI")
                    img = imaging.recolor(img, imaging.read(jdir / f"target_{i}.png", "L") > 127, vocab.hex_rgb(rgb))
                    used.append(rgb)
                Image.fromarray(img).save(jdir / "raw.png")
                return self._finish(jid, {"backend": {"name": "recolor", "color": used}})
            if b == "job-package":
                return self._export_package(jid, jdir, req)
            if b in ("comfyui", "gemini"):
                fn = self._run_comfy if b == "comfyui" else self._run_gemini
                t = threading.Thread(target=self._run_guarded, args=(fn, jid, jdir, req), daemon=True, name=jid)
                self._threads[jid] = t
                t.start()
                return self.store.get_job(jid)
        except BackendError as e:
            return self.store.update_job(jid, f"error:{e.code}", error=str(e))
        raise InvalidInput(b)

    def _run_gemini(self, jid: str, jdir: Path, req: dict):
        try:
            cli = backends.Gemini(self.config)
            job = self.store.get_job(jid)
            text, named = self._ai_input(job, jdir, req)
            images = [p for _, p in named]
            self.store.update_job(jid, result={"geminiPrompt": text})
            info = cli.generate(text, images, jdir / "raw.png", tuple(req["size"]))
            self._finish(jid, {"backend": {"name": "gemini", **info}})
        except BackendError as e:
            self.store.update_job(jid, f"error:{e.code}", error=str(e))

    def _run_comfy(self, jid: str, jdir: Path, req: dict):
        try:
            wf = backends.load_workflow(req["workflow"])
            cli = backends.ComfyUI(self.config)
            tasks = req.get("tasks") or []
            if req["kind"] == "edit" and len(tasks) > 1:  # nhiều việc: chạy nối tiếp, ảnh ghép của việc trước làm ảnh vào việc sau
                cur = imaging.read(jdir / "reference.png", "RGB")
                infos = []
                for i, t in enumerate(tasks, 1):
                    Image.fromarray(cur).save(jdir / f"vao_{i}.png")
                    src = {"reference": f"vao_{i}.png", "mask": f"mask_{i}.png", "lines": "lines_inv.png", "depth": "depth.png"}
                    imgs = {k: cli.upload(jdir / src[k], f"{jid}_{i}_{k}.png") for k in wf["kitchen"].get("image", [])}
                    vals = {**self._values(req, wf), "prompt": t["prompt"], "seed": req["seed"] + i - 1}
                    infos.append(cli.run(backends.build_prompt(wf, imgs, vals, backends.model_defaults(self.config)), jdir / f"raw_{i}.png"))
                    raw_i, _ = imaging.load_rgb(jdir / f"raw_{i}.png", tuple(req["size"]))
                    cur = imaging.composite(cur, raw_i, imaging.alpha(imaging.read(jdir / f"target_{i}.png", "L") > 127, FEATHER_PX))
                Image.fromarray(cur).save(jdir / "raw.png")
                return self._finish(jid, {"backend": {"name": "comfyui", "url": cli.url, "workflow": req["workflow"], "step": infos}})
            files = {"reference": "reference.png", "mask": "mask.png", "lines": "lines_inv.png", "depth": "depth.png"}
            imgs = {k: cli.upload(jdir / files[k], f"{jid}_{k}.png") for k in wf["kitchen"].get("image", [])}
            info = cli.run(backends.build_prompt(wf, imgs, self._values(req, wf), backends.model_defaults(self.config)), jdir / "raw.png")
            self._finish(jid, {"backend": {"name": "comfyui", "url": cli.url, "workflow": req["workflow"], **info}})
        except BackendError as e:
            self.store.update_job(jid, f"error:{e.code}", error=str(e))

    def wait(self, jid: str, timeout: float = 60) -> dict:
        t = self._threads.get(jid)
        if t:
            t.join(timeout)
        return self.store.get_job(jid)

    def _run_guarded(self, fn, jid: str, jdir: Path, req: dict) -> None:
        """Thread entry. A job must never stay 'running' because a worker raised something unforeseen: mark it failed, then re-raise
        so the thread excepthook still logs the traceback. Known backend failures are handled inside the runners."""
        try:
            fn(jid, jdir, req)
        except BaseException as e:
            self.store.update_job(jid, "error:generation-failed", error=f"{type(e).__name__}: {e}")
            raise
