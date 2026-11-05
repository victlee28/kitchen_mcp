"""Multi-view consistency: is the approved image of each view still true to the design?

``renderKey`` covers geometry + camera + size (it ignores materials on purpose, so masks and base images survive a recolour).
That leaves a gap: change a material and the approved image of another view is silently out of date. This module adds the
missing half, an *appearance* snapshot of what a view shows (visible layer -> material name). It is stored when an image is
accepted and compared with the design as it is now.

Statuses per view:
  none              no approved image for the view
  current           geometry and appearance both match
  stale-appearance  same geometry, but a material it shows has changed (``changed`` lists layer / was / now)
  stale-geometry    the approved images belong to older geometry or camera
  unknown           approved image from before snapshots existed: cannot tell
"""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from . import geometry

if TYPE_CHECKING:  # pragma: no cover
    from .imagejobs import ImageJobs


def snapshot(images: "ImageJobs", did: str, view: str, rev: int | None = None, size: list | tuple | None = None) -> dict[str, Any]:
    """What the view shows at ``rev``: {"key", "layers": {layerId: material}, "extras": {...}}. ``size``: render size to look at."""
    if size:
        images.ensure_render(did, rev, view, *size)  # fills the cache at that size so layers() below reuses it
    res = images.layers(did, view, rev)
    spec, _ = images.store.get(did, res["rev"])
    rows = {x["id"]: x.get("material") for x in res["layers"] if x.get("pixels")}
    types = {x["type"] for x in res["layers"] if x.get("pixels") and x.get("type")}
    extra = spec.common.model_extra or {}
    extras: dict[str, Any] = {}
    if "wall-tile" in types:  # how the tile is laid is not part of its name
        extras["wallTile"] = [spec.common.wallTilePattern, extra.get("wallTile")]
    if "floor" in types:
        extras["floorTile"] = extra.get("floorTile")
    blob = json.dumps({"layers": rows, "extras": extras}, sort_keys=True, ensure_ascii=False, default=str)
    return {"key": hashlib.sha256(blob.encode()).hexdigest()[:16], "layers": rows, "extras": extras}


def _changed(was: dict[str, Any], now: dict[str, Any]) -> list[dict]:
    out = []
    for lid in sorted(set(was["layers"]) | set(now["layers"])):
        a, b = was["layers"].get(lid), now["layers"].get(lid)
        if a != b:
            out.append({"layer": lid, "was": a, "now": b})
    for k in sorted(set(was.get("extras", {})) | set(now.get("extras", {}))):
        if was.get("extras", {}).get(k) != now.get("extras", {}).get(k):
            out.append({"layer": f"~{k}", "was": was.get("extras", {}).get(k), "now": now.get("extras", {}).get(k)})
    return out


def view_status(images: "ImageJobs", did: str, rev: int | None = None) -> dict[str, dict]:
    """Status of every view of the design at ``rev`` (latest by default). Views with no approved image are not rendered."""
    spec, r = images.store.get(did, rev)
    out: dict[str, dict] = {}
    for view in geometry.views_of(spec):
        accepted = images.store.list_jobs(did, view, "accepted", 200)
        if not accepted:
            out[view] = {"status": "none"}
            continue
        newest = max(accepted, key=lambda j: (j["result"].get("acceptNow", ""), j["updated_at"]))
        size = (newest.get("request") or {}).get("size") or [None, None]  # compare at the size the approved image was made at
        _, _, _, d, man = images.ensure_render(did, r, view, *size)
        key = man["renderKey"]
        ref, info = images._reference(did, view, key, d)
        if info.get("type") != "job":
            out[view] = {"status": "stale-geometry", "renderKey": key, "approvedJob": newest["id"], "approvedRev": newest["rev"]}
            continue
        job = images.store.get_job(info["jobId"])
        was = (job["result"] or {}).get("appearance")
        entry = {"renderKey": key, "approvedJob": job["id"], "approvedRev": job["rev"]}
        if not was:
            out[view] = {**entry, "status": "unknown"}
            continue
        now = snapshot(images, did, view, r, size)
        if now["key"] == was["key"]:
            out[view] = {**entry, "status": "current", "appearanceKey": now["key"]}
        else:
            out[view] = {**entry, "status": "stale-appearance", "appearanceKey": now["key"], "approvedAppearanceKey": was["key"],
                         "changed": _changed(was, now)}
    return out


def regenerate_stale(images: "ImageJobs", did: str, views: list[str] | None = None, backend: str = "recolor", base_rev: int | None = None) -> dict:
    """Prepare (not send) one review job per view whose approved image shows a changed material.

    Each job re-applies the new materials onto the approved image. Nothing is sent to a backend until the user sends it.
    """
    from .imagejobs import MAX_TASKS
    status = view_status(images, did)
    chosen = views or [v for v, s in status.items() if s["status"] == "stale-appearance"]
    jobs, skipped = [], []
    for v in chosen:
        s = status.get(v)
        if not s or s["status"] != "stale-appearance":
            skipped.append({"view": v, "reason": (s or {}).get("status", "no such view")})
            continue
        todo = [c for c in s["changed"] if not c["layer"].startswith("~") and c["now"]]
        if not todo:
            skipped.append({"view": v, "reason": "only tile layout changed: no per-layer material to apply"})
            continue
        tasks = [{"targetLayer": c["layer"], "material": c["now"], "instruction": ""} for c in todo[:MAX_TASKS]]
        job = images.create(did, v, tasks=tasks, mode="quick", backend=backend, base_rev=base_rev, preview=True)
        jobs.append({"view": v, "jobId": job["id"], "status": job["status"], "layers": [t["targetLayer"] for t in tasks],
                     **({"notApplied": [c["layer"] for c in todo[MAX_TASKS:]]} if len(todo) > MAX_TASKS else {})})
    return {"jobs": jobs, "skipped": skipped}
