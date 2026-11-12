"""KitchenSpec: mô hình tham số của tủ bếp — nguồn sự thật duy nhất.

English field names; legacy Vietnamese-keyed files such as `bep-chu-L-thong-so.json` can be converted with `kitchen.legacy.convert_spec`.
Đơn vị: mm (riêng camera `cameraViews` tính bằng mét, như file gốc).

Quy ước toạ độ (theo file gốc): gốc ở góc trong giữa tường sau và tường phải.
- tường "sau":  tủ chạy theo trục -x, mặt tủ nhìn về +z
- tường "phai": tủ chạy theo trục +z, mặt tủ nhìn về -x
- tường "trai": song song tường phải, đặt tại x = -(dài tường sau), mặt tủ nhìn về +x
`tu` = khoảng cách từ góc dọc theo tường; `y` = cao độ đáy module.
"""
from __future__ import annotations

import re
from typing import Any, Literal, TypedDict, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import NotFound
from .cabinet_types import storey_of
from .words import say

WALLS = ("back", "right", "left")
STOREYS = ("base", "upper", "loft", "tall", "corner")
FACINGS = ("-z", "+z", "-x", "+x")       # direction the doors of a free-standing run look (scene axes); the default "-z" faces the back wall
ORIENT_OF_FACING = {"-z": "island", "+z": "back", "-x": "right", "+x": "left"}   # which wall's frame has the same orientation


MODULE_TYPES = (    # the builtin cabinet types (what the recognizers may answer); a design may use any type of the catalog (kind cabinet-type)
    "base", "base-sink", "base-corner-sink", "base-cooktop", "base-oven", "base-end", "base-drawers",
    "upper", "upper-glass", "upper-open", "upper-hood", "upper-loft",
    "tall-fridge", "tall",
    "corner-shelf",
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Common(_Base):
    plinthHeight: float = Field(default=110, ge=0)
    baseTop: float = Field(default=840, gt=0)
    countertop: float = Field(default=900, gt=0)
    countertopThickness: float = Field(default=60, ge=0)
    baseDepth: float = Field(default=550, gt=0)
    countertopOverhang: float = Field(default=20, ge=0)
    backsplashHeight: Literal["standard", "to-upper", "to-ceiling"] = "standard"
    backsplashHeightMm: float | None = Field(default=None, ge=50, le=3000, description="Backsplash height in mm; overrides backsplashHeight when set")
    wallTilePattern: str | None = Field(default=None, description="How the wall tile is laid (herringbone, running-bond); carried to the 3D file and the image prompt")
    upperBottom: float = Field(default=1530, gt=0)
    upperTierSplit: float = Field(default=2280, gt=0)
    cabinetTop: float = Field(default=2610, gt=0)
    ceiling: float = Field(default=2640, gt=0)
    upperDepth: float = Field(default=320, gt=0)
    doorThickness: float = Field(default=18, gt=0)
    doorGap: float = Field(default=3, ge=0)
    backThickness: float = Field(default=9, gt=0, description="Độ dày tấm hậu (mm)")
    material: dict[str, str] = Field(default_factory=dict, description="base, upper, tall, cornerShelf, carcass, countertop, wallTile, floor, wall")
    handle: "Handle" = Field(default_factory=lambda: Handle())
    handleByStorey: dict[str, "HandleOverride"] | None = Field(
        default=None, description="Partial handle settings per storey (base, upper, loft, tall, corner); overrides `handle`, overridden by Module.handle")

    @field_validator("handleByStorey")
    @classmethod
    def _storeys(cls, v):
        bad = [k for k in (v or {}) if k not in STOREYS]
        if bad:
            raise ValueError(f"handleByStorey: unknown storey {bad}; use one of {', '.join(STOREYS)}")
        return v


class Handle(_Base):
    variant: Literal["bar", "knob", "concealed", "none"] = "bar"  # tay thanh, núm, âm (khoét), không tay (nhấn mở)
    length: float = Field(default=160, ge=0, description="Chiều dài tay thanh (mm)")
    material: str = "Nhôm đen mờ"


class HandleOverride(_Base):
    """Partial handle settings for one storey or one module; unset fields fall back to the next level."""
    variant: Literal["bar", "knob", "concealed", "none"] | None = None
    length: float | None = Field(default=None, ge=0)
    material: str | None = None


class WallOpening(_Base):
    """Lỗ mở trên tường: cửa sổ / cửa đi."""
    type: Literal["window", "entrance"] = "window"
    fromCorner: float = Field(ge=0, description="Khoảng cách từ góc dọc theo tường (mm)")
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    sillHeight: float = Field(default=0, ge=0, description="Cao độ đáy lỗ mở (bậu cửa sổ), cửa đi = 0")


class Wall(_Base):
    id: Literal["back", "right", "left"]
    length: float = Field(gt=0, description="Chiều dài tường (mm)")
    thickness: float = Field(default=100, gt=0, description="Độ dày tường (mm)")
    openings: list[WallOpening] = Field(default_factory=list)


class Room(_Base):
    wall: list[Wall] = Field(default_factory=list)
    walkway: float | None = Field(default=None, description="Khoảng trống phía trước dãy tủ tới vật cản đối diện (mm)")

    def length(self, id: str) -> float | None:
        return next((t.length for t in self.wall if t.id == id), None)


class Run(_Base):
    """An explicit straight run of cabinets standing at any angle. Local axes: s along the run (fromCorner of its modules), d from the back of the
    cabinets to their door face. World = (x, z) + s * (cos yaw, -sin yaw) + d * (sin yaw, cos yaw), yaw in degrees as in three.js rotation.y
    (yaw 0: doors look at +z, s grows towards +x; yaw 180: doors look at -z, s grows towards -x).
"""
    id: str
    x: float = Field(default=0, description="World x of the run origin (s = 0, d = 0), mm, kitchen frame")
    z: float = Field(default=0, description="World z of the run origin, mm, kitchen frame")
    yaw: float = Field(default=0, description="Degrees, three.js rotation.y; the doors look along (sin yaw, cos yaw)")
    purpose: Literal["tv"] | None = Field(default=None, description="tv: a TV wall unit (kitchen/tv_system.py): no worktop, wall tile or kitchen rule. Unset: kitchen cabinets")
    tvLayout: Literal["columns", "shelves", "full"] | None = Field(default=None, description="TV unit only: the layout it was made with (tv_system.STYLES)")
    system: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$", max_length=80,
                               description="Cabinet system the run belongs to: the id of the floorplan element (elements[].id, e.g. furniture_003) it was made "
                                           "against. Unset: the system is worked out from which runs touch (runs.systems)")


