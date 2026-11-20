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
import unicodedata
from typing import Any

from .edit import combine_ops
from .jsonview import as_dict, as_list
from . import builtin, lexicon
from .catalog import Catalog
from .lexicon import fold
from .words import Said, said, say
from .i18n import DEFAULT_LANG
from .numeric import round_half_away
from .spec import KitchenSpec, Module, to_data
from . import vocab
from . import cabinet_types

ALLOWED_OPS = ("add", "remove", "update", "common", "lower-top", "set-moldings", "multi")
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
    return _at(f, word) >= 0


def _at(f: str, word: str) -> int:
    """Where the whole word (or phrase) ``word`` first stands in the folded text, -1 when it does not."""
    hit = re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", f)
    return hit.start() if hit else -1


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
            at = _at(f, fold(word))
            if not wood and any(0 <= _at(f, w) < at for w, _ in _words("edit-wood", catalog)):
                wood = True                       # "gỗ vàng", "gỗ đặc màu đen": a wood of that colour, not a paint
            return say("material.wood-named", wood=name) if wood else (name[:1].upper() + name[1:])
    return None


def _solid_doors(spec: KitchenSpec, f: str, targets: list[str], catalog: Catalog) -> tuple[dict[str, Any], Said] | None:
    """"cánh gỗ" / "cánh đặc": glass fronts of the targets made solid (a glass-door type becomes its plain type, a glass door style
    becomes flat), with the material the clause names. None when no target has glass, so the clause reads on as a colour."""
    color = _color(f, catalog)
    ops: list[dict[str, Any]] = []
    for m in spec.module:
        if m.id not in targets:
            continue
        change: dict[str, Any] = {}
        if m.type.endswith("-glass"):
            change["type"] = m.type[:-len("-glass")]
        if m.doorStyle == "glass":
            change["doorStyle"] = "flat"
        if change and color:
            change["material"] = color
        if change:
            ops.append({"op": "update", "id": m.id, "changes": change})
    if not ops:
        return None
    ids = ", ".join(o["id"] for o in ops)
    return combine_ops(ops), (said("summary.edit.solid-material", ids=ids, value=color) if color else said("summary.edit.solid", ids=ids))


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
    molding = _first(f, "edit-molding", catalog)
    if molding is not None:
        return _moldings(spec, f, tuple(molding), catalog)
    if _says(f, "hinge", catalog):
        return _hinge(spec, f, ids, storeys, catalog)
    if _says(f, "add", catalog):
        return _add(spec, f, ids, catalog)
    if _says(f, "remove", catalog) and not _says(f, "handle", catalog):
        if not ids and storeys and _first(f, "edit-all", catalog):     # "xóa hết tủ trên": every cabinet of that storey
            ids = _pick(spec, [], storeys)
        if not ids:
            return _clarify(said("edit.ask.remove"), _pick(spec, [], storeys))
        whole = say("edit.choice.remove-whole")
        if _says(f, "door", catalog) and not _has(f, fold(whole)):   # "xóa cánh cửa": the cabinet's door, not the cabinet: ask before removing it
            return _clarify(said("edit.ask.remove-part", ids=", ".join(ids)), [whole])
        ops = [{"op": "remove", "id": i} for i in ids]
        return combine_ops(ops), said("summary.edit.remove", ids=", ".join(ids))
    if _says(f, "handle", catalog):
        found = _item_named(f, "handle", catalog)
        named = found[0] if found else None
        rest = f.replace(found[1], " " * len(found[1])) if found else f      # the item's own name says nothing more (its colour, its length)
        into = _into_at(rest, catalog)          # "đổi tay nắm thành dạng tròn": the kind is what follows "thành" (which folds like "thanh", a bar)
        variant = _first(rest[into:] if into is not None else rest, "edit-handle", catalog)
        color = _color(rest, catalog)
        length = _mm(rest, _verb_words("length", catalog))
        change: dict[str, Any] = {}
        if named is not None:                 # a handle of the catalog by its name: its kind, length and finish, unless the sentence says otherwise
            data = catalog.data("handle", named)
            change.update({"item": named, "variant": str(data.get("variant") or "bar")})
            if isinstance(data.get("length"), (int, float)):
                change["length"] = float(data["length"])
            if isinstance(data.get("material"), str):
                change["material"] = str(data["material"])
        if variant:
            change["variant"] = variant
        if color:
            change["material"] = color
        if length is not None and variant != "none":
            change["length"] = length
        if named is not None:
            data = catalog.data("handle", named)
            if any(k in change and data.get(k) is not None and change[k] != data.get(k) for k in ("variant", "length", "material")):
                del change["item"]                # the sentence changed the catalog handle: it is no longer that one
        if not change:
            return _clarify(said("edit.ask.handle"), [say(f"edit.choice.handle.{k}") for k in ("bar", "knob", "concealed", "none")])
        if ids or storeys:
            targets = _pick(spec, ids, storeys)
            def own(i: str) -> dict[str, Any]:     # a cabinet that had a catalog handle of its own loses it unless one is named
                had = next((m.handle for m in spec.module if m.id == i), None)
                return {**change, "item": None} if "item" not in change and had is not None and had.item else change
            return combine_ops([{"op": "update", "id": i, "changes": {"handle": own(i)}} for i in targets]), said("summary.edit.handle", change=change, ids=", ".join(targets))
        current = {k: v for k, v in to_data(spec)["common"]["handle"].items() if k != "item"}     # settings changed by hand: no catalog handle
        handle = {**current, **change}
        return {"op": "common", "changes": {"handle": handle}}, said("summary.edit.handle-common", change=change)
    style = _first(f, "edit-door", catalog)
    if style == "solid" and _says(f, "door", catalog):
        targets = _pick(spec, ids, storeys)
        solid = _solid_doors(spec, f, targets, catalog)
        if solid is not None:
            return solid
        if targets and _color(f, catalog) is None:      # the doors are solid already and no material is named: which wood?
            return _clarify(said("edit.ask.solid-material", ids=", ".join(targets)),
                            [say("material.wood-named", wood=w[0]) for w in vocab.woods(catalog)[:4]])
        style = None                              # no glass to make solid: "cánh gỗ sồi" is the colour of the front
    if style and _says(f, "door", catalog):
        targets = _pick(spec, ids, storeys)
        if not targets:
            return _clarify(said("edit.ask.door"), [m.id for m in spec.module])
        return (combine_ops([{"op": "update", "id": i, "changes": {"doorStyle": style}} for i in targets]),
                said("summary.edit.door", style=style, ids=", ".join(targets)))
    common = _first(f, "edit-common", catalog)
    size = _mm(f)
    if common is not None and size is not None and not _says(f, "width", catalog):   # "hạ mặt bếp xuống 850", "trần cao 2700"
        return {"op": "common", "changes": {common: size}}, said("summary.edit.common-size", what=common, value=size)
    if _first(f, "edit-vague", catalog) and size is None:           # "to ra một chút": how much?
        return _clarify(said("edit.ask.how-much"))
    new_type = _type_after_into(f, catalog)
    if new_type is not None and not _says(f, "add", catalog):     # "đổi TD5 thành tủ ngăn kéo", "thay bằng tủ ngăn kéo"
        if not ids:
            return _clarify(said("edit.ask.type-which"), [m.id for m in spec.module])
        return (combine_ops([{"op": "update", "id": i, "changes": {"type": new_type}} for i in ids]),
                said("summary.edit.type", type=new_type, ids=", ".join(ids)))
    if _says(f, "height", catalog) and size is not None:          # "TT2 cao 800"
        targets = ids or (_pick(spec, [], storeys) if storeys else [])
        if not targets:
            return _clarify(said("edit.ask.height-which"), [m.id for m in spec.module])
        return combine_ops([{"op": "update", "id": i, "changes": {"height": size}} for i in targets]), said("summary.edit.height", height=size, ids=", ".join(targets))
    if _says(f, "change", catalog) and ids and size is not None and _color(f, catalog) is None:   # "đổi TD6 sang 400": a cabinet's size is its width
        return combine_ops([{"op": "update", "id": i, "changes": {"width": size}} for i in ids]), said("summary.edit.width", width=size, ids=", ".join(ids))
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
        if slot is None and ids:                                    # "đổi màu cánh tủ này sang gỗ sồi": the cabinets' own front
            return (combine_ops([{"op": "update", "id": i, "changes": {"material": color}} for i in ids]),
                    said("summary.edit.material-module", value=color, ids=", ".join(ids)))
        if slot is None:
            return _clarify(said("edit.ask.color-where"), [say(f"edit.choice.part.{k}") for k in ("base", "upper", "tall", "countertop", "wall", "floor")])
        value = say("material.stone-named", stone=color.lower()) if slot == "countertop" else color
        material = {**to_data(spec)["common"]["material"], slot: value}
        return {"op": "common", "changes": {"material": material}}, said("summary.edit.material", slot=slot, value=value)
    return {"status": "unsupported", "message": said("edit.not-understood")}


