"""setup_wizard.py: the friendly first-run setup for the Stark World Engine creator suite. A local web page with a
checklist that turns green step by step: tools, camera + mic, phone hub, a first auto-edited clip, YouTube.

  python setup_wizard.py                 open the wizard in your browser (http://127.0.0.1:<free port>/)
  python setup_wizard.py --no-browser    only print the address
  python setup_wizard.py --reset         forget the progress (.claude/setup_state.json) and start over
  python setup_wizard.py --mock          demo / test mode: fake camera, mic, firewall, installs and Google login
  options: --port N (wizard page), --hub-port N (phone hub, default 8510), --obs-root DIR (OBS config folder)

Safety
  - Listens on 127.0.0.1 only. Every request needs this run's secret token (cookie set from the address the
    wizard opens) and a 127.0.0.1/localhost Host header; POSTs must be JSON. Other web pages cannot drive it.
  - Nothing is installed, allowed or connected without a click: winget runs in a visible window, the firewall rule
    needs your "Yes" on the Windows prompt, Google sign-in happens in your own browser.
  - The firewall button runs exactly one command (creator_hub.FIREWALL_CMD: inbound TCP 8510, LocalSubnet only).
    It never changes the network profile (Public/Private).
  - config.json only ever gains MISSING keys (gs_common.merge_config_keys, original backed up). An existing
    client_secrets.json is never replaced without asking, and a backup is kept.
  - Progress lives in .claude/setup_state.json, so closing the page and running this again resumes where you left.
"""
import argparse, base64, datetime, hmac, html, http.server, importlib, importlib.util, json, os, re, secrets, shutil
import socket, socketserver, subprocess, sys, sysconfig, tempfile, threading, time, urllib.parse, webbrowser

from gs_common import (CLIENT_SECRETS, ROOT, STATE, ensure_hub_keys, find_ffmpeg, get_logger, lan_ip, load_config,
                       merge_config_keys)
import obs_bridge
import creator_hub
from publishers import restrict_to_user

STATE_FILE = os.path.join(STATE, 'setup_state.json')
LOCK_FILE = os.path.join(STATE, 'setup_wizard.lock')
DOCS = os.path.join(ROOT, 'docs_product')
HELP_FILES = [os.path.join(ROOT, 'HELP.html'), os.path.join(DOCS, 'help', 'index.html')]
STEPS = ['welcome', 'tools', 'devices', 'phone', 'record', 'youtube', 'done']
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
NEWCON = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
DETACH = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
RULE_NAME = 'Stark World Engine Creator Hub 8510'
WINGET = {'ffmpeg': ('Gyan.FFmpeg', 'FFmpeg'), 'obs': ('OBSProject.OBSStudio', 'OBS Studio')}
PIP_GOOGLE = ['google-api-python-client==2.151.0', 'google-auth-oauthlib==1.2.1']  # security review F-13: pinned (top level)
# Only these official pages can be opened from the wizard (in the user's own browser).
LINKS = {
    'ffmpeg': 'https://ffmpeg.org/download.html',
    'obs': 'https://obsproject.com/download',
    'chrome': 'https://www.google.com/chrome/',
    'python': 'https://www.python.org/downloads/',
    'g_project': 'https://console.cloud.google.com/projectcreate',
    'g_api': 'https://console.cloud.google.com/apis/library/youtube.googleapis.com',
    'g_consent': 'https://console.cloud.google.com/apis/credentials/consent',
    'g_creds': 'https://console.cloud.google.com/apis/credentials',
}
log = get_logger('setup_wizard', 'setup_wizard.log')


# =====================================================================================================
# state (resumable)
# =====================================================================================================
_state_lock = threading.Lock()


def load_state(path=None):
    path = path or STATE_FILE
    try:
        with open(path, encoding='utf-8') as f:
            st = json.load(f)
        if isinstance(st, dict):
            for k in ('done', 'skipped', 'choices'):      # a damaged entry restarts that part, never crashes
                if not isinstance(st.get(k), dict):
                    st[k] = {}
            return st
    except (OSError, ValueError):
        pass
    return {'version': 1, 'done': {}, 'skipped': {}, 'choices': {}}


def save_state(st, path=None):
    path = path or STATE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    st['updated'] = datetime.datetime.now().isoformat(timespec='seconds')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, path)


def update_state(fn, path=None):
    """Read-modify-write under a lock. fn(state) mutates it. -> the new state."""
    with _state_lock:
        st = load_state(path)
        fn(st)
        save_state(st, path)
        return st


def mark(step, how='done', path=None):
    def f(st):
        st['skipped'].pop(step, None)
        st['done'].pop(step, None)
        (st['done'] if how == 'done' else st['skipped'])[step] = datetime.datetime.now().isoformat(timespec='seconds')
    return update_state(f, path)


def current_step(st):
    """First step that is neither done nor skipped (resume point)."""
    for s in STEPS:
        if s not in st['done'] and s not in st['skipped']:
            return s
    return 'done'


# =====================================================================================================
# small helpers
# =====================================================================================================
def port_open(host, port, timeout=0.6):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def first_file(paths):
    return next((p for p in paths if p and os.path.isfile(p)), None)


def program_files():
    return [os.environ.get(k) for k in ('ProgramFiles', 'ProgramW6432', 'ProgramFiles(x86)') if os.environ.get(k)]


def find_obs():
    return first_file([os.path.join(pf, 'obs-studio', 'bin', '64bit', 'obs64.exe') for pf in program_files()]
                      + [shutil.which('obs64') or ''])


