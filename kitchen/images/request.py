"""Typed shapes of an image job: what a caller asks for (``NewJob``) and what is stored with the job (``JobRequest``).

Both are plain JSON-like data (rule R4): a ``dataclass`` of JSON values in, a ``TypedDict`` of JSON values out, so the stored
``image_jobs.request`` column and ``job.json`` / ``request.json`` keep their shape. Keys are the ones written by
``RequestBuilder._prepare``; a key listed as ``total=False`` is present only for some kinds of job:

* ``kind = "gen0"``          a whole first image: no ``tasks``, has ``photoImage``.
* ``kind = "edit"``          one or more ``tasks`` (material / instruction per layer), has ``referenceImage``.
* ``kind = "geometry_edit"`` exactly one task plus ``designOp``, ``newRenderKey``, ``originalGeometry``...
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

JobKind = Literal["edit", "gen0", "geometry_edit"]
JobMode = Literal["quick", "design"]
KINDS: tuple[str, ...] = ("edit", "gen0", "geometry_edit")
MODES: tuple[str, ...] = ("quick", "design")


class TaskInput(TypedDict):
    """What the caller gives for one job task."""
    targetLayer: str
    material: str | None
    instruction: str


class Task(TaskInput, total=False):
    """A task after the request is built. The first three keys are the input; the rest is filled in per kind."""
    name: str | None
    roleEn: str
    typeEn: str
    position: dict[str, Any] | None
    remaining: int
    materialText: str
    prompt: str
    targetParts: list[str]
    maskPixels: int
    scope: str
    scopeNote: str
    pendingOp: dict[str, Any]
    operation: str


class StyleReference(TypedDict):
    """Where the look-alike image came from: the approved image of another view of the same design."""
    view: str
    jobId: str
    auto: bool                      # True when chosen by the system (``styleFrom`` = "auto"), False when the caller named the view


class _Core(TypedDict):
    """Keys every request has."""
    designId: str
    baseRevision: int
    view: str
    renderKey: str
    kind: str
    mode: str
    instruction: str
    backend: str
    workflow: str
    seed: int
    params: dict[str, Any]
    size: list[int]                 # [width, height] in pixels
    preserve: str                   # "strict": outside the mask the original pixels are kept
    negativePrompt: str
    lighting: str
    prompt: str
    globalPrompt: str


class JobRequest(_Core, total=False):
    """The request stored with a job. ``total=False``: the keys below depend on the kind of job (see the module docstring)."""
    tasks: list[Task]
    targetLayer: str | None
    targetParts: list[str]
    maskPixels: int
    material: str | None
    scope: str | None
    operation: str | None
    referenceImage: dict[str, Any]
    photoImage: str
    designOp: dict[str, Any] | None
    newRenderKey: str
    originalGeometry: list[dict[str, Any]]
    description: list[dict[str, Any]]
    different: dict[str, Any]
    pinCamera: bool
    styleReference: StyleReference  # present when an approved image of another view is attached as a style guide


@dataclass(frozen=True)
class NewJob:
    """Everything a caller can ask for when creating a job. Validated by ``ImageJobs.submit``."""
    did: str
    view: str
    target: str | None = None
    instruction: str = ""
    mode: str = "quick"
    material: str | None = None
    backend: str = "recolor"
    reference: str | None = None
    base_rev: int | None = None
    kind: str = "edit"
    workflow: str | None = None
    seed: int | None = None
    params: dict[str, Any] | None = None
    tasks: list[dict[str, Any]] | None = None
    preview: bool = False
    geometry_items: list[dict[str, Any]] | None = None
    operation: str | None = None
    lighting: str | None = None
    style_from: str | None = None   # None: automatic for a first image (gen0), none otherwise; "auto"; a view name; "none"


def size_of(req: JobRequest) -> tuple[int, int]:
    """(width, height) in pixels of the images of the job."""
    w, h = req["size"]
    return w, h


def task_inputs(tasks: list[Task]) -> list[TaskInput]:
    """The caller-supplied part of each stored task (used to recreate a job)."""
    return [{"targetLayer": t["targetLayer"], "material": t.get("material"), "instruction": t.get("instruction", "")} for t in tasks]
