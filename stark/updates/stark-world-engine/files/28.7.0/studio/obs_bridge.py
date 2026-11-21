"""obs_bridge.py: writes a NEW OBS profile "Stark_Profile" + scene collection "Stark_Canon_R50V", enables
obs-websocket v5 on port 4455, and carries a tiny dependency-free obs-websocket v5 client (ObsWS) for the hub.

  python obs_bridge.py                 write profile + collection + websocket settings (OBS may be closed)
  python obs_bridge.py --dry-run       show what would be written, change nothing
  python obs_bridge.py --obs-root DIR  write into another OBS config folder (tests)

Only the two new names are written. Anything touched (the new profile folder, the new collection file, the
websocket config.json) is copied to .claude/obs_backups/<time>/ first. Other profiles/collections are never altered.
"""
import argparse, base64, datetime, hashlib, json, os, re, secrets, shutil, socket, subprocess, sys, urllib.parse, uuid

from gs_common import RAW, STATE, ensure_hub_keys, find_ffmpeg, load_config

PROFILE = 'Stark_Profile'
COLLECTION = 'Stark_Canon_R50V'
SCENE = 'Stark World Engine Studio'
WS_PORT = 4455
CAM_RX = re.compile(r'canon|eos|r50', re.I)
CAPTURE_RX = re.compile(r'cam ?link|elgato|capture|hdmi|uvc|usb video', re.I)


def obs_root_default():
    return os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'obs-studio')


