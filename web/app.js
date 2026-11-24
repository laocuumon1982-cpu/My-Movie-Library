/* My Movie Library — giao diện web (cùng phong cách PikPak Auto Save). Gọi Python qua pywebview.api (hoặc /api/<tên> ở chế độ --serve). */
"use strict";
window.__errs = [];
window.addEventListener("error", e => window.__errs.push(String(e.message || e)));
window.addEventListener("unhandledrejection", e => window.__errs.push(String(e.reason || e)));

function api(name, ...args) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api[name]) return window.pywebview.api[name](...args);
  return fetch("/api/" + name, {method: "POST", body: JSON.stringify(args)}).then(r => r.json());
}
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fmt = n => Number(n || 0).toLocaleString("vi-VN");
const KIND = {video: "Video", audio: "Audio", sub: "Phụ đề", image: "Ảnh", other: "Khác"};
const TITLES = {files: ["Tìm file", "Tìm tức thì trong mọi ổ HDD đã quét — kể cả khi ổ không cắm trong máy"],
  folders: ["Thư mục", "Các thư mục có file bên trong (thường là thư mục từng phim)"],
  tree: ["Cây thư mục", "Duyệt toàn bộ cấu trúc thư mục của từng ổ"],
  scan: ["Quét & Sao lưu", "Quét ổ HDD → lưu thư viện → sao lưu library.db lên PikPak → tháo ổ"],
  settings: ["Cài đặt", "PikPak, thư viện, cập nhật"]};

const S = {page: "files", hid: 0, q: "", kind: "", sort: {files: ["code", false], folders: ["code", false]}, ov: null, cur: {},
  drives: [], pick: null, logn: 0, scanOn: false, ovKey: "", init: null, treeSel: null};

/* ------------------------------------------------------------------ tiện ích giao diện */
function toast(msg, err) {
  const d = document.createElement("div"); if (err) d.className = "err"; d.textContent = msg; $("toast").appendChild(d);
  setTimeout(() => d.remove(), err ? 6500 : 3500);
}
function dialog(title, bodyHtml, buttons, onOpen) {
  return new Promise(res => {
    const ov = document.createElement("div"); ov.className = "overlay";
    ov.innerHTML = `<div class="dlg"><h3>${esc(title)}</h3><div class="body">${bodyHtml}</div><div class="btns"></div></div>`;
    const bt = ov.querySelector(".btns");
    const close = v => { ov.remove(); res(v); };
    buttons.forEach(b => { const x = document.createElement("button"); x.className = "btn " + (b.cls || ""); x.textContent = b.t; x.onclick = () => close(b.v); bt.appendChild(x); });
    ov.addEventListener("keydown", e => { if (e.key === "Escape") close(null); });
    document.body.appendChild(ov); if (onOpen) onOpen(ov); return ov;
  });
}
const confirmD = (title, msg, ok = "Đồng ý", danger = false) =>
  dialog(title, `<div class="msg">${esc(msg)}</div>`, [{t: "Hủy", v: false}, {t: ok, v: true, cls: danger ? "red" : "red"}]);
const info = (title, msg) => dialog(title, `<div class="msg">${esc(msg)}</div>`, [{t: "Đóng", v: true, cls: "red"}]);
async function copy(text) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) { const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); }
  toast("Đã sao chép: " + text);
}
function status(t) { $("status").textContent = t; }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

/* ------------------------------------------------------------------ điều hướng / giao diện */
function setTheme(t) { document.body.classList.toggle("dark", t === "dark"); S.theme = t; }
function go(p) {
  S.page = p;
  document.querySelectorAll(".nav").forEach(n => n.classList.toggle("on", n.dataset.p === p));
  document.querySelectorAll(".page").forEach(x => x.classList.toggle("on", x.id === "pg-" + p));
  $("ptitle").textContent = TITLES[p][0]; $("psub").textContent = TITLES[p][1];
  refreshPage();
}
function refreshPage() {
  if (S.page === "files") searchFiles();
  else if (S.page === "folders") searchFolders();
  else if (S.page === "tree") loadTree();
  else if (S.page === "scan") loadDrives();
  else if (S.page === "settings") loadSettings();
}

