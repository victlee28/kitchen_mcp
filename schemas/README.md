# Complete Kitchen Three.js Scene Schema

| File | Nội dung |
|---|---|
| `kitchen-threejs.v1.0.0.schema.json` | Schema gốc của bạn, giữ nguyên |
| `kitchen-threejs.schema.json` | Bản mở rộng v1.1.0, sinh bằng `python schemas/build_schema.py` |
| `../fixtures/bep-chu-L.threejs.json` | Ví dụ xuất từ bếp chữ L, hợp lệ cả hai bản |

Xuất: MCP `export_threejs(design_id)`, web `GET /api/designs/<id>/threejs?quocGia=VN` (nút **Tải JSON three.js**).
Dựng trong three.js: `web/scene-loader.js` → `buildKitchen(doc, THREE, { RectAreaLightUniformsLib })`.

## Quy ước bắt buộc (schema gốc chưa nói rõ)

- `positionAnchor = bottom_back_left`: `transform.position` là góc dưới – sau – trái **nhìn từ phía trước** vật thể.
- Hệ cục bộ module: x dọc bề rộng (trái → phải), y lên, z từ tấm hậu ra mặt cánh. `parts`, `doors`, `drawers`
  tính theo hệ module; `hardware` (tay nắm) tính theo hệ của cánh/ngăn kéo.
- Tường sau `rotationY = 0` (mặt tủ nhìn +Z), tường phải `-90` (nhìn −X), tường trái `+90` — ghi trong `coordinateSystem.wallFrames`.
- Camera dùng cùng đơn vị với tài liệu (mm); `fov` là góc dọc như `PerspectiveCamera` của three.js.

## Trường bổ sung ở v1.1 (đều tùy chọn, nên file vẫn hợp lệ với v1.0.0)

| Chỗ | Trường | Vì sao cần |
|---|---|---|
| `metadata` | `region` (countryCode, regionCode, appliedRules), `source`, `tags` | Tiêu chuẩn theo quốc gia; truy ngược về KitchenSpec + rev |
| `coordinateSystem` | `metersPerUnit`, `wallFrames`, `notes` | Đặt module theo tường + khoảng cách; nói rõ quy ước |
| `room.walls[]` | `interiorNormal`, `openings` (cửa sổ/cửa đi) | Dựng độ dày tường đúng phía; cửa sổ cho ảnh và quy tắc an toàn |
| `room.ceiling` | `render` | Tắt trần để camera nhìn từ trên |
| `lighting[]` | `groundColor`, `width`, `height`, `angle`, `penumbra`, `parentId` | Tham số constructor three.js của HemisphereLight / RectAreaLight / SpotLight mà bản gốc thiếu |
| `materials[]` | `textureRepeat` (vec2), `textureRotation`, `side`, `emissive*`, `semanticClass`, `sourceKnowledgeCode` | `repeat` gốc là vec3 trong khi texture 2D; kính cần `DoubleSide` |
| `modules[]` | `sourceRef`, `tier`, `frontMaterialId`, `frontStyle`, `blindCorner`, `endPanel`, `niches`, `led`, `placement.offset/elevation` | Liên kết tủ trong spec; tủ góc khuất, tấm hông, hộc thiết bị |
| `modules[].construction` | `edgeBanding`, `grainDirection`, `hingeCountPerDoor` | Chi tiết sản xuất |
| `modules[].doors[]` | `glass`, `openingAngle`, `frontStyle`, `hinges[]` | Cánh kính; minh họa cánh mở |
| `$defs.part` | `customRole` (end_panel, filler, niche_back, niche_board, blind_panel), `semanticClass`, `edgeBanding` | Vai trò ngoài enum gốc mà không phá enum |
| `appliances[]` | `sourceRef`, `parentModuleId`, `energy`, `clearances` | Gắn thiết bị vào tủ; gas/điện/từ ảnh hưởng quy tắc |
| `accessories[]` | `edgeProfile`, `overhang`, `cutouts[]` (ước lượng, `estimated: true`), `sourceRef` | Mặt đá có lỗ khoét chậu/bếp |
| `cameras[]` | `up`, `aspect`, `fovAxis`, `orthoHeight` | Góc nhìn thẳng từ trên xuống cần `up` khác +Y |
| `constraints` | `minimumCountertopToWallCabinet`, `minimumHoodClearance`, `sources` | Lấy từ tiêu chuẩn của quốc gia đã chọn |
| `decorations[]` | `path` (polyline, miter), `sourceRef`, `semanticClass`, `modules` | Phào quét theo đường chạy; mặt cắt ở `assets[assetId].parameters.profile` (category cornice/molding, geometryType extrusion) |
| `renderSettings` | `pixelRatio`, `environment`, `controlPasses` (thêm `instance`, `albedo`), `segmentationPalette` | Ảnh điều khiển (nét, depth, normal, mask) cho AI, màu mask cố định |
| `modules[].doors[]`, `drawers[]`, `$defs.part`, `…hardware` | `sourceRef` | ID chi tiết của bộ biên dịch = layer ID sửa ảnh (vd `TD1-canh-1`) |

## Điểm cần lưu ý trong schema gốc

1. `hingeSide: "Double"` mơ hồ khi `doors` đã là mảng: bộ xuất luôn sinh **một cánh mỗi phần tử** (Left/Right/Top/Bottom).
2. Gốc khóa `additionalProperties: false` ở cấp root, nên mọi phần bổ sung được đặt trong object con.
3. JSON Schema không kiểm được tham chiếu (`materialId`, `assetId`, `parentId` phải tồn tại) — dùng `kitchen.threejs_export.integrity(doc)`.
4. `assets[].modelUrl` để trống: chưa có model GLTF; mọi chi tiết là hộp/tấm (`geometryType` box/panel/procedural).
5. `$id` vẫn là `example.com` — đổi khi bạn có domain thật.
6. Dữ liệu sinh ảnh (mask, renderKey, job) **không** nằm trong JSON three.js: gốc v1.0 khóa `additionalProperties`,
   và mask phụ thuộc từng lần render. Xem `renders/.../manifest.json`, `GET /api/designs/<id>/layers`, bảng `image_jobs`.
