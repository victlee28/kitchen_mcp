"""Image-edit jobs: the class the service (and the adapters through it) talk to, assembled from the parts of this package.

Image Edit Orchestrator: yêu cầu sửa ảnh -> kiểm tra -> mask/prompt -> backend -> ghép strict -> kiểm tra -> duyệt.

Hai chế độ:
- `design`    : sửa vật liệu trong thiết kế. Phạm vi mask = mọi chi tiết đổi vật liệu theo thao tác đó
                (vd cả mặt trước module). Thao tác chỉ ghi vào thiết kế khi người dùng CHẤP NHẬN ảnh.
- `quick`     : chỉ sửa ảnh, đúng layer đã chọn. Khi chấp nhận có thể "Áp vào thiết kế" nếu đã nêu vật liệu.

Một job có thể gồm nhiều việc (`tasks`): mỗi việc một layer + vật liệu/yêu cầu riêng. Các việc không được chạm
cùng một chi tiết (mask rời nhau), ghép từng vùng vào ảnh gốc, và khi chấp nhận thì mọi thao tác thiết kế ghi thành MỘT rev.

Ảnh gốc: ảnh đã chấp nhận gần nhất cùng (thiết kế, góc nhìn, renderKey); chưa có thì albedo.png.
renderKey = băm hình học + camera + kích thước, nên đổi vật liệu không làm mất ảnh gốc / mask.
"""
from __future__ import annotations

import json
import shutil
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .. import geometry, geometry_edit, prompts, render
from ..backends import BACKENDS
from ..config import Config
from ..errors import InvalidInput
from ..store import ConflictError
from .base_images import BaseImages
from .packages import Packages
from .request import KINDS, MODES, NewJob, TaskInput
from .request_builder import RequestBuilder
from .results import Results
from .runners import Runners
from .runtime import Runtime