/* ------------------------------------------------------------------ tổng quan + danh sách ổ */
async function overview(force) {
  const ov = await api("overview"); S.ov = ov;
  const key = JSON.stringify([ov.totals, ov.hdds.map(h => [h.id, h.code, h.name, h.online, h.nfiles, h.scanned_at]), ov.scanning, S.hid]);
  if (!force && key === S.ovKey) return; S.ovKey = key;
  const t = ov.totals;
  $("s-hdd").textContent = fmt(t.hdd); $("s-fold").textContent = fmt(t.folders); $("s-file").textContent = fmt(t.files); $("s-size").textContent = t.bytes_txt;
  const on = ov.hdds.filter(h => h.online).length;
  const led = $("aled"); led.className = "led big " + (ov.scanning ? "run" : (t.hdd ? "ok" : "off"));
  $("a1").textContent = ov.scanning ? "Đang quét " + ov.scan_name : (t.hdd ? "Thư viện sẵn sàng" : "Thư viện trống");
  $("a2").textContent = t.hdd ? `${t.hdd} ổ • ${on} đang cắm • ${fmt(t.files)} file` : "Bấm “＋ Quét ổ HDD” để bắt đầu";
  $("bd-scan").hidden = !ov.scanning;
  const tl = [`<div class="tile raised ${S.hid ? "" : "sel"}" data-h="0"><span class="led sm ok"><i></i></span><div class="tx"><b>Tất cả ổ</b><small>${fmt(t.files)} file • ${t.bytes_txt}</small></div></div>`];
  ov.hdds.forEach(h => {
    const st = ov.scanning && ov.scan_name === h.name ? "run" : (h.online ? "ok" : "off");
    tl.push(`<div class="tile raised ${S.hid === h.id ? "sel" : ""}" data-h="${h.id}"><span class="led sm ${st}"><i></i></span><div class="tx"><b>${esc(h.code)} · ${esc(h.name)}</b>` +
      `<small>${fmt(h.nfiles)} file • ${h.bytes_txt} • ${h.online ? "đang cắm " + esc(h.live_root.replace(/\\$/, "")) : "đã rút"}</small></div></div>`);
  });
  $("tiles").innerHTML = tl.join("");
  $("tiles").querySelectorAll(".tile").forEach(x => x.onclick = () => selectHdd(+x.dataset.h));
  const h = ov.hdds.find(x => x.id === S.hid);
  $("hacts").hidden = !h; if (h) $("hname").textContent = `${h.code} · ${h.name}` + (h.time_txt ? `  (quét ${h.time_txt})` : "");
  if (S.hid && !h) S.hid = 0;
  document.querySelectorAll(".empty-lib").forEach(x => x.remove());
}
function selectHdd(id) { S.hid = id; S.ovKey = ""; overview(true); refreshPage(); }

