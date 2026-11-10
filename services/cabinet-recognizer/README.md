# cabinet-recognizer 0.2

Ảnh tủ bếp (chụp hoặc render) → JSON gồm từng module với vị trí, kích thước, cánh, ngăn kéo, thiết bị.
Nhận được: dãy thẳng chụp chính diện (nhánh v0.1), dãy thẳng chụp xiên, chữ L, chữ U (nhánh phối cảnh v0.2).

## Nhánh phối cảnh (v0.2): chữ L, chữ U, chữ I chụp xiên

`pipeline.recognize_auto` hỏi AI bố cục trước. Dãy thẳng + chính diện → chạy nhánh v0.1 bên dưới; còn lại:

| # | Bước | Ai làm | File |
|---|---|---|---|
| 1 | Bố cục (straight/l-shape/u-shape), kiểu ảnh, mỗi dãy: tường (back/left/right), vùng ảnh, 2 điểm trên mỗi đường ngang (upperTop, upperSplit, upperBottom, worktopFront, frontsBottom, plinthBottom, tallTop) | **AI** | `prompts.scene_prompt`, `contract_persp.parse_scene` |
| 2 | Bám chính xác từng đường xiên (gradient + khớp đường có loại ngoại lệ); đường ứng viên dọc theo từng tầng trong dải xiên; ảnh đánh số cho từng dãy | code | `pixels_persp` |
| 3 | Mỗi dãy: ranh giới module theo tầng (base, upper, upper-top; tủ cao là module tầng base loại tall-*), loại module, các đoạn trong tủ cao, **vật chuẩn** bề rộng (máy rửa bát 600, lò 600, tủ lạnh side-by-side ~910) và chiều cao | **AI** | `prompts.run_prompt`, `contract_persp.parse_run` |
| 4 | Chuẩn kích thước theo vùng: độ lùi chân tủ, chiều sâu, độ dày đá, bước làm tròn, giá trị chuẩn | **AI** (chỉ văn bản, nhận số đo sơ bộ) | `prompts.policy_p_prompt` |
| 5 | Hình học: điểm tụ dọc tường sau và tường bên (bỏ dần đường lệch), tiêu cự từ 2 điểm tụ; nếu ảnh chính diện chữ U (điểm tụ tường sau ở vô cực) thì dò tiêu cự cho các vật chuẩn ở các tường khác nhau cho cùng tỉ lệ; mặt trước mỗi dãy từ đường chân tủ chạm sàn; tỉ lệ mm từ vật chuẩn; hệ số đứng từ vật chuẩn chiều cao; vị trí dọc tường tính từ góc trong; module góc kéo về góc (`blindWidth`, `blindSide`); kệ góc mở (`legBack`, `legSide`); dãy bên không bắt đầu trước mặt trước dãy sau | code | `persp`, `compute_persp` |

Đầu ra `schema: cabinet-recognizer/0.2`: `walls` (chiều dài mỗi dãy, đầu dãy, chiều cao đo được ở từng dãy), `common`, `modules[]` có thêm `wall`, `storey` (`base`/`upper`/`upper-top`/`tall`), `sections` cho tủ cao; `evidence.camera` (điểm tụ, tiêu cự, nguồn tiêu cự), `cameraHeightMm`, `verticalCorrection`, `scaleRefs`; `warnings` (ví dụ `back-vp-treated-infinite`, `scale-references-disagree`, `height-differs-between-walls`, `side-start-clamped`).

### Kiểm tra độ chính xác

- Ảnh chữ L thật (`tests/data/bep-chu-L-trang.png`): điểm tụ (-2656, 433) / (929, 432), tiêu cự 1018 px; khớp bản đo tay trong ~3% (dãy sau 4850 so với 4956).
- Ảnh chữ U dựng bằng three.js (`tests/data/u-frontal-render.png`, camera cao 1450, góc dọc 55°): tiêu cự tìm được 849 px (đúng 864), camera 1511 (đúng 1450); mép module lệch tối đa ~100 mm trên dãy 3600 (≈3%); chiều cao lệch 2–4%.

### Xem 3D

`tools/threejs/kitchen3d.js` dựng cảnh three.js từ JSON (cả tường trái/phải); `node tools/threejs/export.mjs spec.json scene.json` xuất file cho `THREE.ObjectLoader`.

