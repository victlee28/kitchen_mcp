"""Ảnh phối cảnh -> spec nhiều tường (chữ I xiên, L, U). Lõi thuần, xác định.

Các bước (mọi số học ở đây, AI chỉ chọn đường và vật chuẩn):
1. Điểm tụ dọc tường sau (từ các đường của dãy sau) và dọc tường bên (từ dãy trái/phải).
2. Tiêu cự: từ hai điểm tụ vuông góc; nếu một điểm ở vô cực (ảnh chính diện chữ U) thì dò tiêu cự
   sao cho các vật chuẩn trên các tường khác nhau cho cùng tỉ lệ; cuối cùng mới dùng góc nhìn AI ước.
3. Mặt trước mỗi dãy: chiếu đường chân tủ (chạm sàn) xuống sàn, cộng độ lùi chân tủ.
   Mặt tủ trên = tường + chiều sâu tủ trên.
4. Tỉ lệ mm: từ vật chuẩn bề rộng (máy rửa bát 600, tủ lạnh...). Hệ số đứng từ vật chuẩn chiều cao.
5. Vị trí module dọc tường tính từ góc trong; module góc kéo về 0 (phần khuất = blindWidth).
"""
from __future__ import annotations

import math
from typing import Any

from .contract import Line
from .contract_persp import PolicyP, RunSegmentation, Scene
from .errors import RecognizerError, invalid
from .labels_vi import APPLIANCE_NAMES, module_name
from .numeric import round_half_away, round_int, snap
from .persp import Camera, VanishingPoint, build_camera, focal_from_vps, line_y, vanishing_point

UPPER_KEYS = ("upperTop", "upperSplit", "upperBottom")
ID_PREFIX = {"base": "TD", "upper": "TT", "upper-top": "TN", "tall": "TC", "corner": "KG"}
BAND_KEYS = {"base": ("worktopFront", "frontsBottom"), "upper": ("upperSplit|upperTop", "upperBottom"),
             "upper-top": ("upperTop", "upperSplit")}


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        raise invalid("empty", "không có giá trị")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def band_lines(lines: dict[str, list[float]], storey: str) -> tuple[str, str] | None:
    top_key, bot_key = BAND_KEYS[storey]
    if "|" in top_key:
        a, b = top_key.split("|")
        top_key = a if a in lines else b
    if top_key not in lines or bot_key not in lines:
        return None
    return top_key, bot_key


def _line(lines: dict[str, list[float]], key: str) -> tuple[float, float]:
    return (lines[key][0], lines[key][1])


class Geometry:
    """Camera + mặt phẳng các dãy (đơn vị: chiều cao camera = 1)."""

    def __init__(self, cam: Camera, meas: dict[str, Any], scene: Scene, policy: PolicyP) -> None:
        self.cam, self.meas, self.scene, self.policy = cam, meas, scene, policy
        self.walls = [r["wall"] for r in scene["runs"]]
        self.floor_front: dict[str, float] = {}
        for wall in self.walls:
            rm = meas["runs"][wall]
            pb = _line(rm["lines"], "plinthBottom")
            x0, x1 = rm["lines"]["plinthBottom"][4], rm["lines"]["plinthBottom"][5]
            vals = []
            for i in range(9):
                u = x0 + (x1 - x0) * (i + 0.5) / 9
                p = cam.on_floor(u, line_y(pb, u))
                vals.append(p[2] if wall == "back" else p[0])
            self.floor_front[wall] = _median(vals)
        self.scale = 1500.0  # mm / đơn vị (đoán ban đầu: camera cao ~1,5 m; tinh lại từ vật chuẩn)

    def mm(self, value_mm: float) -> float:
        return value_mm / self.scale

    def front(self, wall: str) -> float:
        r = self.mm(self.policy["plinthRecessMm"])
        f = self.floor_front[wall]
        return f + r if wall in ("back", "left") else f - r

    def wall_pos(self, wall: str) -> float:
        d = self.mm(self.policy["baseDepthMm"])
        f = self.front(wall)
        return f - d if wall in ("back", "left") else f + d

    def plane(self, wall: str, storey: str) -> float:
        if storey in ("upper", "upper-top"):
            du = self.mm(self.policy["upperDepthMm"])
            w = self.wall_pos(wall)
            return w + du if wall in ("back", "left") else w - du
        if storey == "tall":
            dt = self.mm(self.policy["tallDepthMm"])
            w = self.wall_pos(wall)
            return w + dt if wall in ("back", "left") else w - dt
        return self.front(wall)

    def point(self, wall: str, storey: str, u: float, v: float) -> tuple[float, float, float]:
        axis = "z" if wall == "back" else "x"
        return self.cam.on_plane(u, v, axis, self.plane(wall, storey))

    def along(self, wall: str, p: tuple[float, float, float]) -> float:
        """Khoảng cách (đơn vị) dọc tường tính từ góc trong."""
        if wall == "back":
            if "left" in self.walls:
                return p[0] - self.wall_pos("left")
            return p[0]
        return p[2] - self.wall_pos("back")

    def height_mm(self, p: tuple[float, float, float], kv: float) -> float:
        return (p[1] + 1.0) * self.scale * kv


