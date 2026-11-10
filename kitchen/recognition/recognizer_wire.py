"""The wire format of the stand-alone cabinet-recognizer service, as pure functions (rule R1): what to send and how to read the answer.

The HTTP call itself lives in ``kitchen/recognizers.py`` (shell). The service answers ``{"kitchen": {"spec": KitchenSpec, "issues": [...]}}``
or ``{"error": {kind, code, message}}``, and since recognized-runs/1 also ``"runs"`` (the kitchen by runs; ``layout_from_runs``), which is what
an anchored recognition places. Of ``kitchen`` only the MODULES are used: ``draft_from_kitchen_spec`` turns them into the raw draft that
``build_draft`` checks, and ``draft_operation`` then keeps the room, floor plan and ``common`` of the current design (the recognizer's own
room is never applied). A Rust build ports these functions and runs the golden cases in tests/golden/recognition.
"""
from __future__ import annotations

import base64
import re
from typing import Any

MAX_NOTE = 500
# a module the recognizer had to approximate or could not place gets a confidence below ``draft.MIN_CONFIDENCE`` so the preview flags it
REVIEW_CODES = ("type-approximated", "unknown-type", "outside-wall", "tall-sections-simplified", "blind-moved-to-left-run", "blind-moved-to-next-run", "corner-gap",
                "corner-shelf-split")
REVIEW_CONFIDENCE = 0.4
MATERIAL_SLOTS = ("base", "upper", "tall", "countertop")        # the slots of ``common.material`` that the draft also knows
JOB_ID = re.compile(r"[0-9]{8}-[0-9]{6}(-[0-9]+)?")             # the service names a job by its creation time: 20261109-142100, -2 when taken
MODULE_FIELDS = ("type", "wall", "width", "fromCorner", "y", "height", "depth", "niche")


def clean_note(text: Any) -> str:
    """The user's hint for the recognizer: whitespace collapsed, control characters dropped, at most MAX_NOTE characters. ``""`` for non-text."""
    if not isinstance(text, str):
        return ""
    kept = "".join(ch if ch.isprintable() or ch in "\n\t" else " " for ch in text)
    return " ".join(kept.split())[:MAX_NOTE]


def request_body(kind: str, data: bytes, note: str = "") -> dict[str, Any]:
    """The JSON body for the service's ``POST /recognize``. ``note`` is sent only when it has text."""
    body: dict[str, Any] = {"kind": kind, "imageBase64": base64.b64encode(data).decode("ascii")}
    cleaned = clean_note(note)
    if cleaned:
        body["note"] = cleaned
    return body


def response_error(payload: Any) -> str:
    """``"code: message"`` when the service answered with an error object, else ``""``."""
    err = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(err, dict):
        return ""
    return f"{err.get('code') or err.get('kind') or 'error'}: {err.get('message') or ''}".strip()[:300]


def clean_job_id(value: Any) -> str:
    """A job id as the service makes them, else ``""``. It becomes part of a URL path, so nothing else is let through."""
    return value if isinstance(value, str) and JOB_ID.fullmatch(value) else ""


def job_progress(payload: Any) -> dict[str, str]:
    """Where a service job stands: ``{"state": "waiting"|"done"|"error", "step": ..., "message": ...}``. An answer that is neither, or that is
    not an object, is an ``error``. ``step``: the question being waited on; ``message``: the service's error."""
    body = payload if isinstance(payload, dict) else {}
    state = body.get("state")
    if state in ("waiting", "done"):
        step = body.get("step")
        return {"state": state, "step": step if isinstance(step, str) else "", "message": ""}
    return {"state": "error", "step": "", "message": response_error(payload) or "the service gave no job state"}


def _issue_text(issue: dict[str, Any]) -> str:
    module = issue.get("module")
    return f"{module + ': ' if isinstance(module, str) and module else ''}{issue.get('message') or issue.get('code') or ''}"[:200]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def draft_from_runs(payload: Any) -> dict[str, Any] | None:
    """The raw draft (what ``Recognizer.recognize`` returns: a flat list the user reviews) from the service's kitchen by runs; None when the
    answer has none. Each cabinet names its run as its wall and gets the ``fromCorner`` the walls use (back and left runs: from their
    right-hand / corner end, so mirrored; right run: as given). Cabinets the service had to approximate are marked for review."""
    doc = layout_from_runs(payload)
    if doc is None:
        return None
    issues = [i for i in _list(doc.get("issues")) if isinstance(i, dict)]
    flagged = {i.get("module") for i in issues if i.get("code") in REVIEW_CODES and isinstance(i.get("module"), str)}
    modules: list[Any] = []
    for run in _list(doc.get("runs")):
        if not isinstance(run, dict):
            continue
        rid, length = run.get("id"), run.get("length")
        for m in _list(run.get("modules")):
            if not isinstance(m, dict):
                modules.append(m)                  # build_draft lists it under ``rejected``
                continue
            item: dict[str, Any] = {k: m[k] for k in MODULE_FIELDS if k not in ("wall", "fromCorner") and m.get(k) is not None}
            item["wall"] = rid
            at, width, total = _number(m.get("s")), _number(m.get("width")), _number(length)
            if at is not None and width is not None and total is not None:
                item["fromCorner"] = at if rid == "right" else total - at - width
            if m.get("name"):
                item["label"] = m["name"]
            if m.get("id") in flagged:
                item["confidence"] = REVIEW_CONFIDENCE
            elif m.get("confidence") is not None:
                item["confidence"] = m["confidence"]
            modules.append(item)
    common = _dict(doc.get("common"))
    draft: dict[str, Any] = {"modules": modules, "notes": [t for t in (_issue_text(i) for i in issues) if t]}
    draft["materials"] = {k: v for k, v in _dict(common.get("material")).items() if k in MATERIAL_SLOTS and isinstance(v, str)}
    return draft


def layout_from_runs(payload: Any) -> dict[str, Any] | None:
    """The service's kitchen BY RUNS (``recognized-runs/1``: runs, joints, each cabinet's ``s`` from the left end of its run) from an answer, or
    None when the answer has none (an older service). ``recognition.build_layout`` checks it."""
    runs = _dict(payload).get("runs")
    return runs if isinstance(runs, dict) and isinstance(runs.get("runs"), list) else None
