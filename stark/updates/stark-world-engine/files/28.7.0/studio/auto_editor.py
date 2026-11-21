"""auto_editor.py: watches raw_clips/ and turns each new recording session into an edited video + 3 vertical clips.

  python auto_editor.py --watch [--no-open]   background watcher (one instance; .claude/auto_editor.lock)
  python auto_editor.py --once  [--no-open]   edit whatever is ready now, then exit
  python auto_editor.py --probe               print the encoder that will be used

Inputs   : video files in raw_clips/ only (realpath-checked; nothing outside raw_clips is read). A file is ready once
           its size and time stamp stop changing. OBS auto-remux pairs (x.mkv + x.mp4) count once (the .mp4 wins).
Lock     : every edited file's SHA-256 (and its recording name) goes into .claude/editor_state.json, so the same
           recording is never edited twice, even after a restart or a rename.
Encoder  : h264_nvenc > h264_qsv > libx264, picked by a real 1-frame probe.
Edit     : each clip -> uniform 30 fps, yuv420p, even size of the first clip, 48 kHz stereo; concat; silence jump-cuts
           (-32 dB / 0.22 s from config.json); two-pass loudnorm to -14 LUFS; captions burned from a RELATIVE
           temp_subs.srt (ffmpeg runs inside the session's work folder). Captions come from <clip>.srt next to the clip,
           else from faster-whisper if it is installed locally, else a title caption.
Outputs  : edits/<session>/FINAL.mp4, Social_Clips/clip_1..3.mp4 (1080x1920), manifest.json, review_gate.html
           (opened in the browser unless --no-open). Log: .claude/editor.log.
"""
import argparse, ctypes, datetime, glob, hashlib, json, os, re, shutil, subprocess, sys, time

from gs_common import EDITS, RAW, STATE, find_ffmpeg, get_logger, load_config, merge_config_keys

# Local, offline enhancement engines (beat-sync cuts, cinematic grade/motion, kinetic captions).
# Imported defensively so the base editor still runs if an engine file is missing or broken.
try:
    import beat_engine, fx_engine, caption_engine
    ENGINES_OK = True
except Exception as _eng_e:  # noqa: BLE001
    beat_engine = fx_engine = caption_engine = None
    ENGINES_OK = False

# New config knobs for the high-tier pipeline. merge_config_keys() only ADDS the ones
# that are missing (existing values are kept, original config.json is backed up first).
EDITOR_DEFAULTS = {
    "grade_preset": "teal_orange",      # fx_engine.GRADES name, or "" to skip the grade
    "grade_intensity": 0.7,             # 0..1 blend toward the full look (subtle default)
    "punch_strength": 0.05,             # beat-synced punch-in zoom amount (0 disables)
    "finishing_grain": 0.3,             # film grain 0..1 (0/false disables)
    "finishing_vignette": True,         # soft corner falloff
    "finishing_glow": 0.14,             # bloom opacity 0..1 (0/false disables)
    "finishing_chroma": False,          # chromatic-aberration-lite (off by default)
    "finishing_intensity": 0.5,         # overall finishing strength 0..1
    "caption_preset": "bold_pop",       # caption_engine preset: bold_pop/clean_lower/hype
    "beat_snap": True,                  # snap silence cut boundaries onto the beat grid
    "beat_max_shift": 0.12,             # seconds a cut may move to reach a beat
    "fx_enable": True,                  # master toggle for grade + punch + finishing
    "transitions": True,                # crossfade between source clips when 2+ clips
    "transition_name": "crossfade",     # fx_engine.TRANSITIONS name
    "transition_dur": 0.4,              # seconds
}

VIDEO_EXT = ('.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v')
STATE_FILE = os.path.join(STATE, 'editor_state.json')
LOCK_FILE = os.path.join(STATE, 'auto_editor.lock')
ENC_ARGS = {'h264_nvenc': ['-c:v', 'h264_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', '21', '-b:v', '0'],
            'h264_qsv': ['-c:v', 'h264_qsv', '-global_quality', '22'],
            'libx264': ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20']}
AUDIO = ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2']
log = get_logger('auto_editor', 'editor.log')


def run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f'{os.path.basename(cmd[0])} failed ({r.returncode}):\n' + r.stderr[-2000:])
    return r


# ---------------- encoder ----------------
def probe_encoder(ff):
    for enc in ('h264_nvenc', 'h264_qsv', 'libx264'):
        try:      # a GPU driver that hangs or prints non-UTF-8 text must not stop the editor: try the next encoder
            r = subprocess.run([ff, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                                'color=c=black:s=256x256:r=30:d=0.2', '-frames:v', '3'] + ENC_ARGS[enc]
                               + ['-pix_fmt', 'yuv420p', '-f', 'null', '-'], capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=60)
        except subprocess.TimeoutExpired:
            continue
        if r.returncode == 0:
            return enc
    return 'libx264'