def _band_mid(meas: dict[str, Any], wall: str, storey: str, u: float) -> float:
    lines = meas["runs"][wall]["lines"]
    keys = band_lines(lines, storey)
    if keys is None:
        raise invalid("missing-band", f"{wall}.{storey}: thiếu đường giới hạn dải")
    return (line_y(_line(lines, keys[0]), u) + line_y(_line(lines, keys[1]), u)) / 2


def _cand_pos(meas: dict[str, Any], wall: str, storey: str) -> dict[str, int]:
    return {ln["id"]: ln["pos"] for ln in meas["runs"][wall]["cand"].get(storey, [])}


def _along_of(geo: Geometry, meas: dict[str, Any], wall: str, storey: str, u: float) -> float:
    plane_storey = storey
    return geo.along(wall, geo.point(wall, plane_storey, u, _band_mid(meas, wall, storey, u)))


def _scale_estimates(geo: Geometry, meas: dict[str, Any], runs: list[RunSegmentation]) -> list[dict[str, Any]]:
    out = []
    for rs in runs:
        for ref in rs["widthRefs"]:
            pos = _cand_pos(meas, rs["wall"], ref["storey"])
            a = _along_of(geo, meas, rs["wall"], ref["storey"], pos[ref["start"]])
            b = _along_of(geo, meas, rs["wall"], ref["storey"], pos[ref["end"]])
            out.append({"wall": rs["wall"], "what": ref["what"], "mm": ref["mm"],
                        "mmPerUnit": ref["mm"] / abs(b - a)})
    return out


VP_MAX_RESIDUAL_PX = 2.5
F_MIN, F_MAX = 0.35, 4.0  # tiêu cự hợp lý theo bề rộng ảnh (góc nhìn ngang ~14°..110°)
VP_MIN_SPAN = 0.15  # đường dùng tìm điểm tụ phải dài ít nhất 15% bề rộng ảnh


def _vp_lines(lines: list[list[float]], width: float) -> list[tuple[float, float]]:
    good = [(ln[0], ln[1]) for ln in lines if ln[2] <= VP_MAX_RESIDUAL_PX and ln[5] - ln[4] >= VP_MIN_SPAN * width]
    return good if len(good) >= 2 else [(ln[0], ln[1]) for ln in lines]


