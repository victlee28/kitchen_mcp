"""Bảng thuật ngữ chuẩn + bộ so khớp cho luồng tạo bếp từ mô tả (tiếng Việt có dấu / không dấu, tiếng Anh).

Mỗi mục (E) có: id, loại (kind), danh sách alias (viết có dấu), nhãn chuẩn, giá trị áp vào spec, vùng mặc định (slot),
trạng thái hỗ trợ (built | exported | ai-only | unsupported) và cụm tiếng Anh cho prompt ảnh.

Cách so khớp:
- Chuẩn hoá giữ nguyên độ dài chuỗi (NFC, chữ thường, bỏ dấu, '-' -> ' ', dấu phẩy thập phân -> '.') nên vị trí khớp trên
  chuỗi đã bỏ dấu dùng được trực tiếp trên chuỗi gốc.
- Cụm dài thắng cụm ngắn ("tân cổ điển" thắng "cổ điển", "đảo thác đá" thắng "đảo").
- Alias "yếu" (mờ, đỏ, đen, đá, ốp, kem, be…) chỉ nhận đúng dạng có dấu hoặc dạng gõ hoàn toàn không dấu, để "mở", "đèn",
  "đã", "kèm", "bê tông" không bị hiểu nhầm.
- Câu được tách thành mệnh đề (dấu , ; : . và các từ nối "và/với/and/with"), mỗi mệnh đề tìm từ chỉ phạm vi
  (tủ dưới, tủ trên, mặt bàn, ốp tường, tay nắm…) rồi gắn vật liệu/hoàn thiện vào đúng vùng.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .numeric import round_int
from . import vocab
from .errors import require

STATUSES = ("built", "exported", "ai-only", "unsupported", "ambiguous")
FRONT_SLOTS = ("base", "upper", "tall")


@dataclass(frozen=True)
class E:
    id: str
    kind: str
    aliases: tuple[str, ...]
    label: str = ""
    value: Any = None
    slot: str | None = None        # vùng mặc định khi mệnh đề không nêu phạm vi
    status: str = "built"
    message: str = ""
    ai: str = ""                   # cụm tiếng Anh cho prompt ảnh
    weak: bool = False             # chỉ nhận đúng dạng có dấu hoặc dạng hoàn toàn không dấu
    needs: tuple[str, ...] = ()    # chỉ hiệu lực khi mệnh đề có từ chỉ phạm vi thuộc tập này
    forbid: tuple[str, ...] = ()   # vô hiệu khi mệnh đề có từ chỉ phạm vi thuộc tập này
    wood_plain: str = ""           # (gỗ) nhãn khi đi kèm veneer/laminate…; label dùng khi đứng một mình


def _e(id: str, kind: str, aliases: str, **kw: Any) -> E:
    return E(id=id, kind=kind, aliases=tuple(a.strip() for a in aliases.split("|") if a.strip()), **kw)


# ------------------------------------------------------------------ chuẩn hoá giữ độ dài
def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").lower()


def _fold_char(ch: str) -> str:
    if ch in "-_":
        return " "
    d = unicodedata.normalize("NFD", ch.replace("đ", "d"))
    base = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return base[:1] if base else " "


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu, '-' -> ' ', '2,4' -> '2.4'; độ dài bằng đúng NFC gốc."""
    s = "".join(_fold_char(c) for c in _nfc(text))
    return re.sub(r"(?<=\d),(?=\d)", ".", s)


def _squash(s: str) -> str:
    return re.sub(r"[\s\-_]+", " ", s.strip())


# ------------------------------------------------------------------ bảng thuật ngữ
SCOPES = [  # kind=scope, value = các vùng
    _e("scope.base", "scope", "tủ dưới|tủ bếp dưới|tủ thấp|base cabinets|base cabinet|lower cabinets|lower cabinet|base units", value=("base",)),
    _e("scope.upper", "scope", "tủ trên|tủ treo|tủ tường|wall cabinets|wall cabinet|upper cabinets|upper cabinet|hanging cabinets", value=("upper",)),
    _e("scope.tall", "scope", "tủ cao|tall cabinets|tall cabinet|tall units", value=("tall",)),
    _e("scope.fronts", "scope", "cánh tủ|mặt tủ|tủ bếp|cabinet doors|cabinet door|cabinet fronts|cabinetry|kitchen cabinets|kitchen cabinet",
       value=("base", "upper")),
    _e("scope.countertop", "scope", "mặt bàn|mặt đá|mặt bếp|countertops|countertop|worktop|benchtop|counter top|kitchen counter", value=("countertop",)),
    _e("scope.wallTile", "scope", "ốp tường|ốp bếp|ốp đá|ốp gạch|mảng tường giữa tủ trên và tủ dưới|mảng tường|backsplash|back splash|splashback",
       value=("wallTile",)),
    _e("scope.wallTile.bare", "scope", "ốp", value=("wallTile",), weak=True),
    _e("scope.handle", "scope", "tay nắm|phụ kiện|handles|handle|hardware|knobs|knob|pulls", value=("handle",)),
    _e("scope.floor", "scope", "sàn nhà|sàn|flooring|floor", value=("floor",)),
    _e("scope.wall", "scope", "tường bếp|tường|wall paint", value=("wall",)),
]

