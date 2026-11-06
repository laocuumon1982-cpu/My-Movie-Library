"""Thư viện SQLite: ổ HDD -> thư mục -> file, mã số và truy vấn tìm kiếm."""
import os, re, sqlite3, unicodedata
from datetime import datetime

VIDEO = {'.mkv', '.mp4', '.avi', '.ts', '.m4v', '.mov', '.wmv', '.mpg', '.mpeg', '.m2ts', '.iso', '.flv', '.webm', '.vob',
         '.rmvb', '.3gp', '.divx', '.bdmv'}
AUDIO = {'.mp3', '.flac', '.wav', '.aac', '.m4a', '.ogg', '.wma', '.ape', '.opus', '.mka', '.ac3', '.dts'}
SUB = {'.srt', '.ass', '.ssa', '.sub', '.idx', '.vtt', '.sup'}
IMAGE = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tif', '.tiff'}
KINDS = {'video': 'Video', 'audio': 'Audio', 'sub': 'Phụ đề', 'image': 'Ảnh', 'other': 'Khác'}


def kind_of(ext):
    return 'video' if ext in VIDEO else 'audio' if ext in AUDIO else 'sub' if ext in SUB else 'image' if ext in IMAGE else 'other'


def norm(s):
    """Bỏ dấu tiếng Việt, hạ chữ thường, đổi . _ - [ ] ( ) thành khoảng trắng — để tìm không dấu."""
    s = unicodedata.normalize('NFD', (s or '').replace('đ', 'd').replace('Đ', 'D'))
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', re.sub(r'[\._\-\[\]\(\)\{\}]+', ' ', s.lower())).strip()


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


SCHEMA = """
CREATE TABLE IF NOT EXISTS hdd(id INTEGER PRIMARY KEY, seq INTEGER, code TEXT UNIQUE, ident TEXT UNIQUE, name TEXT, label TEXT,
  serial TEXT, root TEXT, fs TEXT, total INTEGER DEFAULT 0, free INTEGER DEFAULT 0, nfolders INTEGER DEFAULT 0,
  nfiles INTEGER DEFAULT 0, bytes INTEGER DEFAULT 0, scanned_at TEXT);
CREATE TABLE IF NOT EXISTS folder(id INTEGER PRIMARY KEY, hdd_id INTEGER, code TEXT, parent_id INTEGER, name TEXT,
  name_norm TEXT, path TEXT, path_norm TEXT, depth INTEGER, nfiles INTEGER DEFAULT 0, bytes INTEGER DEFAULT 0,
  tfiles INTEGER DEFAULT 0, tbytes INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS file(id INTEGER PRIMARY KEY, hdd_id INTEGER, folder_id INTEGER, code TEXT, name TEXT,
  name_norm TEXT, ext TEXT, kind TEXT, size INTEGER, mtime INTEGER);
CREATE INDEX IF NOT EXISTS ix_folder_hdd ON folder(hdd_id);
CREATE INDEX IF NOT EXISTS ix_folder_parent ON folder(parent_id);
CREATE INDEX IF NOT EXISTS ix_folder_code ON folder(code);
CREATE INDEX IF NOT EXISTS ix_file_hdd ON file(hdd_id);
CREATE INDEX IF NOT EXISTS ix_file_folder ON file(folder_id);
CREATE INDEX IF NOT EXISTS ix_file_code ON file(code);
CREATE INDEX IF NOT EXISTS ix_file_kind ON file(kind);
"""


def connect(path):
    con = sqlite3.connect(path, timeout=30, check_same_thread=False); con.row_factory = sqlite3.Row
    try: con.execute('PRAGMA journal_mode=WAL')
    except sqlite3.DatabaseError: pass
    con.execute('PRAGMA synchronous=NORMAL')
    con.executescript(SCHEMA); return con


def scalar(con, sql, a=()):
    return con.execute(sql, a).fetchone()[0]


# ---------------------------------------------------------------- ổ HDD
def list_hdds(con):
    return con.execute("SELECT * FROM hdd ORDER BY seq").fetchall()


def next_hdd_seq(con):
    return (scalar(con, "SELECT COALESCE(MAX(seq),0) FROM hdd") or 0) + 1


def hdd_code(seq):
    return f'H{seq:02d}'


def rename_hdd(con, hid, name, code):
    code = re.sub(r'[^A-Za-z0-9]', '', code or '').upper()[:6]
    if not code: raise ValueError('Mã ổ chỉ gồm chữ và số (tối đa 6 ký tự).')
    old = scalar(con, "SELECT code FROM hdd WHERE id=?", (hid,))
    if code != old:
        if scalar(con, "SELECT COUNT(*) FROM hdd WHERE code=? AND id<>?", (code, hid)):
            raise ValueError(f'Mã {code} đã dùng cho ổ khác.')
        n = len(old) + 1
        con.execute("UPDATE file SET code=? || substr(code, ?) WHERE hdd_id=?", (code, n, hid))
        con.execute("UPDATE folder SET code=? || substr(code, ?) WHERE hdd_id=?", (code, n, hid))
    con.execute("UPDATE hdd SET name=?, code=? WHERE id=?", (name.strip() or code, code, hid)); con.commit()