def _without_ids(spec: KitchenSpec, f: str) -> str:
    """The text with the cabinet ids it names taken out."""
    for m in spec.module:
        f = re.sub(rf"(?<![a-z0-9]){re.escape(fold(m.id))}(?![a-z0-9])", " ", f)
    return f


def _into_at(f: str, catalog: Catalog) -> int | None:
    """Where the first "into" word ("thành", "sang", "bằng") ends, None when the text has none."""
    hits = [m.end() for w, _ in _words("edit-into", catalog) for m in re.finditer(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", f)]
    return min(hits) if hits else None


def _type_after_into(f: str, catalog: Catalog) -> str | None:
    """The cabinet type named after an "into" word ("đổi TD5 thành tủ ngăn kéo"): the type to change to."""
    at = _into_at(f, catalog)
    return None if at is None else _first(f[at:], "edit-type", catalog)


def _typed(spec: KitchenSpec, f: str, catalog: Catalog) -> list[str]:
    """Cabinets the text points at by their kind ("xóa tủ chậu", "tủ bếp nấu rộng 900"): the modules of the type it names before any
    "into" word. A storey word ("tủ trên") names a storey, not a kind: none."""
    at = _into_at(f, catalog)
    head = f if at is None else f[:at]
    storey_words = {w for w, _ in _words("edit-storey", catalog)}
    for w, v in _words("edit-type", catalog):
        if w not in storey_words and _has(head, w):
            return [m.id for m in spec.module if m.type == v]
    return []


def _hinge(spec: KitchenSpec, f: str, ids: list[str], storeys: tuple[str, ...] | None,
           catalog: Catalog) -> dict[str, Any] | tuple[dict[str, Any], Said]:
    """"đổi bản lề giảm chấn", "TD3 bản lề lọt lòng": the catalog hinge of the cabinets named or clicked (or of a storey), else of the design."""
    found = _item_named(f, "hinge", catalog)
    if found is None:
        return _clarify(said("edit.ask.hinge"), [str((as_dict(item.data.get("label")) or {}).get(DEFAULT_LANG) or item.id) for item in catalog.all("hinge")])
    hinge = found[0]
    if ids or storeys:
        targets = _pick(spec, ids, storeys)
        return (combine_ops([{"op": "update", "id": i, "changes": {"hinge": hinge}} for i in targets]),
                said("summary.edit.hinge", hinge=hinge, ids=", ".join(targets)))
    return {"op": "common", "changes": {"hinge": hinge}}, said("summary.edit.hinge-common", hinge=hinge)


def _moldings(spec: KitchenSpec, f: str, variants: tuple[str, ...], catalog: Catalog) -> dict[str, Any] | tuple[dict[str, Any], Said]:
    """"bỏ phào", "thêm phào chân": the design's moldings without / with the crown or base molding (``set-moldings``)."""
    from .moldings import default_moldings
    have = [to_data(m) for m in spec.moldings]
    if _says(f, "remove", catalog):
        kept = [m for m in have if m.get("variant") not in variants]
        return {"op": "set-moldings", "moldings": kept}, said("summary.edit.moldings-off", which=", ".join(variants))
    if _says(f, "add", catalog):
        present = {m.get("variant") for m in have}
        extra = [to_data(m) for m in default_moldings("crown" in variants, "base" in variants) if m.variant not in present]
        return {"op": "set-moldings", "moldings": have + extra}, said("summary.edit.moldings-on", which=", ".join(variants))
    return _clarify(said("edit.ask.moldings"), [say("edit.choice.moldings.add"), say("edit.choice.moldings.remove")])


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
    parts: list[str] = []
    for part in [p for p in re.split(r"[,;]" + (f"|{joins}" if joins else ""), f) if p.strip()]:
        if parts and _ids_in(spec, part) and not _without_ids(spec, part).strip():
            parts[-1] += " " + part          # "xóa TD1 và TD2": a part that only names cabinets belongs to the one before
        else:
            parts.append(part)
    for part in parts:
        ids = _ids_in(spec, part) or (_typed(spec, part, catalog) if not _says(part, "add", catalog) else []) or named or selected
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


def surface_edit(text: str, surfaces: list[str], catalog: Catalog = builtin.CATALOG) -> dict[str, Any]:
    """A sentence about the wall faces the user selected (``surfaces``: ``kitchen.wall_surfaces`` ids) -> ``surface-material``.

    What follows a finishing verb ("sơn trắng", "ốp gạch thẻ xanh", "đổi sang gỗ sồi") is the material, as written; a colour or wood alone is
    taken by its name; "bỏ vật liệu" / "như tường" gives the faces back the wall's finish. Other wishes about faces (hang something on the
    wall, cabinets along it) are not read yet."""
    raw = unicodedata.normalize("NFC", text).strip()
    f = fold(raw)                                        # same length as the NFC text: a match in f marks the same words in raw
    if not f.strip():
        return {"status": "unsupported", "message": said("edit.empty")}
    words = _words("edit-surface", catalog)
    makes = [w for w, v in _words("edit-opening", catalog) if v == "make"]
    if any(_has(f, w) for w, v in words if v == "cabinets") and any(_has(f, w) for w in makes):
        return {"status": "cabinets", "prompt": raw}      # cabinets along the face: the caller lays a run on it
    if any(_has(f, w) for w, v in words if v == "reset"):
        return {"status": "ok", "operation": {"op": "surface-material", "surfaces": surfaces, "material": None},
                "summary": [said("summary.edit.surface-material-reset", n=len(surfaces))], "targets": []}
    spans = [(m.start(), -m.end()) for w, v in words if v == "finish" for m in re.finditer(r"(?:^|\s)" + re.escape(w) + r"\s+", f)]
    name = raw[-min(spans)[1]:].strip(" .,!;:") if spans else None          # the first verb, its longest wording ("paint it" over "paint")
    if not name:
        color = _color(f, catalog)          # a colour alone, written with its accents ("đỏ", not "đó": folding loses them)
        name = color if color and color.lower() in text.lower() else None
    if not name:
        return _clarify(said("edit.ask.surface-material", n=len(surfaces)))
    name = name[:1].upper() + name[1:]
    return {"status": "ok", "operation": {"op": "surface-material", "surfaces": surfaces, "material": name[:120]},
            "summary": [said("summary.edit.surface-material", n=len(surfaces), value=name[:120])], "targets": []}


SIZE_PAIR = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mm|cm|m)?\s*[x*]\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|m)?(?![a-z0-9])")