---

# Nhánh chính diện (v0.1)

Ảnh tủ bếp chụp/render chính diện → JSON gồm từng module (tủ trên, tủ dưới) với vị trí, kích thước, cánh, ngăn kéo, thiết bị.

## Quy trình

| # | Bước | Ai làm | File |
|---|---|---|---|
| 1 | Tìm dãy tủ trên / dưới (hộp gần đúng), đầu dãy, vật liệu | **AI** | `prompts.layout_prompt` |
| 2 | Gradient ảnh → đường ứng viên dọc (U\*, B\*) và ngang (H\*); vẽ ảnh đánh số | code | `pixels.measure`, `pixels.annotate` |
| 3 | Chọn đường nào là ranh giới module, khe cánh, đỉnh/đáy tủ, mặt đá, chân, sàn; gọi tên từng ô; bỏ đường nhiễu | **AI** (xem ảnh gốc + ảnh đánh số) | `prompts.segmentation_prompt` |
| 4 | Tìm đường đáy cánh tủ hút mùi, đường chia ngăn kéo trong ô | code | `pixels.refine_cells` |
| 5 | Chọn giả định kích thước theo vùng: chiều cao mặt bếp tham chiếu, chân tủ, độ dày đá, bước làm tròn, dung sai căn đường, các giá trị chuẩn khoảng hở và chiều cao tủ trên | **AI** (chỉ văn bản, nhận số đo px) | `prompts.policy_prompt` |
| 6 | px → mm, hệ số tủ trên (từ hai dãy cùng đầu mút), căn đường chia, làm tròn, snap chuẩn, cảnh báo | code | `compute.build_spec` |

AI chỉ đưa ra phán đoán; mọi phép tính do code làm nên chạy lại cho cùng kết quả. Câu trả lời AI sai hợp đồng (id đường không có, số module lệch, loại không có trong danh sách...) bị bắt ở `contract.py` và hỏi lại 1 lần kèm lý do.

## Chạy

```bash
pip install -e .
# Claude
set RECOG_PROVIDER=anthropic & set ANTHROPIC_API_KEY=...        (Windows; Linux dùng export)
# hoặc model kiểu OpenAI, ví dụ Gemini qua endpoint OpenAI-compatible
set RECOG_PROVIDER=openai & set RECOG_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai & set RECOG_MODEL=gemini-2.5-pro & set RECOG_API_KEY=...

cabinet-recognize anh.png -o tu.json --debug-dir out/        # tự chọn nhánh; out/ có ảnh đánh số, measure.json, answers.json
cabinet-recognize anh.png --frontal-only                     # ép dùng nhánh v0.1
cabinet-recognize anh.png --replay out/answers.json          # chạy lại không gọi API
python -m cabinet_recognizer.http_server --port 8765         # POST /recognize (body là ảnh, hoặc JSON {"imageBase64", "region"})
```

Biến môi trường khác: `RECOG_MODEL`, `RECOG_REGION` (mặc định `VN`), `RECOG_TIMEOUT_S`, `RECOG_MAX_RETRIES`.

## Chạy thử khi chưa có API key

**Chế độ hộp thư** (`--inbox`): không gọi API. Mỗi bước cần AI, service ghi `inbox/pending/<bước>/prompt.txt` và các ảnh `image-*.png` rồi dừng (mã thoát 3). Người hoặc một AI qua giao diện chat (Claude, Gemini...) đọc câu hỏi, ghi JSON trả lời vào `inbox/answers/<bước>.json`, chạy lại đúng lệnh cũ là đi tiếp bước sau. Các bước: `scene`, `run-back`, `run-left`/`run-right`, `policy` (nhánh chính diện: `layout`, `segmentation`, `policy`). Xong thì `inbox/answers/` dùng lại được với `--replay`... (gộp các file thành một JSON `{bước: câu trả lời}`).

```bash
cabinet-recognize anh.png --inbox inbox -o tu.json --debug-dir out/
```