/* ------------------------------------------------------------------ bảng kết quả */
function sortHead(tbl, key) {
  const [k, d] = S.sort[key];
  tbl.querySelectorAll("th").forEach(th => { th.classList.toggle("sorted", th.dataset.k === k); th.classList.toggle("asc", th.dataset.k === k && !d); });
}
function bindSort(tbl, key, fn) {
  tbl.querySelectorAll("th[data-k]").forEach(th => th.onclick = () => {
    const s = S.sort[key]; S.sort[key] = [th.dataset.k, s[0] === th.dataset.k ? !s[1] : false]; fn();
  });
}
let seqF = 0;
async function searchFiles() {
  const my = ++seqF; const r = await api("search_files", S.q, S.kind, S.hid, S.sort.files[0], S.sort.files[1], 2000);
  if (my !== seqF) return; sortHead($("tbl-f"), "files");
  S.rowsF = r.rows;
  $("rows-f").innerHTML = r.rows.map((x, i) => `<tr class="row" data-i="${i}"><td class="mono code">${esc(x[1])}</td><td title="${esc(x[2])}">${esc(x[2])}</td>` +
    `<td><span class="pill t-${x[4]}">${KIND[x[4]] || ""}</span></td><td class="num">${esc(x[5])}</td><td class="mono">${esc(x[6])}</td>` +
    `<td class="mono code">${esc(x[7])}</td><td class="mono" style="color:var(--muted)">${esc(x[9] ? "\\" + x[9] : "")}</td></tr>`).join("") +
    (r.total > r.rows.length ? `<tr><td colspan="7" class="more">Hiện ${fmt(r.rows.length)} / ${fmt(r.total)} kết quả đầu tiên — gõ thêm từ khóa để thu hẹp</td></tr>` : "") ||
    `<tr><td colspan="7" class="empty">${S.ov && S.ov.totals.hdd ? "Không có kết quả phù hợp." : "Thư viện đang trống. Bấm “＋ Quét ổ HDD” để thêm ổ đầu tiên."}</td></tr>`;
  status(`${fmt(r.total)} file` + (S.q ? ` khớp “${S.q}”` : "") + (S.hid ? " trong ổ đã chọn" : ""));
  bindRows($("rows-f"), "f", i => ["file", S.rowsF[i][0]]);
}
let seqD = 0;
async function searchFolders() {
  const my = ++seqD; const r = await api("search_folders", S.q, S.hid, S.sort.folders[0], S.sort.folders[1], 2000);
  if (my !== seqD) return; sortHead($("tbl-d"), "folders");
  S.rowsD = r.rows;
  $("rows-d").innerHTML = r.rows.map((x, i) => `<tr class="row" data-i="${i}"><td class="mono code">${esc(x[1])}</td><td title="${esc(x[2])}">${esc(x[2])}</td>` +
    `<td class="mono code">${esc(x[3])}</td><td class="mono" style="color:var(--muted)">${esc("\\" + x[4])}</td><td class="num">${fmt(x[5])}</td><td class="num">${esc(x[6])}</td></tr>`).join("") +
    (r.total > r.rows.length ? `<tr><td colspan="6" class="more">Hiện ${fmt(r.rows.length)} / ${fmt(r.total)} thư mục đầu tiên</td></tr>` : "") ||
    `<tr><td colspan="6" class="empty">Không có thư mục phù hợp.</td></tr>`;
  status(`${fmt(r.total)} thư mục`);
  bindRows($("rows-d"), "d", i => ["folder", S.rowsD[i][0]]);
}
function bindRows(tb, tag, who) {
  tb.querySelectorAll("tr.row").forEach(tr => {
    tr.onclick = () => { tb.querySelectorAll("tr.sel").forEach(x => x.classList.remove("sel")); tr.classList.add("sel"); showDetail(tag, ...who(+tr.dataset.i)); };
    tr.ondblclick = async () => { const [k, id] = who(+tr.dataset.i); const r = await api("open_item", k, id); if (!r.ok) toast(r.msg, true); };
  });
}

/* ------------------------------------------------------------------ chi tiết */
async function showDetail(tag, kind, id) {
  const it = await api("item", kind, id); const box = $("det-" + tag); if (!it) return;
  S.cur[tag] = it;
  const meta = kind === "file" ? `${it.size} • sửa ${it.mtime} • thư mục ${it.fcode}` : `${fmt(it.nfiles)} file trực tiếp • ${fmt(it.tfiles)} file tính cả thư mục con • ${it.tsize}`;
  box.className = "detail";
  box.innerHTML = `<span class="led ${it.online ? "ok" : "off"}"><i></i></span><div class="tx"><div class="t1">${esc(it.code)} · ${esc(it.name)}</div>` +
    `<div class="t2">${esc(it.path)}</div><div class="t2">${esc(meta)} • ${it.online ? (it.exists ? "ổ đang cắm — mở được" : "ổ đang cắm nhưng không thấy file/thư mục này") : "ổ " + esc(it.hcode) + " chưa cắm vào máy"}</div></div>` +
    `<div class="acts"><button class="btn sm" data-a="open">📂 Mở</button><button class="btn sm" data-a="path">⎘ Đường dẫn</button><button class="btn sm" data-a="code">⎘ Mã</button>` +
    (tag === "f" || tag === "d" ? `<button class="btn sm" data-a="tree">⌥ Xem trong cây</button>` : "") +
    (tag === "d" ? `<button class="btn sm red" data-a="list">⌕ Xem file</button>` : "") + `</div>`;
  box.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => {
    const a = b.dataset.a;
    if (a === "open") { const r = await api("open_item", kind, id); if (!r.ok) toast(r.msg, true); }
    else if (a === "path") copy(it.real || it.path);
    else if (a === "code") copy(it.code);
    else if (a === "tree") revealInTree(kind === "file" ? it.fid : it.id, kind === "file" ? it.id : 0);
    else if (a === "list") { S.q = it.code; $("q").value = it.code; go("files"); }
  });
}

