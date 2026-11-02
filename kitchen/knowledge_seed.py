"""Kho tri thức nền theo khu vực / quốc gia (chỉ dữ liệu + migration sqlite, không phụ thuộc thư viện ngoài).

Trường của mỗi mục:
- khu_vuc  : GLOBAL | SEA | EA | NA | EU | OC  (xem kitchen/regions.py)
- quoc_gia : mã ISO alpha-2, nhiều nước cách nhau dấu phẩy; rỗng = cả khu vực
- metadata.loaiNguon : bat-buoc (quy chuẩn/luật) | tieu-chuan | khuyen-nghi | thuc-hanh (kinh nghiệm phổ biến) | chua-ro
- metadata.kiemTra   : danh sách chủ đề mà bộ kiểm tra tự động dùng (mỗi chủ đề chọn mục ưu tiên nhất theo quốc gia)
- metadata.params    : ngưỡng máy đọc được, sửa trong DB không cần sửa code

Số liệu chỉ ghi khi đọc được từ nguồn ghi ở source_url. Bản tóm tắt không thay văn bản gốc; khi thi công
phải theo bản đầy đủ, quy chuẩn địa phương và hướng dẫn lắp của nhà sản xuất thiết bị.
"""

NKBA = "https://kb.nkba.org/uploads/2022/05/Kitchen-Planning-Guidelines.pdf"
RANGEMASTER = "https://www.rangemaster.co.uk/what-clearances-are-required-between-cooker-top-and-cooker-hood"
EN1116 = "https://catas.com/uploads/media/unien1116-eng.pdf"
ASNZS5601 = "https://energysafe.vic.gov.au/industry-guidance/gas/gas-information-sheets/gis-25-domestic-gas-cooking-appliance-overhead"
GB55038 = "https://ghzrzyw.beijing.gov.cn/biaozhunguanli/bzzl/202506/P020250609570099619169.pdf"
CHEAA = "https://www.cheaa.org/upload/files/2018/7/30152038804.pdf"
DIN18040 = "https://www.agsv.bayern.de/wp-content/uploads/2018/07/obb_faltblatt_barrierefr_wohnen.pdf"
QCVN04 = "https://vksndtc.gov.vn/tin-tong-hop/quy-chuan-ky-thuat-quoc-gia-ve-nha-chung-cu-d8-t9233.html?Page=1"
VN_THUC_HANH = "https://meta.vn/hotro/kich-thuoc-tu-bep-tieu-chuan-21437"


def _k(kind, code, title, content, url, khu_vuc, quoc_gia, nguon, loai, kiem_tra=None, params=None, **extra):
    meta = {"nguon": nguon, "loaiNguon": loai, **extra}
    if kiem_tra:
        meta["kiemTra"] = kiem_tra
    if params:
        meta["params"] = params
    return {"kind": kind, "code": code, "title": title, "content": content, "source_url": url,
            "khu_vuc": khu_vuc, "quoc_gia": quoc_gia, "metadata": meta}


_N = "NKBA Kitchen Planning Guidelines"
_VL = "Mô tả chung, cần đối chiếu catalogue nhà cung cấp"

