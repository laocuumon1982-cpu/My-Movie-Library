"""Việc làm sau mỗi lần quét xong: (1) sao lưu Data/library.db lên PikPak bằng rclone, (2) tháo (eject) ổ HDD vừa quét."""
import os, sys, time, shutil, sqlite3, subprocess, zipfile, tempfile, urllib.request

REMOTE = 'pikpak'
BACKUP_DIR = 'My Pack/2026/_Backup My Movie Library'
BACKUP_NAME = 'library.db'
RCLONE_URL = 'https://downloads.rclone.org/rclone-current-windows-amd64.zip'
NOWIN = 0x08000000 if sys.platform == 'win32' else 0


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)).rstrip('\\/') == os.path.normcase(os.path.abspath(b)).rstrip('\\/')


def drive_of(path):
    d = os.path.splitdrive(os.path.abspath(path))[0]
    return (d + '\\') if d else os.path.abspath(path)


def app_dir():
    return os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- rclone
def _exe_name():
    return 'rclone.exe' if sys.platform == 'win32' else 'rclone'


def find_rclone(data_dir):
    """rclone nằm cạnh app (thư mục rclone\\), hoặc trong Data\\rclone, hoặc có sẵn trong PATH."""
    for d in (os.path.join(app_dir(), 'rclone'), os.path.join(data_dir, 'rclone')):
        p = os.path.join(d, _exe_name())
        if os.path.isfile(p): return p
    return shutil.which('rclone')


def download_rclone(data_dir, progress=None):
    """Tải rclone về thư mục app (nếu không ghi được thì về Data). Trả về đường dẫn rclone.exe."""
    for base in (os.path.join(app_dir(), 'rclone'), os.path.join(data_dir, 'rclone')):
        try:
            os.makedirs(base, exist_ok=True)
            test = os.path.join(base, '.w'); open(test, 'w').close(); os.remove(test)
            break
        except OSError:
            continue
    else:
        raise OSError('Không ghi được thư mục để lưu rclone.')
    zpath = os.path.join(base, 'rclone.zip')
    req = urllib.request.Request(RCLONE_URL, headers={'User-Agent': 'MyMovieLibrary'})
    with urllib.request.urlopen(req, timeout=60) as r, open(zpath, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0); got = 0
        while True:
            b = r.read(1 << 16)
            if not b: break
            f.write(b); got += len(b)
            if progress: progress(got, total)
    try:
        with zipfile.ZipFile(zpath) as z:
            member = next(n for n in z.namelist() if n.lower().endswith('/' + _exe_name()) or n.lower() == _exe_name())
            with z.open(member) as src, open(os.path.join(base, _exe_name()), 'wb') as dst: shutil.copyfileobj(src, dst)
    finally:
        try: os.remove(zpath)
        except OSError: pass
    return os.path.join(base, _exe_name())


def conf_path(data_dir):
    return os.path.join(data_dir, 'rclone.conf')


def _run(args, timeout=300):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf8', errors='replace', timeout=timeout, creationflags=NOWIN)


def is_logged_in(rclone, data_dir):
    c = conf_path(data_dir)
    if not (rclone and os.path.isfile(c)): return False
    try: return (REMOTE + ':') in _run([rclone, 'listremotes', '--config', c], 30).stdout
    except Exception: return False


def login(rclone, data_dir, email, password):
    """Tạo remote 'pikpak' trong Data/rclone.conf (mật khẩu được rclone mã hóa nhẹ — obscure) rồi thử truy cập."""
    c = conf_path(data_dir)
    _run([rclone, 'config', 'delete', REMOTE, '--config', c], 30)
    r = _run([rclone, 'config', 'create', REMOTE, 'pikpak', 'user', email, 'pass', password, '--obscure', '--non-interactive',
              '--config', c], 120)
    if r.returncode != 0: raise RuntimeError((r.stderr or r.stdout).strip()[-400:] or 'rclone config lỗi')
    t = _run([rclone, 'lsd', REMOTE + ':', '--config', c, '--max-depth', '1'], 120)
    if t.returncode != 0:
        _run([rclone, 'config', 'delete', REMOTE, '--config', c], 30)
        raise RuntimeError('Đăng nhập PikPak không thành công (sai email/mật khẩu?):\n' + (t.stderr or t.stdout).strip()[-400:])


def logout(rclone, data_dir):
    if rclone: _run([rclone, 'config', 'delete', REMOTE, '--config', conf_path(data_dir)], 30)