class BackPanel(_Base):
    """A panel on the wall behind a TV (TV units, ``tv_system``): along the run from ``s0`` to ``s1`` mm, measured from the start of the
    cabinet that carries it; from ``y0`` to ``y1`` mm above the floor."""
    s0: float
    s1: float
    y0: float
    y1: float

    @model_validator(mode="before")
    @classmethod
    def _old_names(cls, data: Any) -> Any:
        """Revisions saved before 11/11/2026 call ``s0`` / ``s1`` ``from`` / ``to`` (same meaning); they still load."""
        if isinstance(data, dict) and "s0" not in data and "from" in data:
            old = cast("dict[str, Any]", data)
            return {**{k: v for k, v in old.items() if k not in ("from", "to")}, "s0": old["from"], "s1": old.get("to")}
        return data


class _LaidBox(TypedDict):
    type: str
    s: float          # mm along the run from the start of the line / slot it is laid in
    width: float      # mm
    y: float          # mm above the floor
    height: float     # mm
    depth: float      # mm


class LaidModule(_LaidBox, total=False):
    """A cabinet being laid out along a line, before it is added (``run_line.plan_on_line``, ``system_replace.relayout_ops``,
    ``tv_system.layout``, ``run_template``): its box plus what it may carry (``run_line.EXTRA_FIELDS``). Plain JSON data."""
    name: str
    niche: float
    appliance: dict[str, Any]
    appliances: list[dict[str, Any]]
    doors: list[float]
    frontSections: list[dict[str, Any]]
    hingeSides: list[str]
    doorStyle: str
    blindCorner: float
    blindSide: str
    shelfCount: int
    backPanel: dict[str, float]
    material: str


class FrontSection(_Base):
    """Một tầng mặt trước của tủ dưới (xếp từ trên xuống): hộc trống, ngăn kéo hoặc cánh."""
    type: Literal["niche", "drawer", "door"]
    height: float = Field(gt=0)