def delete_hdd(con, hid):
    con.execute("DELETE FROM file WHERE hdd_id=?", (hid,)); con.execute("DELETE FROM folder WHERE hdd_id=?", (hid,))
    con.execute("DELETE FROM hdd WHERE id=?", (hid,)); con.commit()


def wipe_all(con):
    for t in ('file', 'folder', 'hdd'): con.execute(f"DELETE FROM {t}")
    con.commit(); con.execute("VACUUM")


def totals(con):
    r = con.execute("SELECT COUNT(*) h, COALESCE(SUM(nfolders),0) d, COALESCE(SUM(nfiles),0) f, COALESCE(SUM(bytes),0) b FROM hdd").fetchone()
    return dict(hdd=r['h'], folders=r['d'], files=r['f'], bytes=r['b'])


# ---------------------------------------------------------------- tìm kiếm
_SIZE = re.compile(r'^(?:size)?([<>])(\d+(?:[.,]\d+)?)(b|kb|mb|gb|tb)?$')
_UNIT = {'b': 1, 'kb': 1 << 10, 'mb': 1 << 20, 'gb': 1 << 30, 'tb': 1 << 40, None: 1 << 20}
_FCODE = re.compile(r'^([a-z0-9]{1,6})-(\d{1,6})$')
_DCODE = re.compile(r'^([a-z0-9]{1,6})-d(\d{0,5})$')
_HCODE = re.compile(r'^([a-z0-9]{1,6})-$')


def _like(s):
    return '%' + s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def parse_query(text):
    """Cú pháp: từ khoá (không dấu) | ext:mkv,mp4 | hdd:H01 | kind:video | >1gb <500mb | mã H01-000123 / H01-D00012 / H01-"""
    q = dict(words=[], exts=[], hdds=[], kinds=[], min=None, max=None, fcode=None, dcode=None, hprefix=None)
    toks = re.findall(r'"([^"]+)"|(\S+)', text or '')
    for quoted, tok in toks:
        if quoted:
            q['words'].append(norm(quoted)); continue
        low = tok.lower()
        if low.startswith('ext:'):
            q['exts'] += ['.' + e.strip('. ') for e in low[4:].split(',') if e.strip('. ')]
        elif low.startswith('hdd:'):
            q['hdds'] += [h.upper() for h in low[4:].split(',') if h]
        elif low.startswith('kind:'):
            q['kinds'] += [k for k in low[5:].split(',') if k in KINDS]
        elif _SIZE.match(low):
            op, num, unit = _SIZE.match(low).groups()
            v = int(float(num.replace(',', '.')) * _UNIT[unit])
            q['min' if op == '>' else 'max'] = v
        elif _DCODE.match(low):
            q['dcode'] = low.upper()
        elif _FCODE.match(low):
            q['fcode'] = low.upper()
        elif _HCODE.match(low):
            q['hprefix'] = low.upper()
        elif norm(tok):
            q['words'].append(norm(tok))
    return q


def _code_clause(col, token, full_len):
    return (f"{col} = ?", [token]) if len(token) >= full_len else (f"{col} LIKE ?", [token + '%'])


def _filters(q, kind, hid, for_folders=False):
    """Trả về (sql_điều_kiện, tham_số) trên các bí danh f (file), fo (folder), h (hdd)."""
    w, a = [], []
    if hid: w.append("h.id=?"); a.append(hid)
    for word in q['words']:
        if for_folders:
            w.append("(fo.path_norm LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM file x WHERE x.folder_id=fo.id AND x.name_norm LIKE ? ESCAPE '\\'))")
            a += [_like(word), _like(word)]
        else:
            w.append("(f.name_norm LIKE ? ESCAPE '\\' OR fo.path_norm LIKE ? ESCAPE '\\')"); a += [_like(word), _like(word)]
    if q['hdds']:
        w.append('(' + ' OR '.join('h.code=?' for _ in q['hdds']) + ')'); a += q['hdds']
    if q['hprefix']: w.append("fo.code LIKE ?"); a.append(q['hprefix'] + '%')
    if q['dcode']:
        c, p = _code_clause('fo.code', q['dcode'], len(q['dcode'].split('-')[0]) + 7); w.append(c); a += p
    if for_folders:
        if q['fcode']: w.append("0")
        if q['exts']:
            w.append('EXISTS (SELECT 1 FROM file x WHERE x.folder_id=fo.id AND (' + ' OR '.join('x.ext=?' for _ in q['exts']) + '))'); a += q['exts']
        return w, a
    if q['fcode']:
        c, p = _code_clause('f.code', q['fcode'], len(q['fcode'].split('-')[0]) + 7); w.append(c); a += p
    if q['exts']: w.append('(' + ' OR '.join('f.ext=?' for _ in q['exts']) + ')'); a += q['exts']
    kinds = list(q['kinds'])
    if kind and kind in KINDS: kinds.append(kind)
    if kinds: w.append('(' + ' OR '.join('f.kind=?' for _ in kinds) + ')'); a += kinds
    if q['min'] is not None: w.append("f.size>=?"); a.append(q['min'])
    if q['max'] is not None: w.append("f.size<=?"); a.append(q['max'])
    return w, a


