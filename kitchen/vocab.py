"""Từ vựng vật liệu/màu: tên tiếng Việt -> màu hiển thị (albedo, three.js) và cụm từ tiếng Anh cho prompt AI.

Dùng chung để màu trong ảnh albedo, JSON three.js và prompt cùng hiểu một tên vật liệu như nhau.
"""
from __future__ import annotations

import re
import unicodedata

# cụm dài đặt trước cụm ngắn (khớp cụm dài nhất)
MAU = [
    ("xanh rêu", "#7d8a5f", "sage green"), ("xanh olive", "#6b6b3a", "olive green"), ("xanh lá cây", "#4f7a4a", "green"),
    ("xanh lá", "#4f7a4a", "green"), ("xanh lục", "#3f7d4a", "green"), ("xanh lam", "#3c5f8a", "blue"), ("xanh biển", "#2f5f8a", "sea blue"),
    ("xanh navy", "#22324f", "navy blue"), ("xanh dương", "#3c5f8a", "blue"), ("xanh ngọc", "#3f8f8a", "teal"),
    ("xanh than", "#2b3440", "charcoal blue"), ("xanh mint", "#a8d5c2", "mint green"),
    ("xanh", "#5f7f8f", ""),  # "xanh" đứng một mình = xanh lá hoặc xanh dương: không dịch, để nguyên tiếng Việt cho AI
    ("trắng sữa", "#f3efe4", "off-white"), ("trắng ngà", "#efe8d8", "ivory"), ("trắng", "#f2f2f0", "white"),
    ("kem", "#eadfc8", "cream"), ("be", "#d8c6a8", "beige"), ("ghi", "#9a9a96", "light grey"),
    ("xám đậm", "#4a4a4a", "dark grey"), ("xám nhạt", "#c4c4c0", "light grey"), ("xám", "#8a8a88", "grey"),
    ("đen", "#2a2a2a", "black"), ("nâu đậm", "#4e3526", "dark brown"), ("nâu", "#7a5538", "brown"),
    ("đỏ đô", "#6e1f2a", "burgundy"), ("đỏ", "#a83232", "red"), ("hồng", "#d9a3a8", "pink"),
    ("đồng vàng", "#b5913f", "brushed brass"), ("vàng đồng", "#b5913f", "brushed brass"), ("đồng thau", "#b5913f", "brass"),
    ("đồng đỏ", "#a0583a", "copper"), ("đồng", "#a0703c", "bronze"), ("vàng gold", "#c8a24a", "gold"),
    ("vàng mù tạt", "#c9a03a", "mustard yellow"), ("vàng", "#d9b84a", "yellow"), ("cam", "#d27a3a", "orange"),
    ("tím", "#6b4f7a", "purple"),
]
GO = [  # gỗ / vân gỗ
    ("óc chó", "#5c3f2c", "walnut wood"), ("sồi", "#c49a6c", "oak wood"), ("tần bì", "#cfb28a", "ash wood"),
    ("xoan đào", "#9a5a3c", "cherry wood"), ("gõ đỏ", "#7a3a24", "red hardwood"), ("teak", "#a7774a", "teak wood"),
]
CHAT = [  # bề mặt / chất liệu (chỉ cho prompt)
    ("vân mây", "with soft cloudy veining"), ("vân đá", "marble veining"), ("vân gỗ", "wood grain"),
    ("mờ", "matte finish"), ("bóng gương", "high-gloss mirror finish"), ("bóng", "glossy finish"), ("sần", "textured finish"),
    ("acrylic", "acrylic"), ("laminate", "laminate"), ("melamine", "melamine"), ("sơn", "painted"), ("veneer", "wood veneer"),
    ("đá nhân tạo", "engineered quartz stone"), ("thạch anh", "quartz"), ("granite", "granite"), ("marble", "marble"),
    ("đá", "stone"), ("kính", "glass"), ("inox", "stainless steel"), ("nhôm", "aluminium"), ("gạch thẻ", "subway tile"),
    ("gạch", "ceramic tile"), ("gỗ", "wood"),
]


def _bo_dau(t: str) -> str:
    t = unicodedata.normalize("NFD", t).replace("đ", "d").replace("Đ", "D")
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def _norm(t: str) -> str:
    """Chuẩn hoá để so khớp: chữ thường, BỎ DẤU (người dùng hay gõ 'xanh luc' thay vì 'xanh lục'), gộp khoảng trắng."""
    return " " + re.sub(r"[\s,;/]+", " ", _bo_dau(unicodedata.normalize("NFC", (t or "").lower()))) + " "


def _has(t: str, key: str) -> bool:
    return f" {_bo_dau(key)} " in t


def _find(text: str, table):
    t = _norm(text)
    for row in table:
        if _has(t, row[0]):
            return row
    return None


def mau(text: str) -> str | None:
    """Màu hex suy từ tên vật liệu (màu nêu rõ được ưu tiên hơn màu gỗ)."""
    r = _find(text, MAU) or _find(text, GO)
    return r[1] if r else None


def mau_ro(text: str) -> str | None:
    """Chỉ màu nêu rõ, bỏ trắng/đen (các quy tắc chất liệu đã xử lý)."""
    r = _find(text, MAU)
    return r[1] if r and not r[0].startswith(("trắng", "đen")) else None


def tieng_anh(text: str) -> str:
    """Cụm tiếng Anh ngắn cho prompt, vd 'Laminate xanh rêu mờ' -> 'sage green matte finish laminate'."""
    if not text:
        return ""
    t = _norm(text)
    used, out = set(), []
    for table, col in ((MAU, 2), (GO, 2), (CHAT, 1)):
        for row in table:
            k = row[0]
            if _has(t, k) and not any(_bo_dau(k) in _bo_dau(u) for u in used):
                used.add(k)
                if row[col]:
                    out.append(row[col])
    res: list[str] = []
    for phrase in out:  # bỏ cụm mà mọi từ đã có (vd "wood" sau "oak wood")
        have = set(" ".join(res).split())
        if not set(phrase.split()) <= have:
            res.append(phrase)
    return " ".join(res)


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
