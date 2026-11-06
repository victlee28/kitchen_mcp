"""Khu vực / quốc gia và thứ tự ưu tiên tiêu chuẩn.

Mỗi dòng tri thức có `khu_vuc` (mã khu vực) và `quoc_gia` (danh sách mã ISO 3166-1 alpha-2, cách nhau dấu phẩy;
rỗng = áp dụng cả khu vực). Khi tra cứu/kiểm tra cho quốc gia C thuộc khu vực R:
    quốc gia C (30)  >  cả khu vực R (20)  >  toàn cầu GLOBAL (10)  >  nước/khu vực khác (1, chỉ để tham khảo)
Hòa điểm thì xét độ mạnh của nguồn: bat-buoc > tieu-chuan > khuyen-nghi > thuc-hanh > chua-ro.
"""
from __future__ import annotations
from .errors import InvalidInput

import unicodedata

REGIONS = {
    "GLOBAL": "Toàn cầu",
    "SEA": "Đông Nam Á",
    "EA": "Đông Á",
    "NA": "Bắc Mỹ",
    "EU": "Châu Âu",
    "OC": "Châu Đại Dương",
}

COUNTRIES = {  # mã -> (tên, khu vực)
    "VN": ("Việt Nam", "SEA"), "TH": ("Thái Lan", "SEA"), "MY": ("Malaysia", "SEA"), "SG": ("Singapore", "SEA"),
    "ID": ("Indonesia", "SEA"), "PH": ("Philippines", "SEA"),
    "CN": ("Trung Quốc", "EA"), "JP": ("Nhật Bản", "EA"), "KR": ("Hàn Quốc", "EA"), "TW": ("Đài Loan", "EA"),
    "US": ("Hoa Kỳ", "NA"), "CA": ("Canada", "NA"),
    "GB": ("Vương quốc Anh", "EU"), "DE": ("Đức", "EU"), "FR": ("Pháp", "EU"), "IT": ("Ý", "EU"), "ES": ("Tây Ban Nha", "EU"),
    "NL": ("Hà Lan", "EU"),
    "AU": ("Úc", "OC"), "NZ": ("New Zealand", "OC"),
}

# từ khóa trong câu mô tả -> mã quốc gia / khu vực
_KEYWORDS = {
    "việt nam": "VN", "vn": "VN", "thái lan": "TH", "singapore": "SG", "malaysia": "MY",
    "trung quốc": "CN", "nhật": "JP", "hàn quốc": "KR", "đài loan": "TW",
    "mỹ": "US", "hoa kỳ": "US", "usa": "US", "canada": "CA",
    "anh quốc": "GB", "vương quốc anh": "GB", "image": "GB", "uk": "GB", "đức": "DE", "pháp": "FR", "italy": "IT", "ý": "IT",
    "úc": "AU", "australia": "AU", "new zealand": "NZ",
    "châu âu": "EU", "đông nam á": "SEA", "đông á": "EA", "bắc mỹ": "NA",
}

SOURCE_RANK = {"mandatory": 4, "standard": 3, "recommended": 2, "practice": 1, "unknown": 0}
SEVERITY_BY_SOURCE = {"mandatory": "error", "standard": "warning", "recommended": "warning", "practice": "info", "unknown": "warning"}


def normalize(country: str | None = None, region: str | None = None) -> tuple[str | None, str | None]:
    """Trả (mã quốc gia, mã khu vực); suy khu vực từ quốc gia nếu thiếu. Báo lỗi nếu mã lạ."""
    qg = (country or "").strip().upper() or None
    kv = (region or "").strip().upper() or None
    if qg and qg not in COUNTRIES:
        raise InvalidInput(f"Mã quốc gia '{qg}' chưa hỗ trợ; dùng một trong: {', '.join(COUNTRIES)}")
    if kv and kv not in REGIONS:
        raise InvalidInput(f"Mã khu vực '{kv}' không hợp lệ; dùng một trong: {', '.join(REGIONS)}")
    if qg and not kv:
        kv = COUNTRIES[qg][1]
    return qg, kv


_PREFIX = r"(?:chuẩn|tiêu chuẩn|tại|ở|thị trường|theo|kiểu|cho|sang|nước|khách|nhà)"


def from_description(text: str) -> tuple[str | None, str | None]:
    """Nhận quốc gia/khu vực khi đi sau từ chỉ nơi chốn ("chuẩn Úc", "tại Việt Nam", "thị trường châu Âu")
    để tránh khớp nhầm ("thẩm mỹ", "ý tưởng")."""
    import re
    t = unicodedata.normalize("NFC", text).lower()
    kws = "|".join(re.escape(k) for k in sorted(_KEYWORDS, key=len, reverse=True))
    m = re.search(_PREFIX + r"\s+(" + kws + r")(?![a-zà-ỹ])", t)
    if not m:
        return None, None
    code = _KEYWORDS[m.group(1)]
    return (None, code) if code in REGIONS else (code, COUNTRIES[code][1])


def priority_score(row: dict, country: str | None, region: str | None) -> int:
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


def sort_rows(rows: list[dict], country: str | None, region: str | None) -> list[dict]:
    def key(r):
        meta = r.get("metadata") or {}
        return (-priority_score(r, country, region), -SOURCE_RANK.get(meta.get("sourceType", "unknown"), 0), -(r.get("id") or 0))
    return sorted(rows, key=key)