STYLES = [  # value = (style cơ sở hoặc None, nhãn tag hoặc None)
    _e("style.modern", "style", "modern|hiện đại", value=("Modern", None), ai="modern"),
    _e("style.minimalist", "style", "minimalist|minimal|tối giản", value=("Minimalist", None), ai="minimalist"),
    _e("style.scandinavian", "style", "scandinavian|scandi|bắc âu", value=("Minimalist", "Scandinavian"),
       ai="Scandinavian style: pale woods, soft white surfaces, simple clean lines, light airy feel"),
    _e("style.japandi", "style", "japandi|wabi sabi|nhật kết hợp bắc âu", value=("Minimalist", "Japandi"),
       ai="Japandi style: calm natural wood, muted warm neutrals, minimal clean lines, handcrafted details"),
    _e("style.industrial", "style", "industrial|công nghiệp", value=("Industrial", None), ai="industrial"),
    _e("style.farmhouse", "style", "farmhouse|farm house|phong cách nông trại|nông trại|nông thôn kiểu mỹ", value=(None, "Farmhouse"),
       ai="farmhouse style: warm, homely, shaker-type doors, natural textures"),
    _e("style.country", "style", "country style|country kitchen|country|phong cách đồng quê|đồng quê", value=(None, "Country"),
       ai="country style: cosy, rustic, warm wood tones"),
    _e("style.classic", "style", "classic|cổ điển", value=("Classic", None), ai="classic"),
    _e("style.neoclassical", "style", "neoclassical|neo classic|neoclassic|tân cổ điển", value=("Neoclassical", None), ai="neoclassical"),
    _e("style.transitional", "style", "transitional|giao thoa cổ điển và hiện đại|giao thoa", value=("Transitional", None), ai="transitional"),
    _e("style.midcentury", "style", "mid century modern|mid century|phong cách giữa thế kỷ|giữa thế kỷ", value=("Modern", "Mid-Century Modern"),
       ai="mid-century modern style: warm walnut tones, tapered details, simple geometric forms"),
    _e("style.luxury", "style", "luxury|high end|sang trọng|cao cấp", value=(None, "Luxury"),
       ai="luxury high-end finish: premium materials, refined detailing"),
]

LAYOUTS = [  # value = "I" | "L" | tên cấu trúc chưa hỗ trợ
    _e("layout.I", "layout", "chữ i|bếp thẳng|một dãy|một vách|straight kitchen|i shaped|i shape|single wall", value="I"),
    _e("layout.L", "layout", "chữ l|bếp góc|l shaped kitchen|l shaped|l shape|hình l", value="L"),
    _e("layout.U", "layout", "chữ u|u shaped kitchen|u shaped|u shape|hình u|ba vách|ba dãy", value="U"),
]

FEATURES = [  # kind "feature": adds geometry on top of the chosen layout; value = Template field set to True
    _e("feat.island", "feature", "đảo thác đá|waterfall island|waterfall edge|waterfall|đá chảy xuống cạnh đảo", value="island",
       message="Đã dựng đảo bếp; cạnh đá thác chỉ truyền cho ảnh AI.", ai="waterfall countertop edge running down the island sides"),
    _e("feat.island2", "feature", "đảo bếp|kitchen island|trên đảo|over the island|above the island|island", value="island"),
    _e("feat.peninsula", "feature", "bán đảo|peninsula|đảo nối liền với dãy tủ", value="peninsula",
       message="Bán đảo gắn vào cuối dãy tường phải (cần bếp chữ L hoặc U)."),
]

STRUCTURE = [
    _e("struct.loft", "loft", "tủ kịch trần|kịch trần|tủ đụng trần|đụng trần|tủ nóc|floor to ceiling cabinets|floor to ceiling cabinet|"
                              "full height cabinets|full height cabinet", value=True, forbid=("wallTile",)),
    _e("struct.openshelf", "feature", "open shelving|open shelves|open shelf|kệ mở|kệ không cánh|đợt không cánh", value="openShelf",
       message="Thay tủ trên ngay trên chậu (hoặc tủ trên cuối dãy) bằng kệ mở."),
]

