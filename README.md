# Lemon3 RPA — Xuất kho từ hóa đơn bán hàng

Tool đọc cột **SỐ PHIẾU** trên Excel, lọc trên màn hình **Danh sách hoá đơn bán hàng (D05F9300)**, rồi xuất kho đúng thao tác bạn đang làm.

## Luồng

1. `D05F9300` — nhập Số phiếu vào ô lọc lưới, **đợi mã trên lưới khớp tuyệt đối** (không F5)
2. **Mũi tên xuống** để vào dòng phiếu, rồi **Ctrl+K** Xuất kho — chỉ khi đã `FOUND`
3. `Chọn kho - D05F3104` → kho **1000** đã được hệ thống chọn sẵn → **Alt+T**
4. `Phiếu xuất kho - D05F3105` → **Alt+↓** xổ Loại nghiệp vụ → xuống **dòng 4** (`MNNKXB01`) → **Enter** → **F11** Diễn giải (1–3 dòng) → **Alt+L**
5. `Thông báo` đúng **"Dữ liệu đã được lưu thành công"** → **Enter** = SUCCESS; popup khác = UNCERTAIN, chụp ảnh, không tự chạy lại
6. **Alt+N** Đóng

Phím tắt sửa trong `scenarios/xuat_kho.yaml` mục `erp.keys` (`continue`, `description`, `save`, `close`, `ok`).

## Chạy

1. Mở DIGINET, vào đúng **Danh sách hoá đơn bán hàng**.
2. Double-click `run.bat`.
3. Chọn file Excel (cột `SỐ PHIẾU`).
4. Bấm **Kiểm tra tìm phiếu** trước (nhập + xác minh lưới, không Ctrl+K, không Lưu).
5. Chạy thật trên 1 phiếu.

**Chỉ in mô tả** không bấm DIGINET — không dùng để test lọc phiếu.

Dừng khẩn cấp: đưa chuột vào góc trên-trái màn hình.

Kết quả mỗi lần chạy nằm trong `artifacts/runs/<id>/` (log, ảnh, checkpoint, bản sao Excel). Tool **không ghi đè file Excel nguồn**.

Nếu không nhập được ô Số phiếu: bấm **Ghi tọa độ (3s)** trên ô lọc. Tọa độ được ghi vào YAML và giao diện cùng một nguồn.
