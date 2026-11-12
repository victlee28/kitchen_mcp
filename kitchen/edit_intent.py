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
from . import builtin, lexicon
from .catalog import Catalog
from .lexicon import fold
from .words import Said, said, say
from .numeric import round_half_away
from .spec import KitchenSpec, Module, to_data
from . import vocab
from . import cabinet_types

ALLOWED_OPS = ("add", "remove", "update", "common", "lower-top", "multi")
MAX_CHOICES = 12



def _words(group: str, catalog: Catalog) -> tuple[tuple[str, Any], ...]:
    """``(folded phrase, value)`` of a command group of the dictionary (catalog kind ``lexicon``, groups ``edit-*``), in the order tried."""
    return lexicon.phrases(group, catalog)


def _first(f: str, group: str, catalog: Catalog) -> Any:
    """The value of the first phrase of ``group`` the text holds, None when it holds none."""
    return next((v for w, v in _words(group, catalog) if _has(f, w)), None)


def _says(f: str, verb: str, catalog: Catalog) -> bool:
    """Whether the text holds a word of the command verb ``verb`` (add, remove, handle, door, width, length)."""
    return any(_has(f, w) for w, v in _words("edit-verb", catalog) if v == verb)


def _verb_words(verb: str, catalog: Catalog) -> tuple[str, ...]:
    return tuple(w for w, v in _words("edit-verb", catalog) if v == verb)


