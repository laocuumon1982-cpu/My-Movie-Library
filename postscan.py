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


def is_admin():
    try:
        import ctypes; return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def eject_drive(letter, force=True, log=None, elevate=True):
    """Tháo ổ `letter` ('E:'). Trả về (ok, thông báo). ok=True CHỈ KHI đĩa vật lý thật sự biến mất khỏi hệ thống (hoặc đã Offline).
    Các cấp, dừng ở cấp đầu tiên thành công:
      1  Explorer Eject          2  Safely Remove (CM_Request_Device_Eject) trên đĩa → thiết bị cha (USB)
      --- nếu không tháo được thì tự chuyển sang CHẾ ĐỘ ÉP ---
      3  ép: khóa + ngắt mọi volume của đĩa bất chấp file đang mở → Safely Remove lại
      4  ép: CM_Query_And_Remove_SubTree (gỡ thiết bị cùng cây con)
      5  ép (cần Admin): vô hiệu hóa thiết bị USB cha   6  ép (cần Admin): đưa đĩa về Offline
    Chưa là Admin mà cần ép → tự xin quyền Admin (UAC) rồi chạy lại cấp 3–6."""
    log = log or (lambda m: None)
    if sys.platform != 'win32': return False, 'Tháo ổ chỉ hỗ trợ trên Windows.'
    letter = letter.rstrip('\\/').upper()
    try: disk = _disk_number(letter)
    except Exception as ex: disk = None; log(f'Không đọc được số đĩa của {letter}: {ex}')
    if disk is None:
        return (True, f'Ổ {letter} không còn trong máy.') if not os.path.exists(letter + '\\') else (False, f'Không xác định được đĩa vật lý của ổ {letter}.')
    letters = _letters_on_disk(disk) or [letter]
    log(f'Ổ {", ".join(letters)} thuộc đĩa vật lý số {disk}.')
    if _wait_gone(disk, 0): return True, f'Đĩa {disk} đã được tháo.'

    log('Cấp 1: lệnh Eject của Explorer…')
    for l in letters: _shell_eject(l)
    if _wait_gone(disk, 5): return True, f'Đã tháo ổ {letter} an toàn (Explorer) — có thể rút cáp.'
    log('Cấp 2: Safely Remove Hardware…')
    ok, m = _cm_eject(disk); log('   → ' + m)
    if _wait_gone(disk, 10): return True, f'Đã tháo ổ {letter} an toàn (Safely Remove) — có thể rút cáp.'
    if not force: return False, f'Ổ {letter} chưa tháo được (đang bị chương trình khác dùng): {m}'
    return _force_eject(disk, letters, letter, log, elevate)


def _force_eject(disk, letters, letter, log, elevate):
    log('⚠ Không tháo an toàn được → CHUYỂN SANG CHẾ ĐỘ ÉP THÁO.')
    log('Cấp 3: ép ngắt volume (bất chấp file đang mở) rồi Safely Remove lại…')
    for l in letters:
        ok, m = _ioctl_eject(l); log(f'   {l} → {m}')
    ok, m = _cm_eject(disk); log('   Safely Remove → ' + m)
    if _wait_gone(disk, 10): return True, f'Đã ÉP tháo ổ {letter} — có thể rút cáp.'
    log('Cấp 4: gỡ thiết bị cùng cây con (CM_Query_And_Remove_SubTree)…')
    ok, m = _cm_remove_subtree(disk); log('   → ' + m)
    if _wait_gone(disk, 10): return True, f'Đã ÉP tháo ổ {letter} (gỡ thiết bị) — có thể rút cáp.'
    if not is_admin():
        if elevate:
            log('Cấp 5–6 cần quyền Administrator → xin quyền (hộp thoại UAC)…')
            r = _run_elevated(letter)
            if r is None: return False, f'Không tháo được ổ {letter}: chưa được cấp quyền Administrator. Hãy chạy tool bằng "Run as administrator".'
            return r[0], r[1]
        return False, f'Không tháo được ổ {letter} (cần quyền Administrator).'
    log('Cấp 5: vô hiệu hóa thiết bị USB cha (cần Admin)…')
    ok, m = _cm_disable_parent(disk); log('   → ' + m)
    if _wait_gone(disk, 8): return True, f'Đã ÉP tháo ổ {letter} (vô hiệu thiết bị) — có thể rút cáp.'
    log('Cấp 6: đưa đĩa về Offline…')
    ok, m = _set_offline(disk); log('   → ' + m)
    if ok and _is_offline(disk): return True, f'Đã ép đĩa {disk} (ổ {letter}) về OFFLINE — ổ không còn truy cập được, có thể rút cáp.'
    return False, f'KHÔNG tháo được ổ {letter} dù đã ép tất cả các cấp. Hãy đóng mọi cửa sổ/chương trình đang dùng ổ rồi dùng "Safely Remove Hardware" trong khay hệ thống. ({m})'


