"""Changing an appliance to a model of another KIND (pure, rule R1): the cabinets around it change with it. User's choice (11/11/2026,
recommended option): the cabinets change by themselves, always through the preview.

* hood ``insert`` -> ``chimney`` / ``island``: the hood leaves its wall cabinet and hangs over the hob (the hob's cabinet becomes its host);
  the hood cabinet and the top-row cabinets over it are removed.
* hood ``chimney`` / ``island`` -> ``insert``: a hood cabinet is built over the hob (at the hood height of ``intent``) and the hood goes in.
* fridge ``freestanding`` -> ``integrated``: the tall cabinet loses its open niche (full-height doors hide the fridge); back: a niche again.

``appliance_models.kind_of`` names the kinds; ``appliance_models.changes_cabinets`` says what happens (the popup) or why it cannot.
"""
from __future__ import annotations

from typing import Any

from . import appliance_models, builtin
from .catalog import Catalog
from .edit import new_id
from .errors import InvalidInput
from .labels import NAMES
from .spec import Appliance, KitchenSpec, Module

HOOD_GAP_MM = 650.0          # worktop to the bottom of a hood (KITCHEN-DEFAULT hood gap; intent uses the same default)
INSERT_HEIGHT_MM = 165.0     # the hood insert under its cabinet (intent: "y_hood = countertop + gap + 165")


def changes_kind(app: Appliance, model: dict[str, Any], catalog: Catalog = builtin.CATALOG) -> bool:
    now = appliance_models.models(catalog).get(appliance_models.model_id(app, catalog) or "")
    return app.type in ("hood", "fridge") and appliance_models.kind_of(model) != appliance_models.kind_of(now)


def plan(spec: KitchenSpec, app: Appliance, model: dict[str, Any], catalog: Catalog = builtin.CATALOG) -> tuple[list[dict[str, Any]], list[str]]:
    """``(operations, summary)`` that change ``app`` to ``model`` of another kind with its cabinets. InvalidInput when it cannot."""
    h = appliance_models.host(spec, app)
    reasons = appliance_models.changes_cabinets(spec, app, model, h, catalog)
    if reasons is None or h is None:
        raise InvalidInput(f"{app.id}: the cabinet it stands in was not found", code="appliance-no-host")
    bad = [r for r in reasons if r.startswith("Cannot")]
    if bad:
        raise InvalidInput(bad[0].removeprefix("Cannot: "), code="model-kind-blocked")
    to = appliance_models.kind_of(model)
    if app.type == "hood":
        if to == "insert":
            return _build_hood_cabinet(spec, app, model, h), reasons
        return _hang_hood(spec, app, model, h), reasons
    if to == "integrated":
        return [{"op": "update", "id": h.id, "changes": {"niche": None}, "closeGap": False},
                {"op": "update-appliance", "id": app.id, "model": model["id"]}], reasons
    niche = float((model.get("niche") or {"h": model["size"]["h"] + 20})["h"])
    return [{"op": "update", "id": h.id, "changes": {"niche": niche}, "closeGap": False},
            {"op": "update-appliance", "id": app.id, "model": model["id"]}], reasons


def _hang_hood(spec: KitchenSpec, app: Appliance, model: dict[str, Any], h: Module) -> list[dict[str, Any]]:
    hob = h if h.storey == "base" else next(x for x in spec.module if x.storey == "base" and appliance_models.over(h, x))
    ops: list[dict[str, Any]] = [{"op": "update-appliance", "id": app.id, "model": model["id"], "changes": {"module": hob.id}}]
    if h.storey != "base":                    # out of its wall cabinet: the cabinet goes, and the top-row cabinets standing on it
        ops += [{"op": "remove", "id": x.id, "closeGap": False} for x in spec.module if x.type == "upper-loft" and appliance_models.over(x, h)]
        ops.append({"op": "remove", "id": h.id, "closeGap": False})
    return ops


def _build_hood_cabinet(spec: KitchenSpec, app: Appliance, model: dict[str, Any], hob: Module) -> list[dict[str, Any]]:
    c = spec.common
    y = max(c.upperBottom + 150.0, c.countertop + HOOD_GAP_MM + INSERT_HEIGHT_MM)
    cid = new_id(spec, "TT")
    w = hob.width
    cabinet: dict[str, Any] = {"id": cid, "type": "upper-hood", "name": NAMES["upper-hood"], "wall": hob.wall, "fromCorner": hob.fromCorner,
                               "width": w, "y": y, "height": max(300.0, c.upperTierSplit - y), "depth": c.upperDepth,
                               "doors": [w / 2, w / 2] if w >= 600 else [w]}
    for key in ("run", "offset", "facing"):
        if getattr(hob, key):
            cabinet[key] = getattr(hob, key)
    return [{"op": "add", "closeGap": False, "module": cabinet},
            {"op": "update-appliance", "id": app.id, "model": model["id"], "changes": {"module": cid}}]
