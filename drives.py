"""Liệt kê ổ đĩa đang cắm (Windows: nhãn ổ, serial, dung lượng) + tiện ích định dạng."""
import os, sys, shutil


def fmt_size(n):
    n = float(n or 0)
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or u == 'TB':
            return f'{int(n)} {u}' if u == 'B' else f'{n:.1f} {u}' if n < 100 else f'{n:.0f} {u}'
        n /= 1024


def list_drives():
    """[{letter, root, label, serial, fs, type, total, free, system}] — chỉ ổ cố định / rời / mạng."""
    if sys.platform == 'win32':
        return _list_windows()
    return _list_posix()


def _list_windows():
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    sysdrive = os.environ.get('SystemDrive', 'C:').upper()
    names = {2: 'Ổ rời (USB)', 3: 'Ổ cứng', 4: 'Ổ mạng'}
    out = []
    old = k.SetErrorMode(1)                       # SEM_FAILCRITICALERRORS: không hiện hộp thoại "No disk"
    try:
        mask = k.GetLogicalDrives()
        for i in range(26):
            if not mask & (1 << i): continue
            letter = chr(65 + i) + ':'; root = letter + '\\'
            t = k.GetDriveTypeW(root)
            if t not in names: continue
            label = ctypes.create_unicode_buffer(261); fs = ctypes.create_unicode_buffer(261)
            serial = wintypes.DWORD(0)
            ok = k.GetVolumeInformationW(root, label, 261, ctypes.byref(serial), None, None, fs, 261)
            try: total, _used, free = shutil.disk_usage(root)
            except OSError: total = free = 0
            if not ok and not total: continue
            out.append({'letter': letter, 'root': root, 'label': label.value, 'serial': f'{serial.value:08X}' if ok else '',
                        'fs': fs.value, 'type': names[t], 'total': total, 'free': free, 'system': letter.upper() == sysdrive})
    finally:
        k.SetErrorMode(old)
    return out


def _list_posix():
    out = []; seen = set()
    try:
        with open('/proc/mounts', encoding='utf8', errors='ignore') as f:
            for line in f:
                p = line.split()
                if len(p) < 3: continue
                mp = p[1].replace('\\040', ' ')
                if not mp.startswith(('/media/', '/mnt/', '/run/media/')) or mp in seen: continue
                seen.add(mp)
                try: total, _u, free = shutil.disk_usage(mp)
                except OSError: continue
                out.append({'letter': mp, 'root': mp, 'label': os.path.basename(mp), 'serial': '', 'fs': p[2],
                            'type': 'Ổ đĩa', 'total': total, 'free': free, 'system': False})
    except OSError:
        pass
    return out


def find_by_serial(drives, serial):
    return next((d for d in drives if serial and d['serial'] == serial), None)