# ---------------- devices ----------------
def list_dshow_devices(ffmpeg=None):
    """-> [{'name', 'kind': 'video'|'audio', 'alt'}] from `ffmpeg -list_devices true -f dshow -i dummy`."""
    ff = ffmpeg or find_ffmpeg(load_config())[0]
    if not ff:
        return []
    try:       # a hung camera driver or a broken ffmpeg path means "no devices found", never a crash
        r = subprocess.run([ff, '-hide_banner', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_dshow_list((r.stderr or '') + (r.stdout or ''))


def parse_dshow_list(text):
    devs = []
    for line in text.splitlines():
        m = re.search(r'\]\s+"(.+)"\s+\((video|audio|none)\)\s*$', line)
        if m:
            devs.append({'name': m.group(1), 'kind': m.group(2), 'alt': ''})
            continue
        m = re.search(r'Alternative name\s+"(.+)"\s*$', line)
        if m and devs:
            devs[-1]['alt'] = m.group(1)
    return devs


def obs_encode(s):
    """win-dshow device-id escaping: '#' -> '#22' and ':' -> '#3A' (in that order)."""
    return s.replace('#', '#22').replace(':', '#3A')


def obs_video_device_id(dev):
    path = dev.get('alt', '')
    path = path[len('@device_pnp_'):] if path.startswith('@device_pnp_') else ''
    return obs_encode(dev['name']) + ':' + obs_encode(path)


def pick_camera(devs):
    """-> (device or None, how): 'canon' when a Canon/EOS/R50 device exists, 'capture' for an HDMI capture card the
    camera may be plugged into, 'missing' otherwise."""
    vids = [d for d in devs if d['kind'] == 'video' and 'virtual' not in d['name'].lower()]
    for d in vids:
        if CAM_RX.search(d['name']):
            return d, 'canon'
    for d in vids:
        if CAPTURE_RX.search(d['name']):
            return d, 'capture'
    return None, 'missing'


def _mic_score(d):
    n = d['name']
    return (bool(re.search(r'shure|mvx|rode|yeti|elgato wave', n, re.I)), 'microphone' in n.lower(),
            not re.search(r'virtual|headset|hdmi|controller|output', n, re.I))


def wasapi_id(dev):
    """dshow audio device -> WASAPI capture endpoint id (shares the wave_{GUID}), or None when unknown."""
    m = re.search(r'wave_(\{[0-9A-Fa-f-]{36}\})', (dev or {}).get('alt', ''))
    return '{0.0.1.00000000}.' + m.group(1).lower() if m else None


def find_device(devs, name, kind):
    """The device called `name` (exact, then case-insensitive) of the given kind, or None."""
    same = [d for d in devs if d['kind'] == kind]
    return next((d for d in same if d['name'] == name), None) or         next((d for d in same if d['name'].lower() == str(name or '').lower()), None)


def pick_mic(devs):
    """-> (wasapi device_id, label). WASAPI endpoint ids share the GUID of the dshow wave_{GUID} name."""
    auds = [d for d in devs if d['kind'] == 'audio']
    for d in sorted(auds, key=_mic_score, reverse=True):
        s = _mic_score(d)
        m = re.search(r'wave_(\{[0-9A-Fa-f-]{36}\})', d.get('alt', ''))
        if m and s[1] and s[2]:
            return '{0.0.1.00000000}.' + m.group(1).lower(), d['name']
    return 'default', 'Default microphone'


def has_nvidia():
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], capture_output=True,
                           text=True, errors='replace', timeout=15,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if r.returncode == 0 and 'nvidia' in (r.stdout or '').lower():
            return r.stdout.strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', '(Get-CimInstance Win32_VideoController).Name'],
                           capture_output=True, text=True, errors='replace', timeout=30,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for line in (r.stdout or '').splitlines():
            if 'nvidia' in line.lower():
                return line.strip()
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return ''


# ---------------- profile ----------------
def profile_ini(encoder, rec_path):
    simple = 'nvenc' if encoder == 'jim_nvenc' else 'x264'
    return f"""[General]
Name={PROFILE}

[Output]
Mode=Advanced
FilenameFormatting=Stark World Engine %CCYY-%MM-%DD %hh-%mm-%ss

[SimpleOutput]
FilePath={rec_path}
RecFormat2=mkv
RecQuality=Small
RecEncoder={simple}
StreamEncoder={simple}

[AdvOut]
RecType=Standard
RecFilePath={rec_path}
RecFormat2=mkv
RecEncoder={encoder}
Encoder={encoder}
RecTracks=1
TrackIndex=1
RecAudioEncoder=ffmpeg_aac
AudioEncoder=ffmpeg_aac
RecUseRescale=false

[Video]
BaseCX=3840
BaseCY=1080
OutputCX=3840
OutputCY=1080
FPSType=1
FPSInt=30
FPSNum=30
FPSDen=1
FPSCommon=30
ScaleType=bicubic
ColorFormat=NV12
ColorSpace=709
ColorRange=Partial
AutoRemux=true

[Audio]
SampleRate=48000
ChannelSetup=Stereo
"""


def encoder_json(encoder):
    if encoder == 'jim_nvenc':
        return {'rate_control': 'CQP', 'cqp': 18, 'preset2': 'p5', 'profile': 'high', 'keyint_sec': 2}
    return {'rate_control': 'CRF', 'crf': 18, 'preset': 'veryfast', 'profile': 'high', 'keyint_sec': 2}


# ---------------- scene collection ----------------
def _source(name, sid, settings, **extra):
    s = {'name': name, 'uuid': str(uuid.uuid4()), 'id': sid, 'versioned_id': sid, 'settings': settings,
         'mixers': 0, 'sync': 0, 'flags': 0, 'volume': 1.0, 'balance': 0.5, 'enabled': True, 'muted': False,
         'push-to-mute': False, 'push-to-mute-delay': 0, 'push-to-talk': False, 'push-to-talk-delay': 0,
         'hotkeys': {}, 'deinterlace_mode': 0, 'deinterlace_field_order': 0, 'monitoring_type': 0,
         'private_settings': {}, 'filters': []}
    s.update(extra)
    return s


def _item(src, iid, x, y, bw, bh):
    return {'name': src['name'], 'source_uuid': src['uuid'], 'visible': True, 'locked': False, 'rot': 0.0,
            'align': 5, 'bounds_type': 2 if bw else 0, 'bounds_align': 0, 'bounds_crop': False,
            'crop_left': 0, 'crop_top': 0, 'crop_right': 0, 'crop_bottom': 0, 'id': iid, 'group_item_backup': False,
            'pos': {'x': float(x), 'y': float(y)}, 'scale': {'x': 1.0, 'y': 1.0},
            'bounds': {'x': float(bw), 'y': float(bh)}, 'scale_filter': 'disable', 'blend_method': 'default',
            'blend_type': 'normal', 'private_settings': {}}


def _pw(password):
    return f'&password={urllib.parse.quote(password, safe="")}' if password else ''


def vdo_view_url(room, password=''):
    return f'https://vdo.ninja/?view={room}&cleanoutput&autoplay' + _pw(password)


def vdo_push_url(room, password=''):
    return f'https://vdo.ninja/?push={room}' + _pw(password)


def ensure_vdo_keys(path=None):
    """ADD a 128-bit VDO.Ninja room id + a room password to config.json when missing (existing values, including the
    older short "vdo_room", are never changed; once these exist they are used instead). -> merged config."""
    from gs_common import CONFIG, merge_config_keys
    merge_config_keys({'vdo_room_id': 'stark' + secrets.token_hex(16), 'vdo_password': secrets.token_urlsafe(16)},
                      path or CONFIG)
    return load_config(path or CONFIG)


def vdo_room(cfg):
    """-> (room, password): the 128-bit room + password when configured, else the legacy room without one."""
    return (cfg.get('vdo_room_id') or cfg.get('vdo_room') or 'stark-room'), (cfg.get('vdo_password') or '')


def scene_collection(cam_dev, cam_how, mic_id, mic_label, room, password=''):
    if cam_dev:
        dev_id = obs_video_device_id(cam_dev)
        cam_name = ('Canon_EOS_R50V' if cam_how == 'canon' else f'Camera ({cam_dev["name"]})' if cam_how == 'chosen'
                    else f'Canon_EOS_R50V (via {cam_dev["name"]})')
    else:
        dev_id = ''
        cam_name = 'Canon_EOS_R50V - NOT FOUND (pick the camera in Properties)'
    cam = _source(cam_name, 'dshow_input', {'video_device_id': dev_id, 'last_video_device_id': dev_id,
                                            'active': True, 'deactivate_when_not_showing': False},
                  mixers=255, muted=True)
    phone = _source('iPhone_Remote_Cam', 'browser_source',
                    {'url': vdo_view_url(room, password), 'width': 1080, 'height': 1920, 'fps': 30, 'fps_custom': True,
                     'reroute_audio': False, 'shutdown': False, 'restart_when_active': False})
    screen = _source('Screen_Capture_WGC', 'monitor_capture', {'method': 2, 'capture_cursor': True,
                                                              'force_sdr': False})
    rnnoise = _source('RNNoise', 'noise_suppress_filter', {'method': 'rnnoise'})
    rnnoise['versioned_id'] = 'noise_suppress_filter_v2'
    rnnoise.pop('filters')
    mic = _source(f'Mic ({mic_label})', 'wasapi_input_capture', {'device_id': mic_id, 'use_device_timing': True},
                  mixers=255, sync=135000000, filters=[rnnoise])
    desk = _source('Desktop Audio', 'wasapi_output_capture', {'device_id': 'default'}, mixers=255)
    desk.pop('filters')
    items = [_item(cam, 1, 0, 0, 1920, 1080), _item(screen, 2, 1920, 0, 1920, 1080),
             _item(phone, 3, 1500, 300, 405, 720), _item(mic, 4, 0, 0, 0, 0)]
    scene = _source(SCENE, 'scene', {'id_counter': 4, 'custom_size': False, 'items': items})
    scene.pop('filters')
    return {
        'name': COLLECTION, 'version': 2, 'current_scene': SCENE, 'current_program_scene': SCENE,
        'scene_order': [{'name': SCENE}], 'sources': [cam, phone, screen, mic, scene], 'groups': [],
        'DesktopAudioDevice1': desk, 'current_transition': 'Fade', 'transition_duration': 300,
        'transitions': [], 'quick_transitions': [], 'saved_projectors': [], 'modules': {},
        'preview_locked': False, 'scaling_enabled': False, 'resolution': {'x': 3840, 'y': 1080},
    }


# ---------------- writing ----------------
def backup(paths, root_backups):
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    dest = os.path.join(root_backups, stamp)
    done = []
    for p in paths:
        if os.path.exists(p):
            os.makedirs(dest, exist_ok=True)
            tgt = os.path.join(dest, os.path.basename(p.rstrip('\\/')))
            (shutil.copytree if os.path.isdir(p) else shutil.copy2)(p, tgt)
            done.append(tgt)
    return done


def websocket_settings(path):
    """Enable obs-websocket v5 on 4455. An existing password is kept; if there is none, one is generated."""
    try:
        with open(path, encoding='utf-8-sig') as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = {}
    if not isinstance(cur, dict):          # damaged file (e.g. a JSON list): start from a clean settings object
        cur = {}
    pw = cur.get('server_password') if isinstance(cur.get('server_password'), str) else ''
    pw = pw or secrets.token_urlsafe(12)
    new = dict(cur)
    new.update({'server_enabled': True, 'server_port': WS_PORT, 'auth_required': True, 'server_password': pw,
                'alerts_enabled': cur.get('alerts_enabled', False), 'first_load': False})
    return new


def obs_running():
    try:
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq obs64.exe'], capture_output=True, text=True,
                           errors='replace', timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return 'obs64.exe' in (r.stdout or '')
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def write_all(obs_root=None, devs=None, nvidia=None, dry_run=False, backups_dir=None, room=None, camera=None,
              mic=None, vdo_password=''):
    """camera / mic: device names the user picked (setup wizard); None keeps the automatic choice."""
    obs_root = obs_root or obs_root_default()
    if room is None:
        cfg = load_config() if dry_run else (ensure_hub_keys() and ensure_vdo_keys())
        room, vdo_password = vdo_room(cfg)
    devs = list_dshow_devices() if devs is None else devs
    nvidia = has_nvidia() if nvidia is None else nvidia
    encoder = 'jim_nvenc' if nvidia else 'obs_x264'
    cam, how = pick_camera(devs)
    mic_id, mic_label = pick_mic(devs)
    chosen_cam = find_device(devs, camera, 'video') if camera else None
    if chosen_cam:
        cam, how = chosen_cam, ('canon' if CAM_RX.search(chosen_cam['name']) else 'chosen')
    chosen_mic = find_device(devs, mic, 'audio') if mic else None
    if chosen_mic and wasapi_id(chosen_mic):
        mic_id, mic_label = wasapi_id(chosen_mic), chosen_mic['name']
    rec_path = os.path.abspath(RAW).replace('\\', '/')
    prof_dir = os.path.join(obs_root, 'basic', 'profiles', PROFILE)
    coll = os.path.join(obs_root, 'basic', 'scenes', COLLECTION + '.json')
    ws_cfg = os.path.join(obs_root, 'plugin_config', 'obs-websocket', 'config.json')
    ws = websocket_settings(ws_cfg)
    sc = scene_collection(cam, how, mic_id, mic_label, room, vdo_password)
    report = {'obs_root': obs_root, 'profile': prof_dir, 'collection': coll, 'encoder': encoder,
              'gpu': nvidia or 'none', 'camera': cam['name'] if cam else None, 'camera_match': how,
              'camera_source': sc['sources'][0]['name'], 'mic': mic_label, 'rec_path': rec_path,
              'vdo_view': vdo_view_url(room, vdo_password), 'websocket': {'port': WS_PORT, 'auth_required': True},
              'obs_running': obs_running(), 'devices': [d['name'] for d in devs if d['kind'] == 'video']}
    if dry_run:
        report['dry_run'] = True
        return report
    report['backups'] = backup([prof_dir, coll, ws_cfg], backups_dir or os.path.join(STATE, 'obs_backups'))
    os.makedirs(prof_dir, exist_ok=True)
    with open(os.path.join(prof_dir, 'basic.ini'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(profile_ini(encoder, rec_path))
    for fn in ('recordEncoder.json', 'streamEncoder.json'):
        with open(os.path.join(prof_dir, fn), 'w', encoding='utf-8') as f:
            json.dump(encoder_json(encoder), f)
    os.makedirs(os.path.dirname(coll), exist_ok=True)
    with open(coll, 'w', encoding='utf-8') as f:
        json.dump(sc, f, indent=4)
    os.makedirs(os.path.dirname(ws_cfg), exist_ok=True)
    with open(ws_cfg, 'w', encoding='utf-8') as f:
        json.dump(ws, f, indent=2)
    os.makedirs(RAW, exist_ok=True)
    return report


def read_ws_password(obs_root=None):
    p = os.path.join(obs_root or obs_root_default(), 'plugin_config', 'obs-websocket', 'config.json')
    try:
        with open(p, encoding='utf-8-sig') as f:
            c = json.load(f)
        if not isinstance(c, dict):
            return ''
        pw = c.get('server_password', '') if c.get('auth_required', True) else ''
        return pw if isinstance(pw, str) else ''
    except (OSError, ValueError):
        return ''


# ---------------- obs-websocket v5 client (stdlib only) ----------------
class ObsWS:
    """Minimal obs-websocket v5 client: connect(), call(requestType, data) -> responseData, close()."""

    def __init__(self, host='127.0.0.1', port=WS_PORT, password=None, timeout=5.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.password = read_ws_password() if password is None else password
        self.sock, self._buf = None, b''

    def _send_frame(self, payload, opcode=1):
        b = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            b.append(0x80 | n)
        elif n < 65536:
            b.append(0x80 | 126); b += n.to_bytes(2, 'big')
        else:
            b.append(0x80 | 127); b += n.to_bytes(8, 'big')
        mask = secrets.token_bytes(4)
        b += mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
        self.sock.sendall(bytes(b))

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError('obs-websocket closed the connection')
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _recv_frame(self):
        msg = b''
        while True:
            h = self._read(2)
            fin, op, masked, n = h[0] & 0x80, h[0] & 0x0F, h[1] & 0x80, h[1] & 0x7F
            if n == 126:
                n = int.from_bytes(self._read(2), 'big')
            elif n == 127:
                n = int.from_bytes(self._read(8), 'big')
            mask = self._read(4) if masked else None
            data = self._read(n)
            if mask:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if op == 8:
                raise ConnectionError('obs-websocket closed: ' + data[2:].decode('utf-8', 'replace'))
            if op == 9:
                self._send_frame(data, 10); continue
            if op == 10:
                continue
            msg += data
            if fin:
                return json.loads(msg.decode('utf-8'))

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        self.sock.sendall((f'GET / HTTP/1.1\r\nHost: {self.host}:{self.port}\r\nUpgrade: websocket\r\n'
                           f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
                           'Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n').encode())
        head = b''
        while b'\r\n\r\n' not in head:
            c = self.sock.recv(4096)
            if not c:
                raise ConnectionError('no websocket handshake reply')
            head += c
        head, self._buf = head.split(b'\r\n\r\n', 1)
        if b' 101 ' not in head.split(b'\r\n')[0]:
            raise ConnectionError('websocket upgrade refused: ' + head.split(b'\r\n')[0].decode('latin-1'))
        want = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
        if want not in head:
            raise ConnectionError('bad Sec-WebSocket-Accept')
        hello = self._recv_frame()
        ident = {'rpcVersion': 1, 'eventSubscriptions': 0}
        auth = hello.get('d', {}).get('authentication')
        if auth:
            if not self.password:
                raise PermissionError('OBS websocket needs a password and none is configured')
            ident['authentication'] = self.auth_string(self.password, auth['salt'], auth['challenge'])
        self._send_frame(json.dumps({'op': 1, 'd': ident}).encode())
        r = self._recv_frame()
        if r.get('op') != 2:
            raise PermissionError(f'OBS websocket identify failed: {r}')
        return self

    @staticmethod
    def auth_string(password, salt, challenge):
        secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
        return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()

    def call(self, request_type, data=None):
        rid = secrets.token_hex(6)
        self._send_frame(json.dumps({'op': 6, 'd': {'requestType': request_type, 'requestId': rid,
                                                     'requestData': data or {}}}).encode())
        while True:
            r = self._recv_frame()
            if r.get('op') == 7 and r['d'].get('requestId') == rid:
                st = r['d'].get('requestStatus', {})
                if not st.get('result'):
                    raise RuntimeError(f'{request_type}: {st.get("comment") or st.get("code")}')
                return r['d'].get('responseData') or {}

    def close(self):
        try:
            if self.sock:
                self._send_frame(b'\x03\xe8', 8)
                self.sock.close()
        except OSError:
            pass
        self.sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *a):
        self.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--obs-root', default=None)
    a = ap.parse_args(argv)
    rep = write_all(a.obs_root, dry_run=a.dry_run)
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, 'obs_bridge_report.json'), 'w', encoding='utf-8') as f:
        json.dump(rep, f, indent=2)
    print(f'[obs] profile {PROFILE} + collection {COLLECTION} {"(dry run)" if a.dry_run else "written"}')
    print(f'[obs] encoder {rep["encoder"]} (GPU: {rep["gpu"]}), canvas 3840x1080, mkv + auto-remux -> {rep["rec_path"]}')
    msg = {'canon': 'Canon device found', 'capture': 'no device named Canon; using the HDMI capture device',
           'chosen': 'the camera you picked',
           'missing': 'camera NOT found: placeholder source kept, pick the device in OBS'}[rep['camera_match']]
    view = re.sub(r'password=[^&]*', 'password=***', rep['vdo_view'])
    print(f'[obs] camera: {rep["camera"]} ({msg}); mic: {rep["mic"]}; phone: {view}')
    print(f'[obs] websocket v5 enabled on port {WS_PORT}, password authentication on')
    if rep['obs_running']:
        print('[obs] NOTE: OBS is running; restart it so it reads the new websocket settings')
    return 0


if __name__ == '__main__':
    sys.exit(main())