KNOWLEDGE = [
    # ---------------- 3 mục mẫu ban đầu (không rõ nguồn) — giữ làm mặc định toàn cầu, mức "chua-ro"
    _k("standard", "KITCHEN-DEFAULT-001", "Kích thước công thái học",
       "Chiều cao mặt bàn tham chiếu 850-950 mm; chiều sâu tủ dưới 580-650 mm.", "", "GLOBAL", "",
       "Mục mẫu ban đầu, nguồn example.com là placeholder", "chua-ro", ["mat-da-cao", "sau-tu-duoi"],
       {"matDa_min": 850, "matDa_max": 950, "sauTuDuoi_min": 580, "sauTuDuoi_max": 650}),
    _k("rule", "SAFETY-001", "Khoảng cách bếp và chậu",
       "Không đặt bếp sát chậu rửa; nên có vùng thao tác tối thiểu 300 mm giữa chúng.", "", "GLOBAL", "",
       "Mục mẫu ban đầu, nguồn example.com là placeholder", "chua-ro", ["chau-bep"], {"chau_bep_min": 300}),
    _k("rule", "CLEARANCE-001", "Lối đi",
       "Lối đi thao tác tối thiểu 900 mm; hai dãy tủ đối diện nên có tối thiểu 1100 mm.", "", "GLOBAL", "",
       "Mục mẫu ban đầu, nguồn example.com là placeholder", "chua-ro", ["loi-di"], {"loiDi_min": 900, "haiDay_min": 1100}),

    # ---------------- Bắc Mỹ / Hoa Kỳ: NKBA (khuyến nghị)
    _k("rule", "NKBA-03", "Tam giác làm việc (NKBA)",
       "Tổng 3 cạnh chậu – bếp – tủ lạnh ≤ 7925 mm (26 ft); mỗi cạnh 1219–2743 mm (4–9 ft); cạnh không cắt qua đảo quá 305 mm.",
       NKBA, "NA", "US,CA", _N, "khuyen-nghi", ["tam-giac"], {"canh_min": 1219, "canh_max": 2743, "tong_max": 7925}),
    _k("rule", "NKBA-06", "Lối đi làm việc (NKBA)",
       "Lối đi làm việc ≥ 1067 mm (42 in) cho 1 người nấu, ≥ 1219 mm (48 in) cho nhiều người.", NKBA, "NA", "US,CA", _N,
       "khuyen-nghi", ["loi-di"], {"loiDi_min": 1067, "loiDi_nhieuNguoi": 1219}),
    _k("rule", "NKBA-07", "Lối đi qua lại (NKBA)", "Lối đi qua lại ≥ 914 mm (36 in).", NKBA, "NA", "US,CA", _N, "khuyen-nghi",
       params={"loiQuaLai_min": 914}),
    _k("rule", "NKBA-10", "Mặt bàn hai bên chậu (NKBA)", "Mặt bàn trống ≥ 610 mm (24 in) một bên và ≥ 457 mm (18 in) bên kia chậu chính.",
       NKBA, "NA", "US,CA", _N, "khuyen-nghi", ["ban-chau"], {"ben_lon": 610, "ben_nho": 457}),
    _k("rule", "NKBA-11", "Vị trí máy rửa bát (NKBA)", "Máy rửa bát cách chậu ≤ 914 mm (36 in); chừa ≥ 533 mm (21 in) chỗ đứng.",
       NKBA, "NA", "US,CA", _N, "khuyen-nghi", params={"cach_chau_max": 914, "cho_dung_min": 533}),
    _k("rule", "NKBA-14", "Mặt bàn cạnh tủ lạnh (NKBA)", "Có mặt bàn ≥ 381 mm (15 in) phía tay nắm tủ lạnh.", NKBA, "NA", "US,CA", _N,
       "khuyen-nghi", ["ban-tu-lanh"], {"mat_dat_min": 381}),
    _k("rule", "NKBA-15", "Mặt bàn hai bên bếp (NKBA)", "Mặt bàn trống ≥ 381 mm (15 in) một bên và ≥ 305 mm (12 in) bên kia bếp.",
       NKBA, "NA", "US,CA", _N, "khuyen-nghi", ["ban-bep"], {"ben_lon": 381, "ben_nho": 305}),
    _k("rule", "NKBA-16", "Khoảng trống trên bếp (NKBA)",
       "≥ 610 mm (24 in) tới bề mặt không cháy được bảo vệ; ≥ 762 mm (30 in) tới vật liệu cháy được khi không có hút mùi.",
       NKBA, "NA", "US,CA", _N, "khuyen-nghi", ["tren-bep"], {"khong_hut_mui_min": 762}),
    _k("rule", "NKBA-17", "Thông gió bếp (NKBA)", "Hút mùi có ống thải ra ngoài, khuyến nghị ≥ 150 cfm (~255 m³/h); > 400 cfm cần bù gió.",
       NKBA, "NA", "US,CA", _N, "khuyen-nghi", params={"luu_luong_min_cfm": 150}),
    _k("rule", "NKBA-18", "An toàn bếp (NKBA)", "Không đặt bếp dưới cửa sổ mở được; bình chữa cháy cao 381–1219 mm.", NKBA, "NA", "US,CA", _N,
       "khuyen-nghi"),
    _k("rule", "NKBA-19", "Vị trí lò vi sóng (NKBA)",
       "Đáy lò ≤ 1372 mm (54 in); đặt dưới mặt bàn thì đáy ≥ 381 mm (15 in).", NKBA, "NA", "US,CA", _N, "khuyen-nghi",
       ["lo-vi-song"], {"day_duoi_mat_da_min": 381, "day_max": 1372}),
    _k("rule", "NKBA-21", "Gộp mặt bàn thao tác (NKBA)", "Hai vùng mặt bàn liền nhau: lấy yêu cầu lớn hơn rồi cộng 305 mm.", NKBA,
       "NA", "US,CA", _N, "khuyen-nghi", params={"cong_them": 305}),
    _k("standard", "NKBA-22", "Mặt bàn (NKBA)", "Tổng mặt bàn ≥ 4013 mm, sâu ≥ 610 mm, khoảng trống phía trên ≥ 381 mm tới tủ trên.",
       NKBA, "NA", "US,CA", _N, "khuyen-nghi", ["khoang-tu-tren"], {"khoang_tren_min": 381, "tong_dai_min": 4013}),

    # ---------------- Châu Âu: EN 1116 (kích thước phối hợp tủ bếp & thiết bị), Anh: Rangemaster, Đức: DIN 18040-2
    _k("standard", "EN-1116", "Kích thước phối hợp tủ bếp (EN 1116:2018)",
       "Chiều cao mặt bàn 850, 900 hoặc 950 mm; mặt bàn sâu ≥ 600 mm; tủ treo sâu 310–400 mm; mặt bàn tới đáy tủ treo ≥ 450 mm; "
       "chân tủ ≥ 80 mm; bề rộng module danh nghĩa 400, 500, 600, 900 mm. Khoảng cách bếp – máy hút mùi theo nhà sản xuất.",
       EN1116, "EU", "", "Tóm tắt UNI EN 1116:2018 (CATAS)", "tieu-chuan",
       ["mat-da-cao", "sau-mat-da", "sau-tu-tren", "khoang-tu-tren", "chan-tu"],
       {"matDa_min": 850, "matDa_max": 950, "matDa_cho_phep": [850, 900, 950], "sauMatDa_min": 600,
        "sauTuTren_min": 310, "sauTuTren_max": 400, "khoang_tren_min": 450, "lenChan_min": 80, "rong_module": [400, 500, 600, 900]}),
    _k("rule", "HUT-MUI-001", "Máy hút mùi – mặt bếp (Rangemaster)",
       "Đáy máy hút mùi cách mặt bếp tối thiểu khoảng 650 mm (điện và gas; 670 mm nếu có tấm chắn sau). Ưu tiên hướng dẫn lắp của máy.",
       RANGEMASTER, "EU", "GB", "Rangemaster (nhà sản xuất)", "khuyen-nghi", ["hut-mui"], {"khoang_min": 650}),
    _k("rule", "DIN-18040-2", "Bếp tiếp cận được (DIN 18040-2)",
       "Nhà ở không rào cản: trước dãy bếp có vùng di chuyển sâu ≥ 1200 mm; trong phòng có ít nhất một vùng 1200 × 1200 mm. "
       "Chiều cao mặt bàn, tủ trên và thiết bị theo nhu cầu người dùng.", DIN18040, "EU", "DE", "Tóm tắt DIN 18040-2 (AGSV Bayern)",
       "tieu-chuan", params={"loiDi_tiepCan_min": 1200}, apDung="nhà ở tiếp cận được (người cao tuổi, xe lăn)"),

    # ---------------- Châu Đại Dương: AS/NZS 5601.1:2022 (bắt buộc cho lắp đặt gas)
    _k("rule", "AS-NZS-5601-1", "Khoảng trống trên bếp gas (AS/NZS 5601.1:2022)",
       "Lắp mới: máy hút mùi cách đỉnh kiềng ≥ 650 mm (nếu nhà sản xuất yêu cầu lớn hơn thì theo nhà sản xuất); quạt hút ≥ 750 mm; "
       "bề mặt cháy được hướng xuống thấp hơn 650 mm phải bảo vệ theo Phụ lục C; mọi bề mặt ≥ 450 mm. Lắp đặt cũ theo bản 2013: 600 mm.",
       ASNZS5601, "OC", "AU,NZ", "Energy Safe Victoria GIS 25", "bat-buoc", ["hut-mui", "tren-bep"],
       {"khoang_min": 650, "khong_hut_mui_min": 650, "tuyet_doi_min": 450}, apDung="bếp gas"),

    # ---------------- Đông Á / Trung Quốc
    _k("rule", "GB-55038-2025", "Quy phạm dự án nhà ở – bếp (GB 55038-2025)",
       "Bếp: diện tích sử dụng ≥ 3,5 m²; chiều cao thông thủy ≥ 2,20 m; cửa bếp thông thủy ≥ 0,70 m; lối vào thông thủy ≥ 0,90 m; "
       "thông gió tự nhiên ≥ 10% diện tích sàn và ≥ 0,60 m²; có chiếu sáng tự nhiên trực tiếp; không đặt bếp ở tầng hầm. Hiệu lực 01/05/2025.",
       GB55038, "EA", "CN", "GB 55038-2025 (trích, Bắc Kinh)", "bat-buoc", ["chieu-cao-thong-thuy"],
       {"tran_min": 2200, "dienTich_min_m2": 3.5, "cua_min": 700}),
    _k("rule", "T-CHEAA-TAM-GIAC", "Tam giác làm việc (T/CHEAA, dự thảo)",
       "Chậu, bếp, tủ lạnh tạo tam giác có tổng ba cạnh không quá 6 m. Tủ treo chứa thiết bị sâu lọt lòng ≥ 310 mm.",
       CHEAA, "EA", "CN", "Dự thảo tiêu chuẩn hội CHEAA về kích thước thiết bị bếp âm tủ", "khuyen-nghi", ["tam-giac"],
       {"canh_min": 0, "canh_max": 6000, "tong_max": 6000}),

    # ---------------- Đông Nam Á / Việt Nam
    _k("rule", "QCVN-04-2021-BEP", "QCVN 04:2021/BXD – bếp trong nhà chung cư",
       "Không bố trí bếp trong văn phòng kết hợp lưu trú (officetel). Chưa tìm thấy TCVN/QCVN quy định kích thước tủ bếp.",
       QCVN04, "SEA", "VN", "QCVN 04:2021/BXD (tin VKSNDTC)", "bat-buoc"),
    _k("standard", "VN-TU-BEP-PHO-BIEN", "Kích thước tủ bếp phổ biến tại Việt Nam",
       "Kinh nghiệm thị trường, không phải TCVN: mặt bàn cao 800–850 mm; tủ dưới sâu 560–600 mm; tủ trên sâu 300–350 mm; "
       "mặt bàn tới đáy tủ trên 600–650 mm (khoảng 500–700); chân tủ 90–100 mm; vùng bếp – hút mùi 650–700 mm.",
       VN_THUC_HANH, "SEA", "VN", "META.vn (bài hướng dẫn)", "thuc-hanh",
       ["mat-da-cao", "sau-tu-duoi", "sau-tu-tren", "khoang-tu-tren", "chan-tu", "hut-mui"],
       {"matDa_min": 800, "matDa_max": 850, "sauTuDuoi_min": 560, "sauTuDuoi_max": 600, "sauTuTren_min": 300, "sauTuTren_max": 350,
        "khoang_tren_min": 500, "khoang_tren_max": 700, "lenChan_min": 90, "lenChan_max": 100, "khoang_min": 650}),

    # ---------------- Vật liệu (toàn cầu)
    _k("material", "MAT-WOOD-OAK", "Oak sáng", "Ván oak sáng, matte", "https://images.unsplash.com/photo-1556912173-46c336c7fd55",
       "GLOBAL", "", "Mục mẫu ban đầu (ảnh minh họa)", "chua-ro"),
    _k("material", "MAT-WHITE-MATTE", "Trắng mờ", "Sơn/laminate trắng mờ", "https://images.unsplash.com/photo-1556912167-f556f1f39fdf",
       "GLOBAL", "", "Mục mẫu ban đầu (ảnh minh họa)", "chua-ro"),
    _k("material", "MAT-GRANITE-DARK", "Đá granite tối", "Mặt bàn đá granite xám đậm", "https://images.unsplash.com/photo-1556911220-e15b29be8c8f",
       "GLOBAL", "", "Mục mẫu ban đầu (ảnh minh họa)", "chua-ro"),
    _k("material", "MAT-MDF-HMR", "MDF lõi xanh chống ẩm (HMR)",
       "Ván sợi có phụ gia chống ẩm cho thùng và cánh; chịu ẩm hơn MDF thường, không chịu ngâm nước; cần dán cạnh kín.", "",
       "GLOBAL", "", _VL, "thuc-hanh", dungCho=["than", "canh"], mau="#d9c3a0"),
    _k("material", "MAT-PLYWOOD", "Ván dán (plywood)", "Gỗ lạng ép chéo nhiều lớp; bắt vít chắc, chịu ẩm khá; hay dùng cho thùng tủ chậu.", "",
       "GLOBAL", "", _VL, "thuc-hanh", dungCho=["than"], mau="#cfae7e"),
    _k("material", "MAT-MFC", "Ván dăm phủ melamine (MFC)", "Giá thấp, nhiều màu; chịu nước kém, tránh khu chậu rửa.", "",
       "GLOBAL", "", _VL, "thuc-hanh", dungCho=["than", "canh"], mau="#e4d7c3"),
    _k("material", "MAT-PVC-FOAM", "Nhựa PVC foam", "Không sợ nước; cứng và giữ vít kém hơn gỗ công nghiệp; hợp tủ chậu.", "",
       "GLOBAL", "", _VL, "thuc-hanh", dungCho=["than", "canh"], mau="#f2f2f0"),
    _k("material", "MAT-ACRYLIC", "Cánh phủ Acrylic bóng", "Acrylic bóng gương trên cốt MDF; dễ lau; dễ lộ xước và vân tay.", "",
       "GLOBAL", "", _VL, "thuc-hanh", dungCho=["canh"], mau="#ffffff"),
    _k("material", "MAT-LAMINATE", "Phủ Laminate (HPL)", "Phủ áp lực cao, chịu xước và nhiệt tốt hơn melamine; nhiều vân gỗ/đá.", "",
       "GLOBAL", "", _VL, "thuc-hanh", dungCho=["canh", "than"], mau="#c8a273"),
    _k("material", "MAT-GO-SOI", "Gỗ sồi tự nhiên", "Vân rõ, cứng; cần sơn phủ chống ẩm, có thể co ngót theo độ ẩm.", "",
       "GLOBAL", "", _VL, "thuc-hanh", dungCho=["canh", "ke"], mau="#c49a6c"),
    _k("material", "MAT-DA-THACH-ANH", "Đá thạch anh nhân tạo (quartz)", "Ít thấm, màu đồng đều; không nên đặt nồi nóng trực tiếp.", "",
       "GLOBAL", "", _VL, "thuc-hanh", dungCho=["mat-da"], mau="#f1f0ec"),
    _k("material", "MAT-INOX-304", "Inox 304", "Cho chậu rửa, mặt bàn khu nấu; chịu nước và nhiệt, dễ trầy bề mặt.", "",
       "GLOBAL", "", _VL, "thuc-hanh", dungCho=["chau", "mat-da"], mau="#c9ccd1"),
    _k("material", "MAT-KINH-CUONG-LUC", "Kính cường lực ốp tường bếp", "Ốp giữa mặt bàn và tủ trên; dễ lau; khoét ổ điện trước khi tôi kính.", "",
       "GLOBAL", "", _VL, "thuc-hanh", dungCho=["tuong"], mau="#e8eef0"),
]