DOORS = [  # value = doorStyle; slot = vùng mặc định
    _e("door.shaker", "door", "shaker style|cánh shaker|shaker|cánh pano huỳnh|pano huỳnh|cánh khung", value="frame", slot="fronts",
       ai="Shaker-style framed doors with a recessed centre panel"),
    _e("door.flat", "door", "flat panel|slab|cánh phẳng|cánh slab", value="flat", slot="fronts", ai="flat slab doors without frames"),
    _e("door.fluted", "door", "kính sọc|fluted glass|reeded glass|kính gợn sóng", value="glass", slot="upper",
       message="Dựng cánh kính; kiểu sọc/gợn sóng chỉ truyền cho ảnh AI.", ai="fluted (reeded) glass in the cabinet doors"),
    _e("door.glass", "door", "glass front|cánh kính|tủ kính|kính trong", value="glass", slot="upper", ai="glass-front cabinet doors"),
]

HANDLEVAR = [  # value = Handle.variant
    _e("handle.none", "handlevar", "handleless|push to open|không tay nắm|không có tay nắm", value="none", ai="handleless push-to-open fronts"),
    _e("handle.concealed", "handlevar", "finger pull|rãnh âm|cắm vát|tay nắm âm|tay âm", value="concealed", ai="integrated finger-pull grooves instead of handles"),
]

# vật liệu: nhóm "construction" (cách hoàn thiện cánh) / "wood" / "stone" / "tile" / "metal" / "finish" / "detail"
MATERIALS = [
    _e("mat.veneer", "construction", "wood veneer|veneer|gỗ lạng|veneer gỗ", label="Veneer", slot="base"),
    _e("mat.acrylic", "construction", "acrylic|cánh acrylic", label="Acrylic", slot="base"),
    _e("mat.lacquermatte", "construction", "matte lacquer|sơn lacquer mờ|lacquer mờ|sơn mờ", label="Sơn lacquer mờ", slot="base"),
    _e("mat.lacquer", "construction", "lacquer|sơn lacquer", label="Sơn lacquer", slot="base"),
    _e("mat.paintgloss", "construction", "sơn bóng", label="Sơn bóng", slot="base"),
    _e("mat.laminate", "construction", "laminate", label="Laminate", slot="base"),
    _e("mat.melamine", "construction", "melamine", label="Melamine", slot="base"),
    _e("wood.naturaloak", "wood", "natural oak|sồi tự nhiên", label="Sồi tự nhiên", wood_plain="sồi tự nhiên", slot="base"),
    _e("wood.oak", "wood", "oak|sồi", label="Laminate vân gỗ sồi sáng", wood_plain="sồi", slot="base"),
    _e("wood.walnut", "wood", "walnut|óc chó", label="Gỗ óc chó", wood_plain="óc chó", slot="base"),
    _e("wood.teak", "wood", "teak|gỗ giá tỵ|giá tỵ", label="Gỗ teak", wood_plain="teak", slot="base"),
    _e("wood.ash", "wood", "ash|tần bì", label="Gỗ tần bì", wood_plain="tần bì", slot="base"),
    _e("wood.cherry", "wood", "cherry|xoan đào", label="Gỗ xoan đào", wood_plain="xoan đào", slot="base"),
    _e("wood.generic", "wood", "wood|gỗ", label="Gỗ", wood_plain="gỗ", slot="base"),
    _e("stone.marble", "stone", "đá marble|đá cẩm thạch|marble|cẩm thạch", label="Đá marble", slot="countertop"),
    _e("stone.quartz", "stone", "đá quartz|đá thạch anh|quartz|thạch anh", label="Quartz", slot="countertop"),
    _e("stone.terrazzo", "stone", "đá terrazzo|đá hạt|terrazzo", label="Terrazzo", slot="countertop"),
    _e("stone.granite", "stone", "đá granite|granite", label="Đá granite", slot="countertop"),
    _e("stone.generic", "stone", "đá|stone", label="Đá nhân tạo", slot="countertop", weak=True),
    _e("tile.zellige", "tile", "gạch zellige|zellige|gạch gốm thủ công", label="Gạch Zellige", slot="wallTile"),
    _e("tile.subway", "tile", "subway tile|gạch subway|gạch thẻ|subway", label="Gạch thẻ", slot="wallTile"),
    _e("tile.generic", "tile", "gạch|tile", label="Gạch", slot="wallTile"),
    _e("metal.brass", "metal", "brushed brass|đồng thau xước|đồng xước|đồng thau|brass", label="Đồng thau xước"),
    _e("metal.steel", "metal", "stainless steel|stainless|inox", label="Inox"),
    _e("metal.blackhw", "metal", "matte black hardware|phụ kiện đen mờ|tay nắm đen mờ", label="Đen mờ", slot="handle"),
    _e("metal.black", "metal", "matte black", label="Đen mờ"),
    _e("finish.mirror", "finish", "bóng gương|mirror finish|high gloss", label="bóng gương"),
    _e("finish.gloss", "finish", "glossy finish|glossy|gloss|bóng", label="bóng"),
    _e("finish.matte", "finish", "matte finish|matte|mờ", label="mờ", weak=True),
    _e("detail.cloud", "detail", "vân mây|cloudy veining", label="vân mây"),
]

