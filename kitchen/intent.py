"""Từ câu mô tả -> tham số mẫu -> KitchenSpec.

Khi host MCP là Claude, nên gọi thẳng `create_design(mau=...)` với tham số có cấu trúc.
Bộ phân tích dưới đây phục vụ web/prompt tự do; DeepSeek (nếu có key) chỉ đề xuất tham số,
kết quả luôn được Pydantic kiểm và có đường lùi về regex.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
import urllib.request
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from . import regions
from .spec import Chung, KitchenSpec, Module, ThietBi

logger = logging.getLogger("kitchen.intent")

_NUM = r"(\d+(?:[.,]\d+)?)\s*(mm|cm|mét|met|m)?(?![a-zà-ỹ])"
_KW = r"(?<![a-zà-ỹ])"


class MauBep(BaseModel):
    """Tham số mẫu để sinh thiết kế."""
    hinh: Literal["I", "L"] = "I"
    daiTuongSau: float = Field(3000, ge=600, le=12000, description="Chiều dài dãy tủ dọc tường sau (mm)")
    daiTuongPhai: float | None = Field(None, ge=600, le=12000, description="Chiều dài dãy tường phải (mm), cho bếp chữ L")
    sauTuDuoi: float | None = Field(None, ge=300, le=900, description="Bỏ trống = lấy theo tiêu chuẩn của quốc gia/khu vực")
    matDa: float | None = Field(None, ge=700, le=1100, description="Cao mặt bàn; bỏ trống = theo quốc gia/khu vực")
    dinhTu: float = Field(2200, ge=1500, le=3200, description="Cao độ đỉnh tủ trên (mm)")
    tran: float | None = Field(None, ge=2000, le=4000)
    tuLanh: bool = False
    tuNoc: bool = False
    vatLieu: dict[str, str] = Field(default_factory=dict)
    quocGia: str | None = Field(None, description="Mã ISO alpha-2 nơi lắp đặt: VN, US, AU, CN, DE, GB...")
    phongCach: Literal["Modern", "Classic", "Neoclassical", "Transitional", "Industrial", "Minimalist"] = "Modern"
    phaoNoc: bool | None = Field(None, description="Phào nóc; bỏ trống = có nếu phong cách cổ điển/tân cổ điển")
    phaoChan: bool | None = Field(None, description="Phào chân; bỏ trống = có nếu phong cách cổ điển/tân cổ điển")
    profilePhaoNoc: str = "classic-crown-layered"
    profilePhaoChan: str = "classic-base"
    khuVuc: str | None = Field(None, description="SEA, EA, NA, EU, OC hoặc GLOBAL nếu chưa rõ quốc gia")


def _mm(value: str, unit: str | None) -> float:
    v = float(value.replace(",", "."))
    if unit in ("m", "mét", "met"):
        return v * 1000
    if unit == "cm":
        return v * 10
    if unit is None and v < 10:  # "dài 3" -> hiểu là mét
        return v * 1000
    return v


def parse_prompt(prompt: str) -> tuple[MauBep, list[str]]:
    """Regex có ranh giới từ, chuẩn hóa NFC. Trả (mẫu, ghi chú những gì đã hiểu/đoán)."""
    t = unicodedata.normalize("NFC", prompt).lower()
    notes: list[str] = []
    data: dict = {}
    if re.search(_KW + r"(chữ\s*l|l-shape|hình\s*l)(?![a-zà-ỹ])", t):
        data["hinh"] = "L"
    lens = [_mm(v, u) for v, u in re.findall(_KW + r"(?:dài|rộng|cạnh|width)[^0-9]{0,12}" + _NUM, t)]
    lens += [_mm(v, u) for v, u in re.findall(r"(?:và|x|×)\s*" + _NUM, t)]
    if lens:
        data["daiTuongSau"] = lens[0]
        if data.get("hinh") == "L":
            data["daiTuongPhai"] = lens[1] if len(lens) > 1 else lens[0]
    sau = re.search(_KW + r"(?:sâu|depth)[^0-9]{0,12}" + _NUM, t)
    if sau:
        data["sauTuDuoi"] = _mm(*sau.groups())
    cao = re.search(_KW + r"(?:cao|height)(?!\s*cấp)[^0-9]{0,12}" + _NUM, t)
    if cao:
        data["dinhTu"] = _mm(*cao.groups())
    tran = re.search(_KW + r"trần[^0-9]{0,12}" + _NUM, t)
    if tran:
        data["tran"] = _mm(*tran.groups())
    data["tuLanh"] = bool(re.search(_KW + r"tủ\s*lạnh", t))
    data["tuNoc"] = bool(re.search(_KW + r"(tủ\s*nóc|kịch\s*trần)", t))
    vl = {}
    if re.search(r"sồi|oak", t):
        vl["tuDuoi"] = "Laminate vân gỗ sồi sáng"
    if re.search(r"trắng", t):
        vl["tuTren"] = "Trắng mờ"
    if re.search(r"đá\s*trắng|mặt\s*(đá\s*)?trắng|quartz", t):
        vl["matDa"] = "Đá nhân tạo trắng"
    elif re.search(r"granite|đá\s*(đen|tối|xám)", t):
        vl["matDa"] = "Đá granite tối"
    data["vatLieu"] = vl
    if re.search(r"tân\s*cổ\s*điển|neoclassic", t):
        data["phongCach"] = "Neoclassical"
    elif re.search(r"cổ\s*điển|classic", t):
        data["phongCach"] = "Classic"
    elif re.search(r"tối\s*giản|minimal", t):
        data["phongCach"] = "Minimalist"
    if re.search(r"(không|bỏ)\s*(có\s*)?phào", t):
        data["phaoNoc"] = data["phaoChan"] = False
    else:
        if re.search(r"phào\s*(nóc|trần|đỉnh)", t):
            data["phaoNoc"] = True
        if re.search(r"phào\s*(chân|chân\s*tủ)", t):
            data["phaoChan"] = True
    qg, kv = regions.tu_cau_mo_ta(prompt)
    if qg or kv:
        data["quocGia"], data["khuVuc"] = qg, kv
        notes.append(f"Áp tiêu chuẩn ưu tiên cho {regions.QUOC_GIA[qg][0] if qg else regions.KHU_VUC[kv]}")
    try:
        mau = MauBep.model_validate(data)
    except ValidationError as e:
        notes.append(f"Bỏ qua số đo ngoài phạm vi: {e.errors()[0]['msg']}")
        mau = MauBep.model_validate({k: v for k, v in data.items() if k in ("hinh", "tuLanh", "tuNoc", "vatLieu", "quocGia", "khuVuc",
                                                                            "phongCach", "phaoNoc", "phaoChan")})
    if not lens:
        notes.append("Không thấy chiều dài trong mô tả, dùng mặc định 3000 mm")
    return mau, notes


def parse_prompt_llm(prompt: str) -> tuple[MauBep | None, dict]:
    """DeepSeek đề xuất tham số (JSON mode). Lỗi -> trả None kèm trạng thái, không ném."""
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return None, {"status": "skipped", "reason": "DEEPSEEK_API_KEY chưa được cấu hình"}
    schema = json.dumps(MauBep.model_json_schema(), ensure_ascii=False)
    payload = {"model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"), "temperature": 0,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": "Trích tham số thiết kế tủ bếp từ mô tả. Chỉ trả JSON đúng schema sau, đơn vị mm, trường không rõ thì bỏ qua:\n" + schema},
                            {"role": "user", "content": prompt}]}
    req = urllib.request.Request(os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com") + "/chat/completions",
                                 data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            content = json.loads(r.read())["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        return MauBep.model_validate_json(m.group(0) if m else content), {"status": "ok"}
    except Exception as e:  # mạng, JSON hỏng, sai schema -> lùi về regex
        logger.warning("[DEEPSEEK] lỗi, dùng regex: %s", e)
        return None, {"status": "error", "reason": f"{type(e).__name__}: {e}"[:300]}


def _chia(dai: float, uu_tien: list[float]) -> list[float]:
    """Chia một đoạn thành các bề rộng module chuẩn (bội 10 mm), phần dư dồn vào module cuối."""
    out, con = [], dai
    chuan = [900, 800, 600, 450, 400, 300]
    for w in uu_tien:
        if con - w >= 300:
            out.append(w); con -= w
    while con >= 300:
        w = next((x for x in chuan if con - x >= 300 or con - x == 0), 300)
        if con - w < 300 and con - w != 0:
            w = con
        out.append(w); con -= w
    if con > 0.5:
        if out:
            out[-1] += con
        else:
            out.append(con)
    return [round(w) for w in out]


def _bo_tri(dai: float, thiet_bi: list[str], truoc: float = 450) -> list[tuple[float, str]]:
    """Trả [(rộng, loại)] cho một dãy. Thiết bị chiếm module 800 (co về 600 nếu chật)."""
    loai_tb = {"chau": "duoi-chau", "bep": "duoi-bep"}
    for w_tb, gap_mid, gap_end, gap_start in ((800, 600, 450, truoc), (800, 450, 450, min(truoc, 450)), (600, 450, 400, min(truoc, 400)),
                                              (600, 300, 300, min(truoc, 300)), (600, 300, 0, 0), (600, 0, 0, 0)):
        need = gap_start + len(thiet_bi) * w_tb + gap_mid * max(0, len(thiet_bi) - 1) + gap_end
        if need <= dai:
            break
    else:
        return [(w, "duoi") for w in _chia(dai, [])] if dai >= 300 else []
    extra = dai - need
    gaps = [gap_start] + [gap_mid] * max(0, len(thiet_bi) - 1) + [gap_end + extra]
    out: list[tuple[float, str]] = []
    for i, g in enumerate(gaps):
        if g >= 300:
            out += [(w, "duoi") for w in _chia(g, [])]
        elif g > 0:  # khoảng < 300: nhập vào module thiết bị liền kề
            if out:
                out[-1] = (out[-1][0] + g, out[-1][1])
            else:
                gaps[i + 1 if i + 1 < len(gaps) else i] += 0
                out.append((g, "duoi")) if g >= 150 else None
        if i < len(thiet_bi):
            out.append((w_tb, loai_tb[thiet_bi[i]]))
    return [(round(w), l) for w, l in out]


def _giua(lo, hi, uu_tien, buoc=10):
    """Giá trị ưu tiên kẹp trong [lo, hi], làm tròn theo bước."""
    v = uu_tien
    if lo is not None:
        v = max(v, lo)
    if hi is not None:
        v = min(v, hi)
    return round(v / buoc) * buoc


def kich_thuoc_theo_vung(rows: list[dict] | None, quoc_gia: str | None, khu_vuc: str | None) -> tuple[dict, dict]:
    """Kích thước mặc định của mẫu lấy từ tiêu chuẩn ưu tiên của quốc gia/khu vực. Trả (giá trị, nguồn từng giá trị)."""
    from .rules import default_rows
    from .rules_kb import select
    sel = select(rows if rows is not None else default_rows(), *regions.chuan_hoa(quoc_gia, khu_vuc))
    p = lambda t: (sel.get(t) or {}).get("params") or {}
    src = lambda t: sel[t]["code"] if t in sel else "mặc định"
    out, nguon = {}, {}
    md = p("mat-da-cao")
    allowed = md.get("matDa_cho_phep")
    out["matDa"] = (900 if 900 in allowed else allowed[len(allowed) // 2]) if allowed else _giua(md.get("matDa_min"), md.get("matDa_max"), 900)
    nguon["matDa"] = src("mat-da-cao")
    sd, sm = p("sau-tu-duoi"), p("sau-mat-da")
    if sm.get("sauMatDa_min") and not sd:
        out["sauTuDuoi"], nguon["sauTuDuoi"] = max(580, sm["sauMatDa_min"] - 20), src("sau-mat-da")
    else:
        out["sauTuDuoi"], nguon["sauTuDuoi"] = _giua(sd.get("sauTuDuoi_min"), sd.get("sauTuDuoi_max"), 580), src("sau-tu-duoi")
    st = p("sau-tu-tren")
    out["sauTuTren"], nguon["sauTuTren"] = _giua(st.get("sauTuTren_min"), st.get("sauTuTren_max"), 320), src("sau-tu-tren")
    kt = p("khoang-tu-tren")
    out["khoangTuTren"], nguon["khoangTuTren"] = _giua(kt.get("khoang_tren_min"), kt.get("khoang_tren_max"), 600), src("khoang-tu-tren")
    ct = p("chan-tu")
    out["lenChan"], nguon["lenChan"] = _giua(ct.get("lenChan_min"), ct.get("lenChan_max"), 100), src("chan-tu")
    out["khoangHutMui"], nguon["khoangHutMui"] = p("hut-mui").get("khoang_min", 650), src("hut-mui")
    return out, nguon


def from_template(mau: MauBep, ten: str = "Thiết kế tủ bếp", rows: list[dict] | None = None) -> KitchenSpec:
    """Sinh spec từ mẫu. Kích thước không được chỉ định lấy theo tiêu chuẩn ưu tiên của mau.quocGia/khuVuc."""
    from . import moldings as _mol
    kt, nguon_kt = kich_thuoc_theo_vung(rows, mau.quocGia, mau.khuVuc)
    co_dien = mau.phongCach in ("Classic", "Neoclassical", "Transitional")
    phao_noc = mau.phaoNoc if mau.phaoNoc is not None else co_dien
    phao_chan = mau.phaoChan if mau.phaoChan is not None else co_dien
    h_noc = _mol.PRESETS[mau.profilePhaoNoc].cao if phao_noc and mau.profilePhaoNoc in _mol.PRESETS else 0
    mat_da = mau.matDa or kt["matDa"]
    day_tu_tren = mat_da + kt["khoangTuTren"]
    tran = mau.tran or max(mau.dinhTu + max(30, h_noc), 2400)
    dinh = min(mau.dinhTu, tran - h_noc) if h_noc else mau.dinhTu  # chừa chỗ cho phào nóc dưới trần
    c = Chung(matDa=mat_da, deMatDa=mat_da - 60, lenChan=kt["lenChan"], sauTuDuoi=mau.sauTuDuoi or kt["sauTuDuoi"],
              sauTuTren=kt["sauTuTren"], dinhTu=dinh, tran=tran, chiaTangTren=dinh if not mau.tuNoc else dinh - 330,
              dayTuTren=day_tu_tren if dinh - day_tu_tren >= 450 else dinh - 600, vatLieu=mau.vatLieu)
    y_hut = c.matDa + kt["khoangHutMui"] + 165  # đáy tủ hút mùi = mặt bàn + khoảng tối thiểu + chiều cao máy
    if mau.tuNoc:
        c.dinhTu = tran - max(30, h_noc)
        c.chiaTangTren = c.dinhTu - 330
    mods: list[Module] = []
    tb: list[ThietBi] = []
    cao_tren = c.chiaTangTren - c.dayTuTren
    sau_tren = c.sauTuTren
    n = {"TD": 0, "TT": 0, "TC": 0, "TN": 0}

    def ma(p):
        n[p] += 1
        return f"{p}{n[p]}"

    def day(tuong: str, start: float, dai: float, thiet_bi: list[str], truoc: float = 450):
        """Bố trí một dãy tủ dưới: [khoảng trước] + thiết bị xen khoảng 600 + [khoảng sau 450].
        Khoảng trống là mặt bàn thao tác (NKBA-10/14/15); thiếu chỗ thì co về 300 rồi bỏ."""
        nonlocal tb
        s = start
        if mau.tuLanh and tuong == "sau":
            mods.append(Module(ma=ma("TC"), loai="cao-tu-lanh", ten="Tủ cao tủ lạnh", tuong=tuong, tu=start + dai - 700,
                               rong=700, y=0, cao=c.dinhTu, sau=640, canh=[350, 350], hoc=1650))
            tb.append(ThietBi(ma=f"TB{len(tb)+1}", loai="tu-lanh", ten="Tủ lạnh", kichThuoc="600 × 1600 × 620", module=mods[-1].ma))
            dai -= 700
        plan = _bo_tri(dai, thiet_bi, truoc)
        for w, loai in plan:
            canh = [w / 2, w / 2] if w >= 600 else [w]
            m = Module(ma=ma("TD"), loai=loai, ten={"duoi-chau": "Tủ chậu", "duoi-bep": "Tủ dưới bếp"}.get(loai, "Tủ dưới"),
                       tuong=tuong, tu=s, rong=w, y=0, cao=c.deMatDa, sau=c.sauTuDuoi, canh=canh,
                       matTruoc=[{"loai": "ngan-keo", "cao": 180}, {"loai": "ngan-keo", "cao": 250}] if loai == "duoi-bep" else [])
            mods.append(m)
            if loai == "duoi-chau":
                tb.append(ThietBi(ma=f"TB{len(tb)+1}", loai="chau", ten="Chậu rửa", kichThuoc=f"{min(780, w - 40):g} × 430", tuong=tuong, tam=s + w / 2))
                tb.append(ThietBi(ma=f"TB{len(tb)+1}", loai="voi", ten="Vòi rửa", kichThuoc="cao 300", tuong=tuong, tam=s + w / 2))
            if loai == "duoi-bep":
                tb.append(ThietBi(ma=f"TB{len(tb)+1}", loai="bep", ten="Bếp âm", kichThuoc=f"{min(730, w - 10):g} × 430", tuong=tuong, tam=s + w / 2))
            s += w

    def tren(tuong: str, start: float, end: float):
        """Tủ trên chia theo đúng ranh giới tủ dưới bên dưới; ô ngay trên bếp thành tủ hút mùi."""
        bep_tams = [t.tam for t in tb if t.loai == "bep" and t.tuong == tuong]
        cuts = sorted({start, end, *[m.tu for m in mods if m.tuong == tuong and m.tang == "duoi" and start < m.tu < end],
                       *[m.het for m in mods if m.tuong == tuong and m.tang == "duoi" and start < m.het < end]})
        segs = [(a, b) for a, b in zip(cuts, cuts[1:]) if b - a >= 1]
        merged: list[list[float]] = []
        for a, b in segs:  # gộp ô quá hẹp vào ô bên cạnh
            if merged and (b - a < 300 or merged[-1][1] - merged[-1][0] < 300):
                merged[-1][1] = b
            else:
                merged.append([a, b])
        for a, b in merged:
            w = b - a
            loai = "tren-hut-mui" if any(a <= t < b for t in bep_tams) else "tren"
            y = max(c.dayTuTren + 150, y_hut) if loai == "tren-hut-mui" else c.dayTuTren
            mods.append(Module(ma=ma("TT"), loai=loai, ten="Tủ trên hút mùi" if loai == "tren-hut-mui" else "Tủ trên", tuong=tuong,
                               tu=a, rong=w, y=y, cao=c.chiaTangTren - y, sau=sau_tren, canh=[w / 2, w / 2] if w >= 600 else [w]))
            if loai == "tren-hut-mui":
                tb.append(ThietBi(ma=f"TB{len(tb)+1}", loai="hut-mui", ten="Máy hút mùi âm tủ", kichThuoc=f"{min(w - 40, 730):g} × 165", module=mods[-1].ma))
            if mau.tuNoc:
                # có phào nóc: cánh nóc mở ngang thay vì lật lên để không chạm phào (MOLDING-CANH-LAT-001)
                canh_noc, mo = ([w / 2, w / 2], ["trai", "phai"]) if (h_noc and w >= 600) else ([w], ["trai"] if h_noc else [])
                mods.append(Module(ma=ma("TN"), loai="tren-noc", ten="Tủ nóc", tuong=tuong, tu=a, rong=w, y=c.chiaTangTren,
                                   cao=c.dinhTu - c.chiaTangTren, sau=sau_tren, canh=canh_noc, moCanh=mo))

    lr = 700 if mau.tuLanh else 0
    if mau.hinh == "I":
        day("sau", 0, mau.daiTuongSau, ["chau", "bep"])
        tren("sau", 0, mau.daiTuongSau - lr)
    else:
        L2 = mau.daiTuongPhai or mau.daiTuongSau
        g = c.sauTuDuoi
        # tường phải: tủ góc khuất đầu dãy + chậu; tường sau: bếp (+ tủ lạnh cuối dãy)
        mods.append(Module(ma=ma("TD"), loai="duoi-chau-goc", ten="Tủ góc khuất", tuong="phai", tu=0, rong=g + 450, y=0,
                           cao=c.deMatDa, sau=c.sauTuDuoi, canh=[450], gocKhuat=g))
        day("phai", g + 450, L2 - g - 450, ["chau"], truoc=0)  # tủ góc phía trước đã là mặt bàn thao tác
        day("sau", g, mau.daiTuongSau - g, ["bep"])
        mods.append(Module(ma="KG1", loai="ke-goc", ten="Kệ góc mở", tuong="goc", canhSau=600, canhPhai=600, y=c.dayTuTren,
                           cao=c.chiaTangTren - c.dayTuTren, sau=sau_tren, soNgan=3))
        tren("sau", 600, mau.daiTuongSau - lr)
        tren("phai", 600, L2)
    spec = KitchenSpec(ten=ten, chung=c, module=mods, thietBi=tb, quocGia=mau.quocGia, khuVuc=mau.khuVuc, phongCach=mau.phongCach,
                       moldings=_mol.default_moldings(phao_noc, phao_chan, mau.profilePhaoNoc, mau.profilePhaoChan),
                       nguon="Sinh từ mẫu; kích thước theo: " + ", ".join(f"{k}={v}" for k, v in nguon_kt.items()))
    return KitchenSpec.model_validate(spec.model_dump(mode="json"))