**Trang web hộp thư**: `python -m cabinet_recognizer.web_inbox --port 8770` rồi mở http://127.0.0.1:8770. Chọn ảnh, ghi chú (được gắn vào mọi câu hỏi gửi AI), bấm Gửi → job `jobs/<mã>/` dừng ở bước cần AI. Người/AI trả lời vào `jobs/<mã>/inbox/answers/<bước>.json` rồi chạy `python -m cabinet_recognizer.web_inbox --resume <mã>` để sang bước sau (ảnh đánh số ở `jobs/<mã>/debug/`). Xong hết thì bấm **Nhận kết quả** để tải `result.json`; nút **Xem 3D** mở trang three.js (`/jobs/<mã>/view`, dựng bằng `tools/threejs/kitchen3d.js`, three.js tải từ cdn.jsdelivr.net nên máy cần có mạng).

**Model chạy trên máy (Ollama, không cần khóa)**: `RECOG_PROVIDER=ollama`, `RECOG_MODEL=qwen2.5vl:7b` (mặc định `RECOG_BASE_URL=http://localhost:11434/v1`). Model nhỏ thường chọn đường kém hơn model lớn, nên kiểm tra ảnh đánh số trong `--debug-dir`.


## Tương thích với kitchen service (KitchenSpec của mcp-imagev2)

> **Đường cũ.** Từ 10/11/2026 kitchen service chỉ đọc `runs` (`recognized-runs/1`, mục bên dưới): bản nháp để người dùng duyệt và hệ tủ được đặt đều lấy từ đó. Trường `kitchen` (KitchenSpec kiểu tường, `to_kitchen.py`) vẫn được trả về cho trang Xem 3D và để đối chiếu, nhưng không còn ai trong kitchen dùng; phần mô tả dưới đây giữ lại để tra cứu.

JSON của recognizer **không** nạp thẳng vào kitchen service được: `load_spec` vẫn chạy (spec cho phép trường lạ) nhưng ra bếp **không có module nào**, vì recognizer dùng `modules` còn KitchenSpec dùng `module`. Luôn đi qua bộ chuyển `cabinet_recognizer.to_kitchen.to_kitchen_spec(result)` → `{"spec": KitchenSpec, "issues": [...]}`.

| Recognizer 0.2 | KitchenSpec 2 | Ghi chú |
|---|---|---|
| `modules[]` | `module[]` | |
| `x` (dãy sau: từ góc **trái** sang phải) | `fromCorner` (dãy sau: từ góc **phải** sang trái) | `fromCorner = dài tường sau − x − rộng`; dãy trái/phải giữ nguyên (đo từ tường sau) |
| `doors` dãy sau | `doors` đảo thứ tự | vì chiều đo ngược |
| `blindWidth` + `blindSide` | `blindCorner` (chỉ phía fromCorner) | góc sau–phải giữ ở module dãy sau; góc sau–trái chuyển sang module đầu dãy trái |
| `upper-corner-open-shelf` | `corner-shelf` (chỉ góc sau–phải) | ở góc sau–trái tách thành 2 module `upper-open` |
| `drawers` | `frontSections` `drawer` | |
| `base-oven` | `base-oven` + `frontSections` hốc 450 + 2 ngăn kéo | chiều cao lò là giả định |
| `base-dishwasher` | `base` + `frontSections` hốc cả chiều cao | thiết bị `other` |
| `base-hob` / `base-drawer` / `upper-top` / `upper-open-shelf` | `base-cooktop` / `base-drawers` / `upper-loft` / `upper-open` | |
| `upper-dish-rack`, `upper-lift-up`, `tall-display`, `tall-oven` | `upper`, `upper`, `tall`, `tall` | mất thông tin kiểu cánh nâng/giá bát; ghi vào `note` và `issues` |
| tủ cao `sections` | `niche` (hốc tủ lạnh) + `doors` một nhóm cánh, `doorStyle: glass` | các đoạn khác (lò vi sóng, ngăn kéo, khe mở) bị bỏ, có trong `issues` |
| `common.worktopTop/worktopThickness/upperSplit/upperTop` | `countertop/countertopThickness/upperTierSplit/cabinetTop`, `baseTop = countertop − thickness` | `ceiling` = max(2640, cabinetTop + 30) |
| `common.materials` (fronts, worktop, backsplash, accent) | `common.material` (base, upper, tall, countertop, wallTile, carcass) | |
| `walls.*.runLength` | `room.wall[{id, length}]` | |
| `appliances[].kind` | `appliances[].type` (hob→cooktop, microwave→oven, led→light, dishwasher→other) | |
| `evidence.region` | `country` | `evidence`, `warnings` không chuyển |