class ImageJobs(BaseImages, RequestBuilder, Packages, Runners, Results):
    """Image-edit jobs. Depends on a store, a render directory and one callback to write a design edit; not on KitchenService.

    ``apply(design_id, operation, base_revision, source)`` is how an accepted job changes the design (one revision).

    ``config`` carries the backend settings (ComfyUI url, Gemini key...); ``runtime`` the clock, id and seed sources.
    """

    def __init__(self, store: Any, render_dir: str | Path, apply: Callable[..., dict[str, Any]], config: Config | None = None, runtime: Runtime | None = None):
        self.store = store
        self.render_dir = Path(render_dir)
        self._apply = apply
        self.config = config or Config(db_path=Path(":memory:"), render_dir=self.render_dir)
        self.runtime = runtime or Runtime()
        self._threads: dict[str, threading.Thread] = {}
        self.store.mark_stale_jobs()

    def create(self, did: str, view: str, target: str | None = None, *, instruction: str = "", mode: str = "quick",
               material: str | None = None, backend: str = "recolor", reference: str | None = None, base_rev: int | None = None,
               kind: str = "edit", workflow: str | None = None, seed: int | None = None, params: dict[str, Any] | None = None,
               tasks: list[dict[str, Any]] | None = None, preview: bool = False, geometry_items: list[dict[str, Any]] | None = None,
               operation: str | None = None, lighting: str | None = None) -> dict[str, Any]:
        """Keyword form of ``submit(NewJob(...))``. tasks: [{"targetLayer": "TD1-door-1", "material": "...", "instruction": "..."}, ...];
        without tasks, target/material/instruction are one task. preview=True prepares only (mask, request.json) and stops at
        'awaiting-send' so the person can look first; send() sends it, reject() drops it."""
        return self.submit(NewJob(did, view, target, instruction, mode, material, backend, reference, base_rev, kind, workflow, seed,
                                  params, tasks, preview, geometry_items, operation, lighting))

    def submit(self, new: NewJob) -> dict[str, Any]:
        did, view, target, instruction, mode, material, backend = new.did, new.view, new.target, new.instruction, new.mode, new.material, new.backend
        reference, base_rev, kind, workflow, seed, params = new.reference, new.base_rev, new.kind, new.workflow, new.seed, new.params
        tasks, preview, geometry_items, operation, lighting = new.tasks, new.preview, new.geometry_items, new.operation, new.lighting
        if kind not in KINDS:
            raise InvalidInput("kind phải là edit, gen0 hoặc geometry_edit")
        if lighting not in (None, "", *prompts.LIGHTING):
            raise InvalidInput(f"anhSang phải là một trong: {', '.join(prompts.LIGHTING)}")
        if operation is not None:  # bảng thao tác: workflow + trọng số ControlNet mặc định theo loại việc
            if operation not in geometry_edit.OPERATIONS:
                raise InvalidInput(f"thaoTac phải là một trong: {', '.join(geometry_edit.OPERATIONS)}")
            pre = geometry_edit.OPERATIONS[operation]
            if pre["kind"] != kind:
                raise InvalidInput(f"thaoTac '{operation}' dùng cho kind={pre['kind']} (đang là {kind})")
            workflow = workflow or pre["workflow"]
            params = {**pre["params"], **(params or {})}
        if kind == "geometry_edit":
            if not geometry_items:
                raise InvalidInput("kind=hinh cần danh sách thao tác hình học (hinh)")
            mode = "design"  # sửa hình: chấp nhận ảnh = ghi thao tác vào thiết kế
        if backend not in BACKENDS:
            raise InvalidInput(f"backend phải là một trong: {', '.join(BACKENDS)}")
        if kind not in BACKENDS[backend]["kind"]:
            raise InvalidInput(f"backend '{backend}' không hỗ trợ {kind}")
        if mode not in MODES:
            raise InvalidInput("mode phải là quick hoặc design")
        task_list: list[TaskInput]
        if kind == "geometry_edit":
            task_list = []
        elif kind == "edit" and not tasks:  # một việc: yêu cầu thuộc về việc đó, không lặp ở cấp job
            task_list, instruction = self._norm_tasks(None, target, material, instruction), ""
        else:
            task_list = self._norm_tasks(tasks, None, None, "") if kind == "edit" else []
        latest = self.store.get(did)[1]
        if base_rev is not None and base_rev != latest:
            raise ConflictError(f"baseRev={base_rev} nhưng bản mới nhất là {latest}; hãy tải lại")
        spec, rev, scene, d, man = self.ensure_render(did, latest, view)
        jid = f"job-{self.runtime.new_id()}"
        jdir = d / "jobs" / jid
        jdir.mkdir(parents=True, exist_ok=True)
        prepared = False
        try:
            req = self._prepare(jid, jdir, d, spec, rev, scene, man,
                                replace(new, mode=mode, instruction=instruction, workflow=workflow, params=params, lighting=lighting or "daylight"), task_list)
            prepared = True
        finally:
            if not prepared:  # nothing half-written is left behind when the request cannot be built
                shutil.rmtree(jdir, ignore_errors=True)
        job = self.store.create_job({"id": jid, "design_id": did, "rev": rev, "view": view, "render_key": man["renderKey"],
                                     "kind": kind, "mode": mode, "target": req.get("targetLayer"), "backend": backend, "status": "running",
                                     "request": req})
        self.store.update_job(jid, result={"dir": str(jdir), **({"newRenderKey": req.get("newRenderKey", "")} if kind == "geometry_edit" else {})})
        try:
            self.export_request(jid)  # request.json tự chứa (chỉ dẫn + ảnh gốc + mask nhúng) cho mọi backend
        except (OSError, ValueError, TypeError, KeyError):  # the side file is a convenience; the job does not depend on it
            pass
        if preview:
            return self.store.update_job(jid, "awaiting-send", {"preview": True})
        return self._dispatch(job)

    def send(self, jid: str) -> dict:
        """Gửi job đang chờ (đã xem trước) sang backend. Thiết kế đổi hình học/camera sau khi tạo thì từ chối."""
        job = self.store.get_job(jid)
        if job["status"] != "awaiting-send":
            raise InvalidInput(f"Chỉ gửi được job đang chờ gửi (hiện: {job['status']})")
        spec, rev = self.store.get(job["design_id"])
        views = geometry.views_of(spec)
        if job["view"] in views:
            W, H = job["request"]["size"]
            if render.render_key(geometry.compile_spec(spec), views[job["view"]], W, H) != job["render_key"]:
                raise InvalidInput("Thiết kế đã đổi hình học/góc nhìn sau khi tạo job; mask không còn khớp — hãy tạo job mới")
        if job["backend"] in ("gemini", "job-package"):  # model nhận chỉ dẫn: request phải đủ ảnh, đúng kích thước
            kt = json.loads(self.export_request(jid).read_text(encoding="utf-8")).get("validation") or {}
            if not kt.get("ok", True):
                raise InvalidInput("Request chưa đạt kiểm tra, chưa gửi: " + "; ".join(kt.get("errors", [])))
        job = self.store.update_job(jid, "running")
        return self._dispatch(job)
