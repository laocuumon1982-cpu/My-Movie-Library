"""My Movie Library v3.0 by Duy Anh
Chọn ổ HDD -> quét toàn bộ thư mục / thư mục con / tên file -> lưu vào thư viện (có mã số) -> tìm kiếm tức thì."""
import os, sys, csv, json, queue, shutil, sqlite3, threading, subprocess, tempfile, time, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import library as L, scanner, drives, updater
from drives import fmt_size
from version import APP_TITLE, APP_VERSION, APP_AUTHOR, GITHUB_REPO

FROZEN = getattr(sys, 'frozen', False)
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
RES_DIR = getattr(sys, '_MEIPASS', APP_DIR)
FONT = os.environ.get('MML_FONT', 'Segoe UI')


def pick_data_dir():
    """Thư viện nằm cạnh tool (portable). Nếu thư mục đó không ghi được thì dùng %APPDATA%."""
    forced = os.environ.get('MML_DATA')
    cands = [forced] if forced else [os.path.join(APP_DIR, 'Data'),
                                     os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'My Movie Library')]
    for d in cands:
        try:
            os.makedirs(d, exist_ok=True)
            t = os.path.join(d, '.w'); open(t, 'w').close(); os.remove(t)
            return d
        except OSError:
            continue
    return tempfile.gettempdir()


DATA_DIR = pick_data_dir()
DB_PATH = os.path.join(DATA_DIR, 'library.db')
SETTINGS = os.path.join(DATA_DIR, 'settings.json')

KIND_LABELS = ['Tất cả loại', 'Video', 'Audio', 'Phụ đề', 'Ảnh', 'Khác']
KIND_KEYS = [None, 'video', 'audio', 'sub', 'image', 'other']
HINT = 'Gõ tên phim (không cần dấu)   •   ext:mkv   •   >1gb  <500mb   •   hdd:H01   •   mã: H01-000123 · H01-D00012 · H01-'

THEMES = {
    'dark': dict(bg='#0b1220', panel='#111a2e', card='#16223b', line='#25324d', fg='#e6edf7', muted='#8a99b5', dim='#5d6d8c',
                 accent='#3b82f6', accent_h='#2f6fe0', danger='#ef4444', danger_h='#d83a3a', ok='#22c55e',
                 sel='#1d4ed8', head='#0e1730', zebra='#131d33', warn='#f59e0b'),
    'light': dict(bg='#f1f5fb', panel='#ffffff', card='#ffffff', line='#d6deec', fg='#0f172a', muted='#64748b', dim='#94a3b8',
                  accent='#2563eb', accent_h='#1d4ed8', danger='#dc2626', danger_h='#b91c1c', ok='#16a34a',
                  sel='#bfdbfe', head='#e8eefa', zebra='#f6f9fe', warn='#d97706'),
}


def F(size, bold=False):
    return (FONT, size, 'bold') if bold else (FONT, size)


def load_settings():
    try:
        with open(SETTINGS, encoding='utf8') as f: return json.load(f)
    except Exception:
        return {}


def save_settings(d):
    try:
        with open(SETTINGS, 'w', encoding='utf8') as f: json.dump(d, f)
    except OSError:
        pass


# ======================================================================================= hộp thoại phụ
def center(win, parent, w, h):
    win.update_idletasks()
    x = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 3)
    win.geometry(f'{w}x{h}+{x}+{y}')


class Modal(tk.Toplevel):
    def __init__(self, app, title, w, h):
        super().__init__(app)
        self.app = app; self.C = app.C
        self.title(title); self.configure(bg=self.C['bg']); self.transient(app); self.resizable(False, False)
        center(self, app, app.px(w), app.px(h))
        try: self.iconbitmap(os.path.join(RES_DIR, 'icon.ico'))
        except Exception: pass
        self.after(60, self._grab)

    def _grab(self):
        try: self.grab_set(); self.focus_set()
        except tk.TclError: pass

    def label(self, parent, text, size=10, bold=False, muted=False, **kw):
        return tk.Label(parent, text=text, font=F(size, bold), bg=parent['bg'], fg=self.C['muted' if muted else 'fg'], **kw)


class ScanProgress(Modal):
    """Cửa sổ tiến độ khi quét ổ."""

    def __init__(self, app, name):
        super().__init__(app, 'Đang quét ổ đĩa…', 600, 290)
        C = self.C; self.cancel_event = threading.Event(); self.t0 = time.time()
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        body = tk.Frame(self, bg=C['bg']); body.pack(fill='both', expand=True, padx=24, pady=20)
        self.label(body, 'Đang quét và lưu vào thư viện', 14, True).pack(anchor='w')
        self.label(body, name, 10, muted=True).pack(anchor='w', pady=(2, 12))
        row = tk.Frame(body, bg=C['bg']); row.pack(fill='x')
        self.vals = {}
        for k, t in (('files', 'File'), ('folders', 'Thư mục'), ('bytes', 'Dung lượng'), ('time', 'Thời gian')):
            c = tk.Frame(row, bg=C['card'], highlightthickness=1, highlightbackground=C['line'], padx=12, pady=8)
            c.pack(side='left', fill='x', expand=True, padx=(0, 8))
            v = tk.Label(c, text='0', font=F(15, True), bg=C['card'], fg=C['accent'], anchor='w'); v.pack(anchor='w')
            tk.Label(c, text=t, font=F(9), bg=C['card'], fg=C['muted'], anchor='w').pack(anchor='w')
            self.vals[k] = v
        self.path = tk.Label(body, text='', font=F(9), bg=C['bg'], fg=C['muted'], anchor='w', justify='left')
        self.path.pack(fill='x', pady=(12, 6))
        self.bar = ttk.Progressbar(body, mode='indeterminate', style='Pro.Horizontal.TProgressbar'); self.bar.pack(fill='x')
        self.bar.start(14)
        self.btn = ttk.Button(body, text='Hủy quét', style='Ghost.TButton', command=self.cancel); self.btn.pack(anchor='e', pady=(14, 0))
        self.tick()

    def tick(self):
        try:
            self.vals['time'].config(text=f'{int(time.time() - self.t0)} giây'); self.after(500, self.tick)
        except tk.TclError:
            pass

    def update_stats(self, files, folders, size, rel):
        self.vals['files'].config(text=f'{files:,}'); self.vals['folders'].config(text=f'{folders:,}')
        self.vals['bytes'].config(text=fmt_size(size))
        self.path.config(text=('…\\' + rel[-90:]) if len(rel) > 90 else rel)

    def cancel(self):
        self.cancel_event.set(); self.btn.config(state='disabled', text='Đang hủy…')


