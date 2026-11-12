"""Bảng thuật ngữ chuẩn + bộ so khớp cho luồng tạo bếp từ mô tả (tiếng Việt có dấu / không dấu, tiếng Anh).

Mỗi mục (E) có: id, loại (kind), danh sách alias (viết có dấu), nhãn chuẩn, giá trị áp vào spec, vùng mặc định (slot),
trạng thái hỗ trợ (built | exported | ai-only | unsupported) và cụm tiếng Anh cho prompt ảnh.

Cách so khớp:
- Chuẩn hoá giữ nguyên độ dài chuỗi (NFC, chữ thường, bỏ dấu, '-' -> ' ', dấu phẩy thập phân -> '.') nên vị trí khớp trên
  chuỗi đã bỏ dấu dùng được trực tiếp trên chuỗi gốc.
- Cụm dài thắng cụm ngắn ("tân cổ điển" thắng "cổ điển", "đảo thác đá" thắng "đảo").
- Alias "yếu" (mờ, đỏ, đen, đá, ốp, kem, be…) chỉ nhận đúng dạng có dấu hoặc dạng gõ hoàn toàn không dấu, để "mở", "đèn",
  "đã", "kèm", "bê tông" không bị hiểu nhầm.
- Câu được tách thành mệnh đề (dấu , ; : . và các từ nối "và/với/and/with"), mỗi mệnh đề tìm từ chỉ phạm vi
  (tủ dưới, tủ trên, mặt bàn, ốp tường, tay nắm…) rồi gắn vật liệu/hoàn thiện vào đúng vùng.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any

from .numeric import round_int
from . import builtin, vocab
from .catalog import Catalog
from .jsonview import as_dict, as_list
from .errors import require

STATUSES = ("built", "exported", "ai-only", "unsupported", "ambiguous")
FRONT_SLOTS = ("base", "upper", "tall")


@dataclass(frozen=True)
class E:
    id: str
    kind: str
    aliases: tuple[str, ...]
    label: str = ""
    value: Any = None
    slot: str | None = None        # vùng mặc định khi mệnh đề không nêu phạm vi
    status: str = "built"
    message: str = ""
    ai: str = ""                   # cụm tiếng Anh cho prompt ảnh
    weak: bool = False             # chỉ nhận đúng dạng có dấu hoặc dạng hoàn toàn không dấu
    needs: tuple[str, ...] = ()    # chỉ hiệu lực khi mệnh đề có từ chỉ phạm vi thuộc tập này
    forbid: tuple[str, ...] = ()   # vô hiệu khi mệnh đề có từ chỉ phạm vi thuộc tập này
    wood_plain: str = ""           # (gỗ) nhãn khi đi kèm veneer/laminate…; label dùng khi đứng một mình


# ------------------------------------------------------------------ chuẩn hoá giữ độ dài
def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").lower()


def _fold_char(ch: str) -> str:
    if ch in "-_":
        return " "
    d = unicodedata.normalize("NFD", ch.replace("đ", "d"))
    base = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return base[:1] if base else " "


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu, '-' -> ' ', '2,4' -> '2.4'; độ dài bằng đúng NFC gốc."""
    s = "".join(_fold_char(c) for c in _nfc(text))
    return re.sub(r"(?<=\d),(?=\d)", ".", s)


def _squash(s: str) -> str:
    return re.sub(r"[\s\-_]+", " ", s.strip())


# ------------------------------------------------------------------ bảng thuật ngữ (catalog kind ``lexicon`` + colour words)
COLOR_WEAK = {"đỏ", "đen", "cam", "tím", "kem", "be"}  # dạng không dấu trùng từ thường
_EN_EXTRA = {"xám": "gray"}
COMMAND_PREFIX = "edit-"   # groups of the edit commands (edit_intent), kept out of the description matcher
ALIAS_LANGS = ("vi", "en")   # the order aliases are tried in (all of them are tried; a longer phrase wins)


def _tuple(v: Any) -> Any:
    xs = as_list(v)
    return tuple(_tuple(x) for x in xs) if xs is not None else v


def _by_language(value: Any) -> list[str]:
    """The strings of a ``{lang: [...]}`` field, the languages of ``ALIAS_LANGS`` first."""
    d = as_dict(value) or {}
    langs = [*ALIAS_LANGS, *(k for k in d if k not in ALIAS_LANGS)]
    return [str(x).strip() for lg in langs for x in (as_list(d.get(lg)) or []) if str(x).strip()]


