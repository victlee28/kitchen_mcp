"""Từ câu mô tả -> tham số mẫu -> KitchenSpec.

Khi host MCP là Claude, nên gọi thẳng `create_design(mau=...)` với tham số có cấu trúc.
Bộ phân tích dưới đây phục vụ web/prompt tự do; DeepSeek (nếu có key) chỉ đề xuất tham số,
kết quả luôn được Pydantic kiểm và có đường lùi về regex.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from . import builtin, defaults, lexicon, regions
from .catalog import Catalog
from .spec import Appliance, Common, FrontSection, Handle, KitchenSpec, Module, Room, Wall
from .words import say
from .words import said

WallSide = Literal["back", "right", "left"]


def _DRAWERS() -> list[FrontSection]:
    """The two drawers of a hob or drawer cabinet (180 + 250 mm, from the top)."""
    return [FrontSection(type="drawer", height=180), FrontSection(type="drawer", height=250)]


_NUM = r"(\d+(?:[.,]\d+)?)\s*(mm|cm|mét|met|m)?(?![a-zà-ỹ])"
_KW = r"(?<![a-zà-ỹ])"


class KitchenTemplate(BaseModel):
    """Tham số mẫu để sinh thiết kế."""
    geometry_edit: Literal["I", "L", "U"] = "I"
    backsplashHeight: Literal["standard", "to-upper", "to-ceiling"] = "standard"
    backsplashHeightMm: float | None = Field(None, ge=50, le=3000, description="Chiều cao ốp (mm); có giá trị thì thay backsplashHeight")
    wallTilePattern: str | None = Field(None, description="Kiểu xếp gạch ốp: herringbone, running-bond")
    styleTags: list[str] = Field(default_factory=list, description="Phong cách không có hình học riêng: Scandinavian, Japandi, Farmhouse, Country, Mid-Century Modern, Luxury")
    aiHints: list[str] = Field(default_factory=list, description="Cụm tiếng Anh về nội dung thiết kế (kính sọc, xương cá…) chỉ dùng cho prompt ảnh")
    renderPreferences: list[str] = Field(default_factory=list, description="Cụm tiếng Anh về góc máy, ánh sáng, chất lượng ảnh (đọc bởi kitchen.realism)")
    handleVariant: Literal["bar", "knob", "concealed", "none"] | None = None
    handleMaterial: str | None = None
    doorStyle: dict[str, Literal["flat", "frame", "glass"]] = Field(default_factory=dict, description="base/upper/tall -> kiểu cánh")
    promptInterpretation: list[dict] = Field(default_factory=list, description="Bảng diễn giải mô tả (term, canonical, scope, target, status, message)")
    backWallLength: float = Field(3000, ge=600, le=12000, description="Chiều dài dãy tủ dọc tường sau (mm)")
    rightWallLength: float | None = Field(None, ge=600, le=12000, description="Chiều dài dãy tường phải (mm), cho bếp chữ L")
    leftWallLength: float | None = Field(None, ge=600, le=12000, description="Chiều dài dãy tường trái (mm), cho bếp chữ U")
    baseDepth: float | None = Field(None, ge=300, le=900, description="Bỏ trống = lấy theo tiêu chuẩn của quốc gia/khu vực")
    countertop: float | None = Field(None, ge=700, le=1100, description="Cao mặt bàn; bỏ trống = theo quốc gia/khu vực")
    cabinetTop: float = Field(2200, ge=1500, le=3200, description="Cao độ đỉnh tủ trên (mm)")
    ceiling: float | None = Field(None, ge=2000, le=4000)
    fridge: bool = False
    fridgeSide: Literal["left", "right"] | None = Field(None, description="Đầu dãy đặt tủ lạnh, nhìn từ phía trước (left / right); trống = theo mẫu")
    loft: bool = False
    island: bool = False
    peninsula: bool = False
    openShelf: bool = False
    islandLength: float | None = Field(None, ge=600, le=6000, description="Chiều dài đảo / bán đảo (mm); trống = tự tính theo bếp")
    material: dict[str, str] = Field(default_factory=dict)
    country: str | None = Field(None, description="Mã ISO alpha-2 nơi lắp đặt: VN, US, AU, CN, DE, GB...")
    style: Literal["Modern", "Classic", "Neoclassical", "Transitional", "Industrial", "Minimalist"] = "Modern"
    crownMolding: bool | None = Field(None, description="Phào nóc; bỏ trống = có nếu phong cách cổ điển/tân cổ điển")
    baseMolding: bool | None = Field(None, description="Phào chân; bỏ trống = có nếu phong cách cổ điển/tân cổ điển")
    crownMoldingProfile: str = "classic-crown-layered"
    baseMoldingProfile: str = "classic-base"
    region: str | None = Field(None, description="SEA, EA, NA, EU, OC hoặc GLOBAL nếu chưa rõ quốc gia")


def _mm(value: str, unit: str | None) -> float:
    v = float(value.replace(",", "."))
    if unit in ("m", "mét", "met"):
        return v * 1000
    if unit == "cm":
        return v * 10
    if unit is None and v < 10:  # "dài 3" -> hiểu là mét
        return v * 1000
    return v


NO_LENGTH = "note.no-length"   # the note of a sentence that gives no length (a relayout keeps the run's length: callers drop it)


def parse_prompt(prompt: str, catalog: Catalog = builtin.CATALOG) -> tuple[KitchenTemplate, list[str]]:
    """Regex có ranh giới từ, chuẩn hóa NFC. Trả (mẫu, ghi chú những gì đã hiểu/đoán)."""
    lex = lexicon.interpret(prompt, catalog)
    t = lex.mask(prompt)  # đoạn đã dùng cho chiều cao ốp bị che để regex số đo không hiểu nhầm là chiều cao tủ
    notes: list[str] = lexicon.notes(lex.items)
    data: dict = {}
    if lex.updates.get("geometry_edit"):
        data["geometry_edit"] = lex.updates["geometry_edit"]
    word = lambda id: lexicon.source(id, catalog)      # the words of a dictionary entry (``regex`` group) as a regular expression
    lens = [_mm(v, u) for v, u in re.findall(_KW + word("dim.length") + r"[^0-9]{0,12}" + _NUM, t)]
    lens += [_mm(v, u) for v, u in re.findall(word("dim.and") + r"\s*" + _NUM, t)]
    if lens:
        data["backWallLength"] = lens[0]
        if data.get("geometry_edit") in ("L", "U"):
            data["rightWallLength"] = lens[1] if len(lens) > 1 else lens[0]
        if data.get("geometry_edit") == "U":
            data["leftWallLength"] = lens[2] if len(lens) > 2 else data["rightWallLength"]
    depth = re.search(_KW + word("dim.depth") + r"[^0-9]{0,12}" + _NUM, t)
    if depth:
        data["baseDepth"] = _mm(*depth.groups())
    height = re.search(_KW + word("dim.height") + r"[^0-9]{0,12}" + _NUM, t)
    if height:
        data["cabinetTop"] = _mm(*height.groups())
    ceiling = re.search(_KW + word("dim.ceiling") + r"[^0-9]{0,12}" + _NUM, t)
    if ceiling:
        data["ceiling"] = _mm(*ceiling.groups())
    data["fridge"] = bool(re.search(_KW + word("word.fridge"), t)) or bool(lex.updates.get("fridge"))
    side = re.search(word("word.fridge") + r"[^,.;]{0,24}?\b" + word("fridge.where") + r"\s+(?:bên\s+|phía\s+)?(" + word("side.right") + "|" + word("side.left") + ")", t)
    if side:
        data["fridgeSide"] = "right" if re.fullmatch(word("side.right"), side.group(1)) else "left"
        notes.append(said("note.fridge-side", side=said(f"side.{data['fridgeSide']}")))
    for key, value in lex.updates.items():  # phong cách, vật liệu theo phạm vi, tay nắm, kiểu cánh, ốp tường, tủ kịch trần…
        if key != "geometry_edit":
            data[key] = value
    data["promptInterpretation"] = lex.items
    if re.search(word("molding.none"), t):
        data["crownMolding"] = data["baseMolding"] = False
    else:
        if re.search(word("molding.crown"), t):
            data["crownMolding"] = True
        if re.search(word("molding.base"), t):
            data["baseMolding"] = True
    qg, kv = regions.from_description(prompt, catalog)
    if qg or kv:
        data["country"], data["region"] = qg, kv
        notes.append(said("note.standard-for", place=regions.COUNTRIES[qg][0] if qg else regions.REGIONS[kv or '']))
    try:
        color = KitchenTemplate.model_validate(data)
    except ValidationError as e:
        notes.append(said("note.size-out-of-range", detail=e.errors()[0]['msg']))
        color = KitchenTemplate.model_validate({k: v for k, v in data.items() if k in ("geometry_edit", "fridge", "fridgeSide", "loft", "material", "country", "region", "leftWallLength", "island", "peninsula", "openShelf", "islandLength",
                                                                            "style", "crownMolding", "baseMolding", "styleTags", "aiHints", "renderPreferences", "handleVariant",
                                                                            "handleMaterial", "doorStyle", "wallTilePattern", "promptInterpretation")})
    if not lens:
        notes.append(said(NO_LENGTH))
    return color, notes


_LEX_FIELDS = ("styleTags", "aiHints", "renderPreferences", "handleVariant", "handleMaterial", "doorStyle", "wallTilePattern", "backsplashHeightMm")


def merge_lexicon(template: KitchenTemplate, prompt: str, catalog: Catalog = builtin.CATALOG) -> tuple[KitchenTemplate, list[str]]:
    """Bổ sung vào mẫu do DeepSeek trả những trường chỉ bảng thuật ngữ biết; giá trị DeepSeek đã nêu được giữ nguyên."""
    lex = lexicon.interpret(prompt, catalog)
    cur = template.model_dump()
    upd = {k: lex.updates[k] for k in _LEX_FIELDS if k in lex.updates and not cur.get(k)}
    if lex.updates.get("backsplashHeight") and cur.get("backsplashHeight") == "standard":
        upd["backsplashHeight"] = lex.updates["backsplashHeight"]
    upd["material"] = {**lex.updates.get("material", {}), **cur.get("material", {})}
    upd["promptInterpretation"] = lex.items
    return KitchenTemplate.model_validate({**cur, **upd}), lexicon.notes(lex.items)


def _split(length: float, priority: list[float]) -> list[float]:
    """Chia một đoạn thành các bề rộng module chuẩn (bội 10 mm), phần dư dồn vào module cuối."""
    out, con = [], length
    standard_widths = [900, 800, 600, 450, 400, 300]
    for w in priority:
        if con - w >= 300:
            out.append(w); con -= w
    while con >= 300:
        w = next((x for x in standard_widths if con - x >= 300 or con - x == 0), 300)
        if con - w < 300 and con - w != 0:
            w = con
        out.append(w); con -= w
    if con > 0.5:
        if out:
            out[-1] += con
        else:
            out.append(con)
    return [round(w) for w in out]


# Quy ước bố trí (người dùng, 10/11/2026): có tủ lạnh thì chậu rửa đứng gần tủ lạnh hơn bếp nấu; hút mùi luôn ở tủ trên ngay trên bếp nấu.
SINK_NEAR_FRIDGE = ["cooktop", "sink"]     # thứ tự từ đầu dãy; tủ lạnh ở cuối dãy


def _layout(length: float, appliance: list[str], front: float = 450, toward_end: bool = False) -> list[tuple[float, str]]:
    """Trả [(rộng, loại)] cho một dãy. Thiết bị chiếm module 800 (co về 600 nếu chật).
    ``toward_end``: chỗ thừa dồn về đầu dãy thay vì cuối, để thiết bị cuối danh sách đứng sát cuối dãy (vd chậu sát tủ lạnh)."""
    appliance_type = {"sink": "base-sink", "cooktop": "base-cooktop"}
    for w_tb, gap_mid, gap_end, gap_start in ((800, 600, 450, front), (800, 450, 450, min(front, 450)), (600, 450, 400, min(front, 400)),
                                              (600, 300, 300, min(front, 300)), (600, 300, 0, 0), (600, 0, 0, 0)):
        need = gap_start + len(appliance) * w_tb + gap_mid * max(0, len(appliance) - 1) + gap_end
        if need <= length:
            break
    else:
        return [(w, "base") for w in _split(length, [])] if length >= 300 else []
    extra = length - need
    gaps = ([gap_start + extra] if toward_end else [gap_start]) + [gap_mid] * max(0, len(appliance) - 1) + [gap_end + (0 if toward_end else extra)]
    out: list[tuple[float, str]] = []
    for i, g in enumerate(gaps):
        if g >= 300:
            out += [(w, "base") for w in _split(g, [])]
        elif g > 0:  # khoảng < 300: nhập vào module thiết bị liền kề
            if out:
                out[-1] = (out[-1][0] + g, out[-1][1])
            else:
                gaps[i + 1 if i + 1 < len(gaps) else i] += 0
                out.append((g, "base")) if g >= 150 else None
        if i < len(appliance):
            out.append((w_tb, appliance_type[appliance[i]]))
    return [(round(w), l) for w, l in out]


def _middle(openings, hi, priority, step=10):
    """Giá trị ưu tiên kẹp trong [lo, hi], làm tròn theo bước."""
    v = priority
    if openings is not None:
        v = max(v, openings)
    if hi is not None:
        v = min(v, hi)
    return round(v / step) * step


def dimensions_by_region(rows: list[dict] | None, country: str | None, region: str | None,
                         catalog: Catalog = builtin.CATALOG) -> tuple[dict, dict]:
    """Kích thước mặc định của mẫu lấy từ tiêu chuẩn ưu tiên của quốc gia/khu vực. Trả (giá trị, nguồn từng giá trị)."""
    from .rules import default_rows
    from .rules_kb import select
    sel = select(rows if rows is not None else default_rows(), *regions.normalize(country, region, catalog), catalog)
    p = lambda t: (sel.get(t) or {}).get("params") or {}
    src = lambda t: sel[t]["code"] if t in sel else "mặc định"
    out, source = {}, {}
    md = p("countertop-height")
    allowed = md.get("countertop_allowed")
    out["countertop"] = (900 if 900 in allowed else allowed[len(allowed) // 2]) if allowed else _middle(md.get("countertop_min"), md.get("countertop_max"), 900)
    source["countertop"] = src("countertop-height")
    sd, sm = p("base-depth"), p("countertop-depth")
    if sm.get("countertopDepth_min") and not sd:
        out["baseDepth"], source["baseDepth"] = max(580, sm["countertopDepth_min"] - 20), src("countertop-depth")
    else:
        out["baseDepth"], source["baseDepth"] = _middle(sd.get("baseDepth_min"), sd.get("baseDepth_max"), 580), src("base-depth")
    st = p("upper-depth")
    out["upperDepth"], source["upperDepth"] = _middle(st.get("upperDepth_min"), st.get("upperDepth_max"), 320), src("upper-depth")
    kt = p("upper-gap")
    out["upperGap"], source["upperGap"] = _middle(kt.get("upper_gap_min"), kt.get("upper_gap_max"), 600), src("upper-gap")
    ct = p("cabinet-plinth")
    out["plinthHeight"], source["plinthHeight"] = _middle(ct.get("plinthHeight_min"), ct.get("plinthHeight_max"), 100), src("cabinet-plinth")
    out["hoodGap"], source["hoodGap"] = p("hood").get("gap_min", 650), src("hood")
    return out, source


def _merge_notes(items: list[dict], notes: list[dict]) -> list[dict]:
    """A note from the builder (what was actually placed) replaces the parser's item for the same feature, keeping the user's wording."""
    out = [dict(i) for i in items]
    for n in notes:
        hit = next((i for i in out if i.get("canonical") == n["canonical"] and i.get("target", "").startswith(("island", "peninsula", "openShelf", "module"))
                    or i.get("canonical") == n["canonical"]), None)
        if hit and n["canonical"] in ("island", "peninsula", "openShelf"):
            hit.update(status=n["status"], message=n["message"], target=n["target"])
        else:
            out.append(n)
    return out


def from_template(color: KitchenTemplate, name: str = "", rows: list[dict] | None = None,
                  catalog: Catalog = builtin.CATALOG) -> KitchenSpec:
    """Sinh spec từ mẫu. Kích thước không được chỉ định lấy theo tiêu chuẩn ưu tiên của mau.quocGia/khuVuc; các kích thước chung còn lại
    (dày cánh, khe, mặt đá, đỉnh tủ trên khi câu không nói) lấy từ danh mục ``defaults`` của xưởng."""
    new = defaults.of(catalog).new_design
    if "cabinetTop" not in color.model_fields_set and "cabinetTop" in new:
        color = color.model_copy(update={"cabinetTop": new["cabinetTop"]})
    from . import moldings as _mol
    kt, check_source = dimensions_by_region(rows, color.country, color.region, catalog)
    co_dien = color.style in ("Classic", "Neoclassical", "Transitional")
    crown_molding = color.crownMolding if color.crownMolding is not None else co_dien
    base_molding = color.baseMolding if color.baseMolding is not None else co_dien
    offered = _mol.presets(catalog)
    h_loft = offered[color.crownMoldingProfile].height if crown_molding and color.crownMoldingProfile in offered else 0
    countertop = color.countertop or kt["countertop"]
    upper_bottom = countertop + kt["upperGap"]
    ceiling = color.ceiling or max(color.cabinetTop + max(30, h_loft), 2400)
    top = min(color.cabinetTop, ceiling - h_loft) if h_loft else color.cabinetTop  # chừa chỗ cho phào nóc dưới trần
    material = {"wallTile": "Đá ốp tường đồng bộ mặt bàn", **color.material}
    handle = Handle.model_validate({k: v for k, v in (("variant", color.handleVariant), ("material", color.handleMaterial)) if v})
    c = Common(countertop=countertop, baseTop=countertop - new.get("countertopThickness", 60), plinthHeight=kt["plinthHeight"], baseDepth=color.baseDepth or kt["baseDepth"],
              upperDepth=kt["upperDepth"], cabinetTop=top, ceiling=ceiling, upperTierSplit=top if not color.loft else top - 330,
              upperBottom=upper_bottom if top - upper_bottom >= 450 else top - 600, material=material, backsplashHeight=color.backsplashHeight,
              backsplashHeightMm=color.backsplashHeightMm, wallTilePattern=color.wallTilePattern, handle=handle)
    for key in ("countertopThickness", "countertopOverhang", "doorThickness", "doorGap", "backThickness"):   # the workshop's sizes (defaults)
        if key in new:
            setattr(c, key, new[key])
    y_hood = c.countertop + kt["hoodGap"] + 165  # đáy tủ hút mùi = mặt bàn + khoảng tối thiểu + chiều cao máy
    if color.loft:
        c.cabinetTop = ceiling - max(30, h_loft)
        c.upperTierSplit = c.cabinetTop - 330
    mods: list[Module] = []
    tb: list[Appliance] = []
    upper_height = c.upperTierSplit - c.upperBottom
    upper_depth = c.upperDepth
    n = {"TD": 0, "TT": 0, "TC": 0, "TN": 0}

    def id(p):
        n[p] += 1
        return f"{p}{n[p]}"

    def thickness(wall: WallSide, start: float, length: float, appliance: list[str], front: float = 450):
        """Bố trí một dãy tủ dưới: [khoảng trước] + thiết bị xen khoảng 600 + [khoảng sau 450].
        Khoảng trống là mặt bàn thao tác (NKBA-10/14/15); thiếu chỗ thì co về 300 rồi bỏ."""
        nonlocal tb
        s = start
        if color.fridge and wall == "back":
            mods.append(Module(id=id("TC"), type="tall-fridge", name=say("name.cabinet.tall-fridge"), wall=wall, fromCorner=start + length - 700,
                               width=700, y=0, height=c.cabinetTop, depth=640, doors=[350, 350], niche=1650))
            tb.append(Appliance(id=f"TB{len(tb)+1}", type="fridge", name=say("name.appliance.fridge"), dimensions="600 × 1600 × 620", module=mods[-1].id))
            length -= 700
        near_fridge = color.fridge and wall == "back"
        plan = _layout(length, appliance, front, toward_end=near_fridge)      # với tủ lạnh: chậu (cuối danh sách) sát tủ lạnh
        for w, type in plan:
            doors = [w / 2, w / 2] if w >= 600 else [w]
            m = Module(id=id("TD"), type=type, name=say(f"name.cabinet.{type if type in ('base-sink', 'base-cooktop') else 'base'}"),
                       wall=wall, fromCorner=s, width=w, y=0, height=c.baseTop, depth=c.baseDepth, doors=doors,
                       frontSections=_DRAWERS() if type == "base-cooktop" else [])
            mods.append(m)
            if type == "base-sink":
                tb.append(Appliance(id=f"TB{len(tb)+1}", type="sink", name=say("name.appliance.sink"), dimensions=f"{min(780, w - 40):g} × 430", wall=wall, center=s + w / 2))
                tb.append(Appliance(id=f"TB{len(tb)+1}", type="faucet", name=say("name.appliance.faucet"), dimensions="cao 300", wall=wall, center=s + w / 2))
            if type == "base-cooktop":
                tb.append(Appliance(id=f"TB{len(tb)+1}", type="cooktop", name=say("name.appliance.cooktop"), dimensions=f"{min(730, w - 10):g} × 430", wall=wall, center=s + w / 2))
            s += w

    def upper(wall: WallSide, start: float, end: float):
        """Tủ trên chia theo đúng ranh giới tủ dưới bên dưới; ô ngay trên bếp thành tủ hút mùi."""
        cooktop_centers = [t.center for t in tb if t.type == "cooktop" and t.wall == wall and t.center is not None]
        cuts = sorted({start, end, *[m.fromCorner for m in mods if m.wall == wall and m.storey == "base" and start < m.fromCorner < end],
                       *[m.endAt for m in mods if m.wall == wall and m.storey == "base" and start < m.endAt < end]})
        segs = [(a, b) for a, b in zip(cuts, cuts[1:]) if b - a >= 1]
        merged: list[list[float]] = []
        for a, b in segs:  # gộp ô quá hẹp vào ô bên cạnh
            if merged and (b - a < 300 or merged[-1][1] - merged[-1][0] < 300):
                merged[-1][1] = b
            else:
                merged.append([a, b])
        for a, b in merged:
            w = b - a
            type = "upper-hood" if any(a <= t < b for t in cooktop_centers) else "upper"
            y = max(c.upperBottom + 150, y_hood) if type == "upper-hood" else c.upperBottom
            mods.append(Module(id=id("TT"), type=type, name=say("name.cabinet.upper-hood" if type == "upper-hood" else "name.cabinet.upper"), wall=wall,
                               fromCorner=a, width=w, y=y, height=c.upperTierSplit - y, depth=upper_depth, doors=[w / 2, w / 2] if w >= 600 else [w]))
            if type == "upper-hood":
                tb.append(Appliance(id=f"TB{len(tb)+1}", type="hood", name=say("name.appliance.hood"), dimensions=f"{min(w - 40, 730):g} × 165", module=mods[-1].id))
            if color.loft:
                # có phào nóc: cánh nóc mở ngang thay vì lật lên để không chạm phào (MOLDING-CANH-LAT-001)
                hinge: list[Literal["left", "right", "upper", "base"]] = ["left", "right"] if (h_loft and w >= 600) else ["left"] if h_loft else []
                loft_door = [w / 2, w / 2] if (h_loft and w >= 600) else [w]
                mods.append(Module(id=id("TN"), type="upper-loft", name=say("name.cabinet.top"), wall=wall, fromCorner=a, width=w, y=c.upperTierSplit,
                                   height=c.cabinetTop - c.upperTierSplit, depth=upper_depth, doors=loft_door, hingeSides=hinge))

    notes_built: list[dict] = []
    if color.peninsula and color.geometry_edit == "I":  # bán đảo cần một dãy vuông góc để gắn vào
        color = color.model_copy(update={"geometry_edit": "L"})
        notes_built.append({"term": "bán đảo", "canonical": "peninsula-layout", "scope": ["whole"], "target": "geometry_edit", "status": "ambiguous",
                            "message": "Bán đảo cần dãy tường phải để gắn vào, nên đã dùng bếp chữ L."})
    lr = 700 if color.fridge else 0
    room = None
    if color.geometry_edit == "I":
        thickness("back", 0, color.backWallLength, SINK_NEAR_FRIDGE if color.fridge else ["sink", "cooktop"])
        upper("back", 0, color.backWallLength - lr)
    elif color.geometry_edit == "U":
        g = c.baseDepth
        W = max(color.backWallLength, 2 * g + 900)  # bề rộng trong lòng chữ U; dãy tường sau còn tối thiểu 900 giữa hai tủ góc
        R = color.rightWallLength or W
        Lf = color.leftWallLength or R
        mods.append(Module(id=id("TD"), type="base-corner-sink", name=say("name.cabinet.blind-corner"), wall="right", fromCorner=0, width=g + 450, y=0,
                           height=c.baseTop, depth=c.baseDepth, doors=[450], blindCorner=g))
        thickness("right", g + 450, R - g - 450, ["cooktop"] if color.fridge else ["sink"], front=0)   # tủ lạnh ở tường sau: chậu sang đó
        mods.append(Module(id=id("TD"), type="base", name=say("name.cabinet.blind-corner"), wall="left", fromCorner=0, width=g + 450, y=0,
                           height=c.baseTop, depth=c.baseDepth, doors=[450], blindCorner=g))
        thickness("left", g + 450, Lf - g - 450, [], front=0)
        thickness("back", g, W - 2 * g, ["sink"] if color.fridge else ["cooktop"])
        mods.append(Module(id="KG1", type="corner-shelf", name=say("name.cabinet.corner-shelf"), wall="corner", backLength=600, rightLength=600, y=c.upperBottom,
                           height=c.upperTierSplit - c.upperBottom, depth=upper_depth, shelfCount=3))
        upper("back", 600, W - (g + lr if color.fridge else 0))
        upper("right", 600, R)
        upper("left", math.ceil(upper_depth / 10) * 10, Lf)  # bắt đầu sau bề dày tủ trên tường sau để hai dãy không chồng nhau
        room = Room(wall=[Wall(id="back", length=W)])
    else:
        L2 = color.rightWallLength or color.backWallLength
        g = c.baseDepth
        # tường phải: tủ góc khuất đầu dãy + chậu; tường sau: bếp (+ tủ lạnh cuối dãy)
        mods.append(Module(id=id("TD"), type="base-corner-sink", name=say("name.cabinet.blind-corner"), wall="right", fromCorner=0, width=g + 450, y=0,
                           height=c.baseTop, depth=c.baseDepth, doors=[450], blindCorner=g))
        thickness("right", g + 450, L2 - g - 450, ["cooktop"] if color.fridge else ["sink"], front=0)  # tủ góc phía trước đã là mặt bàn thao tác
        thickness("back", g, color.backWallLength - g, ["sink"] if color.fridge else ["cooktop"])      # tủ lạnh ở cuối tường sau: chậu sát nó
        mods.append(Module(id="KG1", type="corner-shelf", name=say("name.cabinet.corner-shelf"), wall="corner", backLength=600, rightLength=600, y=c.upperBottom,
                           height=c.upperTierSplit - c.upperBottom, depth=upper_depth, shelfCount=3))
        upper("back", 600, color.backWallLength - lr)
        upper("right", 600, L2)
    Wback = max(color.backWallLength, 2 * c.baseDepth + 900) if color.geometry_edit == "U" else color.backWallLength
    g, aisle = c.baseDepth, 1100  # lối đi giữa đảo và dãy tủ (NKBA 1067–1220)

    def free_run(label: str, z: float, start: float, length: float, blind: float = 0) -> bool:
        """Dãy đặt rời (đảo / bán đảo) song song tường sau, mặt cánh hướng về tường sau."""
        s = start
        if blind:  # đầu sát tường phải: phần góc khuất không cánh để không đụng tủ bên cạnh
            mods.append(Module(id=id("TD"), type="base-drawers", name=label, wall="island", offset=z, fromCorner=s, width=blind + 450, y=0,
                               height=c.baseTop, depth=g, blindCorner=blind, frontSections=_DRAWERS()))
            s += blind + 450
            length -= blind + 450
        for w in _split(length, []) if length >= 300 else []:
            mods.append(Module(id=id("TD"), type="base-drawers", name=label, wall="island", offset=z, fromCorner=s, width=w, y=0,
                               height=c.baseTop, depth=g, frontSections=_DRAWERS()))
            s += w
        return length >= 300

    if color.island:
        if color.geometry_edit == "I":
            ln = color.islandLength or min(2400, max(900, Wback - 600))
            start = max(0, (Wback - ln) / 2)
        elif color.geometry_edit == "L":
            start = g + aisle
            ln = min(color.islandLength or 2400, Wback - start)
        else:
            start = g + aisle
            ln = min(color.islandLength or 2400, Wback - 2 * start)
        if ln >= 600 and free_run("Tủ đảo", g + aisle, start, ln):
            notes_built.append({"term": "đảo bếp", "canonical": "island", "scope": ["whole"], "target": "module.wall=island", "status": "built",
                                "message": f"Đảo dài {ln:g} mm, cách dãy tủ sau {aisle} mm."})
        else:
            notes_built.append({"term": "đảo bếp", "canonical": "island", "scope": ["whole"], "target": "module.wall=island", "status": "ambiguous",
                                "message": f"Không đủ chỗ cho đảo (cần lối đi {aisle} mm mỗi bên và dài ≥ 600 mm); chưa thêm."})
    if color.peninsula:
        Rlen = color.rightWallLength or Wback
        room_len = Wback - (2 * g if color.geometry_edit == "U" else g) - 600
        ln = min(color.islandLength or 1800, room_len)
        if ln >= g + 750 and free_run("Tủ bán đảo", Rlen, 0, ln, blind=g):
            notes_built.append({"term": "bán đảo", "canonical": "peninsula", "scope": ["whole"], "target": "module.wall=island", "status": "built",
                                "message": f"Bán đảo dài {ln:g} mm gắn vào cuối dãy tường phải."})
        else:
            notes_built.append({"term": "bán đảo", "canonical": "peninsula", "scope": ["whole"], "target": "module.wall=island", "status": "ambiguous",
                                "message": "Không đủ chỗ cho bán đảo; chưa thêm."})
    if color.openShelf:
        sink = next((t for t in tb if t.type == "sink"), None)
        ups = [m for m in mods if m.type == "upper"]
        pick = next((m for m in ups if sink and m.wall == sink.wall and sink.center is not None and m.fromCorner <= sink.center < m.endAt), None) or (ups[-1] if ups else None)
        if pick:
            pick.type, pick.doors, pick.shelfCount, pick.name = "upper-open", [], 3, say("name.cabinet.open-shelf")
            notes_built.append({"term": "kệ mở", "canonical": "openShelf", "scope": ["upper"], "target": pick.id, "status": "built",
                                "message": f"Tủ trên {pick.id} (rộng {pick.width:g} mm) đổi thành kệ mở 3 tầng."})
        else:
            notes_built.append({"term": "kệ mở", "canonical": "openShelf", "scope": ["upper"], "target": "-", "status": "ambiguous",
                                "message": "Không có tủ trên để đổi thành kệ mở."})
    tier = {"base": "base", "upper": "upper", "loft": "upper", "tall": "tall"}
    for m in mods:  # kiểu cánh theo tầng (shaker / phẳng / kính)
        ds = color.doorStyle.get(tier.get(m.storey, ""))
        if ds and m.doors and m.type not in ("upper-hood", "corner-shelf"):
            m.doorStyle = ds
    spec = KitchenSpec(name=name or say("name.design"), common=c, module=mods, room=room, appliances=tb, country=color.country, region=color.region, style=color.style,
                       styleTags=color.styleTags or None, aiHints=list(dict.fromkeys(color.aiHints)) or None,
                       renderPreferences=list(dict.fromkeys(color.renderPreferences)),
                       promptInterpretation=_merge_notes(color.promptInterpretation, notes_built) or None,
                       moldings=_mol.default_moldings(crown_molding, base_molding, color.crownMoldingProfile, color.baseMoldingProfile),
                       moldingProfiles=_mol.embedded([p for p, on in ((color.crownMoldingProfile, crown_molding), (color.baseMoldingProfile, base_molding)) if on], [],
                                                     catalog),
                       source="Sinh từ mẫu; kích thước theo: " + ", ".join(f"{k}={v}" for k, v in check_source.items()))
    return KitchenSpec.model_validate(spec.model_dump(mode="json"))
