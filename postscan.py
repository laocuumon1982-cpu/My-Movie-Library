"""Việc làm sau mỗi lần quét xong: (1) sao lưu Data/library.db lên PikPak, (2) tháo (eject) ổ HDD vừa quét.

PikPak được gắn thành ổ đĩa bằng RaiDrive (như các tool PikPak khác của Duy Anh) nên "upload" = copy file vào
<ổ PikPak>\\2026\\_Backup My Movie Library\\library.db."""
import os, sys, time, shutil, sqlite3, subprocess

BACKUP_SUB = os.path.join('2026', '_Backup My Movie Library')
BACKUP_NAME = 'library.db'


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)).rstrip('\\/') == os.path.normcase(os.path.abspath(b)).rstrip('\\/')


def drive_of(path):
    """Gốc ổ đĩa chứa `path` (Windows: 'E:\\'), POSIX: trả lại path để so sánh."""
    d = os.path.splitdrive(os.path.abspath(path))[0]
    return (d + '\\') if d else os.path.abspath(path)


# ---------------------------------------------------------------- tìm ổ PikPak
def find_backup_dir(drive_list, configured=''):
    """Thư mục đích. configured (người dùng chọn tay) > ổ có nhãn 'PikPak' > ổ mạng có sẵn thư mục '2026'.
    Trả về (đường dẫn, ghi chú) hoặc (None, lý do)."""
    if configured:
        if os.path.isdir(configured): return configured, ''
        parent = os.path.dirname(configured.rstrip('\\/'))
        if parent and os.path.isdir(parent): return configured, ''
        return None, f'Thư mục PikPak đã chọn không truy cập được:\n{configured}\n(RaiDrive đã chạy chưa?)'
    cands = []
    for d in drive_list:
        if d.get('system'): continue
        lab = (d.get('label') or '').lower()
        root = d['root']
        if 'pikpak' in lab: cands.append((0, root))
        elif d.get('type') == 'Ổ mạng' or 'webdav' in (d.get('fs') or '').lower() or 'raidrive' in lab:
            if os.path.isdir(os.path.join(root, '2026')): cands.append((1, root))
    if not cands:
        return None, ('Không tìm thấy ổ PikPak (RaiDrive). Mở RaiDrive để gắn PikPak, hoặc chọn thư mục đích ở menu "⋯ Thêm" → '
                      '"Chọn thư mục sao lưu PikPak…".')
    cands.sort()
    return os.path.join(cands[0][1], BACKUP_SUB), ''


# ---------------------------------------------------------------- sao lưu
def backup_db(db_path, dest_dir):
    """Chụp bản nhất quán của library.db (sqlite backup API) rồi copy lên dest_dir/library.db (ghi đè bản cũ).
    Ghi ra tên .part rồi đổi tên để không bao giờ để lại file hỏng. Trả về đường dẫn đích."""
    os.makedirs(dest_dir, exist_ok=True)
    tmp = os.path.join(os.path.dirname(os.path.abspath(db_path)), '_upload_snapshot.db')
    for f in (tmp, tmp + '-wal', tmp + '-shm'):
        try: os.remove(f)
        except OSError: pass
    src = sqlite3.connect(db_path); dst = sqlite3.connect(tmp)
    try:
        src.backup(dst); dst.execute('PRAGMA journal_mode=DELETE')      # bản trên PikPak là 1 file đơn, không kèm -wal/-shm
    finally: dst.close(); src.close()
    try:
        final = os.path.join(dest_dir, BACKUP_NAME); part = final + '.part'
        shutil.copyfile(tmp, part)
        if os.path.getsize(part) != os.path.getsize(tmp): raise OSError('Kích thước file trên PikPak không khớp (upload dở dang).')
        os.replace(part, final)
        return final
    finally:
        try: os.remove(tmp)
        except OSError: pass