def _pair(f: str) -> tuple[float, float] | None:
    """``width x height`` written as one ("1200x2400", "90 x 220 cm"), mm."""
    m = SIZE_PAIR.search(f)
    if m is None:
        return None
    unit = m.group(4) or m.group(2)
    scale = {"cm": 10.0, "m": 1000.0}.get(unit or "", 1.0)
    return (float(round_half_away(float(m.group(1).replace(",", ".")) * scale, 0)), float(round_half_away(float(m.group(3).replace(",", ".")) * scale, 0)))


def _item_named(f: str, kind: str, catalog: Catalog) -> tuple[str, str] | None:
    """``(id, the name found)`` of the catalog item of ``kind`` the sentence names by its whole label (any language) or id; the longest
    name wins."""
    best: tuple[int, str, str] | None = None
    for item in catalog.all(kind):
        label = as_dict(item.data.get("label")) or {}
        aliases = [w for ws in (as_dict(item.data.get("aliases")) or {}).values() for w in (as_list(ws) or []) if isinstance(w, str)]
        for name in [fold(str(v)).strip() for v in [*label.values(), *aliases] if isinstance(v, str)] + [item.id.replace("-", " ")]:
            if len(name) >= 4 and _has(f, name) and (best is None or len(name) > best[0]):
                best = (len(name), item.id, name)
    return (best[1], best[2]) if best else None


