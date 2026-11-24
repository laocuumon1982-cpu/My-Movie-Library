"""My Movie Library — giao diện web (pywebview / Edge WebView2) theo phong cách PikPak Auto Save.
Lõi (quét, thư viện, tìm kiếm, PikPak, tháo ổ) dùng lại nguyên vẹn: library.py, scanner.py, drives.py, postscan.py, updater.py.
Mở bằng app.py (tự gọi run_web) hoặc:  python webapp.py [--serve]  (--serve: mở bằng trình duyệt, dùng để thử)."""
import os, sys, csv, json, time, shutil, sqlite3, threading, subprocess, tempfile, webbrowser
from pathlib import Path
import library as L, scanner, drives, updater, postscan
from drives import fmt_size
from version import APP_TITLE, APP_NAME, APP_VERSION, APP_AUTHOR, GITHUB_REPO
from app import DATA_DIR, DB_PATH, APP_DIR, FROZEN, RES_DIR, load_settings, save_settings

LOG_MAX = 400


def web_dir():
    for base in (Path(__file__).resolve().parent, Path(RES_DIR), Path(APP_DIR)):
        p = base / 'web' / 'index.html'
        if p.is_file(): return p.parent
    raise FileNotFoundError("Không thấy thư mục giao diện 'web' (web/index.html)")


def page_html():
    d = web_dir()
    html = (d / 'index.html').read_text(encoding='utf-8')
    css = (d / 'style.css').read_text(encoding='utf-8'); js = (d / 'app.js').read_text(encoding='utf-8')
    html = html.replace('<link rel="stylesheet" href="style.css">', '<style>\n' + css + '\n</style>')
    return html.replace('<script src="app.js"></script>', '<script>\n' + js.replace('</script', '<\\/script') + '\n</script>')


def _d(r):
    return {k: r[k] for k in r.keys()}


class Engine:
    """Trạng thái dùng chung: cài đặt, luồng quét, ổ đang cắm, cập nhật."""

    def __init__(self):
        self.settings = load_settings()
        self.drives = []; self.drives_t = 0
        self.scan = dict(running=False, phase='idle', name='', files=0, folders=0, bytes=0, cur='', est=0, pct=0, bk=0, ej=0, log=[], result=None)
        self.cancel = threading.Event()
        self.rc = dict(busy=False, msg='', err='')
        self.upd = dict(rel=None, newer=False, busy=False, pct=0, msg='', err='')
        self.ui = None; self.quit_fn = None
        threading.Thread(target=self._drive_loop, daemon=True).start()

    def db(self):
        return L.connect(DB_PATH)

    def _drive_loop(self):
        while True:
            try: self.drives = drives.list_drives(); self.drives_t = time.time()
            except Exception: pass
            time.sleep(5)

    def log(self, text):
        s = self.scan; s['log'].append(time.strftime('%H:%M:%S') + '  ' + text)
        if len(s['log']) > LOG_MAX: del s['log'][:50]; s['base'] = s.get('base', 0) + 50

    def root_for(self, h):
        if h['serial']:
            d = drives.find_by_serial(self.drives, h['serial'])
            return d['root'] if d else None
        return h['root'] if os.path.isdir(h['root']) else None


