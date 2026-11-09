"""Conversion of legacy Vietnamese-keyed data to the English schema.

The project originally used Vietnamese field names, operation names, enum values, file names, and
SQLite column names. This module is the single place that knows the old names. It is used to:

- migrate ``kitchen.db`` (columns, stored specifications, operations, jobs, knowledge rows),
- migrate generated files under ``renders/``,
- import old specification JSON files via :func:`convert_spec`.

Everything here is data-only and uses the standard library, so it can run before the application models load.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

# Legacy key -> English key (JSON field names, API parameters, SQL columns).
KEYS = {
    'goi': 'package',
    'taoLuc': 'createdAt',
    'cachDung': 'usage',
    'nhan': 'label',
    'anhGui': 'sentImage',
    'anh': 'image',
    'anhDauVaoGoiY': 'suggestedInputImages',
    'anhDinhKem': 'attachedImages',
    'anhGoc': 'baseImage',
    'anhNhung': 'embeddedImages',
    'anhSang': 'lighting',
    'anhThat': 'photoImage',
    'anhTho': 'rawImage',
    'anh_sang': 'lighting',
    'anh_that': 'photo_image',
    'ap': 'apply',
    'apDung': 'apply',
    'apVaoThietKe': 'applyToDesign',
    'ap_vao_thiet_ke': 'apply_to_design',
    'bat': 'enabled',
    'batBuoc': 'required',
    'ben_lon': 'larger_side',
    'ben_nho': 'smaller_side',
    'bep': 'cooktop',
    'bep_tams': 'cooktop_centers',
    'boQua': 'skip',
    'boQuaTran': 'ignoreCeiling',
    'bo_qua': 'skip',
    'buoc': 'step',
    'by_ma': 'by_id',
    'cac_canh': 'door_widths',
    'cach_chau_max': 'sink_distance_max',
    'cam': 'camera',
    'camId': 'cameraId',
    'cam_info': 'camera_info',
    'canCauHinh': 'needsConfig',
    'canh': 'doors',
    'canhBao': 'warning',
    'canhPhai': 'rightLength',
    'canhSau': 'backLength',
    'canh_max': 'door_max',
    'canh_min': 'door_min',
    'canh_noc': 'loft_door',
    'cao': 'height',
    'caoBauCua': 'sillHeight',
    'cao_tren': 'upper_height',
    'capNhat': 'update',
    'chapNhanLuc': 'acceptNow',
    'chau': 'sink',
    'chau_bep_min': 'sink_cooktop_min',
    'cheDoBaoToan': 'preserveMode',
    'chiDan': 'instruction',
    'chiTiet': 'part',
    'chiVung': 'regionOnly',
    'chi_tiet': 'part',
    'chi_tu': 'cabinets_only',
    'chi_vung': 'region_only',
    'chiaTangTren': 'upperTierSplit',
    'cho_dung_min': 'standing_space_min',
    'chuDe': 'topic',
    'chua-ro': 'unknown',
    'chuaGui': 'notSent',
    'chuaKiemTra': 'unchecked',
    'chuan': 'standard_widths',
    'chuan_hoa': 'normalize',
    'chung': 'common',
    'coThayDoi': 'changed',
    'conLai': 'remaining',
    'cong_them': 'extra',
    'cotMoi': 'newColumn',
    'cua_min': 'window_min',
    'dai': 'length',
    'daiTuongPhai': 'rightWallLength',
    'daiTuongSau': 'backWallLength',
    'dang': 'format',
    'datBaoToan': 'setPreserve',
    'datBien': 'setEdge',
    'dauHo': 'openEnd',
    'day': 'thickness',
    'dayCanh': 'doorThickness',
    'dayHau': 'backThickness',
    'dayMatDa': 'countertopThickness',
    'dayTuTren': 'upperBottom',
    'day_duoi_mat_da_min': 'gap_under_countertop_min',
    'day_max': 'bottom_max',
    'day_tu_tren': 'upper_bottom',
    'deMatDa': 'baseTop',
    'diem': 'score',
    'diem_uu_tien': 'priority_score',
    'dienTich_min_m2': 'area_min_m2',
    'dinh': 'top',
    'dinhMoi': 'newTop',
    'dinhTu': 'cabinetTop',
    'dinh_kem': 'attached',
    'dinh_moi': 'new_top',
    'doDuoc': 'measured',
    'doRender': 'runRender',
    'doiKichThuoc': 'resize',
    'doiTuong': 'target',
    'donDay': 'closeGap',
    'donVi': 'unit',
    'don_day': 'close_gap',
    'dungCho': 'usedFor',
    'duoi': 'base',
    'fileGuiAI': 'aiRequestFile',
    'fileNhungAnh': 'embeddedImagesFile',
    'fovDoc': 'verticalFov',
    'gachNen': 'floorTile',
    'gachOp': 'wallTile',
    'gemini_text_hinh': 'gemini_text_geometry',
    'ghiChu': 'note',
    'ghiChuNguon': 'sourceNote',
    'ghimCamera': 'pinCamera',
    'gioiHan': 'limit',
    'giu': 'keep',
    'goc': 'origin',
    'gocKhuat': 'blindCorner',
    'gocNhin': 'cameraViews',
    'hDonDay': 'hCloseGap',
    'hDonWrap': 'hCloseGapWrap',
    'hKieu': 'hStyle',
    'hKieuWrap': 'hStyleWrap',
    'hLoai': 'hType',
    'hMa': 'hId',
    'hMaWrap': 'hIdWrap',
    'h_noc': 'h_loft',
    'ha': 'lower',
    'haiDay_min': 'twoRows_min',
    'hanhDong': 'action',
    'het': 'endAt',
    'hinh': 'geometry_edit',
    'hinhBox': 'geometryBox',
    'hinhForm': 'geometryForm',
    'hinhGoc': 'originalGeometry',
    'hinhItem': 'geometryItem',
    'hinhMau': 'sampleGeometry',
    'hinhText': 'geometryText',
    'hinh_items': 'geometry_items',
    'hoc': 'niche',
    'hopLe': 'valid',
    'hopLeSchema': 'schemaValid',
    'huongDan': 'instructions',
    'hut': 'hood',
    'jThao': 'jOperation',
    'jVat': 'jItem',
    'keGoc': 'cornerShelf',
    'ke_goc': 'corner_shelf',
    'kem': 'attached',
    'kemAnh': 'withImage',
    'ketQua': 'result',
    'khacBiet': 'different',
    'khacChiTiet': 'partDifferences',
    'khacMau': 'colorDifferences',
    'khacNet': 'lineDifferences',
    'kheCanh': 'doorGap',
    'khoangHutMui': 'hoodGap',
    'khoangNoi': 'joinGap',
    'khoangTuTren': 'upperGap',
    'khoang_min': 'gap_min',
    'khoang_tren_max': 'upper_gap_max',
    'khoang_tren_min': 'upper_gap_min',
    'khongDuoc': 'notAllowed',
    'khong_doi': 'unchanged',
    'khong_hut_mui_min': 'no_hood_min',
    'khopNet': 'lineMatch',
    'khuVuc': 'region',
    'khu_vuc': 'region',
    'khungPhanTram': 'boxPercent',
    'khung_phan_tram': 'box_percent',
    'kichThuoc': 'dimensions',
    'kich_thuoc_so': 'numeric_dimensions',
    'kich_thuoc_theo_vung': 'dimensions_by_region',
    'kiemTra': 'validation',
    'kiem_tra': 'check',
    'kieu': 'variant',
    'kieuCanh': 'doorStyle',
    'lenChan': 'plinthHeight',
    'lenChan_max': 'plinthHeight_max',
    'lenChan_min': 'plinthHeight_min',
    'lien': 'joined',
    'lo': 'openings',
    'loai': 'type',
    'loaiEn': 'typeEn',
    'loaiNguon': 'sourceType',
    'loai_lut': 'type_lut',
    'loai_tb': 'appliance_type',
    'loi': 'errors',
    'loiDi': 'walkway',
    'loiDi_1nguoi': 'walkway_1person',
    'loiDi_min': 'walkway_min',
    'loiDi_nhieuNguoi': 'walkway_multiPerson',
    'loiDi_tiepCan_min': 'walkway_accessible_min',
    'loiQuaLai_min': 'passage_min',
    'loiSchema': 'schemaErrors',
    'luu_luong_min_cfm': 'flow_min_cfm',
    'mDinh': 'mTop',
    'mHinh': 'mShape',
    'mNoc': 'mLoft',
    'mPhai': 'mRight',
    'mSau': 'mBack',
    'mTuLanh': 'mFridge',
    'ma': 'id',
    'ma_moi': 'new_id',
    'macDinh': 'default',
    'mask_mau': 'mask_color',
    'mat': 'material_text',
    'matDa': 'countertop',
    'matDa_cho_phep': 'countertop_allowed',
    'matDa_max': 'countertop_max',
    'matDa_min': 'countertop_min',
    'matTruoc': 'frontSections',
    'mat_da': 'countertop',
    'mat_dat_min': 'floor_min',
    'mat_en': 'face_en',
    'mau': 'color',
    'mauTrungBinh': 'meanColor',
    'mauVien': 'borderColor',
    'mauVung': 'zoneColor',
    'mau_ro': 'explicit_color',
    'mo': 'hinge',
    'moCanh': 'hingeSides',
    'moTa': 'description',
    'moTaEn': 'descriptionEn',
    'moduleThayDuoc': 'editableModule',
    'muc': 'level',
    'mucDo': 'severity',
    'muc_tang': 'tier_level',
    'ngoaiMask': 'outsideMask',
    'nguon': 'source',
    'nguon_kt': 'check_source',
    'nhan_uu_tien': 'priority_label',
    'nhinVao': 'lookAt',
    'nho': 'overhang',
    'nhoMatDa': 'countertopOverhang',
    'nhungAnh': 'embedImages',
    'noi': 'place',
    'noiDung': 'content',
    'nopKetQua': 'submitResult',
    'nopTay': 'submitManual',
    'num': 'knob',
    'opTuong': 'wallTile',
    'phamVi': 'scope',
    'pham_vi': 'scope',
    'phanTich': 'analysis',
    'phao': 'molding',
    'phaoChan': 'baseMolding',
    'phaoNoc': 'crownMolding',
    'phao_chan': 'base_molding',
    'phao_noc': 'crown_molding',
    'phong': 'room',
    'phongCach': 'style',
    'phong_cach_prompt': 'style_prompt',
    'phuTrongAnh': 'imageOverlay',
    'pixelKhacGoc': 'pixelsChanged',
    'profilePhaoChan': 'baseMoldingProfile',
    'profilePhaoNoc': 'crownMoldingProfile',
    'promptChung': 'commonPrompt',
    'quocGia': 'country',
    'quoc_gia': 'country',
    'quyTac': 'rule',
    'quyTacDaDung': 'appliedRules',
    'renderHinh': 'renderGeometry',
    'renderKeyMoi': 'newRenderKey',
    'rong': 'width',
    'rong_module': 'module_width',
    'sap_xep': 'sort_rows',
    'sau': 'depth',
    'sauMatDa_min': 'countertopDepth_min',
    'sauModule': 'afterModule',
    'sauTuDuoi': 'baseDepth',
    'sauTuDuoi_max': 'baseDepth_max',
    'sauTuDuoi_min': 'baseDepth_min',
    'sauTuTren': 'upperDepth',
    'sauTuTren_max': 'upperDepth_max',
    'sauTuTren_min': 'upperDepth_min',
    'sau_module': 'after_module',
    'sau_tren': 'upper_depth',
    'soChiTiet': 'partCount',
    'soModule': 'moduleCount',
    'soMuc': 'entryCounts',
    'soNgan': 'shelfCount',
    'suaThietKe': 'designEdit',
    'tam': 'center',
    'tamHong': 'endPanel',
    'tang': 'storey',
    'tang_key': 'storey_key',
    'tayNam': 'handle',
    'tay_nam': 'handle',
    'ten': 'name',
    'ten_anh': 'image_name',
    'thamKhao': 'reference',
    'tham_khao': 'reference',
    'thanh': 'bar',
    'thanhPhan': 'component',
    'thaoTac': 'operation',
    'thaoTacFor': 'operationFor',
    'thao_tac': 'operation',
    'thayDoi': 'changes',
    'thayDoiNgoaiVungSua': 'changesOutsideEditZone',
    'thayDoiTrungBinh': 'meanChange',
    'thay_doi': 'changes',
    'themMoi': 'addNew',
    'theoKhuVuc': 'byRegion',
    'thietBi': 'appliances',
    'thietKe': 'design',
    'thiet_bi': 'appliance',
    'thiet_ke': 'design',
    'thuTu': 'order',
    'tien_to': 'prefix',
    'tiengAnh': 'english',
    'tieng_anh': 'to_english',
    'tim': 'find',
    'to_cam': 'to_camera',
    'tong': 'total',
    'tong_dai_min': 'total_length_min',
    'tong_max': 'total_max',
    'tran': 'ceiling',
    'tran_min': 'ceiling_min',
    'tren': 'upper',
    'trongMask': 'insideMask',
    'truoc': 'front',
    'tu': 'fromCorner',
    'tuCao': 'tall',
    'tuDuoi': 'base',
    'tuLanh': 'fridge',
    'tuNoc': 'loft',
    'tuRev': 'fromRev',
    'tuTren': 'upper',
    'tu_cao': 'tall',
    'tu_cau_mo_ta': 'from_description',
    'tu_duoi': 'base',
    'tu_lanh': 'fridge',
    'tu_tren': 'upper',
    'tu_tu': 'shift_from',
    'tuong': 'wall',
    'tuong_co_tu': 'walls_with_modules',
    'tuyet_doi_min': 'absolute_min',
    'tyLeNetGoc': 'baseLineRatio',
    'tyLeNetKetQua': 'resultLineRatio',
    'tyLeNgoaiNet': 'outsideLineRatio',
    'tyLeTrenNet': 'onLineRatio',
    'ty_le': 'ratio',
    'update_chung': 'update_common',
    'uuTien': 'priority',
    'uu_tien': 'priority',
    'vaiTro': 'role',
    'vatCungLoaiGiuNguyen': 'sameTypeUnchanged',
    'vatLieu': 'material',
    'vatLieuKhoa': 'materialLocked',
    'vat_lieu': 'material',
    'viTri': 'position',
    'vi_tri': 'describe_position',
    'viec': 'task',
    'vung': 'zone',
    'xemTruoc': 'preview',
    'y_hut': 'y_hood',
    'yeuCau': 'request',
    'yeuCauAnhThat': 'photoRequest',
}

# Legacy enum value / identifier -> English value.
VALUES = {
    'bi-ngat': 'interrupted',
    'GEO-CANH': 'GEO-DOOR',
    'GEO-CAO-DO': 'GEO-HEIGHTS',
    'GEO-KHE-HO': 'GEO-GAPS',
    'GEO-MAT-DA': 'GEO-COUNTERTOP',
    'GEO-TRAN': 'GEO-CEILING',
    'GEO-TUONG': 'GEO-WALL',
    'GEO-VA-CHAM': 'GEO-COLLISION',
    'HUT-MUI-001': 'HOOD-001',
    'KHONG-CO': 'NONE',
    'MAT-DA-THACH-ANH': 'MAT-STONE-QUARTZ',
    'MAT-GO-SOI': 'MAT-OAK-LOCAL',
    'MAT-KINH-CUONG-LUC': 'MAT-TEMPERED-GLASS',
    'MOLDING-CANH-LAT-001': 'MOLDING-FLIPUP-001',
    'MOLDING-CHAN-001': 'MOLDING-BASE-001',
    'MOLDING-TRAN-001': 'MOLDING-CEILING-001',
    'TB-LOT-HOC': 'APPLIANCE-NICHE',
    'VN-TU-BEP-PHO-BIEN': 'VN-KITCHEN-COMMON-PRACTICE',
    'WALL-PHAI': 'WALL-RIGHT',
    'WALL-SAU': 'WALL-BACK',
    'WALL-TRAI': 'WALL-LEFT',
    'am': 'concealed',
    'anh-': 'image-',
    'anh-dau-vao': 'input-image',
    'anh-goc': 'base-image',
    'anh-goc-danh-dau': 'marked-base-image',
    'anh-tham-chieu': 'reference-image',
    'ban-bep': 'cooktop-table',
    'ban-chau': 'sink-table',
    'ban-ngay': 'daylight',
    'ban-tu-lanh': 'fridge-table',
    'bat-buoc': 'mandatory',
    'bep': 'cooktop',
    'can-duyet': 'needs-review',
    'canh': 'door',
    'canh-kinh': 'glass-door',
    'cao': 'tall',
    'cao-tu-lanh': 'tall-fridge',
    'cap-nhat': 'update',
    'cat-phang': 'flat-cut',
    'chan': 'plinth',
    'chan-tu': 'cabinet-plinth',
    'chau': 'sink',
    'chau-bep': 'sink-cooktop',
    'chi-tiet': 'part',
    'chieu-cao-thong-thuy': 'clear-height',
    'cho-gui': 'awaiting-send',
    'cho-ket-qua': 'awaiting-result',
    'chua-ghi': 'unspecified',
    'chua-ro': 'unknown',
    'chung': 'common',
    'cua-di': 'entrance',
    'cua-so': 'window',
    'da-chap-nhan': 'accepted',
    'dang-chay': 'running',
    'day-dai': 'long-run',
    'day-du': 'full',
    'den': 'light',
    'doi-phong-cach': 'change-style',
    'doi-vat-lieu': 'change-material',
    'duoi': 'base',
    'duoi-bep': 'base-cooktop',
    'duoi-chau': 'base-sink',
    'duoi-chau-goc': 'base-corner-sink',
    'duoi-cuoi': 'base-end',
    'duoi-lo': 'base-oven',
    'duoi-ngan-keo': 'base-drawers',
    'goc': 'corner',
    'goc-anh-goc': 'original-angle',
    'goc-nhin': 'set-views',
    'goc-trai': 'left-corner',
    'goi-job': 'job-package',
    'gui-ai': 'ai-request',
    'ha-dinh': 'lower-top',
    'het-gio': 'timeout',
    'hinh': 'geometry_edit',
    'hinh-moi': 'new-geometry',
    'ho_tro': 'supported',
    'hoc': 'niche',
    'hong': 'side-panel',
    'hut-mui': 'hood',
    'ke': 'shelf',
    'ke-goc': 'corner-shelf',
    'khac': 'other',
    'khoa-thu': 'test-key',
    'khoang-tu-tren': 'upper-gap',
    'khong': 'none',
    'khong-co': 'none',
    'khong-co-goc': 'no-corner',
    'khong-ho-tro': 'unsupported',
    'khu-nau': 'cooking-area',
    'khung': 'frame',
    'khuyen-nghi': 'recommended',
    'kieu': 'kind',
    'kieu-canh': 'door-style',
    'kinh': 'glass',
    'lo': 'oven',
    'lo-vi-song': 'microwave',
    'loi': 'error',
    'loi-di': 'walkway',
    'loi:khong-dat-kiem-tra': 'error:check-failed',
    'loi:khong-ho-tro': 'error:unsupported',
    'loi:qua-tai': 'error:overloaded',
    'loi:sinh-that-bai': 'error:generation-failed',
    'mask-mau': 'color-mask',
    'mask-minh-hoa': 'mask-illustration',
    'mat-bang': 'plan',
    'mat-da': 'countertop',
    'mat-da-cao': 'countertop-height',
    'nang-chieu': 'late-afternoon',
    'ngan-keo': 'drawer',
    'nhieu': 'multi',
    'nhom': 'group',
    'noc': 'loft',
    'num': 'knob',
    'op-tuong': 'wall-tile',
    'phai': 'right',
    'phang': 'flat',
    'phao': 'molding',
    'phao-chan': 'base-molding',
    'phao-dat': 'set-moldings',
    'phao-noc': 'crown-molding',
    'phoi-canh': 'perspective',
    'phong': 'room',
    'phong-san-1': 'room-floor-1',
    'qua-tai': 'overloaded',
    'san': 'floor',
    'sau': 'back',
    'sau-mat-da': 'countertop-depth',
    'sau-tu-duoi': 'base-depth',
    'sau-tu-tren': 'upper-depth',
    'sinh-that-bai': 'generation-failed',
    'tam-giac': 'triangle',
    'tay-nam': 'handle',
    'than': 'carcass',
    'thanh': 'bar',
    'thay-vat': 'replace-item',
    'them-module': 'add-module',
    'them-moi': 'add-new',
    'them-vat': 'add-item',
    'thiet-ke': 'design',
    'thieu-anh': 'missing-image',
    'thu-nhanh': 'quick',
    'thuc-hanh': 'practice',
    'tieu-chuan': 'standard',
    'to-mau': 'recolor',
    'toi-am': 'dim-evening',
    'tra-ve-tuong': 'return-to-wall',
    'trai': 'left',
    'tren': 'upper',
    'tren-bep': 'above-cooktop',
    'tren-cao': 'overhead',
    'tren-hut-mui': 'upper-hood',
    'tren-kinh': 'upper-glass',
    'tren-noc': 'upper-loft',
    'tu-choi': 'rejected',
    'tu-lanh': 'fridge',
    'tuong': 'wall',
    'tuong-phai': 'right-wall',
    'tuong-sau': 'back-wall',
    'vat-lieu': 'material',
    'voi': 'faucet',
    'xoa-module': 'remove-module',
    'xoa-vat': 'remove-item',
}

# Legacy file-name fragments in generated files.
FILES = {
    'GUI-GEMINI-WEB.txt': 'AI-CHAT-GUIDE.txt',
    'HUONG-DAN.txt': 'INSTRUCTIONS.txt',
    'gui-ai.json': 'ai-request-short.json',
    'hinh_moi.png': 'new_geometry.png',
    'mask_mau.png': 'mask_color.png',
    'reference_danh_dau.png': 'reference_marked.png',
}

# Legacy id prefixes (``prefix:rest``).
PREFIXES = {
    'chung:': 'common:',
    'hinh: ': 'geometry: ',
    'loai:': 'type:',
    'loi:': 'error:',
    'matTruoc:': 'frontSections:',
    'phao:': 'molding:',
    'tayNam:': 'handle:',
    'thietBi:': 'appliances:',
}

# Part-type segments inside part ids such as ``TD1-canh-1``.
PART_TYPES = {
    'bep': 'cooktop',
    'canh': 'door',
    'canh-kinh': 'glass-door',
    'chan': 'plinth',
    'chau': 'sink',
    'hong': 'side-panel',
    'hut-mui': 'hood',
    'ke': 'shelf',
    'lo': 'oven',
    'mat-da': 'countertop',
    'ngan-keo': 'drawer',
    'phao': 'molding',
    'san': 'floor',
    'tay-nam': 'handle',
    'than': 'carcass',
    'tu-lanh': 'fridge',
    'tuong': 'wall',
    'voi': 'faucet',
}

# Legacy keys whose string values are enumerations (looked up in VALUES).
VALUE_KEYS = {
    "tuong", "loai", "kieu", "kieuCanh", "dauHo", "op", "tang", "kind", "view", "mode", "status", "moCanh", "dungCho",
    "chuDe", "loaiNguon", "backend", "thaoTac", "thao_tac", "ma", "sauModule", "semanticClass", "pham_vi",
}
# Legacy view ids (render directory names).
VIEW_IDS = ("mat-bang", "phoi-canh", "tren-cao", "tuong-sau", "tuong-phai", "day-dai", "goc-anh-goc", "goc-trai", "ke-goc", "khu-nau")

_PART_RE = re.compile(r"(?<=-)(" + "|".join(sorted(PART_TYPES, key=len, reverse=True)) + r")(?=-\d+$|$)")
_ID_RE = re.compile(r"^([A-Z]+\d+|room|phong)(-[a-z]+)+(-\d+)?$")
_IMAGE_PREFIX_RE = re.compile(r"""(?:(?<=^)|(?<=-)|(?<=["'(/^]))anh-(?=[0-9\[*{\\])""")
_VIEW_PATH_RE = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(VIEW_IDS) + r")(?![A-Za-z0-9])")
_VIEW_FILE_RE = re.compile(r"^(" + "|".join(VIEW_IDS) + r")(?=[-.]|$)")


_WALL_SUFFIX_RE = re.compile(r"^([a-z-]+)-(sau|phai|trai|goc)$")


def fix_text(text: str) -> str:
    """Rename legacy ids, file names, and path segments inside a string; free text is left unchanged."""
    if text in VIEW_IDS:
        return VALUES[text]
    wall_ref = _WALL_SUFFIX_RE.match(text)
    if wall_ref and wall_ref.group(1) in VALUES:
        return f"{VALUES[wall_ref.group(1)]}-{VALUES[wall_ref.group(2)]}"
    for old, new in PREFIXES.items():
        if text.startswith(old):
            rest = text[len(old):]
            text = new + VALUES.get(rest, KEYS.get(rest, rest))
            break
    if _ID_RE.match(text):
        text = _PART_RE.sub(lambda match: PART_TYPES[match.group(1)], text)
        if text.startswith("phong-"):
            text = "room-" + text[len("phong-"):]
    for old, new in FILES.items():
        text = text.replace(old, new)
    text = _IMAGE_PREFIX_RE.sub("image-", text)
    return text if " " in text else _VIEW_PATH_RE.sub(lambda match: VALUES[match.group(1)], text)


def _convert_value(text: str, key: str | None) -> str:
    if text in VALUES and (key in VALUE_KEYS or "-" in text):
        return VALUES[text]
    return fix_text(text)


_TIER_TO_STOREY = {"wall": "upper", "top": "loft"}


def convert(obj: Any, key: str | None = None) -> Any:
    """Recursively convert legacy keys and enumeration values to the English schema (idempotent)."""
    if isinstance(obj, dict):
        if "toeKickHeight" in obj and "panelThickness" in obj:  # three.js construction block exported before the plinth rename
            obj = {("plinthHeight" if k == "toeKickHeight" else k): v for k, v in obj.items()}
        if "tier" in obj and "sourceRef" in obj:  # three.js module entry exported before the storey rename
            obj = {("storey" if k == "tier" else k): _TIER_TO_STOREY.get(v, v) if k == "tier" else v for k, v in obj.items()}
        return {(KEYS.get(k) or VALUES.get(k) or fix_text(k)): convert(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert(item, key) for item in obj]
    if isinstance(obj, str):
        return _convert_value(obj, key)
    return obj


def convert_spec(data: dict) -> dict:
    """Convert an old specification dictionary (for example an old design JSON file) to the English schema."""
    return convert(data)


COLUMN_RENAMES = (
    ("designs", "ten", "name"),
    ("revisions", "thao_tac", "operation"),
    ("revisions", "nguon", "source"),
    ("knowledge", "khu_vuc", "region"),
    ("knowledge", "quoc_gia", "country"),
)


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _json_text(text: str | None, default: str = "{}") -> str:
    data = json.loads(text or default)
    return json.dumps(convert(data), ensure_ascii=False)


def migrate_database(conn: sqlite3.Connection) -> bool:
    """Rename legacy columns and convert stored JSON/enum values once (tracked by ``PRAGMA user_version``)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 1:
        return False
    for table, old, new in COLUMN_RENAMES:
        columns = _columns(conn, table)
        if old in columns and new not in columns:
            conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
    conn.execute("DROP INDEX IF EXISTS idx_knowledge_vung")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "revisions" in tables:
        for design_id, rev, spec_json, operation in conn.execute("SELECT design_id, rev, spec_json, operation FROM revisions").fetchall():
            conn.execute("UPDATE revisions SET spec_json=?, operation=? WHERE design_id=? AND rev=?",
                         (_json_text(spec_json), _json_text(operation), design_id, rev))
    if "knowledge" in tables:
        for row_id, code, metadata in conn.execute("SELECT id, code, metadata_json FROM knowledge").fetchall():
            conn.execute("UPDATE knowledge SET code=?, metadata_json=? WHERE id=?",
                         (VALUES.get(code, code), _json_text(metadata), row_id))
    if "image_jobs" in tables:
        rows = conn.execute("SELECT id, view, kind, mode, target, backend, status, request_json, result_json FROM image_jobs").fetchall()
        for job_id, view, kind, mode, target, backend, status, request, result in rows:
            conn.execute(
                "UPDATE image_jobs SET view=?, kind=?, mode=?, target=?, backend=?, status=?, request_json=?, result_json=? WHERE id=?",
                (_convert_value(view, "view"), _convert_value(kind, "kind"), _convert_value(mode, "mode"),
                 fix_text(target) if target else target, _convert_value(backend, "backend"), _convert_value(status, "status"),
                 _json_text(request), _json_text(result), job_id))
    conn.execute("PRAGMA user_version = 1")
    return True


def _convert_file_name(name: str) -> str:
    name = _VIEW_FILE_RE.sub(lambda match: VALUES[match.group(1)], name)
    name = re.sub(r"(?<=-)(" + "|".join(VIEW_IDS) + r")(?=\.[a-z0-9]+$)", lambda match: VALUES[match.group(1)], name)
    name = re.sub(r"(?<=-)(anh-[a-z-]+)(?=\.[a-z0-9]+$)", lambda match: VALUES.get(match.group(1), match.group(1)), name)
    return fix_text(re.sub(r"(?<=-)anh-(?=\d)", "image-", name))


def migrate_renders(root: Path) -> int:
    """Rename legacy files and directories under ``renders/`` and rewrite their JSON content once."""
    root = Path(root)
    marker = root / ".english-schema-v1"
    if not root.exists() or marker.exists():
        return 0
    changed = 0
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        new_name = _convert_file_name(path.name)
        target = path.with_name(new_name)
        if new_name != path.name and not target.exists():
            path.rename(target)
            changed += 1
    for path in root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        converted = convert(data)
        if converted != data:
            path.write_text(json.dumps(converted, ensure_ascii=False, indent=1), encoding="utf-8")
            changed += 1
    marker.write_text("1", encoding="utf-8")
    return changed