_NOT3D = "Chỉ mô tả cho ảnh AI; chưa có trong mô hình 3D và file Three.js."
PHOTO = [  # kind=photo: thuật ngữ ảnh/ánh sáng/thiết bị lắp đặt -> spec.renderPreferences (kitchen.realism đưa vào prompt ảnh)
    _e("photo.digest", "photo", "architectural digest photography|architectural digest|ảnh nội thất kiểu tạp chí kiến trúc|ảnh tạp chí kiến trúc",
       status="ai-only", ai="editorial architectural interior photography", message="Phong cách chụp: chỉ cho ảnh AI."),
    _e("photo.wide", "photo", "wide angle shot|wide angle|góc chụp rộng|góc rộng", status="ai-only", ai="wide-angle architectural view",
       message="Góc máy: chỉ cho ảnh AI; góc nhìn 3D chọn ở mục camera."),
    _e("photo.eye", "photo", "eye level shot|eye level|ngang tầm mắt", status="ai-only", ai="eye-level camera angle",
       message="Góc máy: chỉ cho ảnh AI; góc nhìn 3D chọn ở mục camera."),
    _e("photo.8k", "photo", "8k resolution|độ chi tiết cao|8k", status="ai-only", ai="high-resolution fine material detail",
       message="Hiểu là yêu cầu mức chi tiết; không đổi kích thước ảnh đầu ra."),
    _e("photo.engine", "photo", "unreal engine 5 render|unreal engine 5|unreal engine|octane render|octane", status="ai-only",
       ai="high-quality physically based lighting and materials",
       message="Hiểu là yêu cầu chất lượng ánh sáng/vật liệu; ảnh không thật sự được render bằng engine đó."),
    _e("photo.daylight", "photo", "natural daylight streaming through windows|nắng tự nhiên chiếu qua cửa sổ|natural daylight", status="ai-only",
       ai="natural daylight streaming through windows", message="Ánh sáng: chỉ cho ảnh AI."),
    _e("photo.real", "photo", "photorealistic|ultra realistic|ảnh chân thực", status="ai-only", ai="photorealistic interior photography",
       message="Ảnh AI vốn luôn yêu cầu ảnh chân thực."),
    _e("photo.led", "photo", "under cabinet led strip|under cabinet led|led dây giấu dưới tủ|led dây dưới tủ treo|led dây dưới tủ|đèn led dưới tủ|đèn led hắt backsplash|đèn led hắt",
       status="ai-only", ai="under-cabinet LED strip lighting", message=_NOT3D),
    _e("photo.pendant", "photo", "pendant lights|pendant light|đèn thả trần|đèn thả", status="ai-only",
       ai="pendant lights", message=_NOT3D),
    _e("photo.recessed", "photo", "recessed spotlights|recessed spotlight|recessed lights|spotlight âm trần|đèn âm trần", status="ai-only",
       ai="recessed ceiling spotlights", message=_NOT3D),
    _e("photo.track", "photo", "track lighting|đèn rọi ray|đèn ray", status="ai-only", ai="track lighting", message=_NOT3D),
    _e("photo.warm", "photo", "warm ambient lighting|ánh sáng vàng ấm|ánh sáng nền ấm", status="ai-only", ai="warm ambient lighting",
       message="Tông ánh sáng: chỉ cho ảnh AI; ánh sáng mặc định chọn ở bước tạo ảnh."),
    _e("photo.hood", "photo", "integrated range hood|máy hút mùi âm tủ|máy hút mùi giấu kín", status="ai-only", ai="integrated concealed range hood",
       message="Kiểu lắp đặt âm tủ chưa được lưu trong thiết kế; chỉ mô tả cho ảnh AI."),
    _e("photo.builtin", "photo", "built in appliances|built in appliance|thiết bị âm tủ|lò nướng âm tủ|lò vi sóng âm tủ", status="ai-only",
       ai="built-in integrated appliances", message="Kiểu lắp đặt âm tủ chưa được lưu trong thiết kế; chỉ mô tả cho ảnh AI."),
    _e("photo.seamless", "photo", "seamless integration|thiết bị liền mạch", status="ai-only", ai="seamlessly integrated appliances",
       message="Chỉ mô tả cho ảnh AI."),
]

FRIDGE = [
    _e("fridge.builtin", "fridge", "built in fridge|integrated refrigerator|tủ lạnh âm tủ", value=True, ai="built-in integrated refrigerator",
       message="Tủ lạnh có trong thiết kế; kiểu lắp âm tủ chưa được lưu riêng, chỉ mô tả cho ảnh AI."),
    _e("fridge.plain", "fridge", "refrigerator|fridge", value=True),
]