class Api:
    def __init__(self, eng):
        self._e = eng

    # ------------------------------------------------------------------ chung
    def init(self):
        e = self._e
        return dict(version=APP_VERSION, title=APP_TITLE, repo=GITHUB_REPO, author=APP_AUTHOR, theme=e.settings.get('theme', 'light'),
                    data_dir=DATA_DIR, db=DB_PATH, frozen=FROZEN, backup_on=e.settings.get('backup_on', True),
                    eject_on=e.settings.get('eject_on', True), media_only=e.settings.get('media_only', False),
                    pikpak_user=e.settings.get('pikpak_user', ''), backup_path=f'{postscan.REMOTE}:{postscan.BACKUP_DIR}/{postscan.BACKUP_NAME}')

    def set_setting(self, key, value):
        if key in ('theme', 'backup_on', 'eject_on', 'media_only', 'pikpak_user'):
            self._e.settings[key] = value; save_settings(self._e.settings)
        return True

    def overview(self):
        """Số liệu tổng + danh sách ổ HDD (kèm trạng thái đang cắm)."""
        e = self._e; con = e.db()
        try:
            t = L.totals(con); out = []
            for h in L.list_hdds(con):
                root = e.root_for(h); r = _d(h)
                r.update(online=bool(root), live_root=root or '', bytes_txt=fmt_size(h['bytes']), time_txt=h['scanned_at'] or '')
                out.append(r)
            t['bytes_txt'] = fmt_size(t['bytes'])
            return dict(totals=t, hdds=out, scanning=e.scan['running'], scan_name=e.scan['name'])
        finally: con.close()

    # ------------------------------------------------------------------ tìm kiếm
    def search_files(self, q, kind, hid, sort, desc, limit=2000):
        con = self._e.db()
        try:
            total, rows = L.search_files(con, q, kind or None, hid or None, sort, bool(desc), limit)
            return dict(total=total, rows=[[r['id'], r['code'], r['name'], r['ext'], r['kind'], fmt_size(r['size']), L.fmt_time(r['mtime']),
                                            r['hcode'], r['fcode'], r['path'], r['hname']] for r in rows])
        finally: con.close()

    def search_folders(self, q, hid, sort, desc, limit=2000):
        con = self._e.db()
        try:
            total, rows = L.search_folders(con, q, hid or None, sort, bool(desc), limit)
            return dict(total=total, rows=[[r['id'], r['code'], r['name'], r['hcode'], r['path'], r['nfiles'], fmt_size(r['bytes']), r['hname']] for r in rows])
        finally: con.close()

    def item(self, kind, iid):
        """Chi tiết 1 file / thư mục: đường dẫn trong ổ + đường dẫn thật nếu ổ đang cắm."""
        e = self._e; con = e.db()
        try:
            r = L.file_row(con, iid) if kind == 'file' else L.folder_row(con, iid)
            if not r: return None
            h = L.hdd_row(con, r['hid']); root = e.root_for(h)
            rel = r['path']; name = r['name'] if kind == 'file' else None
            real = L.full_path(root, rel, name) if root else ''
            shown = (h['name'] + '  ›  ' if h else '') + ('\\' + rel if rel else '') + (('\\' if rel else '\\') + name if name and kind == 'file' else '')
            if kind == 'folder' and not rel: shown = h['name'] + '  ›  (gốc ổ)'
            out = dict(kind=kind, id=r['id'], code=r['code'], name=r['name'], hcode=r['hcode'], hname=r['hname'], hid=r['hid'], path=shown,
                       online=bool(root), real=real, exists=bool(real and os.path.exists(real)))
            if kind == 'file': out.update(fcode=r['fcode'], fid=r['fid'], size=fmt_size(r['size']), mtime=L.fmt_time(r['mtime']), ext=r['ext'])
            else: out.update(nfiles=r['nfiles'], tfiles=r['tfiles'], size=fmt_size(r['bytes']), tsize=fmt_size(r['tbytes']))
            return out
        finally: con.close()

    def open_item(self, kind, iid):
        it = self.item(kind, iid)
        if not it: return dict(ok=False, msg='Không tìm thấy.')
        if not it['online']: return dict(ok=False, msg=f"Ổ {it['hcode']} chưa cắm vào máy.")
        if not it['exists']: return dict(ok=False, msg='File / thư mục không còn ở vị trí này (có thể đã bị di chuyển).')
        p = it['real']
        try:
            if sys.platform == 'win32':
                if os.path.isfile(p): subprocess.Popen(['explorer', '/select,' + p])
                else: os.startfile(p)
            else: subprocess.Popen(['xdg-open', p if os.path.isdir(p) else os.path.dirname(p)])
        except Exception as ex: return dict(ok=False, msg=str(ex))
        return dict(ok=True)

    # ------------------------------------------------------------------ cây thư mục
    def tree_roots(self, hid):
        con = self._e.db()
        try:
            out = []
            for h in L.list_hdds(con):
                if hid and h['id'] != hid: continue
                rid = L.root_folder(con, h['id'])
                if rid: out.append(dict(id=rid, name=f"{h['code']} · {h['name']}", code=h['code'], tfiles=h['nfiles'], size=fmt_size(h['bytes']), hdd=True))
            return out
        finally: con.close()

    def tree_children(self, fid):
        con = self._e.db()
        try:
            return [dict(id=r['id'], name=r['name'], code=r['code'], tfiles=r['tfiles'], size=fmt_size(r['tbytes']),
                         leaf=not con.execute('SELECT 1 FROM folder WHERE parent_id=? LIMIT 1', (r['id'],)).fetchone())
                    for r in L.child_folders(con, fid)]
        finally: con.close()

    def tree_files(self, fid):
        con = self._e.db()
        try:
            fo = L.folder_row(con, fid)
            rows = [[r['id'], r['code'], r['name'], fmt_size(r['size']), L.fmt_time(r['mtime'])] for r in L.folder_files(con, fid)]
            return dict(folder=dict(id=fo['id'], code=fo['code'], name=fo['name'], path=fo['path'], tfiles=fo['tfiles'], size=fmt_size(fo['tbytes'])) if fo else None, rows=rows)
        finally: con.close()

    def tree_path(self, fid):
        """Danh sách id từ thư mục gốc của ổ tới thư mục fid (để mở cây tới đúng chỗ)."""
        con = self._e.db()
        try:
            ids = []; cur = fid
            while cur:
                ids.append(cur); r = con.execute('SELECT parent_id FROM folder WHERE id=?', (cur,)).fetchone(); cur = r[0] if r else None
            return ids[::-1]
        finally: con.close()

    # ------------------------------------------------------------------ quản lý ổ / thư viện
    def edit_hdd(self, hid, name, code):
        con = self._e.db()
        try: L.rename_hdd(con, hid, name, code); return dict(ok=True)
        except ValueError as ex: return dict(ok=False, msg=str(ex))
        finally: con.close()

    def delete_hdd(self, hid):
        con = self._e.db()
        try: L.delete_hdd(con, hid); return True
        finally: con.close()

    def wipe(self):
        con = self._e.db()
        try: L.wipe_all(con); return True
        finally: con.close()

    def export_csv(self, tab, q, kind, hid, sort, desc):
        con = self._e.db()
        try:
            if tab == 'folders':
                total, rows = L.search_folders(con, q, hid or None, sort, bool(desc), None)
                head = ['Mã thư mục', 'Tên thư mục', 'Mã ổ', 'Tên ổ', 'Đường dẫn trong ổ', 'Số file', 'Dung lượng (byte)']
                data = [[r['code'], r['name'], r['hcode'], r['hname'], '\\' + r['path'], r['nfiles'], r['bytes']] for r in rows]
            else:
                total, rows = L.search_files(con, q, kind or None, hid or None, sort, bool(desc), None)
                head = ['Mã file', 'Tên file', 'Đuôi', 'Loại', 'Dung lượng (byte)', 'Dung lượng', 'Ngày sửa', 'Mã thư mục', 'Mã ổ', 'Tên ổ', 'Đường dẫn trong ổ']
                data = [[r['code'], r['name'], r['ext'], L.KINDS.get(r['kind'], ''), r['size'], fmt_size(r['size']), L.fmt_time(r['mtime']), r['fcode'],
                         r['hcode'], r['hname'], '\\' + (r['path'] + '\\' if r['path'] else '') + r['name']] for r in rows]
        finally: con.close()
        if not data: return dict(ok=False, msg='Không có dữ liệu để xuất.')
        p = self._e.ui.save('thu_vien_phim.csv', 'CSV (*.csv)') if self._e.ui else ''
        if not p: return dict(ok=False, msg='')
        with open(p, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f); w.writerow(head); w.writerows(data)
        return dict(ok=True, msg=f'Đã xuất {len(data):,} dòng:\n{p}')

    def backup_file(self):
        p = self._e.ui.save(f"MyMovieLibrary_{time.strftime('%Y%m%d')}.db", 'Thư viện (*.db)') if self._e.ui else ''
        if not p: return dict(ok=False, msg='')
        src = sqlite3.connect(DB_PATH); dst = sqlite3.connect(p)
        try: src.backup(dst)
        finally: dst.close(); src.close()
        return dict(ok=True, msg=f'Đã sao lưu thư viện:\n{p}')

    def restore_file(self):
        p = self._e.ui.open('Thư viện (*.db)') if self._e.ui else ''
        if not p: return dict(ok=False, msg='')
        try:
            s = sqlite3.connect(p); s.execute('SELECT COUNT(*) FROM hdd'); s.execute('SELECT COUNT(*) FROM file'); s.execute('SELECT COUNT(*) FROM folder')
        except sqlite3.DatabaseError:
            return dict(ok=False, msg='File này không phải bản sao lưu của My Movie Library.')
        con = self._e.db()
        try: s.backup(con); con.executescript(L.SCHEMA); con.commit()
        finally: s.close(); con.close()
        return dict(ok=True, msg='Đã khôi phục thư viện.')

    def open_data_dir(self):
        try:
            if sys.platform == 'win32': os.startfile(DATA_DIR)
            else: subprocess.Popen(['xdg-open', DATA_DIR])
        except Exception: pass
        return True

    def open_url(self, url):
        if str(url).startswith('https://'): webbrowser.open(url)
        return True

    def pick_folder(self):
        return self._e.ui.folder() if self._e.ui else ''

    # ------------------------------------------------------------------ quét ổ
    def drives(self):
        e = self._e
        con = e.db()
        try:
            known = {h['serial']: h for h in L.list_hdds(con) if h['serial']}
            nxt = L.hdd_code(L.next_hdd_seq(con))
            out = []
            for d in (e.drives or drives.list_drives()):
                k = known.get(d['serial']) if d['serial'] else None
                out.append(dict(letter=d['letter'], root=d['root'], label=d['label'] or '(không nhãn)', type=d['type'], fs=d['fs'], system=d['system'],
                                total=fmt_size(d['total']), free=fmt_size(d['free']), serial=d['serial'],
                                code=k['code'] if k else '', name=k['name'] if k else (d['label'] or d['letter']), hid=k['id'] if k else 0))
            return dict(drives=out, next_code=nxt)
        finally: con.close()

    def target_info(self, root):
        """Thông tin khi chọn thư mục thường (không phải cả ổ)."""
        con = self._e.db()
        try:
            ident = scanner.ident_for(root, '')
            old = con.execute('SELECT id,code,name FROM hdd WHERE ident=?', (ident,)).fetchone()
            return dict(code=old['code'] if old else '', name=old['name'] if old else (os.path.basename(root.rstrip('\\/')) or root),
                        hid=old['id'] if old else 0, next_code=L.hdd_code(L.next_hdd_seq(con)))
        finally: con.close()

    def start_scan(self, root, name, media_only, replace_id=0):
        e = self._e; s = e.scan
        if s['running']: return dict(ok=False, msg='Đang có một lần quét chạy.')
        if not root or not os.path.isdir(root): return dict(ok=False, msg='Không truy cập được ổ / thư mục này.')
        drive = next((d for d in (e.drives or []) if os.path.normcase(d['root'].rstrip('\\/')) == os.path.normcase(root.rstrip('\\/'))), None)
        used = ((drive or {}).get('total', 0) - (drive or {}).get('free', 0)) if drive else 0
        e.cancel.clear()
        s.update(running=True, phase='scan', name=name or root, files=0, folders=0, bytes=0, cur='', est=used, pct=0, bk=0, ej=0, log=[], base=0, result=None)
        e.log(f'▶ Bắt đầu quét: {root}')
        threading.Thread(target=self._scan_thread, args=(root, name, drive, bool(media_only), replace_id or None), daemon=True).start()
        return dict(ok=True)

    def _scan_thread(self, root, name, drive, media_only, replace_id):
        e = self._e; s = e.scan

        def prog(nf, nd, nb, cur):
            s.update(files=nf, folders=nd, bytes=nb, cur=cur)
            if s['est']: s['pct'] = min(99, int(nb * 100 / s['est']))
        try:
            r = scanner.scan_hdd(DB_PATH, root, name, drive, e.cancel, prog, media_only, replace_id)
        except scanner.Cancelled:
            e.log('■ Đã hủy quét — thư viện giữ nguyên như cũ.'); s.update(running=False, phase='cancel'); return
        except Exception as ex:
            e.log(f'✖ Lỗi quét: {ex}'); s.update(running=False, phase='error'); return
        s.update(pct=100, files=r['files'], folders=r['folders'], bytes=r['bytes'], cur='', result=dict(r, bytes_txt=fmt_size(r['bytes'])))
        e.log(f"✔ Quét xong ổ {r['code']} · {r['name']}: {r['files']:,} file • {r['folders']:,} thư mục • {fmt_size(r['bytes'])} • {r['seconds']:.0f} giây"
              + (f" • bỏ qua {r['errors']} mục không đọc được" if r['errors'] else ''))
        if e.settings.get('backup_on', True):
            s.update(phase='backup', bk=10); self._pikpak_backup()
        else: s['bk'] = -1
        if e.settings.get('eject_on', True):
            s.update(phase='eject', ej=10)
            why = postscan.eject_blockers(root, drive, [DATA_DIR, DB_PATH, os.path.abspath(sys.argv[0]), sys.executable])
            if why: e.log(f'⏏ Không tháo ổ: {why}'); s['ej'] = -1
            else:
                try: ok, msg = postscan.eject_drive(drive['letter'], force=True, log=lambda m: e.log('   ⏏ ' + m))
                except Exception as ex: ok, msg = False, str(ex)
                e.log(('⏏ ' if ok else '⏏ KHÔNG tháo được — ') + msg); s['ej'] = 100 if ok else -2
        else: s['ej'] = -1
        s.update(running=False, phase='done')

    def _pikpak_backup(self):
        e = self._e; s = e.scan
        rc = postscan.find_rclone(DATA_DIR)
        if not rc:
            e.log('☁ Chưa có rclone — đang tải về cạnh app…')
            try: rc = postscan.download_rclone(DATA_DIR)
            except Exception as ex: e.log(f'☁ Tải rclone thất bại: {ex}'); s['bk'] = -2; return False
        if not postscan.is_logged_in(rc, DATA_DIR):
            e.log('☁ Bỏ qua sao lưu PikPak — chưa đăng nhập (Cài đặt → PikPak).'); s['bk'] = -2; return False
        try:
            e.log('☁ Đang đẩy Data/library.db lên PikPak…'); s['bk'] = 40
            dest = postscan.backup_db(DB_PATH, DATA_DIR, rc); e.log(f'☁ Đã sao lưu lên PikPak: {dest}'); s['bk'] = 100; return True
        except Exception as ex:
            e.log(f'☁ Sao lưu PikPak THẤT BẠI: {ex}'); s['bk'] = -2; return False

    def eject_hdd(self, hid):
        """Tháo thủ công 1 ổ đã quét (đang cắm): thử tháo an toàn, không được thì tự chuyển sang ép."""
        e = self._e; s = e.scan
        if s['running']: return dict(ok=False, msg='Đang có tác vụ chạy — thử lại sau.')
        con = e.db()
        try: h = L.hdd_row(con, hid)
        finally: con.close()
        root = e.root_for(h) if h else None
        if not root: return dict(ok=False, msg='Ổ này chưa cắm vào máy.')
        drive = next((d for d in (e.drives or []) if os.path.normcase(d['root'].rstrip('\\/')) == os.path.normcase(root.rstrip('\\/'))), None)
        why = postscan.eject_blockers(root, drive, [DATA_DIR, DB_PATH, os.path.abspath(sys.argv[0]), sys.executable]) if drive else 'Không phải ổ đĩa.'
        if why: return dict(ok=False, msg='Không tháo ổ: ' + why)
        s.update(running=True, phase='eject', name=h['name'], log=[], base=0, ej=10, bk=-1, pct=100, files=0, folders=0, bytes=0, cur='', result=None)
        def work():
            e.log(f"⏏ Tháo ổ {h['code']} · {h['name']} ({drive['letter']})")
            try: ok, msg = postscan.eject_drive(drive['letter'], force=True, log=lambda m: e.log('   ⏏ ' + m))
            except Exception as ex: ok, msg = False, str(ex)
            e.log(('⏏ ' if ok else '⏏ KHÔNG tháo được — ') + msg); s['ej'] = 100 if ok else -2; s.update(running=False, phase='done')
        threading.Thread(target=work, daemon=True).start()
        return dict(ok=True)

    def scan_state(self, since=0):
        s = self._e.scan; base = s.get('base', 0)
        lg = s['log']; since = max(0, since - base)
        return dict(running=s['running'], phase=s['phase'], name=s['name'], files=s['files'], folders=s['folders'], bytes=fmt_size(s['bytes']),
                    cur=s['cur'], pct=s['pct'], bk=s['bk'], ej=s['ej'], log=lg[since:], next=base + len(lg), result=s['result'])

    def cancel_scan(self):
        self._e.cancel.set(); return True

    def backup_now(self):
        """Sao lưu library.db lên PikPak ngay (không quét)."""
        e = self._e
        if e.scan['running']: return dict(ok=False, msg='Đang quét — thử lại sau.')
        e.scan.update(log=[], base=0); threading.Thread(target=lambda: (e.scan.update(bk=10), self._pikpak_backup()), daemon=True).start()
        return dict(ok=True)

    # ------------------------------------------------------------------ rclone / PikPak
    def rc_status(self):
        e = self._e; rc = postscan.find_rclone(DATA_DIR)
        return dict(path=rc or '', logged=bool(postscan.is_logged_in(rc, DATA_DIR)), busy=e.rc['busy'], msg=e.rc['msg'], err=e.rc['err'],
                    user=e.settings.get('pikpak_user', ''))

    def rc_login(self, email, password):
        e = self._e
        if e.rc['busy']: return False
        e.rc.update(busy=True, msg='Đang xử lý… (lần đầu sẽ tải rclone ~20 MB)', err='')
        def work():
            try:
                rc = postscan.find_rclone(DATA_DIR) or postscan.download_rclone(DATA_DIR)
                postscan.login(rc, DATA_DIR, email, password)
                e.settings['pikpak_user'] = email; save_settings(e.settings); e.rc.update(msg='Đăng nhập thành công.', err='')
            except Exception as ex: e.rc.update(msg='', err=str(ex))
            e.rc['busy'] = False
        threading.Thread(target=work, daemon=True).start(); return True

    def rc_logout(self):
        postscan.logout(postscan.find_rclone(DATA_DIR), DATA_DIR); self._e.rc.update(msg='Đã đăng xuất PikPak.', err=''); return True

    # ------------------------------------------------------------------ cập nhật
    def update_check(self):
        e = self._e
        try:
            rel = updater.latest_release(); e.upd.update(rel=rel, newer=bool(rel and updater.is_newer(rel['version'])), err='')
        except Exception as ex: e.upd.update(rel=None, newer=False, err=str(ex))
        rel = e.upd['rel']
        return dict(err=e.upd['err'], has_release=bool(rel), newer=e.upd['newer'], version=rel['version'] if rel else '', notes=(rel['notes'] if rel else '')[:900],
                    page=rel['page'] if rel else '')

    def update_apply(self):
        e = self._e; rel = e.upd['rel']
        if not rel or e.upd['busy']: return False
        if FROZEN: url, dest = rel['exe_url'], os.path.join(APP_DIR, 'My Movie Library.update.exe')
        else: url, dest = rel['zip_url'], os.path.join(tempfile.gettempdir(), 'mml_source.zip')
        if not url: webbrowser.open(rel['page']); return False
        e.upd.update(busy=True, pct=0, msg='Đang tải bản cập nhật…', err='')
        def work():
            try:
                updater.download(url, dest, lambda g, t: e.upd.update(pct=(g * 100 // t) if t else 0))
                if FROZEN:
                    e.upd.update(msg='Tải xong — tool sẽ tự khởi động lại.'); updater.apply_exe_update(dest, APP_DIR)
                    time.sleep(1.2); (e.quit_fn or (lambda: os._exit(0)))()
                else:
                    done = updater.apply_source_update(dest, APP_DIR); e.upd.update(msg=f'Đã cập nhật {len(done)} file. Hãy đóng và mở lại tool.')
            except Exception as ex: e.upd.update(err=str(ex), msg='')
            e.upd['busy'] = False
        threading.Thread(target=work, daemon=True).start(); return True

    def update_state(self):
        u = self._e.upd; return dict(busy=u['busy'], pct=u['pct'], msg=u['msg'], err=u['err'])

    def quit(self):
        self._e.cancel.set()
        (self._e.quit_fn or (lambda: os._exit(0)))(); return True


# ================================================================== cửa sổ app
class WebUI:
    """Hộp thoại chọn file qua pywebview."""

    def __init__(self, eng): self.eng = eng; self.win = None

    def _fd(self, name):
        import webview
        fd = getattr(webview, 'FileDialog', None)
        return getattr(fd, name) if fd else getattr(webview, {'OPEN': 'OPEN_DIALOG', 'FOLDER': 'FOLDER_DIALOG', 'SAVE': 'SAVE_DIALOG'}[name])

    def _one(self, r):
        if not r: return ''
        return r if isinstance(r, str) else (r[0] if len(r) else '')

    def save(self, name, ftype):
        return self._one(self.win.create_file_dialog(self._fd('SAVE'), save_filename=name, file_types=(ftype,)))

    def open(self, ftype):
        return self._one(self.win.create_file_dialog(self._fd('OPEN'), file_types=(ftype,)))

    def folder(self):
        return self._one(self.win.create_file_dialog(self._fd('FOLDER')))


class BrowserUI:
    """Chế độ --serve (thử bằng trình duyệt): đường dẫn lấy từ biến môi trường."""

    def save(self, name, ftype):
        d = os.environ.get('MML_PICK_SAVE_DIR', ''); return os.path.join(d, name) if d else ''

    def open(self, ftype): return os.environ.get('MML_PICK_OPEN', '')

    def folder(self): return os.environ.get('MML_PICK_FOLDER', '')


def serve(port=0, open_browser=True):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    eng = Engine(); eng.ui = BrowserUI(); api = Api(eng)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, code, body, ctype):
            data = body.encode('utf-8') if isinstance(body, str) else body
            self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(data)

        def do_GET(self):
            if self.path in ('/', '/index.html'): self._send(200, page_html(), 'text/html; charset=utf-8')
            else: self._send(404, 'not found', 'text/plain')

        def do_POST(self):
            if self.client_address[0] not in ('127.0.0.1', '::1'): return self._send(403, 'forbidden', 'text/plain')
            name = self.path.rsplit('/', 1)[-1]; n = int(self.headers.get('Content-Length') or 0)
            args = json.loads(self.rfile.read(n) or b'[]'); fn = getattr(api, name, None)
            if name.startswith('_') or not callable(fn): return self._send(404, '{}', 'application/json')
            try: res = fn(*args)
            except Exception as ex: return self._send(500, json.dumps({'error': str(ex)}), 'application/json')
            self._send(200, json.dumps(res, ensure_ascii=False), 'application/json; charset=utf-8')

    srv = ThreadingHTTPServer(('127.0.0.1', port), H)
    url = f'http://127.0.0.1:{srv.server_address[1]}/'; print('Giao diện:', url, flush=True)
    if open_browser: webbrowser.open(url)
    eng.quit_fn = lambda: os._exit(0)
    srv.serve_forever()


def run_web(argv=None):
    """Mở giao diện web. Trả về False nếu máy không chạy được (thiếu pywebview / WebView2) -> dùng giao diện Tk."""
    argv = list(sys.argv if argv is None else argv)
    if '--serve' in argv:
        serve(int(os.environ.get('MML_PORT', '0') or 0), '--no-browser' not in argv); return True
    try:
        import webview
    except Exception:
        return False
    try:
        html = page_html()
    except Exception:
        return False
    eng = Engine(); ui = WebUI(eng); eng.ui = ui
    try:
        win = webview.create_window(APP_TITLE, html=html, js_api=Api(eng), width=1440, height=880, min_size=(1100, 680))
    except Exception:
        return False
    ui.win = win; eng.quit_fn = lambda: win.destroy()
    try: win.events.closed += lambda: eng.cancel.set()
    except Exception: pass
    try: webview.start()
    except Exception:
        return False
    return True


if __name__ == '__main__':
    if sys.platform == 'win32':
        try:
            import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception: pass
    if not run_web(): print('Không mở được giao diện web (cần: pip install pywebview).')