class ScanDialog(Modal):
    """Chọn ổ đĩa HDD (hoặc một thư mục) để quét."""

    def __init__(self, app, on_start):
        super().__init__(app, 'Chọn ổ HDD để quét', 860, 520)
        C = self.C; self.on_start = on_start; self.drive_rows = {}; self.picked = None
        body = tk.Frame(self, bg=C['bg']); body.pack(fill='both', expand=True, padx=22, pady=18)
        self.label(body, 'Chọn ổ đĩa cần quét', 14, True).pack(anchor='w')
        self.label(body, 'Tool sẽ quét toàn bộ thư mục, thư mục con và tên file của ổ, rồi lưu vào thư viện kèm mã số.', 9, muted=True).pack(anchor='w', pady=(2, 10))
        cols = ('letter', 'label', 'type', 'fs', 'total', 'free', 'lib')
        heads = ('Ổ', 'Nhãn ổ', 'Loại', 'Hệ tệp', 'Dung lượng', 'Còn trống', 'Trong thư viện')
        widths = (60, 190, 120, 70, 100, 100, 140)
        self.tv = ttk.Treeview(body, columns=cols, show='headings', selectmode='browse', height=8)
        for c, h, w in zip(cols, heads, widths):
            self.tv.heading(c, text=h, anchor='w'); self.tv.column(c, width=app.px(w), anchor='w')
        self.tv.pack(fill='x'); self.tv.bind('<<TreeviewSelect>>', lambda e: self.on_pick())
        self.tv.bind('<Double-1>', lambda e: self.start())
        self.empty = self.label(body, '', 9, muted=True); self.empty.pack(anchor='w', pady=(4, 0))
        form = tk.Frame(body, bg=C['bg']); form.pack(fill='x', pady=(12, 0))
        self.label(form, 'Tên ổ trong thư viện:', 10).grid(row=0, column=0, sticky='w')
        self.name = tk.StringVar(); ttk.Entry(form, textvariable=self.name, width=42, style='Search.TEntry').grid(row=0, column=1, sticky='w', padx=10, ipady=3)
        self.code_lb = self.label(form, '', 10, True); self.code_lb.grid(row=0, column=2, sticky='w')
        self.media = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text='Chỉ quét file media (video, audio, phụ đề) — bỏ qua file khác', variable=self.media).pack(anchor='w', pady=(10, 0))
        self.where = self.label(body, '', 9, muted=True); self.where.pack(anchor='w', pady=(6, 0))
        bar = tk.Frame(body, bg=C['bg']); bar.pack(side='bottom', fill='x', pady=(10, 0))
        ttk.Button(bar, text='Đóng', style='Ghost.TButton', command=self.destroy).pack(side='right')
        self.go = ttk.Button(bar, text='▶  Bắt đầu quét', style='Accent.TButton', command=self.start, state='disabled')
        self.go.pack(side='right', padx=8)
        ttk.Button(bar, text='Chọn thư mục khác…', style='Ghost.TButton', command=self.pick_folder).pack(side='left')
        ttk.Button(bar, text='⟳ Làm mới', style='Ghost.TButton', command=self.load).pack(side='left', padx=8)
        self.after(80, self.load)

    def load(self):
        self.empty.config(text='Đang đọc danh sách ổ đĩa…'); self.update_idletasks()
        self.app.drives = drives.list_drives()
        self.tv.delete(*self.tv.get_children()); self.drive_rows = {}
        known = {h['serial']: h for h in L.list_hdds(self.app.con) if h['serial']}
        for i, d in enumerate(self.app.drives):
            iid = f'd{i}'; self.drive_rows[iid] = d
            inlib = known.get(d['serial']) if d['serial'] else None
            self.tv.insert('', 'end', iid=iid, values=(d['letter'], d['label'] or '(không nhãn)',
                           d['type'] + (' • hệ thống' if d['system'] else ''), d['fs'], fmt_size(d['total']), fmt_size(d['free']),
                           f"{inlib['code']} · quét lại" if inlib else '—'))
        self.empty.config(text='' if self.drive_rows else 'Không thấy ổ đĩa nào. Cắm ổ HDD rồi bấm "Làm mới", hoặc dùng "Chọn thư mục khác…".')
        self.app.refresh_sidebar()

    def on_pick(self):
        s = self.tv.selection()
        if not s: return
        self.set_target(self.drive_rows[s[0]]['root'], self.drive_rows[s[0]])

    def set_target(self, root, drive):
        self.picked = (root, drive); ident = scanner.ident_for(root, drive.get('serial', '') if drive else '')
        old = self.app.con.execute("SELECT code,name FROM hdd WHERE ident=?", (ident,)).fetchone()
        if old:
            self.name.set(old['name']); self.code_lb.config(text=f"Mã ổ: {old['code']}  (quét lại, thay dữ liệu cũ)", fg=self.C['warn'])
        else:
            lab = (drive or {}).get('label') or os.path.basename(root.rstrip('\\/')) or root
            self.name.set(lab); self.code_lb.config(text=f"Mã ổ mới: {L.hdd_code(L.next_hdd_seq(self.app.con))}", fg=self.C['ok'])
        self.where.config(text=f'Sẽ quét: {root}'); self.go.config(state='normal')

    def pick_folder(self):
        p = filedialog.askdirectory(parent=self, title='Chọn thư mục / ổ cần quét')
        if not p: return
        p = os.path.normpath(p)
        match = next((d for d in self.app.drives if os.path.normcase(d['root'].rstrip('\\/')) == os.path.normcase(p.rstrip('\\/'))), None)
        self.tv.selection_remove(*self.tv.selection()); self.set_target(match['root'] if match else p, match)

    def start(self):
        if not self.picked: return
        root, drive = self.picked
        if drive and drive.get('system') and not messagebox.askyesno(
                'Ổ hệ thống', f"{drive['letter']} là ổ hệ thống (Windows), quét sẽ rất lâu và nhiều file không liên quan.\nVẫn quét?", parent=self):
            return
        name = self.name.get().strip(); media = self.media.get(); self.destroy()
        self.on_start(root, name, drive, media, None)


class EditHdd(Modal):
    def __init__(self, app, h, on_ok):
        super().__init__(app, 'Sửa tên / mã ổ', 520, 250)
        C = self.C; body = tk.Frame(self, bg=C['bg']); body.pack(fill='both', expand=True, padx=22, pady=18)
        self.label(body, f"Ổ {h['code']} — {h['name']}", 13, True).pack(anchor='w', pady=(0, 12))
        g = tk.Frame(body, bg=C['bg']); g.pack(fill='x')
        self.name = tk.StringVar(value=h['name']); self.code = tk.StringVar(value=h['code'])
        self.label(g, 'Tên ổ:').grid(row=0, column=0, sticky='w', pady=4)
        ttk.Entry(g, textvariable=self.name, width=40, style='Search.TEntry').grid(row=0, column=1, padx=10, ipady=3)
        self.label(g, 'Mã ổ:').grid(row=1, column=0, sticky='w', pady=4)
        ttk.Entry(g, textvariable=self.code, width=12, style='Search.TEntry').grid(row=1, column=1, sticky='w', padx=10, ipady=3)
        self.label(body, 'Đổi mã ổ sẽ đổi luôn tiền tố mã của mọi file / thư mục thuộc ổ (VD H01-000123 → PL1-000123).', 9, muted=True,
                   wraplength=app.px(470), justify='left').pack(anchor='w', pady=(10, 0))
        bar = tk.Frame(body, bg=C['bg']); bar.pack(side='bottom', fill='x')
        ttk.Button(bar, text='Hủy', style='Ghost.TButton', command=self.destroy).pack(side='right')
        ttk.Button(bar, text='Lưu', style='Accent.TButton', command=lambda: self.ok(on_ok)).pack(side='right', padx=8)

    def ok(self, on_ok):
        try: on_ok(self.name.get(), self.code.get())
        except ValueError as e: messagebox.showwarning('Không lưu được', str(e), parent=self); return
        self.destroy()


