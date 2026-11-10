"""cabinet-recognizer 0.1/0.2 -> hợp đồng theo DÃY ``recognized-runs/1`` (lõi thuần, JSON vào - JSON ra).

Mỗi dãy tủ thẳng là một đường line; tủ được đo dọc dãy bằng ``s``:

    s = khoảng cách từ ĐẦU TRÁI của dãy, khi đứng trước cánh tủ nhìn vào (s tăng về bên phải người nhìn).

Nhờ vậy bên nhận không cần biết "tường" hay gốc toạ độ nào: đặt line ở đâu thì dãy đứng ở đó.

    {"schema": "recognized-runs/1", "unit": "mm", "layout": "straight|l-shape|u-shape",
     "runs":   [{"id": "left|back|right", "length": mm, "end": "open|wall|tall", "modules": [Module...]}],   # theo thứ tự nối: left, back, right
     "joints": [{"a": "left", "b": "back", "angle": 90}],   # CUỐI dãy a (s = length) gặp ĐẦU dãy b (s = 0) ở góc trong của phòng
     "common": {...mức cao độ và vật liệu theo tên trường KitchenSpec...},
     "issues": [{"code", "message", "module"?}]}             # thông tin bị xấp xỉ khi đổi loại tủ

    Module: {"id", "type" (loại KitchenSpec), "sourceType" (loại gốc của bộ nhận diện), "name", "storey", "s", "width", "y", "height", "depth",
             "confidence", "doors"? (trái -> phải), "frontSections"? (trên -> xuống), "blindCorner"? (phần khuất ở phía s nhỏ), "niche"?,
             "doorStyle"?, "shelfCount"?, "appliances"? [{"type", "name", "note"?}], "note"?}

Quy đổi từ kết quả nhận diện (x đo từ góc trong; dãy sau đo từ trái):
- dãy sau:  s = x                       (góc trái ở s = 0, góc phải ở s = length)
- dãy trái: s = length - x - rộng       (cuối dãy chạm góc), thứ tự cánh đảo lại
- dãy phải: s = x                       (đầu dãy chạm góc)
Phần khuất của tủ góc chỉ ghi được ở phía s nhỏ. Khi nó nằm ở CUỐI một dãy (dãy sau ở góc phải, dãy trái ở góc), tủ đó co lại còn phần
nhìn thấy và ô góc chuyển cho tủ ĐẦU của dãy kề (cùng tầng), như thợ vẫn dựng một trong hai tủ chạy hết vào góc.
"""
from __future__ import annotations

from typing import Any

from .numeric import round_int
from .to_kitchen import APPLIANCE_MAP, TYPE_MAP, oven_niche

SCHEMA = "recognized-runs/1"
ORDER = ("left", "back", "right")
APPROXIMATED = ("upper-dish-rack", "upper-lift-up", "tall-display", "tall-oven", "base-open-shelf", "filler", "other")
MIN_LEG = 150      # nhánh kệ góc ngắn hơn mức này thì bỏ (bên nhận không nhận tủ hẹp hơn)


def _issue(issues: list[dict[str, Any]], code: str, message: str, module: str | None = None) -> None:
    item: dict[str, Any] = {"code": code, "message": message}
    if module:
        item["module"] = module
    issues.append(item)


def _band(storey: str) -> str:
    """Tầng dùng để tìm tủ kề ở góc: tủ dưới và tủ cao cùng đứng trên sàn; tủ trên và tủ nóc treo riêng từng tầng."""
    return "floor" if storey in ("base", "tall") else storey