Kiểm tra bằng chính code kitchen service (chạy từ thư mục gốc mcp-imagev2, cần pydantic):
```
python services/cabinet-recognizer/tools/check_kitchen_compat.py ket-qua.json --out kitchen-spec.json
```
Nó chạy `load_spec` → `compile_spec` → `threejs_export.export` → `rules.validate`. File `--out` nạp được vào kitchen service bằng thao tác `{"op": "replace", "spec": ...}` (qua `propose` trước).

## Đầu ra theo dãy: `recognized-runs/1` (dùng cho kitchen service)

Ngoài `spec` (toạ độ theo tường) và `kitchen` (KitchenSpec kiểu tường, đường cũ), mọi câu trả lời (`/recognize`, `/jobs/<id>`, web hộp thư: `runs.json`) có thêm `runs` — hệ tủ **theo dãy**, là hợp đồng chính với kitchen service:

```json
{"schema": "recognized-runs/1", "unit": "mm", "layout": "L",
 "runs": [{"id": "left", "length": 2130, "end": 2130, "modules": [{"id": "TD1", "type": "base", "storey": "base", "s": 0, "width": 600, "y": 0, "height": 840, "depth": 600, "doors": [300, 300], "confidence": 0.8}]},
          {"id": "back", "length": 3600, "modules": []}],
 "joints": [{"a": "left", "b": "back", "angle": 90}], "common": {}, "issues": []}
```

- Thứ tự dãy: `left`, `back`, `right`. `s` đo dọc dãy **từ đầu bên trái của người đứng nhìn vào cánh tủ**; không còn khái niệm tường hay góc gốc.
- `joints[{a, b}]`: **cuối** dãy `a` gặp **đầu** dãy `b` ở góc trong 90°.
- Mỗi module mang đủ `doors`, `frontSections`, `blindCorner`, `niche`, `doorStyle`, `shelfCount`, `appliances`.
- Ô góc mù luôn nằm ở **đầu** một dãy (phía `s` nhỏ); ô góc mù nhận ra ở cuối dãy được chuyển sang tủ đầu của dãy kề, không chuyển được thì ghi `corner-gap` trong `issues`.
- Code: `cabinet_recognizer/to_runs.py` (`to_runs`, `check_runs`), thuần lõi. Test: `tests/test_to_runs.py`; ba tài liệu mẫu dùng chung với kitchen ở `tests/data/recognized_runs/` (gốc repo) — service phải sinh ra đúng chúng, kitchen phải đọc được chúng.

## Ca thử từ job thật

`python tools/jobs_to_cases.py` gom các job hộp thư đã trả lời xong thành ca phát lại (`tests/data/jobs/<id>.png` + `.answers.json`, kết quả chuẩn `tests/golden/jobs/<id>.spec.json`); `tests/test_job_cases.py` chạy lại không cần model.

## Đầu ra

`schema: cabinet-recognizer/0.1`, đơn vị mm, x từ đầu trái dãy, y từ sàn. `common` (dài dãy, chân, mặt đá, đáy/đỉnh tủ trên, chiều sâu, vật liệu), `modules[]` (`id` TT\*/TD\*, `type`, `storey`, `x`, `width`, `y`, `height`, `depth`, `doors[]`, `drawers[]`, `applianceBelowHeight`, `confidence`), `appliances[]`, `evidence` (mm/px, số đo trước khi làm tròn, toạ độ px đã chọn, lý do AI chọn chuẩn) và `warnings[]` (ví dụ `upper-aligned-to-base`, `gap-not-standard`, `hood-line-missing`).

## Vùng code (theo CODING_STANDARDS R1–R23 của mcp-imagev2)

- **Lõi thuần** (stdlib, JSON vào – JSON ra, lỗi có kiểu, làm tròn `round_half_away`): `errors numeric contract compute prompts labels_vi`. Có test AST chặn import ngoài stdlib và `round()` trần.
- **Điểm ảnh** (numpy/PIL): `pixels`.
- **Vỏ**: `config` (đọc env một lần), `vision` (cổng `VisionClient`: Anthropic, OpenAI-compatible, Replay), `pipeline`, `cli`, `http_server`.