def find_browser():
    local = os.environ.get('LOCALAPPDATA', '')
    chrome = first_file([os.path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe') for pf in program_files()]
                        + [os.path.join(local, 'Google', 'Chrome', 'Application', 'chrome.exe')])
    if chrome:
        return chrome, 'Chrome'
    edge = first_file([os.path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe') for pf in program_files()])
    return (edge, 'Edge') if edge else (None, None)


# Runs inside the visible install window: argv[1] = window title, argv[2:] = the command as an argument list.
VISIBLE_RUNNER = r'''import ctypes, subprocess, sys
title = sys.argv[1]
try:
    ctypes.windll.kernel32.SetConsoleTitleW(title)
except Exception:
    pass
print(title + "\n")
try:
    rc = subprocess.call(sys.argv[2:])
except OSError as e:
    print("Could not start %s: %s" % (sys.argv[2], e))
    rc = 1
print()
print("All done. Go back to the setup page in your browser." if rc == 0 else
      "That did not finish (code %s). Scroll up for the reason, then try the button again." % rc)
try:
    input("Press Enter to close this window.")
except EOFError:
    pass
'''


def bundled_site_packages():
    """The bundled runtime's Lib\\site-packages folder (on sys.path through its ._pth file), or None."""
    lib = os.path.normcase(os.path.join(os.path.dirname(sys.executable), 'Lib', 'site-packages'))
    for p in sys.path:
        if os.path.normcase(os.path.abspath(p)) == lib and os.path.isdir(p):
            return os.path.abspath(p)
    return None


def find_pip_python():
    """-> full path of an installed Python 3 that has pip (py launcher, python, python3), or None. The Microsoft
    Store 'python' stub and interpreters without pip are skipped."""
    env = dict(os.environ, PYTHONIOENCODING='utf-8')       # its path may hold "Łukasz": print it as UTF-8
    for cmd in (['py', '-3'], ['python'], ['python3']):
        if not shutil.which(cmd[0]):
            continue
        try:
            r = subprocess.run(cmd + ['-c', 'import sys, pip; print(sys.executable)'], capture_output=True,
                               timeout=20, env=env, creationflags=NOWIN)
        except (OSError, subprocess.SubprocessError):
            continue
        exe = r.stdout.decode('utf-8', 'replace').strip().splitlines()[-1:] if r.returncode == 0 else []
        if exe and os.path.isfile(exe[0]) and os.path.normcase(exe[0]) != os.path.normcase(sys.executable):
            return exe[0]
    return None


def ps_encoded(command):
    """PowerShell -EncodedCommand payload (UTF-16LE base64): no quoting surprises."""
    return base64.b64encode(command.encode('utf-16-le')).decode('ascii')


def elevate_command(command):
    """The PowerShell line that asks Windows (UAC) to run exactly `command` as administrator and waits for it."""
    return ("Start-Process -FilePath powershell.exe -Verb RunAs -Wait -ArgumentList "
            f"'-NoProfile','-EncodedCommand','{ps_encoded(command)}'")


def level_pct(db):
    """dBFS -> 0..100 for the meter (-60 dB and below = 0)."""
    return max(0, min(100, round((db + 60) * 100 / 60)))


def parse_levels(text, points=30):
    """ffmpeg astats/ametadata log -> (meter values 0..100 resampled to `points`, loudest RMS in dB)."""
    vals = []
    for m in re.finditer(r'lavfi\.astats\.Overall\.RMS_level=(-?inf|-?[\d.]+)', text):
        v = m.group(1)
        vals.append(-120.0 if 'inf' in v else float(v))
    if not vals:
        return [], -120.0
    step = max(1, len(vals) // points)
    chunks = [vals[i:i + step] for i in range(0, len(vals), step)][:points]
    return [level_pct(max(c)) for c in chunks], round(max(vals), 1)


def md_to_html(text):
    """Tiny Markdown subset for the help docs (headings, lists, quotes, code, bold, links)."""
    out, in_code, in_list = [], False, None

    def inline(s):
        s = html.escape(s)
        s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
        s = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', s)

        def link(m):
            label, href = m.group(1), html.unescape(m.group(2))
            if re.match(r'https?://', href):
                return f'<a href="{html.escape(href)}" target="_blank" rel="noopener">{label}</a>'
            name = re.match(r'([A-Za-z_]+)\.md', href)
            return f'<a href="/docs/{name.group(1)}">{label}</a>' if name else label
        return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, s)

    def close_list():
        nonlocal in_list
        if in_list:
            out.append(f'</{in_list}>')
            in_list = None
    for line in text.splitlines():
        if line.startswith('```'):
            close_list()
            out.append('</pre>' if in_code else '<pre>')
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        m = re.match(r'(#{1,4})\s+(.*)', line)
        lm = re.match(r'\s*(?:[-*]|(\d+)\.)\s+(.*)', line)
        if m:
            close_list()
            n = len(m.group(1))
            out.append(f'<h{n}>{inline(m.group(2))}</h{n}>')
        elif lm:
            kind = 'ol' if lm.group(1) else 'ul'
            if in_list != kind:
                close_list()
                out.append(f'<{kind}>')
                in_list = kind
            out.append(f'<li>{inline(lm.group(2))}</li>')
        elif line.startswith('>'):
            close_list()
            out.append(f'<blockquote>{inline(line.lstrip("> "))}</blockquote>')
        elif line.strip() in ('---', '***'):
            close_list()
            out.append('<hr>')
        elif line.strip():
            close_list()
            out.append(f'<p>{inline(line)}</p>')
        else:
            close_list()
    close_list()
    if in_code:
        out.append('</pre>')
    return '\n'.join(out)


def check_client_secrets(text):
    """-> (ok, message, parsed). A Google OAuth *Desktop app* client JSON has an "installed" section."""
    if len(text) > 64 * 1024:
        return False, 'That file is too big to be a client_secrets.json.', None
    try:
        data = json.loads(text)
    except ValueError:
        return False, 'That is not a JSON file. Download the client again from the Credentials page (step 4).', None
    if not isinstance(data, dict):
        return False, 'That JSON does not look like a Google OAuth client.', None
    if 'web' in data and 'installed' not in data:
        return False, ('This is a "Web application" client. Make a "Desktop app" client instead (step 4) and '
                       'download that one.'), None
    inst = data.get('installed')
    if not isinstance(inst, dict) or not inst.get('client_id') or not inst.get('client_secret'):
        return False, 'This JSON is missing the client ID or secret. Download it again from step 4.', None
    if not str(inst['client_id']).endswith('.apps.googleusercontent.com'):
        return False, 'The client ID does not look like a Google one. Download it again from step 4.', None
    return True, 'Looks perfect: a Google "Desktop app" client.', data


# =====================================================================================================
# the machine: real by default, every side effect in one place so --mock can replace it
# =====================================================================================================
class RealEnv:
    mock = False

    def __init__(self, hub_port=creator_hub.PORT, obs_root=None, state_path=None):
        self.hub_port, self.obs_root, self.state_path = hub_port, obs_root, state_path
        self._fw = (0, None)
        self.cfg = load_config()

    # ---- tools ----
    def ffmpeg(self):
        return find_ffmpeg(load_config())

    def tools(self):
        ff, probe = self.ffmpeg()
        obs = find_obs()
        br, brname = find_browser()
        py_ok = sys.version_info >= (3, 10)
        return {
            'python': {'ok': py_ok, 'detail': f'Python {sys.version.split()[0]}' + ('' if py_ok else ' (3.10+ needed)')},
            'ffmpeg': {'ok': bool(ff and probe), 'detail': ff or 'not found'},
            'obs': {'ok': bool(obs), 'detail': obs or 'not found'},
            'browser': {'ok': bool(br), 'detail': f'{brname}: {br}' if br else 'Chrome or Edge not found'},
            'winget': bool(shutil.which('winget')),
        }

    def run_visible(self, title, argv, tag=None):
        """Run `argv` (an argument LIST) in a NEW visible console window the user can watch; it waits for Enter at
        the end. No cmd.exe and no .cmd file are involved, so "&", "%", "^" or "José"/"Łukasz" in the install path
        or in sys.executable are plain characters, never shell syntax (audit M-B)."""
        subprocess.Popen([sys.executable, '-I', '-c', VISIBLE_RUNNER, str(title)] + [str(a) for a in argv],
                         creationflags=NEWCON, cwd=ROOT)
        return {'started': True}

    def install(self, tool):
        pkg, label = WINGET[tool]
        return self.run_visible(f'Installing {label} (Stark World Engine setup)',
                                ['winget', 'install', '-e', '--id', pkg, '--accept-package-agreements',
                                 '--accept-source-agreements'], tool)

    def pip_google(self):
        title = 'Installing the YouTube helper (Stark World Engine setup)'
        if importlib.util.find_spec('pip') is not None:
            return self.run_visible(title, [sys.executable, '-m', 'pip', 'install', '--user'] + PIP_GOOGLE, 'pip')
        # The bundled runtime (python.org "embeddable" build) has no pip and ignores the user site folder, so
        # "pip install --user" can never work there. Use an installed Python's pip to put wheels built for THIS
        # interpreter into the runtime's own site-packages (already on its sys.path via the ._pth file).
        site_dir = bundled_site_packages()
        helper = find_pip_python()
        if not site_dir or not helper:
            return {'started': False, 'link': LINKS['python'],
                    'msg': ('The YouTube helper needs Python from python.org once (free). Install it (tick "Add '
                            'python.exe to PATH"), then click "Install YouTube helper" again.')}
        ver = f'{sys.version_info[0]}.{sys.version_info[1]}'
        plat = sysconfig.get_platform().replace('-', '_').replace('.', '_')
        return self.run_visible(title, [helper, '-m', 'pip', 'install', '--upgrade', '--target', site_dir,
                                        '--python-version', ver, '--implementation', 'cp', '--platform', plat,
                                        '--only-binary=:all:'] + PIP_GOOGLE, 'pip')

    def google_libs(self):
        importlib.invalidate_caches()          # the helper may have just been installed by the window above
        try:
            import google_auth_oauthlib.flow  # noqa: F401
            import googleapiclient  # noqa: F401
            return True
        except ImportError:
            return False

    def open_url(self, url):
        webbrowser.open(url)

    # ---- devices ----
    def devices(self):
        ff = self.ffmpeg()[0]
        return obs_bridge.list_dshow_devices(ff) if ff else []

    def video_input(self, name):
        return ['-f', 'dshow', '-rtbufsize', '256M', '-i', f'video={name}']

    def audio_input(self, name):
        return ['-f', 'dshow', '-i', f'audio={name}']

    def av_input(self, cam, mic):
        spec = f'video={cam}' + (f':audio={mic}' if mic else '')
        return ['-f', 'dshow', '-rtbufsize', '512M', '-i', spec]

    def write_obs(self, devs, camera, mic):
        return obs_bridge.write_all(self.obs_root, devs=devs, camera=camera, mic=mic)

    # ---- phone / firewall ----
    def firewall(self, force=False):
        """-> {'rule': bool, 'profile': 'Public'|'Private'|...}. Read-only; cached a few seconds."""
        if not force and time.time() - self._fw[0] < 8 and self._fw[1]:
            return self._fw[1]
        ps = (f"$r = Get-NetFirewallRule -DisplayName '{RULE_NAME}' -ErrorAction SilentlyContinue | "
              "Where-Object { $_.Enabled -eq 'True' }; "
              "$p = (Get-NetConnectionProfile -ErrorAction SilentlyContinue | Select-Object -First 1).NetworkCategory; "
              "Write-Output ('RULE=' + [bool]$r); Write-Output ('PROFILE=' + $p)")
        res = {'rule': False, 'profile': 'unknown'}
        try:
            r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True,
                               text=True, errors='replace', timeout=30, creationflags=NOWIN)
            res['rule'] = 'RULE=True' in (r.stdout or '')
            m = re.search(r'PROFILE=(\w*)', r.stdout or '')
            res['profile'] = (m.group(1) if m else '') or 'unknown'
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        self._fw = (time.time(), res)
        return res

    def allow_firewall(self):
        """Ask Windows (UAC prompt) to run exactly creator_hub.FIREWALL_CMD. -> (ok, message)."""
        try:
            r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                                elevate_command(creator_hub.FIREWALL_CMD)],
                               capture_output=True, text=True, errors='replace', timeout=600, creationflags=NOWIN)
        except subprocess.TimeoutExpired:
            return False, 'The Windows prompt was not answered in 10 minutes. Click the button again when ready.'
        except OSError as e:
            return False, f'Windows PowerShell could not be started ({e}).'
        r.stderr = r.stderr or ''
        if r.returncode != 0:
            if re.search(r'cancel', r.stderr, re.I):
                return False, 'You chose "No" on the Windows prompt. No problem: click the button again any time.'
            return False, 'Windows did not add the rule: ' + (r.stderr.strip().splitlines() or ['unknown error'])[-1]
        return True, 'done'

    def phone_seen(self):
        return creator_hub.phone_seen()

    def start_hub(self):
        args = [sys.executable, os.path.join(ROOT, 'creator_hub.py'), '--port', str(self.hub_port), '--phone']  # phone pairing
        p = subprocess.Popen(args, cwd=ROOT, creationflags=DETACH | NOWIN, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        return p.pid

    # ---- recording ----
    def obs_online(self):
        if not obs_bridge.obs_running():
            return False
        try:
            with obs_bridge.ObsWS(timeout=2.0) as ws:
                ws.call('GetVersion')
            return True
        except Exception:  # noqa: BLE001
            return False

    def obs_start(self):
        with obs_bridge.ObsWS(timeout=4.0) as ws:
            ws.call('StartRecord')

    def obs_stop(self):
        with obs_bridge.ObsWS(timeout=8.0) as ws:
            return ws.call('StopRecord').get('outputPath')

    # ---- YouTube ----
    def oauth(self):
        """publishers' own OAuth flow (Desktop app client, the user's browser). Writes publishers.YT_TOKEN."""
        import publishers
        from google_auth_oauthlib.flow import InstalledAppFlow
        creds = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, publishers.SCOPES).run_local_server(
            port=0, timeout_seconds=600,
            success_message='Stark World Engine is connected to YouTube. You can close this tab and go back to setup.')
        if not creds:
            raise RuntimeError('the sign-in did not finish (closed or timed out)')
        os.makedirs(os.path.dirname(publishers.YT_TOKEN), exist_ok=True)
        with open(publishers.YT_TOKEN, 'w', encoding='utf-8') as f:
            f.write(creds.to_json())
        publishers.restrict_to_user(publishers.YT_TOKEN)
        return True

    def yt_connected(self):
        import publishers
        return os.path.isfile(publishers.YT_TOKEN)

    def open_studio(self):
        subprocess.Popen([sys.executable, os.path.join(ROOT, 'studio_app.py')], cwd=ROOT, creationflags=NEWCON)