/* ------------------------------------------------------------------ cây thư mục */
function nodeHtml(n, hdd) {
  return `<div class="tnode" data-id="${n.id}"><div class="tn" data-id="${n.id}"><span class="tg">${n.leaf ? "" : "▸"}</span><span class="ic">${hdd ? "▣" : "▦"}</span>` +
    `<span class="nm">${esc(n.name)}</span><span class="ct">${fmt(n.tfiles)} file</span></div><div class="tkids" hidden></div></div>`;
}
async function loadTree() {
  const roots = await api("tree_roots", S.hid); const box = $("treebox");
  box.innerHTML = roots.length ? "" : `<div class="empty">Chưa có dữ liệu.</div>`;
  roots.forEach(r => { r.leaf = false; box.insertAdjacentHTML("beforeend", nodeHtml(r, true)); });
  bindTree(box);
  if (roots.length === 1) { const n = box.querySelector(".tnode"); await toggleNode(n, true); selectNode(n); }
}
function bindTree(scope) {
  scope.querySelectorAll(":scope > .tnode > .tn, :scope > .tkids > .tnode > .tn").forEach(tn => {
    if (tn._b) return; tn._b = 1;
    tn.onclick = e => { const node = tn.parentElement; selectNode(node); if (e.target.classList.contains("tg")) toggleNode(node); };
    tn.ondblclick = () => toggleNode(tn.parentElement);
  });
}
async function toggleNode(node, force) {
  const kids = node.querySelector(":scope > .tkids"), tg = node.querySelector(":scope > .tn > .tg");
  if (!kids.hidden && !force) { kids.hidden = true; tg.textContent = "▸"; return; }
  if (!kids.dataset.loaded) {
    const ch = await api("tree_children", +node.dataset.id); kids.innerHTML = ch.map(c => nodeHtml(c, false)).join(""); kids.dataset.loaded = 1; bindTree(kids);
    if (!ch.length) tg.textContent = "";
  }
  if (kids.children.length) { kids.hidden = false; tg.textContent = "▾"; }
}
async function selectNode(node) {
  document.querySelectorAll(".tn.on").forEach(x => x.classList.remove("on")); node.querySelector(":scope > .tn").classList.add("on");
  const id = +node.dataset.id; S.treeSel = id; const r = await api("tree_files", id); const f = r.folder; if (!f) return;
  $("tr-title").textContent = f.name; $("tr-info").textContent = `${f.code} • ${fmt(f.tfiles)} file • ${f.size}` + (f.path ? `  •  \\${f.path}` : "");
  S.rowsT = r.rows;
  $("rows-t").innerHTML = r.rows.map((x, i) => `<tr class="row" data-i="${i}"><td class="mono code">${esc(x[1])}</td><td title="${esc(x[2])}">${esc(x[2])}</td><td class="num">${esc(x[3])}</td><td class="mono">${esc(x[4])}</td></tr>`).join("") ||
    `<tr><td colspan="4" class="empty">Thư mục này không có file trực tiếp — mở các thư mục con ở bên trái.</td></tr>`;
  bindRows($("rows-t"), "t", i => ["file", S.rowsT[i][0]]);
}
async function revealInTree(folderId, fileId) {
  go("tree"); await new Promise(r => setTimeout(r, 60));
  const ids = await api("tree_path", folderId); const box = $("treebox");
  let scope = box;
  const waitFor = async () => { for (let i = 0; i < 40 && !box.querySelector(".tnode"); i++) await new Promise(r => setTimeout(r, 50)); };
  await waitFor();
  for (let k = 0; k < ids.length; k++) {
    const node = scope.querySelector(`.tnode[data-id="${ids[k]}"]`); if (!node) break;
    if (k < ids.length - 1) { await toggleNode(node, true); scope = node.querySelector(":scope > .tkids"); }
    else { await selectNode(node); node.scrollIntoView({block: "center"}); }
  }
  if (fileId) { const i = (S.rowsT || []).findIndex(x => x[0] === fileId); if (i >= 0) { const tr = $("rows-t").children[i]; if (tr) { tr.click(); tr.scrollIntoView({block: "center"}); } } }
}