def _entry(id: str, d: Mapping[str, Any]) -> E:
    return E(id=id, kind=str(d["group"]), aliases=tuple(_by_language(d.get("aliases"))),
             label=str(d.get("label", "")), value=_tuple(d.get("value")), slot=d.get("slot"), status=str(d.get("status", "built")),
             message=str(d.get("message", "")), ai=str(d.get("ai", "")), weak=bool(d.get("weak", False)),
             needs=tuple(d.get("needs") or ()), forbid=tuple(d.get("forbid") or ()), wood_plain=str(d.get("woodPlain", "")))


@dataclass(frozen=True)
class Lexicon:
    """The dictionary the matcher reads: entries in catalog order, then the colour words (``material-word``), with their compiled aliases."""
    entries: tuple[E, ...]
    patterns: tuple[tuple[re.Pattern[str], E, frozenset[str] | None], ...]

    @property
    def by_id(self) -> dict[str, E]:
        return {e.id: e for e in self.entries}

    def tag_phrases(self) -> dict[str, str]:
        return {e.value[1]: e.ai for e in self.entries if e.kind == "style" and e.value[1] and e.ai}


def _build(catalog: Catalog) -> Lexicon:
    entries = [_entry(it.id, it.data) for it in catalog.all("lexicon") if not str(it.data.get("group", "")).startswith(COMMAND_PREFIX) and it.data.get("group") != "regex"]
    entries += [E(id=f"color.{k}", kind="color", aliases=tuple([k, *([en] if en else []), *([_EN_EXTRA[k]] if k in _EN_EXTRA else [])]),
                  label=k, value=hx, weak=(k in COLOR_WEAK)) for k, hx, en in vocab.colors(catalog)]
    patterns: list[tuple[re.Pattern[str], E, frozenset[str] | None]] = []
    for e in entries:
        for a in e.aliases:
            pat = re.compile(r"(?<![a-z0-9])" + r"\s+".join(re.escape(w) for w in fold(a).split()) + r"(?![a-z0-9])")
            patterns.append((pat, e, frozenset(_alias_forms(a)) if e.weak else None))
    return Lexicon(tuple(entries), tuple(patterns))


def table(catalog: Catalog = builtin.CATALOG) -> Lexicon:
    """The dictionary of ``catalog`` (built once per catalog)."""
    return catalog.derived("lexicon", _build)


def _commands(catalog: Catalog) -> dict[str, tuple[tuple[str, Any], ...]]:
    out: dict[str, list[tuple[str, Any]]] = {}
    for it in catalog.all("lexicon"):
        e = _entry(it.id, it.data)
        if e.kind.startswith(COMMAND_PREFIX):
            out.setdefault(e.kind, []).extend((_squash(fold(a)), e.value) for a in e.aliases)
    return {k: tuple(v) for k, v in out.items()}


def _patterns(catalog: Catalog) -> dict[str, str]:
    out: dict[str, str] = {}
    for it in catalog.all("lexicon"):
        alts = _by_language(it.data.get("patterns"))
        if it.data.get("group") == "regex":
            out[it.id] = "(?:" + "|".join(f"(?:{x})" for x in alts) + ")" if alts else NEVER
    return out


NEVER = r"(?!x)x"   # a pattern that matches nothing (an entry without patterns)


def source(id: str, catalog: Catalog = builtin.CATALOG) -> str:
    """The regular expression of the ``regex`` entry ``id`` (its patterns in every language, as one alternation) to build a bigger
    expression with; an unknown id matches nothing."""
    return catalog.derived("lexicon.patterns", _patterns).get(id, NEVER)


def pattern(id: str, catalog: Catalog = builtin.CATALOG) -> re.Pattern[str]:
    """The compiled ``source(id)``."""
    return re.compile(source(id, catalog))


def phrases(group: str, catalog: Catalog = builtin.CATALOG) -> tuple[tuple[str, Any], ...]:
    """The words of an edit-command group (``edit-verb``, ``edit-type``…) as ``(folded phrase, value)``, in the order they are tried
    (the first one the sentence holds wins). These groups only serve the edit commands (``edit_intent``), not ``interpret``."""
    return catalog.derived("lexicon.commands", _commands).get(group, ())