# ---------------------------------------------------------------- sao lưu
def backup_db(db_path, data_dir, rclone):
    """Chụp bản nhất quán của library.db (sqlite backup API, 1 file đơn) rồi rclone copyto lên
    pikpak:2026/_Backup My Movie Library/library.db (ghi đè bản cũ). Trả về đường dẫn đích trên PikPak."""
    tmp = os.path.join(data_dir, 'library.db')
    snap = os.path.join(tempfile.gettempdir(), 'mml_upload', BACKUP_NAME)
    os.makedirs(os.path.dirname(snap), exist_ok=True)
    for f in (snap, snap + '-wal', snap + '-shm'):
        try: os.remove(f)
        except OSError: pass
    src = sqlite3.connect(db_path); dst = sqlite3.connect(snap)
    try:
        src.backup(dst); dst.execute('PRAGMA journal_mode=DELETE')
    finally:
        dst.close(); src.close()
    try:
        remote = f'{REMOTE}:{BACKUP_DIR}/{BACKUP_NAME}'
        r = _run([rclone, 'copyto', snap, remote, '--config', conf_path(data_dir), '--retries', '3', '--stats', '0'], 900)
        if r.returncode != 0: raise RuntimeError((r.stderr or r.stdout).strip()[-500:] or f'rclone mã lỗi {r.returncode}')
        return remote
    finally:
        try: os.remove(snap)
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
    """Tháo ổ `letter` ('E:'). Trả về (ok, thông báo chi tiết). Thử lần lượt:
    1) Lệnh Eject của Explorer (ổ USB 'rời'); 2) CM_Request_Device_Eject — chính là 'Safely Remove Hardware', chạy được cả với
    ổ HDD gắn USB hiện là ổ 'cố định'; 3) ép: khóa/ngắt volume bất chấp file đang mở, rồi eject lại; 4) đưa đĩa về offline (cần Admin)."""
    if sys.platform != 'win32': return False, 'Tháo ổ chỉ hỗ trợ trên Windows.'
    letter = letter.rstrip('\\/').upper(); notes = []
    if _gone_wait(letter, 0): return True, f'Ổ {letter} đã được tháo.'
    disk_no = None
    try: disk_no = _disk_number(letter)
    except Exception as ex: notes.append(f'đọc số đĩa: {ex}')
    _shell_eject(letter)
    if _gone_wait(letter, 3): return True, f'Đã tháo ổ {letter} an toàn — có thể rút cáp.'
    if disk_no is not None:
        ok, m = _cm_eject(disk_no); notes.append('Safely-Remove: ' + m)
        if ok and _gone_wait(letter, 8): return True, f'Đã tháo ổ {letter} an toàn (Safely Remove) — có thể rút cáp.'
    if not force: return False, f'Ổ {letter} đang bị chương trình khác dùng nên chưa tháo được. ' + ' | '.join(notes)
    ok, m = _ioctl_eject(letter); notes.append('ép dismount: ' + m)
    if _gone_wait(letter, 2): return True, f'Đã ép tháo ổ {letter} — có thể rút cáp.'
    if disk_no is not None:
        ok2, m2 = _cm_eject(disk_no); notes.append('Safely-Remove lần 2: ' + m2)
        if ok2 and _gone_wait(letter, 8): return True, f'Đã ép tháo ổ {letter} — có thể rút cáp.'
        ok3, m3 = _set_offline(disk_no); notes.append('offline: ' + m3)
        if ok3: return True, f'Đã đưa ổ {letter} (đĩa {disk_no}) về trạng thái Offline — có thể rút cáp.'
    if ok: return True, f'Đã ngắt (dismount) ổ {letter}; chờ đèn ổ tắt rồi rút cáp. (' + ' | '.join(notes) + ')'
    return False, f'Không tháo được ổ {letter}: ' + ' | '.join(notes)


def _gone_wait(letter, secs):
    end = time.time() + secs
    while True:
        if not os.path.exists(letter + '\\'): return True
        if time.time() >= end: return False
        time.sleep(0.4)


