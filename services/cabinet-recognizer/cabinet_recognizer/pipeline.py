"""Điều phối toàn bộ quy trình (vỏ): ảnh -> 3 lần hỏi AI + đo pixel + tính -> JSON.

  1. AI  layout        : dãy tủ trên/dưới nằm đâu, đầu dãy là gì, vật liệu
  2. px  measure       : gradient -> đường ứng viên dọc/ngang, vẽ ảnh đánh số
  3. AI  segmentation  : đường nào là ranh giới module / khe cánh, ô nào là loại gì,
                         đường ngang nào là đỉnh tủ, đáy tủ, mặt đá, chân tủ, sàn
  4. px  refine        : đường đáy cánh tủ hút mùi, đường chia ngăn kéo trong từng ô
  5. AI  policy        : chuẩn kích thước theo vùng (chiều cao mặt bếp, bước làm tròn...)
  6. core build_spec   : px -> mm, hệ số tủ trên, căn đường chia, làm tròn, snap chuẩn
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from . import compute, contract, pixels, prompts
from .contract_openings import OpeningAnswer, parse_openings
from .errors import RecognizerError
from .vision import VisionClient

T = TypeVar("T")


def _ask(client: VisionClient, step: str, prompt: str, images: list[bytes],
         parse: Callable[[Any], T], retries: int, log: dict[str, Any]) -> T:
    text = client.complete(step, prompt, images)
    for attempt in range(retries + 1):
        log[step] = text
        try:
            return parse(contract.extract_json(text))
        except RecognizerError as e:
            if e.kind != "validation" or attempt == retries or "awaiting-answer" in e.code:
                raise RecognizerError(e.kind, f"{step}-{e.code}", e.message) from e
            text = client.complete(step, prompt + prompts.retry_suffix(e.message), images)
    raise AssertionError("unreachable")


def recognize(image: bytes, client: VisionClient, *, region: str = "VN",
              retries: int = 1, debug: dict[str, Any] | None = None,
              openings: list[OpeningAnswer] | None = None) -> dict[str, Any]:
    """Trả {"spec": ..., "answers": {...}}. `debug` (nếu có) nhận ảnh đánh số và số đo. `openings`: câu trả lời bước cửa (None = không hỏi)."""
    raw: dict[str, Any] = {}
    layout = _ask(client, "layout", prompts.layout_prompt(), [image], contract.parse_layout, retries, raw)
    meas = pixels.measure(image, dict(layout))
    if len(meas["vlines"]["upper"]) < 2 or len(meas["vlines"]["base"]) < 2:
        raise RecognizerError("validation", "no-edges", "không tìm thấy đủ mép tủ trong vùng AI chỉ ra")
    annotated = pixels.annotate(image, meas)
    seg = _ask(client, "segmentation", prompts.segmentation_prompt(meas), [image, annotated],
               lambda d: contract.parse_segmentation(d, meas), retries, raw)
    refine = pixels.refine_cells(image, meas, dict(seg))
    summary = compute.policy_summary(meas, layout, seg)
    policy = _ask(client, "policy", prompts.policy_prompt(region, summary), [],
                  contract.parse_policy, retries, raw)
    spec = compute.build_spec(meas, layout, seg, policy, refine, openings)
    if debug is not None:
        debug.update({"measure": meas, "annotated_png": annotated, "refine": refine,
                      "policy_summary": summary})
    return {"spec": spec, "answers": raw}


# ---------------- v0.2: tự chọn nhánh ----------------

NOTE_STEPS = ("scene", "openings", "policy")      # gợi ý chỉ đi vào các bước hiểu bố cục và chọn chính sách, không vào các bước đo/chia ô


class _NoteClient:
    """Bọc một VisionClient: thêm gợi ý của người dùng vào câu hỏi của NOTE_STEPS. Tên bước giữ nguyên nên Replay/Inbox chạy như cũ."""

    def __init__(self, inner: VisionClient, note: str) -> None:
        self.inner = inner
        self.note = note

    def complete(self, step: str, prompt: str, images: list[bytes]) -> str:
        return self.inner.complete(step, prompts.with_note(prompt, self.note) if step in NOTE_STEPS else prompt, images)


def _openings(client: VisionClient, image: bytes, walls: list[str], retries: int, log: dict[str, Any],
              warnings: list[dict[str, Any]], prompt: str | None = None) -> list[OpeningAnswer] | None:
    """Bước ``openings``: cửa đi / cửa sổ trên các tường có dãy tủ. Một bản ghi phát lại cũ (không có bước này) -> None: kết quả không có
    ``openings``, như trước khi có bước này. Câu trả lời vẫn sai hợp đồng sau khi hỏi lại không làm hỏng phần tủ: không có cửa, kèm cảnh báo."""
    try:
        return _ask(client, "openings", prompt or prompts.openings_prompt(walls), [image],
                    lambda d: parse_openings(d, tuple(walls)), retries, log)
    except RecognizerError as e:
        if e.code.endswith("replay-missing-step"):
            log.pop("openings", None)
            return None
        if e.kind == "validation" and "awaiting-answer" not in e.code:
            warnings.append({"code": "openings-rejected", "message": e.message})
            return []
        raise


def recognize_auto(image: bytes, client: VisionClient, *, region: str = "VN",
                   retries: int = 1, debug: dict[str, Any] | None = None, note: str = "") -> dict[str, Any]:
    """Hỏi AI bố cục trước: dãy thẳng chụp chính diện -> nhánh v0.1; còn lại -> nhánh phối cảnh. `note`: gợi ý tùy chọn của người dùng."""
    from . import compute_persp, contract_persp, pixels_persp

    if prompts.clean_note(note):
        client = _NoteClient(client, note)

    raw: dict[str, Any] = {}
    scene = _ask(client, "scene", prompts.scene_prompt(), [image], contract_persp.parse_scene, retries, raw)
    late: list[dict[str, Any]] = []
    if scene["layout"] == "none":           # chỉ có tường + cửa: không có tủ làm vật chuẩn, nên chỉ ra loại cửa và tỉ lệ
        from . import compute_openings
        seen = _openings(client, image, ["back"], retries, raw, late, prompts.opening_photo_prompt()) or []
        size = pixels_persp.image_size(image)
        found = compute_openings.photo(seen, size, late)
        if not found:
            raise RecognizerError("validation", "no-cabinets-no-openings", "ảnh không có tủ bếp và không thấy cửa nào")
        return {"spec": {"schema": "cabinet-recognizer/0.2", "unit": "mm", "layout": "none", "modules": [], "appliances": [],
                         "photoOpenings": found, "materials": scene["materials"], "warnings": late}, "answers": raw}
    frontal = scene["layout"] == "straight" and scene["view"] == "frontal"
    openings = _openings(client, image, ["back"] if frontal else [r["wall"] for r in scene["runs"] if r["wall"] != "island" and not r.get("peninsula")], retries, raw, late)
    if frontal:
        res = recognize(image, client, region=region, retries=retries, debug=debug, openings=openings)
        res["answers"] = {"scene": raw["scene"], **({"openings": raw["openings"]} if "openings" in raw else {}), **res["answers"]}
        res["spec"].setdefault("warnings", []).extend(late)
        return res
    meas = pixels_persp.measure_runs(image, dict(scene))
    runs = []
    annotated: dict[str, bytes] = {}
    for run in scene["runs"]:
        wall = run["wall"]
        cand = meas["runs"][wall]["cand"]
        if "base" not in cand:
            raise RecognizerError("validation", "no-base-band", f"{wall}: không dựng được dải tủ dưới")
        annotated[wall] = pixels_persp.annotate_run(image, meas, wall, dict(run["box"]))
        ids = {k: [ln["id"] for ln in v] for k, v in cand.items()}
        runs.append(_ask(client, f"run-{wall}", prompts.run_prompt(wall, ids), [image, annotated[wall]],
                         lambda d, w=wall, c=cand: contract_persp.parse_run(d, w, c), retries, raw))
    href_in = [{**r, "wall": rs["wall"]} for rs in runs for r in rs["heightRefs"]]
    hrefs = pixels_persp.snap_height_refs(image, list(scene["runs"]), href_in)
    summary = compute_persp.preview_summary(scene, meas, runs)
    policy = _ask(client, "policy", prompts.policy_p_prompt(region, summary), [], contract_persp.parse_policy_p,
                  retries, raw)
    spec = compute_persp.build_spec_p(scene, meas, runs, policy, hrefs, openings, debug)
    spec["warnings"].extend(late)
    if debug is not None:
        debug.update({"measure": meas, "annotated_runs": annotated, "policy_summary": summary, "heightRefs": hrefs})
    return {"spec": spec, "answers": raw}