class MockEnv(RealEnv):
    """--mock: no real camera, mic, OBS, firewall, winget or Google. ffmpeg still runs for real (on synthetic
    lavfi sources), so the snapshot / level meter / capture / auto-edit pipeline is exercised end to end."""
    mock = True

    def __init__(self, hub_port=18510, obs_root=None, state_path=None):
        super().__init__(hub_port, obs_root or os.path.join(STATE, 'mock_obs'), state_path)
        self.missing = {t for t in os.environ.get('GS_WIZARD_MOCK_MISSING', '').split(',') if t}
        self.fw_rule = False
        self.yt = False
        self.events = []

    def _event(self, what, **kw):
        self.events.append(dict(kw, what=what, time=time.time()))
        update_state(lambda st: st.setdefault('mock_events', []).append(dict(kw, what=what)), self.state_path)

    def tools(self):
        t = super().tools()
        t['obs'] = {'ok': True, 'detail': r'C:\Program Files\obs-studio\bin\64bit\obs64.exe (demo)'}
        t['browser'] = {'ok': True, 'detail': 'Chrome (demo)'}
        t['winget'] = True
        for k in self.missing:
            if k in t:
                t[k] = {'ok': False, 'detail': 'not found (demo)'}
        return t

    def install(self, tool):
        self._event('install', tool=tool, package=WINGET[tool][0])
        threading.Timer(1.5, lambda: self.missing.discard(tool)).start()
        return {'started': True}

    def pip_google(self):
        self._event('pip', packages=PIP_GOOGLE)
        return {'started': True}

    def google_libs(self):
        return True

    def open_url(self, url):
        self._event('open_url', url=url)

    def devices(self):
        guid = '{33D9A762-90C8-11D0-BD43-00A0C911CE86}'
        return [
            {'name': 'Demo HD Webcam', 'kind': 'video',
             'alt': '@device_pnp_\\\\?\\usb#vid_046d&pid_085e&mi_00#7&1a2b3c4d&0&0000#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\\global'},
            {'name': 'OBS Virtual Camera', 'kind': 'video',
             'alt': '@device_sw_{860BB310-5D01-11D0-BD3B-00A0C911CE86}\\{A3FCE0F5-3493-419F-958A-ABA1250EC20B}'},
            {'name': 'Microphone (Demo USB Mic)', 'kind': 'audio',
             'alt': f'@device_cm_{guid}\\wave_{{04F53D9F-FF59-44DC-A73A-E038463436DA}}'},
            {'name': 'Headset Microphone (Demo Controller)', 'kind': 'audio',
             'alt': f'@device_cm_{guid}\\wave_{{673754DC-DC00-4F55-BCEC-A4C912C92071}}'},
        ]

    def video_input(self, name):
        return ['-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30']

    def audio_input(self, name):
        return ['-f', 'lavfi', '-i', 'aevalsrc=0.5*sin(2*PI*330*t)*abs(sin(2*PI*0.9*t)):s=48000']

    def av_input(self, cam, mic):
        return ['-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30', '-f', 'lavfi', '-i',
                'aevalsrc=0.4*sin(2*PI*330*t):s=48000']

    def write_obs(self, devs, camera, mic):
        return obs_bridge.write_all(self.obs_root, devs=devs, nvidia='', camera=camera, mic=mic,
                                    backups_dir=os.path.join(self.obs_root, '_backups'), room='stark-demo')

    def firewall(self, force=False):
        return {'rule': self.fw_rule, 'profile': 'Public'}

    def allow_firewall(self):
        # Record the exact elevated command that WOULD run; nothing is executed.
        self._event('elevate', powershell=elevate_command(creator_hub.FIREWALL_CMD),
                    command=creator_hub.FIREWALL_CMD)
        time.sleep(0.5)
        self.fw_rule = True
        return True, 'done'

    def start_hub(self):
        args = [sys.executable, os.path.join(ROOT, 'creator_hub.py'), '--port', str(self.hub_port),
                '--no-scheduler', '--no-publishers']
        p = subprocess.Popen(args, cwd=ROOT, creationflags=NOWIN, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._event('start_hub', pid=p.pid)
        return p.pid

    def obs_online(self):
        return False

    def oauth(self):
        if not os.path.isfile(CLIENT_SECRETS):
            raise RuntimeError('client_secrets.json is missing')
        self._event('oauth')
        time.sleep(0.5)
        self.yt = True
        return True

    def yt_connected(self):
        return self.yt

    def open_studio(self):
        self._event('open_studio')


# =====================================================================================================
# the wizard (logic behind each API call)
# =====================================================================================================
class Wizard:
    def __init__(self, env, token, state_path=None):
        self.env, self.token, self.state_path = env, token, state_path
        self.jobs, self.jobs_lock = {}, threading.Lock()
        self.work = tempfile.mkdtemp(prefix='stark_wizard_')
        self.devs_cache = None
        self.rec = {}
        self.login_tok = (None, 0)

    # ---- jobs (long tasks run in threads; the page polls) ----
    def start_job(self, kind, fn):
        with self.jobs_lock:
            cur = self.jobs.get(kind)
            if cur and cur['status'] == 'running':
                return cur
            job = {'id': kind, 'status': 'running', 'msg': 'Starting...', 'result': None, 'started': time.time()}
            self.jobs[kind] = job

        def run():
            try:
                job['result'] = fn(lambda msg: job.__setitem__('msg', msg))
                job['status'] = 'done'
            except Exception as e:  # noqa: BLE001
                log.exception('job %s failed', kind)
                job['status'], job['msg'] = 'error', str(e)
        threading.Thread(target=run, daemon=True).start()
        return job

    def job(self, kind):
        j = self.jobs.get(kind)
        return {k: v for k, v in j.items()} if j else {'id': kind, 'status': 'none'}

    # ---- state ----
    def state(self):
        st = load_state(self.state_path)
        return {'state': st, 'current': current_step(st), 'steps': STEPS, 'mock': self.env.mock}

    def set_step(self, step, how):
        if step not in STEPS or how not in ('done', 'skipped', 'reset'):
            raise ValueError('unknown step')
        if how == 'reset':
            update_state(lambda st: (st['done'].pop(step, None), st['skipped'].pop(step, None)), self.state_path)
        else:
            mark(step, how, self.state_path)
        return self.state()

    # ---- step 2: tools ----
    def tools(self):
        t = self.env.tools()
        t['ready'] = t['python']['ok'] and t['ffmpeg']['ok']
        if t['ready'] and t['obs']['ok'] and t['browser']['ok']:
            update_state(lambda st: st.__setitem__('tools_ok', True), self.state_path)
        return t

    def install(self, tool):
        if tool not in WINGET:
            raise ValueError('unknown tool')
        if not self.env.tools()['winget']:
            return {'started': False, 'link': LINKS[tool]}
        return self.env.install(tool)

    # ---- step 3: camera + mic ----
    def devices(self, refresh=False):
        if refresh or self.devs_cache is None:
            self.devs_cache = self.env.devices()
        devs = self.devs_cache
        vids = sorted([d['name'] for d in devs if d['kind'] == 'video'], key=lambda n: 'virtual' in n.lower())
        auds = [d['name'] for d in devs if d['kind'] == 'audio']
        cam, _how = obs_bridge.pick_camera(devs)
        _mic_id, mic_label = obs_bridge.pick_mic(devs)
        ch = load_state(self.state_path)['choices']
        return {'cameras': vids, 'mics': auds,
                'camera': ch.get('camera') if ch.get('camera') in vids else (cam['name'] if cam else (vids[0] if vids else '')),
                'mic': ch.get('mic') if ch.get('mic') in auds else (mic_label if mic_label in auds else (auds[0] if auds else '')),
                'ffmpeg': bool(self.env.ffmpeg()[0])}

    def _known(self, name, kind):
        devs = self.devs_cache if self.devs_cache is not None else self.devices() and self.devs_cache
        if not obs_bridge.find_device(devs, name, kind):
            raise ValueError(f'that {"camera" if kind == "video" else "microphone"} is not in the list; click Refresh')

    def snapshot(self, camera):
        self._known(camera, 'video')
        ff = self.env.ffmpeg()[0]
        cmd = ([ff, '-hide_banner', '-loglevel', 'error'] + self.env.video_input(camera)
               + ['-ss', '0.7', '-frames:v', '1', '-vf', "scale='min(960,iw)':-2", '-f', 'image2pipe', '-c:v', 'mjpeg',
                  '-q:v', '4', '-'])
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=25, creationflags=NOWIN)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'msg': 'The camera did not answer in time. Is it switched on and plugged in?'}
        if r.returncode != 0 or not r.stdout:
            err = r.stderr.decode('utf-8', 'replace')
            busy = re.search(r'busy|in use|Could not run graph|I/O error', err, re.I)
            return {'ok': False, 'msg': ('The camera seems busy (OBS or a video call may be using it). Close that app '
                                          'for a moment and try again, or just continue: OBS will still get it.')
                    if busy else 'Could not grab a picture from this camera. Try another one from the list.'}
        return {'ok': True, 'img': 'data:image/jpeg;base64,' + base64.b64encode(r.stdout).decode('ascii')}

    def mic_test(self, mic, seconds=3):
        self._known(mic, 'audio')
        ff = self.env.ffmpeg()[0]
        cmd = ([ff, '-hide_banner', '-nostats'] + self.env.audio_input(mic)
               + ['-t', str(seconds), '-af', 'astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level',
                  '-f', 'null', '-'])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                               timeout=seconds + 20, creationflags=NOWIN)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'levels': [], 'peak_db': None, 'msg': 'The microphone did not answer in time.'}
        levels, peak = parse_levels(r.stderr + r.stdout)
        if not levels:
            return {'ok': False, 'levels': [], 'peak_db': None,
                    'msg': 'Could not listen to this microphone. Is it plugged in? Try another one from the list.'}
        heard = peak > -50
        return {'ok': heard, 'levels': levels, 'peak_db': peak,
                'msg': 'We hear you loud and clear!' if heard else
                'Very quiet. Speak up, move closer, or check the mute switch on the mic, then test again.'}

    def save_devices(self, camera, mic):
        devs = self.devs_cache if self.devs_cache is not None else self.env.devices()
        if camera:
            self._known(camera, 'video')
        if mic:
            self._known(mic, 'audio')
        update_state(lambda st: st['choices'].update({'camera': camera or '', 'mic': mic or ''}), self.state_path)
        try:
            merge_config_keys({'camera_device': camera or '', 'mic_device': mic or ''})
        except ValueError as e:
            log.warning('config merge skipped: %s', e)
        rep = self.env.write_obs(devs, camera or None, mic or None)
        update_state(lambda st: st.__setitem__('obs_report', {k: rep.get(k) for k in (
            'camera', 'camera_source', 'mic', 'encoder', 'rec_path', 'obs_running')}), self.state_path)
        mark('devices', 'done', self.state_path)
        return {'ok': True, 'camera_source': rep.get('camera_source'), 'mic': rep.get('mic'),
                'encoder': rep.get('encoder'), 'obs_running': rep.get('obs_running'),
                'rec_path': rep.get('rec_path')}

    # ---- step 4: phone ----
    def phone(self):
        cfg = ensure_hub_keys()
        port = self.env.hub_port
        tok, exp = self.login_tok
        if not tok or exp - time.time() < 90 or not creator_hub.login_token_valid(tok):
            tok = creator_hub.mint_login_token(creator_hub.LOGIN_TTL)     # one-time QR login; the PIN is never in a URL
            self.login_tok = (tok, time.time() + creator_hub.LOGIN_TTL)
        url = creator_hub.hub_url(cfg, port=port, token=tok)
        svg, _m = creator_hub.qr_svg(url)
        st = load_state(self.state_path)
        seen = self.env.phone_seen()
        if seen and 'phone' not in st['done']:
            mark('phone', 'done', self.state_path)
        fw = self.env.firewall()
        return {'url': url, 'plain_url': creator_hub.hub_url(cfg, port=port), 'pin': str(cfg['hub_pin']),
                'ip': lan_ip(cfg), 'port': port, 'qr': svg, 'trust_note': creator_hub.TRUST_NOTE,
                'hub_running': port_open('127.0.0.1', port), 'seen': seen, 'firewall': fw,
                'firewall_cmd': creator_hub.FIREWALL_CMD, 'port_matches_rule': port == creator_hub.PORT}

    def start_hub(self):
        port = self.env.hub_port
        if port_open('127.0.0.1', port):
            return {'ok': True, 'msg': 'already running'}
        pid = self.env.start_hub()
        update_state(lambda st: st.__setitem__('hub_pid', pid), self.state_path)
        for _ in range(40):
            if port_open('127.0.0.1', port):
                return {'ok': True, 'pid': pid}
            time.sleep(0.25)
        return {'ok': False, 'msg': 'The phone hub did not start. See .claude/hub.log.'}

    def allow_firewall(self):
        def run(say):
            say('Waiting for you to click "Yes" on the Windows prompt...')
            ok, msg = self.env.allow_firewall()
            fw = self.env.firewall(force=True)
            if ok and fw['rule']:
                update_state(lambda st: st.__setitem__('firewall_rule', True), self.state_path)
                return {'ok': True, 'msg': 'Allowed! Your phone can reach this PC on your home network now.',
                        'firewall': fw}
            return {'ok': False, 'msg': msg if not ok else 'The rule did not show up. Try once more.', 'firewall': fw}
        return self.start_job('firewall', run)

    # ---- step 5: test recording ----
    def record_start(self, mode):
        ch = load_state(self.state_path)['choices']
        if mode == 'obs':
            if not self.env.obs_online():
                return {'ok': False, 'msg': 'OBS is not running (or its remote control is off). Use the quick test instead.'}
            self.env.obs_start()
            self.rec = {'mode': 'obs', 'started': time.time()}
            return {'ok': True, 'mode': 'obs'}
        cam, mic = ch.get('camera') or '', ch.get('mic') or ''

        def run(say):
            ff, probe = self.env.ffmpeg()
            if not ff or not probe:
                raise RuntimeError('FFmpeg is not installed yet: finish the "Tools" step first, then try again.')
            raw = os.path.join(self.work, 'raw')
            os.makedirs(raw, exist_ok=True)
            clip = os.path.join(raw, f'wizard_test_{int(time.time())}.mp4')
            say('Recording 5 seconds... wave and say hi!')
            enc = ['-t', '5', '-vf', "scale='min(1920,iw)':-2,fps=30", '-c:v', 'libx264', '-preset', 'veryfast',
                   '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-shortest', clip]
            if not cam and not self.env.mock:
                raise RuntimeError('Pick a camera in the "Camera + mic" step first.')
            tries = [self.env.av_input(cam, mic)]
            if mic and not self.env.mock:
                tries.append(self.env.av_input(cam, ''))   # some cameras refuse a combined graph
            err = ''
            for inp in tries:
                r = subprocess.run([ff, '-y', '-hide_banner', '-loglevel', 'error'] + inp + enc, capture_output=True,
                                   text=True, encoding='utf-8', errors='replace', timeout=90, creationflags=NOWIN)
                if r.returncode == 0 and os.path.isfile(clip):
                    break
                err = r.stderr[-400:]
            else:
                raise RuntimeError('Could not record from the camera (is OBS or another app using it?). ' + err)
            return self._edit(clip, raw, say)
        self.rec = {'mode': 'ffmpeg', 'started': time.time()}
        return {'ok': True, 'mode': 'ffmpeg', 'job': self.start_job('record', run)}

    def record_stop(self):
        if self.rec.get('mode') != 'obs':
            return {'ok': False, 'msg': 'No OBS test recording is running.'}

        def run(say):
            say('Stopping OBS...')
            out = self.env.obs_stop()
            if not out:
                raise RuntimeError('OBS did not report where it saved the recording.')
            say('Waiting for OBS to finish the file...')
            mp4 = os.path.splitext(out)[0] + '.mp4'
            last, stable = -1, 0
            for _ in range(120):
                src = mp4 if os.path.isfile(mp4) else out
                size = os.path.getsize(src) if os.path.isfile(src) else -1
                stable = stable + 1 if size == last and size > 0 else 0
                last = size
                if stable >= 3:
                    break
                time.sleep(0.5)
            raw = os.path.join(self.work, 'raw')
            os.makedirs(raw, exist_ok=True)
            clip = os.path.join(raw, os.path.basename(src))
            shutil.copy2(src, clip)        # the original stays in raw_clips; the wizard edits a temp copy
            return self._edit(clip, raw, say)
        self.rec = {}
        return {'ok': True, 'job': self.start_job('record', run)}

    def _edit(self, clip, raw, say):
        import auto_editor
        ff, probe = self.env.ffmpeg()
        cfg = load_config()
        for k, v in auto_editor.EDITOR_DEFAULTS.items():
            cfg.setdefault(k, v)
        say('Picking the fastest video encoder on this PC...')
        enc = auto_editor.probe_encoder(ff)
        say('Auto-editing: cutting pauses, grading colour, adding captions and making phone clips...')
        edits = os.path.join(self.work, 'edits')
        session = 'first_clip_' + datetime.datetime.now().strftime('%H%M%S')
        out_dir, man = auto_editor.edit_session([clip], ff, probe, enc, cfg, raw=raw, edits=edits, session=session)
        final = os.path.join(out_dir, 'FINAL.mp4')
        update_state(lambda st: st.__setitem__('first_clip', {'final': final, 'session': session,
                                                               'final_s': man.get('final_s'),
                                                               'grade': man.get('grade'),
                                                               'captions': man.get('captions')}), self.state_path)
        mark('record', 'done', self.state_path)
        return {'ok': True, 'video': '/media/first_clip.mp4?s=' + session, 'final_s': man.get('final_s'),
                'grade': man.get('grade'), 'clips': len(man.get('social_clips', [])), 'encoder': enc}

    def first_clip_path(self):
        fc = load_state(self.state_path).get('first_clip') or {}
        p = fc.get('final')
        if p and os.path.isfile(p) and os.path.realpath(p).startswith(os.path.realpath(tempfile.gettempdir())):
            return p
        return None

    # ---- step 6: YouTube ----
    def youtube(self):
        ok_file = False
        msg = ''
        if os.path.isfile(CLIENT_SECRETS):
            try:
                with open(CLIENT_SECRETS, encoding='utf-8-sig') as f:
                    ok_file, msg, _ = check_client_secrets(f.read())
            except OSError as e:
                msg = str(e)
        return {'secrets': ok_file, 'secrets_msg': msg, 'libs': self.env.google_libs(),
                'connected': self.env.yt_connected(), 'job': self.job('oauth')}

    def save_secrets(self, text, replace=False):
        ok, msg, _data = check_client_secrets(text)
        if not ok:
            return {'ok': False, 'msg': msg}
        if os.path.isfile(CLIENT_SECRETS):
            with open(CLIENT_SECRETS, encoding='utf-8-sig') as f:
                old = f.read()
            if old.strip() == text.strip():
                return {'ok': True, 'msg': 'That file is already saved. All good.'}
            if not replace:
                return {'ok': False, 'exists': True,
                        'msg': 'A client_secrets.json is already saved. Replace it? (The old one is backed up.)'}
            bdir = os.path.join(STATE, 'client_secrets_backups')
            os.makedirs(bdir, exist_ok=True)
            shutil.copy2(CLIENT_SECRETS, os.path.join(bdir, datetime.datetime.now().strftime('client_secrets_%Y%m%d_%H%M%S.json')))
        tmp = CLIENT_SECRETS + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp, CLIENT_SECRETS)
        if not self.env.mock:
            restrict_to_user(CLIENT_SECRETS)
        return {'ok': True, 'msg': msg + ' Saved.'}

    def connect_youtube(self):
        if not os.path.isfile(CLIENT_SECRETS):
            return {'status': 'error', 'msg': 'Add client_secrets.json first.'}
        if not self.env.google_libs():
            return {'status': 'error', 'msg': 'The YouTube helper is not installed yet: click "Install YouTube helper".'}

        def run(say):
            say('A Google sign-in page opened in your browser. Pick your channel account and click Allow...')
            self.env.oauth()
            mark('youtube', 'done', self.state_path)
            return {'ok': True}
        return self.start_job('oauth', run)