PATTERNS = [  # value = tên kiểu xếp gạch (chỉ lưu + truyền cho ảnh AI)
    _e("pattern.herringbone", "pattern", "herringbone|gạch xếp xương cá|xếp xương cá|xương cá", value="herringbone", status="exported",
       ai="wall tiles laid in a herringbone pattern", message="Kiểu xếp xương cá ghi vào thiết kế/file 3D và prompt ảnh; mô hình 3D chưa vẽ từng viên gạch."),
    _e("pattern.runningbond", "pattern", "running bond|xếp so le|gạch xếp so le", value="running-bond", status="exported",
       ai="wall tiles laid in a staggered running-bond pattern", message="Kiểu xếp so le ghi vào thiết kế/file 3D và prompt ảnh; mô hình 3D chưa vẽ từng viên gạch."),
]

BSHEIGHT = [  # value = backsplashHeight
    _e("bs.toupper", "bsheight", "ốp lên sát tủ trên|lên sát tủ trên|sát tủ trên|tới tủ trên|to the upper cabinets|to the wall cabinets|"
                                  "up to the wall cabinets|up to the upper cabinets", value="to-upper", needs=("wallTile",)),
    _e("bs.toceiling", "bsheight", "ốp tới trần|ốp lên trần|tới trần|lên trần|kịch trần|to the ceiling|full height backsplash|full height", value="to-ceiling",
       needs=("wallTile",)),
]

COLOR_WEAK = {"đỏ", "đen", "cam", "tím", "kem", "be"}  # dạng không dấu trùng từ thường
_EN_EXTRA = {"xám": "gray"}
COLORS = [_e(f"color.{k}", "color", "|".join([k, *([_en] if _en else []), *([_EN_EXTRA[k]] if k in _EN_EXTRA else [])]), label=k, value=hx,
             weak=(k in COLOR_WEAK)) for k, hx, _en in vocab.COLORS]

ALL: list[E] = [*SCOPES, *STYLES, *LAYOUTS, *FEATURES, *STRUCTURE, *DOORS, *HANDLEVAR, *MATERIALS, *PATTERNS, *BSHEIGHT, *PHOTO, *FRIDGE, *COLORS]
BY_ID = {e.id: e for e in ALL}
TAG_PHRASES = {e.value[1]: e.ai for e in STYLES if e.value[1] and e.ai}
PATTERN_PHRASES = {e.value: e.ai for e in PATTERNS}
_NUMU = r"(\d+(?:\.\d+)?)\s*(mm|cm|m)(?![a-z0-9])"
_HEIGHT_NUM = re.compile(r"(?:cao|height|high|len|toi|up to|to)\s*(?:khoang\s*)?" + _NUMU + r"|" + _NUMU + r"\s*(?:cao|high)")


# ------------------------------------------------------------------ so khớp
@dataclass
class M:
    start: int
    end: int
    e: E
    raw: str
    order: int = 0


def _alias_forms(alias: str) -> set[str]:
    return {_squash(_nfc(alias)), _squash(fold(alias))}


_PATTERNS: list[tuple[re.Pattern[str], E, set[str] | None]] = []
for _e_ in ALL:
    for _a in _e_.aliases:
        pat = re.compile(r"(?<![a-z0-9])" + r"\s+".join(re.escape(w) for w in fold(_a).split()) + r"(?![a-z0-9])")
        _PATTERNS.append((pat, _e_, _alias_forms(_a) if _e_.weak else None))


def _scan(f: str, raw: str) -> list[M]:
    out: list[M] = []
    for pat, e, forms in _PATTERNS:
        for m in pat.finditer(f):
            r = raw[m.start():m.end()]
            if forms is not None and _squash(r) not in forms:
                continue
            out.append(M(m.start(), m.end(), e, r))
    return out


def _resolve(cands: list[M], taken: list[M] | None = None) -> list[M]:
    chosen = list(taken or [])
    for m in sorted(cands, key=lambda m: (-(m.end - m.start), m.start)):
        if all(m.end <= c.start or m.start >= c.end for c in chosen):
            chosen.append(m)
    return chosen


_SPLIT = re.compile(r"[,;:\n]|(?<!\d)\.(?!\d)|\s(?:va|and|voi|with|plus)\s|\s\+\s")


def _clauses(f: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    last = 0
    for m in _SPLIT.finditer(f):
        out.append((last, m.start()))
        last = m.end()
    out.append((last, len(f)))
    return [(a, b) for a, b in out if b > a]


# ------------------------------------------------------------------ kết quả
@dataclass
class Result:
    updates: dict[str, Any] = field(default_factory=dict[str, Any])       # trường của KitchenTemplate
    items: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])   # bảng diễn giải
    blank: list[tuple[int, int]] = field(default_factory=list[tuple[int, int]])  # đoạn đã dùng cho số đo (che khỏi regex số)

    def mask(self, text: str) -> str:
        t = _nfc(text)
        for a, b in self.blank:
            t = t[:a] + " " * (b - a) + t[b:]
        return t


