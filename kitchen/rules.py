"""Rule engine tất định. LLM chỉ được đề xuất; mọi kết luận đúng/sai hình học đi qua đây.

Mỗi issue: {quyTac, mucDo (error|warning|info), module[], noiDung, doDuoc?, gioiHan?}
Quy tắc trong KB (bảng knowledge) có thể mang tham số máy đọc được ở metadata_json.params;
code nào có bộ kiểm tra thì dùng tham số đó, code chưa có bộ kiểm tra được liệt kê ở `chuaKiemTra`.
"""
from __future__ import annotations

from itertools import combinations

from . import appliance_models, knowledge_seed, moldings, regions, rules_kb, runs, tv_system
from .errors import require
from .spec import KitchenSpec, Module

TOL = 1.0  # mm


def _issue(code, level, mods, msg, measured=None, limit=None):
    d = {"rule": code, "severity": level, "module": list(mods), "content": msg}
    if measured is not None:
        d["measured"] = measured
    if limit is not None:
        d["limit"] = limit
    return d


def _envelopes(spec: KitchenSpec) -> list[tuple[str, tuple, tuple]]:
    """Khối bao của từng module (corner-shelf tách 2 cánh) trong toạ độ thế giới."""
    out = []
    lsau = (spec.room.length("back") if spec.room else None) or max([m.endAt for m in spec.module if m.wall == "back"] + [0]) + 600
    for m in spec.module:
        y0, y1 = m.y, m.y + m.height
        fr = runs.frame_of(spec, m)
        if fr is not None:             # angled run: the axis-aligned bounding box of its footprint (exact overlap is checked on polygons)
            (ax, az), (bx, bz) = runs.aabb(runs.module_footprint(fr, m))
            out.append((m.id, (ax, y0, az), (bx, y1, bz)))
            other = runs.frames(spec).get(m.turnsInto or "")
            if other is not None and m.rightLength:      # a corner shelf by runs: its second leg, at the start of the run it turns into
                (ax, az), (bx, bz) = runs.aabb(other.footprint(0.0, m.rightLength, 0.0, m.depth))
                out.append((m.id, (ax, y0, az), (bx, y1, bz)))
        elif m.type == "corner-shelf":
            out.append((m.id, (-require(m.backLength, f"{m.id}.backLength"), y0, 0), (0, y1, m.depth)))
            out.append((m.id, (-m.depth, y0, 0), (0, y1, require(m.rightLength, f"{m.id}.rightLength"))))
        else:                          # a wall's row or a legacy free run: its seat (an unknown wall name is read as the left wall, as before)
            seat = runs.seat_of(m, lsau) or runs.wall_seat("left", lsau)
            assert seat is not None
            mn, mx = seat.box(m.fromCorner, m.endAt, 0, m.depth, y0, y1)
            out.append((m.id, mn, mx))
    return out


def _overlap(a, b) -> float:
    v = 1.0
    for i in range(3):
        v *= max(0.0, min(a[1][i], b[1][i]) - max(a[0][i], b[0][i]) - TOL)
    return v