/* ------------------------------------------------------------------ quét ổ */
async function loadDrives() {
  const r = await api("drives"); S.drives = r.drives; S.nextCode = r.next_code;
  $("rows-dr").innerHTML = r.drives.map((d, i) => `<tr data-i="${i}" ${S.pick && S.pick.root === d.root ? 'class="on"' : ""}><td><b>${esc(d.letter)}</b></td><td>${esc(d.label)}${d.system ? " • hệ thống" : ""}</td>` +
    `<td>${esc(d.type)}</td><td>${esc(d.fs)}</td><td class="num">${esc(d.total)}</td><td class="num">${esc(d.free)}</td><td>${d.code ? `<span class="pill t-done">${esc(d.code)} · quét lại</span>` : "—"}</td></tr>`).join("") ||
    `<tr><td colspan="7" class="empty">Không thấy ổ đĩa nào. Cắm ổ HDD rồi bấm “Làm mới”, hoặc chọn một thư mục.</td></tr>`;
  $("rows-dr").querySelectorAll("tr[data-i]").forEach(tr => tr.onclick = () => {
    const d = S.drives[+tr.dataset.i]; S.pick = {root: d.root, drive: d, name: d.name, code: d.code, hid: d.hid, system: d.system};
    $("sc-name").value = d.name; showPick(); loadDrives();
  });
  showPick();
}
function showPick() {
  const p = S.pick; $("bGo").disabled = !p || S.scanOn;
  $("sc-code").innerHTML = p ? (p.code ? `<span style="color:var(--orange)">Mã ổ: ${esc(p.code)}  (quét lại, thay dữ liệu cũ)</span>` : `<span style="color:var(--green)">Mã ổ mới: ${esc(S.nextCode)}</span>`) : "";
  $("where").textContent = p ? "Sẽ quét: " + p.root : "";
  if (p && !p.drive) $("sc-ej").disabled = true; else $("sc-ej").disabled = false;
}
async function pickFolder() {
  const p = await api("pick_folder"); if (!p) return;
  const i = await api("target_info", p);
  S.pick = {root: p, drive: null, name: i.name, code: i.code, hid: i.hid}; S.nextCode = i.next_code; $("sc-name").value = i.name; showPick();
  $("sc-ej").title = "Quét một thư mục thì không tháo ổ.";
}
async function startScan() {
  const p = S.pick; if (!p) return;
  if (p.system && !(await confirmD("Ổ hệ thống", `${p.drive.letter} là ổ hệ thống (Windows), quét sẽ rất lâu và nhiều file không liên quan.\nVẫn quét?`, "Vẫn quét"))) return;
  const r = await api("start_scan", p.root, $("sc-name").value.trim(), $("sc-media").checked, p.hid || 0);
  if (!r.ok) { toast(r.msg, true); return; }
  S.logn = 0; $("log").innerHTML = ""; S.scanOn = true; showPick(); pollScan();
}
function bar(id, pct, txt, info) {
  const v = pct < 0 ? 0 : pct; $(id).style.width = v + "%"; $(id + "-p").textContent = pct < 0 ? "—" : pct + "%"; $(id + "-i").textContent = info;
}
async function pollScan() {
  const s = await api("scan_state", S.logn); S.logn = s.next;
  if (s.log.length) { const lg = $("log"); lg.insertAdjacentHTML("beforeend", s.log.map(l => `<div>${esc(l)}</div>`).join("")); lg.scrollTop = lg.scrollHeight; }
  bar("e-sc", s.running && s.phase === "scan" ? s.pct : (s.phase === "idle" ? 0 : (["cancel", "error"].includes(s.phase) ? 0 : 100)), "",
    s.phase === "idle" ? "—" : `${fmt(s.files)} file • ${fmt(s.folders)} thư mục • ${s.bytes}` + (s.cur ? " • " + s.cur : ""));
  bar("e-bk", s.bk, "", s.bk === -1 ? "tắt" : s.bk === -2 ? "bỏ qua / lỗi (xem nhật ký)" : s.bk === 100 ? "đã sao lưu xong" : s.bk > 0 ? "đang đẩy library.db lên PikPak…" : "—");
  bar("e-ej", s.ej, "", s.ej === -1 ? "tắt / không áp dụng" : s.ej === -2 ? "KHÔNG tháo được (xem nhật ký)" : s.ej === 100 ? "đã tháo ổ — rút cáp được" : s.ej > 0 ? "đang tháo ổ…" : "—");
  $("bStop").disabled = !(s.running && s.phase === "scan");
  const was = S.scanOn; S.scanOn = s.running; showPick();
  if (s.running) setTimeout(pollScan, 450);
  else if (was) {
    S.ovKey = ""; overview(true); loadDrives();
    if (s.result) toast(`Đã quét xong ${s.result.code} · ${s.result.name}`);
  }
}

