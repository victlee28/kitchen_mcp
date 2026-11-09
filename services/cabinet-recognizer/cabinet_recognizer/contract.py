"""Hợp đồng dữ liệu giữa các bước và kiểm tra câu trả lời của AI (lõi thuần).

Ba câu trả lời AI:
- layout:       vị trí gần đúng của dãy tủ trên / dưới (tỉ lệ 0..1 của ảnh) + bối cảnh
- segmentation: chọn đường ứng viên nào là đường chia module, mỗi ô là loại gì
- policy:       giả định kích thước chuẩn (chiều cao tham chiếu, bước làm tròn, giá trị chuẩn)

Câu trả lời sai hợp đồng -> RecognizerError(validation); vỏ sẽ hỏi lại AI một lần.
"""
from __future__ import annotations

import re
from typing import Any, TypedDict

from .errors import invalid
from .numeric import round_half_away

MODULE_TYPES: tuple[str, ...] = (
    "upper", "upper-dish-rack", "upper-hood", "upper-open-shelf", "upper-glass", "upper-lift-up",
    "upper-corner", "base", "base-sink", "base-drawer", "base-hob", "base-oven", "base-corner",
    "base-open-shelf", "base-dishwasher", "tall", "tall-fridge", "tall-display", "tall-oven",
    "upper-top", "upper-corner-open-shelf", "filler", "other",
)
SECTION_KINDS: tuple[str, ...] = (
    "plinth", "drawer", "drawers", "door", "doors", "glass-doors", "appliance", "open", "flap",
)
APPLIANCE_KINDS: tuple[str, ...] = (
    "sink", "faucet", "hob", "hood", "oven", "microwave", "dishwasher", "fridge", "led", "other",
)
END_KINDS: tuple[str, ...] = ("open", "wall", "tall")
ROW_KEYS: tuple[str, ...] = (
    "upperTop", "upperBottom", "worktopBack", "worktopFront", "frontsTop", "plinthTop", "floor",
)
OPTIONAL_ROW_KEYS: tuple[str, ...] = ("upperSplit",)   # the line between two stacked rows of wall cabinets (top row = "loft")
BANDS: tuple[str, ...] = ("upper", "base")


class Box(TypedDict):
    left: float
    right: float
    top: float
    bottom: float


class Layout(TypedDict):
    layout: str
    upper: Box
    base: Box
    leftEnd: str
    rightEnd: str
    upperSameExtent: bool
    materials: dict[str, str]


class Line(TypedDict):
    id: str
    pos: int
    strength: float


class Section(TypedDict):
    kind: str
    start: float      # tỉ lệ 0..1 chiều cao module, tính từ dưới
    end: float
    count: int        # số cánh / ngăn kéo (0 nếu không áp dụng)
    appliance: str | None


class ModuleAnswer(TypedDict):
    type: str
    doors: int
    doorSplits: list[str]
    drawers: int
    open: bool
    applianceBelow: str | None
    confidence: float
    note: str
    sections: list[Section]


class BandAnswer(TypedDict):
    boundaries: list[str]
    modules: list[ModuleAnswer]


class ApplianceAnswer(TypedDict):
    kind: str
    band: str
    module: int
    note: str


class Segmentation(TypedDict):
    rows: dict[str, str]
    upper: BandAnswer
    base: BandAnswer
    appliances: list[ApplianceAnswer]


class Policy(TypedDict):
    region: str
    referenceMm: int
    plinthMm: int
    worktopThicknessMm: int
    baseDepthMm: int
    upperDepthMm: int
    upperScaleFactor: float
    runRoundingMm: int
    widthRoundingMm: int
    heightRoundingMm: int
    alignToleranceMm: int
    snapToleranceMm: int
    gapOptionsMm: list[int]
    upperHeightOptionsMm: list[int]
    reasoning: str


# ---------- helpers ----------

