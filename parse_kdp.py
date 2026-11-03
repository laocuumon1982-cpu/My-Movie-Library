"""Phân tích bản in của Karen's Directory Printer (text) thành dữ liệu có cấu trúc."""
import re, collections

HDR_VOL = re.compile(r'Volume:\s+(.*?)\s+Computer:\s*(\S+)')
HDR_SER = re.compile(r'Serial No\.:\s+(\S+)\s+([A-Z]:\\.*)$')
HDR_SKIP = re.compile(r"Karen's Directory Printer|^\s*User:|^\s*\d{1,2}:\d{2}:\d{2}\s*[AP]M\s*$")

def parse_text(text):
    """Trả về (hdds, folders, files): hdds {serial: {...}}, folders [(serial, path)], files [(serial, folder, name)]."""
    hdds, folders, files = {}, collections.OrderedDict(), []
    seen = set(); cur = None; label = computer = ''; last_folder = None
    for raw in text.splitlines():
        line = raw.rstrip('\r\n\f')
        m = HDR_VOL.search(line)
        if m:
            label, computer = m.group(1).strip(), m.group(2); continue
        m = HDR_SER.search(line)
        if m:
            cur = m.group(1)
            hdds.setdefault(cur, {'serial': cur, 'label': label, 'computer': computer, 'drive': m.group(2)[:2]})
            continue
        if cur is None or not line.strip() or HDR_SKIP.search(line): continue
        s = line.strip()
        if s.lower() in ('(continued)', '(continued...)'): continue
        if re.match(r'^[A-Z]:\\', s):
            if s.endswith('\\'): folders[(cur, s)] = True; last_folder = s
            continue
        if last_folder is None: continue
        key = (cur, last_folder, s)
        if key not in seen: seen.add(key); files.append(key)
    return hdds, list(folders.keys()), files

def ext(name):
    i = name.rfind('.'); return name[i:].lower() if i > 0 else ''
