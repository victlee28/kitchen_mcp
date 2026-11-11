"""Free-form edit sentence -> one design operation (``edit.apply_op`` shape) or a clarifying question.

Pure rule parser over the Vietnamese lexicon (no network, no store). It NEVER applies anything: the result is an
operation that the caller sends through ``service.propose`` like every other user edit, so the user sees the diff first.

Result (JSON-able dict)::

    {"status": "ok",        "operation": {...}, "summary": ["..."], "targets": ["TD1"]}
    {"status": "clarify",   "question": "...",  "choices": ["TD1", ...]}
    {"status": "unsupported", "message": "..."}

``check_operation`` is the gate for operations that come from somewhere else (an optional language model): only the
kinds listed in ``ALLOWED_OPS`` pass, so a model cannot ``replace`` the whole design.
"""
from __future__ import annotations

import re
from typing import Any

from .edit import combine_ops
from .jsonview import as_dict, as_list
from .lexicon import fold
from .numeric import round_half_away
from .spec import KitchenSpec, Module, to_data
from .vocab import COLORS, WOOD

ALLOWED_OPS = ("add", "remove", "update", "common", "lower-top", "multi")
MAX_CHOICES = 12

_TYPES: tuple[tuple[str, str], ...] = (      # folded keyword -> module type (longest first)
    ("ngan keo", "base-drawers"), ("chau rua", "base-sink"), ("bep tu", "base-cooktop"), ("bep ga", "base-cooktop"), ("bep", "base-cooktop"),
    ("lo nuong", "base-oven"), ("tu lanh", "tall-fridge"), ("tu cao", "tall"), ("tu treo", "upper"), ("tu tren", "upper"),
    ("tu kinh", "upper-glass"), ("tu duoi", "base"), ("tu thuong", "base"),
)
_DOOR_STYLES: tuple[tuple[str, str], ...] = (("kinh", "glass"), ("glass", "glass"), ("khung", "frame"), ("shaker", "frame"),
                                             ("phang", "flat"), ("tron", "flat"), ("slab", "flat"), ("flat", "flat"))
_HANDLES: tuple[tuple[str, str], ...] = (("khong tay", "none"), ("khong co tay", "none"), ("nhan mo", "none"), ("am", "concealed"),
                                         ("concealed", "concealed"), ("nut", "knob"), ("num", "knob"), ("knob", "knob"), ("thanh", "bar"), ("bar", "bar"))
_STOREYS: tuple[tuple[str, tuple[str, ...]], ...] = (("tu treo", ("upper", "loft")), ("tu tren", ("upper", "loft")), ("upper", ("upper", "loft")),
                                                     ("tu duoi", ("base",)), ("tu cao", ("tall",)), ("base", ("base",)))
_MATERIAL_SLOT: tuple[tuple[str, str], ...] = (("mat ban", "countertop"), ("countertop", "countertop"), ("tuong", "wall"), ("san", "floor"))


