# Kitchen Design MCP (v0.3)

Thiết kế tủ bếp **tham số**: tạo, sửa, thêm/bớt tủ, kiểm tra quy tắc, và render **ảnh điều khiển**
(nét, depth, normal, mask) theo nhiều góc nhìn để làm đầu vào cho AI tạo ảnh ở bước sau.

```
Claude / MCP host ─┐                       ┌─> rules.py   (kiểm tra tất định)
                   ├─> service.py ─ edit ─> KitchenSpec (SQLite, có rev) ─┤
Web editor ────────┘                       └─> geometry.py (spec -> khối hộp) ─┬─> viewer three.js
                                                                              └─> render.py -> PNG
```

## Cài đặt (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .            # mcp, pydantic, numpy, pillow
copy .env.example .env      # tùy chọn: DEEPSEEK_API_KEY... (.env được nạp tự động)
```

- Web editor: chạy `run.bat` rồi mở http://localhost:8080/web/ (log ở `logs\web.log`).
- MCP (stdio): `python server.py` hoặc `kitchen-design-mcp`. Ví dụ cấu hình Claude Desktop:

```json
{"mcpServers": {"kitchen-design": {
  "command": "C:\\Users\\XPC\\Desktop\\image\\mcp-imagev2\\.venv\\Scripts\\python.exe",
  "args": ["C:\\Users\\XPC\\Desktop\\image\\mcp-imagev2\\server.py"]}}}