# ======================================================================================= cửa sổ chính
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE); self.minsize(1100, 680)
        self.sf = max(1.0, float(self.tk.call('tk', 'scaling')) * 72 / 96)
        w = min(self.px(1400), self.winfo_screenwidth() - 60); h = min(self.px(860), self.winfo_screenheight() - 90)
        self.geometry(f'{w}x{h}+{max(0, (self.winfo_screenwidth() - w) // 2)}+{max(0, (self.winfo_screenheight() - h) // 3)}')
        try: self.iconbitmap(os.path.join(RES_DIR, 'icon.ico'))
        except Exception: pass
        self.settings = load_settings(); self.theme = self.settings.get('theme', 'dark'); self.C = THEMES[self.theme]
        self.con = L.connect(DB_PATH)
        self.hid = None; self.drives = []; self.limit = 5000; self.dirty = set(); self.cur = None; self._after = None
        self.sort = {'files': ('code', False), 'folders': ('code', False)}
        self.msgs = queue.Queue(); self.new_release = None; self.scanning = None; self._lock = False
        self.rows = {}; self.last_total = 0
        self._build(); self.apply_theme()
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.bind('<Control-f>', lambda e: (self.ent.focus_set(), self.ent.select_range(0, 'end')))
        self.bind('<Control-o>', lambda e: self.open_scan_dialog()); self.bind('<Escape>', lambda e: self.q.set(''))
        self.refresh_all(); self.after(150, self.pump)
        self.after(300, self.refresh_drives_async); self.after(1800, lambda: self.check_update(silent=True))

    def px(self, n): return int(round(n * self.sf))

    # ------------------------------------------------------------------ dựng giao diện
    def _build(self):
        self.header = tk.Frame(self, height=self.px(66)); self.header.pack(fill='x'); self.header.pack_propagate(False)
        lf = tk.Frame(self.header); lf.pack(side='left', padx=self.px(18))
        self.logo = tk.Canvas(lf, highlightthickness=0, width=self.px(40), height=self.px(40)); self.logo.pack(side='left')
        tf = tk.Frame(lf); tf.pack(side='left', padx=12)
        self.lb_title = tk.Label(tf, text='My Movie Library', font=F(17, True), anchor='w'); self.lb_title.pack(anchor='w')
        self.lb_sub = tk.Label(tf, text=f'v{APP_VERSION[:3]}  •  by {APP_AUTHOR}  •  Thư viện phim theo ổ HDD', font=F(9), anchor='w')
        self.lb_sub.pack(anchor='w')
        rf = tk.Frame(self.header); rf.pack(side='right', padx=self.px(14))
        self.btn_update = ttk.Button(rf, text='⬆  Update', style='Ghost.TButton', command=lambda: self.check_update(False))
        self.btn_theme = ttk.Button(rf, text='◐  Giao diện', style='Ghost.TButton', command=self.toggle_theme)
        self.btn_about = ttk.Button(rf, text='ⓘ  Giới thiệu', style='Ghost.TButton', command=self.about)
        for b in (self.btn_update, self.btn_theme, self.btn_about): b.pack(side='left', padx=3)
        self.lb_new = tk.Label(rf, text='', font=F(9, True), padx=8); self.lb_new.pack(side='left')
        self.sep = tk.Frame(self, height=1); self.sep.pack(fill='x')

        self.status = tk.Label(self, anchor='w', font=F(9), padx=16, pady=5); self.status.pack(fill='x', side='bottom')

        tb = tk.Frame(self); tb.pack(fill='x', padx=16, pady=(12, 6)); self.tb = tb
        self.btn_scan = ttk.Button(tb, text='＋  Quét ổ HDD', style='Accent.TButton', command=self.open_scan_dialog)
        self.btn_rescan = ttk.Button(tb, text='⟳  Quét lại', style='Ghost.TButton', command=self.rescan_selected)
        self.btn_edit = ttk.Button(tb, text='✎  Sửa tên / mã', style='Ghost.TButton', command=self.edit_selected)
        self.btn_del = ttk.Button(tb, text='🗑  Xóa ổ', style='GhostDanger.TButton', command=self.delete_selected)
        for b in (self.btn_scan, self.btn_rescan, self.btn_edit, self.btn_del): b.pack(side='left', padx=(0, 8))
        self.btn_more = ttk.Menubutton(tb, text='⋯  Thêm', style='Ghost.TMenubutton')
        self.more = tk.Menu(self.btn_more, tearoff=0); self.btn_more['menu'] = self.more
        self.more.add_command(label='Sao lưu thư viện…', command=self.backup)
        self.more.add_command(label='Khôi phục thư viện từ bản sao lưu…', command=self.restore)
        self.more.add_command(label='Mở thư mục chứa thư viện', command=lambda: self.open_path(DATA_DIR))
        self.more.add_separator(); self.more.add_command(label='Xóa toàn bộ thư viện…', command=self.wipe)
        self.btn_csv = ttk.Button(tb, text='⇩  Xuất CSV', style='Ghost.TButton', command=self.export_csv)
        self.btn_more.pack(side='right'); self.btn_csv.pack(side='right', padx=8)

        sr = tk.Frame(self); sr.pack(fill='x', padx=16, pady=(4, 10)); self.statrow = sr
        self.cards = {}
        for i, (k, t) in enumerate((('hdd', 'Ổ HDD trong thư viện'), ('folders', 'Thư mục'), ('files', 'File'),
                                    ('bytes', 'Tổng dung lượng'), ('online', 'Đang cắm vào máy'))):
            c = tk.Frame(sr, padx=16, pady=9, highlightthickness=1); c.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 10, 0))
            sr.columnconfigure(i, weight=1, uniform='c')
            v = tk.Label(c, text='0', font=F(20, True), anchor='w'); v.pack(anchor='w')
            tl = tk.Label(c, text=t, font=F(9), anchor='w'); tl.pack(anchor='w'); self.cards[k] = (c, v, tl)

        sf = tk.Frame(self); sf.pack(fill='x', padx=16, pady=(0, 4)); self.sf_row = sf
        self.lb_s = tk.Label(sf, text='🔍', font=F(13)); self.lb_s.pack(side='left')
        self.q = tk.StringVar(); self.q.trace_add('write', lambda *_: self._debounce())
        self.ent = ttk.Entry(sf, textvariable=self.q, style='Search.TEntry', font=F(12)); self.ent.pack(side='left', fill='x', expand=True, padx=(8, 8), ipady=5)
        ttk.Button(sf, text='✕', width=3, style='Ghost.TButton', command=lambda: self.q.set('')).pack(side='left', padx=(0, 8))
        self.kind = tk.StringVar(value=KIND_LABELS[0])
        cb = ttk.Combobox(sf, textvariable=self.kind, state='readonly', width=13, font=F(10), values=KIND_LABELS); cb.pack(side='left')
        cb.bind('<<ComboboxSelected>>', lambda e: self._searched())
        self.btn_more_rows = ttk.Button(sf, text='Xem thêm', style='Ghost.TButton', command=self.more_rows)
        self.lb_count = tk.Label(sf, text='', font=F(10, True), padx=12); self.lb_count.pack(side='left')
        self.hint = tk.Label(self, text=HINT, font=F(9), anchor='w'); self.hint.pack(fill='x', padx=16, pady=(0, 8))

        pw = ttk.PanedWindow(self, orient='horizontal'); pw.pack(fill='both', expand=True, padx=16, pady=(0, 6))
        left = tk.Frame(pw, width=self.px(310), height=10); left.pack_propagate(False); pw.add(left, weight=0); self.left = left
        self.lb_side = tk.Label(left, text='  Ổ HDD TRONG THƯ VIỆN', font=F(8, True), anchor='w'); self.lb_side.pack(fill='x', pady=(0, 4))
        self.info = tk.Label(left, text='', font=F(9), justify='left', anchor='nw', padx=12, pady=10, wraplength=self.px(250))
        self.info.pack(side='bottom', fill='x', pady=(6, 0))
        hw = tk.Frame(left); hw.pack(fill='both', expand=True)
        self.hl = ttk.Treeview(hw, columns=('n',), show='tree', selectmode='browse')
        self.hl.column('#0', width=self.px(200), minwidth=self.px(120)); self.hl.column('n', width=self.px(62), minwidth=self.px(62), stretch=False, anchor='e')
        sbl = ttk.Scrollbar(hw, command=self.hl.yview); self.hl.configure(yscrollcommand=sbl.set)
        sbl.pack(side='right', fill='y'); self.hl.pack(fill='both', expand=True)
        self.hl.bind('<<TreeviewSelect>>', lambda e: self.on_sidebar())

        self.body = tk.Frame(pw); pw.add(self.body, weight=1)
        self.nb = ttk.Notebook(self.body); self.nb.pack(fill='both', expand=True)
        t_files, t_fold, t_tree = ttk.Frame(self.nb), ttk.Frame(self.nb), ttk.Frame(self.nb)
        self.nb.add(t_files, text='   📋  Tìm file   '); self.nb.add(t_fold, text='   📁  Thư mục   '); self.nb.add(t_tree, text='   🌲  Cây thư mục   ')
        self.nb.bind('<<NotebookTabChanged>>', lambda e: self.refresh_tab())

        fcols = ('code', 'name', 'ext', 'size', 'mtime', 'hdd', 'folder')
        self.tv = self.make_table(t_files, fcols, ('Mã', 'Tên file', 'Loại', 'Dung lượng', 'Ngày sửa', 'Ổ', 'Thư mục'),
                                  (118, 430, 62, 92, 128, 56, 330), {'size', 'ext'}, 'files')
        self.tv.bind('<<TreeviewSelect>>', lambda e: self.on_select_file()); self.tv.bind('<Double-1>', lambda e: self.open_folder())
        self.tv.bind('<Button-3>', lambda e: self.popup(e, self.tv, self.m_file))
        dcols = ('code', 'name', 'hdd', 'path', 'files', 'size')
        self.tf = self.make_table(t_fold, dcols, ('Mã', 'Tên thư mục', 'Ổ', 'Đường dẫn', 'File', 'Dung lượng'),
                                  (118, 340, 56, 400, 60, 100), {'files', 'size'}, 'folders')
        self.tf.bind('<<TreeviewSelect>>', lambda e: self.on_select_folder()); self.tf.bind('<Double-1>', lambda e: self.filter_folder())
        self.tf.bind('<Button-3>', lambda e: self.popup(e, self.tf, self.m_fold))

        self.tr = ttk.Treeview(t_tree, columns=('code', 'n', 'size'), selectmode='browse')
        self.tr.heading('#0', text='  Ổ HDD / Thư mục / File', anchor='w'); self.tr.heading('code', text='Mã', anchor='w')
        self.tr.heading('n', text='File', anchor='e'); self.tr.heading('size', text='Dung lượng', anchor='e')
        self.tr.column('#0', width=self.px(560)); self.tr.column('code', width=self.px(120)); self.tr.column('n', width=self.px(70), anchor='e')
        self.tr.column('size', width=self.px(100), anchor='e')
        sby = ttk.Scrollbar(t_tree, command=self.tr.yview); self.tr.configure(yscrollcommand=sby.set)
        sby.pack(side='right', fill='y'); self.tr.pack(side='left', fill='both', expand=True)
        self.tr.bind('<<TreeviewOpen>>', lambda e: self.populate(self.tr.focus())); self.tr.bind('<<TreeviewSelect>>', lambda e: self.on_select_tree())
        self.tr.bind('<Button-3>', lambda e: self.popup(e, self.tr, self.m_tree))

        self.empty = tk.Frame(self.body)
        self.em_icon = tk.Label(self.empty, text='💽', font=F(46)); self.em_icon.pack(pady=(self.px(110), 8))
        self.em_t = tk.Label(self.empty, text='Thư viện đang trống', font=F(18, True)); self.em_t.pack()
        self.em_s = tk.Label(self.empty, text='Cắm ổ HDD vào máy rồi bấm nút bên dưới.\nTool quét toàn bộ thư mục và tên file, đánh mã số để bạn tìm kiếm nhanh.',
                             font=F(10), justify='center'); self.em_s.pack(pady=(6, 16))
        ttk.Button(self.empty, text='＋  Quét ổ HDD đầu tiên', style='Accent.TButton', command=self.open_scan_dialog).pack()

        d = tk.Frame(self, highlightthickness=1); d.pack(fill='x', padx=16, pady=(0, 8), side='bottom'); self.detail = d
        dl = tk.Frame(d); dl.pack(side='left', fill='x', expand=True, padx=12, pady=8); self.dl = dl
        self.d1 = tk.Label(dl, text='Chọn một file hoặc thư mục để xem chi tiết', font=F(10, True), anchor='w'); self.d1.pack(fill='x')
        self.d2 = tk.Label(dl, text='', font=F(9), anchor='w', justify='left'); self.d2.pack(fill='x')
        dr = tk.Frame(d); dr.pack(side='right', padx=10); self.dr = dr
        for t, c in (('Mở thư mục', self.open_folder), ('Sao chép đường dẫn', self.copy_path), ('Sao chép mã', self.copy_code)):
            ttk.Button(dr, text=t, style='Ghost.TButton', command=c).pack(side='left', padx=3, pady=8)

        self.m_file = tk.Menu(self, tearoff=0); self.m_fold = tk.Menu(self, tearoff=0); self.m_tree = tk.Menu(self, tearoff=0)
        for m in (self.m_file, self.m_fold, self.m_tree):
            m.add_command(label='Mở thư mục (nếu ổ đang cắm)', command=self.open_folder)
            m.add_command(label='Sao chép đường dẫn đầy đủ', command=self.copy_path)
            m.add_command(label='Sao chép mã', command=self.copy_code)
        self.m_file.add_command(label='Sao chép tên file', command=self.copy_name); self.m_file.add_separator()
        self.m_file.add_command(label='Chỉ xem file trong thư mục này', command=self.filter_folder)
        self.m_file.add_command(label='Xem trong cây thư mục', command=self.reveal)
        self.m_fold.add_separator(); self.m_fold.add_command(label='Xem file trong thư mục này', command=self.filter_folder)
        self.m_fold.add_command(label='Xem trong cây thư mục', command=self.reveal)

    def make_table(self, parent, cols, heads, widths, right, key):
        wrap = ttk.Frame(parent); wrap.pack(fill='both', expand=True)
        tv = ttk.Treeview(wrap, columns=cols, show='headings', selectmode='browse')
        tv._heads = dict(zip(cols, heads)); tv._key = key
        for c, h, w in zip(cols, heads, widths):
            tv.heading(c, text=h, anchor='e' if c in right else 'w', command=lambda c=c, k=key: self.sort_by(k, c))
            tv.column(c, width=self.px(w), anchor='e' if c in right else 'w', stretch=c in ('name', 'folder', 'path'))
        sb = ttk.Scrollbar(wrap, command=tv.yview); tv.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y'); tv.pack(side='left', fill='both', expand=True)
        return tv

    # ------------------------------------------------------------------ giao diện: màu sắc
    def apply_theme(self):
        C = self.C = THEMES[self.theme]; s = ttk.Style(self)
        try: s.theme_use('clam')
        except tk.TclError: pass
        self.configure(bg=C['bg'])
        s.configure('.', background=C['bg'], foreground=C['fg'], fieldbackground=C['panel'], bordercolor=C['line'], lightcolor=C['line'],
                    darkcolor=C['line'], troughcolor=C['panel'], font=F(10))
        s.configure('TFrame', background=C['bg']); s.configure('TPanedwindow', background=C['bg'])
        s.configure('TLabel', background=C['bg'], foreground=C['fg'])
        s.configure('Treeview', background=C['panel'], fieldbackground=C['panel'], foreground=C['fg'], rowheight=self.px(28), borderwidth=0, font=F(10))
        s.map('Treeview', background=[('selected', C['sel'])], foreground=[('selected', '#ffffff' if self.theme == 'dark' else C['fg'])])
        s.configure('Treeview.Heading', background=C['head'], foreground=C['muted'], relief='flat', font=F(9, True), padding=(8, 7), borderwidth=0)
        s.map('Treeview.Heading', background=[('active', C['card'])])
        s.configure('TNotebook', background=C['bg'], borderwidth=0, tabmargins=(0, 0, 0, 0))
        s.configure('TNotebook.Tab', background=C['bg'], foreground=C['muted'], padding=(14, 8), borderwidth=0, font=F(10, True))
        s.map('TNotebook.Tab', background=[('selected', C['panel'])], foreground=[('selected', C['accent'])])
        for name, bg, hv, fg in (('Accent', C['accent'], C['accent_h'], '#ffffff'), ('Danger', C['danger'], C['danger_h'], '#ffffff'),
                                 ('Ghost', C['card'], C['line'], C['fg']), ('GhostDanger', C['card'], C['line'], C['danger'])):
            s.configure(f'{name}.TButton', background=bg, foreground=fg, borderwidth=0, focusthickness=0, padding=(14, 8),
                        font=F(10, name in ('Accent', 'Danger')), relief='flat')
            s.map(f'{name}.TButton', background=[('active', hv), ('disabled', C['line'])], foreground=[('disabled', C['dim'])])
        s.configure('Ghost.TMenubutton', background=C['card'], foreground=C['fg'], borderwidth=0, padding=(14, 8), relief='flat', arrowcolor=C['muted'])
        s.map('Ghost.TMenubutton', background=[('active', C['line'])])
        s.configure('TEntry', fieldbackground=C['panel'], foreground=C['fg'], insertcolor=C['fg'], bordercolor=C['line'], padding=4)
        s.configure('Search.TEntry', fieldbackground=C['panel'], foreground=C['fg'], insertcolor=C['fg'], bordercolor=C['line'], padding=6)
        s.map('Search.TEntry', bordercolor=[('focus', C['accent'])], lightcolor=[('focus', C['accent'])], darkcolor=[('focus', C['accent'])])
        s.configure('TCombobox', fieldbackground=C['panel'], background=C['card'], foreground=C['fg'], arrowcolor=C['fg'], bordercolor=C['line'], padding=5)
        s.map('TCombobox', fieldbackground=[('readonly', C['panel'])], foreground=[('readonly', C['fg'])])
        for k, v in (('background', C['panel']), ('foreground', C['fg']), ('selectBackground', C['accent']), ('selectForeground', '#ffffff')):
            self.option_add(f'*TCombobox*Listbox.{k}', v)
        s.configure('TCheckbutton', background=C['bg'], foreground=C['fg']); s.map('TCheckbutton', background=[('active', C['bg'])])
        s.configure('TScrollbar', background=C['card'], troughcolor=C['bg'], bordercolor=C['bg'], arrowcolor=C['muted'], relief='flat')
        s.configure('Pro.Horizontal.TProgressbar', background=C['accent'], troughcolor=C['card'], bordercolor=C['card'],
                    lightcolor=C['accent'], darkcolor=C['accent'], thickness=10)

        for w in (self.tb, self.statrow, self.sf_row): w.configure(bg=C['bg'])
        self.header.configure(bg=C['head']); self.sep.configure(bg=C['line'])
        self._tint(self.header, C['head'])
        self.lb_title.configure(fg=C['fg']); self.lb_sub.configure(fg=C['muted']); self.lb_new.configure(bg=C['head'], fg=C['ok'])
        self.draw_logo()
        self.lb_s.configure(bg=C['bg'], fg=C['muted']); self.lb_count.configure(bg=C['bg'], fg=C['muted']); self.hint.configure(bg=C['bg'], fg=C['dim'])
        self.status.configure(bg=C['head'], fg=C['muted'])
        for k, (c, v, tl) in self.cards.items():
            c.configure(bg=C['card'], highlightbackground=C['line'], highlightcolor=C['line'])
            v.configure(bg=C['card'], fg=C['accent'] if k != 'online' else C['ok']); tl.configure(bg=C['card'], fg=C['muted'])
        self.left.configure(bg=C['bg']); self.lb_side.configure(bg=C['bg'], fg=C['dim']); self.info.configure(bg=C['card'], fg=C['muted'])
        self.body.configure(bg=C['bg']); self.empty.configure(bg=C['panel'])
        for w in (self.em_icon, self.em_t, self.em_s): w.configure(bg=C['panel'])
        self.em_t.configure(fg=C['fg']); self.em_s.configure(fg=C['muted'])
        self.detail.configure(bg=C['card'], highlightbackground=C['line'], highlightcolor=C['line'])
        for w in (self.dl, self.dr, self.d1, self.d2): w.configure(bg=C['card'])
        self.d1.configure(fg=C['fg']); self.d2.configure(fg=C['muted'])
        for m in (self.m_file, self.m_fold, self.m_tree, self.more):
            m.configure(bg=C['panel'], fg=C['fg'], activebackground=C['accent'], activeforeground='#ffffff', bd=0)
        for t in (self.tv, self.tf):
            t.tag_configure('odd', background=C['zebra'])
        for t in (self.hl, self.tr):
            t.tag_configure('off', foreground=C['dim']); t.tag_configure('on', foreground=C['fg'])
        self.tr.tag_configure('file', foreground=C['muted']); self.tr.tag_configure('hdd', foreground=C['accent'])

    def _tint(self, w, bg):
        try: w.configure(bg=bg)
        except tk.TclError: pass
        for ch in w.winfo_children(): self._tint(ch, bg)

    def draw_logo(self):
        c = self.logo; C = self.C; c.delete('all'); s = self.px(40); c.configure(bg=C['head']); r = self.px(10)
        pts = [r, 1, s - r, 1, s - 1, 1, s - 1, r, s - 1, s - r, s - 1, s - 1, s - r, s - 1, r, s - 1, 1, s - 1, 1, s - r, 1, r, 1, 1]
        c.create_polygon(pts, smooth=True, fill=C['accent'], outline='')
        c.create_polygon(s * .40, s * .29, s * .40, s * .71, s * .73, s * .50, fill='#ffffff', outline='')

    def toggle_theme(self):
        self.theme = 'light' if self.theme == 'dark' else 'dark'; self.apply_theme()
        self.settings['theme'] = self.theme; save_settings(self.settings); self.refresh_sidebar(); self.mark_dirty(); self.refresh_tab()

    # ------------------------------------------------------------------ dữ liệu & làm mới
    def root_for(self, h):
        """Đường dẫn gốc thật của ổ nếu đang cắm (khớp theo serial, nên đổi ký tự ổ vẫn nhận ra), ngược lại None."""
        if h['serial']:
            d = drives.find_by_serial(self.drives, h['serial'])
            return d['root'] if d else None
        return h['root'] if os.path.isdir(h['root']) else None

    def hdd_row(self, hid): return L.hdd_row(self.con, hid)

    def refresh_all(self):
        self.refresh_stats(); self.refresh_sidebar(); self.mark_dirty(); self.refresh_tab()

    def refresh_stats(self):
        t = L.totals(self.con); online = sum(1 for h in L.list_hdds(self.con) if self.root_for(h))
        self.cards['hdd'][1].config(text=f"{t['hdd']:,}"); self.cards['folders'][1].config(text=f"{t['folders']:,}")
        self.cards['files'][1].config(text=f"{t['files']:,}"); self.cards['bytes'][1].config(text=fmt_size(t['bytes']))
        self.cards['online'][1].config(text=f"{online}/{t['hdd']}")
        if t['hdd'] == 0: self.empty.place(relx=0, rely=0, relwidth=1, relheight=1); self.empty.lift()
        else: self.empty.place_forget()
        for b in (self.btn_rescan, self.btn_edit, self.btn_del): b.config(state='normal' if t['hdd'] else 'disabled')

    def refresh_sidebar(self):
        self._lock = True
        try:
            self.hl.delete(*self.hl.get_children()); t = L.totals(self.con)
            self.hl.insert('', 'end', iid='all', text='  ▣   Tất cả ổ HDD', values=(f"{t['files']:,}",), tags=('on',))
            ids = set()
            for h in L.list_hdds(self.con):
                on = self.root_for(h) is not None; ids.add(h['id'])
                self.hl.insert('', 'end', iid=f"h{h['id']}", text=f"  {'●' if on else '○'}   {h['code']}  ·  {h['name']}",
                               values=(f"{h['nfiles']:,}",), tags=('on' if on else 'off',))
            if self.hid not in ids: self.hid = None
            self.hl.selection_set(f'h{self.hid}' if self.hid else 'all')
        finally:
            self._lock = False
        self.update_info()

    def update_info(self):
        if not self.hid:
            t = L.totals(self.con)
            self.info.config(text=f"Toàn bộ thư viện\n{t['hdd']} ổ • {t['files']:,} file\n{fmt_size(t['bytes'])} dữ liệu\n\nChọn một ổ ở trên để lọc.")
            return
        h = self.hdd_row(self.hid); root = self.root_for(h)
        used = max(0, (h['total'] or 0) - (h['free'] or 0))
        self.info.config(text=(f"{h['code']}  ·  {h['name']}\n"
                               f"{'● Đang cắm (' + root.rstrip(chr(92)) + ')' if root else '○ Chưa cắm vào máy'}\n"
                               f"{h['nfiles']:,} file • {h['nfolders']:,} thư mục\n{fmt_size(h['bytes'])} phim/dữ liệu đã quét\n"
                               f"Ổ: {fmt_size(used)} / {fmt_size(h['total'])}\nQuét lúc {h['scanned_at'] or '—'}"))

    def on_sidebar(self):
        s = self.hl.selection()
        new = int(s[0][1:]) if s and s[0] != 'all' else None
        if self._lock or new == self.hid: return          # sự kiện đến trễ do code tự chọn dòng: bỏ qua
        self.hid = new
        self.update_info(); self.mark_dirty(); self.refresh_tab()

    def mark_dirty(self): self.dirty = {'files', 'folders', 'tree'}

    def tab_name(self): return ('files', 'folders', 'tree')[self.nb.index(self.nb.select())]

    def refresh_tab(self):
        n = self.tab_name()
        if n not in self.dirty: return
        self.dirty.discard(n); getattr(self, 'load_' + n)()

    def _debounce(self):
        if self._after: self.after_cancel(self._after)
        self._after = self.after(220, self._searched)

    def _searched(self):
        self.limit = 5000; self.dirty.update({'files', 'folders'}); self.dirty.discard(self.tab_name()); self.run_tab()

    def run_tab(self):
        n = self.tab_name()
        if n == 'files': self.load_files()
        elif n == 'folders': self.load_folders()

    def kind_key(self): return KIND_KEYS[KIND_LABELS.index(self.kind.get())]

    def sort_by(self, key, col):
        c, d = self.sort[key]; self.sort[key] = (col, (not d) if c == col else False)
        self.limit = 5000; (self.load_files if key == 'files' else self.load_folders)()

    def mark_heads(self, tv, key):
        c, d = self.sort[key]
        for col, txt in tv._heads.items(): tv.heading(col, text=txt + (('  ▼' if d else '  ▲') if col == c else ''))

    def more_rows(self):
        self.limit += 5000; self.run_tab()

    def count_label(self, total, shown, noun):
        self.lb_count.config(text=f'{total:,} {noun}' if shown >= total else f'{shown:,} / {total:,} {noun}')
        if shown < total: self.btn_more_rows.pack(side='left', before=self.lb_count)
        else: self.btn_more_rows.pack_forget()

    # ------------------------------------------------------------------ tab: tìm file
    def load_files(self):
        col, desc = self.sort['files']; self.mark_heads(self.tv, 'files')
        total, rows = L.search_files(self.con, self.q.get(), self.kind_key(), self.hid, col, desc, self.limit)
        self.tv.delete(*self.tv.get_children()); self.rows = {}
        for i, r in enumerate(rows):
            iid = f"f{r['id']}"; self.rows[iid] = r
            self.tv.insert('', 'end', iid=iid, tags=('odd',) if i % 2 else (),
                           values=(r['code'], r['name'], r['ext'].lstrip('.').upper(), fmt_size(r['size']), L.fmt_time(r['mtime']), r['hcode'], r['path'] or '\\'))
        self.count_label(total, len(rows), 'file'); self.set_status_search(total)

    def set_status_search(self, total):
        self.last_total = total; t = L.totals(self.con)
        self.status.config(text='  Thư viện trống — bấm "Quét ổ HDD" để bắt đầu.' if not t['hdd'] else
                           f'  {total:,} kết quả  •  {t["files"]:,} file trong {t["hdd"]} ổ HDD  •  Thư viện: {DATA_DIR}')

    def on_select_file(self):
        s = self.tv.selection()
        if not s: return
        r = self.rows[s[0]]
        self.cur = dict(type='file', id=r['id'], code=r['code'], name=r['name'], hid=r['hid'], rel=r['path'], hcode=r['hcode'])
        self.d1.config(text=f"{r['name']}");
        self.d2.config(text=f"Mã {r['code']}   •   Thư mục {r['fcode']}   •   Ổ {r['hcode']} · {r['hname']}   •   {fmt_size(r['size'])}   •   {L.fmt_time(r['mtime'])}\n{self.path_text(self.cur)}")

    # ------------------------------------------------------------------ tab: thư mục
    def load_folders(self):
        col, desc = self.sort['folders']; self.mark_heads(self.tf, 'folders')
        total, rows = L.search_folders(self.con, self.q.get(), self.hid, col, desc, self.limit)
        self.tf.delete(*self.tf.get_children()); self.rows = {}
        for i, r in enumerate(rows):
            iid = f"d{r['id']}"; self.rows[iid] = r
            self.tf.insert('', 'end', iid=iid, tags=('odd',) if i % 2 else (),
                           values=(r['code'], r['name'], r['hcode'], r['path'] or '\\', f"{r['nfiles']:,}", fmt_size(r['bytes'])))
        self.count_label(total, len(rows), 'thư mục'); self.set_status_search(total)

    def on_select_folder(self):
        s = self.tf.selection()
        if not s: return
        r = self.rows[s[0]]
        self.cur = dict(type='folder', id=r['id'], code=r['code'], name=r['name'], hid=r['hid'], rel=r['path'], hcode=r['hcode'])
        self.d1.config(text=r['name'])
        self.d2.config(text=f"Mã {r['code']}   •   Ổ {r['hcode']} · {r['hname']}   •   {r['nfiles']:,} file   •   {fmt_size(r['bytes'])}\n{self.path_text(self.cur)}")

    def filter_folder(self):
        """Lọc tab 'Tìm file' chỉ còn các file thuộc thư mục đang chọn (bằng mã thư mục)."""
        if not self.cur: return
        code = self.cur['code'] if self.cur['type'] == 'folder' else L.file_row(self.con, self.cur['id'])['fcode']
        self.q.set(code); self.nb.select(0)

    # ------------------------------------------------------------------ tab: cây thư mục
    def load_tree(self):
        self.tr.delete(*self.tr.get_children())
        for h in L.list_hdds(self.con):
            if self.hid and h['id'] != self.hid: continue
            on = self.root_for(h) is not None
            n = f"h{h['id']}"
            self.tr.insert('', 'end', iid=n, text=f"  💽  {h['name']}", values=(h['code'], f"{h['nfiles']:,}", fmt_size(h['bytes'])), tags=('hdd',))
            self.tr.insert(n, 'end', iid='x' + n, text='…')
        self.status.config(text='  Cây thư mục: bấm ▸ để mở từng cấp. Chuột phải trên file/thư mục để mở, sao chép đường dẫn.')

    def populate(self, node):
        if not node or not self.tr.exists('x' + node): return
        self.tr.delete('x' + node)
        fid = L.root_folder(self.con, int(node[1:])) if node[0] == 'h' else int(node[1:])
        if fid is None: return
        for c in L.child_folders(self.con, fid):
            n = f"d{c['id']}"
            self.tr.insert(node, 'end', iid=n, text=f"  📁  {c['name']}", values=(c['code'], f"{c['tfiles']:,}", fmt_size(c['tbytes'])))
            if self.con.execute("SELECT 1 FROM folder WHERE parent_id=? UNION SELECT 1 FROM file WHERE folder_id=? LIMIT 1", (c['id'], c['id'])).fetchone():
                self.tr.insert(n, 'end', iid='x' + n, text='…')
        for f in L.folder_files(self.con, fid):
            self.tr.insert(node, 'end', iid=f"f{f['id']}", text=f"  🎬  {f['name']}", values=(f['code'], '', fmt_size(f['size'])), tags=('file',))

    def on_select_tree(self):
        s = self.tr.selection()
        if not s: return
        k, i = s[0][0], int(s[0][1:])
        if k == 'f':
            r = L.file_row(self.con, i)
            if not r: return
            self.cur = dict(type='file', id=i, code=r['code'], name=r['name'], hid=r['hid'], rel=r['path'], hcode=r['hcode'])
            self.d1.config(text=r['name']); self.d2.config(text=f"Mã {r['code']}   •   Ổ {r['hcode']} · {r['hname']}   •   {fmt_size(r['size'])}   •   {L.fmt_time(r['mtime'])}\n{self.path_text(self.cur)}")
        elif k == 'd':
            r = L.folder_row(self.con, i)
            if not r: return
            self.cur = dict(type='folder', id=i, code=r['code'], name=r['name'], hid=r['hid'], rel=r['path'], hcode=r['hcode'])
            self.d1.config(text=r['name']); self.d2.config(text=f"Mã {r['code']}   •   Ổ {r['hcode']}   •   {r['tfiles']:,} file (gồm thư mục con)   •   {fmt_size(r['tbytes'])}\n{self.path_text(self.cur)}")
        elif k == 'h':
            h = self.hdd_row(i); root = self.root_for(h)
            self.cur = dict(type='folder', id=L.root_folder(self.con, i), code=h['code'], name=h['name'], hid=i, rel='', hcode=h['code'])
            self.d1.config(text=f"{h['code']} · {h['name']}"); self.d2.config(text=f"{h['nfiles']:,} file • {fmt_size(h['bytes'])}\n{root or '(ổ chưa cắm vào máy)'}")

    def reveal(self):
        """Nhảy sang Cây thư mục và mở tới đúng file / thư mục đang chọn."""
        if not self.cur: return
        cur = dict(self.cur); self.hid = None; self.refresh_sidebar(); self.mark_dirty()
        self.nb.select(2); self.update_idletasks(); self.refresh_tab()
        did = cur['id'] if cur['type'] == 'folder' else L.file_row(self.con, cur['id'])['fid']
        chain = []
        while did is not None:
            chain.append(did); r = L.folder_row(self.con, did); did = r['parent_id'] if r else None
        node = f"h{cur['hid']}"; self.populate(node); self.tr.item(node, open=True)
        for fid in reversed(chain[:-1]):
            node = f'd{fid}'
            if not self.tr.exists(node): break
            self.populate(node); self.tr.item(node, open=True)
        target = f"f{cur['id']}" if cur['type'] == 'file' else node
        if self.tr.exists(target): self.tr.selection_set(target); self.tr.focus(target); self.tr.see(target)

    # ------------------------------------------------------------------ thao tác file / thư mục
    def path_text(self, cur):
        h = self.hdd_row(cur['hid']); root = self.root_for(h)
        p = L.full_path(root or '', cur['rel'], cur['name'] if cur['type'] == 'file' else None) if root else \
            '\\' + '\\'.join(x for x in ((cur['rel'] or '').split('\\') + ([cur['name']] if cur['type'] == 'file' else [])) if x)
        return (p if root else f"(ổ {h['code']} chưa cắm)  {p}")

    def real_path(self, cur=None):
        cur = cur or self.cur
        if not cur: return None
        root = self.root_for(self.hdd_row(cur['hid']))
        return L.full_path(root, cur['rel'], cur['name'] if cur['type'] == 'file' else None) if root else None

    def need_cur(self):
        if not self.cur: messagebox.showinfo('Chưa chọn', 'Hãy chọn một file hoặc thư mục trước.'); return False
        return True

    def open_folder(self):
        if not self.need_cur(): return
        p = self.real_path()
        if not p or not os.path.exists(p):
            messagebox.showinfo('Không mở được', f"Ổ {self.cur['hcode']} chưa cắm vào máy hoặc file/thư mục đã bị di chuyển.\n\n{self.path_text(self.cur)}"); return
        if sys.platform == 'win32':
            if os.path.isfile(p): subprocess.Popen(['explorer', '/select,' + p])
            else: os.startfile(p)
        else:
            subprocess.Popen(['xdg-open', p if os.path.isdir(p) else os.path.dirname(p)])

    def to_clipboard(self, text):
        self.clipboard_clear(); self.clipboard_append(text); self.status.config(text=f'  Đã sao chép: {text}')

    def copy_path(self):
        if self.need_cur(): self.to_clipboard(self.real_path() or self.path_text(self.cur).split('  ', 1)[-1])

    def copy_code(self):
        if self.need_cur(): self.to_clipboard(self.cur['code'])

    def copy_name(self):
        if self.need_cur(): self.to_clipboard(self.cur['name'])

    def popup(self, ev, tv, menu):
        i = tv.identify_row(ev.y)
        if not i: return
        tv.selection_set(i); tv.focus(i); self.update_idletasks()
        menu.tk_popup(ev.x_root, ev.y_root)

    def open_path(self, p):
        if sys.platform == 'win32': os.startfile(p)
        else: subprocess.Popen(['xdg-open', p])

    # ------------------------------------------------------------------ quét ổ
    def refresh_drives_async(self):
        def work():
            try: d = drives.list_drives()
            except Exception: d = []
            self.msgs.put(('drives', d))
        threading.Thread(target=work, daemon=True).start()

    def open_scan_dialog(self):
        if self.scanning: return
        ScanDialog(self, self.start_scan)

    def rescan_selected(self):
        if self.scanning: return
        if not self.hid:
            messagebox.showinfo('Quét lại', 'Hãy chọn một ổ HDD ở danh sách bên trái rồi bấm "Quét lại".'); return
        h = self.hdd_row(self.hid); root = self.root_for(h)
        if not root:
            messagebox.showinfo('Ổ chưa cắm', f"Ổ {h['code']} · {h['name']} chưa cắm vào máy.\nCắm ổ rồi thử lại (hoặc dùng \"Quét ổ HDD\" để chọn lại)."); return
        if not messagebox.askyesno('Quét lại ổ', f"Quét lại ổ {h['code']} · {h['name']}?\nDữ liệu cũ của ổ này sẽ được thay bằng kết quả quét mới (mã ổ giữ nguyên)."): return
        d = drives.find_by_serial(self.drives, h['serial']) if h['serial'] else None
        self.start_scan(root, h['name'], d, False, h['id'])

    def start_scan(self, root, name, drive, media_only, replace_id):
        if self.scanning: return
        dlg = self.scanning = ScanProgress(self, name or root)
        def work():
            try:
                r = scanner.scan_hdd(DB_PATH, root, name, drive, dlg.cancel_event,
                                     lambda *a: self.msgs.put(('scan_progress', a)), media_only, replace_id)
                self.msgs.put(('scan_done', r))
            except scanner.Cancelled:
                self.msgs.put(('scan_cancel', None))
            except Exception as ex:
                self.msgs.put(('scan_err', str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def scan_finished(self):
        try: self.scanning.destroy()
        except Exception: pass
        self.scanning = None

    # ------------------------------------------------------------------ hộp thư tín & vòng lặp
    def pump(self):
        try:
            while True:
                kind, p = self.msgs.get_nowait()
                if kind == 'scan_progress' and self.scanning: self.scanning.update_stats(*p)
                elif kind == 'scan_done':
                    self.scan_finished(); self.hid = p['hid']; self.drives = drives.list_drives(); self.refresh_all()
                    messagebox.showinfo('Quét xong', f"Ổ {p['code']} · {p['name']}\n\n{p['files']:,} file • {p['folders']:,} thư mục • {fmt_size(p['bytes'])}\n"
                                        f"Thời gian: {p['seconds']:.0f} giây" + (f"\nBỏ qua {p['errors']} mục không đọc được (không có quyền)." if p['errors'] else '')
                                        + ('\n\nĐã thêm ổ mới vào thư viện.' if p['new'] else '\n\nĐã cập nhật dữ liệu mới của ổ.'))
                elif kind == 'scan_cancel':
                    self.scan_finished(); messagebox.showinfo('Đã hủy', 'Đã hủy quét. Thư viện giữ nguyên như cũ.')
                elif kind == 'scan_err':
                    self.scan_finished(); messagebox.showerror('Lỗi quét', f'Không quét được:\n{p}')
                elif kind == 'drives': self.drives = p; self.refresh_stats(); self.refresh_sidebar()
                elif kind == 'update_info': self.on_update_info(*p)
                elif kind == 'dl': self.on_download_progress(*p)
                elif kind == 'dl_done': self.on_download_done(*p)
        except queue.Empty:
            pass
        self.after(100, self.pump)

    # ------------------------------------------------------------------ quản lý thư viện
    def edit_selected(self):
        if not self.hid: messagebox.showinfo('Sửa ổ', 'Hãy chọn một ổ HDD ở danh sách bên trái.'); return
        h = self.hdd_row(self.hid)
        EditHdd(self, h, lambda name, code: (L.rename_hdd(self.con, h['id'], name, code), self.refresh_all()))

    def delete_selected(self):
        if not self.hid: messagebox.showinfo('Xóa ổ', 'Hãy chọn một ổ HDD ở danh sách bên trái.'); return
        h = self.hdd_row(self.hid)
        if messagebox.askyesno('Xóa ổ khỏi thư viện', f"Xóa ổ {h['code']} · {h['name']} ({h['nfiles']:,} file) khỏi thư viện?\n(Không xóa gì trên ổ cứng thật.)"):
            L.delete_hdd(self.con, h['id']); self.hid = None; self.refresh_all()

    def wipe(self):
        if not L.totals(self.con)['hdd']: messagebox.showinfo('Xóa thư viện', 'Thư viện đang trống.'); return
        if messagebox.askyesno('Xóa toàn bộ thư viện', 'Xóa SẠCH toàn bộ thư viện (mọi ổ, thư mục, file đã quét)?\nKhông ảnh hưởng dữ liệu trên ổ cứng thật.\n\nNên sao lưu trước.', icon='warning'):
            L.wipe_all(self.con); self.hid = None; self.refresh_all()

    def backup(self):
        p = filedialog.asksaveasfilename(defaultextension='.db', filetypes=[('Thư viện My Movie Library', '*.db')],
                                         initialfile=f"MyMovieLibrary_{time.strftime('%Y%m%d')}.db")
        if not p: return
        dst = sqlite3.connect(p); self.con.backup(dst); dst.close(); messagebox.showinfo('Sao lưu', f'Đã sao lưu thư viện:\n{p}')

    def restore(self):
        p = filedialog.askopenfilename(filetypes=[('Thư viện My Movie Library', '*.db')], title='Chọn file sao lưu')
        if not p: return
        try:
            src = sqlite3.connect(p); src.execute('SELECT COUNT(*) FROM hdd'); src.execute('SELECT COUNT(*) FROM file')
        except sqlite3.DatabaseError:
            messagebox.showerror('Khôi phục', 'File này không phải bản sao lưu của My Movie Library.'); return
        if not messagebox.askyesno('Khôi phục', 'Thay toàn bộ thư viện hiện tại bằng bản sao lưu này?'): src.close(); return
        src.backup(self.con); src.close(); self.con.executescript(L.SCHEMA); self.hid = None; self.refresh_all()
        messagebox.showinfo('Khôi phục', 'Đã khôi phục thư viện.')

    def export_csv(self):
        n = self.tab_name()
        if n == 'folders':
            total, rows = L.search_folders(self.con, self.q.get(), self.hid, *self.sort['folders'], None)
            head = ['Mã thư mục', 'Tên thư mục', 'Mã ổ', 'Tên ổ', 'Đường dẫn trong ổ', 'Số file', 'Dung lượng (byte)']
            data = [[r['code'], r['name'], r['hcode'], r['hname'], '\\' + r['path'], r['nfiles'], r['bytes']] for r in rows]
        else:
            total, rows = L.search_files(self.con, self.q.get(), self.kind_key(), self.hid, *self.sort['files'], None)
            head = ['Mã file', 'Tên file', 'Đuôi', 'Loại', 'Dung lượng (byte)', 'Dung lượng', 'Ngày sửa', 'Mã thư mục', 'Mã ổ', 'Tên ổ', 'Đường dẫn trong ổ']
            data = [[r['code'], r['name'], r['ext'], L.KINDS.get(r['kind'], ''), r['size'], fmt_size(r['size']), L.fmt_time(r['mtime']), r['fcode'],
                     r['hcode'], r['hname'], '\\' + (r['path'] + '\\' if r['path'] else '') + r['name']] for r in rows]
        if not data: messagebox.showinfo('Xuất CSV', 'Không có dữ liệu để xuất.'); return
        p = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')], initialfile='thu_vien_phim.csv')
        if not p: return
        with open(p, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f); w.writerow(head); w.writerows(data)
        messagebox.showinfo('Xuất CSV', f'Đã xuất {len(data):,} dòng (kết quả đang lọc):\n{p}')

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
        self.btn_update.config(state='normal'); self.set_status_search(self.last_total)
        newer = bool(rel and updater.is_newer(rel['version']))
        if newer: self.new_release = rel; self.lb_new.config(text=f'● Có bản mới v{rel["version"]}')
        if silent: return
        if err: messagebox.showerror('Update', f'Không kiểm tra được bản mới (cần Internet):\n{err}'); return
        if rel is None: messagebox.showinfo('Update', f'Chưa có bản phát hành nào trên GitHub.\nBạn đang dùng v{APP_VERSION}.'); return
        if not newer: messagebox.showinfo('Update', f'Bạn đang dùng bản mới nhất (v{APP_VERSION}).'); return
        notes = (rel['notes'] or '').strip()[:700]
        if messagebox.askyesno('Có bản cập nhật', f'Có phiên bản mới v{rel["version"]} (hiện tại v{APP_VERSION}).\n\n{notes}\n\nCập nhật ngay? (Thư viện của bạn được giữ nguyên.)'):
            self.start_download(rel)

    def start_download(self, rel):
        if FROZEN:
            if not rel['exe_url']: webbrowser.open(rel['page']); return
            url, dest = rel['exe_url'], os.path.join(APP_DIR, 'My Movie Library.update.exe')
        else:
            if not rel['zip_url']: webbrowser.open(rel['page']); return
            url, dest = rel['zip_url'], os.path.join(tempfile.gettempdir(), 'mml_source.zip')
        self.status.config(text='  Đang tải bản cập nhật…')
        def work():
            try:
                updater.download(url, dest, lambda g, t: self.msgs.put(('dl', (g, t)))); self.msgs.put(('dl_done', (dest, None)))
            except Exception as ex:
                self.msgs.put(('dl_done', (dest, str(ex))))
        threading.Thread(target=work, daemon=True).start()

    def on_download_progress(self, got, total):
        if total: self.status.config(text=f'  Đang tải bản cập nhật… {got * 100 // total}%  ({got // 1024:,}/{total // 1024:,} KB)')

    def on_download_done(self, path, err):
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
        messagebox.showinfo('Giới thiệu', f'{APP_TITLE}\n\nQuét các ổ HDD, lưu thư mục / file vào thư viện có mã số\nvà tìm kiếm tức thì — kể cả khi ổ không cắm trong máy.\n\n'
                            f'GitHub: github.com/{GITHUB_REPO}\nPhiên bản: {APP_VERSION}\nThư viện: {DB_PATH}')

    def on_close(self):
        if self.scanning and not messagebox.askyesno('Đang quét', 'Đang quét ổ đĩa. Hủy quét và thoát?'): return
        if self.scanning: self.scanning.cancel_event.set()
        try: self.con.close()
        except Exception: pass
        self.destroy()


if __name__ == '__main__':
    if sys.platform == 'win32':
        try:
            import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)      # chữ nét trên màn hình 4K / 125%-150%
        except Exception:
            pass
    App().mainloop()
