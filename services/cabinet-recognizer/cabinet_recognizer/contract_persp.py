"""Hợp đồng câu trả lời AI cho nhánh ảnh phối cảnh (chữ I xiên, chữ L, chữ U) — lõi thuần.

1. scene:   bố cục, kiểu ảnh, mỗi dãy tủ (tường nào, vùng ảnh, các đường ngang gợi ý)
2. run:     với mỗi dãy, chọn đường ứng viên thành ranh giới module theo tầng, vật chuẩn kích thước
3. policy:  chuẩn kích thước, chiều sâu, làm tròn
"""
from __future__ import annotations

from typing import Any, TypedDict

from .contract import (APPLIANCE_KINDS, END_KINDS, BandAnswer, Box, Line, _band, _box, _enum,
                       _int, _int_list, _num, _obj, _text)
from .errors import invalid

LAYOUTS: tuple[str, ...] = ("straight", "l-shape", "u-shape")
VIEWS: tuple[str, ...] = ("frontal", "perspective")
WALLS: tuple[str, ...] = ("left", "back", "right")
STOREYS: tuple[str, ...] = ("base", "upper", "upper-top")
LINE_KEYS_REQUIRED: tuple[str, ...] = ("worktopFront", "frontsBottom", "plinthBottom")
LINE_KEYS_OPTIONAL: tuple[str, ...] = ("upperBottom", "upperTop", "upperSplit", "tallTop")
PLANES: tuple[str, ...] = ("base", "upper")

Pt = tuple[float, float]


class RunHint(TypedDict):
    wall: str
    end: str
    box: Box
    lines: dict[str, tuple[Pt, Pt]]   # tỉ lệ 0..1 của ảnh


class Scene(TypedDict):
    layout: str
    view: str
    runs: list[RunHint]
    materials: dict[str, str]


class WidthRef(TypedDict):
    storey: str
    start: str
    end: str
    mm: int
    what: str


class HeightRef(TypedDict):
    top: Pt
    bottom: Pt
    mm: int
    plane: str
    what: str


class RunAppliance(TypedDict):
    kind: str
    storey: str
    module: int
    note: str


class RunSegmentation(TypedDict):
    wall: str
    storeys: dict[str, BandAnswer]
    widthRefs: list[WidthRef]
    heightRefs: list[HeightRef]
    appliances: list[RunAppliance]


class PolicyP(TypedDict):
    region: str
    plinthRecessMm: int
    baseDepthMm: int
    upperDepthMm: int
    tallDepthMm: int
    worktopThicknessMm: int
    widthRoundingMm: int
    heightRoundingMm: int
    alignToleranceMm: int
    snapToleranceMm: int
    worktopOptionsMm: list[int]
    gapOptionsMm: list[int]
    upperHeightOptionsMm: list[int]
    verticalCorrection: str
    fovDeg: float
    reasoning: str


def _pt(v: Any, what: str) -> Pt:
    if (not isinstance(v, list) or len(v) != 2
            or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and -0.5 <= x <= 1.5 for x in v)):
        raise invalid("bad-point", f"{what} phải là [x, y] theo tỉ lệ ảnh")
    return (float(v[0]), float(v[1]))


def _seg(v: Any, what: str) -> tuple[Pt, Pt]:
    if not isinstance(v, list) or len(v) != 2:
        raise invalid("bad-segment", f"{what} phải là [[x1,y1],[x2,y2]]")
    a, b = _pt(v[0], f"{what}[0]"), _pt(v[1], f"{what}[1]")
    if abs(b[0] - a[0]) < 0.015:
        raise invalid("short-segment", f"{what}: hai điểm phải cách nhau theo chiều ngang")
    return (a, b) if a[0] < b[0] else (b, a)


def parse_scene(data: Any) -> Scene:
    d = _obj(data, "scene")
    layout = _enum(d.get("layout"), LAYOUTS, "layout")
    view = _enum(d.get("view"), VIEWS, "view")
    raw = d.get("runs")
    if not isinstance(raw, list) or not raw:
        raise invalid("no-runs", "runs phải có ít nhất 1 dãy")
    runs: list[RunHint] = []
    for i, r in enumerate(raw):
        ro = _obj(r, f"runs[{i}]")
        w = f"runs[{i}]"
        lines_raw = _obj(ro.get("lines"), f"{w}.lines")
        lines: dict[str, tuple[Pt, Pt]] = {}
        for k in LINE_KEYS_REQUIRED:
            if k not in lines_raw:
                raise invalid("missing-line", f"{w}.lines.{k} là bắt buộc")
            lines[k] = _seg(lines_raw[k], f"{w}.lines.{k}")
        for k in LINE_KEYS_OPTIONAL:
            if lines_raw.get(k) is not None:
                lines[k] = _seg(lines_raw[k], f"{w}.lines.{k}")
        runs.append({"wall": _enum(ro.get("wall"), WALLS, f"{w}.wall"),
                     "end": _enum(ro.get("end", "open"), END_KINDS, f"{w}.end"),
                     "box": _box(ro.get("box"), f"{w}.box"), "lines": lines})
    if not any("upperBottom" in r["lines"] for r in runs):
        raise invalid("no-upper-line", "cần đường upperBottom ở ít nhất một dãy")
    walls = sorted(r["wall"] for r in runs)
    if len(set(walls)) != len(walls):
        raise invalid("duplicate-wall", "mỗi tường chỉ có một dãy")
    expected = {"straight": [["back"]], "l-shape": [["back", "left"], ["back", "right"]],
                "u-shape": [["back", "left", "right"]]}[layout]
    if sorted(walls) not in [sorted(e) for e in expected]:
        raise invalid("layout-walls", f"layout {layout} cần các dãy {expected}, nhận {walls}")
    mats = d.get("materials", {})
    materials = {str(k): str(v) for k, v in mats.items()} if isinstance(mats, dict) else {}
    order = {w: i for i, w in enumerate(("back", "left", "right"))}
    runs.sort(key=lambda r: order[r["wall"]])
    return {"layout": layout, "view": view, "runs": runs, "materials": dict(sorted(materials.items()))}