```

- Test: `python -m unittest discover -s tests -v`

## Thành phần

| File | Vai trò |
|---|---|
| `kitchen/spec.py` | KitchenSpec (Pydantic), giữ tên trường như `bep-chu-L-thong-so.json`; thêm `gocKhuat`, `tamHong`, `matTruoc`, `hoc`, `phong`, thiết bị có `tuong`/`tam`/`module` |
| `kitchen/geometry.py` | Biên dịch spec -> khối hộp toạ độ thế giới (mm). Quy ước: gốc ở góc trong, tường sau chạy theo −x, tường phải theo +z |
| `kitchen/rules.py` | Va chạm, cao độ tầng, cánh, tường, thiết bị lọt hốc + quy tắc KB có tham số (`metadata.params`) |
| `kitchen/regions.py` | Khu vực (GLOBAL, SEA, EA, NA, EU, OC), quốc gia ISO và thứ tự ưu tiên: quốc gia > khu vực > toàn cầu > nước khác (chỉ tham khảo) |
| `kitchen/rules_kb.py` | Kiểm tra theo chủ đề (mặt bàn, hút mùi, lối đi, tam giác làm việc…); mỗi chủ đề dùng mục tri thức ưu tiên nhất cho quốc gia của thiết kế |
| `kitchen/knowledge_seed.py`, `seed_knowledge.py` | Kho tri thức nền theo vùng + migration cột `khu_vuc`, `quoc_gia`. `python seed_knowledge.py` chỉ thêm/bổ sung, không ghi đè mục đã sửa |
| `kitchen/edit.py` | Thêm / sửa / xóa module, dồn dãy, sửa tham số chung |
| `kitchen/intent.py` | Mô tả -> mẫu (regex đã sửa lỗi đơn vị; DeepSeek JSON mode nếu có key, lỗi thì lùi về regex) -> spec |
| `kitchen/store.py` | SQLite: `knowledge` (upsert theo code), `designs`, `revisions` (append-only, kiểm `base_rev`) |
| `kitchen/render.py` | Rasterizer numpy, không cần GPU/trình duyệt |
| `kitchen/threejs_export.py`, `schemas/`, `web/scene-loader.js` | Xuất JSON theo Complete Kitchen Three.js Scene Schema (v1.1, tương thích v1.0) và dựng lại bằng three.js — xem `schemas/README.md` |
| `kitchen/moldings.py` | Phào cổ điển: preset mặt cắt, đường chạy tự tính theo dãy tủ (góc chữ L vát 45°, đầu hở quay về tường, tủ sâu hơn tách đoạn), quét thành lưới, kiểm tra trần/cánh lật/phào chân |
| `kitchen/hardware.py` | Bản lề từng cánh, vị trí/kích thước tay nắm — một nguồn cho hình học (render/mask) và JSON three.js |
| `kitchen/layers.py`, `kitchen/vocab.py` | Danh mục layer (layer ID = ID chi tiết), vật liệu từng chi tiết, thao tác sửa thiết kế tương ứng, prompt |
| `kitchen/imaging.py`, `kitchen/imagejobs.py`, `kitchen/backends.py`, `workflows/` | Sửa ảnh theo lớp: mask từ instance, job, ghép strict, kiểm tra, backend `to-mau` / `goi-job` / `comfyui` |
| `kitchen/ai_export.py` | Gói JSON cuối cùng gửi AI tạo ảnh (prompt từng góc, vật liệu, cảnh three.js, ảnh điều khiển) |
| `server.py` | 29 tool MCP; lỗi trả về `ToolError` có lý do rõ ràng |
| `web_server.py` | HTTP API + web; chỉ phục vụ `/web` và `/renders`, không CORS, bắt buộc JSON |
| `fixtures/bep-chu-L.json` | Bếp chữ L chuẩn (16 module, 8 góc nhìn), dùng làm mẫu và test |

## Tiêu chuẩn theo khu vực / quốc gia

- Mỗi mục tri thức có `khu_vuc`, `quoc_gia` (ISO, nhiều nước cách dấu phẩy) và `metadata`: `loaiNguon`
  (bat-buoc → lỗi, tieu-chuan/khuyen-nghi → cảnh báo, thuc-hanh → ghi chú), `kiemTra` (chủ đề), `params` (ngưỡng).
- Thiết kế mang `quocGia`/`khuVuc` (spec, mẫu, hoặc nhận từ mô tả như "chuẩn Úc", "thị trường châu Âu").
  Mẫu tự sinh lấy kích thước (cao mặt bàn, sâu tủ, chân tủ, khoảng tủ trên, độ cao hút mùi) theo tiêu chuẩn ưu tiên của nơi đó.
- Tra cứu: `search_knowledge(query, quoc_gia=..., khu_vuc=..., chi_vung=...)`, web `GET /api/knowledge?quocGia=VN`.
- Kiểm tra theo nước khác: `validate_design(id, quoc_gia="AU")`, web chọn "Tiêu chuẩn" trên thanh tiêu đề.

## Phào cổ điển

- Spec: `phongCach`, `moldings` (phào theo quy tắc: `kieu` crown/base, `profile`, `tuong`, `khoangNoi`, `dauHo`, `bat`, `boQuaTran`)
  và `moldingProfiles` (mặt cắt riêng; preset: `classic-crown-simple|layered|cornice`, `classic-base`, `classic-base-low`).
- Mặt cắt (u, v): u nhô ra phía phòng tính từ mặt trước tủ (âm = lùi vào), v lên từ đường chạy (nóc tủ hoặc sàn).
- Mô tả "cổ điển"/"tân cổ điển" tự thêm phào nóc + phào chân; mẫu tự chừa chỗ phào dưới trần và cho cánh tủ nóc mở ngang.
- Phào nóc vượt trần → lỗi `MOLDING-TRAN-001` kèm nút **Hạ đỉnh tủ** / **Để nguyên** (web) hoặc `hanhDong` → MCP `apply_action`.
- Xuất three.js: `decorations` (Crown_Molding/Base_Molding + `path`), mặt cắt trong `assets[].parameters.profile`; `scene-loader.js` quét bằng `sweepRings` (khớp Python).

## Ảnh điều khiển cho AI

`render_views` (MCP) hoặc nút **Render** trên web ghi vào `renders/<id>/rev<N>/<góc>/`:

| File | Nội dung | Dùng cho |
|---|---|---|
| `lines.png` | nét đen nền trắng: biên chi tiết, khe cánh, cạnh khối | ControlNet lineart/canny/scribble (đảo màu nếu model cần nét trắng) |
| `depth.png` / `depth16.png` | 8-bit gần = sáng / 16-bit theo mm | ControlNet depth |
| `normal.png` | normal hệ camera, RGB = n·0,5+0,5 | ControlNet normal |
| `seg.png` | mask theo loại chi tiết (`legend.json`) | inpaint theo vùng, segmentation control |
| `seg_module.png` | mask theo từng module | đổi vật liệu từng tủ |
| `camera.json` | fx, fy, cx, cy, R, t (OpenCV) | chiếu ngược, ghép nhiều góc |
| `instance.png` + `instances.json` | 16-bit, giá trị = chỉ số chi tiết + 1; bảng tra ID chi tiết, số pixel, bbox | mask chính xác từng chi tiết (sau z-buffer, không khử răng cưa) |
| `albedo.png` | màu vật liệu × đổ bóng đơn giản | ảnh gốc khi chưa có ảnh AI, xem trước |
| `manifest.json` | designId, rev, `renderKey` (băm hình học + camera + kích thước) | biết mask/ảnh cũ còn dùng được không |

Mọi góc render từ cùng một rev nên hình học khớp nhau giữa các ảnh. Render lại cùng một rev cho ra kết quả giống hệt.

## Xuất JSON cuối cùng cho AI tạo ảnh

- Web: khu **Xuất cho AI tạo ảnh** (cột trái). Bật "Tự xuất" thì sau mỗi lần tạo / sửa, bản rev mới nhất được ghi ra
  `renders/<id>/rev<N>/ai/ai-request.json`. **Tải JSON cho AI** tải file đó; **Xuất gói kèm ảnh (.zip)** render ảnh còn thiếu
  và đóng gói JSON + nét/depth/normal/albedo/render three.js của từng góc.
- Ô xem có nút chuyển bản: **Rút gọn** (gửi AI) · **Đầy đủ** (kiểm tra, không gửi AI: job = `request.full.json` gồm toàn bộ yêu cầu nội bộ, kết quả và mọi ảnh của job; thiết kế = `ai-request.json` có cảnh three.js) · **Gemini API** (job, ảnh `inline_data` hiện thành hình).
- **Xem JSON**: mở file JSON cuối cùng ngay trên trang (dạng cây hoặc chữ, ảnh base64 hiện thành hình thu nhỏ, chép / tải về). Request của job: link **Xem JSON** trong chi tiết job.
- **Tải JSON cho AI (kèm ảnh)** tải `ai-request.full.json`: một file tự chứa, mỗi góc nhúng sẵn ảnh nên gửi (`views[].anhNhung`, base64).
- MCP `export_ai_package(design_id, nhung_anh=True)`; HTTP `GET /api/designs/<id>/ai-export?nhungAnh=1`, `POST …/ai-export`.
- **Lọc + giải mã ảnh**: file gửi AI chỉ giữ chỉ dẫn, việc, ảnh đính kèm theo thứ tự (bỏ renderKey, id chi tiết, cảnh three.js…).
  Ảnh base64 chỉ được AI "thấy" khi nằm trong phần `inline_data` của request API: `gemini-request.json` (job) và
  `ai/gemini/<góc>.json` (gen-0) là đúng thân `generateContent`, Gemini tự giải mã. Với Gemini web / chat: đính kèm
  `anh-1-…png`, `anh-2-…png` đúng thứ tự rồi dán chỉ dẫn (`GUI-GEMINI-WEB.txt`, nút **Chép chỉ dẫn**); không dán chuỗi base64 vào chat.
- **Chỉ đúng vùng cần sửa (v0.3.9)** — ba lớp chỉ định cùng lúc để AI không đoán nhầm đối tượng:
  1. *Ảnh 1 có đánh dấu* (`reference_danh_dau.png` → `anh-1-anh-goc-danh-dau.png`): viền màu + số quanh từng vùng
     (việc 1 đỏ, 2 xanh lá…). Viền cách mép vùng 14 px và không bao giờ đè lên vùng sửa nào, nên ghép strict loại bỏ hoàn toàn.
  2. *Vị trí bằng chữ* tính từ mask (`viec[].viTri`, `khungPhanTram`), tên đối tượng (phào nóc / phào chân…) và số vật
     cùng loại khác phải giữ nguyên (`vatCungLoaiGiuNguyen`).
  3. *Mask* (ảnh 2) như cũ.
- **Sửa hình trên ảnh: xóa / thêm / thay vật (v0.4)** — job `kind=hinh` (web: khung "Sửa hình" trong tab Sửa ảnh theo lớp;
  MCP `create_image_job(kind="hinh", hinh=[...])`). Thao tác: `xoa-module` (`donDay` tùy chọn), `them-module`, `kieu-canh`
  (phang/khung/kinh, một module hoặc `*`), `tay-nam` (thanh/num/am/khong), `op` (thao tác thiết kế bất kỳ). Hệ thống áp thao tác
  lên bản sao thiết kế, render lại ĐÚNG camera cũ (góc nhìn mặc định bị dịch thì tự ghim camera cũ, op `goc-nhin`), so
  instance + albedo + nét cũ/mới ra mask vùng thay đổi. Model vẽ lại vùng đó theo nét/depth của thiết kế MỚI (vật đã xóa không
  còn trong ảnh điều khiển). Gemini nhận 3 ảnh: ảnh gốc có viền, mask, hình mẫu thiết kế mới (màu phẳng + nét). Backend
  `to-mau` dán hình mẫu vào vùng đổi để xem nhanh không cần AI. Chấp nhận ảnh = ghi rev mới; ảnh đó thành ảnh gốc của rev mới.
  Đổi kiểu cánh: render nhanh chưa dựng khung, nên mặt trước module được vẽ lại bắt buộc và hình mẫu có nét khung shaker.
- **Yêu cầu ảnh thật (v0.4.1)** — `kitchen/realism.py`, dùng chung cho Gemini (câu văn), ComfyUI (cụm từ khoá) và negative:
  máy ảnh kiến trúc (24–35 mm rectilinear, ngang mắt, f/8, đường đứng thẳng), ánh sáng theo thiết kế (cửa sổ, LED hắt dưới tủ trên),
  bề mặt theo vật liệu (vân gỗ, laminate, sơn mờ/bóng, đá, kim loại xước mịn, kính, gạch), bóng tiếp xúc / AO, khe cánh 2–3 mm,
  cạnh vát bắt sáng, màu và dải sáng tự nhiên, hạt nhiễu mịn. Ảnh đầy đủ chọn ánh sáng `anhSang`: `ban-ngay` (mặc định),
  `nang-chieu`, `toi-am` (web: ô "Ánh sáng" ở Xuất cho AI và tab Sửa ảnh; MCP `anh_sang`). Sửa vùng không đổi ánh sáng mà yêu cầu
  phần mới khớp ảnh gốc (hướng sáng, nhiệt độ màu, độ nét, nhiễu hạt, không lộ đường ghép) và chỉ mô tả bề mặt của vật liệu mới.
- **Bảng thao tác** (`thaoTac`): `doi-vat-lieu`, `thay-vat`, `xoa-vat`, `them-vat` (cho edit/hinh), `doi-phong-cach` (gen0) —
  chọn sẵn workflow ComfyUI + trọng số ControlNet (`cn_strength`, `depth_strength`), params người dùng vẫn ghi đè.
  Job sửa hình tự suy thao tác từ danh sách việc. Danh sách: `GET /api/image-backends` → `thaoTac`.
- **Kiểm tra trước khi gửi**: `request.json` có `kiemTra {ok, loi, canhBao, anh}` (ảnh giải mã được, đúng kích thước, có mask,
  mask màu đủ màu, chỉ dẫn nhắc mọi việc). Gửi qua `gemini` / `goi-job` bị chặn khi chưa đạt. Trên giao diện có nút
  **Kiểm tra một file request…** (`POST /api/check-request`) phát hiện file bị cắt, base64 hỏng, thiếu ảnh, ký tự NBSP do chép qua chat.
- **Job sửa ảnh (một hay nhiều việc)**: mỗi job ghi `request.json` tự chứa (`schema: kitchen-ai-edit-request/1.0`): chỉ dẫn gửi model,
  ảnh gửi theo thứ tự (`anhGui`: ảnh gốc + mask hoặc mask màu, base64), từng việc (`tasks[]`: màu vùng, layer, vật liệu, prompt,
  khung bao, mask riêng base64). Tải: link trong chi tiết job, `GET /api/image-jobs/<job>/request`, MCP `get_image_job` (`requestFile`).
- Nội dung (`schema: kitchen-ai-image-request/1.0`): thiết kế (rev, phong cách, kiểu cánh, tay nắm, phào), vật liệu (tên + tiếng Anh + màu),
  prompt chung, negative, từng góc (camera, kích thước, prompt dạng câu giữ nguyên hình học và kiểu cánh, ảnh đầu vào gợi ý), cảnh three.js đầy đủ.

## Render ảnh trong trình duyệt (không cần API)

- Web: nút **🖼 Render ảnh** (hoặc mở `http://localhost:8080/web/render.html`): chọn thiết kế hoặc mở file JSON three.js,
  chọn góc, bấm **Render** -> ảnh PNG từng camera (vật liệu PBR, đổ bóng, phản xạ môi trường phòng, tone mapping ACES).
