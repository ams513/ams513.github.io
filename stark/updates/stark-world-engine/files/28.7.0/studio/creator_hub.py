"""creator_hub.py: the iPhone Command Center. A PIN-protected web app (this PC only unless phone mode is on).

  python creator_hub.py                    serve on 127.0.0.1:8510 (this PC only; PIN generated if absent)
  python creator_hub.py --phone            phone mode: serve on 0.0.0.0:8510 so your phone on the home Wi-Fi can open it
  python creator_hub.py --qr               write .claude/iphone_qr.html (self-made SVG QR code) and exit
  python creator_hub.py --host 127.0.0.1 --port 0 --no-scheduler     (tests)

Tabs: Shoot Scheduler (.ics reminders with a deep link back here; 5 min before a shoot OBS is pre-armed over
obs-websocket and the teleprompter opens on the PC; optional auto-record at shoot time), Camera (HTTPS VDO.Ninja
push link for Safari's camera permission), Teleprompter (tap / spacebar toggles OBS recording), Review & Approve
(watch the edit, pick a publish date/time, Approve writes .claude/approvals/<session>.json; publishers.py refuses to
run without it), Stats (free YouTube / itch.io numbers only when you configured your own credentials).

Security (use on a trusted home Wi-Fi: plain HTTP on the LAN): Host-header allowlist; login by POST /login with the
PIN, header X-Hub-Pin, or a one-time 15-minute QR login token (?login=, never the PIN in a URL); a login sets a
random server-side session cookie (rotated on restart, not derived from the PIN). PINs are compared in constant
time; 5 wrong PINs from one address in 10 min lock that address's PIN logins for 15 min (valid sessions are never
locked out); 30+ wrong PINs overall add a 1 s delay per PIN attempt. Sockets time out after 15 s, at most 64
connections at once. Approvals are signed with a random .claude/approval.key and can be made once per session.
Log: .claude/hub.log (PINs / tokens redacted). No paid service is ever called.
"""
import argparse, datetime, hashlib, hmac, html, http.server, json, math, os, re, secrets, socketserver, subprocess
import sys, threading, time, urllib.parse, urllib.request, uuid, webbrowser

from gs_common import (APPROVALS, CONFIG, EDITS, ROOT, STATE, classroom_mode, ensure_hub_keys, get_logger, lan_ip, load_config)
import obs_bridge
import publishers

PORT = 8510
SHOOTS = os.path.join(STATE, 'shoots.json')
SCRIPT = os.path.join(STATE, 'teleprompter.txt')
YT_TOKEN = os.path.join(STATE, 'yt_token.json')
OBS_EXE = r'C:\Program Files\obs-studio\bin\64bit\obs64.exe'
PHONE_SEEN = os.path.join(STATE, 'hub_phone_seen.json')   # first PIN-authenticated request from another device
LOGIN_TOKENS = os.path.join(STATE, 'hub_login_tokens.json')  # one-time QR login tokens (sha256 -> expiry)
SESSION_TTL = 30 * 86400
LOGIN_TTL = 15 * 60
TRUST_NOTE = 'Use the Creator Hub on your trusted home Wi-Fi only (it is plain HTTP on your local network).'
log = get_logger('creator_hub', 'hub.log')


# =====================================================================================================
# QR code (byte mode, error correction M, versions 1-10) - pure Python, plus a structural decoder
# =====================================================================================================
EC_M = {1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
        6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
        10: (26, [(4, 43), (1, 44)])}
ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
         9: [6, 26, 46], 10: [6, 28, 50]}
EXP, LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    EXP[_i] = _x
    LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]


def gf_mul(a, b):
    return 0 if a == 0 or b == 0 else EXP[LOG[a] + LOG[b]]


def rs_generator(n):
    g = [1]
    for i in range(n):
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j] ^= c
            ng[j + 1] ^= gf_mul(c, EXP[i])
        g = ng
    return g


def rs_remainder(data, n):
    gen = rs_generator(n)
    msg = list(data) + [0] * n
    for i in range(len(data)):
        c = msg[i]
        if c:
            for j in range(1, len(gen)):
                msg[i + j] ^= gf_mul(gen[j], c)
    return msg[len(data):]


def _syndromes(cw, n_ec):
    out = []
    for i in range(n_ec):
        s = 0
        for c in cw:
            s = gf_mul(s, EXP[i]) ^ c
        out.append(s)
    return out


def qr_capacity(v):
    n_ec, groups = EC_M[v]
    return sum(c * d for c, d in groups)


def _size(v):
    return 17 + 4 * v


