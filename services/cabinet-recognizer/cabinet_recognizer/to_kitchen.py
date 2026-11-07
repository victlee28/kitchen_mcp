"""cabinet-recognizer 0.1/0.2 -> KitchenSpec (schemaVersion 2) của mcp-imagev2 (lõi thuần, JSON vào - JSON ra).

Khác biệt chính đã xử lý (chi tiết ở README, mục "Tương thích với kitchen service"):
- Khóa gốc: `modules` -> `module`; `x` -> `fromCorner`; `common` đổi tên trường.
- Hệ toạ độ: recognizer đo dãy sau từ góc TRÁI sang phải; KitchenSpec lấy gốc ở góc sau–PHẢI và đo dãy sau
  từ phải sang trái (fromCorner = dài tường sau − x − rộng). Dãy trái/phải: cùng đo từ tường sau.
- KitchenSpec chỉ có phần khuất (`blindCorner`) ở phía fromCorner. Góc sau–trái: chuyển phần khuất sang
  module đầu tiên của dãy trái (cùng diện tích, đúng phía). Góc sau–phải: giữ ở module dãy sau.
- Kệ góc mở chỉ có ở góc sau–phải (`corner-shelf`); ở góc sau–trái tách thành hai module `upper-open`.
- Loại module đổi theo bảng TYPE_MAP; thứ không có bản tương đương được ghi vào `issues`.
"""
from __future__ import annotations

from typing import Any

from .numeric import round_int

TYPE_MAP: dict[str, str] = {
    "base": "base", "base-sink": "base-sink", "base-corner": "base", "base-drawer": "base-drawers",
    "base-hob": "base-cooktop", "base-oven": "base-oven", "base-dishwasher": "base", "base-open-shelf": "base",
    "base-corner-sink": "base-corner-sink",
    "upper": "upper", "upper-dish-rack": "upper", "upper-hood": "upper-hood", "upper-open-shelf": "upper-open",
    "upper-glass": "upper-glass", "upper-lift-up": "upper", "upper-corner": "upper", "upper-top": "upper-loft",
    "tall": "tall", "tall-fridge": "tall-fridge", "tall-display": "tall", "tall-oven": "tall",
    "filler": "base", "other": "base",
}
APPLIANCE_MAP = {"sink": "sink", "faucet": "faucet", "hob": "cooktop", "hood": "hood", "oven": "oven",
                 "microwave": "oven", "fridge": "fridge", "led": "light", "dishwasher": "other", "other": "other"}
OVEN_NICHE_MM = 450


def _issue(issues: list[dict[str, Any]], code: str, msg: str, module: str | None = None) -> None:
    item: dict[str, Any] = {"code": code, "message": msg}
    if module:
        item["module"] = module
    issues.append(item)