def parse_run(data: Any, wall: str, cand: dict[str, list[Line]]) -> RunSegmentation:
    """cand: đường ứng viên dọc của dãy theo tầng {"base": [...], "upper": [...], "upper-top": [...]}."""
    d = _obj(data, f"run[{wall}]")
    st_raw = _obj(d.get("storeys"), f"{wall}.storeys")
    storeys: dict[str, BandAnswer] = {}
    for k, v in st_raw.items():
        if k not in STOREYS:
            raise invalid("unknown-storey", f"{wall}.storeys.{k} không thuộc {list(STOREYS)}")
        if v is None:
            continue
        storeys[k] = _band(v, f"{wall}.{k}", cand.get(k, []))
    if "base" not in storeys:
        raise invalid("missing-base", f"{wall}: thiếu tầng base")
    ids = {k: {ln["id"]: ln["pos"] for ln in cand.get(k, [])} for k in STOREYS}
    wrefs: list[WidthRef] = []
    for i, r in enumerate(d.get("widthRefs", []) or []):
        ro = _obj(r, f"{wall}.widthRefs[{i}]")
        st = _enum(ro.get("storey", "base"), STOREYS, f"{wall}.widthRefs[{i}].storey")
        a, b = ro.get("from"), ro.get("to")
        if a not in ids[st] or b not in ids[st] or ids[st][a] == ids[st][b]:
            raise invalid("bad-ref", f"{wall}.widthRefs[{i}]: from/to phải là hai đường khác nhau của tầng {st}")
        wrefs.append({"storey": st, "start": str(a), "end": str(b),
                      "mm": _int(ro, "mm", 100, 3000, f"{wall}.widthRefs[{i}]"), "what": _text(ro, "what")})
    hrefs: list[HeightRef] = []
    for i, r in enumerate(d.get("heightRefs", []) or []):
        ro = _obj(r, f"{wall}.heightRefs[{i}]")
        w = f"{wall}.heightRefs[{i}]"
        top, bot = _pt(ro.get("top"), f"{w}.top"), _pt(ro.get("bottom"), f"{w}.bottom")
        if bot[1] <= top[1]:
            raise invalid("bad-ref", f"{w}: bottom phải nằm dưới top")
        hrefs.append({"top": top, "bottom": bot, "mm": _int(ro, "mm", 100, 3000, w),
                      "plane": _enum(ro.get("plane", "base"), PLANES, f"{w}.plane"), "what": _text(ro, "what")})
    apps: list[RunAppliance] = []
    for i, a in enumerate(d.get("appliances", []) or []):
        ao = _obj(a, f"{wall}.appliances[{i}]")
        st = _enum(ao.get("storey", "base"), STOREYS, f"{wall}.appliances[{i}].storey")
        if st not in storeys:
            raise invalid("bad-appliance", f"{wall}.appliances[{i}]: tầng {st} không có module")
        apps.append({"kind": _enum(ao.get("kind"), APPLIANCE_KINDS, f"{wall}.appliances[{i}].kind"),
                     "storey": st,
                     "module": _int(ao, "module", 0, len(storeys[st]["modules"]) - 1, f"{wall}.appliances[{i}]"),
                     "note": _text(ao, "note")})
    return {"wall": wall, "storeys": storeys, "widthRefs": wrefs, "heightRefs": hrefs, "appliances": apps}


def parse_policy_p(data: Any) -> PolicyP:
    d = _obj(data, "policy")
    w = "policy"
    vc = d.get("verticalCorrection", "auto")
    if not (vc == "auto" or vc == "none"):
        raise invalid("bad-enum", "policy.verticalCorrection là 'auto' hoặc 'none'")
    region = d.get("region")
    return {
        "region": region if isinstance(region, str) and region.isascii() else "unknown",
        "plinthRecessMm": _int(d, "plinthRecessMm", 0, 150, w),
        "baseDepthMm": _int(d, "baseDepthMm", 300, 900, w),
        "upperDepthMm": _int(d, "upperDepthMm", 200, 600, w),
        "tallDepthMm": _int(d, "tallDepthMm", 300, 900, w),
        "worktopThicknessMm": _int(d, "worktopThicknessMm", 10, 100, w),
        "widthRoundingMm": _int(d, "widthRoundingMm", 1, 50, w),
        "heightRoundingMm": _int(d, "heightRoundingMm", 1, 100, w),
        "alignToleranceMm": _int(d, "alignToleranceMm", 0, 100, w),
        "snapToleranceMm": _int(d, "snapToleranceMm", 0, 150, w),
        "worktopOptionsMm": _int_list(d, "worktopOptionsMm"),
        "gapOptionsMm": _int_list(d, "gapOptionsMm"),
        "upperHeightOptionsMm": _int_list(d, "upperHeightOptionsMm"),
        "verticalCorrection": str(vc),
        "fovDeg": _num(d, "fovDeg", 20, 120, w) if "fovDeg" in d else 60.0,
        "reasoning": _text(d, "reasoning"),
    }
