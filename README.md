# My Movie Library v3.0 by Duy Anh

Quét các ổ HDD, lưu **toàn bộ thư mục / thư mục con / tên file** vào thư viện có **mã số**, rồi tìm kiếm tức thì — kể cả khi ổ không cắm trong máy.

## Cách dùng
1. Cắm ổ HDD → bấm **＋ Quét ổ HDD** → chọn ổ (hoặc *Chọn thư mục khác…*) → **Bắt đầu quét**.
2. Mỗi ổ được đánh mã `H01`, `H02`… (đổi được). Mỗi thư mục `H01-D00012`, mỗi file `H01-000123`.
3. Gõ vào ô tìm kiếm (không cần dấu):

| Gõ | Ý nghĩa |
|---|---|
| `avengers endgame` | tên file hoặc đường dẫn chứa các từ này |
| `ext:mkv,mp4` · `kind:audio` | lọc theo đuôi / loại |
| `>1gb` · `<500mb` | lọc theo dung lượng |
| `hdd:H01` | chỉ trong ổ H01 |
| `H01-000123` · `H01-D00012` · `H01-` | tìm theo mã file / thư mục / cả ổ |

4. Ba chế độ xem: **Tìm file**, **Thư mục** (thư mục chứa phim), **Cây thư mục** (có *Xem trong cây thư mục* từ kết quả tìm).
5. Thư viện lưu ở `Data/library.db` cạnh tool (portable). Quét lại ổ khi thêm/xóa phim; **Thêm → Sao lưu thư viện** để backup.

## Tải về
Vào [Releases](../../releases): `My Movie Library.exe` hoặc `My-Movie-Library-Portable.zip`. Nút **Update** trong tool tự kiểm tra và cập nhật bản mới (thư viện được giữ nguyên).

## Chạy từ mã nguồn
Python 3.9+ (không cần cài thêm thư viện): `python app.py` hoặc `Chay_App.bat`. Build exe: `build.bat`.
Phát hành bản mới: sửa `APP_VERSION` trong `version.py` rồi push lên `main` — GitHub Actions tự build và đăng Release `vX.Y.Z`.

## Giao diện mới (v3.3)

Giao diện web (pywebview / Edge WebView2 có sẵn trong Windows 10/11) cùng phong cách **PikPak Auto Save**: thanh bên có phím nổi và đèn LED trạng thái từng ổ HDD, nút 3D, ống tiến độ, nhật ký kiểu màn hình CRT, giao diện sáng / tối. Máy nào không chạy được giao diện web thì tool tự dùng giao diện cũ (Tk).

## Sao lưu PikPak (rclone) + tháo ổ sau khi quét (v3.2)

Sau mỗi lần quét xong, tool tự:
1. **Sao lưu** `Data/library.db` lên PikPak: `My Pack/2026/_Backup My Movie Library/library.db` (ghi đè bản cũ) bằng **rclone**. Không cần RaiDrive. rclone tự tải về thư mục `rclone\` cạnh app nếu chưa có. Đăng nhập một lần ở **⋯ Thêm → Đăng nhập rclone PikPak…** (mật khẩu lưu dạng mã hóa trong `Data/rclone.conf`).
2. **Tháo ổ HDD** vừa quét, chỉ báo thành công khi đĩa vật lý thật sự biến mất khỏi hệ thống. Thử lần lượt: Explorer Eject → Safely Remove Hardware; nếu không được, **tự chuyển sang chế độ ÉP**: ngắt mọi volume bất chấp file đang mở → gỡ thiết bị cùng cây con → vô hiệu thiết bị USB cha → đưa đĩa Offline (các cấp sau cần Administrator, tool tự xin quyền qua UAC). Có thêm nút **⏏ Tháo ổ** để tháo thủ công từng ổ. Không tháo ổ hệ thống, ổ mạng, ổ chứa tool/thư viện, hoặc khi chỉ quét một thư mục con.

Hai việc này bật/tắt bằng 2 ô tick trong hộp thoại quét. **⋯ Thêm → Sao lưu thư viện lên PikPak ngay** để sao lưu thủ công.