/* ------------------------------------------------------------------ cài đặt */
async function loadSettings() {
  const i = S.init; $("bk-path").textContent = i.backup_path; $("db-path").textContent = i.db;
  $("about").innerHTML = `${esc(i.title)}<br>Phiên bản ${esc(i.version)} • GitHub: ${esc(i.repo)}<br>Quét ổ HDD, lưu thư mục / file có mã số, tìm kiếm tức thì — kể cả khi ổ không cắm.`;
  rcRefresh();
}
async function rcRefresh() {
  const r = await api("rc_status"); $("rc-path").textContent = r.path || "chưa có — sẽ tự tải khi đăng nhập";
  $("rc-state").innerHTML = r.logged ? `<span class="state-pill s-ok">ĐÃ đăng nhập PikPak ✔</span>` : `<span class="state-pill s-off">chưa đăng nhập</span>`;
  if (!$("rc-user").value) $("rc-user").value = r.user || "";
  $("rc-msg").textContent = r.busy ? r.msg : (r.err ? "Lỗi: " + r.err : r.msg); $("rc-msg").style.color = r.err ? "var(--red)" : "var(--muted)";
  $("bRcLogin").disabled = r.busy; $("bRcOut").disabled = !r.logged;
  if (r.busy) setTimeout(rcRefresh, 700);
}

/* ------------------------------------------------------------------ cập nhật */
async function checkUpdate(silent) {
  if (!silent) status("Đang kiểm tra bản cập nhật trên GitHub…");
  const r = await api("update_check");
  if (r.newer) { $("bUpd").classList.add("hot"); $("bUpd").textContent = "⟳ Có bản mới v" + r.version; }
  if (silent) return; status("Sẵn sàng.");
  if (r.err) { info("Cập nhật", "Không kiểm tra được bản mới (cần Internet):\n" + r.err); return; }
  if (!r.has_release) { info("Cập nhật", "Chưa có bản phát hành nào trên GitHub.\nBạn đang dùng v" + S.init.version); return; }
  if (!r.newer) { toast("Bạn đang dùng bản mới nhất (v" + S.init.version + ")"); return; }
  if (await confirmD("Có bản cập nhật", `Có phiên bản mới v${r.version} (hiện tại v${S.init.version}).\n\n${r.notes}\n\nCập nhật ngay? (Thư viện của bạn được giữ nguyên.)`, "Cập nhật ngay")) {
    await api("update_apply"); go("settings"); $("upd-bar").hidden = false; pollUpd();
  }
}
async function pollUpd() {
  const u = await api("update_state"); $("upd-bar").firstElementChild.style.width = u.pct + "%";
  $("upd-msg").textContent = u.err ? "Lỗi: " + u.err : (u.msg + (u.busy ? ` ${u.pct}%` : "")); $("upd-msg").style.color = u.err ? "var(--red)" : "var(--muted)";
  if (u.busy) setTimeout(pollUpd, 500);
}