def _opening_type_named(f: str, catalog: Catalog) -> str | None:
    """The opening type (catalog kind ``opening-type``, the workshop's and the user's own included) the sentence names by its label, one of
    its ``aliases`` or its id;
    the longest name wins ("cửa đi hai cánh có ô thoáng" over "cửa đi hai cánh")."""
    best: tuple[int, str] | None = None
    near: tuple[float, int, str] | None = None
    said_words = set(_tokens(f, catalog))
    for item in catalog.all("opening-type"):
        label = as_dict(item.data.get("label")) or {}
        aliases = [w for ws in (as_dict(item.data.get("aliases")) or {}).values() for w in (as_list(ws) or []) if isinstance(w, str)]
        names = [fold(str(v)).strip() for v in [*label.values(), *aliases] if isinstance(v, str)] + [item.id.replace("-", " "), item.id]
        for name in names:
            if len(name) >= 4 and _has(f, name) and (best is None or len(name) > best[0]):
                best = (len(name), item.id)
            words_ = _tokens(name, catalog)
            hit = sum(1 for w in words_ if w in said_words)
            share = hit / len(words_) if words_ else 0.0
            if hit >= NEAR_MIN_WORDS and share >= NEAR_SHARE and (near is None or (share, -len(words_)) > (near[0], -near[1])):
                near = (share, len(words_), item.id)
    if best:
        return best[1]
    return near[2] if near else None