FILE_FROM = " FROM file f JOIN folder fo ON fo.id=f.folder_id JOIN hdd h ON h.id=f.hdd_id"
FILE_ORDER = {'code': 'f.code', 'ext': 'f.ext', 'name': 'f.name_norm', 'folder': 'fo.path_norm', 'hdd': 'h.seq', 'size': 'f.size',
              'mtime': 'f.mtime', 'kind': 'f.kind'}


def search_files(con, text, kind=None, hid=None, sort='code', desc=False, limit=5000):
    q = parse_query(text); w, a = _filters(q, kind, hid)
    where = (' WHERE ' + ' AND '.join(w)) if w else ''
    total = scalar(con, "SELECT COUNT(*)" + FILE_FROM + where, a)
    sql = ("SELECT f.id,f.code,f.name,f.ext,f.kind,f.size,f.mtime,fo.id fid,fo.code fcode,fo.path,h.id hid,h.code hcode,h.name hname"
           + FILE_FROM + where + f" ORDER BY {FILE_ORDER.get(sort, 'f.code')} {'DESC' if desc else 'ASC'}, f.id")
    if limit: sql += f" LIMIT {int(limit)}"
    return total, con.execute(sql, a).fetchall()


FOLDER_FROM = " FROM folder fo JOIN hdd h ON h.id=fo.hdd_id"
FOLDER_ORDER = {'code': 'fo.code', 'name': 'fo.name_norm', 'hdd': 'h.seq', 'path': 'fo.path_norm', 'files': 'fo.nfiles', 'size': 'fo.bytes'}


def search_folders(con, text, hid=None, sort='code', desc=False, limit=5000):
    """Thư mục có file trực tiếp bên trong (thường là thư mục từng phim)."""
    q = parse_query(text); w, a = _filters(q, None, hid, for_folders=True)
    w.insert(0, "fo.nfiles>0"); where = ' WHERE ' + ' AND '.join(w)
    total = scalar(con, "SELECT COUNT(*)" + FOLDER_FROM + where, a)
    sql = ("SELECT fo.id,fo.code,fo.name,fo.path,fo.nfiles,fo.bytes,h.id hid,h.code hcode,h.name hname" + FOLDER_FROM + where +
           f" ORDER BY {FOLDER_ORDER.get(sort, 'fo.code')} {'DESC' if desc else 'ASC'}, fo.id")
    if limit: sql += f" LIMIT {int(limit)}"
    return total, con.execute(sql, a).fetchall()


# ---------------------------------------------------------------- cây thư mục
def root_folder(con, hid):
    r = con.execute("SELECT id FROM folder WHERE hdd_id=? AND parent_id IS NULL", (hid,)).fetchone()
    return r[0] if r else None


def child_folders(con, parent_id):
    rows = con.execute("SELECT id,code,name,path,tfiles,tbytes FROM folder WHERE parent_id=?", (parent_id,)).fetchall()
    return sorted(rows, key=lambda r: natural_key(r['name']))


def folder_files(con, folder_id, limit=3000):
    rows = con.execute("SELECT id,code,name,size,mtime FROM file WHERE folder_id=? LIMIT ?", (folder_id, limit)).fetchall()
    return sorted(rows, key=lambda r: natural_key(r['name']))


def fmt_time(ts):
    try: return datetime.fromtimestamp(ts).strftime('%d/%m/%Y %H:%M') if ts else ''
    except (OSError, OverflowError, ValueError): return ''


def full_path(root, rel, name=None):
    """Ghép đường dẫn thật: gốc ổ + đường dẫn tương đối (lưu dạng a\\b\\c) + tên file."""
    parts = [p for p in (rel or '').split('\\') if p]
    if name: parts.append(name)
    return os.path.join(root, *parts) if parts else root


def file_row(con, fid):
    return con.execute("SELECT f.id,f.code,f.name,f.ext,f.kind,f.size,f.mtime,fo.id fid,fo.code fcode,fo.path,h.id hid,h.code hcode,h.name hname"
                       + FILE_FROM + " WHERE f.id=?", (fid,)).fetchone()


def folder_row(con, did):
    return con.execute("SELECT fo.id,fo.code,fo.name,fo.path,fo.nfiles,fo.tfiles,fo.bytes,fo.tbytes,fo.parent_id,h.id hid,h.code hcode,h.name hname"
                       + FOLDER_FROM + " WHERE fo.id=?", (did,)).fetchone()


def hdd_row(con, hid):
    return con.execute("SELECT * FROM hdd WHERE id=?", (hid,)).fetchone()
