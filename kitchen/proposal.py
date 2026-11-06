"""Preview of a design operation: what it would change and what validation would say, without saving anything.

``spec_diff`` compares two specifications (modules by id, other lists that carry ids by id, everything else by path);
``validation_delta`` compares their validation issues. KitchenService.propose combines them with edit.apply_op.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .spec import KitchenSpec

MAX_ENTRIES = 200
SKIP = {"floorplan"}   # imported plan: not part of an operation preview (and large)


def _keyed(items: list) -> dict | None:
    if items and all(isinstance(x, dict) and isinstance(x.get("id"), str) for x in items):
        ids = [x["id"] for x in items]
        if len(set(ids)) == len(ids):
            return {x["id"]: x for x in items}
    return None


def _walk(a: Any, b: Any, path: str, out: list[dict]) -> None:
    if a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            _walk(a.get(k), b.get(k), f"{path}.{k}" if path else k, out)
    elif isinstance(a, list) and isinstance(b, list) and (ka := _keyed(a)) is not None and (kb := _keyed(b)) is not None:
        for k in list(ka) + [x for x in kb if x not in ka]:
            _walk(ka.get(k), kb.get(k), f"{path}[{k}]", out)
    else:
        out.append({"path": path, "old": a, "new": b})


def spec_diff(old: KitchenSpec, new: KitchenSpec) -> dict:
    """{"modules": {"added", "removed", "changed": {id: [{field, old, new}]}}, "other": [{path, old, new}], "truncated": bool}"""
    a, b = old.model_dump(mode="json"), new.model_dump(mode="json")
    mods_a, mods_b = {m["id"]: m for m in a.get("module", [])}, {m["id"]: m for m in b.get("module", [])}
    changed: dict[str, list] = {}
    for mid in mods_a.keys() & mods_b.keys():
        entries: list[dict] = []
        _walk(mods_a[mid], mods_b[mid], "", entries)
        if entries:
            changed[mid] = [{"field": e["path"], "old": e["old"], "new": e["new"]} for e in entries]
    other: list[dict] = []
    for k in sorted((set(a) | set(b)) - SKIP - {"module"}):
        _walk(a.get(k), b.get(k), k, other)
    truncated = len(other) > MAX_ENTRIES
    return {"modules": {"added": [m for m in mods_b if m not in mods_a], "removed": [m for m in mods_a if m not in mods_b], "changed": changed},
            "other": other[:MAX_ENTRIES], "truncated": truncated}


def affected_modules(diff: dict) -> list[str]:
    """Modules the operation adds, removes or changes (neighbours that slide when a gap closes included)."""
    m = diff["modules"]
    return sorted({*m["added"], *m["removed"], *m["changed"]})


def _key(issue: dict) -> tuple:
    return issue.get("rule"), tuple(issue.get("module") or ()), issue.get("content")


def validation_delta(before: dict, after: dict) -> dict:
    """Issues the operation introduces or resolves; ``introducesErrors`` is true when a new issue has severity 'error'."""
    b, a = {_key(i): i for i in before["issues"]}, {_key(i): i for i in after["issues"]}
    introduced = [a[k] for k in a if k not in b]
    return {"valid": {"before": before["valid"], "after": after["valid"]}, "introduced": introduced,
            "resolved": [b[k] for k in b if k not in a], "remaining": [a[k] for k in a if k in b],
            "introducesErrors": any(i.get("severity") == "error" for i in introduced)}


def op_hash(operation: dict, base_revision: int | None) -> str:
    """Identifies exactly this operation on exactly this base revision; ``apply(..., expect=hash)`` refuses anything else."""
    # Defaults spelled out or left out are the same operation: the MCP editing tools always send closeGap and afterModule.
    canon = {k: v for k, v in operation.items() if v is not None and not (k == "closeGap" and v is True)}
    text = json.dumps({"op": canon, "baseRev": base_revision}, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
