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