def to_kitchen_spec(rec: dict[str, Any], name: str = "Tủ bếp nhận diện từ ảnh") -> dict[str, Any]:
    """Trả {"spec": KitchenSpec JSON, "issues": [...]} — issues liệt kê thông tin bị mất hoặc bị xấp xỉ."""
    issues: list[dict[str, Any]] = []
    c = rec["common"]
    mods = [dict(m) for m in rec["modules"]]
    walls_in = rec.get("walls") or {"back": {"runLength": c.get("runLength", 0)}}
    has_left = any(m.get("wall") == "left" for m in mods)
    has_right = any(m.get("wall") == "right" for m in mods)
    back_len = int(walls_in.get("back", {}).get("runLength") or c.get("runLength") or 0)
    if not back_len:
        back_len = max((m["x"] + m["width"] for m in mods if m.get("wall", "back") == "back"), default=0)

    worktop = int(c["worktopTop"])
    thick = int(c["worktopThickness"])
    upper_top = int(c.get("upperTop", c.get("upperBottom", 1500) + 750))
    cab_top = max(upper_top, int(c.get("tallTop", upper_top)))
    mats = c.get("materials", {})
    material = {k: v for k, v in {
        "base": mats.get("base") or mats.get("fronts"), "upper": mats.get("upper") or mats.get("fronts"),
        "tall": mats.get("fronts") or mats.get("base"), "countertop": mats.get("worktop"),
        "wallTile": mats.get("backsplash"), "carcass": mats.get("accent") or mats.get("plinth"),
    }.items() if v}
    common = {
        "plinthHeight": int(c["plinthHeight"]), "baseTop": worktop - thick, "countertop": worktop,
        "countertopThickness": thick, "baseDepth": int(c["baseDepth"]), "countertopOverhang": 20,
        "upperBottom": int(c["upperBottom"]), "upperTierSplit": int(c.get("upperSplit", upper_top)),
        "cabinetTop": cab_top, "ceiling": max(2640, cab_top + 30), "upperDepth": int(c["upperDepth"]),
        "doorThickness": 18, "doorGap": int(c.get("doorGap", 3)), "material": material,
    }
    if "upperSplit" not in c:
        _issue(issues, "no-loft-row", "không có hàng tủ nóc: upperTierSplit = cabinetTop")

    # --- góc sau-trái: chuyển phần khuất / kệ góc sang dãy trái
    out: list[dict[str, Any]] = []
    left_first: dict[str, dict[str, Any]] = {}
    for st in ("base", "upper"):
        cands = [m for m in mods if m.get("wall") == "left" and m.get("storey") == st]
        if cands:
            left_first[st] = min(cands, key=lambda m: m["x"])
    for m in mods:
        wall = m.get("wall", "back")
        st = m.get("storey", "base")
        if wall == "back" and m.get("blindWidth") and m.get("blindSide", "start") == "start" and has_left:
            blind = int(m["blindWidth"])
            upper_like = st in ("upper", "upper-top")
            lf = left_first.get("upper" if upper_like else "base")
            # phần nhìn thấy bắt đầu sau chiều sâu dãy trái (tránh chồng lấn với tủ dãy trái)
            start = max(m["x"] + blind, int(c["upperDepth"] if upper_like else c["baseDepth"]))
            end = m["x"] + m["width"]
            m["x"], m["width"] = start, end - start
            if m.get("doors"):
                tot = sum(m["doors"])
                m["doors"] = [round_int(d * m["width"] / tot) for d in m["doors"][:-1]]
                m["doors"].append(m["width"] - sum(m["doors"]))
            m.pop("blindWidth", None)
            if lf is not None and lf["x"] > 0:
                grow = lf["x"]
                lf["blind_from_back"] = grow
                lf["width"], lf["x"] = lf["width"] + grow, 0
                _issue(issues, "blind-moved-to-left-run", f"phần khuất {blind} mm ở góc sau-trái chuyển sang {lf['id']} "
                       "(KitchenSpec chỉ đặt phần khuất ở phía fromCorner)", m["id"])
            else:
                _issue(issues, "corner-gap", "góc sau-trái để trống vì dãy trái không có module cùng tầng", m["id"])
        if m.get("type") == "upper-corner-open-shelf":
            side = m.get("side", "left")
            leg_back, leg_side = int(m.get("legBack", m["x"] + m["width"])), int(m.get("legSide", c["upperDepth"]))
            if side == "right" or not has_left:
                out.append({"id": m["id"], "type": "corner-shelf", "name": m.get("name", "Kệ góc mở"), "wall": "corner",
                            "backLength": leg_back, "rightLength": leg_side, "y": m["y"], "height": m["height"],
                            "depth": m["depth"], "shelfCount": 3})
            else:
                base = {"type": "upper-open", "y": m["y"], "height": m["height"], "depth": m["depth"], "shelfCount": 3,
                        "note": f"tách từ kệ góc mở {m['id']} (góc sau-trái)"}
                out.append({**base, "id": f"{m['id']}a", "name": "Kệ góc mở (nhánh tường sau)", "wall": "back",
                            "fromCorner": back_len - leg_back, "width": leg_back})
                side_w = leg_side - int(c["upperDepth"])
                if side_w >= 50:
                    out.append({**base, "id": f"{m['id']}b", "name": "Kệ góc mở (nhánh tường trái)", "wall": "left",
                                "fromCorner": int(c["upperDepth"]), "width": side_w})
                _issue(issues, "corner-shelf-split", "KitchenSpec chỉ có kệ góc ở góc sau-phải: tách thành 2 kệ mở", m["id"])
            continue
        out.append(m)

    modules: list[dict[str, Any]] = []
    counters: dict[str, int] = {}
    for m in out:
        if m.get("type") in ("corner-shelf", "upper-open") and "fromCorner" in m or m.get("type") == "corner-shelf":
            modules.append(m)
            continue
        wall = m.get("wall", "back")
        rtype = m["type"]
        ktype = TYPE_MAP.get(rtype)
        mid = m["id"]
        if ktype is None:
            _issue(issues, "unknown-type", f"loại {rtype} không có bản tương đương, dùng base", mid)
            ktype = "base"
        from_corner = back_len - m["x"] - m["width"] if wall == "back" else m["x"]
        km: dict[str, Any] = {"id": mid, "type": ktype, "name": m.get("name", ""), "wall": wall,
                              "fromCorner": max(0, int(from_corner)), "width": int(m["width"]), "y": int(m["y"]),
                              "height": int(m["height"]), "depth": int(m["depth"])}
        if from_corner < 0:
            _issue(issues, "outside-wall", f"module vượt quá chiều dài tường sau {back_len}", mid)
        doors = list(m.get("doors", []))
        blind = int(m.get("blindWidth", 0))
        if blind and wall == "back" and m.get("blindSide") == "end":
            km["blindCorner"] = blind            # góc sau-phải = phía fromCorner của KitchenSpec
        elif blind and wall != "back":
            km["blindCorner"] = blind
        if "blind_from_back" in m:
            km["blindCorner"] = int(m["blind_from_back"])
        if doors:
            km["doors"] = doors if wall != "back" else list(reversed(doors))
        if rtype == "base-drawer" and m.get("drawers"):
            km["frontSections"] = [{"type": "drawer", "height": int(h)} for h in m["drawers"]]
        elif rtype == "base-oven":
            zone = int(c["worktopTop"]) - thick - int(c["plinthHeight"])
            rest = zone - OVEN_NICHE_MM
            km["frontSections"] = [{"type": "niche", "height": OVEN_NICHE_MM}] + (
                [{"type": "drawer", "height": rest // 2}, {"type": "drawer", "height": rest - rest // 2}] if rest > 150 else [])
        elif rtype == "base-dishwasher":
            zone = int(c["worktopTop"]) - thick - int(c["plinthHeight"])
            km["frontSections"] = [{"type": "niche", "height": zone}]
            km["note"] = "hộc máy rửa bát"
        elif rtype == "base-drawer":
            km["frontSections"] = [{"type": "drawer", "height": 240}] * 3
        if rtype == "upper-glass":
            km["doorStyle"] = "glass"
        if rtype.startswith("tall"):
            secs = m.get("sections", [])
            fridge = next((s for s in secs if s.get("appliance") == "fridge"), None)
            if fridge:
                km["niche"] = int(fridge["y"] + fridge["height"])
            door_sec = next((s for s in reversed(secs) if s.get("kind") in ("doors", "glass-doors")), None)
            if door_sec and door_sec.get("doors"):
                km["doors"] = door_sec["doors"] if wall != "back" else list(reversed(door_sec["doors"]))
            if any(s.get("kind") == "glass-doors" for s in secs):
                km["doorStyle"] = "glass"
            lost = [s["kind"] + (f":{s['appliance']}" if s.get("appliance") else "") for s in secs
                    if s is not fridge and s is not door_sec and s.get("kind") != "plinth"]
            if lost:
                _issue(issues, "tall-sections-simplified", f"tủ cao chỉ giữ hốc tủ lạnh + một nhóm cánh; bỏ: {', '.join(lost)}", mid)
        if rtype in ("upper-dish-rack", "upper-lift-up", "tall-display", "tall-oven", "base-open-shelf", "filler", "other"):
            _issue(issues, "type-approximated", f"{rtype} -> {ktype}", mid)
        note = " · ".join(x for x in (km.get("note"), m.get("note"), rtype if ktype != rtype else None) if x)
        if note:
            km["note"] = note
        prefix = "".join(ch for ch in mid if ch.isalpha())
        num = int("".join(ch for ch in mid if ch.isdigit()) or 0)
        counters[prefix] = max(counters.get(prefix, 0), num)
        modules.append(km)

    appliances = []
    for a in rec.get("appliances", []):
        item = {"id": a["id"], "name": a.get("name", ""), "type": APPLIANCE_MAP.get(a.get("kind", "other"), "other"),
                "module": a.get("module")}
        if a.get("size"):
            item["dimensions"] = a["size"]
        if a.get("note"):
            item["position"] = a["note"]
        appliances.append(item)

    room_walls = [{"id": "back", "length": back_len}]
    for w in ("left", "right"):
        if (w == "left" and has_left) or (w == "right" and has_right):
            ln = int(walls_in.get(w, {}).get("runLength") or 0)
            room_walls.append({"id": w, "length": max(ln, 600)})
    region = (rec.get("evidence") or {}).get("region")
    spec: dict[str, Any] = {
        "schemaVersion": 2, "name": name, "unit": "mm",
        "source": f"cabinet-recognizer ({rec.get('schema', '?')}); kích thước ước lượng từ ảnh",
        "origin": "Gốc ở góc trong giữa tường sau và tường phải (quy ước KitchenSpec)",
        "common": common, "room": {"wall": room_walls}, "module": modules, "appliances": appliances,
        "idCounters": dict(sorted(counters.items())),
    }
    if isinstance(region, str) and len(region) == 2 and region.isalpha():
        spec["country"] = region.upper()
    return {"spec": spec, "issues": issues}


def corner_check(spec: dict[str, Any]) -> list[str]:
    """Kiểm tra nhanh không cần kitchen: tổng cánh khớp bề rộng, fromCorner không âm."""
    bad = []
    for m in spec["module"]:
        if m.get("fromCorner", 0) < 0:
            bad.append(f"{m['id']}: fromCorner âm")
        if m.get("doors") and sum(m["doors"]) + m.get("blindCorner", 0) not in (m["width"], round_int(m["width"])):
            bad.append(f"{m['id']}: tổng cánh {sum(m['doors'])} + khuất {m.get('blindCorner', 0)} ≠ rộng {m['width']}")
    return bad
