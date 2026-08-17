# Lemon3 RPA — Xuất kho từ hóa đơn bán hàng

Tool đọc cột **SỐ PHIẾU** trên Excel, lọc trên màn hình **Danh sách hoá đơn bán hàng (D05F9300)**, rồi xuất kho đúng thao tác bạn đang làm.

## Luồng

1. `D05F9300` — **gõ thật từng ký tự** Số phiếu vào ô lọc lưới (lưới lọc theo sự kiện gõ phím, dán clipboard thì lưới không lọc), **đọc lại ô lọc cho đủ số**
2. **Mũi tên xuống** để vào dòng phiếu, rồi **Ctrl+K** Xuất kho
3. `Chọn kho - D05F3104` → kho **1000** đã được hệ thống chọn sẵn → **đếm số kho được tick** (= số dòng Diễn giải) → **Alt+T**
4. `Phiếu xuất kho - D05F3105` → nếu có popup thì **dừng phiếu này**, không gõ tiếp → **Alt+↓** xổ Loại nghiệp vụ → xuống **dòng 4** (`MNNKXB01`) → **Enter** → **F11** Diễn giải → điền **từng dòng kho** (mũi tên xuống giữa các dòng), xong hết mới **Alt+L**
5. `Thông báo` đúng **"Dữ liệu đã được lưu thành công"** → **Enter** = SUCCESS; popup khác = UNCERTAIN, chụp ảnh, không tự chạy lại
6. **Alt+N** Đóng

Phím tắt sửa trong `scenarios/xuat_kho.yaml` mục `erp.keys` (`continue`, `description`, `save`, `close`, `ok`).

**Diễn giải nhiều dòng:** số dòng Diễn giải trên `D05F3105` bằng **số kho được tick** trên `D05F3104` — các kho được tick luôn được đẩy lên đầu danh sách nên tool đọc ảnh màn đó để đếm. Log ghi `Kho duoc xuat: 1000, 1013 -> 2 dong dien giai`. Mặc định mỗi dòng điền số phiếu; muốn dòng 2/3 ghi nội dung khác thì thêm cột Excel `DIEN_GIAI_2` / `DIEN_GIAI_3`. Nếu không đếm được (log báo `se dien 1 dong dien giai`), tool chỉ điền 1 dòng cho an toàn — đặt `erp.description.rows: 2` trong YAML để chốt cứng.

**Chờ lưới lọc:** `app.filter_timeout_ms` (mặc định 1000) là thời gian chờ **tối đa** — thấy phiếu là đi tiếp ngay, không chờ hết. Log ghi rõ `FOUND ... sau 0.4s (2 lan quet)` để biết lưới thực tế lọc mất bao lâu; nếu phiếu có thật mà báo `NOT_FOUND sau 1.0s` thì tăng số này lên.

**Nếu lưới vẫn không lọc:** đặt `erp.keys.apply_filter: '{ENTER}'` trong YAML để tool bấm thêm Enter sau khi gõ (để rỗng nghĩa là gõ xong để lưới tự lọc).

**Tiếp tục chỉ bấm MỘT lần:** `D05F3105` mất **20–22 giây** mới mở. Tool chờ tới 60s và **không bao giờ bấm Tiếp tục lần hai** — bấm lần hai là DIGINET mở lại chính phiếu đó và tự khoá phiếu (`đang được xử lý bởi User ...`), đồng thời form vừa hiện ra đã bị gõ phím vào nên bước nghiệp vụ hỏng theo. Log ghi `Phieu xuat kho mo sau 21s` để biết thực tế mất bao lâu.

**Phiếu bị khoá:** DIGINET báo `Số phiếu "..." đang được xử lý bởi User "NV1722"` ngay khi `D05F3105` vừa mở. Tool đóng popup, **đóng phiếu và không lưu**, ghi `FAILED` rồi sang phiếu sau — tuyệt đối không gõ nghiệp vụ / diễn giải vào form đang bị khoá. Khoá thường là do chính phiên trước mở phiếu đó rồi thoát giữa chừng; thoát hẳn DIGINET rồi đăng nhập lại là hết khoá.

**Nhịp chọn nghiệp vụ:** `erp.operation.ms` (mặc định 800) là khoảng nghỉ giữa `Alt+↓` → mũi tên → `Enter`. Để 300 thì lưới tra cứu chưa nạp xong 4 dòng, `Enter` rơi vào khoảng trống và dropdown kẹt ở trạng thái đang xổ. Tool thử `Enter` tối đa 3 lần trước khi báo lỗi.

**Dừng khi lọc hỏng:** 5 phiếu liên tiếp `NOT_FOUND` thì tool dừng cả lượt chạy. Đó gần như luôn là dấu hiệu DIGINET đang mở màn hình khác đè lên `D05F9300`, không phải phiếu không tồn tại.

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
