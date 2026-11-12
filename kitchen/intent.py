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
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, ValidationError

from . import builtin, cabinet_types, defaults, layout_solver, lexicon, regions
from .catalog import Catalog
from .spec import Appliance, Common, FrontSection, Handle, KitchenSpec, Module, Room, Wall
from .words import say
from .words import said

WallSide = Literal["back", "right", "left"]


def _drawers(rules: layout_solver.Rules) -> list[FrontSection]:
    """The drawers of a hob or drawer cabinet from the top (``layout-rules.drawers``: 180 + 250 mm)."""
    return [FrontSection(type="drawer", height=h) for h in rules.drawers]


_NUM = r"(\d+(?:[.,]\d+)?)\s*(mm|cm|mét|met|m)?(?![a-zà-ỹ])"
_KW = r"(?<![a-zà-ỹ])"


class KitchenTemplate(BaseModel):
    """Tham số mẫu để sinh thiết kế."""
    geometry_edit: str = Field("I", pattern=r"^[A-Za-z0-9_.:-]{1,64}$", description="Layout template (catalog kind layout-template): I, L, U or one the workshop / user added")
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
    named = layout_solver.named_in(prompt, catalog)      # a layout template called by its name ("theo mẫu Bếp nhà tôi")
    if named:
        data["geometry_edit"] = named[0]
        if named[0] not in ("I", "L", "U"):
            notes.append(said("note.layout-template", name=named[1]))
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
    rules = layout_solver.rules(catalog)
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
              upperDepth=kt["upperDepth"], cabinetTop=top, ceiling=ceiling, upperTierSplit=top if not color.loft else top - rules.loft_height,
              upperBottom=upper_bottom if top - upper_bottom >= 450 else top - 600, material=material, backsplashHeight=color.backsplashHeight,
              backsplashHeightMm=color.backsplashHeightMm, wallTilePattern=color.wallTilePattern, handle=handle)
    for key in ("countertopThickness", "countertopOverhang", "doorThickness", "doorGap", "backThickness"):   # the workshop's sizes (defaults)
        if key in new:
            setattr(c, key, new[key])
    y_hood = c.countertop + kt["hoodGap"] + rules.hood_height  # đáy tủ hút mùi = mặt bàn + khoảng tối thiểu + chiều cao máy
    if color.loft:
        c.cabinetTop = ceiling - max(30, h_loft)
        c.upperTierSplit = c.cabinetTop - rules.loft_height
    mods: list[Module] = []
    tb: list[Appliance] = []
    upper_depth = c.upperDepth
    n = {"TD": 0, "TT": 0, "TC": 0, "TN": 0}

    def id(p):
        n[p] += 1
        return f"{p}{n[p]}"

    def extra(wall: WallSide, at: float, e: dict[str, Any]) -> float:
        """A cabinet the template asks for at the start / end of a run (``extras``): its width."""
        w = float(e["width"])
        mods.append(Module(id=id("TD"), type=str(e["type"]), name=cabinet_types.label_of(str(e["type"]), catalog), wall=wall, fromCorner=at, width=w, y=0,
                           height=c.baseTop, depth=c.baseDepth, doors=[w / 2, w / 2] if w >= rules.double_door_from else [w]))
        return w

    def thickness(wall: WallSide, start: float, length: float, appliance: list[str], front: float = 450, fridge_at_end: bool = False,
                  extras: list[dict[str, Any]] | None = None):
        """Bố trí một dãy tủ dưới: [khoảng trước] + thiết bị xen khoảng 600 + [khoảng sau 450] (``layout_solver.base_plan``).
        Khoảng trống là mặt bàn thao tác (NKBA-10/14/15); thiếu chỗ thì co về 300 rồi bỏ."""
        s = start
        if fridge_at_end:
            fr = rules.fridge
            width = float(fr.get("width", 700))
            mods.append(Module(id=id("TC"), type="tall-fridge", name=say("name.cabinet.tall-fridge"), wall=wall, fromCorner=start + length - width,
                               width=width, y=0, height=c.cabinetTop, depth=fr.get("depth", 640), doors=list(fr.get("doors", [350, 350])),
                               niche=fr.get("niche", 1650)))
            tb.append(Appliance(id=f"TB{len(tb)+1}", type="fridge", name=say("name.appliance.fridge"), dimensions=str(fr.get("dimensions", "")),
                                module=mods[-1].id))
            length -= width
        for e in (x for x in extras or [] if x["at"] == "start"):
            w = extra(wall, s, e)
            s += w
            length -= w
        ends = [x for x in extras or [] if x["at"] == "end"]
        tail = start + (s - start) + length          # where the end cabinets stop (before the fridge)
        for e in reversed(ends):
            tail -= float(e["width"])
        length -= sum(float(e["width"]) for e in ends)
        plan = layout_solver.base_plan(length, appliance, rules, front, toward_end=fridge_at_end)   # với tủ lạnh: chậu (cuối danh sách) sát tủ lạnh
        for w, type in plan:
            base_cabinet(wall, s, w, type)
            s += w
        for e in ends:
            tail += extra(wall, tail, e)

    def base_cabinet(wall: WallSide, s: float, w: float, type: str) -> None:
        """A plain, sink or cooktop base cabinet at ``s`` with the sink and tap / the cooktop on the worktop above it."""
        doors = [w / 2, w / 2] if w >= rules.double_door_from else [w]
        mods.append(Module(id=id("TD"), type=type, name=say(f"name.cabinet.{type if type in ('base-sink', 'base-cooktop') else 'base'}"),
                           wall=wall, fromCorner=s, width=w, y=0, height=c.baseTop, depth=c.baseDepth, doors=doors,
                           frontSections=_drawers(rules) if type == "base-cooktop" else []))
        if type == "base-sink":
            tb.append(Appliance(id=f"TB{len(tb)+1}", type="sink", name=say("name.appliance.sink"), dimensions=f"{min(780, w - 40):g} × 430", wall=wall, center=s + w / 2))
            tb.append(Appliance(id=f"TB{len(tb)+1}", type="faucet", name=say("name.appliance.faucet"), dimensions="cao 300", wall=wall, center=s + w / 2))
        if type == "base-cooktop":
            tb.append(Appliance(id=f"TB{len(tb)+1}", type="cooktop", name=say("name.appliance.cooktop"), dimensions=f"{min(730, w - 10):g} × 430", wall=wall, center=s + w / 2))

    def cabinets(wall: WallSide, start: float, length: float, items: list[dict[str, Any]]) -> None:
        """The cabinets of a ``cabinets`` step in order (``layout_solver.fit_items``): base ones as a run makes them, the fridge cabinet
        with its fridge, any other type at its storey's height."""
        s = start
        for w, type in layout_solver.fit_items(length, items, rules):
            if type == layout_solver.GAP:
                pass
            elif type in ("base", "base-sink", "base-cooktop"):
                base_cabinet(wall, s, w, type)
            elif type == "tall-fridge":
                fr = rules.fridge
                mods.append(Module(id=id("TC"), type="tall-fridge", name=say("name.cabinet.tall-fridge"), wall=wall, fromCorner=s, width=w, y=0,
                                   height=c.cabinetTop, depth=fr.get("depth", 640), doors=[w / 2, w / 2], niche=fr.get("niche", 1650)))
                tb.append(Appliance(id=f"TB{len(tb)+1}", type="fridge", name=say("name.appliance.fridge"), dimensions=str(fr.get("dimensions", "")),
                                    module=mods[-1].id))
            else:
                tall = cabinet_types.storey_of(type, catalog) == "tall"
                mods.append(Module(id=id("TC" if tall else "TD"), type=type, name=cabinet_types.label_of(type, catalog), wall=wall, fromCorner=s,
                                   width=w, y=0, height=c.cabinetTop if tall else c.baseTop, depth=c.baseDepth,
                                   doors=[w / 2, w / 2] if w >= rules.double_door_from else [w]))
            s += w

    def upper(wall: WallSide, start: float, end: float):
        """Tủ trên chia theo đúng ranh giới tủ dưới bên dưới; ô ngay trên bếp thành tủ hút mùi."""
        cooktop_centers = [t.center for t in tb if t.type == "cooktop" and t.wall == wall and t.center is not None]
        talls = [(m.fromCorner, m.endAt) for m in mods if m.wall == wall and m.storey == "tall"]    # no wall cabinet in front of a tall one
        cuts = sorted({start, end, *[m.fromCorner for m in mods if m.wall == wall and m.storey in ("base", "tall") and start < m.fromCorner < end],
                       *[m.endAt for m in mods if m.wall == wall and m.storey in ("base", "tall") and start < m.endAt < end]})
        segs = [(a, b) for a, b in zip(cuts, cuts[1:]) if b - a >= 1 and not any(t0 <= (a + b) / 2 < t1 for t0, t1 in talls)]
        merged: list[list[float]] = []
        for a, b in segs:  # gộp ô quá hẹp vào ô bên cạnh
            if merged and (b - a < rules.min_width or merged[-1][1] - merged[-1][0] < rules.min_width):
                merged[-1][1] = b
            else:
                merged.append([a, b])
        for a, b in merged:
            w = b - a
            type = "upper-hood" if any(a <= t < b for t in cooktop_centers) else "upper"
            y = max(c.upperBottom + 150, y_hood) if type == "upper-hood" else c.upperBottom
            two = w >= rules.double_door_from
            mods.append(Module(id=id("TT"), type=type, name=say("name.cabinet.upper-hood" if type == "upper-hood" else "name.cabinet.upper"), wall=wall,
                               fromCorner=a, width=w, y=y, height=c.upperTierSplit - y, depth=upper_depth, doors=[w / 2, w / 2] if two else [w]))
            if type == "upper-hood":
                tb.append(Appliance(id=f"TB{len(tb)+1}", type="hood", name=say("name.appliance.hood"),
                                    dimensions=f"{min(w - 40, 730):g} × {rules.hood_height:g}", module=mods[-1].id))
            if color.loft:
                # có phào nóc: cánh nóc mở ngang thay vì lật lên để không chạm phào (MOLDING-CANH-LAT-001)
                hinge: list[Literal["left", "right", "upper", "base"]] = ["left", "right"] if (h_loft and two) else ["left"] if h_loft else []
                loft_door = [w / 2, w / 2] if (h_loft and two) else [w]
                mods.append(Module(id=id("TN"), type="upper-loft", name=say("name.cabinet.top"), wall=wall, fromCorner=a, width=w, y=c.upperTierSplit,
                                   height=c.cabinetTop - c.upperTierSplit, depth=upper_depth, doors=loft_door, hingeSides=hinge))

    def corner_base(wall: WallSide, type: str, width: float, blind: float, doors: list[float]):
        mods.append(Module(id=id("TD"), type=type, name=say("name.cabinet.blind-corner"), wall=wall, fromCorner=0, width=width, y=0,
                           height=c.baseTop, depth=c.baseDepth, doors=doors, blindCorner=blind))

    def corner_shelf():
        cs = rules.corner_shelf
        mods.append(Module(id="KG1", type="corner-shelf", name=say("name.cabinet.corner-shelf"), wall="corner", backLength=cs.get("back", 600),
                           rightLength=cs.get("right", 600), y=c.upperBottom, height=c.upperTierSplit - c.upperBottom, depth=upper_depth,
                           shelfCount=int(cs.get("shelfCount", 3))))

    def step(do: str, v: dict[str, Any]) -> None:
        wall = cast(WallSide, v.get("wall", "back"))
        if do == "base-run":
            thickness(wall, v["start"], v["length"], v["appliances"], v["front"], v["fridgeAtEnd"], v.get("extras"))
        elif do == "cabinets":
            cabinets(wall, v["start"], v["length"], v["items"])
        elif do == "corner-base":
            corner_base(wall, v["type"], v["width"], v["blind"], v["doors"])
        elif do == "upper-run":
            upper(wall, v["start"], v["end"])
        else:
            corner_shelf()

    notes_built: list[dict] = []
    layout = layout_solver.template(color.geometry_edit, catalog)
    if color.peninsula and layout.peninsula is None and layout.peninsula_uses:  # bán đảo cần một dãy vuông góc để gắn vào
        color = color.model_copy(update={"geometry_edit": layout.peninsula_uses})
        layout = layout_solver.template(layout.peninsula_uses, catalog)
        notes_built.append({"term": say("term.peninsula"), "canonical": "peninsula-layout", "scope": ["whole"], "target": "geometry_edit", "status": "ambiguous",
                            "message": say("note.peninsula-needs-l", layout=layout.id)})
    fridge_width = float(rules.fridge.get("width", 700))
    g, aisle = c.baseDepth, rules.aisle  # lối đi giữa đảo và dãy tủ (NKBA 1067–1220)
    inputs: dict[str, Any] = {"back": color.backWallLength, "right": color.rightWallLength or 0.0, "left": color.leftWallLength or 0.0, "g": g,
                              "upperDepth": upper_depth, "fridge": color.fridge, "lr": fridge_width if color.fridge else 0.0,
                              "islandLength": color.islandLength or 0.0, "aisle": aisle}
    env = layout_solver.plan(layout, inputs, rules, step)
    room = Room(wall=[Wall(id="back", length=float(layout_solver.expr.evaluate(layout.room, env)))]) if layout.room is not None else None
    Wback = float(env.get("W", color.backWallLength))

    def free_run(label: str, z: float, start: float, length: float, blind: float = 0) -> bool:
        """Dãy đặt rời (đảo / bán đảo) song song tường sau, mặt cánh hướng về tường sau."""
        s = start
        if blind:  # đầu sát tường phải: phần góc khuất không cánh để không đụng tủ bên cạnh
            mods.append(Module(id=id("TD"), type="base-drawers", name=label, wall="island", offset=z, fromCorner=s, width=blind + 450, y=0,
                               height=c.baseTop, depth=g, blindCorner=blind, frontSections=_drawers(rules)))
            s += blind + 450
            length -= blind + 450
        for w in layout_solver.split(length, rules) if length >= rules.min_width else []:
            mods.append(Module(id=id("TD"), type="base-drawers", name=label, wall="island", offset=z, fromCorner=s, width=w, y=0,
                               height=c.baseTop, depth=g, frontSections=_drawers(rules)))
            s += w
        return length >= rules.min_width

    if color.island and layout.island is not None:
        start_f, length_f = layout.island
        ln = float(layout_solver.expr.evaluate(length_f, env))
        start = float(layout_solver.expr.evaluate(start_f, {**env, "n": ln}))
        if ln >= 600 and free_run(say("name.cabinet.island"), g + aisle, start, ln):
            notes_built.append({"term": say("term.island"), "canonical": "island", "scope": ["whole"], "target": "module.wall=island", "status": "built",
                                "message": say("note.island-built", length=ln, aisle=aisle)})
        else:
            notes_built.append({"term": say("term.island"), "canonical": "island", "scope": ["whole"], "target": "module.wall=island", "status": "ambiguous",
                                "message": say("note.island-no-room", aisle=aisle)})
    if color.peninsula and layout.peninsula is not None:
        at_f, room_f = layout.peninsula
        Rlen = float(layout_solver.expr.evaluate(at_f, env))
        room_len = float(layout_solver.expr.evaluate(room_f, env))
        ln = min(color.islandLength or 1800, room_len)
        if ln >= g + 750 and free_run(say("name.cabinet.peninsula"), Rlen, 0, ln, blind=g):
            notes_built.append({"term": say("term.peninsula"), "canonical": "peninsula", "scope": ["whole"], "target": "module.wall=island", "status": "built",
                                "message": say("note.peninsula-built", length=ln)})
        else:
            notes_built.append({"term": say("term.peninsula"), "canonical": "peninsula", "scope": ["whole"], "target": "module.wall=island", "status": "ambiguous",
                                "message": say("note.peninsula-no-room")})
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
