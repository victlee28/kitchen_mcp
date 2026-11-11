"""Từ vựng vật liệu/màu: tên tiếng Việt -> màu hiển thị (albedo, three.js) và cụm từ tiếng Anh cho prompt AI.

Dùng chung để màu trong ảnh albedo, JSON three.js và prompt cùng hiểu một tên vật liệu như nhau.
"""
from __future__ import annotations

from collections.abc import Sequence

import re
import unicodedata

from .catalog import Catalog
from . import builtin

Row = tuple[str, ...]
"""(word, hex, english) for colours and woods, (word, english) for finishes: the catalog kind ``material-word``, in catalog order
(a longer phrase comes before the shorter one it contains: the first match wins; see ``_place``)."""


def _contains(longer: str, shorter: str) -> bool:
    return f" {_strip_diacritics(shorter.lower())} " in f" {_strip_diacritics(longer.lower())} " and longer != shorter


def _place(rows: list[Row], row: Row) -> None:
    """Add a row edited in the app: before the first row whose phrase it contains ("xanh bơ" before "xanh"), else at the end.
    Builtin rows keep the order of ``data/items/material-word.json``."""
    at = next((i for i, r in enumerate(rows) if _contains(row[0], r[0])), len(rows))
    rows.insert(at, row)


def _tables(catalog: Catalog) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {"color": [], "wood": [], "finish": []}
    for it in catalog.all("material-word"):
        d = it.data
        group = str(d.get("group", ""))
        if group not in out:
            continue
        row: Row = (str(d["word"]), str(d.get("hex", "")), str(d.get("en", ""))) if group != "finish" else (str(d["word"]), str(d.get("en", "")))
        if it.source == "builtin":
            out[group].append(row)
        else:
            _place(out[group], row)
    return out


def colors(catalog: Catalog = builtin.CATALOG) -> list[Row]:
    return catalog.derived("vocab.tables", _tables)["color"]


def woods(catalog: Catalog = builtin.CATALOG) -> list[Row]:
    return catalog.derived("vocab.tables", _tables)["wood"]


def finishes(catalog: Catalog = builtin.CATALOG) -> list[Row]:
    return catalog.derived("vocab.tables", _tables)["finish"]


def _strip_diacritics(t: str) -> str:
    t = unicodedata.normalize("NFD", t).replace("đ", "d").replace("Đ", "D")
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def norm(t: str) -> str:
    """Chuẩn hoá để so khớp: chữ thường, BỎ DẤU (người dùng hay gõ 'xanh luc' thay vì 'xanh lục'), gộp khoảng trắng."""
    return " " + re.sub(r"[\s,;/]+", " ", _strip_diacritics(unicodedata.normalize("NFC", (t or "").lower()))) + " "


def has(t: str, key: str) -> bool:
    return f" {_strip_diacritics(key)} " in t


def _accented(t: str) -> str:
    """Like ``_norm`` but keeping the diacritics (same length, so offsets match ``_norm``)."""
    return " " + re.sub(r"[\s,;/]+", " ", unicodedata.normalize("NFC", (t or "").lower())) + " "


def _matches(t: str, ta: str, key: str) -> bool:
    """``key`` is in the text: typed without diacritics, or with exactly these diacritics. "họng" (a gas burner) is not "hồng" (pink),
    though both are "hong" once stripped; "hong" typed bare still means pink."""
    plain, word = f" {_strip_diacritics(key)} ", f" {unicodedata.normalize('NFC', key.lower())} "
    if len(t) != len(ta):                       # a character that did not strip to exactly one: fall back to the plain match
        return plain in t
    at = t.find(plain)
    while at >= 0:
        typed = ta[at:at + len(plain)]
        if typed == word or typed == plain:
            return True
        at = t.find(plain, at + 1)
    return False


def find(text: str, table: Sequence[tuple[str, ...]]) -> tuple[str, ...] | None:
    t, ta = norm(text), _accented(text)
    for row in table:
        if _matches(t, ta, row[0]):
            return row
    return None


def color(text: str, catalog: Catalog = builtin.CATALOG) -> str | None:
    """Màu hex suy từ tên vật liệu (màu nêu rõ được ưu tiên hơn màu gỗ)."""
    r = find(text, colors(catalog)) or find(text, woods(catalog))
    return r[1] if r else None


def explicit_color(text: str, catalog: Catalog = builtin.CATALOG) -> str | None:
    """Chỉ màu nêu rõ, bỏ trắng/đen (các quy tắc chất liệu đã xử lý)."""
    r = find(text, colors(catalog))
    return r[1] if r and not r[0].startswith(("trắng", "đen")) else None


def to_english(text: str, catalog: Catalog = builtin.CATALOG) -> str:
    """Cụm tiếng Anh ngắn cho prompt, vd 'Laminate xanh rêu mờ' -> 'sage green matte finish laminate'."""
    if not text:
        return ""
    t, ta = norm(text), _accented(text)
    used: set[str] = set()
    out: list[str] = []
    for table, col in ((colors(catalog), 2), (woods(catalog), 2), (finishes(catalog), 1)):
        for row in table:
            k = row[0]
            if _matches(t, ta, k) and not any(_strip_diacritics(k) in _strip_diacritics(u) for u in used):
                used.add(k)
                if row[col]:
                    out.append(row[col])
    res: list[str] = []
    for phrase in out:  # bỏ cụm mà mọi từ đã có (vd "wood" sau "oak wood")
        have = set(" ".join(res).split())
        if not set(phrase.split()) <= have:
            res.append(phrase)
    text = " ".join(res)
    for generic, specific in (("stone", ("marble", "quartz", "granite", "terrazzo")), ("ceramic tile", ("subway tile", "zellige tile"))):
        if generic in res and any(x in text for x in specific):  # "white marble stone" -> "white marble"
            res.remove(generic)
    words = " ".join(res).split()
    return " ".join(w for i, w in enumerate(words) if i == 0 or w != words[i - 1])  # "walnut wood wood veneer" -> "walnut wood veneer"


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
