# Hướng dẫn xưởng: danh mục dữ liệu

Danh mục là dữ liệu mà phần thiết kế bếp dựa vào: loại tủ, mẫu bố trí, thiết bị, vật liệu, luật. Mở từ trình sửa bằng nút **📚 Danh mục**
(`catalog.html`). Chọn vai trò ở trên cùng (**xưởng** hoặc **người dùng**); máy chủ có thể cố định vai trò (`KITCHEN_FIXED_ROLE`).

## Những gì sửa được

| Loại | Quyết định điều gì | Ai sửa |
|---|---|---|
| Loại tủ | tầng tủ, công thức kích thước, phần mặt (cánh, ngăn kéo, kính), từ cho prompt ảnh | xưởng |
| Mẫu bố trí bếp | chữ I / L / U và mẫu riêng: các tường, các bước lấp tủ (tủ góc dưới, dãy tủ dưới, kệ góc, dãy tủ trên) | xưởng, người dùng |
| Luật bố trí | cách chia một dãy (chậu gần tủ lạnh hơn bếp, hút mùi luôn trên tủ bếp nấu, bề rộng) | xưởng |
| Bố trí vách tivi | các tấm và công thức của vách tivi | xưởng, người dùng |
| Kích thước và vật liệu mặc định | kích thước thiết kế mới; tên vật liệu vẽ khi thiết kế không ghi | xưởng |
| Từ điển lệnh | các từ trình sửa hiểu ("rộng thêm", màu, kiểu lát gạch) | xưởng |
| Thiết bị, vật liệu, phong cách, bảng màu, khu vực, tri thức… | như tên gọi | xem trên trang |

Loại bị khóa (luật dành cho lập trình viên) chỉ xem, không sửa.

## Sửa một mục

1. Chọn loại, chọn mục, bấm **Sửa** (hoặc **Mới**). Công thức dùng các biến ghi cạnh ô (`width`, `height`, `depth`…); lỗi hiện ngay dưới ô
   kèm vị trí.
2. **Xem trước** vẽ thử mục đó (loại tủ, mẫu bố trí) mà không lưu.
3. **Lưu**. Máy chủ kiểm tra mục có dịch được không; nếu không, không lưu gì và báo lý do.
4. **Lịch sử** liệt kê các bản trước; **So sánh** chỉ ra các trường khác với mục gốc.

## Lưu một bếp thành mẫu bố trí

Trong trình sửa, chọn một tủ của hệ tủ muốn giữ, bấm **💾 Lưu hệ tủ thành mẫu** rồi đặt tên. Hệ tủ vào danh mục thành một mẫu bố trí của
lớp bạn: tủ góc, các tủ dưới và tủ cao theo đúng thứ tự (bước `cabinets`), tủ trên, kệ góc. Dãy có nhiều góc nhất thành tường sau, dãy
vuông góc với nó thành tường bên. Tủ dưới thường co giãn (`fill`) để cùng bếp đó vừa tường dài ngắn khác; chậu, bếp nấu, tủ lạnh và tủ
khác giữ bề rộng. Dùng ở **Tạo thiết kế → Hình**, hoặc gõ "… theo mẫu <tên>" khi thay hệ tủ (mẫu một tường được trải dọc dãy). Tủ mẫu
không giữ được (đảo, dãy xiên) được liệt kê khi lưu.

## Loại cửa phòng (cửa đi, cửa sổ)

Loại `opening-type` (xưởng và người dùng sửa) quyết định cửa của phòng trông ra sao và đo thế nào. Cửa trong thiết kế đặt theo **trục**:
tim cửa trên trục tường (đường tim của cả tường thẳng), bề rộng là **lỗ tường**, các trục đứng / ngang chia lỗ thành ô, mỗi cánh phủ một
nhóm ô (xem `docs/adr/0005-opening-contract.md`).

