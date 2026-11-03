# My Movie Library v2.0 by Duy Anh

Quản lý danh sách phim theo thư mục các ổ HDD, đọc từ bản in PDF của **Karen's Directory Printer**.

## Cách dùng
1. Bỏ các file PDF vào thư mục `Data` — **mỗi PDF = 1 ổ HDD, tên file = tên HDD** (vd `01 - AUDIO 1.pdf`).
2. Mở `My Movie Library.exe` → bấm **Nạp data**. Xem theo tab *Danh sách* hoặc *Cây thư mục*; tìm kiếm không dấu.
3. Xong bấm **Xóa data** (thoát tool cũng tự xóa; file PDF không bị xóa).

## Tải về
Vào [Releases](../../releases): `My Movie Library.exe` hoặc `My-Movie-Library-Portable.zip` (exe + thư mục Data).
Trong tool có nút **Update** tự kiểm tra và cập nhật bản mới.

## Chạy từ mã nguồn
`pip install pypdf` rồi `python app.py` (hoặc `Chay_App.bat`). Build exe: `build.bat`.
Phát hành bản mới: sửa `version.py`, `git tag vX.Y.Z && git push --tags` — GitHub Actions tự build và đăng Release.