def _item(m: M | None, e: E | None, canonical: str, scope: list[str] | str, target: str, status: str | None = None, message: str | None = None) -> dict[str, Any]:
    e = e or (m.e if m else None)
    return {"term": (m.raw if m else ""), "id": e.id if e else "", "kind": e.kind if e else "", "canonical": canonical,
            "scope": scope if isinstance(scope, list) else [scope], "target": target,
            "status": status or (e.status if e else "built"), "message": message if message is not None else (e.message if e else "")}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _compose(ms: list[M], slots: list[str]) -> str | None:
    """Ghép tên vật liệu từ các mục trong một đoạn (theo thứ tự xuất hiện). None nếu không có gì dùng được."""
    rank = {"construction": 0, "wood": 1, "stone": 2, "tile": 2, "metal": 2, "color": 3, "finish": 4, "detail": 5}
    ms = sorted(ms, key=lambda m: (rank.get(m.e.kind, 9), m.start))
    kinds = {m.e.kind for m in ms}
    has_con = "construction" in kinds
    parts: list[str] = []

    def add(x: str):
        if x and x.lower() not in {p.lower() for p in parts}:
            parts.append(x)
    colors = [m.e.label for m in ms if m.e.kind == "color"]
    stone_specific = [m for m in ms if m.e.kind == "stone" and m.e.id != "stone.generic"]
    wood_specific = any(m.e.kind == "wood" and m.e.id != "wood.generic" for m in ms)
    for m in ms:
        e = m.e
        if e.kind == "construction":
            add(e.label)
        elif e.kind == "wood":
            if e.id == "wood.generic" and wood_specific:
                continue
            if has_con:
                add(e.wood_plain)
            elif e.id == "wood.oak" and not colors:
                add(e.label)                     # "sồi" đứng một mình = tên cũ của dự án
            else:
                add("Gỗ " + e.wood_plain if e.id != "wood.generic" else "Gỗ")
        elif e.kind == "stone":
            if e.id == "stone.generic" and stone_specific:
                continue
            add(e.label)
        elif e.kind in ("tile", "metal", "color", "finish", "detail"):
            add(e.label)
    if not parts:
        return None
    res = " ".join(parts)
    if "wallTile" in slots and not any(m.e.kind in ("stone", "tile") for m in ms):
        res = "Đá " + res                       # "ốp đá trắng" -> "Đá trắng"
    if "countertop" in slots and not (stone_specific or any(m.e.kind in ("stone", "tile") for m in ms)):
        res = "Đá nhân tạo " + res          # "mặt bàn trắng" -> "Đá nhân tạo trắng"
    if res == "Đá granite":
        res = "Đá granite tối"
    return _cap(res) if res[:1].islower() else res