## Giới hạn hiện tại

- Nhánh v0.1 chỉ cho dãy thẳng chính diện; ảnh khác đi nhánh phối cảnh.
- Nhánh phối cảnh giả định camera đặt ngang (cạnh đứng của tủ thẳng đứng trên ảnh), điểm chính ở tâm ảnh; chưa có đảo bếp, bán đảo, tủ góc chéo; cần ít nhất một vật chuẩn bề rộng (không có thì lấy chiều cao mặt bếp chuẩn, kém chính xác hơn); ảnh chữ U chính diện cần vật chuẩn ở hai tường khác nhau để giải tiêu cự.
- Chia ngăn kéo trong nhánh phối cảnh đang chia đều; chiều cao máy hút mùi chưa đo.
- Không có vật chuẩn trong ảnh nên kích thước tuyệt đối dựa vào chiều cao mặt bếp AI chọn theo vùng: sai số khoảng ±5–10%.
- Ranh giới module phải trùng một đường ứng viên; mép mờ có thể lệch vài px (ảnh mẫu: mép trái tủ giá bát lấy ở x=80 thay vì 77), phần căn với tủ dưới sẽ bù lại.

## Test

`python -m unittest discover -s tests` (23 test) — chạy toàn bộ quy trình trên 3 ảnh mẫu bằng câu trả lời AI đã ghi (`tests/data/*.answers.json`) và so với `tests/golden/bep-chu-I-xam.spec.json`; thêm ca hỏi lại, ca bỏ cuộc, hợp đồng, số học, kiến trúc.

## Cắm vào mcp-imagev2 (HTTP)

mcp-imagev2 gọi dịch vụ này qua `kitchen/recognizers.py` (`CabinetRecognizerHttp`); khóa API chỉ nằm trong tiến trình này (`RECOG_*`).

1. Chạy dịch vụ: `python -m cabinet_recognizer.http_server --port 8765` (nạp `RECOG_*` vào môi trường trước).
2. Ở mcp-imagev2 đặt `CABINET_RECOGNIZER_URL=http://127.0.0.1:8765` (tùy chọn `CABINET_RECOGNIZER_TIMEOUT`, `KITCHEN_RECOGNIZER=cabinet|gemini|inbox`).

**Hộp thư qua chat (không cần API key)**: service có `POST /jobs` (cùng body `/recognize`, tạo `jobs/<mã>/`, chạy tới bước cần AI rồi dừng → 202 `waiting`) và `POST /jobs/<mã>/resume` (hoặc `GET /jobs/<mã>`; khi `done` trả thêm `kitchen` như `/recognize`). Ở mcp-imagev2 hộp thư là mặc định (không đặt `KITCHEN_RECOGNIZER`; đặt `cabinet` để dùng model API): ảnh + prompt ở menu chuột phải → "Xem trước" tạo job và hiện mã; người dùng nhắn Claude "trả lời hộp thư job <mã>"; Claude đọc `jobs/<mã>/inbox/pending/<bước>/prompt.txt` + `image-*.png`, ghi JSON vào `inbox/answers/<bước>.json`, gọi `POST /jobs/<mã>/resume` (hoặc nút Nhận kết quả) cho tới khi `done`, rồi báo người dùng bấm **Cập nhật** (menu gọi `POST /api/designs/<id>/recognize-job`) để xem trước/áp dụng tủ nhận diện được.
3. `POST /recognize` nhận `{"imageBase64", "kind"?, "region"?, "note"?}`; `note` (≤ 500 ký tự) chỉ đi vào câu hỏi `scene` và `policy`, bọc trong `<user_note>` và được dặn là dữ liệu, không phải chỉ thị. Trả `{"spec", "kitchen": {"spec": KitchenSpec, "issues": [...]}}`.
4. mcp-imagev2 chỉ lấy DANH SÁCH MODULE từ `kitchen.spec` (loại, tường, bề rộng, vị trí, cao, sâu), đưa qua `build_draft` rồi dựng một thao tác `replace` giữ phòng, mặt bằng và thiết lập chung của thiết kế hiện tại. Cánh, ngăn kéo, hốc, thiết bị và id do bộ nhận diện đặt không được mang sang (`draft_operation` dựng lại).