BY_CODE = {k["code"]: k for k in KNOWLEDGE}


def _cols(conn) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(knowledge)")}


def migrate(conn) -> list[str]:
    """Thêm cột khu_vuc, quoc_gia nếu DB cũ chưa có."""
    done = []
    cols = _cols(conn)
    if "khu_vuc" not in cols:
        conn.execute("ALTER TABLE knowledge ADD COLUMN khu_vuc TEXT NOT NULL DEFAULT 'GLOBAL'")
        done.append("khu_vuc")
    if "quoc_gia" not in cols:
        conn.execute("ALTER TABLE knowledge ADD COLUMN quoc_gia TEXT NOT NULL DEFAULT ''")
        done.append("quoc_gia")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_vung ON knowledge(khu_vuc, quoc_gia)")
    return done


def apply(conn) -> dict:
    """Migration + bổ sung kho nền. Thêm code còn thiếu. Với code đã có: gán khu vực/quốc gia nếu còn mặc định,
    bổ sung khóa metadata còn thiếu (nguon, loaiNguon, kiemTra, params) — không ghi đè giá trị người dùng đã sửa;
    bỏ link example.com giả."""
    import json
    cols_added = migrate(conn)
    added, upgraded = [], []
    rows = {r[0]: r for r in conn.execute("SELECT code, id, khu_vuc, quoc_gia, metadata_json, source_url FROM knowledge")}
    for k in KNOWLEDGE:
        if k["code"] not in rows:
            conn.execute("INSERT INTO knowledge(kind,code,title,content,source_url,metadata_json,khu_vuc,quoc_gia) VALUES(?,?,?,?,?,?,?,?)",
                         (k["kind"], k["code"], k["title"], k["content"], k["source_url"],
                          json.dumps(k["metadata"], ensure_ascii=False), k["khu_vuc"], k["quoc_gia"]))
            added.append(k["code"])
            continue
        code, rid, kv, qg, meta_json, url = rows[k["code"]]
        meta = json.loads(meta_json or "{}")
        changed = False
        for key, val in k["metadata"].items():
            if key not in meta:
                meta[key] = val
                changed = True
        new_kv, new_qg = kv, qg
        if (kv or "GLOBAL") == "GLOBAL" and not qg and (k["khu_vuc"] != "GLOBAL" or k["quoc_gia"]):
            new_kv, new_qg = k["khu_vuc"], k["quoc_gia"]
            changed = True
        new_url = url
        if (url or "").startswith("https://example.com"):
            new_url = k["source_url"]
            meta.setdefault("ghiChuNguon", "Link example.com cũ là placeholder, đã bỏ")
            changed = True
        if changed:
            conn.execute("UPDATE knowledge SET metadata_json=?, khu_vuc=?, quoc_gia=?, source_url=? WHERE id=?",
                         (json.dumps(meta, ensure_ascii=False), new_kv, new_qg, new_url, rid))
            upgraded.append(code)
    return {"cotMoi": cols_added, "themMoi": added, "capNhat": upgraded}