def _obj(data: Any, what: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise invalid("not-object", f"{what} phải là object JSON")
    return data  # type: ignore[return-value]


def _num(data: dict[str, Any], key: str, lo: float, hi: float, what: str) -> float:
    v = data.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid("missing-number", f"{what}.{key} phải là số")
    if not (lo <= float(v) <= hi):
        raise invalid("out-of-range", f"{what}.{key}={v} ngoài khoảng [{lo}, {hi}]")
    return float(v)


def _int(data: dict[str, Any], key: str, lo: int, hi: int, what: str) -> int:
    v = _num(data, key, lo, hi, what)
    if v != int(v):
        raise invalid("not-integer", f"{what}.{key} phải là số nguyên")
    return int(v)


def _enum(value: Any, allowed: tuple[str, ...], what: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise invalid("unknown-enum", f"{what}={value!r} không thuộc {list(allowed)}")
    return value


def _text(data: dict[str, Any], key: str) -> str:
    v = data.get(key, "")
    return v if isinstance(v, str) else ""


def _box(data: Any, what: str) -> Box:
    d = _obj(data, what)
    box: Box = {
        "left": _num(d, "left", 0, 1, what), "right": _num(d, "right", 0, 1, what),
        "top": _num(d, "top", 0, 1, what), "bottom": _num(d, "bottom", 0, 1, what),
    }
    if box["left"] >= box["right"] or box["top"] >= box["bottom"]:
        raise invalid("bad-box", f"{what}: left<right và top<bottom")
    return box


# ---------- layout ----------

def parse_layout(data: Any) -> Layout:
    d = _obj(data, "layout")
    if d.get("layout") != "straight":
        raise invalid("unsupported-layout",
                      "phiên bản này chỉ nhận dãy thẳng nhìn chính diện (layout=straight)")
    upper, base = _box(d.get("upper"), "upper"), _box(d.get("base"), "base")
    if upper["bottom"] > base["top"]:
        raise invalid("bad-box", "dãy tủ trên phải nằm phía trên dãy tủ dưới")
    mats = d.get("materials", {})
    materials = {str(k): str(v) for k, v in mats.items()} if isinstance(mats, dict) else {}
    return {
        "layout": "straight", "upper": upper, "base": base,
        "leftEnd": _enum(d.get("leftEnd"), END_KINDS, "leftEnd"),
        "rightEnd": _enum(d.get("rightEnd"), END_KINDS, "rightEnd"),
        "upperSameExtent": bool(d.get("upperSameExtent", True)),
        "materials": dict(sorted(materials.items())),
    }


# ---------- segmentation ----------

def _ids(lines: list[Line]) -> dict[str, int]:
    return {ln["id"]: ln["pos"] for ln in lines}


def _module(d: Any, band: str, i: int, left: int, right: int, vpos: dict[str, int]) -> ModuleAnswer:
    m = _obj(d, f"{band}.modules[{i}]")
    what = f"{band}.modules[{i}]"
    mtype = _enum(m.get("type"), MODULE_TYPES, f"{what}.type")
    splits_raw = m.get("doorSplits", [])
    if not isinstance(splits_raw, list):
        raise invalid("bad-list", f"{what}.doorSplits phải là danh sách")
    splits: list[str] = []
    for s in splits_raw:
        if s not in vpos or not (left < vpos[s] < right):
            raise invalid("bad-split", f"{what}.doorSplits: {s!r} không phải đường nằm trong ô")
        splits.append(str(s))
    splits.sort(key=lambda s: vpos[s])
    doors = _int(m, "doors", 0, 6, what)
    if splits and doors != len(splits) + 1:
        raise invalid("door-count", f"{what}: doors phải bằng số doorSplits + 1")
    below = m.get("applianceBelow")
    if below is not None:
        below = _enum(below, APPLIANCE_KINDS, f"{what}.applianceBelow")
    conf = m.get("confidence", 0.5)
    sections: list[Section] = []
    raw_sec = m.get("sections", [])
    for j, sec in enumerate(raw_sec if isinstance(raw_sec, list) else []):
        so = _obj(sec, f"{what}.sections[{j}]")
        sw = f"{what}.sections[{j}]"
        start, end = _num(so, "start", 0, 1, sw), _num(so, "end", 0, 1, sw)
        if end <= start:
            raise invalid("bad-section", f"{sw}: end phải lớn hơn start")
        app = so.get("appliance")
        sections.append({
            "kind": _enum(so.get("kind"), SECTION_KINDS, f"{sw}.kind"), "start": start, "end": end,
            "count": _int(so, "count", 0, 8, sw) if "count" in so else 0,
            "appliance": _enum(app, APPLIANCE_KINDS, f"{sw}.appliance") if app is not None else None,
        })
    sections.sort(key=lambda x: x["start"])
    return {
        "type": mtype, "doors": doors, "doorSplits": splits,
        "drawers": _int(m, "drawers", 0, 8, what) if "drawers" in m else 0,
        "open": bool(m.get("open", False)), "applianceBelow": below,
        "confidence": float(conf) if isinstance(conf, (int, float)) else 0.5,
        "note": _text(m, "note"), "sections": sections,
    }


def _band(data: Any, band: str, lines: list[Line]) -> BandAnswer:
    d = _obj(data, band)
    vpos = _ids(lines)
    bounds = d.get("boundaries")
    if not isinstance(bounds, list) or len(bounds) < 2:
        raise invalid("bad-boundaries", f"{band}.boundaries cần ít nhất 2 đường")
    for b in bounds:
        if b not in vpos:
            raise invalid("unknown-line", f"{band}.boundaries: {b!r} không có trong danh sách đường")
    xs = [vpos[b] for b in bounds]
    if any(b <= a for a, b in zip(xs, xs[1:])):
        raise invalid("not-sorted", f"{band}.boundaries phải tăng dần từ trái sang phải")
    mods = d.get("modules")
    if not isinstance(mods, list) or len(mods) != len(bounds) - 1:
        raise invalid("module-count", f"{band}: số module phải bằng số boundaries - 1")
    return {
        "boundaries": [str(b) for b in bounds],
        "modules": [_module(m, band, i, xs[i], xs[i + 1], vpos) for i, m in enumerate(mods)],
    }


MANUAL_LINE = re.compile(r"^x(0|1|0?\.\d{1,4})$")     # "x0.412": a boundary the model places itself, as a fraction of the image width


def add_manual_lines(data: dict[str, Any], measure: dict[str, Any]) -> None:
    """Edge detection misses boundaries between same-coloured doors. A boundary or door split written ``x<fraction>`` is added to the
    candidate lines of its band (in place), so every later step finds it by id like any detected line."""
    for band in BANDS:
        d = data.get(band)
        if not isinstance(d, dict):
            continue
        refs = [b for b in d.get("boundaries", []) if isinstance(b, str)]
        for m in d.get("modules", []):
            if isinstance(m, dict):
                refs += [x for x in m.get("doorSplits", []) if isinstance(x, str)]
        lines = measure["vlines"][band]
        have = {ln["id"] for ln in lines}
        for ref in refs:
            if MANUAL_LINE.match(ref) and ref not in have:
                lines.append({"id": ref, "pos": int(round_half_away(float(ref[1:]) * measure["imageSize"][0])), "strength": 0.0})
                have.add(ref)
        lines.sort(key=lambda ln: ln["pos"])


def parse_segmentation(data: Any, measure: dict[str, Any]) -> Segmentation:
    d = _obj(data, "segmentation")
    add_manual_lines(d, measure)
    hpos = _ids(measure["hlines"])
    rows_raw = _obj(d.get("rows"), "rows")
    rows: dict[str, str] = {}
    for key in ROW_KEYS:
        v = rows_raw.get(key)
        if v not in hpos:
            raise invalid("unknown-row", f"rows.{key}={v!r} không có trong danh sách đường ngang")
        rows[key] = str(v)
    order = [hpos[rows[k]] for k in ROW_KEYS]
    if any(b <= a for a, b in zip(order, order[1:])):
        raise invalid("rows-order", f"rows phải theo thứ tự từ trên xuống: {list(ROW_KEYS)}")
    split = rows_raw.get("upperSplit")
    if split is not None:
        if split not in hpos:
            raise invalid("unknown-row", f"rows.upperSplit={split!r} không có trong danh sách đường ngang")
        if not hpos[rows["upperTop"]] < hpos[split] < hpos[rows["upperBottom"]]:
            raise invalid("rows-order", "rows.upperSplit phải nằm giữa upperTop và upperBottom")
        rows["upperSplit"] = str(split)
    apps: list[ApplianceAnswer] = []
    upper = _band(d.get("upper"), "upper", measure["vlines"]["upper"])
    base = _band(d.get("base"), "base", measure["vlines"]["base"])
    raw_apps = d.get("appliances", [])
    for i, a in enumerate(raw_apps if isinstance(raw_apps, list) else []):
        ao = _obj(a, f"appliances[{i}]")
        band = _enum(ao.get("band"), BANDS, f"appliances[{i}].band")
        count = len(upper["modules"] if band == "upper" else base["modules"])
        apps.append({
            "kind": _enum(ao.get("kind"), APPLIANCE_KINDS, f"appliances[{i}].kind"),
            "band": band, "module": _int(ao, "module", 0, count - 1, f"appliances[{i}]"),
            "note": _text(ao, "note"),
        })
    return {"rows": rows, "upper": upper, "base": base, "appliances": apps}


# ---------- policy ----------

def _int_list(d: dict[str, Any], key: str) -> list[int]:
    v = d.get(key)
    if not isinstance(v, list) or not v or not all(isinstance(x, int) and 0 < x < 5000 for x in v):
        raise invalid("bad-list", f"policy.{key} phải là danh sách số nguyên mm")
    return sorted(set(v))


def parse_policy(data: Any) -> Policy:
    d = _obj(data, "policy")
    w = "policy"
    region = d.get("region")
    return {
        "region": region if isinstance(region, str) and region.isascii() else "unknown",
        "referenceMm": _int(d, "referenceMm", 700, 1100, w),
        "plinthMm": _int(d, "plinthMm", 0, 250, w),
        "worktopThicknessMm": _int(d, "worktopThicknessMm", 10, 100, w),
        "baseDepthMm": _int(d, "baseDepthMm", 300, 900, w),
        "upperDepthMm": _int(d, "upperDepthMm", 200, 600, w),
        "upperScaleFactor": _num(d, "upperScaleFactor", 0.8, 1.3, w) if "upperScaleFactor" in d else 1.04,
        "runRoundingMm": _int(d, "runRoundingMm", 1, 100, w),
        "widthRoundingMm": _int(d, "widthRoundingMm", 1, 50, w),
        "heightRoundingMm": _int(d, "heightRoundingMm", 1, 100, w),
        "alignToleranceMm": _int(d, "alignToleranceMm", 0, 100, w),
        "snapToleranceMm": _int(d, "snapToleranceMm", 0, 150, w),
        "gapOptionsMm": _int_list(d, "gapOptionsMm"),
        "upperHeightOptionsMm": _int_list(d, "upperHeightOptionsMm"),
        "reasoning": _text(d, "reasoning"),
    }


def extract_json(text: str) -> Any:
    """Lấy object JSON đầu tiên trong câu trả lời của model (bỏ ```json ...```)."""
    import json

    start = text.find("{")
    if start < 0:
        raise invalid("no-json", "câu trả lời không chứa JSON")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError as e:
                    raise invalid("bad-json", str(e)) from e
    raise invalid("bad-json", "JSON không đóng ngoặc")
