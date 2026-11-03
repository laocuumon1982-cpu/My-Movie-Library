import sqlite3, unicodedata, re, subprocess, shutil, sys
from parse_kdp import ext

def norm(s):
    s = unicodedata.normalize('NFD', (s or '').replace('đ', 'd').replace('Đ', 'D'))
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'[\._\-\[\]\(\)]+', ' ', s.lower()).strip()

def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]

def category(path):
    p = path.upper()
    if 'AUDIO' in p: return 'Audio'
    if 'ANIME' in p: return 'Anime'
    if 'SERIES' in p or 'TV ' in p: return 'Series'
    if 'GAME' in p: return 'Game'
    return 'Phim'

SCHEMA = """
CREATE TABLE IF NOT EXISTS hdd(serial TEXT PRIMARY KEY, label TEXT, computer TEXT, drive TEXT);
CREATE TABLE IF NOT EXISTS folder(id INTEGER PRIMARY KEY, serial TEXT, path TEXT, name TEXT, name_norm TEXT,
  category TEXT, nfiles INTEGER DEFAULT 0, UNIQUE(serial, path));
CREATE TABLE IF NOT EXISTS file(id INTEGER PRIMARY KEY, folder_id INTEGER, name TEXT, name_norm TEXT, ext TEXT,
  UNIQUE(folder_id, name));
CREATE INDEX IF NOT EXISTS ix_file_folder ON file(folder_id);
"""

def connect(path=':memory:'):
    """Dữ liệu nằm trong RAM: mở tool = trống, thoát tool = tự mất."""
    con = sqlite3.connect(path, check_same_thread=False); con.row_factory = sqlite3.Row
    con.executescript(SCHEMA); return con

def wipe_all(con):
    con.execute("DELETE FROM file"); con.execute("DELETE FROM folder"); con.execute("DELETE FROM hdd"); con.commit()

def add_folder(con, serial, path):
    name = path.rstrip('\\/').replace('/', '\\').split('\\')[-1] or path
    con.execute("INSERT OR IGNORE INTO folder(serial,path,name,name_norm,category) VALUES(?,?,?,?,?)",
                (serial, path, name, norm(name), category(path)))
    return con.execute("SELECT id FROM folder WHERE serial=? AND path=?", (serial, path)).fetchone()[0]

def import_parsed(con, hdds, folders, files):
    for h in hdds.values():
        con.execute("INSERT OR REPLACE INTO hdd(serial,label,computer,drive) VALUES(?,?,?,?)",
                    (h['serial'], h['label'], h['computer'], h['drive']))
    ids = {}
    for serial, path in folders: ids[(serial, path)] = add_folder(con, serial, path)
    for serial, fo, name in files:
        fid = ids.get((serial, fo))
        if fid is None: fid = ids[(serial, fo)] = add_folder(con, serial, fo)
        con.execute("INSERT OR IGNORE INTO file(folder_id,name,name_norm,ext) VALUES(?,?,?,?)",
                    (fid, name, norm(name), ext(name)))
    con.execute("UPDATE folder SET nfiles=(SELECT COUNT(*) FROM file WHERE folder_id=folder.id)")
    con.commit()

def load_parsed(con, stem, parsed):
    """1 file PDF = 1 HDD, tên HDD = tên file PDF. PDF chứa nhiều ổ thì tách theo nhãn ổ. Trả về số HDD nạp được."""
    hdds, folders, files = parsed
    if not hdds: return 0
    multi = len(hdds) > 1
    key = {s: (f'{stem}|{s}' if multi else stem) for s in hdds}
    new_h = {key[s]: {'serial': key[s], 'label': h['label'] if multi else stem,
                      'computer': h['computer'], 'drive': h['drive']} for s, h in hdds.items()}
    import_parsed(con, new_h, [(key[s], p) for s, p in folders if s in key],
                  [(key[s], p, n) for s, p, n in files if s in key])
    return len(hdds)

FROZEN = getattr(sys, 'frozen', False)

def read_pdf_text(path):
    """pdftotext (nếu có) -> pypdf. Bản .exe đã đóng gói sẵn pypdf; chạy bằng Python mà thiếu thì tự pip install."""
    if shutil.which('pdftotext'):
        r = subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, encoding='utf8', errors='ignore',
                           creationflags=0x08000000 if sys.platform == 'win32' else 0)
        if r.stdout.strip(): return r.stdout
    try:
        from pypdf import PdfReader
    except ImportError:
        if FROZEN: raise RuntimeError('Thiếu thư viện pypdf trong bản .exe (hãy tải bản mới nhất bằng nút Update).')
        p = subprocess.run([sys.executable, '-m', 'pip', 'install', '--user', 'pypdf'], capture_output=True,
                           encoding='utf8', errors='ignore', creationflags=0x08000000 if sys.platform == 'win32' else 0)
        try:
            import importlib; importlib.invalidate_caches(); from pypdf import PdfReader
        except ImportError:
            raise RuntimeError('Chưa có thư viện pypdf và không tự cài được (cần Internet).\nMở CMD, chạy: pip install pypdf\n' + (p.stderr or '')[-300:])
    text = '\n'.join((pg.extract_text() or '') for pg in PdfReader(path).pages)
    return re.sub(r'[ \t]{2,}', ' ', text)