def _fronts(m: dict[str, Any], c: dict[str, Any], cab_top: int, issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Mặt trước của một tủ theo cách KitchenSpec ghi: cánh, ngăn kéo, hốc thiết bị, kiểu cánh."""
    rtype, mid = m["type"], m["id"]
    out: dict[str, Any] = {}
    zone = int(c["worktopTop"]) - int(c["worktopThickness"]) - int(c["plinthHeight"])
    if m.get("doors"):
        out["doors"] = [int(d) for d in m["doors"]]
    if rtype == "base-drawer":
        heights = m.get("drawers") or [zone // 3, zone // 3, zone - 2 * (zone // 3)]
        out["frontSections"] = [{"type": "drawer", "height": int(h)} for h in heights]
    elif rtype == "base-oven":
        rest = zone - oven_niche(zone)
        out["frontSections"] = [{"type": "niche", "height": oven_niche(zone)}] + (
            [{"type": "drawer", "height": rest // 2}, {"type": "drawer", "height": rest - rest // 2}] if rest > 150 else [])
    elif rtype == "base-dishwasher":
        out["frontSections"] = [{"type": "niche", "height": zone}]
        out["note"] = "hộc máy rửa bát"
    if rtype in ("upper-glass", "tall-display"):
        out["doorStyle"] = "glass"
    if rtype == "upper-open-shelf":
        out["shelfCount"] = 3
    if rtype.startswith("tall"):
        secs = m.get("sections", [])
        fridge = next((s for s in secs if s.get("appliance") == "fridge"), None)
        if fridge:
            out["niche"] = int(fridge["y"] + fridge["height"])
        door_sec = next((s for s in reversed(secs) if s.get("kind") in ("doors", "glass-doors")), None)
        if door_sec and door_sec.get("doors"):
            out["doors"] = [int(d) for d in door_sec["doors"]]
        if any(s.get("kind") == "glass-doors" for s in secs):
            out["doorStyle"] = "glass"
        lost = [s["kind"] + (f":{s['appliance']}" if s.get("appliance") else "") for s in secs
                if s is not fridge and s is not door_sec and s.get("kind") != "plinth"]
        if lost:
            _issue(issues, "tall-sections-simplified", f"tủ cao chỉ giữ hốc tủ lạnh + một nhóm cánh; bỏ: {', '.join(lost)}", mid)
    return out


def _common(c: dict[str, Any]) -> dict[str, Any]:
    worktop, thick = int(c["worktopTop"]), int(c["worktopThickness"])
    upper_top = int(c.get("upperTop", c.get("upperBottom", 1500) + 750))
    cab_top = max(upper_top, int(c.get("tallTop", upper_top)))
    mats = c.get("materials", {})
    material = {k: v for k, v in {
        "base": mats.get("base") or mats.get("fronts"), "upper": mats.get("upper") or mats.get("fronts"),
        "tall": mats.get("fronts") or mats.get("base"), "countertop": mats.get("worktop"),
        "wallTile": mats.get("backsplash"), "carcass": mats.get("accent") or mats.get("plinth"),
    }.items() if v}
    return {"plinthHeight": int(c["plinthHeight"]), "baseTop": worktop - thick, "countertop": worktop, "countertopThickness": thick,
            "baseDepth": int(c["baseDepth"]), "upperBottom": int(c["upperBottom"]), "upperTierSplit": int(c.get("upperSplit", upper_top)),
            "cabinetTop": cab_top, "upperDepth": int(c["upperDepth"]), "material": material}


def _scale_doors(doors: list[int], width: int) -> list[int]:
    total = sum(doors)
    out = [round_int(d * width / total) for d in doors[:-1]]
    return [*out, width - sum(out)]


def to_runs(rec: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    c = rec["common"]
    common = _common(c)
    walls_in = rec.get("walls") or {}
    src = [dict(m) for m in rec["modules"]]
    for m in src:
        m.setdefault("wall", "back")
    present = [w for w in ORDER if any(m["wall"] == w for m in src)]

    def extent(wall: str) -> int:
        return max((int(m["x"] + m["width"]) for m in src if m["wall"] == wall), default=0)

    length = {w: max(int(walls_in.get(w, {}).get("runLength") or (c.get("runLength") if w == "back" else 0) or 0), extent(w)) for w in present}
    appliances_of: dict[str, list[dict[str, Any]]] = {}
    for a in rec.get("appliances", []):
        item = {"type": APPLIANCE_MAP.get(a.get("kind", "other"), "other"), "name": a.get("name", "")}
        if a.get("note"):
            item["note"] = a["note"]
        if isinstance(a.get("module"), str):
            appliances_of.setdefault(a["module"], []).append(item)

    # --- từng tủ sang khung dãy (s từ đầu trái, nhìn từ trước cánh)
    runs: dict[str, list[dict[str, Any]]] = {w: [] for w in present}
    end_blind: list[tuple[str, dict[str, Any], int]] = []        # (dãy, tủ, phần khuất) khi phần khuất nằm ở CUỐI dãy
    for m in src:
        wall, rtype, mid = m["wall"], m["type"], m["id"]
        L = length[wall]
        x, width = int(m["x"]), int(m["width"])
        mirrored = wall == "left"
        if rtype == "upper-corner-open-shelf":
            side = m.get("side", "left")
            leg = {"type": "upper-open", "sourceType": rtype, "storey": "upper", "y": int(m["y"]), "height": int(m["height"]),
                   "depth": int(m["depth"]), "shelfCount": 3, "confidence": float(m.get("confidence", 0.5))}
            runs[wall].append({**leg, "id": f"{mid}a", "name": "Kệ góc mở (nhánh dãy chính)", "s": x, "width": width})
            leg_side, ud = int(m.get("legSide", 0)), int(c["upperDepth"])
            if side in runs and leg_side - ud >= MIN_LEG:
                s = length[side] - leg_side if side == "left" else ud
                runs[side].append({**leg, "id": f"{mid}b", "name": "Kệ góc mở (nhánh dãy bên)", "s": s, "width": leg_side - ud})
            _issue(issues, "corner-shelf-split", "kệ góc mở chữ L tách thành kệ mở trên từng dãy", mid)
            continue
        ktype = TYPE_MAP.get(rtype)
        if ktype is None:
            _issue(issues, "unknown-type", f"loại {rtype} không có bản tương đương, dùng base", mid)
            ktype = "base"
        out: dict[str, Any] = {"id": mid, "type": ktype, "sourceType": rtype, "name": m.get("name", ""), "storey": m.get("storey", "base"),
                               "s": L - x - width if mirrored else x, "width": width, "y": int(m["y"]), "height": int(m["height"]),
                               "depth": int(m["depth"]), "confidence": float(m.get("confidence", 0.5))}
        if rtype.startswith("tall") and not m.get("sections") and out["height"] < 1500:
            out["y"], out["height"] = 0, common["cabinetTop"]
        fronts = _fronts(m, c, common["cabinetTop"], issues)
        if mirrored and fronts.get("doors"):
            fronts["doors"] = list(reversed(fronts["doors"]))
        out.update(fronts)
        blind = int(m.get("blindWidth", 0))
        if blind:
            at_corner_low_s = (wall == "back" and m.get("blindSide", "start") == "start") or wall == "right"
            if at_corner_low_s:
                out["blindCorner"] = blind
            else:
                end_blind.append((wall, out, blind))
        devices = [d for d in appliances_of.get(mid, []) if not (ktype == "tall-fridge" and d["type"] == "fridge")]   # bên nhận tự đặt tủ lạnh vào hốc
        if devices:
            out["appliances"] = devices
        if rtype in APPROXIMATED:
            _issue(issues, "type-approximated", f"{rtype} -> {ktype}", mid)
        note = " · ".join(t for t in (out.get("note"), m.get("note"), rtype if ktype != rtype else None) if t)
        if note:
            out["note"] = note
        runs[wall].append(out)

    # --- phần khuất ở CUỐI dãy: chuyển ô góc cho tủ đầu của dãy kề
    after = {"left": "back", "back": "right"}
    for wall, mod, blind in end_blind:
        nxt = after.get(wall)
        visible = max(mod["width"] - blind, 0)
        if visible < MIN_LEG:
            if mod.get("doors"):
                mod["doors"] = [mod["width"]]
            _issue(issues, "corner-gap", "phần nhìn thấy của tủ góc quá hẹp, giữ nguyên tủ không có phần khuất", mod["id"])
            continue
        if mod.get("doors"):
            mod["doors"] = _scale_doors(mod["doors"], visible)
        mod["width"] = visible
        first = min((n for n in runs.get(nxt or "", []) if _band(n["storey"]) == _band(mod["storey"])), key=lambda n: n["s"], default=None)
        if first is not None and 0 < first["s"] <= 1000 and "blindCorner" not in first and not first["type"].startswith("tall"):
            grow = first["s"]
            first["s"], first["width"], first["blindCorner"] = 0, first["width"] + grow, grow
            _issue(issues, "blind-moved-to-next-run", f"ô góc {blind} mm chuyển sang {first['id']} của dãy {nxt}", mod["id"])
        else:
            _issue(issues, "corner-gap", f"ô góc {blind} mm để trống: dãy kề không có tủ cùng tầng sát góc", mod["id"])

    for mods in runs.values():
        mods.sort(key=lambda n: (n["y"], n["s"]))
    ends = {w: (walls_in.get(w, {}).get("end") or (rec.get("rightEnd") if w == "back" else None) or "open") for w in present}
    joints = [{"a": a, "b": b, "angle": 90} for a, b in (("left", "back"), ("back", "right")) if a in runs and b in runs]
    return {"schema": SCHEMA, "unit": "mm", "layout": rec.get("layout", "straight"),
            "runs": [{"id": w, "length": length[w], "end": ends[w], "modules": runs[w]} for w in present],
            "joints": joints, "common": common, "issues": issues}


def check_runs(doc: dict[str, Any]) -> list[str]:
    """Kiểm tra nhanh một tài liệu recognized-runs: tủ nằm trong dãy, không chồng nhau trong một tầng, cánh khớp bề rộng."""
    bad: list[str] = []
    for run in doc["runs"]:
        rows: dict[tuple[int, str], list[tuple[int, int, str]]] = {}
        for m in run["modules"]:
            if m["s"] < 0 or m["s"] + m["width"] > run["length"] + 1:
                bad.append(f"{run['id']}/{m['id']}: nằm ngoài dãy ({m['s']}..{m['s'] + m['width']} / {run['length']})")
            if m.get("doors") and abs(sum(m["doors"]) + m.get("blindCorner", 0) - m["width"]) > 1:
                bad.append(f"{run['id']}/{m['id']}: cánh {sum(m['doors'])} + khuất {m.get('blindCorner', 0)} ≠ rộng {m['width']}")
            rows.setdefault((m["y"], "tall" if m["type"].startswith("tall") else "row"), []).append((m["s"], m["s"] + m["width"], m["id"]))
        for spans in rows.values():
            spans.sort()
            for a, b in zip(spans, spans[1:]):
                if a[1] > b[0] + 1:
                    bad.append(f"{run['id']}: {a[2]} đè {b[2]}")
    return bad