/* ------------------------------------------------------------------ hành động */
async function editHddFlow() {
  const h = S.ov.hdds.find(x => x.id === S.hid); if (!h) return;
  let vals = null;
  const res = await new Promise(resolve => {
    dialog(`Sửa ổ ${h.code}`, `<div class="fr sm"><label>Tên ổ</label><input type="text" id="e-n" value="${esc(h.name)}"></div>` +
      `<div class="fr sm"><label>Mã ổ</label><input type="text" id="e-c" value="${esc(h.code)}" maxlength="6" style="max-width:120px"></div>` +
      `<div class="hint" style="margin-left:0">Đổi mã sẽ đổi luôn tiền tố mã thư mục / file của ổ. Mã gồm chữ và số, tối đa 6 ký tự.</div>`,
      [{t: "Hủy", v: null}, {t: "Lưu", v: "ok", cls: "red"}], ov => {
        const ok = ov.querySelector(".btns .red"); ok.onclick = async () => {
          const r = await api("edit_hdd", h.id, ov.querySelector("#e-n").value, ov.querySelector("#e-c").value);
          if (r.ok) { ov.remove(); resolve(true); } else toast(r.msg, true);
        };
      }).then(v => { if (v === null) resolve(false); });
  });
  if (res) { toast("Đã lưu."); S.ovKey = ""; overview(true); refreshPage(); }
}
async function rescan() {
  const h = S.ov.hdds.find(x => x.id === S.hid); if (!h) return;
  if (!h.online) { info("Ổ chưa cắm", `Ổ ${h.code} · ${h.name} chưa cắm vào máy.\nCắm ổ rồi thử lại.`); return; }
  if (!(await confirmD("Quét lại ổ", `Quét lại ổ ${h.code} · ${h.name}?\nDữ liệu cũ của ổ này sẽ được thay bằng kết quả quét mới (mã ổ giữ nguyên).`, "Quét lại"))) return;
  S.pick = {root: h.live_root, drive: {letter: h.live_root.replace(/\\$/, "")}, name: h.name, code: h.code, hid: h.id};
  go("scan"); $("sc-name").value = h.name; showPick();
  await startScan();
}
async function delHdd() {
  const h = S.ov.hdds.find(x => x.id === S.hid); if (!h) return;
  if (!(await confirmD("Xóa ổ khỏi thư viện", `Xóa ổ ${h.code} · ${h.name} (${fmt(h.nfiles)} file) khỏi thư viện?\n(Không xóa gì trên ổ cứng thật.)`, "Xóa", true))) return;
  await api("delete_hdd", h.id); S.hid = 0; S.ovKey = ""; await overview(true); refreshPage(); toast("Đã xóa ổ khỏi thư viện.");
}
async function exportCsv() {
  const tab = S.page === "folders" ? "folders" : "files"; const k = S.sort[tab];
  const r = await api("export_csv", tab, S.q, S.kind, S.hid, k[0], k[1]);
  if (r.msg) (r.ok ? info("Xuất CSV", r.msg) : toast(r.msg, true));
}