def venc(enc):
    return ENC_ARGS[enc] + ['-pix_fmt', 'yuv420p']


# ---------------- state / lock ----------------
def load_state():
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    if not isinstance(st, dict):           # damaged state file: start clean instead of crashing the watcher
        st = {}
    for k, kind in (('done', dict), ('stems', list), ('hash_cache', dict)):
        if not isinstance(st.get(k), kind):
            st[k] = kind()
    return st


def save_state(st):
    os.makedirs(STATE, exist_ok=True)
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE_FILE)


def sha256_file(path, st=None):
    s = os.stat(path)
    key = f'{os.path.basename(path)}|{s.st_size}|{int(s.st_mtime)}'
    if st is not None and key in st['hash_cache']:
        return st['hash_cache'][key]
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    d = h.hexdigest()
    if st is not None:
        st['hash_cache'][key] = d
    return d


def pid_alive(pid):
    """True if the process exists (Windows: OpenProcess/GetExitCodeProcess; never sends a signal)."""
    if pid <= 0:
        return False
    if os.name == 'nt':
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259            # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def take_lock():
    os.makedirs(STATE, exist_ok=True)
    try:
        with open(LOCK_FILE, encoding='utf-8') as f:
            pid = int(f.read().strip() or 0)
        if pid != os.getpid() and pid_alive(pid):
            return False
    except (OSError, ValueError):
        pass
    with open(LOCK_FILE, 'w', encoding='utf-8') as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    try:
        with open(LOCK_FILE, encoding='utf-8') as f:
            mine = int(f.read().strip() or 0) == os.getpid()
        if mine:
            os.remove(LOCK_FILE)
    except (OSError, ValueError):
        pass


# ---------------- discovery ----------------
def inside(path, root):
    rp, rr = os.path.realpath(path), os.path.realpath(root)
    return rp.startswith(rr + os.sep)


def candidates(raw=RAW):
    """Video files directly inside raw/ (realpath must stay inside raw/). x.mkv is dropped when x.mp4 exists."""
    files = [p for p in glob.glob(os.path.join(glob.escape(raw), '*'))
             if p.lower().endswith(VIDEO_EXT) and os.path.isfile(p) and inside(p, raw)]
    stems_mp4 = {os.path.splitext(p)[0].lower() for p in files if p.lower().endswith('.mp4')}
    return sorted(p for p in files if not (p.lower().endswith('.mkv') and os.path.splitext(p)[0].lower() in stems_mp4))


def ready_files(raw, st, sizes, settle=15.0, mkv_settle=90.0, now=None):
    """Files not done yet whose (size, mtime) did not change since the previous poll and that are old enough."""
    now = now or time.time()
    out = []
    for p in candidates(raw):
        stem = os.path.splitext(os.path.basename(p))[0].lower()
        if stem in st['stems']:
            continue
        s = os.stat(p)
        sig = (s.st_size, s.st_mtime)
        prev = sizes.get(p)
        sizes[p] = sig
        wait = mkv_settle if p.lower().endswith('.mkv') else settle
        if prev == sig and now - s.st_mtime >= wait and s.st_size > 0:
            out.append(p)
    return out


# ---------------- edit helpers ----------------
def ffprobe_json(probe, path, cwd=None):
    r = run([probe, '-v', 'error', '-show_entries', 'stream=codec_type,width,height:format=duration', '-of', 'json',
             path], cwd=cwd)
    return json.loads(r.stdout)


def parse_silences(stderr):
    starts = [float(x) for x in re.findall(r'silence_start: (-?[\d.]+)', stderr)]
    ends = [float(x) for x in re.findall(r'silence_end: (-?[\d.]+)', stderr)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def keep_segments(silences, duration, pad=0.08, min_len=0.15):
    """Complement of the silences (each kept part padded), merged, without slivers."""
    segs, t = [], 0.0
    for s, e in silences:
        s = max(0.0, s)
        if s > t:
            segs.append([max(0.0, t - pad), min(duration, s + pad)])
        t = duration if e is None else e
    if t < duration:
        segs.append([max(0.0, t - pad), duration])
    merged = []
    for a, b in segs:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in merged if b - a >= min_len]


def map_time(t, segs):
    """Joined-timeline time -> cut-timeline time (times inside a removed gap snap to the next kept part)."""
    acc = 0.0
    for a, b in segs:
        if t < a:
            return acc
        if t <= b:
            return acc + (t - a)
        acc += b - a
    return acc


def srt_time(t):
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def parse_srt_time(s):
    h, m, rest = s.strip().replace('.', ',').split(':')
    sec, ms = rest.split(',')
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def read_srt(path):
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        blocks = re.split(r'\n\s*\n', f.read().replace('\r\n', '\n').strip())
    out = []
    for b in blocks:
        lines = b.split('\n')
        for i, ln in enumerate(lines):
            m = re.match(r'(.+?)\s*-->\s*(.+)', ln)
            if m:
                out.append((parse_srt_time(m.group(1)), parse_srt_time(m.group(2)), ' '.join(lines[i + 1:]).strip()))
                break
    return out