def _robust_vp(lines: list[tuple[float, float]]) -> VanishingPoint:
    """Bỏ dần đường lệch nhất (theo góc tới điểm tụ) cho tới khi nhất quán."""
    cur = list(lines)
    while True:
        vp = vanishing_point(cur)
        if not vp.finite or len(cur) <= 2:
            return vp
        errs = []
        for m, q in cur:
            # góc giữa đường và hướng từ điểm tụ tới điểm trên đường ở hoành độ cách điểm tụ 1000 px
            u = vp.u + (1000.0 if vp.u < 0 else -1000.0)
            vline = m * u + q
            ang = math.atan2(vline - vp.v, u - vp.u) - math.atan(m)
            errs.append(abs(math.atan2(math.sin(ang), math.cos(ang))))
        worst = max(range(len(cur)), key=lambda i: errs[i])
        med = sorted(errs)[len(errs) // 2]
        if errs[worst] <= max(0.004, 3 * med):
            return vp
        cur.pop(worst)


def _camera(scene: Scene, meas: dict[str, Any], runs: list[RunSegmentation], policy: PolicyP,
            warnings: list[dict[str, Any]]) -> tuple[Camera, dict[str, Any]]:
    w, h = meas["imageSize"]
    cx, cy = w / 2, h / 2
    back = _vp_lines([ln for ln in meas["runs"]["back"]["lines"].values()], w)
    side = _vp_lines([ln for wall in ("left", "right") if wall in meas["runs"]
                      for ln in meas["runs"][wall]["lines"].values()], w)
    vb = _robust_vp(back)
    vs: VanishingPoint | None = _robust_vp(side) if len(side) >= 2 else None
    info: dict[str, Any] = {"vpBack": [round_half_away(vb.u, 0.1), round_half_away(vb.v, 0.1)] if vb.finite else "infinite",
                            "vpSide": ([round_half_away(vs.u, 0.1), round_half_away(vs.v, 0.1)]
                                       if vs is not None and vs.finite else None)}
    f = focal_from_vps(vb, vs, cx, cy) if vs is not None else None
    source = "vanishing-points"
    if f is not None and not (F_MIN * w <= f <= F_MAX * w):
        # tiêu cự vô lý: dãy sau gần như chính diện, điểm tụ dọc tường sau coi như ở vô cực
        warnings.append({"code": "back-vp-treated-infinite", "focalFromVp": round_half_away(f, 0.1)})
        f = None
        vb = VanishingPoint(False, 0.0, 0.0, _median([m for m, _ in back]), 0.0)
        info["vpBack"] = "infinite"
    if f is None:
        f_fov = (w / 2) / math.tan(math.radians(policy["fovDeg"]) / 2)
        walls_with_refs = {rs["wall"] for rs in runs if rs["widthRefs"]}
        if len(walls_with_refs) >= 2 and vs is not None:
            best: tuple[float, float] | None = None
            for i in range(161):
                fi = w * F_MIN * ((F_MAX / F_MIN) ** (i / 160))  # dò theo thang log
                try:
                    cam_i = build_camera(vb, vs, fi, cx, cy)
                    geo_i = Geometry(cam_i, meas, scene, policy)
                    est = [math.log(e["mmPerUnit"]) for e in _scale_estimates(geo_i, meas, runs)]
                except (RecognizerError, ZeroDivisionError):  # tiêu cự thử không hợp lệ thì bỏ qua
                    continue
                mean = sum(est) / len(est)
                var = sum((x - mean) ** 2 for x in est) / len(est)
                if best is None or var < best[0]:
                    best = (var, fi)
            if best is not None:
                f, source = best[1], "reference-consistency"
        if f is None:
            f, source = f_fov, "fov-assumption"
            warnings.append({"code": "focal-from-fov", "fovDeg": policy["fovDeg"]})
    info.update({"focalPx": round_half_away(f, 0.1), "focalSource": source})
    return build_camera(vb, vs, f, cx, cy), info


def build_spec_p(scene: Scene, meas: dict[str, Any], runs: list[RunSegmentation], policy: PolicyP,
                 height_refs_px: list[dict[str, Any]]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    cam, cam_info = _camera(scene, meas, runs, policy, warnings)
    geo = Geometry(cam, meas, scene, policy)

    # --- tỉ lệ (2 vòng: vòng 2 có độ lùi chân tủ theo mm)
    estimates: list[dict[str, Any]] = []
    for _ in range(4):
        estimates = _scale_estimates(geo, meas, runs)
        if estimates:
            geo.scale = _median([e["mmPerUnit"] for e in estimates])
        else:
            wt_units = []
            for wall in geo.walls:
                lines = meas["runs"][wall]["lines"]
                u = (lines["worktopFront"][4] + lines["worktopFront"][5]) / 2
                p = geo.point(wall, "base", u, line_y(_line(lines, "worktopFront"), u))
                wt_units.append(p[1] + 1.0)
            target = _median([float(x) for x in policy["worktopOptionsMm"]])
            geo.scale = target / _median(wt_units)
    if not estimates:
        warnings.append({"code": "scale-from-worktop-standard"})
    else:
        spread = max(e["mmPerUnit"] for e in estimates) / min(e["mmPerUnit"] for e in estimates) - 1
        if spread > 0.05:
            warnings.append({"code": "scale-references-disagree", "spread": round_half_away(spread, 0.001)})

    # --- hệ số đứng
    kv_list = []
    for r in height_refs_px:
        wall = r["wall"]
        top = geo.point(wall, r["plane"], r["top"][0], r["top"][1])
        bot = geo.point(wall, r["plane"], r["bottom"][0], r["bottom"][1])
        dy = (top[1] - bot[1]) * geo.scale
        if dy > 0:
            kv_list.append(r["mm"] / dy)
    kv = 1.0
    if policy["verticalCorrection"] == "auto" and kv_list:
        kv = _median(kv_list)
        if not 0.85 <= kv <= 1.15:
            warnings.append({"code": "vertical-correction-clamped", "raw": round_half_away(kv, 0.001)})
            kv = min(1.15, max(0.85, kv))

    # --- chiều cao từ các đường ngang (đo ở giữa mỗi dãy, lấy trung vị giữa các dãy)
    per_key: dict[str, list[float]] = {}
    per_run: dict[str, dict[str, int]] = {}
    for wall in geo.walls:
        lines = meas["runs"][wall]["lines"]
        per_run[wall] = {}
        for key, ln in lines.items():
            storey = "upper" if key in UPPER_KEYS else "base"
            u = (ln[4] + ln[5]) / 2  # đo ở giữa đoạn đường bám được
            hv = geo.height_mm(geo.point(wall, storey, u, line_y((ln[0], ln[1]), u)), kv)
            per_key.setdefault(key, []).append(hv)
            per_run[wall][key] = round_int(hv)
    hm = {k: _median(v) for k, v in per_key.items()}
    for k, vals in per_key.items():
        if len(vals) > 1 and max(vals) - min(vals) > 60:
            warnings.append({"code": "height-differs-between-walls", "line": k,
                             "values": [round_int(x) for x in vals]})

    tol = policy["snapToleranceMm"]
    hr = policy["heightRoundingMm"]
    worktop, ok_w = snap(hm["worktopFront"], policy["worktopOptionsMm"], tol)
    thick = policy["worktopThicknessMm"]
    plinth = round_int(hm["frontsBottom"], 10)
    gap, ok_g = snap(hm["upperBottom"] - worktop, policy["gapOptionsMm"], tol)
    upper_bottom = worktop + gap
    upper_top_meas = hm.get("upperTop", hm["upperBottom"] + 750)
    if "upperSplit" in hm:
        tier1, ok_u = snap(hm["upperSplit"] - upper_bottom, policy["upperHeightOptionsMm"], tol)
        upper_split = upper_bottom + tier1
        upper_top = upper_split + round_int(upper_top_meas - upper_split, hr)
    else:
        tier1, ok_u = snap(upper_top_meas - upper_bottom, policy["upperHeightOptionsMm"], tol)
        upper_split = None
        upper_top = upper_bottom + tier1
    tall_top = round_int(hm["tallTop"], hr) if "tallTop" in hm else upper_top
    for code, ok in (("worktop-not-standard", ok_w), ("gap-not-standard", ok_g), ("upper-height-not-standard", ok_u)):
        if not ok:
            warnings.append({"code": code})

    # --- module
    wr = policy["widthRoundingMm"]
    modules: list[dict[str, Any]] = []
    counters = {k: 0 for k in ID_PREFIX}
    walls_out: dict[str, Any] = {}
    left_upper_start: float | None = None
    right_upper_start: float | None = None
    run_by_wall = {rs["wall"]: rs for rs in runs}

    def corner_ends(wall: str) -> tuple[bool, bool]:
        """(đầu along nhỏ là góc?, đầu along lớn là góc?)"""
        if wall == "back":
            return ("left" in geo.walls, "right" in geo.walls)
        return (True, False)

    back_len_right: float | None = None
    back_origin = 0.0  # mm; khác 0 khi không có tường trái: x dãy sau tính từ đầu trái dãy

    def min_side_start(storey: str) -> int:
        if "back" not in geo.walls:
            return 0
        return policy["upperDepthMm"] if storey in ("upper", "upper-top") else policy["baseDepthMm"]

    for wall in ("back", "left", "right"):
        if wall not in run_by_wall:
            continue
        rs = run_by_wall[wall]
        base_edges: list[float] = []
        storey_order = [s for s in ("base", "upper", "upper-top") if s in rs["storeys"]]
        for storey in storey_order:
            band = rs["storeys"][storey]
            pos = _cand_pos(meas, wall, storey)
            al = [_along_of(geo, meas, wall, storey, pos[b]) * geo.scale for b in band["boundaries"]]
            if wall == "back" and storey == "base":
                if "left" not in geo.walls:
                    back_origin = min(al)
                if "right" in geo.walls:
                    left_ref = geo.wall_pos("left") * geo.scale if "left" in geo.walls else back_origin
                    back_len_right = geo.wall_pos("right") * geo.scale - left_ref
            if wall == "back":
                al = [a - back_origin for a in al]
            # căn về đường chia của tủ dưới cùng dãy
            if storey != "base" and base_edges:
                for i, a in enumerate(al):
                    near = min(base_edges, key=lambda b: abs(b - a))
                    if abs(near - a) <= policy["alignToleranceMm"]:
                        al[i] = near
            if storey == "base":
                base_edges = list(al)
            xs = [round_int(a, wr) for a in al]
            mods = band["modules"]
            reverse = xs[0] > xs[-1]
            idx = list(range(len(mods)))
            if reverse:
                idx.reverse()
            lo_corner, hi_corner = corner_ends(wall)
            for rank, i in enumerate(idx):
                ans = mods[i]
                x0, x1 = sorted((xs[i], xs[i + 1]))
                first, last = rank == 0, rank == len(idx) - 1
                kind = "tall" if ans["type"].startswith("tall") else storey
                mod: dict[str, Any] = {"type": ans["type"], "storey": kind, "wall": wall,
                                       "confidence": ans["confidence"]}
                blind = 0
                if "corner" in ans["type"] and first and lo_corner:
                    blind, x0 = x0, 0
                if "corner" in ans["type"] and last and hi_corner and wall == "back" and back_len_right is not None:
                    blind = round_int(back_len_right, wr) - x1
                    x1 = round_int(back_len_right, wr)
                if wall != "back" and first and blind == 0 and x0 < min_side_start(storey):
                    # dãy bên không thể bắt đầu trước mặt trước của dãy sau (thường do bị che khuất)
                    warnings.append({"code": "side-start-clamped", "wall": wall, "fromMm": x0,
                                     "toMm": min_side_start(storey)})
                    x0 = min_side_start(storey)
                width = x1 - x0
                if ans["type"] == "upper-corner-open-shelf":
                    counters["corner"] += 1
                    mod.update({"id": f"KG{counters['corner']}", "name": "Kệ góc mở", "x": x0, "width": width,
                                "y": upper_bottom, "height": upper_top - upper_bottom,
                                "depth": policy["upperDepthMm"], "legBack": x1})
                    modules.append(mod)
                    continue
                counters[kind] += 1
                mod["id"] = f"{ID_PREFIX[kind]}{counters[kind]}"
                mod["name"] = module_name(ans["type"], ans["doors"], ans["drawers"], ans["open"])
                mod["x"], mod["width"] = x0, width
                if kind == "base":
                    mod.update({"y": 0, "height": worktop - thick, "depth": policy["baseDepthMm"]})
                elif kind == "tall":
                    mod.update({"y": 0, "height": tall_top, "depth": policy["tallDepthMm"]})
                elif storey == "upper":
                    top = upper_split if upper_split is not None else upper_top
                    mod.update({"y": upper_bottom, "height": top - upper_bottom, "depth": policy["upperDepthMm"]})
                else:
                    base_y = upper_split if upper_split is not None else upper_top
                    mod.update({"y": base_y, "height": upper_top - base_y, "depth": policy["upperDepthMm"]})
                visible = width - (blind if blind > 0 else 0)
                if blind > 0:
                    mod["blindWidth"] = blind
                    mod["blindSide"] = "start" if x0 == 0 else "end"
                if ans["doors"] and not ans["open"] and not ans["sections"]:
                    if ans["doorSplits"]:
                        sp = [_along_of(geo, meas, wall, storey, pos[s]) * geo.scale - (back_origin if wall == "back" else 0)
                              for s in ans["doorSplits"]]
                        edges = sorted([al[i], *sp, al[i + 1]])
                        tot = edges[-1] - edges[0]
                        fr = [(b - a) / tot for a, b in zip(edges, edges[1:])]
                    else:
                        fr = [1 / ans["doors"]] * ans["doors"]
                    mod["doors"] = _split(visible, fr, wr)
                if ans["drawers"] and not ans["sections"]:
                    zone = worktop - thick - plinth
                    mod["drawers"] = _split(zone, [1 / ans["drawers"]] * ans["drawers"], 10)
                if ans["sections"]:
                    hgt = mod["height"]
                    secs = []
                    for s in ans["sections"]:
                        y0, y1 = round_int(s["start"] * hgt, 10), round_int(s["end"] * hgt, 10)
                        sec: dict[str, Any] = {"kind": s["kind"], "y": y0 + mod["y"], "height": y1 - y0}
                        if s["count"]:
                            sec["count"] = s["count"]
                            if s["kind"] in ("doors", "glass-doors"):
                                sec["doors"] = _split(visible, [1 / s["count"]] * s["count"], wr)
                        if s["appliance"]:
                            sec["appliance"] = s["appliance"]
                        secs.append(sec)
                    mod["sections"] = secs
                if ans["applianceBelow"]:
                    mod["applianceBelow"] = ans["applianceBelow"]
                if ans["note"]:
                    mod["note"] = ans["note"]
                mod["_src"] = (wall, storey, i)
                modules.append(mod)
            if storey == "upper" and wall in ("left", "right"):
                st = min(xs)
                if wall == "left":
                    left_upper_start = st
                else:
                    right_upper_start = st
        wall_mods = [m for m in modules if m["wall"] == wall]   # mọi tầng: tủ trên có thể dài hơn tủ dưới
        walls_out[wall] = {"runLength": max(m["x"] + m["width"] for m in wall_mods) if wall_mods else 0,
                           "end": next(r["end"] for r in scene["runs"] if r["wall"] == wall),
                           "heightsMm": per_run[wall]}
    for m in modules:
        if m.get("type") == "upper-corner-open-shelf":
            m["legSide"] = left_upper_start if left_upper_start is not None else (
                right_upper_start if right_upper_start is not None else policy["upperDepthMm"])
            m["side"] = "left" if left_upper_start is not None else "right"

    # thiết bị
    appliances = []
    src_index = {m["_src"]: m["id"] for m in modules if "_src" in m}
    n = 0
    for rs in runs:
        for a in rs["appliances"]:
            n += 1
            mid = src_index.get((rs["wall"], a["storey"], a["module"]), "?")
            item: dict[str, Any] = {"id": f"AP{n}", "kind": a["kind"], "name": APPLIANCE_NAMES.get(a["kind"], a["kind"]),
                                    "module": mid}
            if a["note"]:
                item["note"] = a["note"]
            appliances.append(item)
    for m in modules:
        m.pop("_src", None)

    common: dict[str, Any] = {
        "plinthHeight": plinth, "worktopTop": worktop, "worktopThickness": thick,
        "baseDepth": policy["baseDepthMm"], "upperBottom": upper_bottom, "upperTop": upper_top,
        "upperDepth": policy["upperDepthMm"], "tallTop": tall_top, "tallDepth": policy["tallDepthMm"],
        "materials": scene["materials"],
    }
    if upper_split is not None:
        common["upperSplit"] = upper_split
    return {
        "schema": "cabinet-recognizer/0.2",
        "unit": "mm",
        "origin": "Góc trong giữa tường sau và tường trái (hoặc đầu trái dãy sau nếu không có tường trái), tại sàn. "
                  "Module tường sau: x dọc tường sau sang phải. Module tường bên: x dọc tường bên từ tường sau ra phía người nhìn.",
        "layout": scene["layout"],
        "walls": walls_out,
        "common": common,
        "modules": modules,
        "appliances": appliances,
        "evidence": {
            "region": policy["region"], "camera": cam_info,
            "cameraHeightMm": round_int(geo.scale * kv), "mmPerUnit": round_half_away(geo.scale, 0.1),
            "verticalCorrection": round_half_away(kv, 0.001), "verticalRefs": [round_half_away(k, 0.001) for k in kv_list],
            "scaleRefs": [{"wall": e["wall"], "what": e["what"], "mm": e["mm"],
                           "impliedCameraHeightMm": round_int(e["mmPerUnit"])} for e in estimates],
            "measuredHeightsMm": {k: round_int(v) for k, v in sorted(hm.items())},
            "policyReasoning": policy["reasoning"],
        },
        "warnings": warnings,
    }


def _split(total: int, fractions: list[float], step: int) -> list[int]:
    n = len(fractions)
    if n > 1 and max(fractions) - min(fractions) < 0.04:
        if total % n == 0:
            return [total // n] * n
        fractions = [1 / n] * n
    out = [round_int(total * f, step) for f in fractions[:-1]]
    out.append(total - sum(out))
    return out


def preview_summary(scene: Scene, meas: dict[str, Any], runs: list[RunSegmentation]) -> dict[str, Any]:
    """Số liệu sơ bộ (theo chính sách mặc định) gửi cho AI chọn chuẩn kích thước."""
    default: PolicyP = {
        "region": "unknown", "plinthRecessMm": 50, "baseDepthMm": 600, "upperDepthMm": 350, "tallDepthMm": 600,
        "worktopThicknessMm": 40, "widthRoundingMm": 10, "heightRoundingMm": 10, "alignToleranceMm": 0,
        "snapToleranceMm": 0, "worktopOptionsMm": [860], "gapOptionsMm": [650], "upperHeightOptionsMm": [750],
        "verticalCorrection": "auto", "fovDeg": 60.0, "reasoning": "",
    }
    spec = build_spec_p(scene, meas, runs, default, [])
    return {"measuredHeightsMm": spec["evidence"]["measuredHeightsMm"],
            "scaleRefs": spec["evidence"]["scaleRefs"], "camera": spec["evidence"]["camera"],
            "runLengthsMm": {w: v["runLength"] for w, v in spec["walls"].items()},
            "note": "đo với chính sách mặc định, chưa hiệu chỉnh đứng"}