_NUMU = r"(\d+(?:\.\d+)?)\s*(mm|cm|m)(?![a-z0-9])"
_HEIGHT_NUM = re.compile(r"(?:cao|height|high|len|toi|up to|to)\s*(?:khoang\s*)?" + _NUMU + r"|" + _NUMU + r"\s*(?:cao|high)")


# ------------------------------------------------------------------ so khớp
@dataclass
class M:
    start: int
    end: int
    e: E
    raw: str
    order: int = 0


def _alias_forms(alias: str) -> set[str]:
    return {_squash(_nfc(alias)), _squash(fold(alias))}


def _scan(f: str, raw: str, lex: Lexicon) -> list[M]:
    out: list[M] = []
    for pat, e, forms in lex.patterns:
        for m in pat.finditer(f):
            r = raw[m.start():m.end()]
            if forms is not None and _squash(r) not in forms:
                continue
            out.append(M(m.start(), m.end(), e, r))
    return out


def _resolve(cands: list[M], taken: list[M] | None = None) -> list[M]:
    chosen = list(taken or [])
    for m in sorted(cands, key=lambda m: (-(m.end - m.start), m.start)):
        if all(m.end <= c.start or m.start >= c.end for c in chosen):
            chosen.append(m)
    return chosen


_SPLIT = re.compile(r"[,;:\n]|(?<!\d)\.(?!\d)|\s(?:va|and|voi|with|plus)\s|\s\+\s")


def _clauses(f: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    last = 0
    for m in _SPLIT.finditer(f):
        out.append((last, m.start()))
        last = m.end()
    out.append((last, len(f)))
    return [(a, b) for a, b in out if b > a]


# ------------------------------------------------------------------ kết quả
@dataclass
class Result:
    updates: dict[str, Any] = field(default_factory=dict[str, Any])       # trường của KitchenTemplate
    items: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])   # bảng diễn giải
    blank: list[tuple[int, int]] = field(default_factory=list[tuple[int, int]])  # đoạn đã dùng cho số đo (che khỏi regex số)

    def mask(self, text: str) -> str:
        t = _nfc(text)
        for a, b in self.blank:
            t = t[:a] + " " * (b - a) + t[b:]
        return t


def _item(m: M | None, e: E | None, canonical: str, scope: list[str] | str, target: str, status: str | None = None, message: str | None = None) -> dict[str, Any]:
    e = e or (m.e if m else None)
    return {"term": (m.raw if m else ""), "id": e.id if e else "", "kind": e.kind if e else "", "canonical": canonical,
            "scope": scope if isinstance(scope, list) else [scope], "target": target,
            "status": status or (e.status if e else "built"), "message": message if message is not None else (e.message if e else "")}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _compose(ms: list[M], slots: list[str]) -> str | None:
    """Ghép tên vật liệu từ các mục trong một đoạn (theo thứ tự xuất hiện). None nếu không có gì dùng được."""
    rank = {"construction": 0, "wood": 1, "stone": 2, "tile": 2, "metal": 2, "color": 3, "finish": 4, "detail": 5}
    ms = sorted(ms, key=lambda m: (rank.get(m.e.kind, 9), m.start))
    kinds = {m.e.kind for m in ms}
    has_con = "construction" in kinds
    parts: list[str] = []

    def add(x: str):
        if x and x.lower() not in {p.lower() for p in parts}:
            parts.append(x)
    colors = [m.e.label for m in ms if m.e.kind == "color"]
    stone_specific = [m for m in ms if m.e.kind == "stone" and m.e.id != "stone.generic"]
    wood_specific = any(m.e.kind == "wood" and m.e.id != "wood.generic" for m in ms)
    for m in ms:
        e = m.e
        if e.kind == "construction":
            add(e.label)
        elif e.kind == "wood":
            if e.id == "wood.generic" and wood_specific:
                continue
            if has_con:
                add(e.wood_plain)
            elif e.id == "wood.oak" and not colors:
                add(e.label)                     # "sồi" đứng một mình = tên cũ của dự án
            else:
                add("Gỗ " + e.wood_plain if e.id != "wood.generic" else "Gỗ")
        elif e.kind == "stone":
            if e.id == "stone.generic" and stone_specific:
                continue
            add(e.label)
        elif e.kind in ("tile", "metal", "color", "finish", "detail"):
            add(e.label)
    if not parts:
        return None
    res = " ".join(parts)
    if "wallTile" in slots and not any(m.e.kind in ("stone", "tile") for m in ms):
        res = "Đá " + res                       # "ốp đá trắng" -> "Đá trắng"
    if "countertop" in slots and not (stone_specific or any(m.e.kind in ("stone", "tile") for m in ms)):
        res = "Đá nhân tạo " + res          # "mặt bàn trắng" -> "Đá nhân tạo trắng"
    if res == "Đá granite":
        res = "Đá granite tối"
    return _cap(res) if res[:1].islower() else res