def check_geometry(spec: KitchenSpec) -> list[dict]:
    c = spec.common
    issues = []
    env = _envelopes(spec)
    angled = {m.id: runs.module_footprint(fr, m) for m in spec.module if (fr := runs.frame_of(spec, m)) is not None and not m.turnsInto}   # two-legged: by its boxes
    for (id, mn, mx), (mb, nn, nx) in combinations(env, 2):
        if id == mb:
            continue
        if id in angled or mb in angled:       # a box of an angled run: exact polygon test (bounding boxes of rotated rows overlap far too often)
            if min(mx[1], nx[1]) - max(mn[1], nn[1]) <= TOL:
                continue
            pa = angled.get(id) or [(mn[0], mn[2]), (mx[0], mn[2]), (mx[0], mx[2]), (mn[0], mx[2])]
            pb = angled.get(mb) or [(nn[0], nn[2]), (nx[0], nn[2]), (nx[0], nx[2]), (nn[0], nx[2])]
            if runs.penetration(pa, pb) > TOL:
                issues.append(_issue("GEO-COLLISION", "error", [id, mb], f"{id} và {mb} chồng lên nhau"))
        elif _overlap((mn, mx), (nn, nx)) > 0:
            issues.append(_issue("GEO-COLLISION", "error", [id, mb], f"{id} và {mb} chồng lên nhau"))
    tier_level = {"base": c.baseTop, "upper": c.upperTierSplit, "loft": c.cabinetTop, "tall": c.cabinetTop, "corner": None}
    tv = tv_system.tv_modules(spec)          # a TV unit keeps its own heights (low console, floating shelf)
    for m in spec.module:
        top = m.y + m.height
        lim = None if m.id in tv else tier_level[m.storey]
        if lim is not None and abs(top - lim) > TOL:
            issues.append(_issue("GEO-HEIGHTS", "warning", [m.id], f"{m.id}: đỉnh {top:g} lệch cao độ tầng {m.storey} ({lim:g})", top, lim))
        if m.storey == "upper" and m.type != "upper-hood" and m.id not in tv and abs(m.y - c.upperBottom) > TOL:
            issues.append(_issue("GEO-HEIGHTS", "warning", [m.id], f"{m.id}: đáy {m.y:g} khác dayTuTren {c.upperBottom:g}", m.y, c.upperBottom))
        if m.doors:
            total = sum(m.doors) + m.blindCorner + m.endPanel
            if abs(total - m.width) > TOL:
                issues.append(_issue("GEO-DOOR", "warning", [m.id],
                                     f"{m.id}: tổng cánh + góc khuất + tấm hông = {total:g} ≠ rộng {m.width:g}", total, m.width))
        if spec.room and m.wall in ("back", "right", "left"):
            L = spec.room.length(m.wall)
            if L and m.endAt > L + TOL:
                issues.append(_issue("GEO-WALL", "error", [m.id], f"{m.id} vượt chiều dài tường {m.wall} ({m.endAt:g} > {L:g})", m.endAt, L))
    if spec.room and not isinstance(getattr(spec, "floorplan", None), dict):      # explicit runs against the drawn room (an imported plan has its own walls)
        back = spec.room.length("back")
        for m in spec.module:
            fr = runs.frame_of(spec, m)
            if fr is None:
                continue
            pts = runs.module_footprint(fr, m)
            over = max(-x - back for x, _ in pts) if back else 0.0        # along the back wall; how deep the room is, the walls' lengths do not say
            over = max(over, max(x for x, _ in pts), max(-z for _, z in pts))
            if over > TOL:
                issues.append(_issue("GEO-WALL", "error", [m.id], f"{m.id} vượt ra ngoài phòng {over:g} mm (dãy {m.run})", over, 0))
    joints = {(j.a, j.b) for j in runs.corner_joints(spec) if j.square}
    for m in spec.module:
        if m.turnsInto and (m.run, m.turnsInto) not in joints:
            issues.append(_issue("GEO-CORNER", "warning", [m.id], f"{m.id}: kệ góc nối dãy {m.run} với dãy {m.turnsInto}, nhưng hai dãy không còn gặp nhau ở góc vuông"))
    if c.cabinetTop > c.ceiling + TOL:
        issues.append(_issue("GEO-CEILING", "error", [], f"Đỉnh tủ {c.cabinetTop:g} cao hơn trần {c.ceiling:g}", c.cabinetTop, c.ceiling))
    if abs(c.countertop - (c.baseTop + c.countertopThickness)) > TOL:
        issues.append(_issue("GEO-COUNTERTOP", "warning", [], f"matDa {c.countertop:g} ≠ deMatDa + dayMatDa = {c.baseTop + c.countertopThickness:g}"))
    # khe hở giữa các module liền kề trong cùng tường/tầng
    for wall in ("back", "right", "left"):
        for storey in ("base", "upper", "loft"):
            ms = sorted((m for m in spec.module if m.wall == wall and m.storey in (storey, "tall")), key=lambda m: m.fromCorner)
            for a, b in zip(ms, ms[1:]):
                if a.storey == b.storey == "tall":
                    continue
                gap = b.fromCorner - a.endAt
                if gap > TOL:
                    issues.append(_issue("GEO-GAPS", "info", [a.id, b.id], f"Khe hở {gap:g} mm giữa {a.id} và {b.id} (tường {wall})", gap))
    for r in spec.runs:                # gaps inside an explicit run, per storey
        for storey in ("base", "upper", "loft"):
            ms = sorted((m for m in spec.module if m.run == r.id and m.storey in (storey, "tall")), key=lambda m: m.fromCorner)
            for a, b in zip(ms, ms[1:]):
                gap = b.fromCorner - a.endAt
                if gap > TOL and not (a.storey == b.storey == "tall"):
                    issues.append(_issue("GEO-GAPS", "info", [a.id, b.id], f"Khe hở {gap:g} mm giữa {a.id} và {b.id} (dãy {r.id})", gap))
    # thiết bị lọt module
    for tb in spec.appliances:
        k = tb.numeric_dimensions()
        if not tb.module:
            continue
        try:
            m = spec.find(tb.module)
        except KeyError:
            issues.append(_issue("TB-MODULE", "error", [], f"{tb.id}: module '{tb.module}' không tồn tại"))
            continue
        if tb.type == "fridge" and len(k) >= 3:
            w, h, d = k[:3]
            inner = m.width - 2 * c.doorThickness
            if w > inner + TOL or (m.niche and h > m.niche + TOL) or d > m.depth + TOL:
                issues.append(_issue("APPLIANCE-NICHE", "error", [m.id, tb.id], f"{tb.id} {w:g}×{h:g}×{d:g} không lọt hốc {m.id}"))
        if tb.type == "oven" and len(k) >= 2:
            w, h = k[:2]
            niche = next((t.height for t in m.frontSections if t.type == "niche"), None)
            if w > m.width - 2 * c.doorThickness + TOL or (niche and h > niche - 2 * c.doorThickness + TOL):
                issues.append(_issue("APPLIANCE-NICHE", "error", [m.id, tb.id], f"{tb.id} không lọt hộc {m.id}"))
    return issues