def write_srt(cues, path):
    with open(path, 'w', encoding='utf-8') as f:
        n = 0
        for a, b, text in cues:
            if b - a < 0.05 or not text:
                continue
            n += 1
            f.write(f'{n}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n')
    return n


def whisper_cues(path):
    """Local speech-to-text when faster-whisper is installed (runs on this PC, no cloud). Else []."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return []
    try:
        model = WhisperModel('small', device='auto', compute_type='auto')
        segs, _ = model.transcribe(path, vad_filter=True)
        return [(s.start, s.end, s.text.strip()) for s in segs]
    except Exception as e:  # noqa: BLE001
        log.warning('faster-whisper failed: %s', e)
        return []


def caption_source(clip_paths, offsets, raw):
    """-> (cues on the joined timeline, how). Sidecar .srt files must also live inside raw_clips."""
    cues, how = [], 'title caption (add <clip>.srt or install faster-whisper for speech captions)'
    for p, off in zip(clip_paths, offsets):
        side = os.path.splitext(p)[0] + '.srt'
        if os.path.isfile(side) and inside(side, raw):
            cues += [(a + off, b + off, t) for a, b, t in read_srt(side)]
            how = 'sidecar .srt'
    if not cues:
        for p, off in zip(clip_paths, offsets):
            cues += [(a + off, b + off, t) for a, b, t in whisper_cues(p)]
        if cues:
            how = 'faster-whisper (local)'
    return cues, how


def measure_loudness(ff, path, target, cwd=None):
    r = subprocess.run([ff, '-hide_banner', '-i', path, '-af', f'loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json',
                        '-f', 'null', '-'], capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=cwd)
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    if not m:
        raise RuntimeError('loudnorm measurement failed:\n' + r.stderr[-1500:])
    return json.loads(m.group(0))


def loudnorm_af(m, target):
    return (f'loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m["input_i"]}:measured_TP={m["input_tp"]}:'
            f'measured_LRA={m["input_lra"]}:measured_thresh={m["input_thresh"]}:offset={m["target_offset"]}:linear=true,'
            'aresample=48000')


SUB_STYLE = ('FontName=Arial,Bold=1,FontSize={fs},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,'
             'Outline=3,Shadow=0,Alignment=2,MarginV={mv}')


# ---------------- enhancement helpers (beats / fx / captions) ----------------
def _point_engines(ff, probe):
    """Point the engines at the ffmpeg/ffprobe this editor resolved (fx_engine reads these;
    beat/caption_engine use PATH, so also export the env vars for consistency)."""
    if ff:
        os.environ['FFMPEG'] = ff
        if fx_engine is not None:
            fx_engine.FFMPEG = ff
    if probe:
        os.environ['FFPROBE'] = probe
        if fx_engine is not None:
            fx_engine.FFPROBE = probe


def _join_clips(ff, enc, cfg, norm, durs, work, degraded):
    """Join the normalised clips -> work/joined.mp4 and return (path, per-clip start offsets).

    With transitions on and 2+ clips, crossfade between them via fx_engine.transition(); the
    offsets are pulled in by the transition overlap so captions stay aligned. Falls back to a
    plain stream-copy concat (the robust base behaviour) on any error or for a single clip.
    """
    joined = os.path.join(work, 'joined.mp4')
    offsets, acc = [], 0.0
    for d in durs:
        offsets.append(round(acc, 4)); acc += d
    name = cfg.get('transition_name', 'crossfade')
    td = max(0.05, float(cfg.get('transition_dur', 0.4)))
    want_tx = (ENGINES_OK and fx_engine is not None and cfg.get('transitions', True)
               and len(norm) >= 2 and name in getattr(fx_engine, 'TRANSITIONS', {})
               and all(d > td + 0.2 for d in durs))
    if want_tx:
        try:
            parts, cv, ca, T, tx_off = [], '0:v', '0:a', durs[0], [0.0]
            for i in range(1, len(norm)):
                off = max(0.0, T - td)
                tx_off.append(round(off, 4))
                spec = fx_engine.transition(name, td, off)
                parts.append(f'[{cv}][{i}:v]{spec["video"]}[vx{i}]')
                parts.append(f'[{ca}][{i}:a]{spec["audio"]}[ax{i}]')
                cv, ca = f'vx{i}', f'ax{i}'
                T += durs[i] - td
            args = [ff, '-y', '-hide_banner']
            for p in norm:
                args += ['-i', os.path.basename(p)]
            args += ['-filter_complex', ';'.join(parts), '-map', f'[{cv}]', '-map', f'[{ca}]']
            run(args + venc(enc) + AUDIO + ['joined.mp4'], cwd=work)
            return joined, tx_off
        except Exception as e:  # noqa: BLE001
            degraded.append(f'transitions->concat: {e}')
            log.warning('transition join failed, using plain concat: %s', e)
    with open(os.path.join(work, 'concat.txt'), 'w', encoding='utf-8') as f:
        f.writelines(f"file '{os.path.basename(p)}'\n" for p in norm)
    run([ff, '-y', '-hide_banner', '-f', 'concat', '-safe', '0', '-i', 'concat.txt', '-c', 'copy', 'joined.mp4'],
        cwd=work)
    return joined, offsets


def _beats_and_snap(cfg, work, segs, joined_d, degraded):
    """Analyse the beat grid, snap the keep/cut boundaries onto it, and return
    (beat_info, snapped_segs, n_boundaries_moved, accents_on_cut_timeline).

    Degrades to the silence-only segments (and no accents) if analysis is unavailable."""
    if not (ENGINES_OK and beat_engine is not None and cfg.get('beat_snap', True)):
        return None, segs, 0, []
    try:
        info = beat_engine.analyze(os.path.join(work, 'joined.mp4'))
    except Exception as e:  # noqa: BLE001
        degraded.append(f'beats: {e}')
        log.warning('beat analysis failed, silence-only cuts: %s', e)
        return None, segs, 0, []
    beats = info.get('beats') or []
    shift = float(cfg.get('beat_max_shift', 0.12))
    moved, new = 0, []
    for a, b in segs:
        na = snap_cuts_one(a, beats, shift)
        nb = snap_cuts_one(b, beats, shift)
        na = min(max(0.0, na), joined_d)
        nb = min(max(0.0, nb), joined_d)
        if nb - na >= 0.15:
            moved += (abs(na - a) > 1e-4) + (abs(nb - b) > 1e-4)
            new.append((round(na, 3), round(nb, 3)))
    new.sort()
    snapped = []                       # merge any overlap the snap may have created
    for a, b in (new or segs):
        if snapped and a <= snapped[-1][1]:
            snapped[-1] = (snapped[-1][0], max(snapped[-1][1], b))
        else:
            snapped.append((a, b))
    acc = beat_engine.accents(beats, info.get('downbeats') or [], info.get('energy_envelope') or [])
    acc_cut = [(round(map_time(t, snapped), 4), s) for t, s in acc if any(a <= t <= b for a, b in snapped)]
    if len(acc_cut) > 400:             # keep the graph expression bounded on long videos
        acc_cut = acc_cut[:400]
    return info, snapped, moved, acc_cut


def snap_cuts_one(t, beats, shift):
    """One boundary snapped onto the nearest beat via beat_engine.snap_cuts (single-cut call)."""
    return beat_engine.snap_cuts([t], beats, shift)[0] if beats else t


def _fx_options(cfg, size, accents):
    """Build the fx_engine.compose()/render_clip() options dict from config (subtle by default)."""
    opts = {'size': size, 'fps': 30, 'accents': list(accents or [])}
    if cfg.get('grade_preset'):
        opts['grade'] = cfg['grade_preset']
        opts['grade_intensity'] = float(cfg.get('grade_intensity', 0.7))
    if accents and float(cfg.get('punch_strength', 0.05)) > 0:
        opts['punch'] = {'strength': float(cfg['punch_strength']), 'tau': 0.16}
    fin = {}
    if cfg.get('finishing_grain'):
        fin['grain'] = float(cfg['finishing_grain'])
    if cfg.get('finishing_vignette'):
        fin['vignette'] = True
    if cfg.get('finishing_glow'):
        fin['glow'] = float(cfg['finishing_glow'])
    if cfg.get('finishing_chroma'):
        fin['chroma'] = True
    if fin:
        fin['intensity'] = float(cfg.get('finishing_intensity', 0.5))
        opts['finishing'] = fin
    return opts


# ---------------- ffmpeg filter-safe paths ----------------
def ff_filter_escape(value):
    r"""Escape a value for an ffmpeg filter option inside a -vf graph (both escaping levels, ffmpeg-filters 4.1):
    level 1 (option value) escapes ' and : ; level 2 (filtergraph) escapes \ ' [ ] , ; . Backslashes in Windows
    paths become forward slashes first, so no literal backslash survives into level 1."""
    v = str(value).replace('\\', '/')
    for ch in ("'", ':'):
        v = v.replace(ch, '\\' + ch)
    return ''.join('\\' + ch if ch in "\\'[],;" else ch for ch in v)


def styled_caption_vf(ass_path, fonts_dir=None):
    """-vf for the ass filter that references the .ass by its BARE name (run ffmpeg with cwd = its folder).
    The bare name is generated by us ({tag}_subs.ass) but is escaped anyway; fontsdir is escaped in full."""
    vf = f'ass=filename={ff_filter_escape(os.path.basename(ass_path))}'
    if fonts_dir and os.path.isdir(fonts_dir):
        vf += f':fontsdir={ff_filter_escape(fonts_dir)}'
    return vf


# ---------------- disk space ----------------
class DiskSpaceError(RuntimeError):
    """Raised before an edit starts when the edits drive is too full; the message is shown to the user as-is."""


DISK_FACTOR = 4          # work/ intermediates peak at about 3-4x the raw input (norm, joined, cut, stage renders)
DISK_MARGIN = 512 * 1024 * 1024


def _existing_parent(path):
    path = os.path.abspath(path)
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def disk_need_bytes(clips):
    total = 0
    for c in clips:
        try:
            total += os.path.getsize(c)
        except OSError:
            pass
    return total * DISK_FACTOR + DISK_MARGIN


def check_disk_space(clips, dest, usage=None):
    """Refuse (DiskSpaceError) when the drive holding dest has less free space than the edit will need."""
    need = disk_need_bytes(clips)
    try:
        free = (usage or shutil.disk_usage)(_existing_parent(dest)).free
    except OSError:
        return need, None            # cannot tell: do not block the edit
    if free < need:
        gb = 1024 ** 3
        raise DiskSpaceError(f'not enough free disk space for this edit: about {need / gb:.1f} GB is needed '
                             f'and only {free / gb:.1f} GB is free on the drive holding {os.path.abspath(dest)}. '
                             'Free some space (or move older edits/ sessions) and run the edit again.')
    return need, free


def _cleanup_failed_work(work):
    """After a failed edit, drop the large work/ intermediates; logs and the state file live elsewhere."""
    shutil.rmtree(work, ignore_errors=True)
    if os.path.isdir(work):
        log.warning('could not fully remove %s after the failed edit', work)


def _render_enhanced(ff, probe, enc, cfg, src, dst, size, orientation, cues, accents, target, work, tag, degraded):
    """src -> dst through: cinematic grade + beat-synced motion + finishing (fx_engine),
    then kinetic styled captions (caption_engine), then two-pass loudnorm to target LUFS.

    Every stage degrades independently: if one errors we log it, record it in the manifest,
    and carry the last good intermediate forward, so a valid dst is always produced."""
    W, H = size
    cur = src
    # --- 1. look + motion ---------------------------------------------------
    if ENGINES_OK and fx_engine is not None and cfg.get('fx_enable', True):
        try:
            fxout = os.path.join(work, f'{tag}_fx.mp4')
            fx_engine.render_clip(cur, fxout, _fx_options(cfg, size, accents))
            cur = fxout
        except Exception as e:  # noqa: BLE001
            degraded.append(f'{tag}:fx:{e}')
            log.warning('fx stage failed on %s: %s', tag, e)
    # --- 2. captions --------------------------------------------------------
    if cues:
        srt = os.path.join(work, f'{tag}_subs.srt')
        if write_srt(cues, srt):
            capout = os.path.join(work, f'{tag}_cap.mp4')
            try:
                if ENGINES_OK and caption_engine is not None:
                    style = {'preset': cfg.get('caption_preset', 'bold_pop'), 'orientation': orientation}
                    ass = caption_engine.srt_to_ass(srt, style, os.path.join(work, f'{tag}_subs.ass'))
                    vf = styled_caption_vf(ass, getattr(caption_engine, 'WINDOWS_FONTS_DIR', None))
                else:
                    raise RuntimeError('caption_engine unavailable')
                # cwd=work + bare .ass name: the install path (O'Brien, a,b [x];y ...) never enters the filter.
                run([ff, '-y', '-hide_banner', '-i', cur, '-vf', vf] + venc(enc)
                    + ['-c:a', 'copy', '-movflags', '+faststart', capout], cwd=work)
                cur = capout
            except Exception as e:  # noqa: BLE001
                degraded.append(f'{tag}:captions->plain:{e}')
                log.warning('styled captions failed on %s, plain burn: %s', tag, e)
                try:                    # fall back to the base plain SRT burn so captions still show
                    st = SUB_STYLE.format(fs=max(14, int(18 * H / 1080)), mv=90 if orientation == '9:16' else 40)
                    run([ff, '-y', '-hide_banner', '-i', cur, '-vf',
                         f"subtitles={os.path.basename(srt)}:force_style='{st}'"] + venc(enc)
                        + ['-c:a', 'copy', '-movflags', '+faststart', capout], cwd=work)
                    cur = capout
                except Exception as e2:  # noqa: BLE001
                    degraded.append(f'{tag}:captions-off:{e2}')
                    log.warning('plain caption burn also failed on %s: %s', tag, e2)
    # --- 3. loudness --------------------------------------------------------
    try:
        m = measure_loudness(ff, cur, target)
        run([ff, '-y', '-hide_banner', '-i', cur, '-af', loudnorm_af(m, target)]
            + venc(enc) + AUDIO + ['-movflags', '+faststart', dst])
    except Exception as e:  # noqa: BLE001
        degraded.append(f'{tag}:loudnorm:{e}')
        log.warning('loudnorm failed on %s, writing un-normalised: %s', tag, e)
        if os.path.abspath(cur) != os.path.abspath(dst):
            shutil.copyfile(cur, dst)
    return dst


# ---------------- the edit ----------------
def edit_session(clips, ff, probe, enc, cfg, raw=RAW, edits=EDITS, session=None):
    for c in clips:
        if not inside(c, raw):
            raise ValueError(f'{c} is outside raw_clips')
    _point_engines(ff, probe)
    check_disk_space(clips, edits)
    session = session or datetime.datetime.now().strftime('session_%Y%m%d_%H%M%S')
    out_dir = os.path.join(edits, session)
    work = os.path.join(out_dir, 'work')
    os.makedirs(work, exist_ok=True)
    os.makedirs(os.path.join(out_dir, 'Social_Clips'), exist_ok=True)
    try:
        return _edit_body(clips, ff, probe, enc, cfg, raw, session, out_dir, work)
    except BaseException:
        _cleanup_failed_work(work)
        raise


def run_cut(ff, enc, work):
    """joined.mp4 + cut_filter.txt -> cut.mp4 (inside `work`)."""
    tail = ['-map', '[v]', '-map', '[a]'] + venc(enc) + AUDIO + ['cut.mp4']
    try:
        run([ff, '-y', '-hide_banner', '-i', 'joined.mp4', '-/filter_complex', 'cut_filter.txt'] + tail, cwd=work)
    except RuntimeError as e:
        if 'filter_complex' not in str(e) or 'nrecognized option' not in str(e):
            raise
        # FFmpeg 6.x and older do not know "-/option file"; they read a filter script with -filter_complex_script.
        log.info('old ffmpeg: retrying the cut with -filter_complex_script')
        run([ff, '-y', '-hide_banner', '-i', 'joined.mp4', '-filter_complex_script', 'cut_filter.txt'] + tail,
            cwd=work)


def _edit_body(clips, ff, probe, enc, cfg, raw, session, out_dir, work):
    degraded = []
    info0 = ffprobe_json(probe, clips[0])
    v0 = next((s for s in info0['streams'] if s['codec_type'] == 'video'), None)
    if not v0:
        raise ValueError(f'{os.path.basename(clips[0])} has no video stream')
    W, H = int(v0['width']) // 2 * 2, int(v0['height']) // 2 * 2
    norm, durs = [], []
    for i, c in enumerate(clips):
        info = ffprobe_json(probe, c)
        has_a = any(s['codec_type'] == 'audio' for s in info['streams'])
        dur = float(info['format'].get('duration') or 0)
        out = os.path.join(work, f'norm_{i:02d}.mp4')
        vf = (f'scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30,'
              'format=yuv420p,setsar=1')
        args = [ff, '-y', '-hide_banner', '-i', c]
        if not has_a:
            args += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
        args += ['-map', '0:v:0', '-map', '0:a:0' if has_a else '1:a:0', '-vf', vf, '-af',
                 'aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo', '-t', f'{dur:.3f}']
        run(args + venc(enc) + AUDIO + [out])
        norm.append(out)
        durs.append(dur)
    joined, offsets = _join_clips(ff, enc, cfg, norm, durs, work, degraded)
    joined_d = float(ffprobe_json(probe, 'joined.mp4', cwd=work)['format']['duration'])
    r = subprocess.run([ff, '-hide_banner', '-i', 'joined.mp4', '-af',
                        f'silencedetect=noise={cfg["silence_db"]}dB:d={cfg["silence_min_s"]}', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=work)
    sil = parse_silences(r.stderr)
    segs = keep_segments(sil, joined_d) or [(0.0, round(joined_d, 3))]
    # Beat-sync: snap the silence-based keep/cut boundaries onto the beat grid; get FX accents.
    beatinfo, segs, cuts_snapped, acc_cut = _beats_and_snap(cfg, work, segs, joined_d, degraded)
    sel = '+'.join(f'between(t,{a},{b})' for a, b in segs)
    with open(os.path.join(work, 'cut_filter.txt'), 'w', encoding='utf-8') as f:
        f.write(f"[0:v]select='{sel}',setpts=N/FRAME_RATE/TB[v];[0:a]aselect='{sel}',asetpts=N/SR/TB[a]")
    run_cut(ff, enc, work)
    cut_d = float(ffprobe_json(probe, 'cut.mp4', cwd=work)['format']['duration'])
    cues, how = caption_source(clips, offsets, raw)
    cues = [(map_time(a, segs), map_time(b, segs), x) for a, b, x in cues]
    cues = [(a, b, x) for a, b, x in cues if b - a > 0.05]
    if not cues:
        cues = [(0.2, min(cut_d, 4.0), cfg.get('video_topic') or 'Stark World Engine')]
        how = 'title caption (add <clip>.srt or install faster-whisper for speech captions)'
    target = cfg['target_lufs']
    cut_path = os.path.join(work, 'cut.mp4')
    # FINAL render (16:9, source size): grade + beat-synced motion + finishing + kinetic captions.
    final = os.path.join(out_dir, 'FINAL.mp4')
    _render_enhanced(ff, probe, enc, cfg, cut_path, final, (W, H), '16:9', cues, acc_cut, target, work, 'final',
                     degraded)
    # 3 vertical clips (1080x1920): camera half of a dual 32:9 canvas (or the centre of a normal frame).
    clips_out = []
    part = cut_d / 3
    crop = 'crop=iw/2:ih:0:0,' if W / H > 3 else ''
    for k in range(3):
        start, length = part * k, min(30.0, part)
        if length < 1.0:
            break
        vraw = os.path.join(work, f'vraw_{k + 1}.mp4')
        vf = f'{crop}crop=min(iw\\,ih*9/16):ih,scale=1080:1920,setsar=1'
        run([ff, '-y', '-hide_banner', '-ss', f'{start:.3f}', '-t', f'{length:.3f}', '-i', 'cut.mp4', '-vf', vf]
            + venc(enc) + AUDIO + [os.path.basename(vraw)], cwd=work)
        c_cues = [(max(0.0, a - start), b - start, x) for a, b, x in cues if b > start and a < start + length]
        c_acc = [(t - start, s) for t, s in acc_cut if start <= t < start + length]
        dest = os.path.join(out_dir, 'Social_Clips', f'clip_{k + 1}.mp4')
        _render_enhanced(ff, probe, enc, cfg, vraw, dest, (1080, 1920), '9:16', c_cues, c_acc, target, work,
                         f'clip{k + 1}', degraded)
        clips_out.append(dest)
    lufs = float(measure_loudness(ff, final, target)['input_i'])
    man = {'session': session, 'created': datetime.datetime.now().isoformat(timespec='seconds'),
           'sources': [os.path.basename(c) for c in clips], 'encoder': enc, 'size': f'{W}x{H}',
           'source_s': round(joined_d, 2), 'final_s': round(cut_d, 2), 'silences_cut': len(sil),
           'segments': len(segs), 'lufs': round(lufs, 2), 'captions': how,
           'captions_style': cfg.get('caption_preset', 'bold_pop') if ENGINES_OK else 'plain',
           'grade': (cfg.get('grade_preset') or 'none') if (ENGINES_OK and cfg.get('fx_enable', True)) else 'none',
           'tempo_bpm': (beatinfo or {}).get('tempo_bpm'),
           'beat_snap': bool(beatinfo), 'cuts_snapped': cuts_snapped, 'accents': len(acc_cut),
           'transitions': cfg.get('transition_name') if (cfg.get('transitions', True) and len(clips) >= 2) else None,
           'degraded': degraded,
           'final': 'FINAL.mp4', 'social_clips': [f'Social_Clips/{os.path.basename(c)}' for c in clips_out]}
    with open(os.path.join(out_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f, indent=2)
    write_review_gate(out_dir, man, cfg)
    shutil.rmtree(work, ignore_errors=True)
    if degraded:
        log.warning('%s produced with %d degraded stage(s): %s', session, len(degraded), '; '.join(degraded))
    return out_dir, man


def write_review_gate(out_dir, man, cfg):
    vids = ''.join(f'<figure><video src="{c}" controls playsinline preload="metadata"></video><figcaption>{c}'
                   '</figcaption></figure>' for c in man['social_clips'])
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Review gate - {man['session']}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{{margin:0;background:#101418;color:#e9eef2;font:15px system-ui,sans-serif;padding:16px}}h1{{font-size:20px}}
video{{max-width:100%;border-radius:8px;background:#000}}.v{{display:flex;flex-wrap:wrap;gap:12px}}
.v figure{{margin:0;width:220px}}.v video{{width:220px}}a.btn{{display:inline-block;background:#5fd3b5;color:#05231c;
padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600}}td{{padding:2px 10px 2px 0;color:#93a3b1}}
</style></head><body><h1>Review gate: {man['session']}</h1>
<p>Nothing is published from this page. Watch the edit, then approve it on the Creator Hub (it asks for your PIN).
Publishing tools run only after that approval.</p>
<p><a class="btn" href="http://127.0.0.1:8510/?tab=review&amp;session={man['session']}">Open Review &amp; Approve on the hub</a></p>
<video src="{man['final']}" controls preload="metadata"></video>
<table><tr><td>Sources</td><td>{', '.join(man['sources'])}</td></tr><tr><td>Length</td><td>{man['source_s']} s raw -&gt; {man['final_s']} s cut ({man['silences_cut']} silences removed)</td></tr>
<tr><td>Loudness</td><td>{man['lufs']} LUFS (target {cfg['target_lufs']})</td></tr><tr><td>Captions</td><td>{man['captions']}</td></tr>
<tr><td>Encoder</td><td>{man['encoder']}</td></tr></table><h2>Social clips (1080x1920)</h2><div class="v">{vids}</div></body></html>
"""
    p = os.path.join(out_dir, 'review_gate.html')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(html)
    return p