- Khi nguồn là thiết kế, ảnh được lưu thành `renders/<id>/rev<N>/<góc>/beauty.png` và dùng làm **ảnh gốc** cho tab sửa ảnh
  (thứ tự: ảnh đã duyệt > render three.js > albedo). Camera trùng ảnh điều khiển nên mask khớp ảnh (điểm `khopNet` ≈ 0,85–0,9).
- Dòng lệnh (cần `pip install playwright` và `python -m playwright install chromium`):
  `python render_browser.py fixtures/bep-chu-L.threejs.json` hoặc `python render_browser.py --design <id> --views goc-anh-goc --size 1920x1440`.
- three.js r180 nằm sẵn trong `web/vendor/three` (giấy phép MIT), web chạy không cần mạng.

## Sửa ảnh theo lớp

Web: tab **Sửa ảnh theo lớp** (bấm lên ảnh để chọn chi tiết, xem mask, tạo job, kéo thanh so sánh trước/sau, duyệt).
MCP: `list_layers`, `create_image_job`, `get_image_job`, `list_image_jobs`, `submit_image_result`, `accept_image_job`,
`reject_image_job`, `regenerate_image_job`.

- **Layer ID = ID chi tiết** của bộ biên dịch (`TD1-canh-1`, `TD1-tay-nam-1`); nhóm `matTruoc:TD1`, `tayNam:TD1`, `module:TD1`, `loai:mat-da`, `loai:tay-nam`.
- **Tay nắm** là chi tiết thật trong hình học (`kitchen/hardware.py`, dùng chung với JSON three.js): có trong nét, depth, mask.
  Đổi vật liệu tay nắm là thao tác thiết kế `chung.tayNam.vatLieu` (áp cho mọi tay nắm); đổi kiểu/chiều dài tay nắm là đổi hình học (sửa thiết kế, không qua sửa ảnh).
