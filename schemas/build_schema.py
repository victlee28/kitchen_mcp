"""Sinh schema mở rộng v1.4.0 (gồm các bổ sung v1.1) từ schema gốc v1.0.0 của người dùng.

Nguyên tắc: KHÔNG đổi/bớt gì của bản gốc; chỉ thêm thuộc tính TÙY CHỌN vào $defs và các object con
(những chỗ bản gốc không khóa additionalProperties). Nhờ vậy mọi file xuất ra hợp lệ với CẢ HAI bản.
Giá trị ngoài enum gốc (vd vai trò "end_panel") đi qua trường custom* thay vì sửa enum.

    python schemas/build_schema.py
"""
import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADD = "Bổ sung v1.1 (VicKitchenCabinet)"
ADD2 = "Bổ sung v1.2 (VicKitchenCabinet)"


def opt(schema: dict, desc: str) -> dict:
    return {**schema, "description": f"[{ADD}] {desc}"}


def main():
    base = json.loads((HERE / "kitchen-threejs.v1.0.0.schema.json").read_text(encoding="utf-8"))
    s = copy.deepcopy(base)
    s["$id"] = "https://example.com/schemas/kitchen-threejs-full.v1.4.0.schema.json"
    s["title"] = base["title"] + " (v1.4)"
    s["description"] = base["description"] + " v1.1 thêm trường tùy chọn cho tủ tham số, vùng tiêu chuẩn và ảnh điều khiển AI; v1.2 thêm phong cách phụ, gợi ý ảnh AI và bảng diễn giải mô tả; v1.3 thêm nguồn độ dày tường và thông tin mặt bằng nhập vào; v1.4 thêm partRef (chi tiết nào bị chọn: cánh, ngăn kéo, tay nắm, mặt bàn); tương thích ngược v1.0.0."
    P, D = s["properties"], s["$defs"]
    P["schemaVersion"]["default"] = "1.4.0"

    D["vec2"] = {"type": "object", "required": ["u", "v"], "properties": {"u": {"type": "number"}, "v": {"type": "number"}},
                 "description": f"[{ADD}] Véc-tơ 2D cho lặp texture"}
    D["region"] = {"type": "object", "description": f"[{ADD}] Nơi lắp đặt, quyết định tiêu chuẩn ưu tiên",
                   "properties": {"countryCode": {"type": ["string", "null"], "pattern": "^[A-Z]{2}$"},
                                  "regionCode": {"type": ["string", "null"], "enum": ["GLOBAL", "SEA", "EA", "NA", "EU", "OC", None]},
                                  "appliedRules": {"type": "object", "additionalProperties": {"type": "string"},
                                                   "description": "chủ đề -> mã quy tắc đã áp"}}}

    # metadata
    m = P["metadata"]["properties"]
    m["region"] = {"$ref": "#/$defs/region"}
    m["source"] = opt({"type": "object", "properties": {"generator": {"type": "string"}, "specSchemaVersion": {"type": "integer"},
                                                        "specRevision": {"type": "integer"}}}, "Nguồn sinh file (KitchenSpec + rev)")
    m["tags"] = opt({"type": "array", "items": {"type": "string"}}, "Nhãn tự do")
    m["styleTags"] = {"type": "array", "items": {"type": "string"},
                      "description": f"[{ADD2}] Phong cách không có hình học riêng (Scandinavian, Japandi, Farmhouse, Country, Mid-Century Modern, Luxury); `style` giữ phong cách hình học gần nhất"}
    m["aiHints"] = {"type": "array", "items": {"type": "string"}, "description": f"[{ADD2}] Cụm tiếng Anh chỉ dùng cho prompt ảnh AI (kính sọc, gạch xương cá…)"}
    m["renderPreferences"] = {"type": "array", "items": {"type": "string"}, "description": f"[{ADD2}] Cụm tiếng Anh về góc máy, ánh sáng, chất lượng ảnh từ mô tả (chỉ cho ảnh AI)"}
    m["promptInterpretation"] = {"type": "array", "description": f"[{ADD2}] Cách hiểu từng thuật ngữ trong mô tả tạo thiết kế",
                                 "items": {"type": "object", "required": ["term", "status"],
                                           "properties": {"term": {"type": "string"}, "id": {"type": "string"}, "kind": {"type": "string"},
                                                          "canonical": {"type": "string"}, "scope": {"type": "array", "items": {"type": "string"}},
                                                          "target": {"type": "string"},
                                                          "status": {"type": "string", "enum": ["built", "exported", "ai-only", "unsupported", "ambiguous"]},
                                                          "message": {"type": "string"}}}}

    # hệ toạ độ: khung từng tường để đặt module theo tường + khoảng cách
    c = P["coordinateSystem"]["properties"]
    c["metersPerUnit"] = opt({"type": "number", "exclusiveMinimum": 0}, "Hệ số đổi sang mét (mm = 0.001)")
    c["wallFrames"] = opt({"type": "array", "items": {"type": "object", "required": ["wallId", "origin", "alongAxis", "frontAxis", "rotationY"],
                                                       "properties": {"wallId": {"$ref": "#/$defs/id"}, "origin": {"$ref": "#/$defs/vec3"},
                                                                      "alongAxis": {"$ref": "#/$defs/vec3"}, "frontAxis": {"$ref": "#/$defs/vec3"},
                                                                      "rotationY": {"type": "number", "description": "độ, áp cho module đặt trên tường này"}}}},
                          "Khung toạ độ của từng tường: trục dọc tường, hướng mặt tủ, góc xoay Y của module")
    c["notes"] = opt({"type": "string"}, "Mô tả quy ước toạ độ bằng lời")

    # tường: lỗ mở, mặt trong
    w = P["room"]["properties"]["walls"]["items"]["properties"]
    w["interiorNormal"] = opt({"$ref": "#/$defs/vec3"}, "Pháp tuyến hướng vào phòng (để dựng độ dày tường ra phía ngoài)")
    w["openings"] = opt({"type": "array", "items": {"type": "object", "required": ["id", "type", "offset", "width", "height"],
                                                     "properties": {"id": {"$ref": "#/$defs/id"},
                                                                    "type": {"type": "string", "enum": ["window", "door", "pass_through"]},
                                                                    "offset": {"type": "number", "description": "từ start dọc tường"},
                                                                    "width": {"type": "number"}, "height": {"type": "number"},
                                                                    "sillHeight": {"type": "number", "default": 0}}}},
                        "Cửa sổ / cửa đi trên tường (cần cho quy tắc không đặt bếp dưới cửa sổ, và cho ảnh)")
    w["visible"] = {"type": "boolean", "default": True, "description": "[Bổ sung v1.3 (VicKitchenCabinet)] false = chỉ là dữ liệu (neo tủ, lỗ cửa), không dựng khối; tường thật của mặt bằng nằm trong room.structures"}
    w["thicknessSource"] = {"type": "string", "enum": ["measured", "assumed"],
                            "description": "[Bổ sung v1.3 (VicKitchenCabinet)] Độ dày đo từ mặt bằng (measured) hay giả định (assumed)"}
    m["floorplan"] = {"type": "object", "description": "[Bổ sung v1.3 (VicKitchenCabinet)] Mặt bằng đã nhập: mã băm nguồn, phòng, cảnh báo và việc gắn bếp vào tường",
                      "properties": {"ref": {"type": "string"}, "roomId": {"type": "string"}, "roomLabel": {"type": ["string", "null"]},
                                     "warnings": {"type": "array", "items": {"type": ["string", "object"]}},
                                     "binding": {"type": "object", "properties": {"back": {"type": "integer"}, "right": {"type": ["integer", "null"]},
                                                                                  "left": {"type": ["integer", "null"]}, "offset": {"type": "number"},
                                                                                  "source": {"type": "string", "enum": ["auto", "manual"]},
                                                                                  "score": {"type": "number"}, "warnings": {"type": "array", "items": {"type": "string"}}}}}}
    xz = {"type": "object", "required": ["x", "z"], "properties": {"x": {"type": "number"}, "z": {"type": "number"}}}
    P["room"]["properties"]["structures"] = {
        "type": "array", "description": "[Bổ sung v1.3 (VicKitchenCabinet)] Mọi phần tử của mặt bằng nhập vào (cột, thang, tủ, cửa, tường không thuộc biên phòng...) dưới dạng khối đùn từ đường viền XZ, toạ độ phòng (mm)",
        "items": {"type": "object", "required": ["id", "kind", "outline", "height"],
                  "properties": {"id": {"$ref": "#/$defs/id"}, "sourceElement": {"type": "string"},
                                 "kind": {"type": "string", "enum": ["wall", "column", "opening", "furniture", "shaft", "stair", "area"]},
                                 "tag": {"type": "string"}, "label": {"type": "string"}, "outline": {"type": "array", "minItems": 3, "items": xz},
                                 "base": {"type": "number"}, "height": {"type": "number", "description": "0 = mảng phẳng"},
                                 "heightSource": {"type": "string", "enum": ["measured", "assumed"]},
                                 "color": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                                 "membership": {"type": "string", "enum": ["inside", "overlapping", "adjacent", "outside", "unknown"]},
                                 "swing": {"type": "array", "items": {"$ref": "#/$defs/vec3"}, "description": "Cung mở cửa"},
                                 "hinge": {"$ref": "#/$defs/vec3"},
                                 "arrow": {"type": "array", "items": {"$ref": "#/$defs/vec3"}, "description": "Cầu thang: từ chân lên đỉnh"},
                                 "steps": {"type": "integer", "description": "Số bậc cầu thang (độ cao đo tổng = height)"}}}}
    P["room"]["properties"]["floor"]["properties"]["outline"] = opt(
        {"type": "array", "minItems": 3, "items": {"type": "object", "required": ["x", "z"],
                                                       "properties": {"x": {"type": "number"}, "z": {"type": "number"}}}},
        "Floor polygon outline in XZ coordinates (mm)")
    P["room"]["properties"]["ceiling"]["properties"]["render"] = opt({"type": "boolean", "default": False},
                                                                      "Có dựng trần không (tắt để camera nhìn từ trên)")

    # đèn: các tham số constructor three.js còn thiếu
    li = P["lighting"]["items"]["properties"]
    li["groundColor"] = opt({"type": "string", "pattern": "^#([0-9a-fA-F]{6})$"}, "HemisphereLight: màu phía đất")
    li["width"] = opt({"type": "number", "exclusiveMinimum": 0}, "RectAreaLight: bề rộng")
    li["height"] = opt({"type": "number", "exclusiveMinimum": 0}, "RectAreaLight: chiều cao")
    li["angle"] = opt({"type": "number"}, "SpotLight: góc (độ)")
    li["penumbra"] = opt({"type": "number", "minimum": 0, "maximum": 1}, "SpotLight")
    li["parentId"] = opt({"$ref": "#/$defs/id"}, "Gắn vào module (vd LED dưới tủ trên)")

    # vật liệu
    mt = D["material"]["properties"]
    mt["textureRepeat"] = opt({"$ref": "#/$defs/vec2"}, "Lặp texture 2D (repeat gốc là vec3, giữ để tương thích)")
    mt["textureRotation"] = opt({"type": "number"}, "Xoay texture (độ), vd hướng vân gỗ")
    mt["side"] = opt({"type": "string", "enum": ["FrontSide", "BackSide", "DoubleSide"], "default": "FrontSide"}, "Mặt hiển thị")
    mt["emissive"] = opt({"type": "string", "pattern": "^#([0-9a-fA-F]{6})$"}, "Màu phát sáng")
    mt["emissiveIntensity"] = opt({"type": "number", "minimum": 0}, "")
    mt["semanticClass"] = opt({"type": "string"}, "Lớp ngữ nghĩa cho mask AI")
    mt["pattern"] = {"type": "string", "description": f"[{ADD2}] Kiểu xếp gạch (herringbone, running-bond); chỉ mô tả, chưa dựng từng viên"}
    mt["sourceKnowledgeCode"] = opt({"type": "string"}, "Mã vật liệu trong kho tri thức")

    # module
    md = D["module"]["properties"]
    md["sourceRef"] = opt({"type": "string"}, "Mã module trong KitchenSpec (vd TD1)")
    md["storey"] = opt({"type": "string", "enum": ["base", "upper", "loft", "tall", "corner", "island"]}, "Tầng tủ")
    md["frontMaterialId"] = opt({"$ref": "#/$defs/id"}, "Vật liệu mặt cánh mặc định")
    md["frontStyle"] = opt({"type": "string", "enum": ["slab", "shaker", "glass"]}, "Kiểu cánh")
    md["blindCorner"] = opt({"type": "object", "properties": {"side": {"type": "string", "enum": ["left", "right"]}, "width": {"type": "number"}}},
                            "Phần góc khuất không có cánh")
    md["endPanel"] = opt({"type": "object", "properties": {"side": {"type": "string", "enum": ["left", "right"]}, "thickness": {"type": "number"}}},
                         "Tấm hông hoàn thiện")
    md["niches"] = opt({"type": "array", "items": {"type": "object", "properties": {"bottom": {"type": "number"}, "height": {"type": "number"},
                                                                                     "applianceId": {"$ref": "#/$defs/id"}}}},
                       "Hộc thiết bị (lò, tủ lạnh)")
    md["led"] = opt({"type": "boolean"}, "Có đèn LED hắt")
    md["placement"]["properties"]["offset"] = opt({"type": "number"}, "Khoảng cách từ góc dọc theo tường (mm)")
    md["placement"]["properties"]["elevation"] = opt({"type": "number"}, "Cao độ đáy module (mm)")
    cons = md["construction"]["properties"]
    renamed = {("plinthHeight" if k == "toeKickHeight" else k): v for k, v in cons.items()}  # v1.0.0 calls it toeKickHeight
    cons.clear()
    cons.update(renamed)
    cons["edgeBanding"] = opt({"type": "object", "properties": {"thickness": {"type": "number"}, "materialId": {"$ref": "#/$defs/id"}}}, "Nẹp cạnh")
    cons["grainDirection"] = opt({"type": "string", "enum": ["horizontal", "vertical"]}, "Hướng vân mặt cánh")
    cons["hingeCountPerDoor"] = opt({"type": "integer", "minimum": 0}, "Số bản lề mỗi cánh")
    dp = md["doors"]["items"]["properties"]
    dp["glass"] = opt({"type": "boolean"}, "Cánh kính")
    dp["openingAngle"] = opt({"type": "number", "default": 0}, "Góc mở khi dựng (độ), 0 = đóng")
    dp["frontStyle"] = opt({"type": "string", "enum": ["slab", "shaker", "glass"]}, "")
    dp["sourceRef"] = opt({"type": "string"}, "ID chi tiết trong bộ biên dịch (= layer ID sửa ảnh, vd TD1-canh-1)")
    if "drawers" in md and "items" in md["drawers"] and "properties" in md["drawers"]["items"]:
        md["drawers"]["items"]["properties"]["sourceRef"] = opt({"type": "string"}, "ID chi tiết (= layer ID sửa ảnh)")
    dp["hinges"] = opt({"type": "array", "items": {"type": "object", "properties": {"offset": {"type": "number"}}}}, "Vị trí bản lề dọc cạnh")

    # v1.4: partRef — which kind of detail a mesh is, so a click can be mapped to an action (door style, handle, countertop material...)
    ADD4 = "Bổ sung v1.4 (VicKitchenCabinet)"
    D["partRef"] = {"type": "object", "required": ["kind"], "description": f"[{ADD4}] Loại chi tiết của khối này, để giao diện biết bấm chuột phải vào thì sửa gì",
                    "properties": {"kind": {"type": "string", "enum": ["door", "drawer", "handle", "countertop"]},
                                   "module": {"type": "string", "description": "Mã module (KitchenSpec) chứa chi tiết; có với door/drawer/handle"},
                                   "wall": {"type": "string", "description": "Tường của dải mặt bàn; có với countertop"}}}
    PART_REF = {"$ref": "#/$defs/partRef", "description": f"[{ADD4}] Loại chi tiết (cánh, ngăn kéo, tay nắm, mặt bàn)"}
    dp["partRef"] = PART_REF
    if "drawers" in md and "items" in md["drawers"] and "properties" in md["drawers"]["items"]:
        md["drawers"]["items"]["properties"]["partRef"] = PART_REF

    # part
    pt = D["part"]["properties"]
    pt["customRole"] = opt({"type": "string", "enum": ["end_panel", "filler", "niche_back", "niche_board", "blind_panel"]},
                           "Vai trò chi tiết khi role = custom")
    pt["semanticClass"] = opt({"type": "string"}, "Lớp mask AI (khớp renderSettings.segmentationPalette)")
    pt["sourceRef"] = opt({"type": "string"}, "ID chi tiết trong bộ biên dịch (= layer ID sửa ảnh); tấm thân tách từ cùng một chi tiết")
    pt["edgeBanding"] = opt({"type": "array", "items": {"type": "string", "enum": ["front", "back", "top", "bottom", "left", "right"]}}, "Cạnh dán nẹp")

    D["hardwareRef"].setdefault("properties", {})["sourceRef"] = opt({"type": "string"}, "ID chi tiết tay nắm trong bộ biên dịch (= layer sửa ảnh, vd TD1-tay-nam-1)")

    D["hardwareRef"]["properties"]["partRef"] = PART_REF

    # thiết bị, phụ kiện
    apply = D["appliance"]["properties"]
    apply["sourceRef"] = opt({"type": "string"}, "Mã thiết bị trong KitchenSpec")
    apply["parentModuleId"] = opt({"$ref": "#/$defs/id"}, "Module chứa thiết bị")
    apply["energy"] = opt({"type": "string", "enum": ["electric", "induction", "gas", "none"]}, "Nguồn năng lượng")
    apply["clearances"] = opt({"type": "object", "properties": {"top": {"type": "number"}, "sides": {"type": "number"}, "back": {"type": "number"}}},
                           "Khoảng hở yêu cầu")
    ac = D["accessoryInstance"]["properties"]
    ac["sourceRef"] = opt({"type": "string"}, "Mã trong KitchenSpec")
    ac["partRef"] = PART_REF
    ac["edgeProfile"] = opt({"type": "string", "enum": ["square", "eased", "bevel", "bullnose", "ogee"]}, "Mặt đá: kiểu mép")
    ac["overhang"] = opt({"type": "number"}, "Mặt đá: độ nhô trước")
    ac["cutouts"] = opt({"type": "array", "items": {"type": "object", "properties": {"forId": {"$ref": "#/$defs/id"},
                                                                                       "type": {"type": "string", "enum": ["sink", "cooktop", "faucet_hole"]},
                                                                                       "dimensions": {"$ref": "#/$defs/dimensions"},
                                                                                       "transform": {"$ref": "#/$defs/transform"},
                                                                                       "estimated": {"type": "boolean"}}}},
                        "Mặt đá: lỗ khoét cho chậu/bếp (transform theo hệ của mặt đá)")

    # trang trí: phào quét theo đường gấp khúc
    de = D["decoration"]["properties"]
    de["path"] = opt({"type": "object", "required": ["type", "points"],
                      "properties": {"type": {"type": "string", "enum": ["polyline"]},
                                     "points": {"type": "array", "minItems": 2, "items": {"$ref": "#/$defs/vec3"}},
                                     "joints": {"type": "string", "enum": ["miter"], "default": "miter"},
                                     "ends": {"type": "string", "enum": ["flush"], "default": "flush"},
                                     "normalRule": {"type": "string"}}},
                     "Đường chạy của phào (toạ độ theo transform của decoration). Mặt cắt lấy từ assets[assetId].parameters.profile; "
                     "pháp tuyến phía phòng n = (t.z, 0, -t.x); đỉnh giữa vát góc (miter)")
    de["sourceRef"] = opt({"type": "string"}, "Mã phào trong KitchenSpec")
    de["semanticClass"] = opt({"type": "string"}, "Lớp mask AI (molding)")
    de["modules"] = opt({"type": "array", "items": {"$ref": "#/$defs/id"}}, "Các module phào chạy qua")

    # camera
    ca = D["camera"]["properties"]
    ca["up"] = opt({"$ref": "#/$defs/vec3"}, "Véc-tơ 'lên' (bắt buộc với góc nhìn thẳng từ trên xuống)")
    ca["aspect"] = opt({"type": "number"}, "Tỉ lệ khung")
    ca["fovAxis"] = opt({"type": "string", "enum": ["vertical", "horizontal"], "default": "vertical"}, "fov theo trục nào (three.js: dọc)")
    ca["orthoHeight"] = opt({"type": "number"}, "Orthographic: chiều cao vùng nhìn")

    # ràng buộc, render
    co = P["constraints"]["properties"]
    co["minimumCountertopToWallCabinet"] = opt({"type": "number"}, "Mặt bàn tới đáy tủ trên")
    co["minimumHoodClearance"] = opt({"type": "number"}, "Mặt bếp tới đáy máy hút mùi")
    co["sources"] = opt({"type": "object", "additionalProperties": {"type": "string"}}, "Ràng buộc -> mã quy tắc nguồn")
    rs = P["renderSettings"]["properties"]
    rs["pixelRatio"] = opt({"type": "number"}, "")
    rs["environment"] = opt({"type": "string"}, "HDR URL hoặc 'room' (RoomEnvironment)")
    rs["controlPasses"] = opt({"type": "array", "items": {"type": "string", "enum": ["lines", "depth", "normal", "seg", "seg_module", "instance", "albedo"]}},
                              "Ảnh điều khiển cho AI cần xuất")
    rs["segmentationPalette"] = opt({"type": "object", "additionalProperties": {"type": "string", "pattern": "^#([0-9a-fA-F]{6})$"}},
                                    "semanticClass -> màu mask")

    out = HERE / "kitchen-threejs.schema.json"
    out.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print("đã ghi", out)


if __name__ == "__main__":
    main()
