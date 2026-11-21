"""Shared helpers for the six Stark World Engine v28 modules (studio_app, build_release, obs_bridge, auto_editor,
creator_hub, publishers).

Owner files: config.json, CUSTOMER_FEEDBACK.txt, raw_clips/ and client_secrets.json belong to the owner. They are
created only when missing and never overwritten. config.json only ever gains MISSING keys (merge_config_keys);
existing values are kept. No module here talks to a paid cloud API; the only AI hook is a local Ollama server.

Secrets (security review F-08): the hub PIN and the VDO.Ninja password can live outside the studio folder, in
%LOCALAPPDATA%/StarkPrivate/stark_world_engine/secrets_<install id>.json (`python gs_common.py --move-secrets`).
load_config() overlays them, merge_config_keys() never re-adds them to config.json once they are stored there.
"""
import glob, hashlib, json, logging, os, secrets, shutil, socket

ROOT = os.path.dirname(os.path.abspath(__file__))              # code (read-only on Steam)
DATA = os.path.abspath(os.environ.get('GS_DATA_DIR') or ROOT)    # user data (Steam: Documents\Stark World Engine)
DIST = os.path.join(ROOT, 'dist')
RAW = os.path.join(DATA, 'raw_clips')
EDITS = os.path.join(DATA, 'edits')
DRAFTS = os.path.join(DATA, 'drafts')
STATE = os.path.join(DATA, '.claude')
APPROVALS = os.path.join(STATE, 'approvals')
CONFIG = os.path.join(DATA, 'config.json')
FEEDBACK = os.path.join(DATA, 'CUSTOMER_FEEDBACK.txt')
CLIENT_SECRETS = os.path.join(DATA, 'client_secrets.json')
VERSION = '28.7.0'
EDITION = 'Holiday 2026 Edition'

DEFAULT_CONFIG = {
    "product_name": "Stark World Engine",
    "store_url": "https://your-store.example/stark-world-engine",
    "itch_url": "https://your-name.itch.io/stark-world-engine",
    "channel_name": "Your Channel",
    "support_email": "support@your-domain.example",
    "video_topic": "Building a cozy 3D world in one evening",
    "ffmpeg": "",
    "target_lufs": -14,
    "silence_db": -32,
    "silence_min_s": 0.22,
    "classroom_profile": False,      # True = student-safe: no publishing, YouTube, phone hub or network features
}

DEFAULT_FEEDBACK = """# CUSTOMER_FEEDBACK.txt - paste buyer messages here, one per block, separated by a blank line.
# Lines starting with # are ignored.
"""


def ensure_workspace():
    """Create config.json / CUSTOMER_FEEDBACK.txt / raw_clips/ ONLY if missing. -> list of what was created."""
    made = []
    os.makedirs(STATE, exist_ok=True)
    if not os.path.exists(CONFIG):
        with open(CONFIG, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        made.append('config.json')
    if not os.path.exists(FEEDBACK):
        with open(FEEDBACK, 'w', encoding='utf-8') as f:
            f.write(DEFAULT_FEEDBACK)
        made.append('CUSTOMER_FEEDBACK.txt')
    if not os.path.isdir(RAW):
        os.makedirs(RAW)
        made.append('raw_clips/')
    return made


SECRET_KEYS = ('hub_pin', 'vdo_password')


def private_dir():
    """Owner-only folder for secrets, outside every workspace (GS_PRIVATE_DIR overrides it, e.g. in tests)."""
    if os.environ.get('GS_PRIVATE_DIR'):
        return os.path.abspath(os.environ['GS_PRIVATE_DIR'])
    base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'StarkPrivate')


def secrets_path(path=CONFIG):
    """The private secrets file that belongs to the install whose config.json is `path` (one file per folder)."""
    where = os.path.normcase(os.path.abspath(os.path.dirname(path)))
    tag = hashlib.sha256(where.encode('utf-8')).hexdigest()[:16]
    new = os.path.join(private_dir(), 'stark_world_engine', f'secrets_{tag}.json')
    if not os.environ.get('GS_PRIVATE_DIR') and not os.path.exists(new):   # not migrated yet (doctor.py does it)
        old = os.path.join(os.path.dirname(private_dir()), 'GorgonPrivate', 'gorgon_studios', f'secrets_{tag}.json')
        if os.path.exists(old):
            return old
    return new


def load_secrets(path=CONFIG):
    """-> {key: value} for the SECRET_KEYS stored privately for this install ({} when none)."""
    try:
        with open(secrets_path(path), encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: str(data[k]) for k in SECRET_KEYS if isinstance(data, dict) and data.get(k) not in (None, '')}


def _write_json_atomic(dest, data):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, dest)