- **Một job nhiều việc**: `tasks: [{targetLayer, vatLieu, instruction}, ...]` (tối đa 8). Các việc không được chạm cùng chi tiết.
  `to-mau` tô từng vùng; `gemini` gọi MỘT lần với mask màu (mỗi việc một màu, `mask_mau.png`); `comfyui` chạy nối tiếp từng việc;
  `goi-job` xuất `workflow_api_<i>.json` nối tiếp + `mask_mau.png`, nộp ảnh cuối. Báo cáo có kết quả từng việc (`report.viec`);
  chấp nhận thì mọi thao tác thiết kế ghi thành một rev (op `nhieu`). Web: **＋ Thêm vào danh sách việc**.
  JSON three.js mang `sourceRef` tới đúng ID này ở cánh, ngăn kéo và tấm.
- **Ảnh gốc** = ảnh đã chấp nhận gần nhất cùng (thiết kế, góc nhìn, `renderKey`), chưa có thì `albedo.png`.
  Đổi vật liệu không đổi `renderKey` nên ảnh gốc và mask vẫn dùng được sau khi thiết kế lên rev mới.
- **Chế độ** `thu-nhanh` (chỉ ảnh, đúng layer đã chọn) và `thiet-ke` (cần `vatLieu`; mask = mọi chi tiết đổi vật liệu
  theo thao tác đó, vd cả mặt trước module; thiết kế chỉ đổi khi **chấp nhận**). Job thử nhanh có `vatLieu` vẫn
  "Chấp nhận & áp vào thiết kế" được.
