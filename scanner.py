"""Quét toàn bộ thư mục / thư mục con / tên file của một ổ đĩa và ghi vào thư viện (1 giao dịch: hủy = không đổi gì)."""
import os, sys, time, shutil
import library as L

SKIP_DIRS = {'$recycle.bin', 'system volume information', 'recovery', '$winreagent', 'config.msi', 'lost+found',
             '.trashes', '.spotlight-v100', '.fseventsd', '.trash-1000'}
MEDIA_KINDS = {'video', 'audio', 'sub'}


class Cancelled(Exception):
    pass


def _skip_dir(entry):
    n = entry.name.lower()
    if n in SKIP_DIRS or n.startswith('$'): return True
    try:
        if entry.is_symlink(): return True
        st = entry.stat(follow_symlinks=False)
        return bool(getattr(st, 'st_file_attributes', 0) & 0x400)      # junction / reparse point: tránh lặp vô hạn
    except OSError:
        return True


def _long(p):
    """Windows: thêm tiền tố \\\\?\\ để quét được đường dẫn dài hơn 260 ký tự (thư mục phim tải về hay rất dài)."""
    if sys.platform != 'win32': return p
    p = os.path.abspath(p)
    if p.startswith('\\\\?\\'): return p
    return '\\\\?\\UNC\\' + p[2:] if p.startswith('\\\\') else '\\\\?\\' + p


def ident_for(root, serial):
    return f'S:{serial}' if serial and serial != '00000000' else 'P:' + os.path.abspath(root).lower()


def scan_hdd(db_path, root, name='', drive=None, cancel=None, progress=None, media_only=False, replace_id=None):
    """Quét `root`. drive = dict từ drives.list_drives() (serial/label/fs/total) hoặc None nếu chọn thư mục thường.
    Trả về dict thống kê. Quét lại cùng ổ (cùng serial) = thay toàn bộ dữ liệu cũ của ổ đó, giữ nguyên mã ổ + tên."""
    t0 = time.time(); last = [0.0]
    drive = drive or {}
    serial = drive.get('serial', '')
    ident = ident_for(root, serial)
    con = L.connect(db_path)
    try:
        con.execute('BEGIN IMMEDIATE')
        old = (con.execute("SELECT id,code,name FROM hdd WHERE id=?", (replace_id,)).fetchone() if replace_id else
               con.execute("SELECT id,code,name FROM hdd WHERE ident=?", (ident,)).fetchone())
        label = drive.get('label', '') or os.path.basename(root.rstrip('\\/')) or root
        try: total, _u, free = shutil.disk_usage(root)
        except OSError: total, free = drive.get('total', 0), drive.get('free', 0)
        if old:
            hid, code, hname = old['id'], old['code'], old['name']
            con.execute("DELETE FROM file WHERE hdd_id=?", (hid,)); con.execute("DELETE FROM folder WHERE hdd_id=?", (hid,))
            con.execute("UPDATE hdd SET ident=?,label=?,serial=?,root=?,fs=?,total=?,free=? WHERE id=?",
                        (ident, label, serial, root, drive.get('fs', ''), total, free, hid))
        else:
            seq = L.next_hdd_seq(con); code = L.hdd_code(seq); hname = (name or label).strip() or code
            hid = con.execute("INSERT INTO hdd(seq,code,ident,name,label,serial,root,fs,total,free) VALUES(?,?,?,?,?,?,?,?,?,?)",
                              (seq, code, ident, hname, label, serial, root, drive.get('fs', ''), total, free)).lastrowid
        n_files = n_bytes = n_folders = n_err = 0
        buf, order, par, tot = [], [], {}, {}
        rname = os.path.basename(root.rstrip('\\/')) or root
        sroot = _long(root)
        try: os.scandir(sroot).close()
        except OSError: sroot = root
        stack = [(sroot, '', None, 0, rname)]
        INS = "INSERT INTO file(hdd_id,folder_id,code,name,name_norm,ext,kind,size,mtime) VALUES(?,?,?,?,?,?,?,?,?)"
        while stack:
            if cancel is not None and cancel.is_set(): raise Cancelled()
            path, rel, parent, depth, dname = stack.pop()
            dirs, files = [], []
            try:
                with os.scandir(path) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if not _skip_dir(e): dirs.append(e.name)
                            elif e.is_symlink() and e.is_dir():
                                continue                                  # symlink trỏ tới thư mục: bỏ qua (tránh lặp)
                            else:
                                ext = os.path.splitext(e.name)[1].lower(); kind = L.kind_of(ext)
                                if media_only and kind not in MEDIA_KINDS: continue
                                st = e.stat(); files.append((e.name, ext, kind, st.st_size, int(st.st_mtime)))
                        except FileNotFoundError:
                            pass                                              # symlink hỏng / file vừa bị xóa: bỏ qua im lặng
                        except OSError:
                            n_err += 1
            except OSError:
                n_err += 1
            files.sort(key=lambda r: L.natural_key(r[0])); dirs.sort(key=L.natural_key)
            fbytes = sum(r[3] for r in files)
            fid = con.execute("INSERT INTO folder(hdd_id,code,parent_id,name,name_norm,path,path_norm,depth,nfiles,bytes) "
                              "VALUES(?,?,?,?,?,?,?,?,?,?)",
                              (hid, f'{code}-D{n_folders:05d}', parent, dname, L.norm(dname), rel, L.norm(rel.replace('\\', ' / ')),
                               depth, len(files), fbytes)).lastrowid
            n_folders += 1; order.append(fid); par[fid] = parent; tot[fid] = [len(files), fbytes]
            for nm, ext, kind, size, mt in files:
                n_files += 1; n_bytes += size
                buf.append((hid, fid, f'{code}-{n_files:06d}', nm, L.norm(nm), ext, kind, size, mt))
            if len(buf) >= 5000: con.executemany(INS, buf); buf.clear()
            for d in reversed(dirs):
                stack.append((os.path.join(path, d), (rel + '\\' + d) if rel else d, fid, depth + 1, d))
            now = time.time()
            if progress and now - last[0] > 0.1:
                last[0] = now; progress(n_files, n_folders, n_bytes, rel or rname)
        if buf: con.executemany(INS, buf)
        for fid in reversed(order):                                   # cộng dồn số file / dung lượng lên thư mục cha
            p = par[fid]
            if p is not None: tot[p][0] += tot[fid][0]; tot[p][1] += tot[fid][1]
        con.executemany("UPDATE folder SET tfiles=?, tbytes=? WHERE id=?", [(v[0], v[1], k) for k, v in tot.items()])
        con.execute("UPDATE hdd SET nfolders=?,nfiles=?,bytes=?,scanned_at=datetime('now','localtime') WHERE id=?",
                    (n_folders, n_files, n_bytes, hid))
        con.commit()
        if progress: progress(n_files, n_folders, n_bytes, '')
        return dict(hid=hid, code=code, name=hname, files=n_files, folders=n_folders, bytes=n_bytes, errors=n_err,
                    seconds=time.time() - t0, new=old is None)
    except BaseException:
        con.rollback(); raise
    finally:
        con.close()
