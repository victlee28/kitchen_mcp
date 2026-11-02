"""KitchenSpec: mô hình tham số của tủ bếp — nguồn sự thật duy nhất.

Giữ nguyên tên trường tiếng Việt như file `bep-chu-L-thong-so.json` để đọc thẳng file cũ.
Đơn vị: mm (riêng camera `gocNhin` tính bằng mét, như file gốc).

Quy ước toạ độ (theo file gốc): gốc ở góc trong giữa tường sau và tường phải.
- tường "sau":  tủ chạy theo trục -x, mặt tủ nhìn về +z
- tường "phai": tủ chạy theo trục +z, mặt tủ nhìn về -x
- tường "trai": song song tường phải, đặt tại x = -(dài tường sau), mặt tủ nhìn về +x
`tu` = khoảng cách từ góc dọc theo tường; `y` = cao độ đáy module.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TUONG = ("sau", "phai", "trai")
LOAI_MODULE = (
    "duoi", "duoi-chau", "duoi-chau-goc", "duoi-bep", "duoi-lo", "duoi-cuoi", "duoi-ngan-keo",
    "tren", "tren-kinh", "tren-hut-mui", "tren-noc",
    "cao-tu-lanh", "cao",
    "ke-goc",
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Chung(_Base):
    lenChan: float = 110
    deMatDa: float = 840
    matDa: float = 900
    dayMatDa: float = 60
    sauTuDuoi: float = 550
    nhoMatDa: float = 20
    dayTuTren: float = 1530
    chiaTangTren: float = 2280
    dinhTu: float = 2610
    tran: float = 2640
    sauTuTren: float = 320
    dayCanh: float = 18
    kheCanh: float = 3
    dayHau: float = Field(9, gt=0, description="Độ dày tấm hậu (mm)")
    vatLieu: dict[str, str] = Field(default_factory=dict, description="tuDuoi, tuTren, tuCao, keGoc, than, matDa, opTuong, san, tuong")
    tayNam: "TayNam" = Field(default_factory=lambda: TayNam())


class TayNam(_Base):
    kieu: Literal["thanh", "num", "am", "khong"] = "thanh"  # tay thanh, núm, âm (khoét), không tay (nhấn mở)
    dai: float = Field(160, ge=0, description="Chiều dài tay thanh (mm)")
    vatLieu: str = "Nhôm đen mờ"


class LoTuong(_Base):
    """Lỗ mở trên tường: cửa sổ / cửa đi."""
    loai: Literal["cua-so", "cua-di"] = "cua-so"
    tu: float = Field(ge=0, description="Khoảng cách từ góc dọc theo tường (mm)")
    rong: float = Field(gt=0)
    cao: float = Field(gt=0)
    caoBauCua: float = Field(0, ge=0, description="Cao độ đáy lỗ mở (bậu cửa sổ), cửa đi = 0")


class Tuong(_Base):
    ma: Literal["sau", "phai", "trai"]
    dai: float = Field(gt=0, description="Chiều dài tường (mm)")
    day: float = Field(100, gt=0, description="Độ dày tường (mm)")
    lo: list[LoTuong] = Field(default_factory=list)


class Phong(_Base):
    tuong: list[Tuong] = Field(default_factory=list)
    loiDi: float | None = Field(None, description="Khoảng trống phía trước dãy tủ tới vật cản đối diện (mm)")

    def dai(self, ma: str) -> float | None:
        return next((t.dai for t in self.tuong if t.ma == ma), None)


class MatTruoc(_Base):
    """Một tầng mặt trước của tủ dưới (xếp từ trên xuống): hộc trống, ngăn kéo hoặc cánh."""
    loai: Literal["hoc", "ngan-keo", "canh"]
    cao: float = Field(gt=0)


class Module(_Base):
    ma: str
    loai: str = "duoi"
    ten: str = ""
    tuong: Literal["sau", "phai", "trai", "goc"] = "sau"
    tu: float = Field(0, ge=0)
    rong: float = Field(0, ge=0)
    y: float = Field(0, ge=0)
    cao: float = Field(gt=0)
    sau: float = Field(gt=0)
    canh: list[float] = Field(default_factory=list)
    gocKhuat: float = Field(0, ge=0, description="Phần góc khuất không có cánh, tính từ phía góc (mm)")
    tamHong: float = Field(0, ge=0, description="Tấm hông hoàn thiện ở đầu xa góc (mm)")
    matTruoc: list[MatTruoc] = Field(default_factory=list)
    hoc: float | None = Field(None, description="Tủ cao: chiều cao hốc thiết bị tính từ sàn (mm)")
    canhSau: float | None = None   # ke-goc: chiều dài cánh dọc tường sau
    canhPhai: float | None = None  # ke-goc: chiều dài cánh dọc tường phải
    soNgan: int = 3
    moCanh: list[Literal["trai", "phai", "tren", "duoi"]] = Field(default_factory=list,
        description="Bản lề từng cánh theo thứ tự từ trái sang (nhìn từ trước); trống = tự suy")
    kieuCanh: Literal["phang", "khung", "kinh"] | None = Field(None, description="Cánh phẳng (slab), cánh khung (shaker) hoặc kính")
    vatLieu: str | None = Field(None, description="Vật liệu mặt trước riêng của module (ghi đè chung.vatLieu theo tầng)")
    ghiChu: str | None = None

    @model_validator(mode="after")
    def _kiem_tra(self):
        if self.loai not in LOAI_MODULE:
            raise ValueError(f"loai '{self.loai}' không hỗ trợ; dùng một trong: {', '.join(LOAI_MODULE)}")
        if self.loai == "ke-goc":
            if self.tuong != "goc" or not self.canhSau or not self.canhPhai:
                raise ValueError(f"{self.ma}: ke-goc cần tuong='goc', canhSau và canhPhai")
        elif self.tuong == "goc":
            raise ValueError(f"{self.ma}: chỉ ke-goc mới đặt ở tuong='goc'")
        elif self.rong <= 0:
            raise ValueError(f"{self.ma}: rong phải > 0")
        return self

    @property
    def tang(self) -> str:
        """Tầng của module: duoi / tren / noc / cao / goc."""
        if self.loai == "ke-goc":
            return "goc"
        if self.loai.startswith("cao"):
            return "cao"
        if self.loai == "tren-noc":
            return "noc"
        if self.loai.startswith("tren"):
            return "tren"
        return "duoi"

    @property
    def het(self) -> float:
        return self.tu + self.rong


class ThietBi(_Base):
    ma: str
    ten: str = ""
    loai: Literal["tu-lanh", "chau", "voi", "bep", "hut-mui", "lo", "den", "khac"] = "khac"
    kichThuoc: str | None = None
    viTri: str | None = None
    module: str | None = Field(None, description="Module chứa thiết bị")
    tuong: Literal["sau", "phai", "trai"] | None = None
    tam: float | None = Field(None, description="Tâm thiết bị, khoảng cách từ góc dọc theo tường (mm)")

    def kich_thuoc_so(self) -> list[float]:
        return [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", self.kichThuoc or "")]


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
    ma: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    ten: str = ""
    points: list[tuple[float, float]]
    moTa: str | None = None

    @model_validator(mode="after")
    def _kiem_tra(self):
        pts = [tuple(map(float, p)) for p in self.points]
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            raise ValueError(f"profile {self.ma}: cần ít nhất 3 điểm")
        area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2
        if abs(area) < 1:
            raise ValueError(f"profile {self.ma}: diện tích mặt cắt gần 0")
        n = len(pts)
        for i in range(n):
            for j in range(i + 2, n):
                if i == 0 and j == n - 1:
                    continue
                if _seg_cross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                    raise ValueError(f"profile {self.ma}: mặt cắt tự cắt (cạnh {i} và {j})")
        if area < 0:
            pts = pts[::-1]
        if min(v for _, v in pts) < -0.5:
            raise ValueError(f"profile {self.ma}: v phải ≥ 0 (tính từ đường chạy lên)")
        self.points = pts
        return self

    @property
    def cao(self) -> float:
        return max(v for _, v in self.points) - min(v for _, v in self.points)

    @property
    def nho(self) -> float:
        return max(u for u, _ in self.points)


class Molding(_Base):
    """Phào theo QUY TẮC: đường chạy được tính lại từ module mỗi lần dựng (thêm/bớt tủ thì phào tự theo)."""
    ma: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    kieu: Literal["crown", "base"] = Field(description="crown = phào nóc theo đỉnh tủ; base = phào chân theo sàn")
    profile: str
    tuong: list[Literal["sau", "phai", "trai"]] = Field(default_factory=list, description="Trống = mọi tường có tủ")
    khoangNoi: float = Field(50, ge=0, description="Khe giữa hai tủ ≤ giá trị này thì phào chạy liền qua")
    dauHo: Literal["tra-ve-tuong", "cat-phang"] = Field("tra-ve-tuong", description="Đầu hở: quay về tường hoặc cắt phẳng")
    vatLieu: str | None = Field(None, description="Trống = vật liệu cánh của tầng tủ tương ứng")
    bat: bool = True
    boQuaTran: bool = Field(False, description="Người dùng chọn 'để nguyên' khi phào vượt trần")


class GocNhin(_Base):
    ten: str = ""
    viTri: tuple[float, float, float]
    nhinVao: tuple[float, float, float]
    fovDoc: float = Field(50, gt=1, lt=170)


class KitchenSpec(_Base):
    schemaVersion: int = 2
    ten: str = "Thiết kế tủ bếp"
    phongCach: Literal["Modern", "Classic", "Neoclassical", "Transitional", "Industrial", "Minimalist"] = "Modern"
    donVi: Literal["mm"] = "mm"
    quocGia: str | None = Field(None, description="Mã ISO alpha-2 nơi lắp đặt (VN, US, AU...) — quyết định tiêu chuẩn ưu tiên khi kiểm tra")
    khuVuc: str | None = Field(None, description="Mã khu vực (SEA, EA, NA, EU, OC, GLOBAL) nếu chưa rõ quốc gia")
    nguon: str | None = None
    goc: str | None = None
    chung: Chung = Field(default_factory=Chung)
    phong: Phong | None = None
    module: list[Module] = Field(default_factory=list)
    thietBi: list[ThietBi] = Field(default_factory=list)
    gocNhin: dict[str, GocNhin] = Field(default_factory=dict)
    moldingProfiles: list[MoldingProfile] = Field(default_factory=list, description="Mặt cắt riêng; preset có sẵn ở kitchen/moldings.py")
    moldings: list[Molding] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ma_duy_nhat(self):
        seen: set[str] = set()
        for m in self.module:
            if m.ma in seen:
                raise ValueError(f"Trùng mã module: {m.ma}")
            seen.add(m.ma)
        mol = [x.ma for x in self.moldings]
        if len(mol) != len(set(mol)):
            raise ValueError("Trùng mã phào")
        if set(mol) & seen:
            raise ValueError("Mã phào trùng mã module")
        return self

    def tim(self, ma: str) -> Module:
        for m in self.module:
            if m.ma == ma:
                return m
        raise KeyError(f"Không có module '{ma}'")

    def tuong_co_tu(self) -> list[str]:
        return [t for t in TUONG if any(m.tuong == t for m in self.module)]


def load_spec(data: dict | str) -> KitchenSpec:
    if isinstance(data, str):
        return KitchenSpec.model_validate_json(data)
    return KitchenSpec.model_validate(data)


def dump_spec(spec: KitchenSpec) -> dict:
    return spec.model_dump(mode="json", exclude_none=True)