- **Ghép strict**: ngoài mask luôn là pixel ảnh gốc; viền mềm chỉ vào trong mask. `report.json` gồm ngoài mask
  (phải 0 px khác), trong mask có đổi không, biên so với `lines.png`, và độ lệch của ảnh AI thô ngoài vùng sửa (chẩn đoán model).
- **Backend**: `to-mau` (đổi màu giữ sáng tối, không AI, cần màu trong tên vật liệu), `goi-job` (xuất gói gồm ảnh, mask,
  nét đảo, depth, `workflow_api.json` cho ComfyUI và `HUONG-DAN.txt`; nộp ảnh về sau), `comfyui` (HTTP, cấu hình `COMFYUI_*` trong `.env`),
  `gemini` (Gemini API: gen-0 gửi `albedo.png` + chỉ dẫn giữ nguyên hình học; sửa gửi ảnh gốc + mask + chỉ dẫn, rồi ghép strict.
  Khóa: `GEMINI_API_KEY`, hoặc `GEMINI_ENV_FILE` trỏ tới `.env` của mcp-image. Gen-0 có điểm `khopNet` cho biết ảnh AI còn khớp nét bản vẽ không).
- Workflow mẫu trong `workflows/`: `inpaint` (node lõi), `inpaint-lineart` (thêm ControlNet lineart), `gen0-lineart-depth` (ảnh đầu tiên từ nét + depth).
  Tên model lấy từ `COMFYUI_CKPT`, `COMFYUI_CN_LINEART`, `COMFYUI_CN_DEPTH`.