def interpret(text: str, catalog: Catalog = builtin.CATALOG) -> Result:
    lex = table(catalog)
    raw = _nfc(text)
    f = fold(text)
    res = Result()
    items = res.items
    # 1. khớp không điều kiện
    base = [m for m in _scan(f, raw, lex) if not (m.e.needs or m.e.forbid)]
    cond = [m for m in _scan(f, raw, lex) if (m.e.needs or m.e.forbid)]
    chosen = _resolve(base)
    # 2. điều kiện theo phạm vi của mệnh đề
    clauses = _clauses(f)
    def scopes_in(c: tuple[int, int]) -> list[M]:
        return [m for m in chosen if m.e.kind == "scope" and c[0] <= m.start and m.end <= c[1]]
    keep: list[M] = []
    for m in cond:
        c = next((c for c in clauses if c[0] <= m.start and m.end <= c[1]), (0, len(f)))
        sc = {s for x in scopes_in(c) for s in x.e.value}
        if (not m.e.needs or sc & set(m.e.needs)) and not (sc & set(m.e.forbid)):
            keep.append(m)
    # điều kiện thắng khi trùng chỗ với mục không điều kiện
    for m in keep:
        chosen = [c for c in chosen if c.end <= m.start or c.start >= m.end]
    chosen = _resolve(keep, chosen)
    for i, m in enumerate(sorted(chosen, key=lambda m: m.start)):
        m.order = i
    chosen.sort(key=lambda m: m.start)

    def clause_of(m: M) -> tuple[int, int]:
        return next((c for c in clauses if c[0] <= m.start and m.end <= c[1]), (0, len(f)))

    # 3. bố cục
    layouts = [m for m in chosen if m.e.kind == "layout"]
    for m in layouts:
        if m.e.status == "unsupported":
            items.append(_item(m, None, m.e.value, "whole", "geometry_edit"))
    sup = [m for m in layouts if m.e.status != "unsupported"]
    if sup:
        pick = sup[-1]
        res.updates["geometry_edit"] = pick.e.value
        for m in sup:
            items.append(_item(m, None, m.e.value, "whole", "geometry_edit", message="" if m is pick else f"Có nhiều bố cục; dùng '{pick.e.value}' (nêu sau cùng)."))
    elif any(m.e.status == "unsupported" for m in layouts):
        items.append(_item(None, None, "I", "whole", "geometry_edit", "ambiguous",
                           "Không dựng được bố cục bạn mô tả nên đã tạo bếp chữ I mặc định; thiết kế này KHÔNG phải bố cục đó."))
    # 4. phong cách
    smatch = [m for m in chosen if m.e.kind == "style"]
    bases = [m for m in smatch if m.e.value[0]]
    tags: list[str] = []
    if bases:
        pick = bases[-1]
        res.updates["style"] = pick.e.value[0]
    for m in smatch:
        st, tag = m.e.value
        if st:
            msg = ""
            if len({b.e.value[0] for b in bases}) > 1 and m is not bases[-1]:
                msg = f"Nhiều phong cách; hình học theo '{bases[-1].e.value[0]}' (nêu sau cùng)."
            if tag:
                msg = (msg + " " if msg else "") + f"Hình học theo {st}; nhãn {tag} ghi thêm cho prompt ảnh."
            items.append(_item(m, None, st, "whole", "style", "ambiguous" if msg.startswith("Nhiều") else "built", msg))
        if tag and tag not in tags:
            tags.append(tag)
            items.append(_item(m, None, tag, "whole", "styleTags", "exported",
                               "Ghi vào thiết kế, file 3D và prompt ảnh; không đổi hình học. Vật liệu đi kèm cần nêu riêng (vd 'gỗ sáng')."))
    if tags:
        res.updates["styleTags"] = tags
    # 5. kịch trần, kệ mở
    for m in chosen:
        if m.e.kind == "loft":
            res.updates["loft"] = True
            items.append(_item(m, None, "tủ nóc / kịch trần", "whole", "loft"))
        elif m.e.kind == "unsupported":
            items.append(_item(m, None, m.e.value, "whole", "-"))
        elif m.e.kind == "feature":
            if res.updates.get(m.e.value):
                continue  # đảo nêu hai lần (vd "đảo bếp ... trên đảo") chỉ ghi một mục
            res.updates[m.e.value] = True
            items.append(_item(m, None, m.e.value, "whole", m.e.value, "built", m.e.message))
            if m.e.ai:
                res.updates.setdefault("aiHints", []).append(m.e.ai)
        elif m.e.kind == "photo":
            res.updates.setdefault("renderPreferences", []).append(m.e.ai)
            items.append(_item(m, None, m.e.ai, "image", "renderPreferences"))
        elif m.e.kind == "fridge":
            res.updates["fridge"] = True
            if m.e.ai:
                res.updates.setdefault("renderPreferences", []).append(m.e.ai)
            items.append(_item(m, None, "tủ lạnh", "whole", "fridge", "built"))
    # 6. tay nắm không / âm
    for m in chosen:
        if m.e.kind == "handlevar":
            res.updates["handleVariant"] = m.e.value
            items.append(_item(m, None, m.e.value, "handle", "common.handle.variant"))
            if m.e.ai:
                res.updates.setdefault("aiHints", []).append(m.e.ai)
    # 7. cánh
    door_style: dict[str, str] = {}
    for m in chosen:
        if m.e.kind != "door":
            continue
        c = clause_of(m)
        sl = sorted(scopes_in(c), key=lambda x: x.start)
        near = ([x for x in sl if x.start < m.start] or sl or [None])[-1] if any(x.start < m.start for x in sl) else (sl[0] if sl else None)
        sc = list(near.e.value) if near is not None else []
        slots = [s for s in FRONT_SLOTS if s in sc] or (list(("base", "upper", "tall")) if m.e.slot == "fronts" else [require(m.e.slot, f"{m.e.id}.slot")])
        for s in slots:
            door_style[s] = m.e.value
        items.append(_item(m, None, m.e.value, slots, "module.doorStyle", message=m.e.message))
        if m.e.ai:
            res.updates.setdefault("aiHints", []).append(m.e.ai)
    if door_style:
        res.updates["doorStyle"] = door_style
    # 8. kiểu xếp gạch
    for m in chosen:
        if m.e.kind == "pattern":
            res.updates["wallTilePattern"] = m.e.value
            res.updates.setdefault("aiHints", []).append(m.e.ai)
            items.append(_item(m, None, m.e.value, "wallTile", "common.wallTilePattern"))
    # 9. chiều cao ốp
    for m in chosen:
        if m.e.kind == "bsheight":
            res.updates["backsplashHeight"] = m.e.value
            items.append(_item(m, None, m.e.value, "wallTile", "common.backsplashHeight"))
    for c in clauses:
        sc = {s for x in scopes_in(c) for s in x.e.value}
        if "wallTile" in sc and "backsplashHeight" not in res.updates:
            seg = f[c[0]:c[1]]
            hm = _HEIGHT_NUM.search(seg)
            if hm:
                g = [x for x in hm.groups() if x is not None]
                val, unit = float(g[0]), g[1]
                mm = val * {"mm": 1, "cm": 10, "m": 1000}[unit]
                span = (c[0] + hm.start(), c[0] + hm.end())
                res.blank.append(span)
                if 50 <= mm <= 3000:
                    res.updates["backsplashHeightMm"] = round_int(mm)
                    items.append({"term": raw[span[0]:span[1]], "id": "bs.mm", "kind": "bsheight", "canonical": f"{round_int(mm)} mm",
                                  "scope": ["wallTile"], "target": "common.backsplashHeightMm", "status": "built", "message": ""})
                else:
                    items.append({"term": raw[span[0]:span[1]], "id": "bs.mm", "kind": "bsheight", "canonical": f"{round_int(mm)} mm", "scope": ["wallTile"],
                                  "target": "common.backsplashHeightMm", "status": "ambiguous", "message": "Chiều cao ốp ngoài khoảng 50–3000 mm nên bỏ qua."})
    # che đoạn chiều cao ốp dạng từ (đã khớp bsheight) khỏi regex số
    # 10. vật liệu theo mệnh đề / đoạn
    material: dict[str, str] = {}
    for c in clauses:
        in_c = [m for m in chosen if c[0] <= m.start and m.end <= c[1]]
        scs = sorted([m for m in in_c if m.e.kind == "scope"], key=lambda m: m.start)
        mats = [m for m in in_c if m.e.kind in ("construction", "wood", "stone", "tile", "metal", "finish", "detail", "color")]
        if not mats:
            continue
        segs: list[tuple[list[str], str, list[M]]] = []   # (vùng, từ chỉ phạm vi, mục)
        if scs:
            bounds = [scs[0].start] + [s.start for s in scs[1:]] + [c[1]]
            for i, s in enumerate(scs):
                lo = c[0] if i == 0 else bounds[i]
                hi = bounds[i + 1]
                segs.append((list(s.e.value), s.raw, [m for m in mats if lo <= m.start < hi]))
        else:
            segs.append(([], "", mats))
        for slots, _sraw, ms in segs:
            if not ms:
                continue
            guessed = ""
            main = next((m for m in sorted(ms, key=lambda m: m.start) if m.e.kind not in ("color", "finish", "detail")), None)
            if not slots:
                if main is not None:
                    slots = [main.e.slot] if main.e.slot else []
                    guessed = (f"Không nêu phạm vi nên áp cho '{slots[0]}' (đoán theo loại vật liệu)."
                               if slots and main.e.kind not in ("tile", "metal") else "")
                else:
                    cols = [m.e.label for m in ms if m.e.kind == "color"]
                    if cols and cols[0] == "trắng":
                        slots, guessed = ["upper"], "Không nêu phạm vi nên áp màu trắng cho tủ trên (đoán)."
                    else:
                        for m in ms:
                            if len(m.e.label) > 4:   # màu ngắn (ghi, kem, be…) quá dễ trùng từ thường: không báo
                                items.append(_item(m, None, m.e.label, "?", "-", "ambiguous", "Chưa rõ áp cho vùng nào; hãy nêu 'tủ dưới…', 'mặt bàn…', 'tay nắm…'."))
                        continue
            if main is not None and main.e.kind == "metal" and "handle" not in slots:
                for m in ms:
                    items.append(_item(m, None, m.e.label, slots, "-", "ambiguous",
                                       "Kim loại chỉ áp cho tay nắm khi nêu rõ ('tay nắm đồng thau xước'); chưa áp lên các vùng khác."))
                continue
            label = _compose(ms, slots)
            if not label:
                continue
            for s in slots:
                if s == "handle":
                    res.updates["handleMaterial"] = label
                else:
                    material[s] = label
            term = " ".join(m.raw for m in sorted(ms, key=lambda m: m.start))
            first = sorted(ms, key=lambda m: m.start)[0]
            it = _item(first, first.e, label, slots, "common.handle.material" if slots == ["handle"] else "common.material." + "/".join(slots), "built", guessed)
            it["term"] = term
            items.append(it)
    if material:
        res.updates["material"] = material
    # gom mục trùng (cùng term + target)
    seen: set[tuple[Any, Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        k = (it["term"], it["id"], it["target"])
        if k not in seen:
            seen.add(k)
            out.append(it)
    res.items = out
    return res


def notes(items: list[dict[str, Any]]) -> list[str]:
    """Ghi chú dạng chữ cho những mục chưa dựng được hoặc cần lưu ý."""
    return [f"[{i['status']}] {i['term'] or i['canonical']}: {i['message']}" for i in items if i["message"] and i["status"] != "built"]


def tag_phrases(tags: list[str] | None, catalog: Catalog = builtin.CATALOG) -> list[str]:
    phrases = table(catalog).tag_phrases()
    return [phrases[t] for t in (tags or []) if t in phrases]