def interpret(text: str) -> Result:
    raw = _nfc(text)
    f = fold(text)
    res = Result()
    items = res.items
    # 1. khớp không điều kiện
    base = [m for m in _scan(f, raw) if not (m.e.needs or m.e.forbid)]
    cond = [m for m in _scan(f, raw) if (m.e.needs or m.e.forbid)]
    chosen = _resolve(base)
    # 2. điều kiện theo phạm vi của mệnh đề
    clauses = _clauses(f)
    def scopes_in(c: tuple[int, int]) -> list[M]:
        return [m for m in chosen if m.e.kind == "scope" and c[0] <= m.start and m.end <= c[1]]
    keep: list[M] = []
    for m in cond:
        c = next((c for c in clauses if c[0] <= m.start and m.end <= c[1]), (0, len(f)))
        sc = {s for x in scopes_in(c) for s in x.e.value}
        if (not m.e.needs or sc & set(m.e.needs)) and not (sc & set(m.e.forbid)):
            keep.append(m)
    # điều kiện thắng khi trùng chỗ với mục không điều kiện
    for m in keep:
        chosen = [c for c in chosen if c.end <= m.start or c.start >= m.end]
    chosen = _resolve(keep, chosen)
    for i, m in enumerate(sorted(chosen, key=lambda m: m.start)):
        m.order = i
    chosen.sort(key=lambda m: m.start)

    def clause_of(m: M) -> tuple[int, int]:
        return next((c for c in clauses if c[0] <= m.start and m.end <= c[1]), (0, len(f)))

    # 3. bố cục
    layouts = [m for m in chosen if m.e.kind == "layout"]
    for m in layouts:
        if m.e.status == "unsupported":
            items.append(_item(m, None, m.e.value, "whole", "geometry_edit"))
    sup = [m for m in layouts if m.e.status != "unsupported"]
    if sup:
        pick = sup[-1]
        res.updates["geometry_edit"] = pick.e.value
        for m in sup:
            items.append(_item(m, None, m.e.value, "whole", "geometry_edit", message="" if m is pick else f"Có nhiều bố cục; dùng '{pick.e.value}' (nêu sau cùng)."))
    elif any(m.e.status == "unsupported" for m in layouts):
        items.append(_item(None, None, "I", "whole", "geometry_edit", "ambiguous",
                           "Không dựng được bố cục bạn mô tả nên đã tạo bếp chữ I mặc định; thiết kế này KHÔNG phải bố cục đó."))
    # 4. phong cách
    smatch = [m for m in chosen if m.e.kind == "style"]
    bases = [m for m in smatch if m.e.value[0]]
    tags: list[str] = []
    if bases:
        pick = bases[-1]
        res.updates["style"] = pick.e.value[0]
    for m in smatch:
        st, tag = m.e.value
        if st:
            msg = ""
            if len({b.e.value[0] for b in bases}) > 1 and m is not bases[-1]:
                msg = f"Nhiều phong cách; hình học theo '{bases[-1].e.value[0]}' (nêu sau cùng)."
            if tag:
                msg = (msg + " " if msg else "") + f"Hình học theo {st}; nhãn {tag} ghi thêm cho prompt ảnh."
            items.append(_item(m, None, st, "whole", "style", "ambiguous" if msg.startswith("Nhiều") else "built", msg))
        if tag and tag not in tags:
            tags.append(tag)
            items.append(_item(m, None, tag, "whole", "styleTags", "exported",
                               "Ghi vào thiết kế, file 3D và prompt ảnh; không đổi hình học. Vật liệu đi kèm cần nêu riêng (vd 'gỗ sáng')."))
    if tags:
        res.updates["styleTags"] = tags
    # 5. kịch trần, kệ mở
    for m in chosen:
        if m.e.kind == "loft":
            res.updates["loft"] = True
            items.append(_item(m, None, "tủ nóc / kịch trần", "whole", "loft"))
        elif m.e.kind == "unsupported":
            items.append(_item(m, None, m.e.value, "whole", "-"))
        elif m.e.kind == "feature":
            if res.updates.get(m.e.value):
                continue  # đảo nêu hai lần (vd "đảo bếp ... trên đảo") chỉ ghi một mục
            res.updates[m.e.value] = True
            items.append(_item(m, None, m.e.value, "whole", m.e.value, "built", m.e.message))
            if m.e.ai:
                res.updates.setdefault("aiHints", []).append(m.e.ai)
        elif m.e.kind == "photo":
            res.updates.setdefault("renderPreferences", []).append(m.e.ai)
            items.append(_item(m, None, m.e.ai, "image", "renderPreferences"))
        elif m.e.kind == "fridge":
            res.updates["fridge"] = True
            if m.e.ai:
                res.updates.setdefault("renderPreferences", []).append(m.e.ai)
            items.append(_item(m, None, "tủ lạnh", "whole", "fridge", "built"))
    # 6. tay nắm không / âm
    for m in chosen:
        if m.e.kind == "handlevar":
            res.updates["handleVariant"] = m.e.value
            items.append(_item(m, None, m.e.value, "handle", "common.handle.variant"))
            if m.e.ai:
                res.updates.setdefault("aiHints", []).append(m.e.ai)
    # 7. cánh
    door_style: dict[str, str] = {}
    for m in chosen:
        if m.e.kind != "door":
            continue
        c = clause_of(m)
        sl = sorted(scopes_in(c), key=lambda x: x.start)
        near = ([x for x in sl if x.start < m.start] or sl or [None])[-1] if any(x.start < m.start for x in sl) else (sl[0] if sl else None)
        sc = list(near.e.value) if near is not None else []
        slots = [s for s in FRONT_SLOTS if s in sc] or (list(("base", "upper", "tall")) if m.e.slot == "fronts" else [require(m.e.slot, f"{m.e.id}.slot")])
        for s in slots:
            door_style[s] = m.e.value
        items.append(_item(m, None, m.e.value, slots, "module.doorStyle", message=m.e.message))
        if m.e.ai:
            res.updates.setdefault("aiHints", []).append(m.e.ai)
    if door_style:
        res.updates["doorStyle"] = door_style
    # 8. kiểu xếp gạch
    for m in chosen:
        if m.e.kind == "pattern":
            res.updates["wallTilePattern"] = m.e.value
            res.updates.setdefault("aiHints", []).append(m.e.ai)
            items.append(_item(m, None, m.e.value, "wallTile", "common.wallTilePattern"))
    # 9. chiều cao ốp
    for m in chosen:
        if m.e.kind == "bsheight":
            res.updates["backsplashHeight"] = m.e.value
            items.append(_item(m, None, m.e.value, "wallTile", "common.backsplashHeight"))
    for c in clauses:
        sc = {s for x in scopes_in(c) for s in x.e.value}
        if "wallTile" in sc and "backsplashHeight" not in res.updates:
            seg = f[c[0]:c[1]]
            hm = _HEIGHT_NUM.search(seg)
            if hm:
                g = [x for x in hm.groups() if x is not None]
                val, unit = float(g[0]), g[1]
                mm = val * {"mm": 1, "cm": 10, "m": 1000}[unit]
                span = (c[0] + hm.start(), c[0] + hm.end())
                res.blank.append(span)
                if 50 <= mm <= 3000:
                    res.updates["backsplashHeightMm"] = round_int(mm)
                    items.append({"term": raw[span[0]:span[1]], "id": "bs.mm", "kind": "bsheight", "canonical": f"{round_int(mm)} mm",
                                  "scope": ["wallTile"], "target": "common.backsplashHeightMm", "status": "built", "message": ""})
                else:
                    items.append({"term": raw[span[0]:span[1]], "id": "bs.mm", "kind": "bsheight", "canonical": f"{round_int(mm)} mm", "scope": ["wallTile"],
                                  "target": "common.backsplashHeightMm", "status": "ambiguous", "message": "Chiều cao ốp ngoài khoảng 50–3000 mm nên bỏ qua."})
    # che đoạn chiều cao ốp dạng từ (đã khớp bsheight) khỏi regex số
    # 10. vật liệu theo mệnh đề / đoạn
    material: dict[str, str] = {}
    for c in clauses:
        in_c = [m for m in chosen if c[0] <= m.start and m.end <= c[1]]
        scs = sorted([m for m in in_c if m.e.kind == "scope"], key=lambda m: m.start)
        mats = [m for m in in_c if m.e.kind in ("construction", "wood", "stone", "tile", "metal", "finish", "detail", "color")]
        if not mats:
            continue
        segs: list[tuple[list[str], str, list[M]]] = []   # (vùng, từ chỉ phạm vi, mục)
        if scs:
            bounds = [scs[0].start] + [s.start for s in scs[1:]] + [c[1]]
            for i, s in enumerate(scs):
                lo = c[0] if i == 0 else bounds[i]
                hi = bounds[i + 1]
                segs.append((list(s.e.value), s.raw, [m for m in mats if lo <= m.start < hi]))
        else:
            segs.append(([], "", mats))
        for slots, _sraw, ms in segs:
            if not ms:
                continue
            guessed = ""
            main = next((m for m in sorted(ms, key=lambda m: m.start) if m.e.kind not in ("color", "finish", "detail")), None)
            if not slots:
                if main is not None:
                    slots = [main.e.slot] if main.e.slot else []
                    guessed = (f"Không nêu phạm vi nên áp cho '{slots[0]}' (đoán theo loại vật liệu)."
                               if slots and main.e.kind not in ("tile", "metal") else "")
                else:
                    cols = [m.e.label for m in ms if m.e.kind == "color"]
                    if cols and cols[0] == "trắng":
                        slots, guessed = ["upper"], "Không nêu phạm vi nên áp màu trắng cho tủ trên (đoán)."
                    else:
                        for m in ms:
                            if len(m.e.label) > 4:   # màu ngắn (ghi, kem, be…) quá dễ trùng từ thường: không báo
                                items.append(_item(m, None, m.e.label, "?", "-", "ambiguous", "Chưa rõ áp cho vùng nào; hãy nêu 'tủ dưới…', 'mặt bàn…', 'tay nắm…'."))
                        continue
            if main is not None and main.e.kind == "metal" and "handle" not in slots:
                for m in ms:
                    items.append(_item(m, None, m.e.label, slots, "-", "ambiguous",
                                       "Kim loại chỉ áp cho tay nắm khi nêu rõ ('tay nắm đồng thau xước'); chưa áp lên các vùng khác."))
                continue
            label = _compose(ms, slots)
            if not label:
                continue
            for s in slots:
                if s == "handle":
                    res.updates["handleMaterial"] = label
                else:
                    material[s] = label
            term = " ".join(m.raw for m in sorted(ms, key=lambda m: m.start))
            first = sorted(ms, key=lambda m: m.start)[0]
            it = _item(first, first.e, label, slots, "common.handle.material" if slots == ["handle"] else "common.material." + "/".join(slots), "built", guessed)
            it["term"] = term
            items.append(it)
    if material:
        res.updates["material"] = material
    # gom mục trùng (cùng term + target)
    seen: set[tuple[Any, Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        k = (it["term"], it["id"], it["target"])
        if k not in seen:
            seen.add(k)
            out.append(it)
    res.items = out
    return res


def notes(items: list[dict[str, Any]]) -> list[str]:
    """Ghi chú dạng chữ cho những mục chưa dựng được hoặc cần lưu ý."""
    return [f"[{i['status']}] {i['term'] or i['canonical']}: {i['message']}" for i in items if i["message"] and i["status"] != "built"]


def tag_phrases(tags: list[str] | None) -> list[str]:
    return [TAG_PHRASES[t] for t in (tags or []) if t in TAG_PHRASES]