/* ------------------------------------------------------------------ khởi động */
async function start() {
  if (S.started) return; S.started = true;
  S.init = await api("init"); setTheme(S.init.theme);
  $("ver").textContent = "v" + S.init.version.split(".").slice(0, 2).join(".") + " by " + S.init.author;
  $("sc-bk").checked = S.init.backup_on; $("sc-ej").checked = S.init.eject_on; $("sc-media").checked = S.init.media_only;
  document.querySelectorAll(".nav").forEach(n => n.onclick = () => go(n.dataset.p));
  $("fold").onclick = () => { $("side").classList.toggle("mini"); $("fold").textContent = $("side").classList.contains("mini") ? "»" : "«"; };
  $("bTheme").onclick = () => { setTheme(S.theme === "dark" ? "light" : "dark"); api("set_setting", "theme", S.theme); };
  $("bUpd").onclick = () => checkUpdate(false); $("bUpd2").onclick = () => checkUpdate(false);
  $("bScanNew").onclick = () => go("scan");
  const onq = debounce(v => { S.q = v; if (S.page === "files") searchFiles(); else if (S.page === "folders") searchFolders(); }, 160);
  $("q").oninput = e => { $("q2").value = e.target.value; onq(e.target.value); };
  $("q2").oninput = e => { $("q").value = e.target.value; onq(e.target.value); };
  $("kind").onchange = e => { S.kind = e.target.value; searchFiles(); };
  bindSort($("tbl-f"), "files", searchFiles); bindSort($("tbl-d"), "folders", searchFolders);
  $("bCsv").onclick = $("bCsv2").onclick = exportCsv;
  $("bEject").onclick = async () => {
    const h = S.ov.hdds.find(x => x.id === S.hid); if (!h) return;
    if (!(await confirmD("Tháo ổ", `Tháo ổ ${h.code} · ${h.name}?\nTool thử tháo an toàn trước; nếu không được sẽ tự chuyển sang chế độ ÉP THÁO (có thể cần quyền Administrator).`, "Tháo ổ"))) return;
    const r = await api("eject_hdd", h.id); if (!r.ok) { toast(r.msg, true); return; }
    go("scan"); S.logn = 0; $("log").innerHTML = ""; S.scanOn = true; pollScan();
  };
  $("bRescan").onclick = rescan; $("bEdit").onclick = editHddFlow; $("bDel").onclick = delHdd;
  $("bPickDir").onclick = pickFolder; $("bRefDr").onclick = loadDrives; $("bGo").onclick = startScan;
  $("bStop").onclick = async () => { await api("cancel_scan"); $("bStop").disabled = true; };
  $("sc-bk").onchange = e => api("set_setting", "backup_on", e.target.checked); $("sc-ej").onchange = e => api("set_setting", "eject_on", e.target.checked);
  $("sc-media").onchange = e => api("set_setting", "media_only", e.target.checked);
  $("bRcLogin").onclick = async () => {
    const u = $("rc-user").value.trim(), p = $("rc-pw").value; if (!u || !p) { toast("Nhập email và mật khẩu PikPak.", true); return; }
    await api("rc_login", u, p); rcRefresh(); const iv = setInterval(async () => { const r = await api("rc_status"); if (!r.busy) { clearInterval(iv); $("rc-pw").value = ""; rcRefresh(); } }, 800);
  };
  $("bRcOut").onclick = async () => { await api("rc_logout"); rcRefresh(); };
  $("bBkNow").onclick = async () => { const r = await api("backup_now"); if (!r.ok) { toast(r.msg, true); return; } go("scan"); S.logn = 0; $("log").innerHTML = ""; S.scanOn = true; pollScan(); };
  $("bBkFile").onclick = async () => { const r = await api("backup_file"); if (r.msg) info("Sao lưu", r.msg); };
  $("bRestore").onclick = async () => {
    if (!(await confirmD("Khôi phục", "Thay toàn bộ thư viện hiện tại bằng bản sao lưu bạn sắp chọn?", "Chọn file…", true))) return;
    const r = await api("restore_file"); if (r.msg) (r.ok ? info("Khôi phục", r.msg) : toast(r.msg, true)); S.hid = 0; S.ovKey = ""; overview(true);
  };
  $("bOpenData").onclick = () => api("open_data_dir");
  $("bWipe").onclick = async () => {
    if (!S.ov.totals.hdd) { toast("Thư viện đang trống."); return; }
    if (await confirmD("Xóa toàn bộ thư viện", "Xóa SẠCH toàn bộ thư viện (mọi ổ, thư mục, file đã quét)?\nKhông ảnh hưởng dữ liệu trên ổ cứng thật.\n\nNên sao lưu trước.", "Xóa sạch", true)) {
      await api("wipe"); S.hid = 0; S.ovKey = ""; await overview(true); refreshPage(); toast("Đã xóa toàn bộ thư viện.");
    }
  };
  $("bRepo").onclick = () => api("open_url", "https://github.com/" + S.init.repo);
  await overview(true); go("files");
  setInterval(() => { if (!S.scanOn) overview(false); }, 3000);
  setTimeout(() => checkUpdate(true), 4000);
}
window.addEventListener("pywebviewready", start);
if (window.pywebview && window.pywebview.api) start();
else setTimeout(() => { if (window.pywebview && window.pywebview.api) start(); else if (!window.pywebview) start(); }, 1500);