NEAR_MIN_WORDS = 3          # a type named loosely: at least this many of its label's words in the sentence...
NEAR_SHARE = 0.6            # ...and this share of them ("cửa đi hai cánh" -> "Cửa đi hai cánh đều")


def _tokens(f: str, catalog: Catalog = builtin.CATALOG) -> list[str]:
    """Words of folded text, single digits read as words ("2 cánh" = "hai cánh": dictionary group ``edit-number``, the Vietnamese word of
    each digit), brackets and commas dropped."""
    digits: dict[str, str] = {}
    for w, v in lexicon.phrases("edit-number", catalog):    # the first word of each digit (the Vietnamese one: the labels are worded so)
        digits.setdefault(str(v), w)
    found: list[str] = re.findall(r"[a-z0-9]+", f)
    return [digits.get(w) or w for w in found]


def opening_wish(text: str, catalog: Catalog = builtin.CATALOG) -> dict[str, Any] | None:
    """A sentence about a room door, window or passage, or about saving what was clicked to the catalog; None when it is neither.

    ``{"action": "save", "name": str | None, "what": "system" | None}``: "lưu vào database", "lưu cửa này thành mẫu tên Cửa nhôm" (``what`` None:
    whatever was clicked, a door or a cabinet system).
    ``{"action": "make" | "replace", "kind": "door" | "window" | "passage", "type": id | None, "width"?, "height"?}``: "tạo cửa đi ở vị trí này",
    "thay bằng cửa sổ 1200x1400", "đặt cửa đi hai cánh". Words of the lexicon group ``edit-opening``; "cửa tủ" (a cabinet door) is not an opening."""
    raw = unicodedata.normalize("NFC", text).strip()
    f = fold(raw)
    words = _words("edit-opening", catalog)

    def said_(value: str) -> list[str]:
        return [w for w, v in words if v == value and _has(f, w)]
    if said_("save") and (said_("store") or said_("door") or said_("window") or said_("passage") or said_("system")):
        name = None
        for w in sorted((w for w, v in words if v == "name"), key=len, reverse=True):
            m = re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])\s*[:\"'“]?\s*", f)
            if m:
                name = raw[m.end():].strip(" .,!;:\"'”“") or None
                break
        return {"action": "save", "name": name[:80] if name else None, "what": "system" if said_("system") else None}
    if said_("not"):
        return None
    named = _opening_type_named(f, catalog)
    kind = next((v for w, v in words if v in ("window", "passage", "door") and _has(f, w)), None)
    if named is not None:
        kind = str(catalog.data("opening-type", named).get("kind") or kind or "door")
    if kind is None:
        return None
    raising = bool(said_("raise"))
    action = ("remove" if said_("remove") else "edit" if said_("edit") or raising else "replace" if said_("replace") else "make")
    out: dict[str, Any] = {"action": action, "kind": kind, "type": named}
    if said_("keep-size"):
        out["size"] = "keep"            # answers "the hole is wider than the type allows": keep it (``oversize``)
    elif said_("fit-size"):
        out["size"] = "fit"             # ...or bring it into the type's range
    if action == "remove":
        return out
    sill_words = sorted(said_("sill"), key=len, reverse=True)
    if sill_words:                      # "cách sàn 900", "bậu cửa 1m": the height of the sill above the floor; taken out of the rest
        out["sill"], f = _taken(f, sill_words[0])
    pair = _pair(f)
    if pair is not None:
        out["width"], out["height"] = pair
    else:
        high = said_("height")
        wide = [w for w, v in words if v == "width" and _has(f, w)] + [w for w in _verb_words("width", catalog) if _has(f, w)]
        if high:
            out["height"] = _mm(f, tuple(high))
        if wide:
            out["width"] = _mm(f, tuple(wide))
        elif not high and raising and "sill" not in out:
            out["sill"] = _mm(f)        # "nâng cửa sổ lên 1000": the number is where its sill goes
        elif not high:
            out["width"] = _mm(f)
    return {k: v for k, v in out.items() if v is not None or k == "type"}


def _taken(f: str, word: str) -> tuple[float | None, str]:
    """The length written after ``word`` (mm, as ``_mm``) and the text without the word and that number, so the other sizes of the
    sentence are not read from it."""
    k = re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", f)
    if k is None:
        return None, f
    number = r"(\d+(?:[.,]\d+)?)\s*(mm|cm|m)?(?![a-z0-9])"
    m = re.search(number, f[k.end():])
    if m is not None and f[k.end():k.end() + m.start()].strip(" :=") in ("", "la", "len", "xuong", "o", "khoang", "tu", "is", "at", "of", "to"):
        return _mm(m.group(0)), f[:k.start()] + " " + f[k.end() + m.end():]
    b = re.search(number + r"\s*$", f[:k.start()])     # "1000 off the floor": the number just before it
    if b is not None:
        return _mm(b.group(0)), f[:b.start()] + " " + f[k.end():]
    return None, f[:k.start()] + " " + f[k.end():]