def _run_elevated(letter):
    """Chạy lại chính tool với quyền Admin (--force-eject) chỉ để ép tháo; trả (ok, msg) hoặc None nếu bị từ chối UAC."""
    import ctypes, json
    from ctypes import wintypes
    out = os.path.join(tempfile.gettempdir(), 'mml_eject_result.json')
    try: os.remove(out)
    except OSError: pass
    exe = sys.executable
    params = f'--force-eject {letter} "{out}"' if getattr(sys, 'frozen', False) else f'"{os.path.join(app_dir(), "mml.py")}" --force-eject {letter} "{out}"'

    class SEI(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND), ('lpVerb', wintypes.LPCWSTR),
                    ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR), ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int),
                    ('hInstApp', wintypes.HINSTANCE), ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]
    sei = SEI(); sei.cbSize = ctypes.sizeof(SEI); sei.fMask = 0x40; sei.lpVerb = 'runas'; sei.lpFile = exe; sei.lpParameters = params; sei.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)): return None
    ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 150000); ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    try:
        with open(out, encoding='utf-8') as f: d = json.load(f)
        return bool(d['ok']), d['msg']
    except Exception:
        return False, 'Bản chạy với quyền Admin không trả kết quả.'


def eject_cli(letter, out):
    """Gọi từ `mml.py --force-eject E: <file>` (đang chạy bằng quyền Admin): chỉ chạy các cấp ép, ghi kết quả ra file."""
    import json
    letters, disk = [letter], None
    try: disk = _disk_number(letter); letters = _letters_on_disk(disk) or [letter]
    except Exception: pass
    if disk is None: res = (False, 'Không đọc được đĩa vật lý.')
    elif _wait_gone(disk, 0): res = (True, f'Đã tháo ổ {letter}.')
    else: res = _force_eject(disk, letters, letter, lambda m: None, False)
    with open(out, 'w', encoding='utf-8') as f: json.dump({'ok': bool(res[0]), 'msg': res[1]}, f, ensure_ascii=False)


# ---------------------------------------------------------------- hạ tầng Windows
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


def _letters_on_disk(disk):
    """Mọi ký tự ổ (phân vùng) nằm trên cùng đĩa vật lý."""
    import string
    out = []
    for c in string.ascii_uppercase:
        l = c + ':'
        if not os.path.exists(l + '\\'): continue
        try:
            if _disk_number(l) == disk: out.append(l)
        except Exception: pass
    return out


