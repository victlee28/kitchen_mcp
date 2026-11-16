"""Free-form text -> design parameters / one edit operation through a language model. I/O shell: the model is reached through the
``ModelGateway`` it is given (whichever provider ``.env`` chooses: Claude, OpenAI, DeepSeek...).

The pure text parser stays in ``intent`` / ``edit_intent``; this module only asks for a better first guess and never raises (an error
returns ``None`` plus a status so the caller falls back to the rules).
"""
from __future__ import annotations

import json
import logging

from . import model_contract as mc
from .intent import KitchenTemplate
from .model_gateway import ModelGateway
from .spec import KitchenSpec

logger = logging.getLogger("kitchen.llm")


def _skipped(models: ModelGateway) -> dict[str, str] | None:
    return None if models.available() else {"status": "skipped", "reason": "no language model is set (KITCHEN_LLM_PROVIDER + its API key)"}


def _status(reply: mc.ModelReply) -> dict[str, str]:
    return {"status": "ok", "provider": reply.provider, "model": reply.model}


def parse_prompt_llm(prompt: str, models: ModelGateway) -> tuple[KitchenTemplate | None, dict[str, str]]:
    """The model proposes the parameters of a kitchen described in words (JSON). Error -> ``(None, status)``, never raised."""
    skipped = _skipped(models)
    if skipped:
        return None, skipped
    schema = json.dumps(KitchenTemplate.model_json_schema(), ensure_ascii=False)
    req = mc.ModelRequest(system="Trích tham số thiết kế tủ bếp từ mô tả. Chỉ trả JSON đúng schema sau, đơn vị mm, trường không rõ thì bỏ qua:\n" + schema,
                          messages=({"role": "user", "text": prompt},), json_only=True, task="prompt")
    try:
        reply = models.ask(req)
        return KitchenTemplate.model_validate(mc.first_json(reply.text)), _status(reply)
    except Exception as e:  # network, broken JSON, wrong schema -> fall back to the regex parser
        logger.warning("[LLM] prompt failed, using the rules: %s", e)
        return None, {"status": "error", "reason": f"{type(e).__name__}: {e}"[:300]}


def edit_operation_llm(text: str, spec: KitchenSpec, models: ModelGateway) -> tuple[dict[str, object] | None, dict[str, str]]:
    """The model turns an edit sentence the rules could not read into ONE operation (``edit.apply_op`` shape). Error -> ``(None, status)``.

    The caller must pass the operation through ``edit_intent.check_operation`` and ``service.propose``; nothing here touches the store.
    """
    skipped = _skipped(models)
    if skipped:
        return None, skipped
    modules = [{"id": m.id, "type": m.type, "run": m.run, "fromCorner": m.fromCorner, "width": m.width, "storey": m.storey} for m in spec.module]
    system = ("Chuyển câu lệnh sửa tủ bếp thành MỘT thao tác JSON. Chỉ dùng: "
              '{"op":"add","module":{"type","width"},"afterModule":id} | {"op":"remove","id"} | {"op":"update","id","changes":{...}} | '
              '{"op":"common","changes":{...}} | {"op":"multi","ops":[...]}. Đơn vị mm. Không rõ thì trả {"op":"none"}.\nModule: '
              + json.dumps(modules, ensure_ascii=False))
    req = mc.ModelRequest(system=system, messages=({"role": "user", "text": text},), json_only=True, task="edit")
    try:
        reply = models.ask(req)
        op = mc.first_json(reply.text)
        return (op if op.get("op") != "none" else None), _status(reply)
    except Exception as e:  # network or broken JSON -> no guess
        logger.warning("[LLM] edit failed: %s", e)
        return None, {"status": "error", "reason": f"{type(e).__name__}: {e}"[:300]}