def default_rows() -> list[dict]:
    """Kho nền dùng khi không có DB (test, hàm thuần)."""
    return [{"id": i + 1, **k} for i, k in enumerate(knowledge_seed.KNOWLEDGE) if k["kind"] in ("rule", "standard")]


def validate(spec: KitchenSpec, kb_rules: list[dict] | None = None, country: str | None = None,
             region: str | None = None) -> dict:
    """kb_rules: các dòng tri thức kind rule/standard đang active (đã parse metadata); None -> kho nền.
    Quốc gia/khu vực: tham số > spec.quocGia/spec.khuVuc > không chỉ định (ưu tiên mục toàn cầu, rồi nguồn mạnh nhất)."""
    qg, kv = regions.normalize(country or spec.country, region or spec.region)
    rows = default_rows() if kb_rules is None else kb_rules
    sel = rules_kb.select(rows, qg, kv)
    kitchen = tv_system.kitchen_only(spec)       # kitchen rules (worktop, depths, appliances...) do not look at TV units
    issues = check_geometry(spec) + rules_kb.check(kitchen, sel) + moldings.check(spec) + appliance_models.check(kitchen)
    if not (qg or kv):
        issues.append({"rule": "VUNG", "severity": "info", "module": [], "content": "Chưa chọn quốc gia/khu vực (spec.quocGia): "
                       "chỉ tiêu chuẩn toàn cầu được áp, tiêu chuẩn của các nước chỉ để tham khảo"})
    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order[i["severity"]])
    dem = {k: sum(i["severity"] == k for i in issues) for k in order}
    dung = {t: f"{v['code']} ({v['zone']}, {v['priority']})" for t, v in sel.items()}
    chua = [r["code"] for r in rows if not (r.get("metadata") or {}).get("validation")]
    return {"valid": dem["error"] == 0, "dem": dem, "issues": issues, "country": qg, "region": kv,
            "appliedRules": dung, "unchecked": chua}