- File job: `renders/<id>/rev<N>/<góc>/jobs/<job>/` (`reference`, `target`, `mask`, `raw`, `composite`, `report.json`, `job.json`).
- **Xem trước khi gửi** (web: ô tick, bật sẵn; HTTP `xemTruoc: true`; MCP `xem_truoc=True`): job chỉ chuẩn bị mask + `request.json`, dừng ở `cho-gui`
  và mở ngay ô Xem JSON; bấm **Gửi <backend>** (`POST /api/image-jobs/<job>/send`, MCP `send_image_job`) hoặc **Hủy**. Nếu thiết kế đổi hình học sau khi tạo job thì không cho gửi.
- Trạng thái: `cho-gui`, `dang-chay`, `cho-ket-qua`, `can-duyet`, `da-chap-nhan`, `tu-choi`, `loi:<mã>`
  (`khong-ho-tro`, `qua-tai`, `het-gio`, `sinh-that-bai`, `khong-dat-kiem-tra`, `bi-ngat`).

## Chưa làm

- Ghép có tính ánh sáng/bóng lân cận, đồng bộ một lần sửa ra nhiều góc nhìn; tay nắm âm (khoét) chưa có hình học.
- Nhận diện từ ảnh -> spec (giai đoạn 4).
- Bếp chữ U chưa có mẫu sinh tự động; tường `trai` đã có trong spec/compiler.
- Đảo bếp chưa có.