# ---------------------------------------------------------------- tháo ổ
def eject_blockers(root, drive, protected_paths):
    """Lý do KHÔNG được tháo (hoặc None nếu an toàn)."""
    if not drive: return 'Đây là thư mục (không phải cả một ổ đĩa) nên không tháo.'
    if drive.get('system'): return 'Đây là ổ hệ thống (Windows).'
    if drive.get('type') == 'Ổ mạng': return 'Đây là ổ mạng.'
    if not _same(root, drive['root']): return 'Chỉ quét một thư mục con, không tháo ổ.'
    for p in protected_paths:
        if p and _same(drive_of(p), drive['root']): return f'Ổ này đang chứa tool / thư viện ({p}).'
    return None


def eject_drive(letter, force=True):
    """Tháo ổ `letter` ('E:'). Trả về (ok, thông báo). Windows: dùng lệnh Eject của Explorer; nếu ổ còn bị chiếm
    thì ép: khóa, ngắt (dismount) volume bất chấp file đang mở rồi gửi lệnh eject."""
    if sys.platform != 'win32': return False, 'Tháo ổ chỉ hỗ trợ trên Windows.'
    letter = letter.rstrip('\\/').upper()
    if not _gone_wait(letter, 0):
        return True, f'Ổ {letter} đã được tháo.'
    _shell_eject(letter)
    if _gone_wait(letter, 6): return True, f'Đã tháo ổ {letter} an toàn — có thể rút cáp.'
    if not force: return False, f'Ổ {letter} đang bị chương trình khác sử dụng nên chưa tháo được.'
    ok, msg = _ioctl_eject(letter)
    if _gone_wait(letter, 3): return True, f'Đã ép tháo ổ {letter} — có thể rút cáp.'
    if ok: return True, f'Đã ngắt (dismount) ổ {letter}: {msg}. Nếu ổ vẫn còn trong "This PC", chờ đèn ổ tắt rồi rút cáp.'
    return False, f'Không tháo được ổ {letter}: {msg}'


def _gone_wait(letter, secs):
    end = time.time() + secs
    while True:
        if not os.path.exists(letter + '\\'): return True
        if time.time() >= end: return False
        time.sleep(0.4)


def _shell_eject(letter):
    ps = ("$s=New-Object -comObject Shell.Application;"
          f"$i=$s.Namespace(17).ParseName('{letter}');if($i){{$i.InvokeVerb('Eject')}}")
    try:
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', ps],
                       timeout=25, creationflags=0x08000000, capture_output=True)
    except Exception:
        pass


def _ioctl_eject(letter):
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    h = k.CreateFileW('\\\\.\\' + letter, 0xC0000000, 3, None, 3, 0, None)       # GENERIC_READ|WRITE, share R|W, OPEN_EXISTING
    if h in (None, wintypes.HANDLE(-1).value, 0xFFFFFFFF, -1):
        return False, f'không mở được ổ (mã lỗi {ctypes.GetLastError()}) — thử chạy tool bằng quyền Administrator'
    ret = wintypes.DWORD(0)
    def ctl(code, buf=None, n=0):
        return bool(k.DeviceIoControl(h, code, buf, n, None, 0, ctypes.byref(ret), None))
    try:
        for _ in range(4):                                                      # khóa (bỏ qua nếu thất bại — đang ép)
            if ctl(0x00090018): break
            time.sleep(0.5)
        if not ctl(0x00090020): return False, 'lệnh dismount bị từ chối'        # FSCTL_DISMOUNT_VOLUME
        pmr = (ctypes.c_ubyte * 4)(0, 0, 0, 0)                                  # PREVENT_MEDIA_REMOVAL = FALSE
        ctl(0x002D4804, pmr, 4)
        ejected = ctl(0x002D4808)                                               # IOCTL_STORAGE_EJECT_MEDIA
        return True, 'đã gửi lệnh eject' if ejected else 'đã ngắt volume'
    finally:
        k.CloseHandle(h)