def _has(f: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", f) is not None


def _any(f: str, *words: str) -> bool:
    return any(_has(f, w) for w in words)


def _ids_in(spec: KitchenSpec, f: str) -> list[str]:
    """Module ids named in the sentence, in the order they appear."""
    hits: list[tuple[int, str]] = []
    for m in spec.module:
        found = re.search(rf"(?<![a-z0-9]){re.escape(fold(m.id))}(?![a-z0-9])", f)
        if found:
            hits.append((found.start(), m.id))
    return [i for _, i in sorted(hits)]


def _mm(f: str, after: tuple[str, ...] = ()) -> float | None:
    """First length in the text as mm. 'cm' x10, 'm' x1000, bare numbers are mm. ``after``: take the number that follows one of these words."""
    pat = r"(\d+(?:[.,]\d+)?)\s*(mm|cm|m)?(?![a-z0-9])"
    scope = f
    for w in after:
        k = re.search(rf"(?<![a-z0-9]){re.escape(w)}", f)
        if k:
            scope = f[k.end():]
            break
    for found in re.finditer(pat, scope):
        value = float(found.group(1).replace(",", "."))
        unit = found.group(2)
        if unit == "cm":
            value *= 10
        elif unit == "m":
            value *= 1000
        elif value < 20 and "." not in found.group(1):
            continue                                  # a lone small integer is a count, not a length
        return float(round_half_away(value, 0))
    return None


def _color(f: str) -> str | None:
    table = sorted([(v, True) for v, *_ in WOOD] + [(v, False) for v, *_ in COLORS], key=lambda t: -len(t[0]))
    for name, wood in table:
        if _has(f, fold(name)):
            return ("Gỗ " + name) if wood else (name[:1].upper() + name[1:])
    return None


def _storeys_in(f: str) -> tuple[str, ...] | None:
    for word, storeys in _STOREYS:
        if _has(f, word):
            return storeys
    return None


def _pick(spec: KitchenSpec, ids: list[str], storeys: tuple[str, ...] | None) -> list[str]:
    if ids:
        return ids
    return [m.id for m in spec.module if storeys is None or m.storey in storeys]


def _clarify(question: str, choices: list[str] | None = None) -> dict[str, Any]:
    return {"status": "clarify", "question": question, "choices": (choices or [])[:MAX_CHOICES]}


def _add(spec: KitchenSpec, f: str, ids: list[str]) -> dict[str, Any] | tuple[dict[str, Any], str]:
    mtype = next((t for w, t in _TYPES if _has(f, w)), "base")
    width = _mm(f, ("rong", "ngang", "width"))
    if width is None:
        return _clarify("Tủ mới rộng bao nhiêu mm?")
    if not ids:
        return _clarify("Thêm sau tủ nào?", [m.id for m in spec.module])
    ref = spec.find(ids[0])
    new_storey = "tall" if mtype.startswith("tall") else "upper" if mtype.startswith("upper") else "base"
    if ref.storey not in (new_storey, "loft" if new_storey == "upper" else new_storey):
        return _clarify(f"{ref.id} nằm ở tầng khác với loại tủ mới; thêm sau tủ nào cùng tầng?", [m.id for m in spec.module if m.storey == new_storey])
    op: dict[str, Any] = {"op": "add", "module": {"type": mtype, "width": width}, "afterModule": ref.id}
    return op, f"Thêm tủ {mtype} rộng {width:g} mm sau {ref.id}"


def _clause(spec: KitchenSpec, f: str, ids: list[str]) -> dict[str, Any] | tuple[dict[str, Any], str]:
    """One clause -> (operation, summary) | a clarify result | an unsupported result. ``ids``: targets (mentioned or selected)."""
    storeys = _storeys_in(f)
    if _any(f, "them", "bo sung", "add", "chen"):
        return _add(spec, f, ids)
    if _any(f, "xoa", "bo", "go", "loai", "remove", "delete") and not _any(f, "tay nam"):
        if not ids:
            return _clarify("Xóa tủ nào?", [m.id for m in spec.module])
        ops = [{"op": "remove", "id": i} for i in ids]
        return combine_ops(ops), "Xóa " + ", ".join(ids)
    if _any(f, "tay nam", "handle"):
        variant = next((v for w, v in _HANDLES if _has(f, w)), None)
        color = _color(f)
        length = _mm(f, ("dai", "length"))
        change: dict[str, Any] = {}
        if variant:
            change["variant"] = variant
        if color:
            change["material"] = color
        if length is not None and variant != "none":
            change["length"] = length
        if not change:
            return _clarify("Tay nắm muốn đổi thành kiểu nào?", ["thanh", "núm", "âm", "không tay"])
        if ids or storeys:
            targets = _pick(spec, ids, storeys)
            return combine_ops([{"op": "update", "id": i, "changes": {"handle": change}} for i in targets]), f"Tay nắm {change} cho {', '.join(targets)}"
        handle = {**to_data(spec)["common"]["handle"], **change}
        return {"op": "common", "changes": {"handle": handle}}, f"Tay nắm chung: {change}"
    style = next((s for w, s in _DOOR_STYLES if _has(f, w)), None)
    if style and _any(f, "canh", "door"):
        targets = _pick(spec, ids, storeys)
        if not targets:
            return _clarify("Đổi cánh của tủ nào?", [m.id for m in spec.module])
        return combine_ops([{"op": "update", "id": i, "changes": {"doorStyle": style}} for i in targets]), f"Cánh {style} cho {', '.join(targets)}"
    if _any(f, "rong", "ngang", "width"):
        width = _mm(f)
        if width is None:
            return _clarify("Muốn rộng bao nhiêu mm?")
        if not ids:
            return _clarify("Đổi độ rộng của tủ nào?", [m.id for m in spec.module])
        return combine_ops([{"op": "update", "id": i, "changes": {"width": width}} for i in ids]), f"Rộng {width:g} mm cho {', '.join(ids)}"
    color = _color(f)
    if color:
        slot = next((s for w, s in _MATERIAL_SLOT if _has(f, w)), None)
        if slot is None and storeys:
            slot = "tall" if storeys == ("tall",) else "upper" if "upper" in storeys else "base"
        if slot is None:
            return _clarify("Đổi màu cho phần nào?", ["tủ dưới", "tủ trên", "tủ cao", "mặt bàn", "tường", "sàn"])
        value = f"Đá {color.lower()}" if slot == "countertop" else color
        material = {**to_data(spec)["common"]["material"], slot: value}
        return {"op": "common", "changes": {"material": material}}, f"Vật liệu {slot}: {value}"
    return {"status": "unsupported", "message": "Chưa hiểu câu lệnh này; thử: 'xóa TD3', 'TD2 rộng 800', 'cánh kính cho tủ trên', 'tay nắm âm'."}


def interpret_edit(spec: KitchenSpec, text: str, scope: list[str] | None = None) -> dict[str, Any]:
    """Parse one sentence (clauses split on , ; 'và' 'rồi') against ``spec``. ``scope``: modules the user selected, used when the text names none."""
    f = fold(text)
    if not f.strip():
        return {"status": "unsupported", "message": "Câu lệnh trống."}
    named = _ids_in(spec, f)
    selected = [i for i in (scope or []) if any(m.id == i for m in spec.module)]
    ops: list[dict[str, Any]] = []
    lines: list[str] = []
    for part in [p for p in re.split(r"[,;]| va | roi | dong thoi ", f) if p.strip()]:
        ids = _ids_in(spec, part) or named or selected
        got = _clause(spec, part, ids)
        if isinstance(got, dict):
            return got
        ops.append(got[0])
        lines.append(got[1])
    op = combine_ops(ops)
    targets = sorted({str(o.get("id") or o.get("afterModule") or "") for o in ([op] if op.get("op") != "multi" else op["ops"])} - {""})
    return {"status": "ok", "operation": op, "summary": lines, "targets": targets}


def check_operation(op: Any) -> dict[str, Any]:
    """Gate for an operation produced elsewhere (a language model): a known kind, no whole-design replace, no nested multi."""
    obj = as_dict(op)
    kind = obj.get("op") if obj is not None else None
    if obj is None or kind not in ALLOWED_OPS:
        return {"status": "unsupported", "message": f"Thao tác {kind!r} không được phép từ câu lệnh tự do."}
    subs = [as_dict(o) for o in as_list(obj.get("ops")) or []]
    if kind == "multi" and not all(o is not None and o.get("op") in ALLOWED_OPS and o.get("op") != "multi" for o in subs):
        return {"status": "unsupported", "message": "Danh sách thao tác không hợp lệ."}
    return {"status": "ok", "operation": op, "summary": ["Đề xuất từ mô hình ngôn ngữ"], "targets": []}


def module_choices(modules: list[Module]) -> list[str]:
    return [m.id for m in modules][:MAX_CHOICES]