# =====================================================================================================
# HTTP
# =====================================================================================================
class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class Handler(http.server.BaseHTTPRequestHandler):
    wiz = None
    server_version = 'StarkSetup'
    timeout = 20                               # idle / slow sockets are dropped instead of pinning a thread

    def log_message(self, fmt, *a):
        pass

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

    def _guard(self, u, q):
        """Host must be this machine (blocks DNS rebinding) and the per-run token must match."""
        port = self.server.server_address[1]
        if self.headers.get('Host', '') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            self._send(403, {'error': 'wrong host'})
            return False
        tok = self.wiz.token
        given = q.get('t', [None])[0]
        if given is not None and hmac.compare_digest(str(given).encode(), tok.encode()) and self.command == 'GET':
            self._send(302, b'', 'text/plain', {'Location': u.path,
                                                'Set-Cookie': f'gs_wiz={tok}; HttpOnly; SameSite=Strict; Path=/'})
            return False
        cookies = dict(c.strip().split('=', 1) for c in (self.headers.get('Cookie') or '').split(';') if '=' in c)
        if hmac.compare_digest(cookies.get('gs_wiz', '').encode(), tok.encode()):
            return True
        if u.path.startswith('/api/'):
            self._send(401, {'error': 'Open the setup page from the address shown in the setup window.'})
        else:
            self._send(401, EXPIRED_HTML, 'text/html; charset=utf-8')
        return False

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if not self._guard(u, q):
            return
        w = self.wiz
        try:
            if u.path == '/':
                return self._send(200, PAGE_HTML, 'text/html; charset=utf-8')
            if u.path == '/api/state':
                return self._send(200, w.state())
            if u.path == '/api/tools':
                return self._send(200, w.tools())
            if u.path == '/api/devices':
                return self._send(200, w.devices(refresh='refresh' in q))
            if u.path == '/api/phone':
                return self._send(200, w.phone())
            if u.path == '/api/youtube':
                return self._send(200, w.youtube())
            if u.path == '/api/job':
                return self._send(200, w.job(q.get('id', [''])[0]))
            if u.path == '/media/first_clip.mp4':
                return self._file(w.first_clip_path())
            if u.path == '/help':
                return self._help()
            m = re.fullmatch(r'/docs/([A-Za-z_]+)', u.path)
            if m:
                return self._doc(m.group(1))
            if u.path.startswith('/docs/'):
                return self._page_error(404, 'There is no help page by that name. Open the Quick start from the '
                                             'setup page instead.')
            return self._send(404, {'error': 'not found'})
        except Exception as e:  # noqa: BLE001
            log.exception('GET %s', u.path)
            if not u.path.startswith('/api/'):
                return self._page_error(500, 'Something went wrong opening that page. Details are in '
                                             '.claude\\setup_wizard.log.')
            return self._send(500, {'error': str(e)})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not self._guard(u, {}):
            return
        if not (self.headers.get('Content-Type') or '').startswith('application/json'):
            return self._send(415, {'error': 'JSON only'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if n < 0:                              # rfile.read(-1) would wait for the client forever
            return self._send(400, {'error': 'bad Content-Length'})
        if n > 256 * 1024:
            return self._send(413, {'error': 'too big'})
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
            if not isinstance(body, dict):
                raise ValueError('JSON object expected')
        except ValueError:
            return self._send(400, {'error': 'bad JSON'})
        w = self.wiz
        try:
            p = u.path
            if p == '/api/step':
                return self._send(200, w.set_step(str(body.get('step')), str(body.get('how', 'done'))))
            if p == '/api/install':
                return self._send(200, w.install(str(body.get('tool'))))
            if p == '/api/snapshot':
                return self._send(200, w.snapshot(str(body.get('camera', ''))))
            if p == '/api/mictest':
                return self._send(200, w.mic_test(str(body.get('mic', ''))))
            if p == '/api/devices/save':
                return self._send(200, w.save_devices(str(body.get('camera', '')), str(body.get('mic', ''))))
            if p == '/api/hub/start':
                return self._send(200, w.start_hub())
            if p == '/api/firewall/allow':
                return self._send(200, w.allow_firewall())
            if p == '/api/record/start':
                return self._send(200, w.record_start(str(body.get('mode', 'ffmpeg'))))
            if p == '/api/record/stop':
                return self._send(200, w.record_stop())
            if p == '/api/youtube/secrets':
                return self._send(200, w.save_secrets(str(body.get('text', '')), bool(body.get('replace'))))
            if p == '/api/youtube/connect':
                return self._send(200, w.connect_youtube())
            if p == '/api/youtube/libs':
                return self._send(200, w.env.pip_google())
            if p == '/api/open':
                key = str(body.get('key'))
                if key not in LINKS:
                    return self._send(400, {'error': 'unknown link'})
                w.env.open_url(LINKS[key])
                return self._send(200, {'ok': True, 'url': LINKS[key]})
            if p == '/api/open/studio':
                w.env.open_studio()
                return self._send(200, {'ok': True})
            if p == '/api/open/hub':
                tok = creator_hub.mint_login_token(120)
                w.env.open_url(f'http://127.0.0.1:{w.env.hub_port}/?login={tok}')
                return self._send(200, {'ok': True})
            return self._send(404, {'error': 'not found'})
        except ValueError as e:
            return self._send(400, {'error': str(e)})
        except Exception as e:  # noqa: BLE001
            log.exception('POST %s', u.path)
            return self._send(500, {'error': str(e)})

    def _file(self, path):
        if not path:
            return self._send(404, {'error': 'no clip yet'})
        size = os.path.getsize(path)
        rng = re.match(r'bytes=(\d*)-(\d*)', self.headers.get('Range') or '')
        start, end = 0, size - 1
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            if start > end:
                return self._send(416, b'', 'text/plain', {'Content-Range': f'bytes */{size}'})
        with open(path, 'rb') as f:
            f.seek(start)
            data = f.read(end - start + 1)
        extra = {'Accept-Ranges': 'bytes'}
        if rng and (rng.group(1) or rng.group(2)):
            extra['Content-Range'] = f'bytes {start}-{end}/{size}'
            return self._send(206, data, 'video/mp4', extra)
        return self._send(200, data, 'video/mp4', extra)

    def _page_error(self, code, text):
        """A readable page (never raw JSON) for links the user opens in a browser tab."""
        body = DOC_HTML.replace('{{BODY}}', f'<h1>Sorry</h1><p>{html.escape(text)}</p>').replace('{{TITLE}}', 'Help')
        return self._send(code, body, 'text/html; charset=utf-8')

    def _help(self):
        """The offline help book: HELP.html at the top of a release zip (docs_product/help/index.html in the source
        tree). Sections are opened by the #fragment (quickstart, troubleshooting, ...). Without it: Markdown docs."""
        path = first_file(HELP_FILES)
        if not path:
            if os.path.isfile(os.path.join(DOCS, 'QUICKSTART.md')):
                return self._send(302, b'', 'text/plain', {'Location': '/docs/QUICKSTART'})
            return self._page_error(404, 'The help guides are not in this copy. Extract the Stark World Engine zip '
                                         'again into a new folder to get HELP.html back.')
        with open(path, 'rb') as f:
            return self._send(200, f.read(), 'text/html; charset=utf-8')

    def _doc(self, name):
        path = os.path.join(DOCS, name + '.md')
        if not os.path.isfile(path):
            if first_file(HELP_FILES):         # the help book has every guide: open the matching section
                return self._send(302, b'', 'text/plain', {'Location': '/help#' + name.lower().replace('_', '-')})
            return self._page_error(404, 'That help page is not in this copy. Open HELP.html in your Stark World Engine '
                                         'Studios folder, or extract the zip again to get the guides back.')
        with open(path, encoding='utf-8') as f:
            body = md_to_html(f.read())
        return self._send(200, DOC_HTML.replace('{{BODY}}', body).replace('{{TITLE}}', html.escape(name.title())),
                          'text/html; charset=utf-8')


def make_server(env, port=0, token=None, state_path=None):
    token = token or secrets.token_urlsafe(18)
    srv = Server(('127.0.0.1', port), type('H', (Handler,), {}))
    srv.RequestHandlerClass.wiz = Wizard(env, token, state_path)
    return srv, srv.RequestHandlerClass.wiz


# =====================================================================================================
# pages
# =====================================================================================================
EXPIRED_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Stark World Engine Setup</title>
<link rel="icon" href="data:,"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{margin:0;background:#0f1417;color:#eef3f1;font:18px system-ui,sans-serif;display:flex;justify-content:center;padding:20vh 16px}
</style></head><body><div><h2>This setup link is from an older run</h2><p>Double-click <b>SETUP_STARK_WORLD_ENGINE.bat</b> in your Stark World Engine
folder again: it opens a fresh page and remembers your progress.</p></div></body></html>"""

DOC_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{{TITLE}} - Stark World Engine help</title>
<link rel="icon" href="data:,"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#0f1417;--ink:#eef3f1;--mute:#9fb0aa;--acc:#5fd3b5;--card:#172024}
@media (prefers-color-scheme: light){:root{--bg:#f6f8f7;--ink:#14201c;--mute:#55665f;--acc:#0f8a6c;--card:#e9efec}}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 60px}a{color:var(--acc)}h1,h2,h3{line-height:1.25}
pre,code{background:var(--card);border-radius:6px}pre{padding:12px;overflow-x:auto}code{padding:1px 5px}
blockquote{margin:0;padding:8px 14px;border-left:4px solid var(--acc);background:var(--card);border-radius:0 8px 8px 0}
</style></head><body><main><p><a href="/">&larr; Back to setup</a></p>{{BODY}}</main></body></html>"""

PAGE_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Stark World Engine Setup</title>
<link rel="icon" href="data:,"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f1417;--panel:#151d21;--card:#1b252a;--line:#2a3940;--ink:#eef3f1;--mute:#9fb0aa;--acc:#5fd3b5;--acc-ink:#04241b;
--ok:#3ecf8e;--warn:#f5b84a;--bad:#ef6461;--glow:rgba(95,211,181,.18)}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--bg:#f4f7f6;--panel:#ffffff;--card:#eef3f1;--line:#d5dfdb;--ink:#14201c;
--mute:#56675f;--acc:#0f8a6c;--acc-ink:#ffffff;--ok:#18995e;--warn:#b7791f;--bad:#c53b38;--glow:rgba(15,138,108,.14)}}
*{box-sizing:border-box}html,body{margin:0}body{background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.app{display:grid;grid-template-columns:270px minmax(0,1fr);min-height:100vh}.app>*{min-width:0}
aside{background:var(--panel);border-right:1px solid var(--line);padding:22px 18px;position:sticky;top:0;height:100vh}
.brand{font-weight:800;font-size:19px;letter-spacing:.3px;margin:0 0 4px}.brand span{color:var(--acc)}
.sub{color:var(--mute);font-size:13px;margin:0 0 18px}
.bar{height:8px;border-radius:99px;background:var(--card);overflow:hidden;margin-bottom:18px}.bar i{display:block;height:100%;width:0;background:var(--acc);transition:width .6s}
ol.check{list-style:none;margin:0;padding:0}ol.check li{display:flex;align-items:center;gap:12px;padding:9px 10px;border-radius:10px;cursor:pointer;color:var(--mute)}
ol.check li:hover{background:var(--card)}ol.check li.cur{background:var(--card);color:var(--ink);font-weight:600}
.dot{width:26px;height:26px;border-radius:50%;border:2px solid var(--line);display:grid;place-items:center;flex:none;font-size:14px;transition:all .35s}
li.ok .dot{background:var(--ok);border-color:var(--ok);color:#fff;transform:scale(1.08)}li.ok{color:var(--ink)}
li.skip .dot{border-style:dashed}li.cur .dot{border-color:var(--acc);box-shadow:0 0 0 4px var(--glow)}
main{padding:34px 40px 80px;max-width:900px;width:100%}
h1{font-size:30px;line-height:1.2;margin:0 0 8px}h2{font-size:19px;margin:22px 0 8px}p{margin:8px 0}.lead{font-size:18px;color:var(--mute)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:14px 0}
.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.grow{flex:1;min-width:200px}
button,.btn{font:inherit;font-weight:600;border:0;border-radius:11px;padding:11px 18px;cursor:pointer;background:var(--acc);color:var(--acc-ink);text-decoration:none;display:inline-block}
button.sec,.btn.sec{background:transparent;color:var(--ink);border:1px solid var(--line)}button.big{font-size:18px;padding:14px 26px}
button:disabled{opacity:.45;cursor:default}button:focus-visible,select:focus-visible{outline:3px solid var(--acc);outline-offset:2px}
select{font:inherit;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px;width:100%}
.tool{display:flex;align-items:center;gap:14px;padding:12px 0;border-bottom:1px solid var(--line)}.tool:last-child{border:0}
.tool .ic{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;font-weight:800;flex:none;background:var(--panel);border:2px solid var(--line)}
.tool.ok .ic{background:var(--ok);border-color:var(--ok);color:#fff}.tool.bad .ic{border-color:var(--warn);color:var(--warn)}
.mute{color:var(--mute);font-size:14px}.small{font-size:13px}.msg{margin-top:10px;min-height:1.5em}.msg.ok{color:var(--ok)}.msg.bad{color:var(--bad)}.msg.warn{color:var(--warn)}
.ok-t{color:var(--ok);font-weight:700}.warn-t{color:var(--warn);font-weight:700}
.preview{width:100%;max-width:480px;aspect-ratio:16/9;background:#000;border-radius:12px;display:grid;place-items:center;color:#889;overflow:hidden}
.preview img{width:100%;height:100%;object-fit:cover}
.meter{display:flex;gap:3px;height:54px;align-items:flex-end;background:var(--panel);border-radius:10px;padding:6px;max-width:480px}
.meter i{flex:1;background:var(--line);border-radius:3px;height:6%;transition:height .08s}.meter i.on{background:var(--ok)}
.qrbox{display:flex;gap:22px;align-items:center;flex-wrap:wrap}.qr{background:#fff;padding:10px;border-radius:14px;width:240px;max-width:100%}.qr svg{width:100%;height:auto;display:block}
.pin{font-size:44px;font-weight:800;letter-spacing:8px;color:var(--acc);font-variant-numeric:tabular-nums}
.status{display:flex;align-items:center;gap:10px;font-weight:600}.pulse{width:12px;height:12px;border-radius:50%;background:var(--warn);animation:pulse 1.4s infinite}
.status.ok .pulse{background:var(--ok);animation:none}@keyframes pulse{50%{opacity:.25}}
.big-count{font-size:84px;font-weight:800;text-align:center;color:var(--acc)}
video{width:100%;max-width:640px;border-radius:12px;background:#000}
.steps{counter-reset:s;list-style:none;padding:0;margin:0}.steps>li{counter-increment:s;display:grid;grid-template-columns:44px 1fr;gap:12px;margin:14px 0;align-items:start}
.steps>li:before{content:counter(s);width:34px;height:34px;border-radius:50%;background:var(--acc);color:var(--acc-ink);display:grid;place-items:center;font-weight:800}
.shot{display:block;margin-top:8px;max-width:360px;width:100%;border-radius:10px;border:1px solid var(--line)}
.drop{border:2px dashed var(--line);border-radius:14px;padding:26px;text-align:center;color:var(--mute);transition:all .2s;cursor:pointer}
.drop.over{border-color:var(--acc);background:var(--glow);color:var(--ink)}
.have{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.have div{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.have b{display:block;margin-bottom:4px}
code{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:1px 6px;font-size:13px;word-break:break-all}
details summary{cursor:pointer;color:var(--mute)}
.nav{display:flex;gap:10px;justify-content:space-between;margin-top:26px;flex-wrap:wrap}
#confetti{position:fixed;inset:0;pointer-events:none;z-index:50}
.hidden{display:none!important}
@media (max-width:760px){.app{grid-template-columns:minmax(0,1fr)}aside{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line);padding:16px}
ol.check{display:flex;overflow-x:auto;gap:4px}ol.check li{flex:none;padding:6px 8px}ol.check li .lbl{display:none}ol.check li.cur .lbl{display:inline}
main{padding:20px 16px 60px}h1{font-size:25px}.pin{font-size:36px}}
@media (prefers-reduced-motion: reduce){*{transition:none!important;animation:none!important}}
</style></head><body>
<div class="app">
<aside><p class="brand">Stark World Engine <span>Studios</span></p><p class="sub">Creator suite setup <span id="mockTag" class="hidden">(demo mode)</span></p>
<div class="bar" aria-hidden="true"><i id="barFill"></i></div><p class="mute small" id="barText" aria-live="polite"></p>
<ol class="check" id="check"></ol></aside>
<main id="main" aria-live="polite"></main>
</div>
<canvas id="confetti"></canvas>
<script>
var LABELS={welcome:'Welcome',tools:'Check your tools',devices:'Camera + mic',phone:'Phone remote',record:'First test clip',youtube:'YouTube (optional)',done:'All set!'};
var S=null,CUR='welcome',TIMERS=[],DEV=null;
function $(i){return document.getElementById(i);}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return'&#'+c.charCodeAt(0)+';';});}
function api(p,b){var o={credentials:'same-origin'};if(b!==undefined){o.method='POST';o.headers={'Content-Type':'application/json'};o.body=JSON.stringify(b);}
 return fetch(p,o).then(function(r){return r.json().then(function(j){if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j;});});}
function clearTimers(){TIMERS.forEach(function(t){clearInterval(t);clearTimeout(t);});TIMERS=[];}
function every(ms,fn){fn();TIMERS.push(setInterval(fn,ms));}
function msg(id,text,kind){var e=$(id);if(!e)return;e.textContent=text||'';e.className='msg '+(kind||'');}
function isDone(s){return S&&S.state.done[s];}function isSkip(s){return S&&S.state.skipped[s];}
function drawCheck(){var n=0;$('check').innerHTML=S.steps.map(function(s,i){var ok=isDone(s),sk=isSkip(s);if(ok||sk)n++;
 return'<li data-s="'+s+'" class="'+(ok?'ok ':'')+(sk?'skip ':'')+(s===CUR?'cur':'')+'"><span class="dot">'+(ok?'&#10003;':(sk?'&ndash;':(i+1)))+'</span><span class="lbl">'+LABELS[s]+'</span></li>';}).join('');
 $('barFill').style.width=Math.round(100*n/S.steps.length)+'%';$('barText').textContent=n+' of '+S.steps.length+' steps done';
 Array.prototype.forEach.call($('check').children,function(li){li.onclick=function(){go(li.dataset.s);};});}
function load(){return api('/api/state').then(function(s){S=s;$('mockTag').classList.toggle('hidden',!s.mock);drawCheck();return s;});}
function step(s,how){return api('/api/step',{step:s,how:how||'done'}).then(function(st){S=st;drawCheck();});}
function next(){var i=S.steps.indexOf(CUR);go(S.steps[Math.min(i+1,S.steps.length-1)]);}
function finish(s,how){return step(s,how).then(next);}
function go(s){clearTimers();CUR=s;drawCheck();try{history.replaceState(null,'','#'+s);}catch(e){}var m=$('main');m.innerHTML='';VIEWS[s](m);window.scrollTo(0,0);var h=m.querySelector('h1');if(h){h.setAttribute('tabindex','-1');h.focus({preventScroll:true});}}
function navHtml(skipLabel){return'<div class="nav"><button class="sec" id="back">&larr; Back</button><span class="row">'+(skipLabel?'<button class="sec" id="skip">'+skipLabel+'</button>':'')+'<button id="nextBtn">Continue &rarr;</button></span></div>';}
function wireNav(s,canNext,onSkip){$('back').onclick=function(){var i=S.steps.indexOf(s);go(S.steps[Math.max(0,i-1)]);};
 var nb=$('nextBtn');nb.disabled=!canNext;nb.onclick=function(){finish(s,'done');};if($('skip'))$('skip').onclick=onSkip||function(){finish(s,'skipped');};}
var VIEWS={};

/* 1. welcome */
VIEWS.welcome=function(m){m.innerHTML='<h1>Hi! Let\'s get your studio ready.</h1><p class="lead">About 5 minutes, one step at a time. Everything stays on your own computer, and nothing changes without your click.</p>'+
 '<h2>What you\'ll have in 5 minutes</h2><div class="have"><div><b>Your camera + mic in OBS</b><span class="mute">A ready-made recording setup with the devices you pick.</span></div>'+
 '<div><b>A phone remote</b><span class="mute">Start/stop recording, teleprompter and approvals from your phone.</span></div>'+
 '<div><b>Your first auto-edited clip</b><span class="mute">Pauses cut, colour graded, captions and phone clips, automatically.</span></div>'+
 '<div><b>One-click YouTube</b><span class="mute">Optional: uploads go to your own channel after you approve them.</span></div></div>'+
 '<p class="mute small">You can stop any time; next time you open setup it picks up right where you left off.</p>'+
 '<div class="nav"><span></span><button class="big" id="go">Let\'s go &rarr;</button></div>';$('go').onclick=function(){finish('welcome');};};

/* 2. tools */
VIEWS.tools=function(m){m.innerHTML='<h1>Check your tools</h1><p class="lead">Stark World Engine uses a few free programs. Missing one? One click installs it in a window you can watch.</p>'+
 '<div class="card" id="toolList">Checking...</div><p class="msg" id="tmsg"></p>'+navHtml();
 var NAMES={python:['Python','Runs Stark World Engine.'],ffmpeg:['FFmpeg','Records the test clip and edits your videos.'],obs:['OBS Studio','Records your camera, screen and mic.'],browser:['Chrome or Edge','Shows this page and the studio.']};
 var installing={};
 function draw(t){$('toolList').innerHTML=['python','ffmpeg','obs','browser'].map(function(k){var x=t[k],btn='';
  if(!x.ok&&(k==='ffmpeg'||k==='obs'))btn=t.winget?'<button data-i="'+k+'" '+(installing[k]?'disabled':'')+'>'+(installing[k]?'Installing... watch the black window':'Install '+NAMES[k][0])+'</button> <button class="sec" data-l="'+k+'">Official download page</button>':'<button data-l="'+k+'">Get '+NAMES[k][0]+' (official page)</button>';
  if(!x.ok&&k==='browser')btn='<button data-l="chrome">Get Chrome (official page)</button>';
  if(!x.ok&&k==='python')btn='<button data-l="python">Get Python 3.10+ (official page)</button>';
  return'<div class="tool '+(x.ok?'ok':'bad')+'"><span class="ic">'+(x.ok?'&#10003;':'!')+'</span><div class="grow"><b>'+NAMES[k][0]+'</b> <span class="mute">'+NAMES[k][1]+'</span><div class="mute small">'+esc(x.ok?x.detail:'Not found yet')+'</div></div>'+btn+'</div>';}).join('');
  Array.prototype.forEach.call(document.querySelectorAll('[data-i]'),function(b){b.onclick=function(){installing[b.dataset.i]=true;b.disabled=true;
   api('/api/install',{tool:b.dataset.i}).then(function(r){if(r.started)msg('tmsg','A black window opened and is installing it. Watch it finish; this page notices by itself.','warn');else if(r.link)msg('tmsg','winget is not available on this PC, so the official download page opened instead.','warn');}).catch(function(e){msg('tmsg',e.message,'bad');});};});
  Array.prototype.forEach.call(document.querySelectorAll('[data-l]'),function(b){b.onclick=function(){api('/api/open',{key:b.dataset.l});};});
  var ready=t.ready;$('nextBtn').disabled=!ready;
  if(ready&&t.obs.ok&&t.browser.ok){msg('tmsg','Everything is here. Nice!','ok');}else if(ready){msg('tmsg',t.obs.ok?'Ready to continue.':'You can continue now; install OBS before your first real recording.','warn');}
  ['ffmpeg','obs'].forEach(function(k){if(t[k].ok)installing[k]=false;});}
 wireNav('tools',false);
 every(3000,function(){api('/api/tools').then(draw).catch(function(e){msg('tmsg',e.message,'bad');});});};

/* 3. camera + mic */
VIEWS.devices=function(m){m.innerHTML='<h1>Camera + mic</h1><p class="lead">Pick the camera and microphone you want to record with. Try them out right here.</p>'+
 '<div class="card"><label class="mute small" for="cam">Camera</label><div class="row"><div class="grow"><select id="cam"></select></div><button class="sec" id="snap">Show me</button><button class="sec" id="refresh" title="Look for devices again">Refresh</button></div>'+
 '<div class="preview" id="prev" style="margin-top:12px"><span>Click "Show me" for a live snapshot</span></div><p class="msg" id="cmsg"></p></div>'+
 '<div class="card"><label class="mute small" for="mic">Microphone</label><div class="row"><div class="grow"><select id="mic"></select></div><button class="sec" id="mtest">Test (3 seconds)</button></div>'+
 '<div class="meter" id="meter" style="margin-top:12px" aria-label="Microphone level"></div><p class="msg" id="mmsg"></p></div>'+
 '<div class="row"><button id="save" class="big">Use these</button><span class="msg" id="smsg"></span></div>'+navHtml('No camera? Skip');
 var meter=$('meter');for(var i=0;i<30;i++)meter.appendChild(document.createElement('i'));
 function fill(sel,list,val,empty){sel.innerHTML=list.length?list.map(function(n){return'<option'+(n===val?' selected':'')+'>'+esc(n)+'</option>';}).join(''):'<option value="">'+empty+'</option>';}
 function loadDevs(refresh){return api('/api/devices'+(refresh?'?refresh=1':'')).then(function(d){DEV=d;fill($('cam'),d.cameras,d.camera,'No camera found - plug one in and click Refresh');fill($('mic'),d.mics,d.mic,'No microphone found');
  if(!d.ffmpeg)msg('cmsg','FFmpeg is needed to see devices. Go back one step to install it.','bad');});}
 loadDevs(false);$('refresh').onclick=function(){loadDevs(true);};
 $('snap').onclick=function(){var b=this;b.disabled=true;$('prev').innerHTML='<span>Smile...</span>';msg('cmsg','');
  api('/api/snapshot',{camera:$('cam').value}).then(function(r){if(r.ok){$('prev').innerHTML='<img alt="Camera snapshot" src="'+r.img+'">';msg('cmsg','Looking good!','ok');}else{$('prev').innerHTML='<span>No picture</span>';msg('cmsg',r.msg,'warn');}}).catch(function(e){msg('cmsg',e.message,'bad');}).then(function(){b.disabled=false;});};
 $('mtest').onclick=function(){var b=this;b.disabled=true;msg('mmsg','Listening... say something!');var bars=meter.children,k=0,anim=setInterval(function(){k++;for(var j=0;j<bars.length;j++){bars[j].style.height=(6+Math.random()*10)+'%';}},120);TIMERS.push(anim);
  api('/api/mictest',{mic:$('mic').value}).then(function(r){clearInterval(anim);var i=0;var play=setInterval(function(){if(i>=r.levels.length){clearInterval(play);return;}var v=r.levels[i];bars[i].style.height=Math.max(6,v)+'%';bars[i].classList.toggle('on',v>15);i++;},60);TIMERS.push(play);
   msg('mmsg',r.msg+(r.peak_db!=null?' (loudest: '+r.peak_db+' dB)':''),r.ok?'ok':'warn');}).catch(function(e){clearInterval(anim);msg('mmsg',e.message,'bad');}).then(function(){b.disabled=false;});};
 $('save').onclick=function(){var b=this;b.disabled=true;msg('smsg','Setting up OBS...');
  api('/api/devices/save',{camera:$('cam').value,mic:$('mic').value}).then(function(r){msg('smsg','Saved! OBS now has "'+r.camera_source+'" and your mic.'+(r.obs_running?' Restart OBS once so it picks this up.':''),'ok');return load();}).then(function(){$('nextBtn').disabled=false;}).catch(function(e){msg('smsg',e.message,'bad');}).then(function(){b.disabled=false;});};
 wireNav('devices',!!isDone('devices'));};

/* 4. phone */
VIEWS.phone=function(m){m.innerHTML='<h1>Your phone remote</h1><p class="lead">Scan this with your phone camera (same Wi-Fi as this PC), then type the PIN if it asks.</p>'+
 '<div class="card qrbox"><div class="qr" id="qr" aria-label="QR code for the phone remote"></div><div><div class="mute small">PIN</div><div class="pin" id="pin">------</div><p class="mute small">The QR logs your phone in once. Or open this on your phone and type the PIN:<br><code id="url"></code></p><p class="mute small" id="trust"></p>'+
 '<div class="status" id="pstat"><span class="pulse"></span><span id="ptext">Waiting for your phone...</span></div></div></div>'+
 '<div class="card hidden" id="hubCard"><b>The phone remote is not running yet.</b><p class="mute">It runs quietly in the background on this PC.</p><button id="hubStart">Start it</button><p class="msg" id="hmsg"></p></div>'+
 '<div class="card" id="fwCard"><b>Phone says "can\'t connect"?</b><p>Windows may be blocking it. This button adds one rule that lets devices on your home network (not the internet) open the phone remote on port 8510. Windows will ask you to click "Yes".</p>'+
 '<div class="row"><button id="fwBtn">Allow on my home network</button><span class="mute small" id="fwState"></span></div><p class="msg" id="fmsg"></p>'+
 '<details><summary>What exactly runs?</summary><p class="mute small">Exactly this, as administrator (it does not change your network settings):</p><code id="fwCmd"></code></details></div>'+navHtml('I\'ll do this later');
 var fwRunning=false;
 var lastUrl='';
 function poll(){api('/api/phone').then(function(p){if(p.url!==lastUrl){$('qr').innerHTML=p.qr;lastUrl=p.url;}$('pin').textContent=p.pin;$('url').textContent=p.plain_url;$('trust').textContent=p.trust_note;$('fwCmd').textContent=p.firewall_cmd;
  $('hubCard').classList.toggle('hidden',p.hub_running);
  var ok=!!p.seen;$('pstat').classList.toggle('ok',ok);$('ptext').textContent=ok?'Your phone is connected! ('+p.seen.ip+')':(p.hub_running?'Waiting for your phone...':'Start the phone remote first');
  if(p.firewall.rule){$('fwState').innerHTML='<span class="ok-t">&#10003; Allowed on your home network</span>';$('fwBtn').disabled=true;}else if(!fwRunning){$('fwState').textContent='Network type: '+p.firewall.profile;$('fwBtn').disabled=false;}
  if(ok){$('nextBtn').disabled=false;if(!isDone('phone'))load();}}).catch(function(e){msg('fmsg',e.message,'bad');});}
 $('hubStart').onclick=function(){var b=this;b.disabled=true;msg('hmsg','Starting...');api('/api/hub/start',{}).then(function(r){msg('hmsg',r.ok?'Running!':r.msg,r.ok?'ok':'bad');poll();}).catch(function(e){msg('hmsg',e.message,'bad');}).then(function(){b.disabled=false;});};
 $('fwBtn').onclick=function(){var b=this;b.disabled=true;fwRunning=true;msg('fmsg','Look for the Windows prompt (it may blink in the taskbar) and click "Yes".','warn');
  api('/api/firewall/allow',{}).then(function(){var t=setInterval(function(){api('/api/job?id=firewall').then(function(j){if(j.status==='running')return;clearInterval(t);fwRunning=false;
   var r=j.result||{};msg('fmsg',j.status==='done'?r.msg:j.msg,j.status==='done'&&r.ok?'ok':'bad');poll();});},800);TIMERS.push(t);}).catch(function(e){fwRunning=false;b.disabled=false;msg('fmsg',e.message,'bad');});};
 wireNav('phone',!!isDone('phone'));
 api('/api/phone').then(function(p){if(!p.hub_running)return api('/api/hub/start',{});}).catch(function(){}).then(function(){every(2000,poll);});};

/* 5. test recording */
VIEWS.record=function(m){m.innerHTML='<h1>Your first test clip</h1><p class="lead">Record a few seconds and watch Stark World Engine edit it for you: pauses cut, colours graded, captions added.</p>'+
 '<div class="card" id="recCard"><div class="row"><button class="big" id="quick">Record a 5-second test</button><button class="sec hidden" id="obsBtn">Record with OBS instead</button></div><p class="mute small">The test clip is edited in a temporary folder; your recordings folder stays as it is.</p></div>'+
 '<div class="card hidden" id="busy"><div class="big-count" id="count"></div><p id="bmsg" class="msg"></p></div>'+
 '<div class="card hidden" id="result"><h2>Your first auto-edited clip!</h2><video id="vid" controls playsinline></video><p class="mute" id="rinfo"></p></div><p class="msg" id="rmsg"></p>'+navHtml('Skip for now');
 var obsMode=false;
 function watch(){$('busy').classList.remove('hidden');var t0=Date.now();var t=setInterval(function(){api('/api/job?id=record').then(function(j){var s=Math.round((Date.now()-t0)/1000);
   $('bmsg').textContent=(j.msg||'Working...')+(j.status==='running'?'  ('+(s>=60?Math.floor(s/60)+' min '+(s%60)+' s':s+' s')+' so far. The edit usually takes 1 to 3 minutes; slower PCs up to 5. Keep this page open.)':'');
   if(j.status==='running')return;clearInterval(t);$('count').textContent='';$('busy').classList.add('hidden');$('quick').disabled=false;
   if(j.status==='done'){show(j.result);load().then(function(){$('nextBtn').disabled=false;});}else{msg('rmsg',j.msg,'bad');}});},700);TIMERS.push(t);}
 function show(r){$('result').classList.remove('hidden');$('vid').src=r.video;$('rinfo').textContent=(r.final_s!=null?r.final_s+' seconds, ':'')+'look: '+(r.grade||'clean')+(r.clips?', plus '+r.clips+' phone-size clips':'')+'.';burst(60);}
 $('quick').onclick=function(){var b=this;b.disabled=true;msg('rmsg','');$('result').classList.add('hidden');
  if(obsMode){api('/api/record/stop',{}).then(function(r){obsMode=false;b.textContent='Record a 5-second test';if(r.ok)watch();else{msg('rmsg',r.msg,'bad');b.disabled=false;}});return;}
  api('/api/record/start',{mode:'ffmpeg'}).then(function(r){if(!r.ok){msg('rmsg',r.msg,'bad');b.disabled=false;return;}var n=5;$('busy').classList.remove('hidden');$('count').textContent=n;
   var c=setInterval(function(){n--;$('count').textContent=n>0?n:'';if(n<=0)clearInterval(c);},1000);TIMERS.push(c);watch();}).catch(function(e){msg('rmsg',e.message,'bad');b.disabled=false;});};
 $('obsBtn').onclick=function(){api('/api/record/start',{mode:'obs'}).then(function(r){if(!r.ok){msg('rmsg',r.msg,'warn');return;}obsMode=true;$('quick').textContent='Stop OBS recording';$('quick').disabled=false;$('obsBtn').classList.add('hidden');msg('rmsg','OBS is recording. Say hi, then click Stop.','warn');}).catch(function(e){msg('rmsg',e.message,'bad');});};
 api('/api/tools').then(function(t){if(t.obs.ok&&!S.mock)$('obsBtn').classList.remove('hidden');});
 if(S.state.first_clip){show({video:'/media/first_clip.mp4?s='+encodeURIComponent(S.state.first_clip.session),final_s:S.state.first_clip.final_s,grade:S.state.first_clip.grade});}
 wireNav('record',!!isDone('record'));};

/* 6. YouTube */
var SHOT=function(title,btn){return'<svg class="shot" viewBox="0 0 360 120" role="img" aria-label="'+esc(title+': click '+btn)+'"><rect width="360" height="120" rx="10" fill="#fff" stroke="#d5dfdb"/><rect width="360" height="26" rx="10" fill="#e8eef0"/><circle cx="14" cy="13" r="4" fill="#ef6461"/><circle cx="27" cy="13" r="4" fill="#f5b84a"/><circle cx="40" cy="13" r="4" fill="#3ecf8e"/><text x="58" y="17" font-size="11" fill="#55665f" font-family="system-ui">console.cloud.google.com</text><text x="18" y="54" font-size="14" font-weight="700" fill="#14201c" font-family="system-ui">'+esc(title)+'</text><rect x="18" y="70" width="'+(btn.length*8+28)+'" height="30" rx="6" fill="#1a73e8"/><text x="32" y="90" font-size="13" font-weight="700" fill="#fff" font-family="system-ui">'+esc(btn)+'</text><path d="M'+(btn.length*8+40)+' 104 l10 -14 l4 9 l9 -2 z" fill="#14201c"/></svg>';};
VIEWS.youtube=function(m){m.innerHTML='<h1>YouTube (optional)</h1><p class="lead">Want approved videos to upload to your channel by themselves? Google needs a free "key" that says the uploads come from you. It takes about 4 minutes, once.</p>'+
 '<ol class="steps"><li><div><b>Make a project.</b> Sign in with your YouTube Google account, type any name (for example "Stark World Engine"), click Create.<br><button class="sec" data-l="g_project">Open the page</button>'+SHOT('New Project','CREATE')+'</div></li>'+
 '<li><div><b>Turn on the YouTube API.</b> On the "YouTube Data API v3" page, click Enable.<br><button class="sec" data-l="g_api">Open the page</button>'+SHOT('YouTube Data API v3','ENABLE')+'</div></li>'+
 '<li><div><b>Name your app and switch it on for good.</b> Choose "External", type an app name (for example "Stark World Engine") and your e-mail, and save. Then click <b>Publish app</b> and confirm, so the status reads <b>In production</b>.<br><span class="small"><b>Why this matters:</b> if it stays on "Testing", Google stops the uploads after 7 days and you would have to connect again every week. "In production" is fine for your own channel: nobody else can use your app, and Google does not need to review it.</span><br><button class="sec" data-l="g_consent">Open the page</button>'+SHOT('OAuth consent screen','PUBLISH APP')+'</div></li>'+
 '<li><div><b>Make the key.</b> Click "Create credentials", then "OAuth client ID", choose <b>Desktop app</b>, click Create, then <b>Download JSON</b>.<br><button class="sec" data-l="g_creds">Open the page</button>'+SHOT('Create OAuth client ID: Desktop app','DOWNLOAD JSON')+'</div></li>'+
 '<li><div><b>Drop the downloaded file here.</b><div class="drop" id="drop" tabindex="0" role="button" aria-label="Choose client_secrets.json">Drag the file here, or click to choose it<br><span class="small">(it is called client_secret_....json, in your Downloads)</span></div><input type="file" id="file" accept=".json,application/json" class="hidden"><p class="msg" id="ymsg"></p></div></li>'+
 '<li><div><b>Connect.</b> A Google page opens: choose your channel account and click Allow. Google will warn that the app is not verified. That is expected, because it is your own app: click <b>Advanced</b>, then <b>Go to Stark World Engine (unsafe)</b>, then Allow.<div class="row" style="margin-top:8px"><button id="conn" disabled>Connect YouTube</button><button class="sec hidden" id="libs">Install YouTube helper</button></div><p class="msg" id="cmsg"></p></div></li></ol>'+navHtml('Skip YouTube');
 Array.prototype.forEach.call(document.querySelectorAll('[data-l]'),function(b){b.onclick=function(){api('/api/open',{key:b.dataset.l});};});
 var pending=null;
 function send(text,replace){api('/api/youtube/secrets',{text:text,replace:!!replace}).then(function(r){if(r.exists&&confirm(r.msg)){send(text,true);return;}msg('ymsg',r.msg,r.ok?'ok':'bad');refresh();}).catch(function(e){msg('ymsg',e.message,'bad');});}
 function readFile(f){if(!f)return;if(f.size>65536){msg('ymsg','That file is too big to be the Google key.','bad');return;}var rd=new FileReader();rd.onload=function(){send(String(rd.result));};rd.readAsText(f);}
 var d=$('drop');d.onclick=function(){$('file').click();};d.onkeydown=function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();$('file').click();}};$('file').onchange=function(){readFile(this.files[0]);};
 d.ondragover=function(e){e.preventDefault();d.classList.add('over');};d.ondragleave=function(){d.classList.remove('over');};d.ondrop=function(e){e.preventDefault();d.classList.remove('over');readFile(e.dataTransfer.files[0]);};
 function refresh(){return api('/api/youtube').then(function(y){$('conn').disabled=!y.secrets||y.job.status==='running';$('libs').classList.toggle('hidden',y.libs);
  if(y.secrets&&!$('ymsg').textContent)msg('ymsg','Key saved. Ready to connect.','ok');
  if(y.connected){msg('cmsg','Connected! Approved videos can now go to your channel.','ok');$('conn').textContent='Connected';$('conn').disabled=true;$('nextBtn').disabled=false;}
  else if(y.job.status==='running')msg('cmsg',y.job.msg,'warn');else if(y.job.status==='error')msg('cmsg','Not connected: '+y.job.msg,'bad');return y;});}
 $('conn').onclick=function(){$('conn').disabled=true;api('/api/youtube/connect',{}).then(function(j){if(j.status==='error'){msg('cmsg',j.msg,'bad');$('conn').disabled=false;return;}
  var t=setInterval(function(){refresh().then(function(y){if(y.job.status!=='running'){clearInterval(t);if(y.connected)load();}});},1000);TIMERS.push(t);}).catch(function(e){msg('cmsg',e.message,'bad');});};
 $('libs').onclick=function(){api('/api/youtube/libs',{}).then(function(r){if(r&&r.started===false){msg('cmsg',r.msg||'Could not start the install.','bad');return;}msg('cmsg','Installing in a black window. When it says done, click Connect.','warn');}).catch(function(e){msg('cmsg',e.message,'bad');});every(4000,refresh);};
 wireNav('youtube',!!isDone('youtube'));refresh();};

/* 7. done */
VIEWS.done=function(m){m.innerHTML='<h1>You\'re all set!</h1><p class="lead">Your studio is ready. Time to make something.</p>'+
 '<div class="have"><div><b>Make a game</b><span class="mute">Open the Stark World Engine Studio game builder.</span><br><br><button id="studio">Open Studio</button></div>'+
 '<div><b>Phone remote</b><span class="mute">Teleprompter, record button and approvals.</span><br><br><button class="sec" id="hub">Open on this PC</button></div>'+
 '<div><b>Help</b><span class="mute">Short guides, in plain words.</span><br><br><a class="btn sec" href="/help#quickstart" target="_blank" rel="noopener">Quick start</a> <a class="btn sec" href="/help#troubleshooting" target="_blank" rel="noopener">Troubleshooting</a></div></div>'+
 '<p class="mute small" id="summary"></p><p class="msg" id="dmsg"></p>';
 $('studio').onclick=function(){api('/api/open/studio',{}).then(function(){msg('dmsg','The studio is starting in a new window; your browser opens it in a moment.','ok');});};
 $('hub').onclick=function(){api('/api/open/hub',{});};
 var skipped=S.steps.filter(function(s){return isSkip(s);}).map(function(s){return LABELS[s];});
 $('summary').textContent=skipped.length?'Skipped for now: '+skipped.join(', ')+'. Click them on the left whenever you like.':'Every step done. Brilliant.';
 if(!isDone('done'))step('done','done');burst(220);};

/* confetti */
function burst(n){var c=$('confetti');if(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)return;var x=c.getContext('2d');if(!x)return;c.width=innerWidth;c.height=innerHeight;
 var cols=['#5fd3b5','#f5b84a','#ef6461','#7aa2ff','#c58bff','#3ecf8e'],P=[];for(var i=0;i<n;i++)P.push({x:c.width/2+(Math.random()-.5)*200,y:c.height*0.35,vx:(Math.random()-.5)*14,vy:-Math.random()*13-4,s:4+Math.random()*6,r:Math.random()*6,vr:(Math.random()-.5)*.4,c:cols[i%cols.length]});
 var t0=performance.now();(function f(t){var dt=Math.min(32,t-t0)/16;t0=t;x.clearRect(0,0,c.width,c.height);var alive=0;P.forEach(function(p){p.vy+=.35*dt;p.x+=p.vx*dt;p.y+=p.vy*dt;p.r+=p.vr*dt;if(p.y<c.height+20)alive++;x.save();x.translate(p.x,p.y);x.rotate(p.r);x.fillStyle=p.c;x.fillRect(-p.s/2,-p.s/4,p.s,p.s/2);x.restore();});if(alive)requestAnimationFrame(f);else x.clearRect(0,0,c.width,c.height);})(t0);}

load().then(function(s){var h=(location.hash||'').slice(1);go(s.steps.indexOf(h)>=0?h:s.current);}).catch(function(e){$('main').innerHTML='<h1>Setup could not start</h1><p>'+esc(e.message)+'</p>';});
</script></body></html>"""


# =====================================================================================================
# entry point
# =====================================================================================================
def pid_alive(pid):
    try:
        r = subprocess.run(['tasklist', '/FI', f'PID eq {int(pid)}', '/NH', '/FO', 'CSV'], capture_output=True,
                           text=True, errors='replace', timeout=10, creationflags=NOWIN)
        return f'"{int(pid)}"' in (r.stdout or '')        # whole CSV field: PID 12 must not match 1234
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def running_instance():
    """-> URL of a wizard that is already running (so a second double-click just re-opens it), or None."""
    try:
        with open(LOCK_FILE, encoding='utf-8') as f:
            lk = json.load(f)
        if pid_alive(lk['pid']) and port_open('127.0.0.1', int(lk['port'])):
            return f'http://127.0.0.1:{int(lk["port"])}/?t={lk["token"]}'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--port', type=int, default=0)
    ap.add_argument('--hub-port', type=int, default=None)
    ap.add_argument('--obs-root', default=None)
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--mock', action='store_true')
    ap.add_argument('--reset', action='store_true')
    a = ap.parse_args(argv)
    os.makedirs(STATE, exist_ok=True)
    if a.reset and os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        print('Setup progress cleared; starting fresh.')
    if not a.mock:
        url = running_instance()
        if url:
            print('\n  Stark World Engine setup is already open. Bringing it back in your browser:\n    ' + url + '\n')
            if not a.no_browser:
                webbrowser.open(url)
            return 0
    env_cls = MockEnv if a.mock else RealEnv
    hub_port = a.hub_port or (18510 if a.mock else creator_hub.PORT)
    env = env_cls(hub_port=hub_port, obs_root=a.obs_root)
    srv, wiz = make_server(env, a.port)
    port = srv.server_address[1]
    url = f'http://127.0.0.1:{port}/?t={wiz.token}'
    if not a.mock:
        with open(LOCK_FILE, 'w', encoding='utf-8') as f:
            json.dump({'pid': os.getpid(), 'port': port, 'token': wiz.token}, f)
    log.info('wizard on 127.0.0.1:%d (mock=%s, hub port %d)', port, a.mock, hub_port)
    print('\n  ============================================')
    print('     STARK WORLD ENGINE  -  setup')
    print('  ============================================\n')
    print('  Your setup page is opening in your browser.')
    print('  If it does not appear, copy this into the address bar:\n')
    print('    ' + url + '\n')
    print('  Keep this window open while you set up. Close it when you are done.\n', flush=True)
    if not a.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        if not a.mock:
            try:
                os.remove(LOCK_FILE)
            except OSError:
                pass
        shutil.rmtree(wiz.work, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
