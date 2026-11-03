"""My Movie Library v2.0 by Duy Anh
Bỏ các file PDF (Karen's Directory Printer) vào thư mục Data: mỗi PDF = 1 ổ HDD, tên file = tên HDD.
Mở tool lên là trống; bấm "Nạp data" để đọc PDF; thoát tool dữ liệu tự mất (PDF không bị xóa)."""
import os, sys, csv, re, queue, itertools, threading, subprocess, tempfile, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import db, updater
from parse_kdp import parse_text
from version import APP_TITLE, APP_VERSION, APP_AUTHOR, GITHUB_REPO

FROZEN = getattr(sys, 'frozen', False)
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
RES_DIR = getattr(sys, '_MEIPASS', APP_DIR)
DATA_DIR = os.path.join(APP_DIR, 'Data')
ALL = '▣  Tất cả HDD'
ALL_CAT = 'Tất cả loại'
EMPTY_MSG = 'Chưa có dữ liệu — bỏ file PDF vào thư mục Data rồi bấm "Nạp data".'
FONT = 'Segoe UI'

THEMES = {
    'dark': dict(bg='#0b1220', panel='#111a2e', card='#16223b', line='#25324d', fg='#e6edf7', muted='#8a99b5',
                 accent='#3b82f6', accent_h='#2f6fe0', danger='#ef4444', danger_h='#d83a3a', ok='#22c55e',
                 sel='#1d4ed8', hit='#5b4a0a', head='#0e1730'),
    'light': dict(bg='#f1f5fb', panel='#ffffff', card='#ffffff', line='#d6deec', fg='#0f172a', muted='#64748b',
                  accent='#2563eb', accent_h='#1d4ed8', danger='#dc2626', danger_h='#b91c1c', ok='#16a34a',
                  sel='#bfdbfe', hit='#fde68a', head='#e8eefa'),
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE); self.geometry('1380x820'); self.minsize(1080, 640)
        try: self.iconbitmap(os.path.join(RES_DIR, 'icon.ico'))
        except Exception: pass
        os.makedirs(DATA_DIR, exist_ok=True)
        self.con = db.connect(':memory:')
        self.theme = 'dark'; self.C = THEMES[self.theme]
        self.sort_col, self.sort_rev = 'name', False
        self.hdd_by_iid = {}; self.tree_info = {}; self.lazy = {}; self.dummy = {}
        self._cnt = itertools.count(); self._after = None; self.loading = False
        self.msgs = queue.Queue(); self.new_release = None
        self._build(); self.apply_theme()
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.load_hdds(); self.refresh(); self.update_data_info()
        self.after(150, self.pump)
        self.after(1500, lambda: self.check_update(silent=True))

    # ------------------------------------------------------------------ giao diện
    def _build(self):
        # Header
        self.header = tk.Frame(self, height=64)
        self.header.pack(fill='x')
        self.header.pack_propagate(False)
        lf = tk.Frame(self.header); lf.pack(side='left', padx=18)
        self.lb_logo = tk.Label(lf, text='🎬', font=(FONT, 24)); self.lb_logo.pack(side='left')
        tf = tk.Frame(lf); tf.pack(side='left', padx=10)
        self.lb_title = tk.Label(tf, text='My Movie Library', font=(FONT, 17, 'bold'), anchor='w'); self.lb_title.pack(anchor='w')
        self.lb_sub = tk.Label(tf, text=f'v{APP_VERSION[:3]}  •  by {APP_AUTHOR}  •  Quản lý phim theo thư mục HDD',
                               font=(FONT, 9), anchor='w'); self.lb_sub.pack(anchor='w')
        rf = tk.Frame(self.header); rf.pack(side='right', padx=14)
        self.btn_update = ttk.Button(rf, text='⬆  Update', style='Ghost.TButton', command=lambda: self.check_update(False))
        self.btn_theme = ttk.Button(rf, text='◐  Giao diện', style='Ghost.TButton', command=self.toggle_theme)
        self.btn_about = ttk.Button(rf, text='ⓘ  Giới thiệu', style='Ghost.TButton', command=self.about)
        for b in (self.btn_update, self.btn_theme, self.btn_about): b.pack(side='left', padx=3)
        self.lb_new = tk.Label(rf, text='', font=(FONT, 9, 'bold'), padx=8)
        self.lb_new.pack(side='left')
        self.sep = tk.Frame(self, height=1); self.sep.pack(fill='x')

        # Thanh hành động
        act = tk.Frame(self); act.pack(fill='x', padx=16, pady=(12, 6)); self.act = act
        self.btn_load = ttk.Button(act, text='⟳  Nạp data', style='Accent.TButton', command=self.load_data)
        self.btn_clear = ttk.Button(act, text='🗑  Xóa data', style='Danger.TButton', command=self.clear_data)
        self.btn_open = ttk.Button(act, text='📂  Mở thư mục Data', style='Ghost.TButton', command=self.open_data)
        self.btn_csv = ttk.Button(act, text='⇩  Xuất CSV', style='Ghost.TButton', command=self.export_csv)
        for b in (self.btn_load, self.btn_clear, self.btn_open, self.btn_csv): b.pack(side='left', padx=(0, 8))
        self.info = tk.Label(act, text='', font=(FONT, 9)); self.info.pack(side='right')

        # Thẻ thống kê
        sr = tk.Frame(self); sr.pack(fill='x', padx=16, pady=(4, 8)); self.statrow = sr
        self.cards = {}
        for i, (k, t) in enumerate((('hdd', 'Ổ HDD'), ('folder', 'Thư mục'), ('file', 'File'),
                                    ('pdf', 'PDF trong Data'), ('cat', 'Phân loại'))):
            c = tk.Frame(sr, padx=14, pady=8, highlightthickness=1)
            c.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 8, 0)); sr.columnconfigure(i, weight=3 if k == 'cat' else 1, uniform='c' if k != 'cat' else '')
            v = tk.Label(c, text='0', font=(FONT, 20, 'bold'), anchor='w'); v.pack(anchor='w')
            tl = tk.Label(c, text=t, font=(FONT, 9), anchor='w'); tl.pack(anchor='w')
            self.cards[k] = (c, v, tl)
        self.cards['cat'][1].config(font=(FONT, 11, 'bold'))

        # Tìm kiếm
        sf = tk.Frame(self); sf.pack(fill='x', padx=16, pady=(0, 8)); self.sf = sf
        self.q = tk.StringVar(); self.q.trace_add('write', lambda *_: self._debounce())
        self.lb_s = tk.Label(sf, text='🔍', font=(FONT, 12)); self.lb_s.pack(side='left')
        self.ent = ttk.Entry(sf, textvariable=self.q, width=44, style='Search.TEntry', font=(FONT, 11))
        self.ent.pack(side='left', padx=(6, 10), ipady=4); self.ent.focus()
        self.cat = tk.StringVar(value=ALL_CAT)
        ttk.Combobox(sf, textvariable=self.cat, state='readonly', width=13, font=(FONT, 10),
                     values=[ALL_CAT, 'Phim', 'Series', 'Anime', 'Audio', 'Game']).pack(side='left', padx=4)
        self.cat.trace_add('write', lambda *_: self.refresh())
        self.parents = tk.BooleanVar(value=False)
        ttk.Checkbutton(sf, text='Hiện cả thư mục cha', variable=self.parents, command=self.refresh).pack(side='left', padx=12)
        self.prog = ttk.Progressbar(sf, mode='determinate', length=260, style='Pro.Horizontal.TProgressbar')
        self.lb_prog = tk.Label(sf, text='', font=(FONT, 9))

        # Thân
        self.status = tk.Label(self, anchor='w', font=(FONT, 9), padx=16, pady=5); self.status.pack(fill='x', side='bottom')
        pw = ttk.PanedWindow(self, orient='horizontal'); pw.pack(fill='both', expand=True, padx=16, pady=(0, 8))
        left = ttk.Frame(pw); pw.add(left, weight=1)
        self.hl = ttk.Treeview(left, columns=('n',), show='tree headings', selectmode='browse')
        self.hl.heading('#0', text='  Danh sách HDD', anchor='w'); self.hl.heading('n', text='Mục')
        self.hl.column('#0', width=210); self.hl.column('n', width=54, anchor='e')
        sbl = ttk.Scrollbar(left, command=self.hl.yview); self.hl.configure(yscrollcommand=sbl.set)
        sbl.pack(side='right', fill='y'); self.hl.pack(fill='both', expand=True)
        self.hl.bind('<<TreeviewSelect>>', lambda e: self.refresh())

        self.nb = ttk.Notebook(pw); pw.add(self.nb, weight=5)
        tab_list = ttk.Frame(self.nb); tab_tree = ttk.Frame(self.nb)
        self.nb.add(tab_list, text='   📋  Danh sách   '); self.nb.add(tab_tree, text='   🌲  Cây thư mục   ')

        right = ttk.PanedWindow(tab_list, orient='vertical'); right.pack(fill='both', expand=True)
        cols = ('name', 'hdd', 'cat', 'n', 'path')
        heads = {'name': 'Tên thư mục', 'hdd': 'HDD', 'cat': 'Loại', 'n': 'File', 'path': 'Đường dẫn'}
        widths = {'name': 380, 'hdd': 150, 'cat': 70, 'n': 55, 'path': 420}
        fr = ttk.Frame(right); right.add(fr, weight=3)
        self.tv = ttk.Treeview(fr, columns=cols, show='headings', selectmode='extended')
        for c in cols:
            self.tv.heading(c, text=heads[c], command=lambda c=c: self.sort_by(c), anchor='w')
            self.tv.column(c, width=widths[c], anchor='e' if c == 'n' else 'w')
        sb = ttk.Scrollbar(fr, command=self.tv.yview); self.tv.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y'); self.tv.pack(side='left', fill='both', expand=True)
        self.tv.bind('<<TreeviewSelect>>', lambda e: self.show_files()); self.tv.bind('<Button-3>', self.menu)
        self.m = tk.Menu(self, tearoff=0)
        self.m.add_command(label='Sao chép đường dẫn', command=self.copy_path)
        self.m.add_command(label='Mở thư mục (nếu HDD đang cắm)', command=self.open_folder)
        bf = ttk.Frame(right); right.add(bf, weight=2)
        self.lb_files = tk.Label(bf, text='  File trong thư mục đã chọn', anchor='w', font=(FONT, 9, 'bold'))
        self.lb_files.pack(fill='x')
        self.ft = ttk.Treeview(bf, columns=('name', 'ext'), show='headings')
        self.ft.heading('name', text='Tên file', anchor='w'); self.ft.heading('ext', text='Đuôi', anchor='w')
        self.ft.column('name', width=820); self.ft.column('ext', width=60)
        sb2 = ttk.Scrollbar(bf, command=self.ft.yview); self.ft.configure(yscrollcommand=sb2.set)
        sb2.pack(side='right', fill='y'); self.ft.pack(side='left', fill='both', expand=True)

        self.tr = ttk.Treeview(tab_tree, columns=('n',), selectmode='browse')
        self.tr.heading('#0', text='  HDD / Thư mục / File', anchor='w'); self.tr.heading('n', text='File')
        self.tr.column('#0', width=780); self.tr.column('n', width=70, anchor='e')
        sby = ttk.Scrollbar(tab_tree, command=self.tr.yview); self.tr.configure(yscrollcommand=sby.set)
        sby.pack(side='right', fill='y'); self.tr.pack(side='left', fill='both', expand=True)
        self.tr.bind('<<TreeviewOpen>>', lambda e: self.load_files(self.tr.focus())); self.tr.bind('<Button-3>', self.tree_menu)
        self.tm = tk.Menu(self, tearoff=0)
        self.tm.add_command(label='Sao chép đường dẫn', command=self.copy_tree_path)
        self.tm.add_command(label='Mở thư mục (nếu HDD đang cắm)', command=self.open_tree_folder)

    def apply_theme(self):
        C = self.C = THEMES[self.theme]
        s = ttk.Style(self)
        try: s.theme_use('clam')
        except tk.TclError: pass
        self.configure(bg=C['bg'])
        s.configure('.', background=C['bg'], foreground=C['fg'], fieldbackground=C['panel'], bordercolor=C['line'],
                    lightcolor=C['line'], darkcolor=C['line'], troughcolor=C['panel'], font=(FONT, 10))
        s.configure('TFrame', background=C['bg']); s.configure('TPanedwindow', background=C['bg'])
        s.configure('TLabel', background=C['bg'], foreground=C['fg'])
        s.configure('Treeview', background=C['panel'], fieldbackground=C['panel'], foreground=C['fg'], rowheight=28,
                    borderwidth=0, font=(FONT, 10))
        s.map('Treeview', background=[('selected', C['sel'])], foreground=[('selected', '#ffffff' if self.theme == 'dark' else C['fg'])])
        s.configure('Treeview.Heading', background=C['head'], foreground=C['muted'], relief='flat', font=(FONT, 9, 'bold'),
                    padding=(8, 7), borderwidth=0)
        s.map('Treeview.Heading', background=[('active', C['card'])])
        s.configure('TNotebook', background=C['bg'], borderwidth=0, tabmargins=(0, 0, 0, 0))
        s.configure('TNotebook.Tab', background=C['bg'], foreground=C['muted'], padding=(14, 8), borderwidth=0, font=(FONT, 10, 'bold'))
        s.map('TNotebook.Tab', background=[('selected', C['panel'])], foreground=[('selected', C['accent'])])
        for name, bg, hv, fg in (('Accent', C['accent'], C['accent_h'], '#ffffff'), ('Danger', C['danger'], C['danger_h'], '#ffffff'),
                                  ('Ghost', C['card'], C['line'], C['fg'])):
            s.configure(f'{name}.TButton', background=bg, foreground=fg, borderwidth=0, focusthickness=0, padding=(14, 8),
                        font=(FONT, 10, 'bold' if name != 'Ghost' else 'normal'), relief='flat')
            s.map(f'{name}.TButton', background=[('active', hv), ('disabled', C['line'])], foreground=[('disabled', C['muted'])])
        s.configure('TEntry', fieldbackground=C['panel'], foreground=C['fg'], insertcolor=C['fg'], bordercolor=C['line'], padding=4)
        s.configure('Search.TEntry', fieldbackground=C['panel'], foreground=C['fg'], insertcolor=C['fg'])
        s.configure('TCombobox', fieldbackground=C['panel'], background=C['card'], foreground=C['fg'], arrowcolor=C['fg'],
                    bordercolor=C['line'], padding=4)
        s.map('TCombobox', fieldbackground=[('readonly', C['panel'])], foreground=[('readonly', C['fg'])])
        s.configure('TCheckbutton', background=C['bg'], foreground=C['fg']); s.map('TCheckbutton', background=[('active', C['bg'])])
        s.configure('TScrollbar', background=C['card'], troughcolor=C['bg'], bordercolor=C['bg'], arrowcolor=C['muted'], relief='flat')
        s.configure('Pro.Horizontal.TProgressbar', background=C['accent'], troughcolor=C['card'], bordercolor=C['card'],
                    lightcolor=C['accent'], darkcolor=C['accent'], thickness=10)
        for w in (self.act, self.statrow, self.sf): w.configure(bg=C['bg'])
        self.header.configure(bg=C['head']); self.sep.configure(bg=C['line'])
        for w in self.header.winfo_children() + [self.lb_logo, self.lb_title, self.lb_sub]: self._tint(w, C['head'])
        self.lb_title.configure(fg=C['fg']); self.lb_sub.configure(fg=C['muted'])
        self.lb_new.configure(bg=C['head'], fg=C['ok'])
        self.info.configure(bg=C['bg'], fg=C['muted']); self.lb_s.configure(bg=C['bg'], fg=C['muted']); self.lb_prog.configure(bg=C['bg'], fg=C['muted'])
        self.status.configure(bg=C['head'], fg=C['muted']); self.lb_files.configure(bg=C['head'], fg=C['muted'])
        for k, (c, v, tl) in self.cards.items():
            c.configure(bg=C['card'], highlightbackground=C['line'], highlightcolor=C['line'])
            v.configure(bg=C['card'], fg=C['accent'] if k != 'cat' else C['fg']); tl.configure(bg=C['card'], fg=C['muted'])
        for m in (self.m, self.tm):
            m.configure(bg=C['panel'], fg=C['fg'], activebackground=C['accent'], activeforeground='#ffffff', bd=0)
        for t in (self.ft, self.tr): t.tag_configure('hit', background=C['hit'])

    def _tint(self, w, bg):
        try: w.configure(bg=bg)
        except tk.TclError: pass
        for ch in w.winfo_children() if hasattr(w, 'winfo_children') else []: self._tint(ch, bg)

    def toggle_theme(self):
        self.theme = 'light' if self.theme == 'dark' else 'dark'; self.apply_theme(); self.refresh()

    def _debounce(self):
        if self._after: self.after_cancel(self._after)
        self._after = self.after(250, self.refresh)

    def new_iid(self): return 'n%d' % next(self._cnt)

    # ------------------------------------------------------------------ truy vấn
    def sel_serial(self):
        s = self.hl.selection()
        return None if not s or s[0] == 'all' else self.hdd_by_iid.get(s[0])

    def filters(self, include_empty):
        serial = self.sel_serial()
        sql = " FROM folder f JOIN hdd h ON h.serial=f.serial WHERE 1=1"; a = []
        if not include_empty: sql += " AND f.nfiles>0"
        if serial: sql += " AND f.serial=?"; a.append(serial)
        if self.cat.get() != ALL_CAT: sql += " AND f.category=?"; a.append(self.cat.get())
        words = db.norm(self.q.get()).split()
        for w in words:
            sql += " AND (f.name_norm LIKE ? OR f.id IN (SELECT folder_id FROM file WHERE name_norm LIKE ?))"
            a += [f'%{w}%', f'%{w}%']
        return sql, a, words, serial

    def scalar(self, sql): return self.con.execute(sql).fetchone()[0]

    def load_hdds(self):
        self.hl.delete(*self.hl.get_children()); self.hdd_by_iid = {}
        self.hl.insert('', 'end', iid='all', text=ALL, values=(self.scalar("SELECT COUNT(*) FROM folder WHERE nfiles>0"),))
        rows = self.con.execute("SELECT h.serial,h.label,(SELECT COUNT(*) FROM folder f WHERE f.serial=h.serial AND f.nfiles>0) n FROM hdd h").fetchall()
        for k, r in enumerate(sorted(rows, key=lambda r: db.natural_key(r['label']))):
            iid = 'h%d' % k; self.hdd_by_iid[iid] = r['serial']
            self.hl.insert('', 'end', iid=iid, text='  💽  ' + r['label'], values=(r['n'],))
        self.hl.selection_set('all')

    def refresh(self):
        n = self.refresh_list(); self.refresh_tree(); self.update_stats(n)

    def update_stats(self, shown):
        nh = self.scalar("SELECT COUNT(*) FROM hdd")
        self.cards['hdd'][1].config(text=f'{nh:,}')
        self.cards['folder'][1].config(text=f'{self.scalar("SELECT COUNT(*) FROM folder WHERE nfiles>0"):,}')
        self.cards['file'][1].config(text=f'{self.scalar("SELECT COUNT(*) FROM file"):,}')
        self.cards['pdf'][1].config(text=str(len(self.pdf_list())))
        cats = self.con.execute("SELECT category,COUNT(*) n FROM folder WHERE nfiles>0 GROUP BY 1 ORDER BY n DESC").fetchall()
        self.cards['cat'][1].config(text='  •  '.join(f"{r['category']} {r['n']}" for r in cats) or '—')
        self.status.config(text=('  ' + EMPTY_MSG) if nh == 0 else f'  Đang hiển thị {shown:,} thư mục')

    # ------------------------------------------------------------------ tab danh sách
    def refresh_list(self):
        sql, a, _, _ = self.filters(include_empty=self.parents.get())
        order = {'name': 'f.name_norm', 'hdd': 'h.label', 'cat': 'f.category', 'n': 'f.nfiles', 'path': 'f.path'}[self.sort_col]
        rows = self.con.execute("SELECT f.id,f.name,h.label,f.category,f.nfiles,f.path" + sql +
                                f" ORDER BY {order} {'DESC' if self.sort_rev else 'ASC'}", a).fetchall()
        self.tv.delete(*self.tv.get_children())
        for r in rows:
            self.tv.insert('', 'end', iid=str(r['id']), values=(r['name'], r['label'], r['category'], r['nfiles'], r['path']))
        self.show_files()
        return len(rows)

    def sort_by(self, c):
        self.sort_rev = (not self.sort_rev) if self.sort_col == c else False
        self.sort_col = c; self.refresh()

    def show_files(self):
        self.ft.delete(*self.ft.get_children())
        sel = self.tv.selection()
        if len(sel) != 1: return
        words = db.norm(self.q.get()).split()
        for r in self.con.execute("SELECT name,ext,name_norm FROM file WHERE folder_id=? ORDER BY name_norm", (sel[0],)):
            self.ft.insert('', 'end', values=(r['name'], r['ext']),
                           tags=('hit',) if words and all(w in r['name_norm'] for w in words) else ())

    def menu(self, ev):
        i = self.tv.identify_row(ev.y)
        if i and i not in self.tv.selection(): self.tv.selection_set(i)
        self.m.tk_popup(ev.x_root, ev.y_root)

    def selected_paths(self):
        return [self.con.execute("SELECT path FROM folder WHERE id=?", (i,)).fetchone()[0] for i in self.tv.selection()]

    def copy_path(self): self.to_clipboard('\n'.join(self.selected_paths()))

    def open_folder(self):
        p = self.selected_paths()
        if p: self.open_path(p[0])

    def to_clipboard(self, text):
        if text: self.clipboard_clear(); self.clipboard_append(text)

    def open_path(self, p):
        if os.path.isdir(p):
            os.startfile(p) if sys.platform == 'win32' else subprocess.Popen(['xdg-open', p])
        else:
            messagebox.showinfo('Không tìm thấy', f'Chưa cắm HDD hoặc thư mục không tồn tại:\n{p}')

    # ------------------------------------------------------------------ tab cây thư mục
    @staticmethod
    def parts_of(path):
        return tuple(p for p in re.sub(r'^[A-Za-z]:', '', path).replace('/', '\\').split('\\') if p)

    def refresh_tree(self):
        self.tr.delete(*self.tr.get_children())
        self.tree_info.clear(); self.lazy.clear(); self.dummy.clear()
        sql, a, words, serial = self.filters(include_empty=True)
        rows = self.con.execute("SELECT f.id,f.serial,f.path,f.nfiles" + sql, a).fetchall()
        present = {r['serial'] for r in rows}
        active = bool(words) or self.cat.get() != ALL_CAT
        hdds = [h for h in self.con.execute("SELECT serial,label FROM hdd")
                if (not serial or h['serial'] == serial) and (not active or h['serial'] in present)]
        hdds.sort(key=lambda h: db.natural_key(h['label']))
        total = {}
        for r in rows: total[r['serial']] = total.get(r['serial'], 0) + r['nfiles']
        hnode, nodes = {}, {}
        for h in hdds:
            iid = self.new_iid(); hnode[h['serial']] = iid
            self.tr.insert('', 'end', iid=iid, text='💽  ' + h['label'], values=(total.get(h['serial'], 0),))
            self.tree_info[iid] = ('hdd', h['serial'])

        def node_for(sv, parts, drive):
            if not parts: return hnode[sv]
            iid = nodes.get((sv, parts))
            if iid: return iid
            parent = node_for(sv, parts[:-1], drive)
            iid = self.new_iid()
            self.tr.insert(parent, 'end', iid=iid, text='📁  ' + parts[-1], values=('',))
            nodes[(sv, parts)] = iid
            self.tree_info[iid] = ('folder', drive + '\\'.join(parts) + '\\')
            return iid

        items = sorted(((self.parts_of(r['path']), r) for r in rows if r['serial'] in hnode),
                       key=lambda t: (t[1]['serial'], [db.natural_key(p) for p in t[0]]))
        for parts, r in items:
            iid = node_for(r['serial'], parts, r['path'][:3])
            if r['nfiles'] > 0:
                self.tr.set(iid, 'n', r['nfiles']); self.lazy[iid] = r['id']
                d = self.new_iid(); self.dummy[iid] = d
                self.tr.insert(iid, 'end', iid=d, text='…')
        if words and len(rows) <= 200:
            for iid in list(hnode.values()) + list(nodes.values()):
                self.tr.item(iid, open=True); self.load_files(iid)

    def load_files(self, iid):
        fid = self.lazy.pop(iid, None)
        if fid is None: return
        self.tr.delete(self.dummy.pop(iid))
        words = db.norm(self.q.get()).split()
        info = self.tree_info.get(iid)
        base = info[1] if info and info[0] == 'folder' else ''
        for r in self.con.execute("SELECT name,name_norm FROM file WHERE folder_id=? ORDER BY name_norm", (fid,)):
            f = self.new_iid()
            self.tr.insert(iid, 'end', iid=f, text='🎬  ' + r['name'], values=('',),
                           tags=('hit',) if words and all(w in r['name_norm'] for w in words) else ())
            self.tree_info[f] = ('file', base, r['name'])

    def tree_menu(self, ev):
        i = self.tr.identify_row(ev.y)
        if i: self.tr.selection_set(i); self.tm.tk_popup(ev.x_root, ev.y_root)

    def tree_path(self):
        s = self.tr.selection(); info = self.tree_info.get(s[0]) if s else None
        return info[1] if info and info[0] in ('folder', 'file') else None

    def copy_tree_path(self):
        s = self.tr.selection(); info = self.tree_info.get(s[0]) if s else None
        if info and info[0] == 'file': self.to_clipboard(info[1] + info[2])
        elif info and info[0] == 'folder': self.to_clipboard(info[1])

    def open_tree_folder(self):
        p = self.tree_path()
        if p: self.open_path(p)

    # ------------------------------------------------------------------ nạp / xóa data
    def pdf_list(self):
        try: names = [f for f in os.listdir(DATA_DIR) if f.lower().endswith('.pdf')]
        except OSError: names = []
        return [os.path.join(DATA_DIR, f) for f in sorted(names, key=db.natural_key)]

    def update_data_info(self):
        self.info.config(text=f'Data: {DATA_DIR}')
        self.cards['pdf'][1].config(text=str(len(self.pdf_list())))

    def open_data(self):
        os.makedirs(DATA_DIR, exist_ok=True); self.open_path(DATA_DIR)

    def set_busy(self, busy):
        self.loading = busy
        for b in (self.btn_load, self.btn_clear, self.btn_csv): b.config(state='disabled' if busy else 'normal')
        if busy: self.prog.pack(side='right'); self.lb_prog.pack(side='right', padx=8)
        else: self.prog.pack_forget(); self.lb_prog.pack_forget()

    def load_data(self):
        if self.loading: return
        self.update_data_info(); pdfs = self.pdf_list()
        if not pdfs:
            if messagebox.askyesno('Chưa có file PDF', 'Thư mục Data chưa có file PDF nào.\n\nMở thư mục Data để bỏ file PDF vào?'):
                self.open_data()
            return
        self.set_busy(True); self.prog.configure(maximum=len(pdfs), value=0)

        def work():
            results, errors = [], []
            for i, p in enumerate(pdfs, 1):
                stem = os.path.splitext(os.path.basename(p))[0]
                self.msgs.put(('progress', (i - 1, len(pdfs), stem)))
                try: results.append((stem, parse_text(db.read_pdf_text(p))))
                except Exception as ex:
                    errors.append((stem, str(ex)))
                    if 'pypdf' in str(ex): break
            self.msgs.put(('done', (results, errors, len(pdfs))))
        threading.Thread(target=work, daemon=True).start()

    def pump(self):
        try:
            while True:
                kind, p = self.msgs.get_nowait()
                if kind == 'progress':
                    i, n, stem = p; self.prog.configure(value=i); self.lb_prog.config(text=f'{i}/{n}  {stem}')
                    self.status.config(text=f'  Đang đọc {stem} …')
                elif kind == 'done': self.load_done(*p)
                elif kind == 'update_info': self.on_update_info(*p)
                elif kind == 'dl': self.on_download_progress(*p)
                elif kind == 'dl_done': self.on_download_done(*p)
        except queue.Empty:
            pass
        self.after(120, self.pump)

    def load_done(self, results, errors, total):
        db.wipe_all(self.con); multi = []
        for stem, parsed in results:
            n = db.load_parsed(self.con, stem, parsed)
            if n == 0: errors.append((stem, "Không nhận diện được nội dung (không phải bản in của Karen's Directory Printer?)"))
            elif n > 1: multi.append((stem, n))
        self.set_busy(False); self.load_hdds(); self.refresh()
        msg = (f'Đã nạp {self.scalar("SELECT COUNT(*) FROM hdd")} HDD, {self.scalar("SELECT COUNT(*) FROM folder WHERE nfiles>0")} thư mục, '
               f'{self.scalar("SELECT COUNT(*) FROM file")} file từ {total - len(errors)}/{total} file PDF.')
        for stem, n in multi: msg += f'\n\n"{stem}.pdf" chứa {n} ổ nên đã tách theo nhãn ổ (nên để mỗi PDF 1 ổ).'
        if errors:
            msg += '\n\nLỗi:\n' + '\n'.join(f'- {s}: {e}' for s, e in errors[:8])
            messagebox.showwarning('Nạp data xong (có lỗi)', msg)
        else:
            messagebox.showinfo('Nạp data xong', msg)

    def clear_data(self):
        if self.loading: return
        if self.scalar("SELECT COUNT(*) FROM hdd") == 0:
            messagebox.showinfo('Xóa data', 'Chưa có dữ liệu nào để xóa.'); return
        if messagebox.askyesno('Xóa data', 'Xóa toàn bộ dữ liệu đang nạp trong tool?\n(File PDF trong thư mục Data KHÔNG bị xóa)'):
            db.wipe_all(self.con); self.load_hdds(); self.refresh()

    def export_csv(self):
        if not self.tv.get_children():
            messagebox.showinfo('Xuất CSV', 'Không có dữ liệu để xuất.'); return
        p = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')], initialfile='thu_vien_phim.csv')
        if not p: return
        with open(p, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f); w.writerow(['Tên thư mục', 'HDD', 'Loại', 'Số file', 'Đường dẫn'])
            for i in self.tv.get_children(): w.writerow(self.tv.item(i, 'values'))
        messagebox.showinfo('Xong', 'Đã xuất danh sách đang hiển thị.')

    # ------------------------------------------------------------------ update
    def check_update(self, silent):
        self.btn_update.config(state='disabled')
        if not silent: self.status.config(text='  Đang kiểm tra bản cập nhật trên GitHub…')
        def work():
            try: rel, err = updater.latest_release(), None
            except Exception as ex: rel, err = None, str(ex)
            self.msgs.put(('update_info', (rel, err, silent)))
        threading.Thread(target=work, daemon=True).start()

    def on_update_info(self, rel, err, silent):
        self.btn_update.config(state='normal'); self.refresh()
        newer = bool(rel and updater.is_newer(rel['version']))
        if newer:
            self.new_release = rel; self.lb_new.config(text=f'● Có bản mới v{rel["version"]}')
        if silent: return
        if err: messagebox.showerror('Update', f'Không kiểm tra được bản mới (cần Internet):\n{err}'); return
        if rel is None: messagebox.showinfo('Update', f'Chưa có bản phát hành nào trên GitHub.\nBạn đang dùng v{APP_VERSION}.'); return
        if not newer: messagebox.showinfo('Update', f'Bạn đang dùng bản mới nhất (v{APP_VERSION}).'); return
        notes = (rel['notes'] or '').strip()[:700]
        if not messagebox.askyesno('Có bản cập nhật', f'Có phiên bản mới v{rel["version"]} (hiện tại v{APP_VERSION}).\n\n{notes}\n\nCập nhật ngay?'):
            return
        self.start_download(rel)

    def start_download(self, rel):
        if FROZEN:
            if not rel['exe_url']: webbrowser.open(rel['page']); return
            url, dest = rel['exe_url'], os.path.join(APP_DIR, 'My Movie Library.update.exe')
        else:
            if not rel['zip_url']: webbrowser.open(rel['page']); return
            url, dest = rel['zip_url'], os.path.join(tempfile.gettempdir(), 'mml_source.zip')
        self.set_busy(True); self.prog.configure(maximum=100, value=0); self.lb_prog.config(text='Đang tải bản cập nhật…')
        def work():
            try:
                updater.download(url, dest, lambda g, t: self.msgs.put(('dl', (g, t))))
                self.msgs.put(('dl_done', (dest, None)))
            except Exception as ex:
                self.msgs.put(('dl_done', (dest, str(ex))))
        threading.Thread(target=work, daemon=True).start()

    def on_download_progress(self, got, total):
        if total: self.prog.configure(value=got * 100 / total); self.lb_prog.config(text=f'Đang tải… {got // 1024:,}/{total // 1024:,} KB')

    def on_download_done(self, path, err):
        self.set_busy(False)
        if err: messagebox.showerror('Update', f'Tải bản cập nhật thất bại:\n{err}'); return
        try:
            if FROZEN:
                messagebox.showinfo('Update', 'Tải xong. Tool sẽ tự khởi động lại bằng phiên bản mới.')
                updater.apply_exe_update(path, APP_DIR); self.on_close()
            else:
                done = updater.apply_source_update(path, APP_DIR)
                messagebox.showinfo('Update', f'Đã cập nhật {len(done)} file. Hãy đóng và mở lại tool.')
        except Exception as ex:
            messagebox.showerror('Update', f'Không áp dụng được bản cập nhật:\n{ex}')

    def about(self):
        messagebox.showinfo('Giới thiệu', f'{APP_TITLE}\n\nQuản lý danh sách phim theo thư mục các ổ HDD,\nđọc từ bản in PDF của Karen\'s Directory Printer.\n\n'
                            f'GitHub: github.com/{GITHUB_REPO}\nPhiên bản: {APP_VERSION}')

    def on_close(self):
        try: db.wipe_all(self.con); self.con.close()
        except Exception: pass
        self.destroy()


if __name__ == '__main__':
    App().mainloop()