def _enum_disks():
    """[(số đĩa, devinst)] của các đĩa đang HIỆN DIỆN trong hệ thống (SetupAPI)."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32; sa = ctypes.windll.setupapi

    class GUID(ctypes.Structure):
        _fields_ = [('a', wintypes.DWORD), ('b', wintypes.WORD), ('c', wintypes.WORD), ('d', ctypes.c_ubyte * 8)]

    class IFACE(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('Guid', GUID), ('Flags', wintypes.DWORD), ('Res', ctypes.c_void_p)]

    class DEVINFO(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('Guid', GUID), ('DevInst', wintypes.DWORD), ('Res', ctypes.c_void_p)]

    g = GUID(0x53f56307, 0xb6bf, 0x11d0, (ctypes.c_ubyte * 8)(0x94, 0xf2, 0x00, 0xa0, 0xc9, 0x1e, 0xfb, 0x8b))
    sa.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    sa.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    sa.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.POINTER(IFACE)]
    sa.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(IFACE), ctypes.c_void_p, wintypes.DWORD,
                                                    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(DEVINFO)]
    sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    hdev = sa.SetupDiGetClassDevsW(ctypes.byref(g), None, None, 0x12)                  # PRESENT | DEVICEINTERFACE
    if hdev in (None, ctypes.c_void_p(-1).value): return []
    out = []
    try:
        i = 0
        while True:
            ifc = IFACE(); ifc.cbSize = ctypes.sizeof(IFACE)
            if not sa.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(g), i, ctypes.byref(ifc)): break
            i += 1
            need = wintypes.DWORD(0)
            sa.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifc), None, 0, ctypes.byref(need), None)
            buf = ctypes.create_string_buffer(need.value)
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            di = DEVINFO(); di.cbSize = ctypes.sizeof(DEVINFO)
            if not sa.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifc), buf, need.value, None, ctypes.byref(di)): continue
            h, _e = _open_dev(ctypes.wstring_at(ctypes.addressof(buf) + 4), 0)
            if h is None: continue
            try: n = _dev_number(h)
            finally: k.CloseHandle(h)
            if n is not None: out.append((n, di.DevInst))
    finally:
        sa.SetupDiDestroyDeviceInfoList(hdev)
    return out


def _wait_gone(disk, secs):
    """True khi đĩa vật lý `disk` KHÔNG còn trong hệ thống (đã tháo thật). Không dựa vào ký tự ổ."""
    end = time.time() + secs
    while True:
        try: present = any(n == disk for n, _ in _enum_disks())
        except Exception: present = True
        if not present: return True
        if time.time() >= end: return False
        time.sleep(0.5)


def _devinst_chain(disk, levels=3):
    """devinst của đĩa rồi các thiết bị cha (đĩa → USBSTOR/SCSI → thiết bị USB). Dừng trước hub để không gỡ nhầm thiết bị khác."""
    import ctypes
    from ctypes import wintypes
    cm = ctypes.windll.cfgmgr32
    cm.CM_Get_Parent.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.ULONG]
    node = next((d for n, d in _enum_disks() if n == disk), None)
    chain = []
    while node is not None and len(chain) < levels:
        chain.append(node); par = wintypes.DWORD(0)
        node = par.value if cm.CM_Get_Parent(ctypes.byref(par), node, 0) == 0 else None
    return chain


def _cm_eject(disk):
    import ctypes
    from ctypes import wintypes
    cm = ctypes.windll.cfgmgr32
    cm.CM_Request_Device_EjectW.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_wchar_p, wintypes.ULONG, wintypes.ULONG]
    chain = _devinst_chain(disk)
    if not chain: return False, f'không tìm thấy thiết bị của đĩa {disk}'
    last = ''
    for node in chain:
        veto = wintypes.DWORD(0); name = ctypes.create_unicode_buffer(260)
        cr = cm.CM_Request_Device_EjectW(node, ctypes.byref(veto), name, 260, 0)
        if cr == 0 and veto.value == 0: return True, 'đã gửi yêu cầu tháo thiết bị'
        last = f'CR={cr} veto={veto.value} {name.value}'.strip()
    return False, 'Windows từ chối: ' + last


def _cm_remove_subtree(disk):
    import ctypes
    from ctypes import wintypes
    cm = ctypes.windll.cfgmgr32
    cm.CM_Query_And_Remove_SubTreeW.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_wchar_p, wintypes.ULONG, wintypes.ULONG]
    chain = _devinst_chain(disk)
    if not chain: return False, 'không tìm thấy thiết bị'
    last = ''
    for node in chain:
        veto = wintypes.DWORD(0); name = ctypes.create_unicode_buffer(260)
        cr = cm.CM_Query_And_Remove_SubTreeW(node, ctypes.byref(veto), name, 260, 2)       # CM_REMOVE_NO_RESTART
        if cr == 0 and veto.value == 0: return True, 'đã gỡ thiết bị'
        last = f'CR={cr} veto={veto.value} {name.value}'.strip()
    return False, 'Windows từ chối: ' + last


def _cm_disable_parent(disk):
    import ctypes
    from ctypes import wintypes
    cm = ctypes.windll.cfgmgr32
    cm.CM_Disable_DevNode.argtypes = [wintypes.DWORD, wintypes.ULONG]
    chain = _devinst_chain(disk)[1:]                                                       # bỏ chính đĩa, thử thiết bị cha
    if not chain: return False, 'không tìm thấy thiết bị cha'
    res = []
    for node in chain:
        cr = cm.CM_Disable_DevNode(node, 0); res.append(f'CR={cr}')
        if cr == 0: return True, 'đã vô hiệu hóa thiết bị'
    return False, 'không vô hiệu hóa được: ' + ' '.join(res)


def _ps(cmd, t=40):
    r = _run(['powershell', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', cmd], t)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def _set_offline(disk):
    try:
        ok, out = _ps(f'Set-Disk -Number {int(disk)} -IsOffline $true -ErrorAction Stop')
        return ok, out[:200] or 'ok'
    except Exception as ex:
        return False, str(ex)


def _is_offline(disk):
    try:
        ok, out = _ps(f'(Get-Disk -Number {int(disk)}).IsOffline')
        return ok and out.strip().lower() == 'true'
    except Exception:
        return False


def _ioctl_eject(letter):
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    h, err = _open_dev('\\\\.\\' + letter, 0xC0000000)
    if h is None: return False, f'không mở được ổ (mã lỗi {err})'
    ret = wintypes.DWORD(0)
    def ctl(code, buf=None, n=0):
        return bool(k.DeviceIoControl(h, code, buf, n, None, 0, ctypes.byref(ret), None))
    try:
        locked = False
        for _ in range(4):
            if ctl(0x00090018): locked = True; break                                # FSCTL_LOCK_VOLUME (bỏ qua nếu thất bại — đang ép)
            time.sleep(0.5)
        if not ctl(0x00090020): return False, 'dismount bị từ chối'                  # FSCTL_DISMOUNT_VOLUME
        ctl(0x002D4804, (ctypes.c_ubyte * 4)(0, 0, 0, 0), 4)                        # PREVENT_MEDIA_REMOVAL = FALSE
        ctl(0x002D4808)                                                              # IOCTL_STORAGE_EJECT_MEDIA
        return True, 'đã ngắt volume' + ('' if locked else ' (ép, có file đang mở)')
    finally:
        k.CloseHandle(h)
