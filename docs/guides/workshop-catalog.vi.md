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

## Thiết kế đang có thì sao

Mỗi thiết kế giữ danh mục lúc nó được lưu. Khi danh mục đổi, trình sửa hiện thông báo (**Danh mục đã cập nhật**) trên thiết kế dùng mục
đã đổi; bấm **Cập nhật** để áp danh mục mới thành một bản sửa mới (hoàn tác bằng quay lại bản cũ). Không có gì tự đổi ngầm.

## Chuyển danh mục sang máy khác

**Xuất** lưu một loại; **Xuất tất cả** lưu cả danh mục của xưởng vào một tệp (`kitchen-catalog-bundle/1`). **Nhập** nhận cả hai; mọi mục
được kiểm tra như khi lưu bằng tay.
