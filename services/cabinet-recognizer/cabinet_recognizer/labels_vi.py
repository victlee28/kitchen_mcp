"""Từ điển hiển thị tiếng Việt (R12: chữ tiếng Việt chỉ ở lớp từ điển/giao diện)."""
from __future__ import annotations

MODULE_NAMES: dict[str, str] = {
    "upper": "Tủ trên", "upper-dish-rack": "Tủ giá bát nâng hạ", "upper-hood": "Tủ trên máy hút mùi",
    "upper-open-shelf": "Kệ mở", "upper-glass": "Tủ trên cánh kính", "upper-lift-up": "Tủ trên cánh nâng",
    "upper-corner": "Tủ trên góc", "base": "Tủ dưới", "base-sink": "Tủ chậu rửa",
    "base-drawer": "Tủ ngăn kéo", "base-hob": "Tủ dưới bếp nấu", "base-oven": "Tủ lò nướng",
    "base-corner": "Tủ dưới góc", "base-open-shelf": "Kệ mở dưới", "tall": "Tủ cao",
    "tall-fridge": "Tủ cao tủ lạnh", "filler": "Tấm bù", "other": "Module khác",
}
APPLIANCE_NAMES: dict[str, str] = {
    "sink": "Chậu rửa", "faucet": "Vòi rửa", "hob": "Bếp nấu âm", "hood": "Máy hút mùi",
    "oven": "Lò nướng", "microwave": "Lò vi sóng", "dishwasher": "Máy rửa bát",
    "fridge": "Tủ lạnh", "led": "Đèn LED", "other": "Thiết bị khác",
}


def module_name(mtype: str, doors: int, drawers: int, is_open: bool) -> str:
    base = MODULE_NAMES.get(mtype, mtype)
    parts = [base]
    if drawers:
        parts.append(f"{drawers} ngăn kéo")
    if doors and not is_open:
        parts.append(f"{doors} cánh")
    return " ".join(parts)
