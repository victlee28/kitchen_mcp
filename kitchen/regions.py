"""Khu vực / quốc gia và thứ tự ưu tiên tiêu chuẩn.

Mỗi dòng tri thức có `khu_vuc` (mã khu vực) và `quoc_gia` (danh sách mã ISO 3166-1 alpha-2, cách nhau dấu phẩy;
rỗng = áp dụng cả khu vực). Khi tra cứu/kiểm tra cho quốc gia C thuộc khu vực R:
    quốc gia C (30)  >  cả khu vực R (20)  >  toàn cầu GLOBAL (10)  >  nước/khu vực khác (1, chỉ để tham khảo)
Hòa điểm thì xét độ mạnh của nguồn: bat-buoc > tieu-chuan > khuyen-nghi > thuc-hanh > chua-ro.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import builtin
from .catalog import Catalog
from .errors import InvalidInput
from .i18n import pick
from .jsonview import as_list

import unicodedata

@dataclass(frozen=True)
class Tables:
    """The catalog kinds ``region``, ``country`` (name, region, words recognised in a request) and ``source-type`` (strength, severity)."""
    regions: dict[str, str]                       # code -> Vietnamese name
    countries: dict[str, tuple[str, str]]         # code -> (Vietnamese name, region code)
    keywords: dict[str, str]                      # word in a request -> country or region code
    source_rank: dict[str, int]
    severity: dict[str, str]


def _build(catalog: Catalog) -> Tables:
    regs = {it.id: pick(it.data.get("name"), "vi") for it in catalog.all("region")}
    countries = {it.id: (pick(it.data.get("name"), "vi"), str(it.data.get("region", "GLOBAL"))) for it in catalog.all("country")}
    keywords: dict[str, str] = {}
    for it in [*catalog.all("country"), *catalog.all("region")]:
        for word in as_list(it.data.get("keywords")) or []:
            keywords.setdefault(str(word).lower(), it.id)
    rank = {it.id: int(it.data.get("rank", 0)) for it in catalog.all("source-type")}
    severity = {it.id: str(it.data.get("severity", "warning")) for it in catalog.all("source-type")}
    return Tables(regs, countries, keywords, rank, severity)


def tables(catalog: Catalog = builtin.CATALOG) -> Tables:
    return catalog.derived("regions.tables", _build)


_BUILTIN = tables()
REGIONS = _BUILTIN.regions                    # the builtin tables (the functions take the merged catalog)
COUNTRIES = _BUILTIN.countries
SOURCE_RANK = _BUILTIN.source_rank
SEVERITY_BY_SOURCE = _BUILTIN.severity


def normalize(country: str | None = None, region: str | None = None, catalog: Catalog = builtin.CATALOG) -> tuple[str | None, str | None]:
    """Trả (mã quốc gia, mã khu vực); suy khu vực từ quốc gia nếu thiếu. Báo lỗi nếu mã lạ."""
    t = tables(catalog)
    COUNTRIES, REGIONS = t.countries, t.regions  # noqa: N806 — the catalog's tables, under the names the code below uses
    qg = (country or "").strip().upper() or None
    kv = (region or "").strip().upper() or None
    if qg and qg not in COUNTRIES:
        raise InvalidInput(f"Country code {qg!r} is not supported; use one of {', '.join(COUNTRIES)}", code="bad-country", params={"code": qg, "allowed": ', '.join(COUNTRIES)})
    if kv and kv not in REGIONS:
        raise InvalidInput(f"Region code {kv!r} is not valid; use one of {', '.join(REGIONS)}", code="bad-region", params={"code": kv, "allowed": ', '.join(REGIONS)})
    if qg and not kv:
        kv = COUNTRIES[qg][1]
    return qg, kv


_PREFIX = r"(?:chuẩn|tiêu chuẩn|tại|ở|thị trường|theo|kiểu|cho|sang|nước|khách|nhà)"
_Y_WORDS = r"\s+(?:tưởng|kiến|nghĩa|muốn|định|thích|thức|chí|niệm)(?![a-zà-ỹ])"   # "ý" as the first syllable of a word, not Italy


def from_description(text: str, catalog: Catalog = builtin.CATALOG) -> tuple[str | None, str | None]:
    """Nhận quốc gia/khu vực khi đi sau từ chỉ nơi chốn ("chuẩn Úc", "tại Việt Nam", "thị trường châu Âu")
    để tránh khớp nhầm ("thẩm mỹ", "ý tưởng")."""
    import re
    t = unicodedata.normalize("NFC", text).lower()
    t_ = tables(catalog)
    kws = "|".join(re.escape(k) for k in sorted(t_.keywords, key=len, reverse=True))
    m = next((x for x in re.finditer(_PREFIX + r"\s+(" + kws + r")(?![a-zà-ỹ])", t)
              if not (x.group(1) == "ý" and re.match(_Y_WORDS, t[x.end():]))), None)   # "kiểu ý tưởng" is an idea, not Italy
    if not m:
        return None, None
    code = t_.keywords[m.group(1)]
    return (None, code) if code in t_.regions else (code, t_.countries[code][1])


def priority_score(row: dict[str, Any], country: str | None, region: str | None) -> int:
    ds = [x.strip().upper() for x in (row.get("country") or "").split(",") if x.strip()]
    kv = (row.get("region") or "GLOBAL").upper()
    if country and country in ds:
        return 30
    if region and kv == region and not ds:
        return 20
    if region and kv == region:  # cùng khu vực nhưng của nước khác
        return 15
    if kv == "GLOBAL":
        return 10
    return 1


def priority_label(score: int) -> str:
    return {30: "quốc gia", 20: "khu vực", 15: "cùng khu vực (nước khác)", 10: "toàn cầu"}.get(score, "tham khảo nước ngoài")


def sort_rows(rows: list[dict[str, Any]], country: str | None, region: str | None, catalog: Catalog = builtin.CATALOG) -> list[dict[str, Any]]:
    rank = tables(catalog).source_rank

    def key(r: dict[str, Any]) -> tuple[float, float, float]:
        meta: dict[str, Any] = r.get("metadata") or {}
        return (-priority_score(r, country, region), -rank.get(meta.get("sourceType", "unknown"), 0), -(r.get("id") or 0))
    return sorted(rows, key=key)