def _has(f: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", f) is not None


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
    scopes = [f]
    for w in after:
        k = re.search(rf"(?<![a-z0-9]){re.escape(w)}", f)
        if k:
            scopes = [f[k.end():], f[:k.start()]]     # the number after the word ("rộng 600"), else the one before it ("600 wide")
            break
    for found in (x for sc in scopes for x in re.finditer(pat, sc)):
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


def _color(f: str, catalog: Catalog) -> str | None:
    """The colour or wood the text names (by its Vietnamese word or its English one), as the material name designs keep (Vietnamese)."""
    rows = [(v, v, True) for v, _hx, *_ in vocab.woods(catalog)] + [(v, v, False) for v, _hx, *_ in vocab.colors(catalog)]
    rows += [(r[2], r[0], True) for r in vocab.woods(catalog) if len(r) > 2 and r[2]] + [(r[2], r[0], False) for r in vocab.colors(catalog) if len(r) > 2 and r[2]]
    for word, name, wood in sorted(rows, key=lambda t: -len(t[0])):
        if _has(f, fold(word)):
            return say("material.wood-named", wood=name) if wood else (name[:1].upper() + name[1:])
    return None


def _storeys_in(f: str, catalog: Catalog) -> tuple[str, ...] | None:
    return _first(f, "edit-storey", catalog)


def _pick(spec: KitchenSpec, ids: list[str], storeys: tuple[str, ...] | None) -> list[str]:
    if ids:
        return ids
    return [m.id for m in spec.module if storeys is None or m.storey in storeys]


def _clarify(question: str, choices: list[str] | None = None) -> dict[str, Any]:   # question: a words.Said, worded again per reader
    return {"status": "clarify", "question": question, "choices": (choices or [])[:MAX_CHOICES]}


def _add(spec: KitchenSpec, f: str, ids: list[str], catalog: Catalog) -> dict[str, Any] | tuple[dict[str, Any], Said]:
    mtype = _first(f, "edit-type", catalog) or "base"
    width = _mm(f, _verb_words("width", catalog))
    if width is None:
        return _clarify(said("edit.ask.width-new"))
    if not ids:
        return _clarify(said("edit.ask.after"), [m.id for m in spec.module])
    ref = spec.find(ids[0])
    new_storey = cabinet_types.storey_of(mtype, catalog)
    if ref.storey not in (new_storey, "loft" if new_storey == "upper" else new_storey):
        return _clarify(said("edit.ask.same-storey", id=ref.id), [m.id for m in spec.module if m.storey == new_storey])
    op: dict[str, Any] = {"op": "add", "module": {"type": mtype, "width": width}, "afterModule": ref.id}
    return op, said("summary.edit.add", type=mtype, width=width, id=ref.id)


def _clause(spec: KitchenSpec, f: str, ids: list[str], catalog: Catalog) -> dict[str, Any] | tuple[dict[str, Any], Said]:
    """One clause -> (operation, summary) | a clarify result | an unsupported result. ``ids``: targets (mentioned or selected)."""
    storeys = _storeys_in(f, catalog)
    if _says(f, "add", catalog):
        return _add(spec, f, ids, catalog)
    if _says(f, "remove", catalog) and not _says(f, "handle", catalog):
        if not ids:
            return _clarify(said("edit.ask.remove"), [m.id for m in spec.module])
        ops = [{"op": "remove", "id": i} for i in ids]
        return combine_ops(ops), said("summary.edit.remove", ids=", ".join(ids))
    if _says(f, "handle", catalog):
        variant = _first(f, "edit-handle", catalog)
        color = _color(f, catalog)
        length = _mm(f, _verb_words("length", catalog))
        change: dict[str, Any] = {}
        if variant:
            change["variant"] = variant
        if color:
            change["material"] = color
        if length is not None and variant != "none":
            change["length"] = length
        if not change:
            return _clarify(said("edit.ask.handle"), [say(f"edit.choice.handle.{k}") for k in ("bar", "knob", "concealed", "none")])
        if ids or storeys:
            targets = _pick(spec, ids, storeys)
            return combine_ops([{"op": "update", "id": i, "changes": {"handle": change}} for i in targets]), said("summary.edit.handle", change=change, ids=", ".join(targets))
        handle = {**to_data(spec)["common"]["handle"], **change}
        return {"op": "common", "changes": {"handle": handle}}, said("summary.edit.handle-common", change=change)
    style = _first(f, "edit-door", catalog)
    if style and _says(f, "door", catalog):
        targets = _pick(spec, ids, storeys)
        if not targets:
            return _clarify(said("edit.ask.door"), [m.id for m in spec.module])
        return (combine_ops([{"op": "update", "id": i, "changes": {"doorStyle": style}} for i in targets]),
                said("summary.edit.door", style=style, ids=", ".join(targets)))
    if _says(f, "width", catalog):
        width = _mm(f)
        if width is None:
            return _clarify(said("edit.ask.width"))
        if not ids:
            return _clarify(said("edit.ask.width-which"), [m.id for m in spec.module])
        return combine_ops([{"op": "update", "id": i, "changes": {"width": width}} for i in ids]), said("summary.edit.width", width=width, ids=", ".join(ids))
    color = _color(f, catalog)
    if color:
        slot = _first(f, "edit-slot", catalog)
        if slot is None and storeys:
            slot = "tall" if storeys == ("tall",) else "upper" if "upper" in storeys else "base"
        if slot is None:
            return _clarify(said("edit.ask.color-where"), [say(f"edit.choice.part.{k}") for k in ("base", "upper", "tall", "countertop", "wall", "floor")])
        value = say("material.stone-named", stone=color.lower()) if slot == "countertop" else color
        material = {**to_data(spec)["common"]["material"], slot: value}
        return {"op": "common", "changes": {"material": material}}, said("summary.edit.material", slot=slot, value=value)
    return {"status": "unsupported", "message": said("edit.not-understood")}


def interpret_edit(spec: KitchenSpec, text: str, scope: list[str] | None = None, catalog: Catalog = builtin.CATALOG) -> dict[str, Any]:
    """Parse one sentence (clauses split on , ; 'và' 'rồi') against ``spec``. ``scope``: modules the user selected, used when the text names none."""
    f = fold(text)
    if not f.strip():
        return {"status": "unsupported", "message": said("edit.empty")}
    named = _ids_in(spec, f)
    selected = [i for i in (scope or []) if any(m.id == i for m in spec.module)]
    ops: list[dict[str, Any]] = []
    lines: list[Said] = []
    joins = "|".join(re.escape(f" {w} ") for w, _ in _words("edit-split", catalog))
    for part in [p for p in re.split(r"[,;]" + (f"|{joins}" if joins else ""), f) if p.strip()]:
        ids = _ids_in(spec, part) or named or selected
        got = _clause(spec, part, ids, catalog)
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
        return {"status": "unsupported", "message": said("edit.op-not-allowed", op=repr(kind))}
    subs = [as_dict(o) for o in as_list(obj.get("ops")) or []]
    if kind == "multi" and not all(o is not None and o.get("op") in ALLOWED_OPS and o.get("op") != "multi" for o in subs):
        return {"status": "unsupported", "message": said("edit.bad-op-list")}
    return {"status": "ok", "operation": op, "summary": [said("summary.edit.from-model")], "targets": []}


def module_choices(modules: list[Module]) -> list[str]:
    return [m.id for m in modules][:MAX_CHOICES]
