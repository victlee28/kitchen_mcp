"""Free-form text -> design parameters through a language model (DeepSeek). I/O shell: it reads no environment and is given a Config.

The pure text parser stays in ``intent``; this module only asks the network for a better first guess and never raises
(an error returns ``None`` plus a status so the caller falls back to the regex parser).
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request

from .config import Config
from .intent import KitchenTemplate
from .spec import KitchenSpec

logger = logging.getLogger("kitchen.llm")


def parse_prompt_llm(prompt: str, config: Config) -> tuple[KitchenTemplate | None, dict[str, str]]:
    """DeepSeek proposes the parameters (JSON mode). Error -> ``(None, status)``, never raised."""
    key = config.deepseek_api_key
    if not key:
        return None, {"status": "skipped", "reason": "DEEPSEEK_API_KEY chưa được cấu hình"}
    schema = json.dumps(KitchenTemplate.model_json_schema(), ensure_ascii=False)
    payload = {"model": config.deepseek_model, "temperature": 0,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": "Trích tham số thiết kế tủ bếp từ mô tả. Chỉ trả JSON đúng schema sau, đơn vị mm, trường không rõ thì bỏ qua:\n" + schema},
                            {"role": "user", "content": prompt}]}
    req = urllib.request.Request(config.deepseek_base_url + "/chat/completions",
                                 data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            content = json.loads(r.read())["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        return KitchenTemplate.model_validate_json(m.group(0) if m else content), {"status": "ok"}
    except Exception as e:  # network, broken JSON, wrong schema -> fall back to the regex parser
        logger.warning("[DEEPSEEK] lỗi, dùng regex: %s", e)
        return None, {"status": "error", "reason": f"{type(e).__name__}: {e}"[:300]}


def edit_operation_llm(text: str, spec: KitchenSpec, config: Config) -> tuple[dict[str, object] | None, dict[str, str]]:
    """DeepSeek turns an edit sentence the rules could not read into ONE operation (``edit.apply_op`` shape). Error -> ``(None, status)``.

    The caller must pass the operation through ``edit_intent.check_operation`` and ``service.propose``; nothing here touches the store.
    """
    key = config.deepseek_api_key
    if not key:
        return None, {"status": "skipped", "reason": "DEEPSEEK_API_KEY chưa được cấu hình"}
    modules = [{"id": m.id, "type": m.type, "wall": m.wall, "width": m.width, "storey": m.storey} for m in spec.module]
    system = ("Chuyển câu lệnh sửa tủ bếp thành MỘT thao tác JSON. Chỉ dùng: "
              '{"op":"add","module":{"type","width"},"afterModule":id} | {"op":"remove","id"} | {"op":"update","id","changes":{...}} | '
              '{"op":"common","changes":{...}} | {"op":"multi","ops":[...]}. Đơn vị mm. Không rõ thì trả {"op":"none"}.\nModule: '
              + json.dumps(modules, ensure_ascii=False))
    payload = {"model": config.deepseek_model, "temperature": 0, "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}
    req = urllib.request.Request(config.deepseek_base_url + "/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            content = json.loads(r.read())["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        op = json.loads(m.group(0) if m else content)
        return (op if isinstance(op, dict) and op.get("op") != "none" else None), {"status": "ok"}
    except Exception as e:  # network or broken JSON -> no guess
        logger.warning("[DEEPSEEK] edit lỗi: %s", e)
        return None, {"status": "error", "reason": f"{type(e).__name__}: {e}"[:300]}