class Module(_Base):
    id: str
    type: str = "base"
    name: str = ""
    wall: Literal["back", "right", "left", "corner", "island"] = "back"
    offset: float = Field(default=0, ge=0, description="wall='island' only (island / peninsula): door face position of the run in mm. For facing -z / +z (runs along x): distance from the back-wall plane (z); fromCorner is measured from the right-wall plane. For facing -x / +x (runs along z): distance from the right-wall plane towards -x (x = -offset); fromCorner is measured from the back-wall plane")
    facing: Literal["-z", "+z", "-x", "+x"] | None = Field(default=None, description="wall='island' only: direction the doors look in scene axes. Default (null) = -z, towards the back wall. Lets a run stand against any axis-parallel edge of an object and face outward")
    run: str | None = Field(default=None, description="wall='island' only: id of an entry of spec.runs. The module then sits at s = fromCorner in that run's frame (any angle); offset and facing are not used")
    fromCorner: float = Field(default=0, ge=0)
    width: float = Field(default=0, ge=0)
    y: float = Field(default=0, ge=0)
    height: float = Field(gt=0)
    depth: float = Field(gt=0)
    doors: list[float] = Field(default_factory=list)
    blindCorner: float = Field(default=0, ge=0, description="Phần góc khuất không có cánh, tính từ phía góc (mm)")
    endPanel: float = Field(default=0, ge=0, description="Tấm hông hoàn thiện ở đầu xa góc (mm)")
    blindSide: Literal["start", "end"] = Field(default="start", description="Which end of the cabinet the blind corner is at: start = the low-fromCorner end (the corner of a wall row), end = the other one (a run that ENDS in a corner). The end panel is at the opposite end")
    frontSections: list[FrontSection] = Field(default_factory=list)
    niche: float | None = Field(default=None, description="Tủ cao: chiều cao hốc thiết bị tính từ sàn (mm)")
    backLength: float | None = None   # corner-shelf: length of the leg along the back wall
    rightLength: float | None = None  # corner-shelf: length of the leg along the right wall
    turnsInto: str | None = Field(default=None, description="corner-shelf standing in explicit runs: id of the run its SECOND leg lies in. The first leg is the cabinet's own place (run, fromCorner, width) at the END of its run; the second, rightLength long, lies at the START of this run, the two runs meeting in a square inside corner")
    shelfCount: int = 3
    hingeSides: list[Literal["left", "right", "upper", "base"]] = Field(default_factory=list,
        description="Bản lề từng cánh theo thứ tự từ trái sang (nhìn từ trước); trống = tự suy")
    doorStyle: Literal["flat", "frame", "glass"] | None = Field(default=None, description="Cánh phẳng (slab), cánh khung (shaker) hoặc kính")
    material: str | None = Field(default=None, description="Vật liệu mặt trước riêng của module (ghi đè chung.vatLieu theo tầng)")
    handle: HandleOverride | None = Field(default=None, description="Handle settings of this module only; overrides the storey and common handle")
    backPanel: BackPanel | None = Field(default=None, description="TV units: the panel on the wall behind the TV, carried by one console cabinet")
    note: str | None = None

    @property
    def fronts(self) -> tuple[float, float]:
        """The stretch of the cabinet that has doors or drawers, along its row: all of it but the blind corner and the end panel."""
        at_start, at_end = (self.blindCorner, self.endPanel) if self.blindSide == "start" else (self.endPanel, self.blindCorner)
        return self.fromCorner + at_start, self.fromCorner + self.width - at_end

    @property
    def blind_span(self) -> tuple[float, float]:
        f0, f1 = self.fronts
        return (self.fromCorner, f0) if self.blindSide == "start" else (f1, self.fromCorner + self.width)

    @property
    def panel_span(self) -> tuple[float, float]:
        f0, f1 = self.fronts
        return (f1, self.fromCorner + self.width) if self.blindSide == "start" else (self.fromCorner, f0)

    @property
    def orient(self) -> str:
        """Which of back / right / left / island this module's front looks like (a free run takes the orientation of its facing)."""
        if self.run:
            return "back"                      # the run frame is back-wall like: s to the right, d towards the viewer
        return ORIENT_OF_FACING[self.facing or "-z"] if self.wall == "island" else self.wall

    @model_validator(mode="after")
    def _validate(self):
        if self.run and (self.wall != "island" or self.facing):
            raise ValueError(f"{self.id}: run only applies to wall='island' without facing")
        if self.facing and self.wall != "island":
            raise ValueError(f"{self.id}: facing only applies to wall='island'")
        if not self.type:
            raise ValueError(f"{self.id}: type is empty")
        if self.turnsInto and (self.type != "corner-shelf" or not self.run):
            raise ValueError(f"{self.id}: turnsInto only applies to a corner-shelf standing in a run")
        if self.type == "corner-shelf":
            by_runs = bool(self.run and self.turnsInto and self.width > 0 and self.rightLength)
            if not by_runs and (self.wall != "corner" or not self.backLength or not self.rightLength):
                raise ValueError(f"{self.id}: corner-shelf needs wall='corner', backLength and rightLength; or run, width, turnsInto and rightLength")
        elif self.wall == "corner":
            raise ValueError(f"{self.id}: only corner-shelf may be placed at wall='corner'")
        elif self.width <= 0:
            raise ValueError(f"{self.id}: rong phải > 0")
        return self

    @property
    def storey(self) -> str:
        """The storey of the cabinet (base, upper, loft, tall, corner): its type's (catalog kind ``cabinet-type``)."""
        return storey_of(self.type)

    @property
    def endAt(self) -> float:
        return self.fromCorner + self.width


