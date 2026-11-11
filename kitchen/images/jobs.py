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
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .. import geometry, geometry_edit, prompts, render
from .. import backends
from ..catalog import Catalog
from ..config import Config
from ..errors import InvalidInput
from ..store import ConflictError
from .request import KINDS, MODES, NewJob, TaskInput
from .base_images import BaseImages
from .common import JobEnv
from .packages import Packages
from .request_builder import RequestBuilder
from .results import Results
from .runners import Runners
from .runtime import Runtime



class ImageJobs:
    """Image-edit jobs: the object the service (and the adapters through it) talk to. Depends on a store, a render directory and one
    callback to write a design edit; not on KitchenService.

    ``apply(design_id, operation, base_revision, source)`` is how an accepted job changes the design (one revision).

    ``config`` carries backend settings such as the Gemini key; ``runtime`` carries the clock, id and seed sources.

    It is assembled from parts that call each other through attributes, not through inheritance: ``base`` (renders, masks, base images),
    ``builder`` (building a request), ``packages`` (request files and instructions for a model), ``results`` (check, accept, regenerate),
    ``runners`` (backends and worker threads). The public methods below only forward to them.
    """

    def __init__(self, store: Any, render_dir: str | Path, apply: Callable[..., dict[str, Any]], config: Config | None = None, runtime: Runtime | None = None,
                 catalog: Callable[[], Catalog] | None = None):
        render_dir = Path(render_dir)
        self.env = JobEnv(store, render_dir, apply, config or Config(db_path=Path(":memory:"), render_dir=render_dir), runtime or Runtime())
        if catalog is not None:
            self.env.catalog = catalog
        self.base = BaseImages(self.env)
        self.builder = RequestBuilder(self.env, self.base, self)
        self.packages = Packages(self.env)
        self.results = Results(self.env, self.base, self)
        self.runners = Runners(self.env, self.packages, self.results)
        self.store.mark_stale_jobs()

    # the shared settings: replacing them here replaces them for every part
    @property
    def store(self) -> Any:
        return self.env.store

    @property
    def render_dir(self) -> Path:
        return self.env.render_dir

    @property
    def config(self) -> Config:
        return self.env.config

    @config.setter
    def config(self, value: Config) -> None:
        self.env.config = value

    @property
    def runtime(self) -> Runtime:
        return self.env.runtime

    @runtime.setter
    def runtime(self, value: Runtime) -> None:
        self.env.runtime = value

    def view_dir(self, did: str, rev: int, view: str) -> Path:
        """Where the renders of one view of one revision live."""
        return self.base.view_dir(did, rev, view)

    def create(self, did: str, view: str, target: str | None = None, *, instruction: str = "", mode: str = "quick",
               material: str | None = None, backend: str = "recolor", reference: str | None = None, base_rev: int | None = None,
               kind: str = "edit", seed: int | None = None, params: dict[str, Any] | None = None,
               tasks: list[dict[str, Any]] | None = None, preview: bool = False, geometry_items: list[dict[str, Any]] | None = None,
               operation: str | None = None, lighting: str | None = None, style_from: str | None = None) -> dict[str, Any]:
        """Keyword form of ``submit(NewJob(...))``. tasks: [{"targetLayer": "TD1-door-1", "material": "...", "instruction": "..."}, ...];
        without tasks, target/material/instruction are one task. preview=True prepares only (mask, request.json) and stops at
        'awaiting-send' so the person can look first; send() sends it, reject() drops it."""
        return self.submit(NewJob(did=did, view=view, target=target, instruction=instruction, mode=mode, material=material,
                                  backend=backend, reference=reference, base_rev=base_rev, kind=kind, seed=seed, params=params,
                                  tasks=tasks, preview=preview, geometry_items=geometry_items, operation=operation,
                                  lighting=lighting, style_from=style_from))

    def submit(self, new: NewJob) -> dict[str, Any]:
        did, view, target, instruction, mode, material, backend = new.did, new.view, new.target, new.instruction, new.mode, new.material, new.backend
        reference, base_rev, kind, seed, params = new.reference, new.base_rev, new.kind, new.seed, new.params
        tasks, preview, geometry_items, operation, lighting = new.tasks, new.preview, new.geometry_items, new.operation, new.lighting
        if kind not in KINDS:
            raise InvalidInput("kind phải là edit, gen0 hoặc geometry_edit")
        if lighting not in (None, "", *prompts.LIGHTING):
            raise InvalidInput(f"anhSang phải là một trong: {', '.join(prompts.LIGHTING)}")
        if operation is not None:
            if operation not in geometry_edit.OPERATIONS:
                raise InvalidInput(f"thaoTac phải là một trong: {', '.join(geometry_edit.OPERATIONS)}")
            pre = geometry_edit.OPERATIONS[operation]
            if pre["kind"] != kind:
                raise InvalidInput(f"thaoTac '{operation}' dùng cho kind={pre['kind']} (đang là {kind})")
            params = params or {}
        if kind == "geometry_edit":
            if not geometry_items:
                raise InvalidInput("kind=hinh cần danh sách thao tác hình học (hinh)")
            mode = "design"  # sửa hình: chấp nhận ảnh = ghi thao tác vào thiết kế
        offered = backends.table(self.env.catalog())
        if backend not in offered:
            raise InvalidInput(f"backend phải là một trong: {', '.join(offered)}")
        if kind not in offered[backend]["kind"]:
            raise InvalidInput(f"backend '{backend}' không hỗ trợ {kind}")
        if mode not in MODES:
            raise InvalidInput("mode phải là quick hoặc design")
        task_list: list[TaskInput]
        if kind == "geometry_edit":
            task_list = []
        elif kind == "edit" and not tasks:  # một việc: yêu cầu thuộc về việc đó, không lặp ở cấp job
            task_list, instruction = self.builder.norm_tasks(None, target, material, instruction), ""
        else:
            task_list = self.builder.norm_tasks(tasks, None, None, "") if kind == "edit" else []
        latest = self.store.get(did)[1]
        if base_rev is not None and base_rev != latest:
            raise ConflictError(f"baseRev={base_rev} nhưng bản mới nhất là {latest}; hãy tải lại")
        spec, rev, scene, d, man = self.base.ensure_render(did, latest, view)
        jid = f"job-{self.runtime.new_id()}"
        jdir = d / "jobs" / jid
        jdir.mkdir(parents=True, exist_ok=True)
        prepared = False
        try:
            req = self.builder.prepare(jid, jdir, d, spec, rev, scene, man,
                                replace(new, mode=mode, instruction=instruction, params=params, lighting=lighting or "daylight"), task_list)
            prepared = True
        finally:
            if not prepared:  # nothing half-written is left behind when the request cannot be built
                shutil.rmtree(jdir, ignore_errors=True)
        job = self.store.create_job({"id": jid, "design_id": did, "rev": rev, "view": view, "render_key": man["renderKey"],
                                     "kind": kind, "mode": mode, "target": req.get("targetLayer"), "backend": backend, "status": "running",
                                     "request": req})
        self.store.update_job(jid, result={"dir": str(jdir), **({"newRenderKey": req.get("newRenderKey", "")} if kind == "geometry_edit" else {})})
        try:
            self.packages.export_request(jid)  # request.json tự chứa (chỉ dẫn + ảnh gốc + mask nhúng) cho mọi backend
        except (OSError, ValueError, TypeError, KeyError):  # the side file is a convenience; the job does not depend on it
            pass
        if preview:
            return self.store.update_job(jid, "awaiting-send", {"preview": True})
        return self.runners.dispatch(job)

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
            kt = json.loads(self.packages.export_request(jid).read_text(encoding="utf-8")).get("validation") or {}
            if not kt.get("ok", True):
                raise InvalidInput("Request chưa đạt kiểm tra, chưa gửi: " + "; ".join(kt.get("errors", [])))
        job = self.store.update_job(jid, "running")
        return self.runners.dispatch(job)

    # ---- forwarding to the parts
    def ensure_render(self, did: str, rev: int | None, view: str, width: int | None = None, height: int | None = None):
        return self.base.ensure_render(did, rev, view, width, height)

    def layers(self, did: str, view: str, rev: int | None = None, all_layers: bool = False) -> dict:
        return self.base.layers(did, view, rev, all_layers)

    def mask_png(self, did: str, view: str, layer_id: str, rev: int | None = None) -> bytes:
        return self.base.mask_png(did, view, layer_id, rev)

    def pick(self, did: str, view: str, x: int, y: int, rev: int | None = None, radius: int = 0) -> dict:
        return self.base.pick(did, view, x, y, rev, radius)

    def save_beauty(self, did: str, view: str, image: bytes, rev: int | None = None) -> dict:
        """Ảnh render three.js (trình duyệt) -> beauty.png của rev/góc; dùng làm ảnh gốc khi chưa có ảnh AI đã duyệt."""
        return self.base.save_beauty(did, view, image, rev)

    def import_base(self, did: str, view: str, image: bytes, rev: int | None = None, source: str = 'external image', fit: str = 'reject') -> dict:
        """Replace the base image of a rev/view with an externally generated image (e.g. a fully lit ChatGPT render)."""
        return self.base.import_base(did, view, image, rev, source, fit)

    def clear_imported_base(self, did: str, view: str, rev: int | None = None) -> dict:
        """Drop the imported base image of a rev/view so the default base image order applies again."""
        return self.base.clear_imported_base(did, view, rev)

    def reference(self, did: str, view: str, key: str, d: Path) -> tuple[Path, dict]:
        return self.base.reference(did, view, key, d)

    def export_request(self, jid: str) -> Path:
        """Xuất request gửi AI, đã LỌC bỏ thông tin hệ thống AI không dùng (renderKey, id chi tiết, số pixel, prompt kiểu tag…)."""
        return self.packages.export_request(jid)

    def export_full(self, jid: str) -> Path:
        """Bản ĐẦY ĐỦ để kiểm tra (không gửi AI): toàn bộ yêu cầu nội bộ (renderKey, chi tiết bị sửa, thao tác thiết kế chờ ghi,"""
        return self.packages.export_full(jid)

    def submit_result(self, jid: str, image: bytes) -> dict:
        return self.results.submit_result(jid, image)

    def accept(self, jid: str, apply_to_design: bool = False, base_rev: int | None = None) -> dict:
        return self.results.accept(jid, apply_to_design, base_rev)

    def view_status(self, did: str, rev: int | None = None) -> dict:
        return self.results.view_status(did, rev)

    def regenerate_stale(self, did: str, views: list[str] | None = None, backend: str = 'recolor', base_rev: int | None = None) -> dict:
        return self.results.regenerate_stale(did, views, backend, base_rev)

    def reject(self, jid: str) -> dict:
        return self.results.reject(jid)

    def regenerate(self, jid: str, seed: int | None = None) -> dict[str, Any]:
        """A new job with the same request (and a new seed when given)."""
        return self.results.regenerate(jid, seed)

    def get(self, jid: str) -> dict:
        return self.results.get(jid)

    def list(self, did: str | None = None, view: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
        return self.results.list(did, view, status, limit)

    def wait(self, jid: str, timeout: float = 60) -> dict:
        return self.runners.wait(jid, timeout)