def _shell_eject(letter):
    ps = ("$s=New-Object -comObject Shell.Application;"
          f"$i=$s.Namespace(17).ParseName('{letter}');if($i){{$i.InvokeVerb('Eject')}}")
    try: _run(['powershell', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', ps], 25)
    except Exception: pass


def _open_dev(path, access=0):
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    h = k.CreateFileW(path, access, 3, None, 3, 0, None)
    bad = h is None or ctypes.c_void_p(h).value in (None, 0, ctypes.c_void_p(-1).value)
    return (None, ctypes.GetLastError()) if bad else (h, 0)


def _dev_number(h):
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    out = (wintypes.DWORD * 3)(); ret = wintypes.DWORD(0)
    if not k.DeviceIoControl(h, 0x002D1080, None, 0, out, 12, ctypes.byref(ret), None): return None   # IOCTL_STORAGE_GET_DEVICE_NUMBER
    return out[1]


def _disk_number(letter):
    import ctypes
    h, err = _open_dev('\\\\.\\' + letter, 0)
    if h is None: raise OSError(f'mở ổ lỗi {err}')
    try: return _dev_number(h)
    finally: ctypes.windll.kernel32.CloseHandle(h)


def _cm_eject(disk_no):
    """Tìm thiết bị đĩa số disk_no (SetupAPI) rồi yêu cầu eject nó hoặc thiết bị cha (USB) — như 'Safely Remove Hardware'."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32; sa = ctypes.windll.setupapi; cm = ctypes.windll.cfgmgr32

    class GUID(ctypes.Structure):
        _fields_ = [('a', wintypes.DWORD), ('b', wintypes.WORD), ('c', wintypes.WORD), ('d', ctypes.c_ubyte * 8)]

    class IFACE(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('Guid', GUID), ('Flags', wintypes.DWORD), ('Res', ctypes.c_void_p)]

    class DEVINFO(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('Guid', GUID), ('DevInst', wintypes.DWORD), ('Res', ctypes.c_void_p)]

    disk_guid = GUID(0x53f56307, 0xb6bf, 0x11d0, (ctypes.c_ubyte * 8)(0x94, 0xf2, 0x00, 0xa0, 0xc9, 0x1e, 0xfb, 0x8b))
    sa.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    sa.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    sa.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.POINTER(IFACE)]
    sa.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(IFACE), ctypes.c_void_p, wintypes.DWORD,
                                                    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(DEVINFO)]
    sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    hdev = sa.SetupDiGetClassDevsW(ctypes.byref(disk_guid), None, None, 0x12)          # PRESENT | DEVICEINTERFACE
    if hdev in (None, ctypes.c_void_p(-1).value): return False, 'SetupAPI lỗi'
    devinst = None
    try:
        i = 0
        while True:
            ifc = IFACE(); ifc.cbSize = ctypes.sizeof(IFACE)
            if not sa.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(disk_guid), i, ctypes.byref(ifc)): break
            i += 1
            need = wintypes.DWORD(0)
            sa.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifc), None, 0, ctypes.byref(need), None)
            buf = ctypes.create_string_buffer(need.value)
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            di = DEVINFO(); di.cbSize = ctypes.sizeof(DEVINFO)
            if not sa.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifc), buf, need.value, None, ctypes.byref(di)): continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            h, _e = _open_dev(path, 0)
            if h is None: continue
            try: n = _dev_number(h)
            finally: k.CloseHandle(h)
            if n == disk_no: devinst = di.DevInst; break
    finally:
        sa.SetupDiDestroyDeviceInfoList(hdev)
    if devinst is None: return False, f'không tìm thấy thiết bị của đĩa {disk_no}'
    cm.CM_Get_Parent.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.ULONG]
    cm.CM_Request_Device_EjectW.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_wchar_p, wintypes.ULONG, wintypes.ULONG]
    last = ''
    node = devinst
    for _ in range(4):                                                             # đĩa → USBSTOR → USB hub/port: thử từng cấp
        veto = wintypes.DWORD(0); name = ctypes.create_unicode_buffer(260)
        cr = cm.CM_Request_Device_EjectW(node, ctypes.byref(veto), name, 260, 0)
        if cr == 0 and veto.value == 0: return True, 'đã gửi yêu cầu tháo thiết bị'
        last = f'CR={cr} veto={veto.value} {name.value}'.strip()
        par = wintypes.DWORD(0)
        if cm.CM_Get_Parent(ctypes.byref(par), node, 0) != 0: break
        node = par.value
    return False, 'Windows từ chối: ' + last


def _set_offline(disk_no):
    try:
        r = _run(['powershell', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command',
                  f'Set-Disk -Number {int(disk_no)} -IsOffline $true -ErrorAction Stop'], 40)
        return r.returncode == 0, (r.stderr or r.stdout).strip()[:200] or 'ok'
    except Exception as ex:
        return False, str(ex)


def _ioctl_eject(letter):
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    h, err = _open_dev('\\\\.\\' + letter, 0xC0000000)
    if h is None: return False, f'không mở được ổ (mã lỗi {err}) — thử chạy tool bằng quyền Administrator'
    ret = wintypes.DWORD(0)
    def ctl(code, buf=None, n=0):
        return bool(k.DeviceIoControl(h, code, buf, n, None, 0, ctypes.byref(ret), None))
    try:
        for _ in range(4):
            if ctl(0x00090018): break                                               # FSCTL_LOCK_VOLUME (bỏ qua nếu thất bại)
            time.sleep(0.5)
        if not ctl(0x00090020): return False, 'dismount bị từ chối'                  # FSCTL_DISMOUNT_VOLUME
        ctl(0x002D4804, (ctypes.c_ubyte * 4)(0, 0, 0, 0), 4)                        # PREVENT_MEDIA_REMOVAL = FALSE
        return True, 'đã ngắt volume' if not ctl(0x002D4808) else 'đã gửi eject'     # IOCTL_STORAGE_EJECT_MEDIA
    finally:
        k.CloseHandle(h)
