"""Hợp đồng câu trả lời AI cho bước ``openings``: cửa đi, cửa sổ, ô thông trên các tường có dãy tủ (lõi thuần).

AI chỉ chỉ ra vị trí trong ảnh (tỉ lệ 0..1); code đổi sang mm bằng đúng camera / tỉ lệ đã dùng cho tủ (``compute_openings``).

    {"openings": [{"kind": "door" | "window" | "passage", "wall": "back" | "left" | "right",
                   "corners": {"topLeft": [x, y], "topRight": [x, y], "bottomRight": [x, y], "bottomLeft": [x, y]},
                   "edgesSeen": "casing" | "hole", "style": "swing" | "sliding" | "folding" | "fixed" | "top-hung" | "none",
                   "leaves": int, "verticals": [[x, y]], "horizontals": [[x, y]], "hidden": ["left" | "right" | "top" | "bottom"],
                   "confidence": 0..1, "note": ""}]}
"""
from __future__ import annotations

from typing import Any, TypedDict

from .contract import _enum, _obj, _text
from .contract_persp import Pt, _pt
from .errors import invalid

KINDS: tuple[str, ...] = ("door", "window", "passage")
EDGES: tuple[str, ...] = ("casing", "hole")
STYLES: tuple[str, ...] = ("swing", "sliding", "folding", "fixed", "top-hung", "none")
SIDES: tuple[str, ...] = ("left", "right", "top", "bottom")
CORNERS: tuple[str, ...] = ("topLeft", "topRight", "bottomRight", "bottomLeft")
MAX_OPENINGS = 12
MAX_SPLITS = 4
MAX_LEAVES = 6


class OpeningAnswer(TypedDict):
    kind: str
    wall: str
    corners: dict[str, Pt]
    edgesSeen: str
    style: str
    leaves: int
    verticals: list[Pt]
    horizontals: list[Pt]
    hidden: list[str]
    confidence: float
    note: str


def _points(value: Any, what: str) -> list[Pt]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_SPLITS:
        raise invalid("bad-points", f"{what} phải là danh sách tối đa {MAX_SPLITS} điểm [x, y]")
    return [_pt(p, f"{what}[{i}]") for i, p in enumerate(value)]


def _opening(data: Any, i: int, walls: tuple[str, ...]) -> OpeningAnswer:
    w = f"openings[{i}]"
    d = _obj(data, w)
    kind = _enum(d.get("kind"), KINDS, f"{w}.kind")
    wall = _enum(d.get("wall", walls[0] if len(walls) == 1 else None), walls, f"{w}.wall (chỉ tường có dãy tủ)")
    raw = _obj(d.get("corners"), f"{w}.corners")
    corners = {k: _pt(raw.get(k), f"{w}.corners.{k}") for k in CORNERS}
    if not (corners["topLeft"][1] < corners["bottomLeft"][1] and corners["topRight"][1] < corners["bottomRight"][1]):
        raise invalid("upside-down", f"{w}: các góc trên phải nằm trên các góc dưới")
    if not (corners["topLeft"][0] < corners["topRight"][0] and corners["bottomLeft"][0] < corners["bottomRight"][0]):
        raise invalid("left-right", f"{w}: các góc trái phải nằm bên trái các góc phải")
    leaves = d.get("leaves", 1 if kind != "passage" else 0)
    if isinstance(leaves, bool) or not isinstance(leaves, int) or not 0 <= leaves <= MAX_LEAVES:
        raise invalid("bad-leaves", f"{w}.leaves phải là số nguyên 0..{MAX_LEAVES}")
    hidden = d.get("hidden") or []
    if not isinstance(hidden, list):
        raise invalid("bad-hidden", f"{w}.hidden phải là danh sách")
    conf = d.get("confidence", 1.0)
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
        raise invalid("bad-confidence", f"{w}.confidence phải trong 0..1")
    return {"kind": kind, "wall": wall, "corners": corners,
            "edgesSeen": _enum(d.get("edgesSeen", "casing"), EDGES, f"{w}.edgesSeen"),
            "style": _enum(d.get("style", "none" if kind == "passage" else "swing"), STYLES, f"{w}.style"),
            "leaves": leaves, "verticals": _points(d.get("verticals"), f"{w}.verticals"),
            "horizontals": _points(d.get("horizontals"), f"{w}.horizontals"),
            "hidden": sorted({_enum(h, SIDES, f"{w}.hidden") for h in hidden}), "confidence": float(conf), "note": _text(d, "note")}


def parse_openings(data: Any, walls: tuple[str, ...]) -> list[OpeningAnswer]:
    d = _obj(data, "openings")
    raw = d.get("openings", [])
    if not isinstance(raw, list):
        raise invalid("bad-openings", "openings phải là danh sách (rỗng khi không thấy cửa nào)")
    if len(raw) > MAX_OPENINGS:
        raise invalid("too-many-openings", f"tối đa {MAX_OPENINGS} cửa")
    return [_opening(x, i, walls) for i, x in enumerate(raw)]
