"""Khu vực / quốc gia và thứ tự ưu tiên tiêu chuẩn.

Mỗi dòng tri thức có `khu_vuc` (mã khu vực) và `quoc_gia` (danh sách mã ISO 3166-1 alpha-2, cách nhau dấu phẩy;
rỗng = áp dụng cả khu vực). Khi tra cứu/kiểm tra cho quốc gia C thuộc khu vực R:
    quốc gia C (30)  >  cả khu vực R (20)  >  toàn cầu GLOBAL (10)  >  nước/khu vực khác (1, chỉ để tham khảo)
Hòa điểm thì xét độ mạnh của nguồn: bat-buoc > tieu-chuan > khuyen-nghi > thuc-hanh > chua-ro.
"""
from __future__ import annotations

import unicodedata

KHU_VUC = {
    "GLOBAL": "Toàn cầu",
    "SEA": "Đông Nam Á",
    "EA": "Đông Á",
    "NA": "Bắc Mỹ",
    "EU": "Châu Âu",
    "OC": "Châu Đại Dương",
}

QUOC_GIA = {  # mã -> (tên, khu vực)
    "VN": ("Việt Nam", "SEA"), "TH": ("Thái Lan", "SEA"), "MY": ("Malaysia", "SEA"), "SG": ("Singapore", "SEA"),
    "ID": ("Indonesia", "SEA"), "PH": ("Philippines", "SEA"),
    "CN": ("Trung Quốc", "EA"), "JP": ("Nhật Bản", "EA"), "KR": ("Hàn Quốc", "EA"), "TW": ("Đài Loan", "EA"),
    "US": ("Hoa Kỳ", "NA"), "CA": ("Canada", "NA"),
    "GB": ("Vương quốc Anh", "EU"), "DE": ("Đức", "EU"), "FR": ("Pháp", "EU"), "IT": ("Ý", "EU"), "ES": ("Tây Ban Nha", "EU"),
    "NL": ("Hà Lan", "EU"),
    "AU": ("Úc", "OC"), "NZ": ("New Zealand", "OC"),
}

# từ khóa trong câu mô tả -> mã quốc gia / khu vực
_TU_KHOA = {
    "việt nam": "VN", "vn": "VN", "thái lan": "TH", "singapore": "SG", "malaysia": "MY",
    "trung quốc": "CN", "nhật": "JP", "hàn quốc": "KR", "đài loan": "TW",
    "mỹ": "US", "hoa kỳ": "US", "usa": "US", "canada": "CA",
    "anh quốc": "GB", "vương quốc anh": "GB", "anh": "GB", "uk": "GB", "đức": "DE", "pháp": "FR", "italy": "IT", "ý": "IT",
    "úc": "AU", "australia": "AU", "new zealand": "NZ",
    "châu âu": "EU", "đông nam á": "SEA", "đông á": "EA", "bắc mỹ": "NA",
}

NGUON_RANK = {"bat-buoc": 4, "tieu-chuan": 3, "khuyen-nghi": 2, "thuc-hanh": 1, "chua-ro": 0}
MUC_DO_THEO_NGUON = {"bat-buoc": "error", "tieu-chuan": "warning", "khuyen-nghi": "warning", "thuc-hanh": "info", "chua-ro": "warning"}


def chuan_hoa(quoc_gia: str | None = None, khu_vuc: str | None = None) -> tuple[str | None, str | None]:
    """Trả (mã quốc gia, mã khu vực); suy khu vực từ quốc gia nếu thiếu. Báo lỗi nếu mã lạ."""
    qg = (quoc_gia or "").strip().upper() or None
    kv = (khu_vuc or "").strip().upper() or None
    if qg and qg not in QUOC_GIA:
        raise ValueError(f"Mã quốc gia '{qg}' chưa hỗ trợ; dùng một trong: {', '.join(QUOC_GIA)}")
    if kv and kv not in KHU_VUC:
        raise ValueError(f"Mã khu vực '{kv}' không hợp lệ; dùng một trong: {', '.join(KHU_VUC)}")
    if qg and not kv:
        kv = QUOC_GIA[qg][1]
    return qg, kv


_TIEN_TO = r"(?:chuẩn|tiêu chuẩn|tại|ở|thị trường|theo|kiểu|cho|sang|nước|khách|nhà)"


def tu_cau_mo_ta(text: str) -> tuple[str | None, str | None]:
    """Nhận quốc gia/khu vực khi đi sau từ chỉ nơi chốn ("chuẩn Úc", "tại Việt Nam", "thị trường châu Âu")
    để tránh khớp nhầm ("thẩm mỹ", "ý tưởng")."""
    import re
    t = unicodedata.normalize("NFC", text).lower()
    kws = "|".join(re.escape(k) for k in sorted(_TU_KHOA, key=len, reverse=True))
    m = re.search(_TIEN_TO + r"\s+(" + kws + r")(?![a-zà-ỹ])", t)
    if not m:
        return None, None
    code = _TU_KHOA[m.group(1)]
    return (None, code) if code in KHU_VUC else (code, QUOC_GIA[code][1])


def diem_uu_tien(row: dict, quoc_gia: str | None, khu_vuc: str | None) -> int:
    ds = [x.strip().upper() for x in (row.get("quoc_gia") or "").split(",") if x.strip()]
    kv = (row.get("khu_vuc") or "GLOBAL").upper()
    if quoc_gia and quoc_gia in ds:
        return 30
    if khu_vuc and kv == khu_vuc and not ds:
        return 20
    if khu_vuc and kv == khu_vuc:  # cùng khu vực nhưng của nước khác
        return 15
    if kv == "GLOBAL":
        return 10
    return 1


def nhan_uu_tien(diem: int) -> str:
    return {30: "quốc gia", 20: "khu vực", 15: "cùng khu vực (nước khác)", 10: "toàn cầu"}.get(diem, "tham khảo nước ngoài")


def sap_xep(rows: list[dict], quoc_gia: str | None, khu_vuc: str | None) -> list[dict]:
    def key(r):
        meta = r.get("metadata") or {}
        return (-diem_uu_tien(r, quoc_gia, khu_vuc), -NGUON_RANK.get(meta.get("loaiNguon", "chua-ro"), 0), -(r.get("id") or 0))
    return sorted(rows, key=key)