def process_ready(clips, st, ff, probe, enc, cfg, open_gate=True, raw=RAW, edits=EDITS):
    hashes, fresh = [], []
    for c in clips:
        d = sha256_file(c, st)
        stem = os.path.splitext(os.path.basename(c))[0].lower()
        if d in st['done']:
            log.info('skip %s: already edited (sha256 %s)', os.path.basename(c), d[:12])
            if stem not in st['stems']:
                st['stems'].append(stem)
            continue
        hashes.append(d); fresh.append(c)
    if not fresh:
        save_state(st)
        return None
    log.info('editing %d clip(s): %s (encoder %s)', len(fresh), ', '.join(map(os.path.basename, fresh)), enc)
    try:
        out_dir, man = edit_session(fresh, ff, probe, enc, cfg, raw, edits)
    except DiskSpaceError as e:
        # Refused BEFORE any work: do not lock the clips, so the edit runs once space is freed (as the message says).
        log.error('edit postponed: %s', e)
        save_state(st)
        raise
    except Exception as e:  # noqa: BLE001
        log.error('edit failed: %s', e)
        for d, c in zip(hashes, fresh):            # locked anyway, so a broken file cannot loop forever
            st['done'][d] = {'file': os.path.basename(c), 'session': None, 'error': str(e)[:300]}
            st['stems'].append(os.path.splitext(os.path.basename(c))[0].lower())
        save_state(st)
        raise
    for d, c in zip(hashes, fresh):
        st['done'][d] = {'file': os.path.basename(c), 'session': man['session'],
                         'at': datetime.datetime.now().isoformat(timespec='seconds')}
        st['stems'].append(os.path.splitext(os.path.basename(c))[0].lower())
    save_state(st)
    log.info('done %s: %s s -> %s s, %s LUFS, %d social clips', man['session'], man['source_s'], man['final_s'],
             man['lufs'], len(man['social_clips']))
    if open_gate:
        try:
            os.startfile(os.path.join(out_dir, 'review_gate.html'))  # local file in the default browser
        except (AttributeError, OSError):
            pass
    return out_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--watch', action='store_true')
    g.add_argument('--once', action='store_true')
    g.add_argument('--probe', action='store_true')
    ap.add_argument('--no-open', action='store_true')
    ap.add_argument('--interval', type=float, default=10.0)
    ap.add_argument('--settle', type=float, default=15.0)
    a = ap.parse_args(argv)
    try:
        added = merge_config_keys(EDITOR_DEFAULTS)
        if added:
            log.info('config.json: added editor keys %s (original backed up)', added)
    except Exception as e:  # noqa: BLE001
        log.warning('could not merge editor config keys (using defaults): %s', e)
    cfg = load_config()
    ff, probe = find_ffmpeg(cfg)
    if not ff or not probe:
        print('ffmpeg/ffprobe not found: install FFmpeg or set "ffmpeg" in config.json'); return 1
    enc = probe_encoder(ff)
    if a.probe:
        print(enc); return 0
    if not take_lock():
        print('another auto_editor is already running (see .claude/auto_editor.lock)'); return 0
    os.makedirs(RAW, exist_ok=True)
    log.info('auto_editor started (%s, encoder %s, pid %d)', 'watch' if a.watch else 'once', enc, os.getpid())
    st, sizes = load_state(), {}
    try:
        if a.once:
            ready_files(RAW, st, sizes, 0, 0)
            clips = ready_files(RAW, st, sizes, 0, 0)
            out = process_ready(clips, st, ff, probe, enc, cfg, not a.no_open) if clips else None
            print(f'edited -> {out}' if out else 'nothing new in raw_clips/')
            return 0
        while True:
            try:
                clips = ready_files(RAW, st, sizes, a.settle, max(90.0, a.settle))
                if clips:
                    process_ready(clips, st, ff, probe, enc, cfg, not a.no_open)
            except DiskSpaceError:
                time.sleep(max(0.0, 300.0 - a.interval))     # disk full: re-check every ~5 min, not every poll
            except Exception as e:  # noqa: BLE001
                log.error('watch loop: %s', e)
            time.sleep(a.interval)
    except KeyboardInterrupt:
        return 0
    finally:
        release_lock()


if __name__ == '__main__':
    sys.exit(main())