| Trường | Ý nghĩa |
|---|---|
| `kind`, `operation` | cửa đi / cửa sổ / lỗ thông; kiểu mở chính |
| `axesRatio` | trục đứng giữa theo tỉ lệ bề rộng lỗ (vd `[0.5]` hai cánh đều, `[0.75]` cánh mẹ con 900 + 300 trên lỗ 1200) |
| `hAxesFromSill`, `hAxesRatio` | trục ngang (ô thoáng, ô fix trên cửa sổ): mm từ bậu, hoặc tỉ lệ chiều cao |
| `leaves` | các cánh: ô từ trục nào tới trục nào (`cols`, `rows`; số âm đếm từ cuối), kiểu mở, bản lề bám trục nào, mở vào / ra nhìn từ bếp, cánh chính |
| `frameFace`, `frameDepth`, `casing`, `transom`, `threshold`, `stop` | khung: mặt khung, sâu khung (trống = dày tường), nẹp chỉ, đố ngang, ngưỡng, chặn cửa |
| `leafThickness`, `gap`, `minLeaf`, `openingAngle` | cánh: dày, khe, bề rộng tối thiểu, góc mở (vùng quét) |
| `defaultHeight`, `defaultSill` | chiều cao lỗ và bậu khi không ghi (cũng là chiều cao mặc định khi bản vẽ mặt bằng thiếu cao độ) |
| `defaultWidth`, `minWidth`, `maxWidth` | khổ rộng của cửa mới khi câu lệnh không ghi; khoảng khổ của mẫu: khổ nằm ngoài sẽ được hỏi trước khi tạo cửa ("giữ nguyên khổ" ghi `oversize` vào cửa, "dùng khổ của mẫu" đưa về trong khoảng) |
| `sizes` | **khổ lỗ tường** chuẩn theo nước (`widths`, `heights`): số AI đoán từ ảnh được bắt về khổ gần nhất trong ±30 mm |
| `sources` | nguồn của các khổ theo nước (loại nguồn, đường dẫn, ghi chú) |

Thông thủy được tính: ô của cánh chính − khung ở mép lỗ − (dày cánh + chặn cửa) với cánh quay. **Xem trước** vẽ hình chiếu đứng của loại ở
từng khổ chuẩn của nước (tham số `?country=` của trang) kèm thông thủy, hoặc báo lỗi nếu mẫu cánh không phủ kín các ô. Khổ của nước ghi theo
cánh (Mỹ, Anh, Úc) đã được đổi sang lỗ tường theo cách quy đổi ghi trong `sources`.

## Tay nắm và bản lề

Loại `handle` và `hinge` (xưởng và người dùng sửa) liệt kê phụ kiện xưởng có: tên, hãng, mã sản phẩm, kích thước, vật liệu/màu và giá
(`price.amount` + `price.currency`, ví dụ `VND`). Gọi tên một tay nắm trong câu lệnh ("đổi tay nắm thành tay thanh inox 320") sẽ lấy kiểu,
chiều dài và màu của nó cho tủ, và thiết kế ghi lại đó là tay nắm nào trong danh mục (`handle.item`); sửa tay nắm bằng tay sau đó thì bỏ
liên kết này. Bản lề hiện mới có trong danh mục, thiết kế chưa dùng.

## Thiết kế đang có thì sao

Mỗi thiết kế giữ danh mục lúc nó được lưu. Khi danh mục đổi, trình sửa hiện thông báo (**Danh mục đã cập nhật**) trên thiết kế dùng mục
đã đổi; bấm **Cập nhật** để áp danh mục mới thành một bản sửa mới (hoàn tác bằng quay lại bản cũ). Không có gì tự đổi ngầm.

## Chuyển danh mục sang máy khác

**Xuất** lưu một loại; **Xuất tất cả** lưu cả danh mục của xưởng vào một tệp (`kitchen-catalog-bundle/1`). **Nhập** nhận cả hai; mọi mục
được kiểm tra như khi lưu bằng tay.
