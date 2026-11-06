"""Cập nhật tự động qua GitHub Releases."""
import json, os, re, sys, shutil, subprocess, tempfile, zipfile, urllib.request, urllib.error
from version import APP_VERSION, GITHUB_REPO

UA = {'User-Agent': 'MyMovieLibrary-Updater', 'Accept': 'application/vnd.github+json'}
FROZEN = getattr(sys, 'frozen', False)
SOURCE_FILES = ('app.py', 'library.py', 'scanner.py', 'drives.py', 'updater.py', 'version.py')

def vtuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', v or '')[:4]) or (0,)

def is_newer(remote, local=APP_VERSION):
    a, b = vtuple(remote), vtuple(local); n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))

def latest_release(timeout=12):
    """Trả về dict {tag, version, notes, page, exe_url, zip_url, size} hoặc None nếu repo chưa có release."""
    req = urllib.request.Request(f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest', headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: d = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404: return None
        raise
    exe = next((a for a in d.get('assets', []) if a['name'].lower().endswith('.exe')), None)
    return {'tag': d.get('tag_name', ''), 'version': d.get('tag_name', '').lstrip('vV'), 'notes': d.get('body') or '',
            'page': d.get('html_url', ''), 'exe_url': exe and exe['browser_download_url'], 'size': exe and exe.get('size', 0),
            'zip_url': d.get('zipball_url')}

def download(url, dest, cb=None, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA['User-Agent']})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0); got = 0
        while True:
            b = r.read(1 << 16)
            if not b: break
            f.write(b); got += len(b)
            if cb: cb(got, total)

def apply_exe_update(new_exe, app_dir):
    """Ghi file .bat: đợi tool thoát -> thay file .exe -> mở lại. Gọi xong thì app phải thoát."""
    cur = sys.executable
    bat = os.path.join(tempfile.gettempdir(), 'mml_update.bat')
    with open(bat, 'w', encoding='mbcs', errors='replace') as f:
        f.write('@echo off\r\nset n=0\r\n:retry\r\ntimeout /t 1 /nobreak >nul\r\n'
                f'move /y "{new_exe}" "{cur}" >nul 2>&1\r\n'
                'if errorlevel 1 (set /a n+=1 & if %n% lss 15 goto retry)\r\n'
                f'start "" "{cur}"\r\ndel "%~f0"\r\n')
    subprocess.Popen(['cmd', '/c', bat], creationflags=0x08000008, close_fds=True)   # DETACHED | NO_WINDOW

def apply_source_update(zip_path, app_dir):
    """Chạy bằng Python: chép các file .py mới đè lên thư mục tool. Trả về danh sách file đã cập nhật."""
    done = []
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            base = os.path.basename(n)
            if base in SOURCE_FILES and n.count('/') == 1:
                with z.open(n) as s, open(os.path.join(app_dir, base), 'wb') as d: shutil.copyfileobj(s, d)
                done.append(base)
    return done