class Appliance(_Base):
    id: str
    name: str = ""
    type: Literal["fridge", "sink", "faucet", "cooktop", "hood", "oven", "light", "tv", "other"] = "other"
    dimensions: str | None = None
    position: str | None = None
    module: str | None = Field(default=None, description="Module chứa thiết bị")
    wall: Literal["back", "right", "left"] | None = None
    center: float | None = Field(default=None, description="Tâm thiết bị, khoảng cách từ góc dọc theo tường (mm); tivi (type tv): tính từ đầu tủ chứa nó, nên đi theo tủ")
    model: str | None = Field(default=None, description="Model id (catalog kind appliance, data/items/appliance.json); none = read from name and dimensions")
    energy: Literal["gas", "induction", "electric", "mixed"] | None = None
    size: dict[str, float] | None = Field(default=None, description="Body size {w, d, h} in mm")
    cutout: dict[str, float] | None = Field(default=None, description="Worktop hole {w, d} in mm (hobs, sinks)")
    mount: Literal["built_in", "freestanding", "wall", "undermount", "topmount"] | None = None

    def numeric_dimensions(self) -> list[float]:
        return [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", self.dimensions or "")]


def _seg_cross(a, b, c, d) -> bool:
    """Hai đoạn ab, cd cắt nhau thật sự (không tính chung đầu mút)."""
    def o(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 1e-9) - (v < -1e-9)
    return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0


class MoldingProfile(_Base):
    """Mặt cắt 2D của phào (mm). Quy ước:
    u = độ nhô ra phía phòng tính từ MẶT TRƯỚC tủ (âm = lùi vào trên nóc / dưới tủ),
    v = chiều cao tính từ ĐƯỜNG CHẠY (phào nóc: nóc tủ; phào chân: sàn).
    Đa giác kín (không lặp điểm đầu), không tự cắt; được chuẩn hóa ngược chiều kim đồng hồ."""
    id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    name: str = ""
    points: list[tuple[float, float]]
    description: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "MoldingProfile":
        pts = [(float(p[0]), float(p[1])) for p in self.points]
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            raise ValueError(f"profile {self.id}: cần ít nhất 3 điểm")
        area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2
        if abs(area) < 1:
            raise ValueError(f"profile {self.id}: diện tích mặt cắt gần 0")
        n = len(pts)
        for i in range(n):
            for j in range(i + 2, n):
                if i == 0 and j == n - 1:
                    continue
                if _seg_cross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                    raise ValueError(f"profile {self.id}: mặt cắt tự cắt (cạnh {i} và {j})")
        if area < 0:
            pts = pts[::-1]
        if min(v for _, v in pts) < -0.5:
            raise ValueError(f"profile {self.id}: v phải ≥ 0 (tính từ đường chạy lên)")
        self.points = pts
        return self

    @property
    def height(self) -> float:
        return max(v for _, v in self.points) - min(v for _, v in self.points)

    @property
    def overhang(self) -> float:
        return max(u for u, _ in self.points)


class Molding(_Base):
    """Phào theo QUY TẮC: đường chạy được tính lại từ module mỗi lần dựng (thêm/bớt tủ thì phào tự theo)."""
    id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    variant: Literal["crown", "base"] = Field(description="crown = phào nóc theo đỉnh tủ; base = phào chân theo sàn")
    profile: str
    wall: list[str] = Field(default_factory=list, description="Trống = mọi tường / dãy có tủ; else wall names (back, right, left) and ids of explicit runs")
    joinGap: float = Field(default=50, ge=0, description="Khe giữa hai tủ ≤ giá trị này thì phào chạy liền qua")
    openEnd: Literal["return-to-wall", "flat-cut"] = Field(default="return-to-wall", description="Đầu hở: quay về tường hoặc cắt phẳng")
    material: str | None = Field(default=None, description="Trống = vật liệu cánh của tầng tủ tương ứng")
    enabled: bool = True
    ignoreCeiling: bool = Field(default=False, description="Người dùng chọn 'để nguyên' khi phào vượt trần")


class ViewAngle(_Base):
    name: str = ""
    position: tuple[float, float, float]
    lookAt: tuple[float, float, float]
    verticalFov: float = Field(default=50, gt=1, lt=170)
    hide: list[str] = Field(default_factory=list, description="Ids of floorplan structures (STRUCT-...) left out of this view because they stand between the camera and the cabinets")


class KitchenSpec(_Base):
    schemaVersion: int = 2
    name: str = say("name.design")
    style: Literal["Modern", "Classic", "Neoclassical", "Transitional", "Industrial", "Minimalist"] = "Modern"
    unit: Literal["mm"] = "mm"
    country: str | None = Field(default=None, description="Mã ISO alpha-2 nơi lắp đặt (VN, US, AU...) — quyết định tiêu chuẩn ưu tiên khi kiểm tra")
    region: str | None = Field(default=None, description="Mã khu vực (SEA, EA, NA, EU, OC, GLOBAL) nếu chưa rõ quốc gia")
    source: str | None = None
    origin: str | None = None
    styleTags: list[str] | None = Field(default=None, description="Style names with no geometry of their own (Scandinavian, Japandi, Farmhouse, Country, Mid-Century Modern, Luxury)")
    renderPreferences: list[str] = Field(default_factory=list, description="Photography / lighting / quality phrases from the creation prompt; read by kitchen.realism")
    aiHints: list[str] | None = Field(default=None, description="English phrases for the image prompt only (e.g. fluted glass, herringbone tile)")
    floorplan: dict[str, Any] | None = Field(default=None, description="Derived room geometry imported from an audited floorplan (mm); the source document is stored once, referenced by floorplan.ref")
    promptInterpretation: list[dict[str, Any]] | None = Field(default=None, description="How each term of the creation prompt was understood: term, canonical, scope, target, status, message")
    common: Common = Field(default_factory=lambda: Common())
    room: Room | None = None
    module: list[Module] = Field(default_factory=list)
    appliances: list[Appliance] = Field(default_factory=list)
    cameraViews: dict[str, ViewAngle] = Field(default_factory=dict)
    moldingProfiles: list[MoldingProfile] = Field(default_factory=list, description="Mặt cắt riêng; preset có sẵn ở kitchen/moldings.py")
    moldings: list[Molding] = Field(default_factory=list)
    idCounters: dict[str, int] = Field(default_factory=dict, description="Highest number handed out per id prefix (TD, TT, TC…); ids are never reused after a module is removed")
    runs: list[Run] = Field(default_factory=list, description="Explicit runs (any angle) that modules with wall='island' and run=<id> stand in")

    @model_validator(mode="after")
    def _unique_ids(self):
        run_ids = [r.id for r in self.runs]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("Trùng mã dãy (run)")
        for m in self.module:
            if m.run and m.run not in run_ids:
                raise ValueError(f"{m.id}: dãy '{m.run}' không có trong runs")
        seen: set[str] = set()
        for m in self.module:
            if m.id in seen:
                raise ValueError(f"Trùng mã module: {m.id}")
            seen.add(m.id)
        mol = [x.id for x in self.moldings]
        if len(mol) != len(set(mol)):
            raise ValueError("Trùng mã phào")
        if set(mol) & seen:
            raise ValueError("Mã phào trùng mã module")
        return self

    def find(self, id: str) -> Module:
        for m in self.module:
            if m.id == id:
                return m
        raise NotFound(f"No module {id!r}", code="module-not-found", params={"id": id})

    def walls_with_modules(self) -> list[str]:
        return [t for t in WALLS if any(m.wall == t for m in self.module)]


def effective_handle(common: Common, module: Module) -> Handle:
    """Handle settings of one module: module override > storey override > common default."""
    data = common.handle.model_dump()
    for override in ((common.handleByStorey or {}).get(module.storey), module.handle):
        if override is not None:
            data.update(override.model_dump(exclude_none=True))
    return Handle.model_validate(data)


def load_spec(data: dict | str) -> KitchenSpec:
    if isinstance(data, str):
        return KitchenSpec.model_validate_json(data)
    return KitchenSpec.model_validate(data)


def dump_spec(spec: KitchenSpec) -> dict[str, Any]:
    return spec.model_dump(mode="json", exclude_none=True)


def to_data(model: BaseModel, exclude_none: bool = False) -> dict[str, Any]:
    """Spec-side value -> plain JSON data (the one place the core turns a model into data; in Rust this is serde)."""
    return model.model_dump(mode="json", exclude_none=exclude_none)


ModelT = TypeVar("ModelT", bound=BaseModel)


def from_data(cls: type[ModelT], data: dict[str, Any]) -> ModelT:
    """Plain JSON data -> validated model of type ``cls`` (the boundary validation; raises pydantic.ValidationError)."""
    return cls.model_validate(data)
