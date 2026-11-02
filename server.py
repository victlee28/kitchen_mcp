"""MCP server (stdio) cho thiết kế tủ bếp tham số — adapter mỏng gọi kitchen.service.

Luồng: tạo thiết kế (mẫu / mô tả / spec) -> sửa bằng lệnh có base_rev -> kiểm tra quy tắc
-> render ảnh điều khiển (nét, depth, normal, mask) theo các góc nhìn để làm đầu vào cho AI tạo ảnh.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image
from pydantic import ValidationError

from kitchen.intent import MauBep
from kitchen.service import KitchenService
from kitchen.store import ConflictError

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("kitchen-design-mcp")

mcp = MCPServer("kitchen-design", description="Thiết kế tủ bếp tham số: tạo, sửa, kiểm tra quy tắc, render ảnh điều khiển cho AI",
                version="0.3.0")
_svc: KitchenService | None = None


def svc() -> KitchenService:
    global _svc
    if _svc is None:
        _svc = KitchenService()
    return _svc


def _call(fn, *a, **kw):
    """Đổi lỗi nghiệp vụ thành ToolError để client (LLM) đọc được lý do."""
    try:
        return fn(*a, **kw)
    except ConflictError as e:
        raise ToolError(f"Xung đột phiên bản: {e}") from e
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:5])
        raise ToolError(f"Dữ liệu không hợp lệ: {msgs}") from e
    except (KeyError, ValueError) as e:
        raise ToolError(str(e).strip("'\"")) from e


# ---------------- tạo thiết kế
def create_design(mau: MauBep | None = None, spec: dict[str, Any] | None = None, ten: str = "Thiết kế tủ bếp") -> dict[str, Any]:
    """Tạo thiết kế mới. Cách 1: `mau` (hình I/L, chiều dài các tường, sâu, đỉnh tủ, tủ lạnh, tủ nóc).
    Cách 2: `spec` đầy đủ dạng KitchenSpec (như fixtures/bep-chu-L.json). Trả id, rev, danh sách module và kết quả kiểm tra."""
    if (mau is None) == (spec is None):
        raise ToolError("Truyền đúng một trong hai: mau hoặc spec")
    return _call(svc().create_from_spec, spec) if spec is not None else _call(svc().create_from_template, mau, ten)


def design_kitchen(customer_prompt: str) -> dict[str, Any]:
    """Tạo thiết kế từ mô tả tự do của khách (tiếng Việt). Phân tích bằng DeepSeek nếu có key, không thì regex.
    Với Claude làm host, ưu tiên create_design(mau=...) vì tham số có cấu trúc chính xác hơn."""
    if not customer_prompt.strip():
        raise ToolError("customer_prompt không được rỗng")
    return _call(svc().create_from_prompt, customer_prompt)


def list_designs() -> list[dict[str, Any]]:
    """Liệt kê các thiết kế đã lưu (id, tên, rev mới nhất)."""
    return svc().list_designs()


def get_design(design_id: str, rev: int | None = None) -> dict[str, Any]:
    """Lấy spec đầy đủ của thiết kế (mặc định bản mới nhất)."""
    return _call(svc().get, design_id, rev)


def design_history(design_id: str) -> list[dict[str, Any]]:
    """Lịch sử phiên bản: mỗi rev và lệnh đã tạo ra nó."""
    return _call(svc().history, design_id)


# ---------------- sửa
def add_module(design_id: str, base_rev: int, module: dict[str, Any], sau_module: str | None = None,
               don_day: bool = True) -> dict[str, Any]:
    """Thêm tủ. `module` theo trường của KitchenSpec (loai, rong, cao, sau, tuong, tu, y, canh...).
    `sau_module`: đặt ngay sau module này (kế thừa tường/tầng/cao/sâu). `don_day`: dịch các tủ phía sau cho khít."""
    return _call(svc().apply, design_id, {"op": "add", "module": module, "sauModule": sau_module, "donDay": don_day}, base_rev, "mcp")


def update_module(design_id: str, base_rev: int, ma: str, thay_doi: dict[str, Any], don_day: bool = True) -> dict[str, Any]:
    """Sửa thông số một tủ (vd {"rong": 800} hoặc {"loai": "tren-kinh"}). Đổi rộng thì cánh giữ tỉ lệ và dãy được dồn."""
    return _call(svc().apply, design_id, {"op": "update", "ma": ma, "thayDoi": thay_doi, "donDay": don_day}, base_rev, "mcp")


def remove_module(design_id: str, base_rev: int, ma: str, don_day: bool = True) -> dict[str, Any]:
    """Xóa một tủ; `don_day` kéo các tủ phía sau lấp chỗ trống."""
    return _call(svc().apply, design_id, {"op": "remove", "ma": ma, "donDay": don_day}, base_rev, "mcp")


def update_global(design_id: str, base_rev: int, thay_doi: dict[str, Any]) -> dict[str, Any]:
    """Sửa tham số chung (chung.*): matDa, deMatDa, dinhTu, tran, kheCanh, vatLieu..."""
    return _call(svc().apply, design_id, {"op": "chung", "thayDoi": thay_doi}, base_rev, "mcp")


def set_moldings(design_id: str, base_rev: int, phao_noc: bool = True, phao_chan: bool = True,
                 profile_noc: str = "classic-crown-layered", profile_chan: str = "classic-base",
                 phong_cach: Literal["Modern", "Classic", "Neoclassical", "Transitional", "Industrial", "Minimalist"] | None = "Classic",
                 dau_ho: Literal["tra-ve-tuong", "cat-phang"] = "tra-ve-tuong") -> dict[str, Any]:
    """Bật/tắt phào nóc, phào chân (đường chạy tự tính theo dãy tủ, góc chữ L vát 45°, đầu hở quay về tường).
    Nếu phào nóc vượt trần, validate trả issue MOLDING-TRAN-001 kèm hanhDong: hạ đỉnh tủ hoặc để nguyên (gọi apply_action)."""
    from kitchen.moldings import default_moldings
    ms = [m.model_dump() | {"dauHo": dau_ho} for m in default_moldings(phao_noc, phao_chan, profile_noc, profile_chan)]
    return _call(svc().apply, design_id, {"op": "phao-dat", "moldings": ms, "phongCach": phong_cach}, base_rev, "mcp")


def list_molding_profiles(design_id: str | None = None) -> dict[str, Any]:
    """Các mặt cắt phào có sẵn (và mặt cắt riêng của thiết kế): chiều cao, độ nhô, toạ độ (u, v)."""
    return _call(svc().molding_profiles, design_id)


def apply_action(design_id: str, base_rev: int, op: dict[str, Any]) -> dict[str, Any]:
    """Thực hiện một lựa chọn trong `hanhDong` của issue (vd {"op":"ha-dinh","dinhMoi":2550} hoặc
    {"op":"phao","ma":"phao-noc","thayDoi":{"boQuaTran":true}}). Chỉ nhận op: ha-dinh, phao, phao-dat."""
    if op.get("op") not in ("ha-dinh", "phao", "phao-dat"):
        raise ToolError("apply_action chỉ nhận op ha-dinh, phao, phao-dat; dùng tool sửa module cho thao tác khác")
    return _call(svc().apply, design_id, op, base_rev, "mcp-action")


def revert_design(design_id: str, base_rev: int, ve_rev: int) -> dict[str, Any]:
    """Hoàn tác: tạo rev mới có nội dung giống `ve_rev`."""
    return _call(svc().revert, design_id, ve_rev, base_rev)


# ---------------- kiểm tra, hình học, ảnh
def validate_design(design_id: str, rev: int | None = None, quoc_gia: str | None = None, khu_vuc: str | None = None) -> dict[str, Any]:
    """Kiểm tra tất định: hình học + quy tắc KB. Mỗi chủ đề dùng tiêu chuẩn ưu tiên của quốc gia > khu vực > toàn cầu
    (mặc định theo spec.quocGia/khuVuc; truyền quoc_gia như 'VN','US','AU' để kiểm theo nước khác). `quyTacDaDung` cho biết mục nào được áp."""
    return _call(svc().validate, design_id, rev, quoc_gia, khu_vuc)


def get_scene(design_id: str, rev: int | None = None) -> dict[str, Any]:
    """Scene đã biên dịch: danh sách khối hộp (center/size mm, loại chi tiết, module) + góc nhìn."""
    return _call(svc().scene, design_id, rev)


def export_threejs(design_id: str, rev: int | None = None, quoc_gia: str | None = None, tra_noi_dung: bool = False) -> dict[str, Any]:
    """Xuất JSON theo "Complete Kitchen Three.js Scene Schema" v1.1 (hợp lệ cả v1.0.0): room, materials, assets, modules
    (parts/doors/drawers/shelves/tay nắm), appliances, accessories (mặt đá có lỗ khoét, chậu, ốp tường), lighting, cameras,
    constraints theo tiêu chuẩn vùng, renderSettings. Ghi file renders/<id>/rev<N>/scene.threejs.json; `tra_noi_dung` trả cả JSON."""
    import jsonschema
    from pathlib import Path
    doc = _call(svc().threejs, design_id, rev, quoc_gia)
    schema = json.loads((Path(__file__).resolve().parent / "schemas" / "kitchen-threejs.schema.json").read_text(encoding="utf-8"))
    errs = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(doc)][:5]
    out_dir = svc().render_dir / design_id / f"rev{doc['metadata']['revision']}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "scene.threejs.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    res = {"file": str(path), "hopLeSchema": not errs, "loiSchema": errs,
           "dem": {k: len(doc[k]) for k in ("modules", "appliances", "accessories", "materials", "lighting", "cameras")},
           "soChiTiet": sum(len(m["parts"]) + len(m["doors"]) + len(m["drawers"]) for m in doc["modules"])}
    if tra_noi_dung:
        res["doc"] = doc
    return res


def render_views(design_id: str, rev: int | None = None, views: list[str] | None = None, width: int = 1280,
                 height: int = 960, kem_anh: Literal["khong", "lines", "lines+depth"] = "lines") -> list[Any]:
    """Render ảnh điều khiển cho AI theo các góc nhìn (mặc định: mọi góc trong spec.gocNhin).
    Mỗi góc ghi: lines.png, depth.png, depth16.png, normal.png, seg.png, seg_module.png, camera.json vào renders/<id>/rev<N>/<góc>/.
    `kem_anh` trả kèm ảnh để xem trực tiếp."""
    res = _call(svc().render, design_id, rev, views, width, height)
    out: list[Any] = [json.dumps(res, ensure_ascii=False, indent=1)]
    if kem_anh != "khong":
        kinds = ["lines"] + (["depth"] if kem_anh == "lines+depth" else [])
        for v in res["views"].values():
            for k in kinds:
                out.append(Image(path=f"{v['dir']}/{k}.png"))
    return out


# ---------------- tri thức
def search_knowledge(query: str = "", kinds: list[Literal["standard", "rule", "material"]] | None = None,
                     quoc_gia: str | None = None, khu_vuc: str | None = None, chi_vung: bool = False) -> dict[str, Any]:
    """Tìm tiêu chuẩn/quy tắc/vật liệu theo từ khóa. Có quoc_gia (ISO: VN, US, CN, AU, GB, DE...) hoặc khu_vuc
    (SEA, EA, NA, EU, OC) thì xếp quốc gia > khu vực > toàn cầu > nước khác; `chi_vung` bỏ mục của nơi khác."""
    return {"items": _call(svc().search_knowledge, query, kinds, quoc_gia, khu_vuc, chi_vung)}


def list_regions() -> dict[str, Any]:
    """Danh sách khu vực, quốc gia hỗ trợ và số mục tri thức của từng nơi."""
    return svc().list_regions()


def add_knowledge(kind: Literal["standard", "rule", "material"], code: str, title: str, content: str, source_url: str = "",
                  metadata: dict[str, Any] | None = None, khu_vuc: str = "GLOBAL", quoc_gia: str = "") -> dict[str, Any]:
    """Thêm/cập nhật (theo code) mục tri thức kèm khu_vuc và quoc_gia (ISO, nhiều nước cách dấu phẩy).
    Để bộ kiểm tra dùng: metadata = {"loaiNguon": "bat-buoc|tieu-chuan|khuyen-nghi|thuc-hanh", "kiemTra": ["hut-mui"],
    "params": {"khoang_min": 650}}. Chủ đề hỗ trợ xem kitchen/rules_kb.py CHU_DE."""
    return _call(svc().add_knowledge, kind=kind, code=code, title=title, content=content, source_url=source_url, metadata=metadata,
                 khu_vuc=khu_vuc, quoc_gia=quoc_gia)


def export_ai_package(design_id: str, rev: int | None = None, views: list[str] | None = None, kem_anh: bool = True,
                      quoc_gia: str | None = None, nhung_anh: bool = False,
                      anh_sang: Literal["ban-ngay", "nang-chieu", "toi-am"] = "ban-ngay") -> dict[str, Any]:
    """Xuất gói cuối cùng gửi AI tạo ảnh sau khi tạo/sửa xong: renders/<id>/rev<N>/ai/ai-request.json gồm vật liệu (tên + tiếng Anh
    + màu), kiểu cánh, tay nắm, prompt chung/negative, từng góc (camera, prompt dạng câu, ảnh điều khiển) và cảnh three.js.
    kem_anh=True: render ảnh còn thiếu, chép nét/depth/normal/albedo/beauty vào gói và nén ai-package.zip.
    nhung_anh=True: ghi thêm ai-request.full.json có nhúng sẵn ảnh nên gửi của từng góc (một file tự chứa)."""
    res = _call(svc().ai_export, design_id, rev, views, quoc_gia, kem_anh, False, anh_sang)
    if nhung_anh:
        res["fileNhungAnh"] = _call(svc().ai_export, design_id, rev, views, quoc_gia, False, True, anh_sang)["file"]
    return res


# ---------------- sửa ảnh theo lớp
def _slim_job(j: dict) -> dict:
    r = j["result"]
    return {"id": j["id"], "status": j["status"], "error": j["error"], "kind": j["kind"], "mode": j["mode"], "target": j["target"],
            "backend": j["backend"], "view": j["view"], "rev": j["rev"], "renderKey": j["render_key"], "dir": r.get("dir"),
            "phamVi": j["request"].get("phamVi"), "prompt": j["request"].get("prompt"), "report": r.get("report"),
            "thietKe": r.get("thietKe"), "goi": r.get("goi"),
            "requestFile": str(Path(r["dir"]) / "request.json") if r.get("dir") and (Path(r["dir"]) / "request.json").exists() else None,
            "tasks": [{k: t.get(k) for k in ("targetLayer", "vatLieu", "instruction", "phamVi", "maskPixels")}
                      for t in j["request"].get("tasks") or []]}


def list_layers(design_id: str, view: str, rev: int | None = None, tat_ca: bool = False) -> dict[str, Any]:
    """Layer chọn được ở một góc nhìn (render nếu chưa có). Layer ID = ID chi tiết (vd TD1-canh-1); nhóm: matTruoc:TD1,
    module:TD1, loai:mat-da. Mỗi layer có vatLieu hiện tại, số pixel thấy được và `suaThietKe` (phạm vi nếu áp vào thiết kế).
    Trả thêm renderKey và ảnh gốc đang dùng (ảnh đã chấp nhận gần nhất, hoặc albedo)."""
    r = _call(svc().images.layers, design_id, view, rev, tat_ca)
    r["layers"] = [{k: v for k, v in x.items() if k not in ("allowGeometryChange", "allowPositionChange", "selectable")}
                   for x in r["layers"]]
    return r


def create_image_job(design_id: str, view: str, target_layer: str | None = None, instruction: str = "",
                     mode: Literal["thu-nhanh", "thiet-ke"] = "thu-nhanh", vat_lieu: str | None = None,
                     backend: Literal["to-mau", "goi-job", "comfyui", "gemini"] = "to-mau", kind: Literal["edit", "gen0", "hinh"] = "edit",
                     reference: str | None = None, base_rev: int | None = None, workflow: str | None = None,
                     seed: int | None = None, tasks: list[dict[str, Any]] | None = None,
                     xem_truoc: bool = False, hinh: list[dict[str, Any]] | None = None,
                     thao_tac: Literal["doi-vat-lieu", "thay-vat", "xoa-vat", "them-vat", "doi-phong-cach"] | None = None,
                     anh_sang: Literal["ban-ngay", "nang-chieu", "toi-am"] | None = None) -> dict[str, Any]:
    """Tạo job sinh/sửa ảnh. kind=edit: sửa MỘT layer trên ảnh gốc, ghép strict (ngoài mask giữ nguyên ảnh gốc).
    mode=thiet-ke: cần vat_lieu, phạm vi = mọi chi tiết đổi vật liệu theo thao tác đó; thiết kế chỉ đổi khi accept.
    mode=thu-nhanh: chỉ đổi ảnh. backend: to-mau (đổi màu, không AI, cần màu trong vat_lieu), goi-job (xuất gói cho ComfyUI,
    nộp ảnh sau bằng submit_image_result), comfyui (cần ComfyUI chạy, COMFYUI_URL), gemini (Gemini API; khóa qua
    GEMINI_API_KEY hoặc GEMINI_ENV_FILE). Job comfyui/gemini chạy nền: dùng get_image_job(job_id, cho_giay=120). kind=gen0: ảnh đầy đủ từ nét+depth.
    reference: 'albedo' | job id | bỏ trống = ảnh đã chấp nhận gần nhất.
    Nhiều việc trong một job: tasks=[{"target_layer": "matTruoc:TD1", "vat_lieu": "Laminate xanh rêu"},
    {"target_layer": "tayNam:TD1", "vat_lieu": "Đồng vàng"}, ...] (tối đa 8; các việc không được chạm cùng chi tiết;
    instruction khi đó là yêu cầu chung). Tay nắm: layer tayNam:<module>, loai:tay-nam hoặc <module>-tay-nam-<n>.
    xem_truoc=True: chỉ chuẩn bị mask + request.json (requestFile), job dừng ở 'cho-gui'; gửi bằng send_image_job, hủy bằng reject_image_job.
    kind=hinh — SỬA HÌNH trên ảnh (xóa/thêm/thay vật): hinh=[{"loai": "xoa-module", "ma": "TD3", "donDay": false} |
    {"loai": "them-module", "module": {...}, "sauModule": "TD3"} | {"loai": "kieu-canh", "ma": "TD1"|"*", "kieu": "phang|khung|kinh"} |
    {"loai": "tay-nam", "kieu": "thanh|num|am|khong"} | {"loai": "op", "op": {...}}]. Hệ thống áp thao tác lên bản sao thiết kế, render lại
    cùng camera, mask = vùng khác giữa cũ/mới, model vẽ lại vùng đó theo nét/depth của thiết kế MỚI; accept = ghi rev mới.
    anh_sang: ánh sáng cho ảnh đầy đủ gen0 (ban-ngay | nang-chieu | toi-am); câu lệnh luôn kèm yêu cầu ảnh thật (máy ảnh kiến trúc,
    vật liệu, bóng tiếp xúc, khe cánh…); sửa vùng thì bám ánh sáng/nhiễu hạt của ảnh gốc.
    thao_tac: chọn sẵn workflow + trọng số ControlNet (doi-vat-lieu/thay-vat/xoa-vat/them-vat cho edit/hinh, doi-phong-cach cho gen0)."""
    return _slim_job(_call(svc().images.create, design_id, view, target_layer, instruction, mode, vat_lieu, backend, reference,
                           base_rev, kind, workflow, seed, None, tasks, xem_truoc, hinh, thao_tac, anh_sang))


def send_image_job(job_id: str) -> dict[str, Any]:
    """Gửi job đang 'cho-gui' (tạo với xem_truoc=True) sang backend sau khi đã xem request.json."""
    return _slim_job(_call(svc().images.send, job_id))


def get_image_job(job_id: str, cho_giay: float = 0) -> dict[str, Any]:
    """Trạng thái job: cho-gui | dang-chay | cho-ket-qua | can-duyet | da-chap-nhan | tu-choi | loi:<ma>. cho_giay>0: chờ job comfyui."""
    if cho_giay > 0:
        return _slim_job(_call(svc().images.wait, job_id, min(cho_giay, 300)))
    return _slim_job(_call(svc().images.get, job_id))


def list_image_jobs(design_id: str | None = None, view: str | None = None, status: str | None = None) -> dict[str, Any]:
    """Danh sách job sinh ảnh (mới nhất trước)."""
    return {"items": [_slim_job(j) for j in _call(svc().images.list, design_id, view, status)]}


def submit_image_result(job_id: str, image_path: str) -> dict[str, Any]:
    """Nộp ảnh kết quả (PNG/JPEG trên máy) cho job goi-job; hệ thống ghép strict và kiểm tra rồi chuyển sang can-duyet."""
    from pathlib import Path
    p = Path(image_path).expanduser()
    if not p.is_file():
        raise ToolError(f"Không thấy file {p}")
    return _slim_job(_call(svc().images.submit_result, job_id, p.read_bytes()))


def accept_image_job(job_id: str, ap_vao_thiet_ke: bool = False, base_rev: int | None = None) -> dict[str, Any]:
    """Chấp nhận ảnh: thành ảnh gốc cho lần sửa sau. mode thiet-ke (hoặc ap_vao_thiet_ke=True với job có vat_lieu)
    thì ghi thao tác vật liệu vào thiết kế thành rev mới; lỗi Xung đột nếu thiết kế đã đổi sau khi tạo job."""
    return _slim_job(_call(svc().images.accept, job_id, ap_vao_thiet_ke, base_rev))


def reject_image_job(job_id: str) -> dict[str, Any]:
    """Từ chối ảnh của job (không đổi thiết kế)."""
    return _slim_job(_call(svc().images.reject, job_id))


def regenerate_image_job(job_id: str, seed: int | None = None) -> dict[str, Any]:
    """Sinh lại: tạo job mới cùng yêu cầu, seed mới."""
    return _slim_job(_call(svc().images.regenerate, job_id, seed))


TOOLS = [create_design, design_kitchen, list_designs, get_design, design_history, add_module, update_module, remove_module,
         update_global, set_moldings, list_molding_profiles, apply_action, revert_design, validate_design, get_scene, export_threejs, render_views, search_knowledge, list_regions, add_knowledge, export_ai_package,
         list_layers, create_image_job, get_image_job, list_image_jobs, submit_image_result, accept_image_job,
         reject_image_job, regenerate_image_job, send_image_job]
for _fn in TOOLS:
    mcp.add_tool(_fn, name=_fn.__name__, description=(_fn.__doc__ or "").strip(),
                 structured_output=False if _fn is render_views else None)


def main() -> None:
    logger.info("Starting kitchen-design MCP server (stdio), %d tools", len(TOOLS))
    s = svc()
    logger.info("SQLite: %s · renders: %s", s.store.path, s.render_dir)
    try:
        mcp.run("stdio")
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("MCP server stopped")


if __name__ == "__main__":
    main()
