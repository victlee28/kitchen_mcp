"""Run image jobs. Workers run in a thread and never leave a job in the running state."""
from __future__ import annotations

from pathlib import Path
import shutil
import threading

from PIL import Image

from .. import backends, imaging, vocab
from ..backends import BackendError
from ..errors import InvalidInput
from .packages import Packages
from .results import Results
from .request import JobRequest, size_of
from .common import Component, JobEnv


class Runners(Component):
    def __init__(self, env: JobEnv, packages: Packages, results: Results) -> None:
        super().__init__(env)
        self.packages = packages
        self.results = results

    def dispatch(self, job: dict) -> dict:
        jid, b = job["id"], job["backend"]
        jdir = Path(self.store.get_job(jid)["result"]["dir"])
        req = job["request"]
        try:
            if b == "recolor" and req["kind"] == "geometry_edit":  # không AI: dán hình mẫu (màu phẳng + nét) vào vùng đổi để xem nhanh
                shutil.copyfile(jdir / "new_geometry.png", jdir / "raw.png")
                return self.results.finish(jid, {"backend": {"name": "recolor", "sampleGeometry": True}})
            if b == "recolor":
                img = imaging.read(jdir / "reference.png", "RGB")
                used = []
                catalog = self.env.catalog()
                for i, t in enumerate(req.get("tasks", []), 1):
                    rgb = vocab.color(t.get("material") or "", catalog) or vocab.color(t.get("instruction") or "", catalog)
                    if not rgb:
                        raise BackendError("unsupported", f"Việc {i} ({t['targetLayer']}): không suy được màu từ vật liệu/yêu cầu; "
                                                           "ghi rõ màu (vd 'xanh rêu') hoặc dùng backend AI")
                    img = imaging.recolor(img, imaging.read(jdir / f"target_{i}.png", "L") > 127, vocab.hex_rgb(rgb))
                    used.append(rgb)
                Image.fromarray(img).save(jdir / "raw.png")
                return self.results.finish(jid, {"backend": {"name": "recolor", "color": used}})
            if b == "job-package":
                return self.packages.export_package(jid, jdir, req)
            if b == "gemini":
                fn = self._run_gemini
                t = threading.Thread(target=self._run_guarded, args=(fn, jid, jdir, req), daemon=True, name=jid)
                self.env.threads[jid] = t
                t.start()
                return self.store.get_job(jid)
        except BackendError as e:
            return self.store.update_job(jid, f"error:{e.code}", error=str(e))
        raise InvalidInput(b)

    def _run_gemini(self, jid: str, jdir: Path, req: JobRequest):
        try:
            cli = backends.Gemini(self.config)
            job = self.store.get_job(jid)
            text, named = self.packages.ai_input(job, jdir, req)
            images = [p for _, p in named]
            self.store.update_job(jid, result={"geminiPrompt": text})
            info = cli.generate(text, images, jdir / "raw.png", size_of(req))
            self.results.finish(jid, {"backend": {"name": "gemini", **info}})
        except BackendError as e:
            self.store.update_job(jid, f"error:{e.code}", error=str(e))

    def wait(self, jid: str, timeout: float = 60) -> dict:
        t = self.env.threads.get(jid)
        if t:
            t.join(timeout)
        return self.store.get_job(jid)

    def _run_guarded(self, fn, jid: str, jdir: Path, req: JobRequest) -> None:
        """Thread entry. A job must never stay 'running' because a worker raised something unforeseen: mark it failed, then re-raise
        so the thread excepthook still logs the traceback. Known backend failures are handled inside the runners."""
        try:
            fn(jid, jdir, req)
        except BaseException as e:
            self.store.update_job(jid, "error:generation-failed", error=f"{type(e).__name__}: {e}")
            raise