def function_map(v):
    n = _size(v)
    f = [[False] * n for _ in range(n)]
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        for r in range(-1, 8):
            for c in range(-1, 8):
                if 0 <= r0 + r < n and 0 <= c0 + c < n:
                    f[r0 + r][c0 + c] = True
    for i in range(n):
        f[6][i] = f[i][6] = True
    al = ALIGN[v]
    for r in al:
        for c in al:
            if (r, c) in ((6, 6), (6, al[-1]), (al[-1], 6)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    f[r + dr][c + dc] = True
    for i in range(9):
        f[8][i] = f[i][8] = True
    for i in range(8):
        f[8][n - 1 - i] = f[n - 1 - i][8] = True
    if v >= 7:
        for i in range(6):
            for j in range(3):
                f[i][n - 11 + j] = f[n - 11 + j][i] = True
    return f


def _draw_function_patterns(m, v):
    n = _size(v)
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        for r in range(-1, 8):
            for c in range(-1, 8):
                if 0 <= r0 + r < n and 0 <= c0 + c < n:
                    d = max(abs(r - 3), abs(c - 3))
                    m[r0 + r][c0 + c] = d != 2 and d != 4
    for i in range(8, n - 8):
        m[6][i] = m[i][6] = i % 2 == 0
    al = ALIGN[v]
    for r in al:
        for c in al:
            if (r, c) in ((6, 6), (6, al[-1]), (al[-1], 6)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = max(abs(dr), abs(dc)) != 1
    if v >= 7:
        rem = v
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = v << 12 | rem
        for i in range(18):
            bit = (bits >> i) & 1 == 1
            a, b = n - 11 + i % 3, i // 3
            m[b][a] = bit          # top-right block (row b, col a)
            m[a][b] = bit          # bottom-left block


def format_bits(mask, ec_bits=0b00):
    data = ec_bits << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return (data << 10 | rem) ^ 0x5412


def _draw_format(m, v, mask):
    n = _size(v)
    bits = format_bits(mask)
    get = lambda i: (bits >> i) & 1 == 1
    for i in range(0, 6):
        m[i][8] = get(i)           # (x=8, y=i)
    m[7][8] = get(6)
    m[8][8] = get(7)
    m[8][7] = get(8)
    for i in range(9, 15):
        m[8][14 - i] = get(i)
    for i in range(0, 8):
        m[8][n - 1 - i] = get(i)
    for i in range(8, 15):
        m[n - 15 + i][8] = get(i)
    m[n - 8][8] = True            # dark module


MASKS = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
         lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
         lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
         lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]


def _zigzag(n, func):
    """Module coordinates (row, col) in data placement order."""
    out = []
    right = n - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(n):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = n - 1 - vert if upward else vert
                if not func[y][x]:
                    out.append((y, x))
        right -= 2
    return out


def _data_codewords(text, v):
    data = text.encode('utf-8')
    bits = []

    def put(val, n):
        bits.extend((val >> (n - 1 - i)) & 1 for i in range(n))
    put(0b0100, 4)
    put(len(data), 8 if v < 10 else 16)
    for b in data:
        put(b, 8)
    cap = qr_capacity(v) * 8
    put(0, min(4, cap - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    cws = [int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    k = 0
    while len(cws) < qr_capacity(v):
        cws.append((0xEC, 0x11)[k % 2])
        k += 1
    return cws


def _blocks(v):
    n_ec, groups = EC_M[v]
    sizes = []
    for count, dlen in groups:
        sizes += [dlen] * count
    return n_ec, sizes


def _interleave(cws, v):
    n_ec, sizes = _blocks(v)
    blocks, i = [], 0
    for s in sizes:
        blocks.append(cws[i:i + s]); i += s
    ecs = [rs_remainder(b, n_ec) for b in blocks]
    out = []
    for k in range(max(sizes)):
        for b in blocks:
            if k < len(b):
                out.append(b[k])
    for k in range(n_ec):
        for e in ecs:
            out.append(e[k])
    return out


def _penalty(m):
    n = len(m)
    p = 0
    for grid in (m, [list(r) for r in zip(*m)]):
        for row in grid:
            run, prev = 0, None
            for c in row:
                if c == prev:
                    run += 1
                else:
                    if run >= 5:
                        p += run - 2
                    run, prev = 1, c
            if run >= 5:
                p += run - 2
            s = ''.join('1' if c else '0' for c in row)
            p += 40 * (len(re.findall('(?=10111010000)', s)) + len(re.findall('(?=00001011101)', s)))
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                p += 3
    dark = sum(map(sum, m))
    p += 10 * (abs(dark * 20 - n * n * 10) // (n * n))
    return p


def qr_matrix(text, version=None, mask=None):
    """-> (matrix rows of bool, version, mask). Byte mode, EC level M."""
    need = len(text.encode('utf-8'))
    v = version or next((v for v in range(1, 11) if qr_capacity(v) >= need + (2 if v < 10 else 3)), None)
    if not v:
        raise ValueError('text too long for QR versions 1-10')
    n = _size(v)
    func = function_map(v)
    allbits = []
    for cw in _interleave(_data_codewords(text, v), v):
        allbits += [(cw >> (7 - i)) & 1 for i in range(8)]
    order = _zigzag(n, func)
    best = None
    for mk in ([mask] if mask is not None else range(8)):
        m = [[False] * n for _ in range(n)]
        _draw_function_patterns(m, v)
        for idx, (y, x) in enumerate(order):
            bit = allbits[idx] if idx < len(allbits) else 0
            m[y][x] = bool(bit) ^ MASKS[mk](x, y)
        _draw_format(m, v, mk)
        pen = _penalty(m)
        if best is None or pen < best[0]:
            best = (pen, m, mk)
    return best[1], v, best[2]


def qr_decode(m):
    """Structural decoder: format BCH check, unmask, de-interleave, RS syndromes must be zero, parse byte mode."""
    n = len(m)
    v = (n - 17) // 4
    if v < 1 or v > 10 or n != 17 + 4 * v:
        raise ValueError('bad size')
    bits = 0
    pos = [(i, 8) for i in range(6)] + [(7, 8), (8, 8), (8, 7)] + [(8, 14 - i) for i in range(9, 15)]
    for i, (r, c) in enumerate(pos):
        bits |= int(m[r][c]) << i
    bits2 = 0
    pos2 = [(8, n - 1 - i) for i in range(8)] + [(n - 15 + i, 8) for i in range(8, 15)]
    for i, (r, c) in enumerate(pos2):
        bits2 |= int(m[r][c]) << i
    if bits != bits2:
        raise ValueError('format copies differ')
    match = [(ec, mk) for ec in range(4) for mk in range(8) if format_bits(mk, ec) == bits]
    if not match:
        raise ValueError('format BCH check failed')
    ec, mk = match[0]
    if ec != 0:
        raise ValueError('not EC level M')
    if not m[n - 8][8]:
        raise ValueError('dark module missing')
    func = function_map(v)
    raw = []
    for (y, x) in _zigzag(n, func):
        raw.append(int(m[y][x] ^ MASKS[mk](x, y)))
    n_ec, sizes = _blocks(v)
    total = sum(sizes) + n_ec * len(sizes)
    cws = [int(''.join(map(str, raw[i * 8:i * 8 + 8])), 2) for i in range(total)]
    blocks = [[] for _ in sizes]
    i = 0
    for k in range(max(sizes)):
        for b, s in enumerate(sizes):
            if k < s:
                blocks[b].append(cws[i]); i += 1
    ecs = [[] for _ in sizes]
    for k in range(n_ec):
        for b in range(len(sizes)):
            ecs[b].append(cws[i]); i += 1
    data = []
    for b in range(len(sizes)):
        if any(_syndromes(blocks[b] + ecs[b], n_ec)):
            raise ValueError(f'RS syndromes non-zero in block {b}')
        data += blocks[b]
    bitstr = ''.join(f'{c:08b}' for c in data)
    if bitstr[:4] != '0100':
        raise ValueError('not byte mode')
    ln = int(bitstr[4:12 if v < 10 else 20], 2)
    start = 12 if v < 10 else 20
    payload = bytes(int(bitstr[start + 8 * j:start + 8 * j + 8], 2) for j in range(ln))
    return payload.decode('utf-8')


def qr_svg(text, scale=8, quiet=4):
    m, v, mk = qr_matrix(text)
    n = len(m)
    size = (n + 2 * quiet) * scale
    path = ''.join(f'M{(c + quiet) * scale},{(r + quiet) * scale}h{scale}v{scale}h-{scale}z'
                   for r in range(n) for c in range(n) if m[r][c])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
            f'shape-rendering="crispEdges" role="img" aria-label="QR code"><rect width="100%" height="100%" '
            f'fill="#fff"/><path d="{path}" fill="#000"/></svg>'), m


FIREWALL_CMD = ('New-NetFirewallRule -DisplayName "Stark World Engine Creator Hub 8510" -Direction Inbound -Protocol TCP '
                '-LocalPort 8510 -RemoteAddress LocalSubnet -Action Allow -Profile Any')


def phone_seen(path=None):
    """-> {'ip', 'time'} of the last device that first opened the hub with the PIN, or None."""
    rec = load_json(path or PHONE_SEEN, None)
    return rec if isinstance(rec, dict) and rec.get('ip') else None


def hub_url(cfg, ip=None, port=PORT, token=None):
    """The phone link the QR encodes: with a one-time login token (mint_login_token) when given. The PIN itself is
    never put in a URL."""
    return f'http://{ip or lan_ip(cfg)}:{port}/' + (f'?login={token}' if token else '')


def _tok_hash(tok):
    return hashlib.sha256(str(tok).encode()).hexdigest()


def mint_login_token(ttl=LOGIN_TTL, path=None):
    """A random one-time, short-lived login token for the QR code. Stored hashed in .claude/hub_login_tokens.json,
    which the hub (any process) consumes. -> token"""
    path = path or LOGIN_TOKENS
    tok = secrets.token_urlsafe(24)
    now = time.time()
    data = load_json(path, {})
    data = {h: e for h, e in (data.items() if isinstance(data, dict) else []) if isinstance(e, (int, float)) and e > now}
    data[_tok_hash(tok)] = now + ttl
    new = not os.path.exists(path)
    save_json(path, data)
    if new:
        publishers.restrict_to_user(path)
    return tok


def login_token_valid(tok, path=None):
    """True while `tok` is unused and not expired (read-only check, for the setup wizard's QR refresh)."""
    data = load_json(path or LOGIN_TOKENS, {})
    e = data.get(_tok_hash(tok)) if isinstance(data, dict) else None
    return isinstance(e, (int, float)) and e > time.time()


def write_qr_page(url, pin, dest=None):
    dest = dest or os.path.join(STATE, 'iphone_qr.html')
    svg, m = qr_svg(url)
    decoded = qr_decode(m)
    if decoded != url:
        raise AssertionError(f'QR self-check failed: {decoded!r} != {url!r}')
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Stark World Engine Hub QR</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{{margin:0;background:#101418;color:#e9eef2;font:16px system-ui,sans-serif;display:flex;justify-content:center;padding:24px}}
.c{{max-width:560px;text-align:center}}.q{{background:#fff;display:inline-block;padding:8px;border-radius:10px}}
code{{background:#1d2731;padding:2px 6px;border-radius:4px;word-break:break-all}}.pin{{font-size:34px;letter-spacing:6px;color:#5fd3b5}}
p{{color:#b8c4ce;text-align:left}}</style></head><body><div class="c"><h1>Stark World Engine Creator Hub</h1>
<div class="q">{svg}</div><p>Scan with the iPhone camera (same Wi-Fi as this PC). URL: <code>{html.escape(url)}</code></p>
<div class="pin">PIN {html.escape(pin)}</div>
<p>If the phone cannot open the page, Windows is blocking port 8510 because this network is set to "Public".
Run this ONE command in an administrator PowerShell to allow it from your local network only:</p>
<p><code>{html.escape(FIREWALL_CMD)}</code></p>
<p>QR self-check: decoded back to the same URL (format BCH, Reed-Solomon syndromes and payload verified).</p>
</div></body></html>
"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w', encoding='utf-8') as f:
        f.write(page)
    return dest


# =====================================================================================================
# hub state
# =====================================================================================================
def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def list_sessions(edits=EDITS, approvals=APPROVALS):
    out = []
    for p in sorted(glob_manifests(edits), reverse=True):
        man = load_json(p, None)
        # one half-written / foreign manifest must not hide every other session from Review & Approve
        if not isinstance(man, dict) or not isinstance(man.get('final'), str):
            continue
        sid = os.path.basename(os.path.dirname(p))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', sid) or man.get('session', sid) != sid:
            continue
        man['session'] = sid
        if not isinstance(man.get('social_clips'), list):
            man['social_clips'] = []
        ap = load_json(os.path.join(approvals, sid + '.json'), None)
        man['approved'] = bool(ap)
        man['publish_at'] = ap.get('publish_at') if isinstance(ap, dict) else None
        out.append(man)
    return out


def glob_manifests(edits):
    import glob
    return glob.glob(os.path.join(glob.escape(edits), '*', 'manifest.json'))


def ics_for(shoot, base_url):
    def ut(ts):
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    link = f'{base_url}/?tab=prompter&shoot={shoot["id"]}'
    title = re.sub(r'[\r\n,;\\]', ' ', shoot['title'])[:120]
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Stark World Engine//Creator Hub//EN', 'CALSCALE:GREGORIAN',
             'BEGIN:VEVENT', f'UID:{shoot["id"]}@stark-hub', f'DTSTAMP:{ut(time.time())}',
             f'DTSTART:{ut(shoot["start"])}', f'DTEND:{ut(shoot["start"] + 30 * 60)}', f'SUMMARY:Shoot: {title}',
             f'URL:{link}', f'DESCRIPTION:Open the Creator Hub teleprompter: {link}', 'BEGIN:VALARM',
             'TRIGGER:-PT5M', 'ACTION:DISPLAY', f'DESCRIPTION:Shoot in 5 minutes: {title}', 'END:VALARM',
             'END:VEVENT', 'END:VCALENDAR']
    return '\r\n'.join(lines) + '\r\n'


class AlreadyApproved(Exception):
    pass


class Hub:
    """Shared state for the handler + scheduler."""

    def __init__(self, cfg, port, obs_factory=None, spawn_publishers=True, edits=EDITS, approvals=APPROVALS,
                 approval_key=None, login_tokens=None):
        self.cfg, self.port = cfg, port
        self.pin = str(cfg['hub_pin'])
        self.sessions = {}                    # sha256(random session id) -> expiry; rotated on every restart
        self.login_tokens = login_tokens or LOGIN_TOKENS
        self.approval_key = approval_key or publishers.approval_key(approvals, create=True)
        self.fails, self.global_fails, self.lock = {}, [], threading.Lock()
        self.seen_ips, self.lan_cache = set(), (0, None)
        self.obs_factory = obs_factory or (lambda: obs_bridge.ObsWS(timeout=3.0))
        self.spawn_publishers = spawn_publishers
        self.edits, self.approvals = edits, approvals
        self.stats_cache = (0, None)
        self.obs_cache = (0, None)

    # ---- auth ----
    def locked(self, ip):
        """Per-address PIN lockout: 5 wrong PINs in 10 min lock THAT address's PIN logins for 15 min. Valid session
        cookies are checked before this and are never locked out."""
        now = time.time()
        with self.lock:
            f = [t for t in self.fails.get(ip, []) if now - t < 900]
            self.fails[ip] = f
            recent = [t for t in f if now - t < 600]
            return len(recent) >= 5

    def backoff(self):
        """Seconds to wait before checking a PIN: 1 s once 30+ wrong PINs arrived (from anywhere) in 15 min. A
        slowdown for distributed guessing that never blocks anyone outright."""
        now = time.time()
        with self.lock:
            self.global_fails = [t for t in self.global_fails if now - t < 900]
            return 1.0 if len(self.global_fails) >= 30 else 0.0

    def fail(self, ip):
        with self.lock:
            self.fails.setdefault(ip, []).append(time.time())
            self.global_fails.append(time.time())

    def check_pin(self, given):
        if len(self.pin.strip()) < 4:          # an emptied / too short "hub_pin" must never mean "no PIN needed"
            return False
        return hmac.compare_digest(str(given).encode(), self.pin.encode())

    def check_cookie(self, given):
        """A random server-side session id (new_session); looked up by its SHA-256, so timing reveals nothing."""
        h = _tok_hash(given)
        with self.lock:
            e = self.sessions.get(h)
            if e and e < time.time():
                self.sessions.pop(h, None)
                e = None
        return bool(e)

    def new_session(self):
        tok = secrets.token_urlsafe(32)
        with self.lock:
            if len(self.sessions) >= 500:
                for h, _e in sorted(self.sessions.items(), key=lambda kv: kv[1])[:100]:
                    self.sessions.pop(h, None)
            self.sessions[_tok_hash(tok)] = time.time() + SESSION_TTL
        return tok

    def consume_login(self, tok):
        """One-time QR login token -> True once (then it is gone); False if unknown, expired or used."""
        if not tok or len(str(tok)) > 100:
            return False
        h, now = _tok_hash(tok), time.time()
        with self.lock:
            data = load_json(self.login_tokens, {})
            if not isinstance(data, dict):
                return False
            e = data.pop(h, None)
            data = {k: v for k, v in data.items() if isinstance(v, (int, float)) and v > now}
            if e is None:
                return False
            try:
                save_json(self.login_tokens, data)
            except OSError:
                return False
            return isinstance(e, (int, float)) and e > now

    def host_ok(self, host):
        """Host-header allowlist (blocks DNS rebinding): 127.0.0.1, localhost, ::1, the LAN IP, the configured
        lan_ip / hub_hostname; the port, when given, must be this hub's."""
        m = re.fullmatch(r'(\[[0-9a-fA-F:]+\]|[A-Za-z0-9.-]+)(?::(\d+))?', host or '')
        if not m or (m.group(2) and int(m.group(2)) != self.port):
            return False
        t, ip = self.lan_cache
        if time.time() - t > 60:
            ip = lan_ip(self.cfg)
            self.lan_cache = (time.time(), ip)
        names = {'127.0.0.1', 'localhost', '[::1]', ip, self.cfg.get('lan_ip'), self.cfg.get('hub_hostname')}
        return m.group(1).lower() in {str(n).lower() for n in names if n}

    def note_auth(self, ip, path=None):
        """Record the first PIN-authenticated request from each non-loopback address (the setup wizard polls
        phone_seen() to turn "phone connected" green). Never raises: auth must not depend on the disk."""
        if ip.startswith('127.') or ip == '::1':
            return
        with self.lock:
            if ip in self.seen_ips:
                return
            self.seen_ips.add(ip)
        try:
            save_json(path or PHONE_SEEN, {'ip': ip, 'time': time.time()})
            log.info('first PIN-authenticated request from %s', ip)
        except OSError:
            pass

    # ---- obs ----
    def obs(self, *calls):
        """Run [(requestType, data)] on OBS; -> list of responses. Raises ConnectionError if OBS is offline."""
        ws = self.obs_factory()
        with ws:
            return [ws.call(rt, d) for rt, d in calls]

    def obs_status(self):
        t, v = self.obs_cache
        if time.time() - t < 3 and v is not None:
            return v
        try:
            st = self.obs(('GetRecordStatus', None))[0]
            v = {'online': True, 'recording': bool(st.get('outputActive')), 'timecode': st.get('outputTimecode')}
        except (OSError, ConnectionError, PermissionError, RuntimeError, ValueError) as e:
            v = {'online': False, 'recording': False, 'error': str(e)[:120]}
        self.obs_cache = (time.time(), v)
        return v

    def pre_arm(self):
        """Make sure OBS runs with the Stark World Engine profile + collection, then select the scene. Never starts recording."""
        try:
            self.obs(('GetVersion', None))
        except (OSError, ConnectionError):
            if os.path.isfile(OBS_EXE):
                subprocess.Popen([OBS_EXE, '--disable-updater', '--disable-shutdown-check', '--profile',
                                  obs_bridge.PROFILE, '--collection', obs_bridge.COLLECTION],
                                 cwd=os.path.dirname(OBS_EXE), creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
                log.info('pre-arm: OBS was closed, launched it')
                for _ in range(30):
                    time.sleep(2)
                    try:
                        self.obs(('GetVersion', None))
                        break
                    except (OSError, ConnectionError):
                        continue
        calls = [('SetCurrentProfile', {'profileName': obs_bridge.PROFILE}),
                 ('SetCurrentSceneCollection', {'sceneCollectionName': obs_bridge.COLLECTION}),
                 ('SetCurrentProgramScene', {'sceneName': obs_bridge.SCENE})]
        done = []
        for rt, d in calls:
            try:
                self.obs((rt, d)); done.append(rt)
            except RuntimeError as e:          # e.g. "already current" or recording in progress
                log.info('pre-arm %s: %s', rt, e)
        self.obs_cache = (0, None)
        return done

    # ---- stats ----
    def stats(self):
        t, v = self.stats_cache
        if v is not None and time.time() - t < 600:
            return v
        out = {'youtube': 'not connected', 'itch': 'not connected'}
        if os.path.isfile(YT_TOKEN):
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
                creds = Credentials.from_authorized_user_file(YT_TOKEN)
                yt = build('youtube', 'v3', credentials=creds, cache_discovery=False)
                ch = yt.channels().list(part='statistics,snippet', mine=True).execute()['items'][0]
                s = ch['statistics']
                out['youtube'] = {'channel': ch['snippet']['title'], 'subscribers': s.get('subscriberCount'),
                                  'views': s.get('viewCount'), 'videos': s.get('videoCount')}
            except Exception as e:  # noqa: BLE001
                out['youtube'] = f'error: {str(e)[:100]}'
        key = self.cfg.get('itch_api_key')
        if key:
            try:
                req = urllib.request.Request(f'https://itch.io/api/1/{urllib.parse.quote(key)}/my-games',
                                             headers={'User-Agent': 'StarkHub'})
                with urllib.request.urlopen(req, timeout=10) as r:
                    games = json.load(r).get('games', [])
                out['itch'] = {'games': len(games), 'views': sum(g.get('views_count', 0) for g in games),
                               'downloads': sum(g.get('downloads_count', 0) for g in games),
                               'purchases': sum(g.get('purchases_count', 0) for g in games)}
            except Exception as e:  # noqa: BLE001
                out['itch'] = f'error: {str(e)[:100]}'
        self.stats_cache = (time.time(), out)
        return out

    # ---- approvals ----
    def approve(self, session, publish_at, platforms, ip):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', session or ''):
            raise ValueError('bad session id')
        man_p = os.path.join(self.edits, session, 'manifest.json')
        man = load_json(man_p, None)
        if not man:
            raise FileNotFoundError('no such edited session')
        if publish_at:
            dt = datetime.datetime.fromisoformat(publish_at.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                raise ValueError('publish time needs a time zone')
            publish_at = dt.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        platforms = [p for p in platforms if p in ('youtube', 'x', 'instagram', 'substack')]
        rec = {'session': session, 'approved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'approved_from': ip, 'publish_at': publish_at or None, 'platforms': platforms,
               'final': os.path.join(self.edits, session, man['final']),
               'social_clips': [os.path.join(self.edits, session, c) for c in man['social_clips']],
               'nonce': secrets.token_hex(8)}
        rec['token'] = publishers.sign_approval(rec, self.approval_key)
        path = os.path.join(self.approvals, session + '.json')
        os.makedirs(self.approvals, exist_ok=True)
        try:                                   # exclusive create: a session is approved (and published) once
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            raise AlreadyApproved(f'{session} is already approved') from None
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(rec, f, indent=1)
        log.info('APPROVED %s from %s publish_at=%s platforms=%s', session, ip, publish_at, platforms)
        if self.spawn_publishers:
            subprocess.Popen([sys.executable, os.path.join(ROOT, 'publishers.py'), '--approval', path], cwd=ROOT,
                             creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                             | getattr(subprocess, 'DETACHED_PROCESS', 0), close_fds=True)
        return rec


# =====================================================================================================
# scheduler: pre-arm 5 min before each shoot, optional auto-record at shoot time
# =====================================================================================================
def scheduler_tick(hub, now=None):
    now = now or time.time()
    shoots = load_shoots()                 # broken entries are skipped, so one bad shoot never blocks the others
    changed = False
    for s in shoots:
        s['start'] = float(s['start'])
        s.setdefault('id', uuid.uuid4().hex[:10])
        if not s.get('armed') and s['start'] - 300 <= now < s['start'] + 600:
            s['armed'] = True; changed = True
            try:
                done = hub.pre_arm()
                s['arm_result'] = 'OBS armed: ' + ', '.join(done)
            except Exception as e:  # noqa: BLE001
                s['arm_result'] = f'OBS not reachable: {e}'
            log.info('shoot %s pre-armed: %s', s['id'], s['arm_result'])
            try:
                tok = mint_login_token(600, hub.login_tokens)
                webbrowser.open(f'http://127.0.0.1:{hub.port}/?tab=prompter&shoot={s["id"]}&login={tok}')
            except Exception:  # noqa: BLE001
                pass
        if s.get('auto_record') and not s.get('rec_started') and s['start'] <= now < s['start'] + 600:
            s['rec_started'] = True; changed = True
            try:
                if not hub.obs_status().get('recording'):
                    hub.obs(('StartRecord', None))
                s['rec_result'] = 'recording started'
            except Exception as e:  # noqa: BLE001
                s['rec_result'] = f'could not start recording: {e}'
            log.info('shoot %s auto-record: %s', s['id'], s['rec_result'])
    if changed:
        save_json(SHOOTS, shoots)
    return shoots


def scheduler_loop(hub):
    while True:
        try:
            scheduler_tick(hub)
        except Exception as e:  # noqa: BLE001
            log.error('scheduler: %s', e)
        time.sleep(15)


# =====================================================================================================
# HTTP
# =====================================================================================================
DEFAULT_SCRIPT = """Hi! Today I'm building a tiny 3D world from scratch, offline, in one sitting.
First, pick a mood. I'll go with Sub-Zero Aurora.
Now I drop in some ruins, a few crystals and a couple of enemies.
Press P for drone mode, and grab a postcard.
That's it. Tell me in the comments which mood I should try next."""


def redact(path):
    """Hide PINs / login tokens in logged paths, %-encoded ones included."""
    return re.sub(r'(?i)(pin|login)(=|%3D)[^&\s]*', r'\1=***', path)


def load_shoots():
    """shoots.json without broken entries (non-finite start times would make /api/state invalid JSON)."""
    out = []
    data = load_json(SHOOTS, [])
    for x in (data if isinstance(data, list) else []):
        try:
            if isinstance(x, dict) and math.isfinite(float(x.get('start'))):
                out.append(x)
        except (TypeError, ValueError):
            pass
    return out


class Handler(http.server.BaseHTTPRequestHandler):
    hub = None
    server_version = 'StarkHub'
    timeout = 15                               # idle / slow sockets are dropped instead of pinning a thread

    def log_message(self, fmt, *a):
        pass

    def _ip(self):
        return self.client_address[0]

    def _send(self, code, body, ctype='application/json; charset=utf-8', extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)
        log.info('%s %s %s -> %d', self._ip(), self.command, redact(self.path)[:120], code)

    def _session_cookie(self):
        return f'gs_hub={self.hub.new_session()}; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Strict; Path=/'

    def _login_page(self, code, note=''):
        page = LOGIN_HTML.replace('{{NOTE}}', html.escape(note)).replace('{{TRUST}}', html.escape(TRUST_NOTE))
        self._send(code, page, 'text/html; charset=utf-8')

    def _pin_ok(self, given, ip):
        """Rate-limited, constant-time PIN check. -> True, False, or None when this address is locked out."""
        if self.hub.locked(ip):
            return None
        wait = self.hub.backoff()
        if wait:
            time.sleep(wait)
        if self.hub.check_pin(given):
            self.hub.note_auth(ip)
            return True
        self.hub.fail(ip)
        log.warning('wrong PIN from %s', ip)
        return False

    def _auth(self, u, q):
        """-> True (ok), or False after sending the reply (login page / 401 / 403 / 429).
        Order: Host allowlist, then a valid session cookie (never locked out), then the PIN header or a one-time QR
        login token (both rate limited per address). The PIN is never accepted from the URL."""
        ip = self._ip()
        if not self.hub.host_ok(self.headers.get('Host')):
            self._send(403, {'error': 'unknown host name'})
            return False
        cookies = dict(c.strip().split('=', 1) for c in (self.headers.get('Cookie') or '').split(';') if '=' in c)
        if 'gs_hub' in cookies and self.hub.check_cookie(cookies['gs_hub']):
            self.hub.note_auth(ip)
            return True
        tok = q.get('login', [None])[0]
        if tok is not None and self.command in ('GET', 'HEAD'):
            # One-time QR tokens are 192-bit random: they cannot be guessed, so a bad one is NOT a wrong PIN. Counting
            # it would let any web page (<img src=".../?login=x">) lock the phone's PIN login (audit L-5).
            if self.hub.consume_login(tok):
                self.hub.note_auth(ip)
                rest = urllib.parse.urlencode([(k, v) for k, vs in q.items() if k not in ('login', 'pin') for v in vs])
                self._send(302, b'', 'text/plain', {'Location': '/' + ('?' + rest if rest else ''),
                                                    'Set-Cookie': self._session_cookie()})
                return False
            self._login_page(401, 'That QR code was already used or has expired. Type the PIN instead.')
            return False
        if self.hub.locked(ip):
            self._send(429, {'error': 'too many wrong PINs; wait 15 minutes'})
            return False
        given = self.headers.get('X-Hub-Pin')
        if given is not None:
            ok = self._pin_ok(given, ip)
            if ok:
                return True
            if ok is None:
                self._send(429, {'error': 'too many wrong PINs; wait 15 minutes'})
                return False
        if u.path.startswith('/api/') or u.path.startswith('/media/'):
            self._send(401, {'error': 'PIN required'})
        else:
            self._login_page(401)
        return False

    def _login_post(self):
        """POST /login (form field pin): sets a random session cookie and redirects to '/'."""
        ip = self._ip()
        if not self.hub.host_ok(self.headers.get('Host')):
            return self._send(403, {'error': 'unknown host name'})
        n = self._length(4096)
        if n is None:
            return
        form = urllib.parse.parse_qs(self.rfile.read(n).decode('utf-8', 'replace'))
        ok = self._pin_ok((form.get('pin') or [''])[0], ip)
        if ok is None:
            return self._login_page(429, 'Too many wrong PINs from this device. Wait 15 minutes.')
        if not ok:
            return self._login_page(401, 'Wrong PIN. It is shown in the setup page (Your phone remote step).')
        return self._send(303, b'', 'text/plain', {'Location': '/', 'Set-Cookie': self._session_cookie()})

    def _length(self, limit):
        """Content-Length as an int in 0..limit, or None after sending 400/413."""
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if n < 0:
            self._send(400, {'error': 'bad Content-Length'})
            return None
        if n > limit:
            self._send(413, {'error': 'too large'})
            return None
        return n

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if not self._auth(u, q):
            return
        try:
            if u.path == '/':
                return self._send(200, HUB_HTML, 'text/html; charset=utf-8')
            if u.path == '/api/state':
                cfg = self.hub.cfg
                return self._send(200, {'shoots': load_shoots(), 'obs': self.hub.obs_status(),
                                        'sessions': list_sessions(self.hub.edits, self.hub.approvals),
                                        'vdo_push': obs_bridge.vdo_push_url(*obs_bridge.vdo_room(cfg)),
                                        'trust_note': TRUST_NOTE, 'now': time.time()})
            if u.path == '/api/stats':
                return self._send(200, self.hub.stats())
            if u.path == '/api/script':
                txt = DEFAULT_SCRIPT
                if os.path.isfile(SCRIPT):
                    with open(SCRIPT, encoding='utf-8') as f:
                        txt = f.read()
                return self._send(200, {'text': txt})
            if u.path == '/shoot.ics':
                sid = q.get('id', [''])[0]
                s = next((x for x in load_shoots() if x.get('id') == sid), None)
                if not s:
                    return self._send(404, {'error': 'no such shoot'})
                base = f'http://{lan_ip(self.hub.cfg)}:{self.hub.port}'      # never the request's Host header
                return self._send(200, ics_for(s, base), 'text/calendar; charset=utf-8',
                                  {'Content-Disposition': f'attachment; filename="shoot_{sid}.ics"'})
            if u.path.startswith('/media/'):
                return self._media(urllib.parse.unquote(u.path[len('/media/'):]))
            return self._send(404, {'error': 'not found'})
        except Exception as e:  # noqa: BLE001
            return self._send(400, {'error': f'{e.__class__.__name__}: {e}'})

    def _media(self, rel):
        root = os.path.realpath(self.hub.edits)
        p = os.path.realpath(os.path.join(root, rel))
        if not p.startswith(root + os.sep) or not p.lower().endswith(('.mp4', '.html', '.png')) or not os.path.isfile(p):
            return self._send(404, {'error': 'not found'})
        size = os.path.getsize(p)
        ctype = 'video/mp4' if p.lower().endswith('.mp4') else 'image/png' if p.endswith('.png') else 'text/html'
        rng = re.match(r'bytes=(\d*)-(\d*)', self.headers.get('Range') or '')
        start, end = 0, size - 1
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1)); end = int(rng.group(2)) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            end = min(end, size - 1)
            if start > end:
                return self._send(416, b'', 'text/plain', {'Content-Range': f'bytes */{size}'})
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(length))
        if rng:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        with open(p, 'rb') as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(1 << 16, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionError, OSError):
                    return
                left -= len(chunk)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == '/login':
            return self._login_post()
        if not self._auth(u, q):
            return
        if (self.headers.get('Content-Type') or '').split(';')[0] != 'application/json':
            return self._send(415, {'error': 'json only'})
        try:
            n = self._length(256 * 1024)
            if n is None:
                return
            body = json.loads(self.rfile.read(n) or b'{}')
            if not isinstance(body, dict):
                raise ValueError('JSON object expected')
            if u.path == '/api/shoots':
                start = float(body['start'])
                if not math.isfinite(start) or start > time.time() + 366 * 86400:
                    raise ValueError('pick a real date within the next year')
                if start < time.time() - 3600:
                    raise ValueError('that time is in the past')
                s = {'id': uuid.uuid4().hex[:10], 'title': str(body.get('title') or 'Shoot')[:120], 'start': start,
                     'auto_record': bool(body.get('auto_record')), 'countdown': int(body.get('countdown') or 10)}
                shoots = load_shoots() + [s]
                save_json(SHOOTS, sorted(shoots, key=lambda x: x['start']))
                log.info('shoot scheduled %s at %s', s['id'], datetime.datetime.fromtimestamp(start))
                return self._send(200, s)
            if u.path == '/api/shoots/delete':
                save_json(SHOOTS, [x for x in load_shoots() if x.get('id') != body.get('id')])
                return self._send(200, {'ok': True})
            if u.path == '/api/obs/toggle':
                r = self.hub.obs(('ToggleRecord', None))[0]
                self.hub.obs_cache = (0, None)
                log.info('record toggled from %s -> %s', self._ip(), r.get('outputActive'))
                return self._send(200, {'recording': bool(r.get('outputActive'))})
            if u.path == '/api/obs/arm':
                return self._send(200, {'done': self.hub.pre_arm()})
            if u.path == '/api/script':
                os.makedirs(STATE, exist_ok=True)
                with open(SCRIPT, 'w', encoding='utf-8') as f:
                    f.write(str(body.get('text', ''))[:50000])
                return self._send(200, {'ok': True})
            if u.path == '/api/approve':
                rec = self.hub.approve(body.get('session'), body.get('publish_at') or '', body.get('platforms') or [],
                                       self._ip())
                return self._send(200, {'approved': rec['session'], 'publish_at': rec['publish_at']})
            return self._send(404, {'error': 'not found'})
        except AlreadyApproved as e:
            return self._send(409, {'error': f'{e}; nothing was published again'})
        except (OSError, ConnectionError) as e:
            return self._send(503, {'error': f'OBS not reachable: {e}'})
        except Exception as e:  # noqa: BLE001
            return self._send(400, {'error': f'{e.__class__.__name__}: {e}'})


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Threaded, with at most PER_IP connections per client address and MAX_CONNS overall; extra ones are closed
    immediately. The per-address cap means one LAN device holding idle sockets cannot lock the owner (or the phone)
    out (audit M-C); the global cap only bounds threads."""
    daemon_threads = True
    MAX_CONNS = 256
    PER_IP = 8

    def __init__(self, *a, **kw):
        self.slots = threading.BoundedSemaphore(self.MAX_CONNS)
        self.per_ip, self.per_ip_lock = {}, threading.Lock()
        super().__init__(*a, **kw)

    def _take(self, ip):
        with self.per_ip_lock:
            # The PC itself (loopback: the owner's own browser, the scheduler) is only bound by the global cap.
            loop = ip in ('127.0.0.1', '::1', '::ffff:127.0.0.1')
            if not loop and self.per_ip.get(ip, 0) >= self.PER_IP:
                return False
            if not self.slots.acquire(blocking=False):
                return False
            self.per_ip[ip] = self.per_ip.get(ip, 0) + 1
            return True

    def _give(self, ip):
        with self.per_ip_lock:
            n = self.per_ip.get(ip, 1) - 1
            if n > 0:
                self.per_ip[ip] = n
            else:
                self.per_ip.pop(ip, None)
            self.slots.release()

    def process_request(self, request, client_address):
        ip = client_address[0]
        if not self._take(ip):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._give(ip)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._give(client_address[0])

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return                              # the client went away; nothing to report
        super().handle_error(request, client_address)


def make_server(host='127.0.0.1', port=PORT, cfg=None, **hub_kw):
    if classroom_mode():
        raise PermissionError('the Creator Hub (phone hub, publishing) is switched off in classroom mode')
    cfg = cfg or ensure_hub_keys()
    srv = Server((host, port), type('H', (Handler,), {}))
    hub = Hub(cfg, srv.server_address[1], **hub_kw)
    srv.RequestHandlerClass.hub = hub
    return srv, hub


LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Stark World Engine Hub</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#101418;color:#e9eef2;
font:18px system-ui,sans-serif;display:flex;justify-content:center;padding-top:20vh}input,button{font:inherit;padding:12px;
border-radius:10px;border:1px solid #2a3742;background:#182028;color:#e9eef2}button{background:#5fd3b5;color:#05231c}
p{color:#93a3b1;font-size:14px;max-width:340px}.n{color:#f5b84a}</style>
</head><body><form method="post" action="/login"><h2>Stark World Engine Creator Hub</h2><p class="n">{{NOTE}}</p><input name="pin" inputmode="numeric" pattern="[0-9]{6}"
maxlength="6" autocomplete="one-time-code" placeholder="6-digit PIN" autofocus> <button>Open</button><p>{{TRUST}}</p></form></body></html>"""

HUB_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Stark World Engine Creator Hub</title>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="apple-mobile-web-app-capable" content="yes">
<style>
:root{--bg:#101418;--card:#182028;--ink:#e9eef2;--mute:#93a3b1;--acc:#5fd3b5;--rec:#e5484d;--line:#2a3742}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px system-ui,-apple-system,sans-serif;padding-bottom:84px}
header{padding:14px 16px 6px;display:flex;justify-content:space-between;align-items:center}h1{font-size:19px;margin:0}
.pill{font-size:13px;padding:4px 10px;border-radius:99px;background:var(--card);color:var(--mute)}.pill.rec{background:var(--rec);color:#fff}
nav{position:fixed;bottom:0;left:0;right:0;display:flex;background:var(--card);border-top:1px solid var(--line);padding-bottom:env(safe-area-inset-bottom)}
nav button{flex:1;background:none;border:0;color:var(--mute);padding:12px 2px;font-size:12px}nav button.on{color:var(--acc)}
section{padding:8px 16px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:10px 0}
input,button.b,select,textarea{font:inherit;color:var(--ink);background:#0d1115;border:1px solid var(--line);border-radius:10px;padding:11px;width:100%}
button.b{background:var(--acc);color:#05231c;font-weight:600;border:0;margin-top:8px}button.b.sec{background:#26323d;color:var(--ink)}
label{display:block;color:var(--mute);font-size:13px;margin:10px 0 4px}.row{display:flex;gap:8px}.mute{color:var(--mute);font-size:13px}
video{width:100%;border-radius:10px;background:#000}.clips{display:flex;gap:8px;overflow-x:auto}.clips video{width:120px;flex:none}
#prompter{position:fixed;inset:0;background:#000;color:#fff;font-size:34px;line-height:1.35;padding:40vh 7vw;overflow:hidden;display:none;z-index:5}
#prompter .txt{white-space:pre-wrap;transform:scaleX(1)}#prompter.mirror .txt{transform:scaleX(-1)}
#pbar{position:fixed;top:0;left:0;right:0;display:none;z-index:6;padding:10px;gap:8px;background:rgba(0,0,0,.6)}
#pbar button{flex:1;padding:10px;border-radius:8px;border:0;font:inherit}#recDot{position:fixed;top:60px;right:16px;z-index:6;display:none;font-size:20px;color:var(--rec)}
#count{position:fixed;inset:0;display:none;align-items:center;justify-content:center;font-size:30vw;z-index:7;color:#fff;background:rgba(0,0,0,.5)}
a{color:var(--acc)}
</style></head><body>
<header><h1>Stark World Engine Creator Hub</h1><span id="obs" class="pill">OBS ?</span></header><p class="mute" style="padding:0 16px;margin:0">Trusted home Wi-Fi only: the hub is plain HTTP on your local network.</p>
<section id="tab-schedule"><div class="card"><b>Shoot Scheduler</b><label>Title</label><input id="sTitle" placeholder="Aurora world build">
<label>Date and time</label><input id="sWhen" type="datetime-local"><label><input id="sAuto" type="checkbox" style="width:auto"> Auto-record at shoot time (countdown on the teleprompter)</label>
<button class="b" onclick="addShoot()">Schedule</button><p class="mute">5 minutes before, OBS is pre-armed (profile, scene collection, scene) and the teleprompter opens on the PC. Add the .ics to your calendar for a reminder that links back here.</p></div><div id="shoots"></div></section>
<section id="tab-camera" hidden><div class="card"><b>iPhone camera into OBS</b><p class="mute">Safari only allows the camera on HTTPS pages, so this opens the free VDO.Ninja push page. OBS already has the matching "iPhone_Remote_Cam" browser source.</p>
<a id="vdo" class="b" style="display:block;text-align:center;padding:14px;border-radius:10px;background:var(--acc);color:#05231c;text-decoration:none;font-weight:600" target="_blank" rel="noopener">Start iPhone camera (VDO.Ninja, HTTPS)</a></div>
<div class="card"><b>OBS</b><button class="b sec" onclick="arm()">Pre-arm OBS now</button><button class="b" onclick="toggleRec()">Start / stop recording</button></div></section>
<section id="tab-prompter" hidden><div class="card"><b>Teleprompter</b><textarea id="script" rows="9"></textarea><button class="b sec" onclick="saveScript()">Save script</button>
<label>Speed</label><input id="speed" type="range" min="10" max="160" value="45"><label><input id="mirror" type="checkbox" style="width:auto"> Mirror (beam-splitter glass)</label>
<button class="b" onclick="openPrompter()">Open full-screen prompter</button><p class="mute">In the prompter: tap the text or press Space to start/stop OBS recording. Swipe or use the buttons to scroll.</p></div></section>
<section id="tab-review" hidden><div id="sessions"></div></section>
<section id="tab-stats" hidden><div class="card" id="stats">Loading...</div></section>
<div id="prompter"><div class="txt" id="ptxt"></div></div><div id="pbar"><button onclick="pScroll(-200)">Up</button><button onclick="pPause()" id="pp">Pause</button><button onclick="toggleRec()">REC</button><button onclick="closePrompter()">Close</button></div>
<div id="recDot">REC</div><div id="count"></div>
<nav><button data-t="schedule">Schedule</button><button data-t="camera">Camera</button><button data-t="prompter">Prompter</button><button data-t="review">Review</button><button data-t="stats">Stats</button></nav>
<script>
var ST={},PY=0,PRUN=true,RAF=0,CD=null;
function $(i){return document.getElementById(i);}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return'&#'+c.charCodeAt(0)+';';});}
function api(p,b){return fetch(p,b?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b),credentials:'same-origin'}:{credentials:'same-origin'}).then(function(r){return r.json().then(function(j){if(!r.ok)throw new Error(j.error||r.status);return j;});});}
function tab(t){document.querySelectorAll('section').forEach(function(s){s.hidden=s.id!=='tab-'+t;});document.querySelectorAll('nav button').forEach(function(b){b.classList.toggle('on',b.dataset.t===t);});if(t==='stats')loadStats();}
function fmt(ts){return new Date(ts*1000).toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});}
function refresh(){api('/api/state').then(function(s){ST=s;var o=s.obs;$('obs').textContent=o.online?(o.recording?'REC '+(o.timecode||''):'OBS ready'):'OBS offline';$('obs').classList.toggle('rec',!!o.recording);$('recDot').style.display=o.recording&&$('prompter').style.display==='block'?'block':'none';
 $('vdo').href=s.vdo_push;
 $('shoots').innerHTML=s.shoots.map(function(x){return'<div class="card"><b>'+esc(x.title)+'</b><div class="mute">'+fmt(x.start)+(x.auto_record?' - auto-record':'')+'</div><div class="mute">'+esc(x.arm_result||'')+' '+esc(x.rec_result||'')+'</div><div class="row"><a class="b sec" style="text-align:center;text-decoration:none;display:block;padding:11px;border-radius:10px;background:#26323d;color:#e9eef2;flex:1;margin-top:8px" href="/shoot.ics?id='+x.id+'">Add to calendar (.ics)</a><button class="b sec" style="flex:none;width:auto" onclick="delShoot(\''+x.id+'\')">Delete</button></div></div>';}).join('')||'<p class="mute">No shoots scheduled.</p>';
 var open=location.search.match(/session=([\w-]+)/);
 $('sessions').innerHTML=s.sessions.map(function(m){var id=m.session;return'<div class="card"><b>'+esc(id)+'</b><div class="mute">'+m.final_s+' s, '+m.lufs+' LUFS, captions: '+esc(m.captions)+'</div><video controls playsinline preload="metadata" src="/media/'+id+'/'+m.final+'"></video><div class="clips">'+m.social_clips.map(function(c){return'<video controls playsinline preload="metadata" src="/media/'+id+'/'+c+'"></video>';}).join('')+'</div>'+
  (m.approved?'<p>Approved'+(m.publish_at?' - scheduled for '+esc(new Date(m.publish_at).toLocaleString()):'')+'</p>':'<label>Publish date and time (optional; YouTube keeps it private until then)</label><input type="datetime-local" id="pa_'+id+'"><label>Send to</label><div class="mute"><label><input type="checkbox" style="width:auto" id="pf_yt_'+id+'" checked> YouTube upload (your own API project)</label><label><input type="checkbox" style="width:auto" id="pf_x_'+id+'"> X draft</label><label><input type="checkbox" style="width:auto" id="pf_ig_'+id+'"> Instagram draft</label><label><input type="checkbox" style="width:auto" id="pf_ss_'+id+'"> Substack draft</label></div><button class="b" onclick="approve(\''+id+'\')">Approve</button>')+'</div>';}).join('')||'<p class="mute">No edited sessions yet. Record in OBS; the auto editor picks the files up from raw_clips.</p>';});}
function addShoot(){var w=$('sWhen').value;if(!w){alert('Pick a date and time');return;}api('/api/shoots',{title:$('sTitle').value,start:new Date(w).getTime()/1000,auto_record:$('sAuto').checked}).then(refresh).catch(function(e){alert(e.message);});}
function delShoot(id){api('/api/shoots/delete',{id:id}).then(refresh);}
function arm(){api('/api/obs/arm',{}).then(function(r){alert('OBS: '+(r.done.join(', ')||'nothing changed'));refresh();}).catch(function(e){alert(e.message);});}
function toggleRec(){api('/api/obs/toggle',{}).then(function(r){refresh();}).catch(function(e){alert(e.message);});}
function approve(id){var pa=$('pa_'+id).value,pf=[];if($('pf_yt_'+id).checked)pf.push('youtube');if($('pf_x_'+id).checked)pf.push('x');if($('pf_ig_'+id).checked)pf.push('instagram');if($('pf_ss_'+id).checked)pf.push('substack');
 if(!confirm('Approve '+id+(pa?' for '+new Date(pa).toLocaleString():'')+'? Publishing tools run after this.'))return;
 api('/api/approve',{session:id,publish_at:pa?new Date(pa).toISOString():'',platforms:pf}).then(function(){refresh();}).catch(function(e){alert(e.message);});}
function loadStats(){api('/api/stats').then(function(s){function show(k,v){return'<p><b>'+k+'</b>: '+(typeof v==='string'?esc(v):Object.keys(v).map(function(x){return esc(x)+' '+esc(v[x]);}).join(', '))+'</p>';}$('stats').innerHTML=show('YouTube',s.youtube)+show('itch.io',s.itch)+'<p class="mute">Stats use only your own free API access. "not connected" means nothing is configured.</p>';}).catch(function(e){$('stats').textContent=e.message;});}
function saveScript(){api('/api/script',{text:$('script').value});}
function openPrompter(){$('ptxt').textContent=$('script').value;$('prompter').classList.toggle('mirror',$('mirror').checked);$('prompter').style.display='block';$('pbar').style.display='flex';PY=0;PRUN=true;$('pp').textContent='Pause';cancelAnimationFrame(RAF);var last=performance.now();
 (function step(t){RAF=requestAnimationFrame(step);var dt=(t-last)/1000;last=t;if(PRUN&&!CD)PY+=dt*+$('speed').value;$('ptxt').style.marginTop=(-PY)+'px';})(last);
 var m=location.search.match(/shoot=(\w+)/),sh=m&&ST.shoots&&ST.shoots.find(function(x){return x.id===m[1];});if(sh&&sh.auto_record){var left=Math.round(sh.start-Date.now()/1000);if(left>0&&left<600)countdown(left);}}
function countdown(n){CD=n;$('count').style.display='flex';(function tick(){$('count').textContent=CD>60?Math.ceil(CD/60)+'m':CD;if(CD<=0){$('count').style.display='none';CD=null;refresh();return;}CD--;setTimeout(tick,1000);})();}
function closePrompter(){$('prompter').style.display='none';$('pbar').style.display='none';cancelAnimationFrame(RAF);}
function pScroll(d){PY=Math.max(0,PY+d);}function pPause(){PRUN=!PRUN;$('pp').textContent=PRUN?'Pause':'Play';}
$('prompter').addEventListener('click',toggleRec);
window.addEventListener('keydown',function(e){if($('prompter').style.display==='block'&&e.code==='Space'){e.preventDefault();toggleRec();}});
document.querySelectorAll('nav button').forEach(function(b){b.onclick=function(){tab(b.dataset.t);};});
api('/api/script').then(function(s){$('script').value=s.text;var t=(location.search.match(/tab=(\w+)/)||[])[1]||'schedule';tab(t);if(t==='prompter'&&/shoot=/.test(location.search))setTimeout(openPrompter,400);});
refresh();setInterval(refresh,4000);
</script></body></html>"""


def main(argv=None):
    if classroom_mode():
        print('REFUSED: the Creator Hub (phone hub, publishing) is switched off in classroom mode (config.json classroom_profile).')
        return 3
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--host', default=None, help='bind address (default 127.0.0.1; 0.0.0.0 with --phone)')
    ap.add_argument('--phone', action='store_true',
                    help='phone mode: listen on the home network (0.0.0.0) so your phone can open the hub')
    ap.add_argument('--port', type=int, default=PORT)
    ap.add_argument('--qr', action='store_true', help='write .claude/iphone_qr.html and exit')
    ap.add_argument('--ip', default=None, help='LAN IP for the QR link (default: detected / config lan_ip)')
    ap.add_argument('--no-scheduler', action='store_true')
    ap.add_argument('--no-publishers', action='store_true', help='Approve records only; do not start publishers.py')
    a = ap.parse_args(argv)
    try:
        cfg = ensure_hub_keys()
        cfg = obs_bridge.ensure_vdo_keys()
    except ValueError as e:                # config.json damaged by hand: say so (the wizard points at hub.log)
        log.error('hub not started: %s', e)
        print(f'Creator Hub not started: {e}')
        return 2
    for secret in (CONFIG, publishers.approval_key_path(), publishers.YT_TOKEN, LOGIN_TOKENS):
        publishers.restrict_to_user(secret)
    if a.qr:
        url = hub_url(cfg, a.ip, a.port, mint_login_token(LOGIN_TTL))
        p = write_qr_page(url, str(cfg['hub_pin']))
        publishers.restrict_to_user(p)
        print('wrote', p, 'for', redact(url), f'(one-time QR login, valid {LOGIN_TTL // 60} min; or type the PIN)')
        return 0
    if len(str(cfg.get('hub_pin', '')).strip()) < 4:
        log.warning('config.json "hub_pin" is empty or shorter than 4 characters: PIN logins are disabled')
        print('WARNING: config.json "hub_pin" is empty or too short, so PIN logins are disabled. Put a 6-digit PIN '
              'there (or delete the key to get a new one) and restart the hub.')
    host = a.host or ('0.0.0.0' if a.phone else '127.0.0.1')     # security review F-06: loopback unless phone mode
    srv, hub = make_server(host, a.port, cfg, spawn_publishers=not a.no_publishers)
    log.info('hub listening on %s:%d (pid %d)', host, srv.server_address[1], os.getpid())
    if host in ('127.0.0.1', 'localhost', '::1'):
        print(f'Creator Hub on http://127.0.0.1:{srv.server_address[1]}/  (this PC only; start it with --phone, '
              f'or from START_CREATOR_HUB.bat, to use it from your phone)')
    else:
        print(f'Creator Hub on http://{lan_ip(cfg)}:{srv.server_address[1]}/  (phone mode; PIN shown in the setup page)')
    if not a.no_scheduler:
        threading.Thread(target=scheduler_loop, args=(hub,), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