def move_secrets(path=CONFIG, rotate=False):
    """Move hub_pin / vdo_password out of config.json into the private folder (F-08). rotate=True makes NEW values
    (the old ones may have been seen). Every other config.json value is kept as it is. -> list of keys moved."""
    data = _read_config_file(path)
    if data is None:
        raise ValueError(f'{path} is missing or not valid JSON; nothing was changed')
    store = load_secrets(path)
    fresh = {'hub_pin': lambda: f'{secrets.randbelow(10 ** 6):06d}', 'vdo_password': lambda: secrets.token_urlsafe(16)}
    moved = []
    for k in SECRET_KEYS:
        if k not in data and k not in store:
            continue
        if rotate:
            store[k] = fresh[k]()
        elif k not in store:
            store[k] = str(data[k])
        moved.append(k)
    if not moved:
        return []
    _write_json_atomic(secrets_path(path), store)          # the private copy first: nothing is lost if we stop here
    left = {k: v for k, v in data.items() if k not in SECRET_KEYS}
    if left != data:
        _write_json_atomic(path, left)
    return moved


def _read_config_file(path=CONFIG):
    try:
        with open(path, encoding='utf-8-sig') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return None


def load_config(path=CONFIG):
    """config.json merged over the defaults (missing keys fall back; the file is not rewritten here)."""
    if path == CONFIG:
        ensure_workspace()
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_read_config_file(path) or {})
    cfg.update(load_secrets(path))         # private secrets (F-08) win over any copy left in config.json
    return cfg


def classroom_mode(path=CONFIG):
    """True when config.json has "classroom_profile": true (Stark Education Suite). Read-only; same rule as
    stark_classroom.is_classroom. The publishing helpers, YouTube upload and the phone hub refuse to run when on."""
    v = (_read_config_file(path) or {}).get('classroom_profile')
    return v is not False and (v.strip().lower() if isinstance(v, str) else v) in (True, 1, '1', 'true', 'yes', 'on', 'classroom', 'student')


def merge_config_keys(new_keys, path=CONFIG):
    """Add keys that are MISSING from config.json; never change an existing value. -> list of keys added.
    A one-time backup of the original file is kept in .claude/config_backups/ before the first merge."""
    data = _read_config_file(path)
    if data is None:
        if os.path.exists(path):           # unreadable JSON: refuse to touch the owner's file
            raise ValueError(f'{path} is not valid JSON; fix it by hand, nothing was changed')
        data = {}
    private = load_secrets(path)
    added = [k for k in new_keys if k not in data and k not in private]   # a privately stored secret is never re-added
    if not added:
        return []
    if os.path.exists(path):
        bdir = os.path.join(os.path.dirname(path), '.claude', 'config_backups')
        os.makedirs(bdir, exist_ok=True)
        first = os.path.join(bdir, 'config.original.json')
        if not os.path.exists(first):
            shutil.copy2(path, first)
    for k in added:
        data[k] = new_keys[k]
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    return added


def ensure_hub_keys(path=CONFIG):
    """PIN, VDO.Ninja room and the creator-suite keys: generated only when absent. -> merged config dict."""
    merge_config_keys({
        'hub_pin': f'{secrets.randbelow(10 ** 6):06d}',
        'vdo_room': 'stark' + secrets.token_hex(5),
        'tier': 'studio',
        'itch_target': '',
        'itch_api_key': '',
        'substack_url': '',
        'lan_ip': '',
    }, path)
    return load_config(path)


def find_ffmpeg(cfg=None):
    """-> (ffmpeg, ffprobe) paths or (None, None)."""
    cands = []
    if cfg and cfg.get('ffmpeg'):
        cands.append(cfg['ffmpeg'])
    w = shutil.which('ffmpeg')
    if w:
        cands.append(w)
    local = os.environ.get('LOCALAPPDATA', '')
    cands += sorted(glob.glob(os.path.join(local, 'Microsoft', 'WinGet', 'Packages', 'Gyan.FFmpeg*', '*', 'bin',
                                           'ffmpeg.exe')), reverse=True)
    for c in cands:
        if c and os.path.isfile(c):
            probe = os.path.join(os.path.dirname(c), 'ffprobe' + ('.exe' if c.lower().endswith('.exe') else ''))
            return c, (probe if os.path.isfile(probe) else shutil.which('ffprobe'))
    return None, None


def lan_ip(cfg=None):
    """The PC's LAN address (no packet is sent: a UDP connect only picks the route)."""
    if cfg and cfg.get('lan_ip'):
        return cfg['lan_ip']
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def get_logger(name, filename):
    """File logger under .claude/."""
    os.makedirs(STATE, exist_ok=True)
    log = logging.getLogger(name)
    if not log.handlers:
        h = logging.FileHandler(os.path.join(STATE, filename), encoding='utf-8')
        h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


if __name__ == '__main__':
    import sys
    if '--move-secrets' in sys.argv[1:]:
        keys = move_secrets(rotate='--rotate' in sys.argv[1:])
        print(('moved ' + ', '.join(keys) + (' (new values made)' if '--rotate' in sys.argv[1:] else '')
               + ' to the private folder ' + os.path.dirname(secrets_path())) if keys else 'nothing to move')
    else:
        print('created:', ensure_workspace() or 'nothing (all present)')
