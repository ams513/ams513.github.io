"""fx_engine.py - Stark World Engine cinematic video FX library (pure ffmpeg, 100% local).

No paid cloud APIs, no network. Everything is an ffmpeg filtergraph rendered with the
local ffmpeg/ffprobe on PATH. numpy is optional (graceful fallback if absent).

The module returns ffmpeg *filter strings* and offers thin helpers that actually run
ffmpeg. Two kinds of returns:

  * LINEAR builders (`grade`, `punch_zoom`) return a bare filterchain with no stream
    labels. They can be comma-joined with others or passed straight to ``-vf``.
  * GRAPH builders (`finishing`, `compose`, `ramp_speed`, `glow`) return labelled
    ``filter_complex`` fragments because they branch (split/blend, trim/concat).
  * `transition` returns a dict of the xfade/acrossfade specs to splice two clips.

Design: a pro editor's restraint. Every effect has an ``intensity`` 0..1 knob and the
defaults are deliberately subtle. Output is normalised to fps=30, yuv420p.

Public API
----------
    GRADES, TRANSITIONS                         -> available preset names
    grade(name, intensity=0.85)                 -> str   (linear)
    punch_zoom(accents, fps=30, ...)            -> str   (linear)
    ramp_speed(segments, fps=30, audio=True)    -> str   (filter_complex, [v]/[a])
    transition(name, duration=0.5, offset=0.0)  -> dict  {video, audio, name, duration}
    finishing(options, in_label, out_label)     -> str   (filter_complex fragment)
    glow(in_label, out_label, intensity=0.25)   -> str   (filter_complex fragment)
    compose(options)                            -> str   (filter_complex, [vout])

    render_clip(src, out, options, ...)         -> out path (runs ffmpeg via compose)
    crossfade_clips(a, b, out, name, duration)  -> out path (xfade + acrossfade)
    make_test_clip(out, seconds, size, hz)      -> out path (testsrc2 + sine)
    probe(path)                                 -> dict (width,height,fps,pix_fmt,dur,has_audio)

Run ``python fx_engine.py`` for a full self-test that renders example outputs.
"""

import json
import math
import os
import subprocess

try:                                   # numpy is optional; only used for a smoothstep LUT.
    import numpy as _np
except Exception:                      # graceful fallback -> pure-python math.
    _np = None

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
FPS = 30
PIX = "yuv420p"


# --------------------------------------------------------------------------- helpers
def _run(args):
    """Run ffmpeg/ffprobe, raise with stderr tail on failure."""
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-18:])
        raise RuntimeError("ffmpeg failed (%d):\n%s" % (p.returncode, tail))
    return p


def _lerp1(target, k):
    """Lerp a multiplicative param (1.0 == identity) toward `target` by amount k."""
    return round(1.0 + (target - 1.0) * k, 4)


def _scale0(target, k):
    """Scale an additive param (0.0 == identity) by amount k."""
    return round(target * k, 4)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _smoothstep_points(n=5):
    """Return n (x,y) ease points on a smoothstep curve; uses numpy if present."""
    if _np is not None:
        xs = _np.linspace(0.0, 1.0, n)
        ys = xs * xs * (3 - 2 * xs)
        return list(zip([round(float(x), 3) for x in xs], [round(float(y), 3) for y in ys]))
    out = []
    for i in range(n):
        x = i / (n - 1)
        out.append((round(x, 3), round(x * x * (3 - 2 * x), 3)))
    return out


# --------------------------------------------------------------------------- grades
# Each preset: eq multiplicative/additive moves + colorbalance shifts + optional extra.
GRADES = {
    "teal_orange": {
        "eq": {"contrast": 1.08, "saturation": 1.06},
        "cb": {"rs": -0.05, "bs": 0.06, "rh": 0.06, "bh": -0.06},
    },
    "warm_film": {
        "eq": {"contrast": 1.04, "saturation": 1.04, "gamma_r": 1.05, "gamma_b": 0.96},
        "cb": {"rs": 0.03, "bh": -0.05},
        "curves": "all='0/0.02 0.5/0.5 1/0.97'",
    },
    "cold_cinematic": {
        "eq": {"contrast": 1.08, "saturation": 0.9, "gamma_b": 1.03},
        "cb": {"rs": -0.04, "bs": 0.06, "bh": 0.04},
        "curves": "all='0/0 0.5/0.47 1/0.98'",
    },
    "punch": {
        "eq": {"contrast": 1.12, "saturation": 1.12, "brightness": 0.01},
        "cb": {},
        "extra": "unsharp=5:5:0.3:5:5:0.0",
    },
    "neutral_clean": {
        "eq": {"contrast": 1.03, "saturation": 1.02},
        "cb": {},
    },
}

_EQ_ADD = {"brightness"}  # additive eq keys (0 == identity); the rest are multiplicative (1 == identity)


def grade(name="neutral_clean", intensity=0.85):
    """Return a bare, comma-joinable colour-grade filterchain for a named look.

    Subtle by default; `intensity` 0..1 blends from a clean image (0) to the full look.
    """
    if name not in GRADES:
        raise ValueError("unknown grade %r; choose from %s" % (name, sorted(GRADES)))
    k = _clamp(float(intensity), 0.0, 1.0)
    spec = GRADES[name]
    parts = []

    eq = []
    for key, tgt in spec.get("eq", {}).items():
        val = _scale0(tgt, k) if key in _EQ_ADD else _lerp1(tgt, k)
        eq.append("%s=%s" % (key, val))
    if eq:
        parts.append("eq=" + ":".join(eq))

    cb = []
    for key, tgt in spec.get("cb", {}).items():
        val = _scale0(tgt, k)
        if val != 0.0:
            cb.append("%s=%s" % (key, val))
    if cb:
        parts.append("colorbalance=" + ":".join(cb))

    if spec.get("curves") and k >= 0.4:   # curves are anchor moves; apply once we're past faint
        parts.append("curves=" + spec["curves"])
    if spec.get("extra") and k >= 0.3:
        parts.append(spec["extra"])

    return ",".join(parts) if parts else "null"


# --------------------------------------------------------------------------- punch-in zoom
def _norm_accents(accents):
    """Normalise accents to a list of (time, strength) with sane strength clamp."""
    out = []
    for a in accents or []:
        if isinstance(a, (list, tuple)):
            t, s = float(a[0]), float(a[1])
        else:
            t, s = float(a), 1.0
        out.append((round(t, 4), _clamp(s, 0.0, 1.0)))
    return out


def punch_zoom(accents, fps=FPS, strength=0.06, tau=0.16, size=(1920, 1080)):
    """Beat-synced punch-in zoom: snap to ~1+strength on each accent, ease back (tau s).

    Returns a bare ``zoompan=...`` filterchain. `accents` is a list of seconds, or of
    (seconds, 0..1 strength). Zoom pulses are combined with max() so they never stack
    past the per-accent ceiling. Centre-anchored, resolution preserved via ``s=WxH``.
    """
    W, H = int(size[0]) // 2 * 2, int(size[1]) // 2 * 2
    acc = _norm_accents(accents)
    strength = _clamp(float(strength), 0.0, 0.25)
    tau = max(0.04, float(tau))
    T = "(on/%d)" % int(fps)
    if not acc:
        z = "1"
    else:
        pulses = []
        for t, s in acc:
            amp = round(strength * s, 5)
            # instant rise at t, exponential ease-back over tau; 0 before the accent.
            pulses.append("%s*exp(0-(%s-%s)/%s)*gte(%s,%s)" % (amp, T, t, tau, T, t))
        expr = pulses[0]
        for p in pulses[1:]:               # nested max() -> envelope, not sum
            expr = "max(%s,%s)" % (expr, p)
        z = "1+%s" % expr
    return ("zoompan=z='%s':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            "d=1:fps=%d:s=%dx%d" % (z, int(fps), W, H))


# --------------------------------------------------------------------------- speed ramp
def _atempo_chain(factor):
    """atempo supports 0.5..100 per instance; chain to reach any positive factor."""
    f = max(0.01, float(factor))
    links = []
    while f > 100.0:
        links.append("atempo=100.0")
        f /= 100.0
    while f < 0.5:
        links.append("atempo=0.5")
        f /= 0.5
    links.append("atempo=%s" % round(f, 5))
    return ",".join(links)


def ramp_speed(segments, fps=FPS, audio=True):
    """Variable speed from a list of (start_s, end_s, factor) over the source timeline.

    factor > 1 = faster, < 1 = slow-mo. Audio (when kept) is retimed with atempo so it
    stays in sync with the video. Returns a ``filter_complex`` ending in ``[v]`` (and
    ``[a]`` when audio=True). Segments should be in order; gaps play at normal speed is
    the caller's concern - pass contiguous segments for a clean ramp.
    """
    segs = [(float(a), float(b), float(f)) for a, b, f in segments if float(b) > float(a)]
    if not segs:
        raise ValueError("ramp_speed needs at least one (start,end,factor) segment")
    chains, vlabels, alabels = [], [], []
    for i, (a, b, f) in enumerate(segs):
        f = max(0.05, f)
        chains.append("[0:v]trim=start=%s:end=%s,setpts=(PTS-STARTPTS)/%s,fps=%d[v%d]"
                      % (a, b, f, int(fps), i))
        vlabels.append("[v%d]" % i)
        if audio:
            chains.append("[0:a]atrim=start=%s:end=%s,asetpts=PTS-STARTPTS,%s[a%d]"
                          % (a, b, _atempo_chain(f), i))
            alabels.append("[a%d]" % i)
    n = len(segs)
    chains.append("%sconcat=n=%d:v=1:a=0[v]" % ("".join(vlabels), n))
    if audio:
        chains.append("%sconcat=n=%d:v=0:a=1[a]" % ("".join(alabels), n))
    return ";".join(chains)


# --------------------------------------------------------------------------- transitions
TRANSITIONS = {
    "crossfade": "fade",
    "whip_pan": "smoothleft",
    "whip_right": "smoothright",
    "dip_to_black": "fadeblack",
    "dip_to_white": "fadewhite",
    "zoom_blur": "zoomin",
    "glitch": "pixelize",
    "dissolve": "dissolve",
    "circle": "circleopen",
    "radial": "radial",
}


def transition(name="crossfade", duration=0.5, offset=0.0):
    """Return splice specs for an xfade/acrossfade transition between two clips.

    {'video': 'xfade=transition=..:duration=..:offset=..', 'audio': 'acrossfade=d=..',
     'name', 'duration'}. `offset` is where (seconds into clip A) the blend starts -
     usually dur(A) - duration. Both clips must share size/fps/pix_fmt/sar (compose or
     the auto-editor's normalise pass guarantees this).
    """
    if name not in TRANSITIONS:
        raise ValueError("unknown transition %r; choose from %s" % (name, sorted(TRANSITIONS)))
    d = max(0.05, float(duration))
    return {
        "name": name,
        "duration": d,
        "video": "xfade=transition=%s:duration=%s:offset=%s" % (TRANSITIONS[name], d, round(float(offset), 4)),
        "audio": "acrossfade=d=%s:c1=tri:c2=tri" % d,
    }


# --------------------------------------------------------------------------- finishing
def glow(in_label, out_label, intensity=0.25):
    """Bloom/glow: screen-blend a blurred copy over the original at low opacity.

    Branches, so it returns a labelled ``filter_complex`` fragment ([in]->[out]).
    """
    k = _clamp(float(intensity), 0.0, 1.0)
    sigma = round(6 + 8 * k, 2)
    op = round(0.18 * k, 4)
    a, b, bl = in_label + "_ga", in_label + "_gb", in_label + "_gbl"
    return ("[%s]split=2[%s][%s];[%s]gblur=sigma=%s[%s];"
            "[%s][%s]blend=all_mode=screen:all_opacity=%s[%s]"
            % (in_label, a, b, b, sigma, bl, a, bl, op, out_label))


def _finishing_linear(opts):
    """Build the comma-joinable part of the finishing pass (everything but glow)."""
    k = _clamp(float(opts.get("intensity", 0.5)), 0.0, 1.0)
    parts = []

    if opts.get("chroma"):               # chromatic-aberration-lite: split R/B by a pixel
        d = int(round(1 + 1 * k * float(opts.get("chroma", 1) if opts["chroma"] is not True else 1)))
        d = max(1, min(3, d))
        parts.append("rgbashift=rh=%d:bh=-%d" % (d, d))

    if opts.get("shake"):                # gentle camera shake inside a symmetric pixel margin
        amp01 = _clamp(float(opts["shake"]) if opts["shake"] is not True else 1.0, 0.0, 1.0)
        M = int(round(amp01 * 12)) + 2   # margin px per side; crop stays within it -> no black edges
        freq = float(opts.get("shake_freq", 5.5))
        gate = "1"
        acc = _norm_accents(opts.get("accents"))
        if acc:                          # only shake around big accents
            g = None
            for t, s in acc:
                pulse = "%s*exp(0-(t-%s)/0.18)*gte(t,%s)" % (round(s, 4), t, t)
                g = pulse if g is None else "max(%s,%s)" % (g, pulse)
            gate = "min(1,%s)" % g
        # pad by M on all sides, then crop back to the ORIGINAL size at a moving offset in [0,2M].
        parts.append("pad=iw+%d:ih+%d:%d:%d:color=black" % (2 * M, 2 * M, M, M))
        parts.append(
            "crop=iw-%d:ih-%d:"
            "x='%d+%d*%s*sin(2*PI*%s*t)':"
            "y='%d+%d*%s*cos(2*PI*%s*1.3*t)'"
            % (2 * M, 2 * M, M, M, gate, freq, M, M, gate, freq))

    if opts.get("vignette"):             # soft corner falloff
        ang = round(math.pi / 5 * (0.6 + 0.5 * k), 4)
        parts.append("vignette=angle=%s" % ang)

    if opts.get("grain"):                # fine film grain, temporal so it shimmers lightly
        a = int(round(_clamp(float(opts["grain"]) if opts["grain"] is not True else 1.0, 0.0, 1.0) * 10 + 2))
        parts.append("noise=alls=%d:allf=t+u" % a)

    return ",".join(parts)


def finishing(options, in_label="0:v", out_label="fin"):
    """Finishing layer: grain, vignette, chroma-lite, bloom/glow, gentle shake.

    `options` is a dict; keys toggle effects (truthy), ``intensity`` scales the look:
        {"grain":0.5, "vignette":True, "chroma":True, "glow":0.25, "shake":0.6,
         "accents":[...], "intensity":0.5}
    Returns a labelled ``filter_complex`` fragment ([in_label] -> [out_label]).
    """
    options = dict(options or {})
    stages = []
    lin = _finishing_linear(options)
    if lin:
        stages.append(("lin", lin))
    if options.get("glow"):
        g = options["glow"]
        stages.append(("glow", 0.25 if g is True else float(g)))
    if not stages:
        return "[%s]null[%s]" % (in_label, out_label)

    frags, cur = [], in_label
    for i, (kind, payload) in enumerate(stages):
        nxt = out_label if i == len(stages) - 1 else "%s_s%d" % (out_label, i)
        if kind == "lin":
            frags.append("[%s]%s[%s]" % (cur, payload, nxt))
        else:
            frags.append(glow(cur, nxt, payload))
        cur = nxt
    return ";".join(frags)


# --------------------------------------------------------------------------- compose
def compose(options=None):
    """Chain grade + punch-zoom + finishing into one validated ``filter_complex``.

    Normalises to fps=30, yuv420p and ends at label ``[vout]``.
    options (all optional):
        size            (W,H)   target frame, default (1920,1080)
        fps             int     default 30
        grade           name    e.g. "teal_orange"; None to skip
        grade_intensity 0..1    default 0.85
        accents         list    seconds / (sec,strength) for punch & shake
        punch           bool/dict  enable punch-zoom (dict: strength,tau)
        finishing       dict    see finishing(); None/empty to skip
    """
    o = dict(options or {})
    W, H = o.get("size", (1920, 1080))
    W, H = int(W) // 2 * 2, int(H) // 2 * 2
    fps = int(o.get("fps", FPS))
    accents = o.get("accents", [])

    # Stage 0: all linear ops fold into one comma chain off [0:v].
    lin = ["scale=%d:%d:force_original_aspect_ratio=decrease" % (W, H),
           "pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (W, H),
           "setsar=1", "fps=%d" % fps, "format=%s" % PIX]
    if o.get("grade"):
        g = grade(o["grade"], o.get("grade_intensity", 0.85))
        if g != "null":
            lin.append(g)
    punch = o.get("punch")
    if punch and accents:
        pk = punch if isinstance(punch, dict) else {}
        lin.append(punch_zoom(accents, fps=fps, size=(W, H),
                              strength=pk.get("strength", 0.06), tau=pk.get("tau", 0.16)))

    frags = ["[0:v]%s[cg]" % ",".join(lin)]
    cur = "cg"

    fin = o.get("finishing")
    if fin:
        fin = dict(fin)
        fin.setdefault("accents", accents)
        frags.append(finishing(fin, in_label=cur, out_label="fin"))
        cur = "fin"

    frags.append("[%s]format=%s[vout]" % (cur, PIX))   # guarantee final pixfmt + label
    return ";".join(frags)


# --------------------------------------------------------------------------- ffmpeg runners
def probe(path):
    """Return {width,height,fps,pix_fmt,duration,has_audio} via ffprobe."""
    p = _run([FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    data = json.loads(p.stdout)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    has_a = any(s["codec_type"] == "audio" for s in data["streams"])
    num, den = (v.get("r_frame_rate", "0/1").split("/") + ["1"])[:2]
    fps = round(float(num) / float(den), 3) if float(den or 1) else 0.0
    return {
        "width": int(v.get("width", 0)), "height": int(v.get("height", 0)),
        "fps": fps, "pix_fmt": v.get("pix_fmt", ""),
        "duration": float(data["format"].get("duration", 0.0)), "has_audio": has_a,
    }


_VENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", PIX]
_AENC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]


def make_test_clip(out, seconds=6, size=(1920, 1080), hz=220):
    """Synthesize a testsrc2 clip with a sine tone (for self-test / demos)."""
    W, H = size
    _run([FFMPEG, "-y", "-hide_banner",
          "-f", "lavfi", "-i", "testsrc2=size=%dx%d:rate=30:duration=%s" % (W, H, seconds),
          "-f", "lavfi", "-i", "sine=frequency=%s:sample_rate=48000:duration=%s" % (hz, seconds),
          "-map", "0:v", "-map", "1:a"] + _VENC + _AENC + ["-t", str(seconds), out])
    return out


def render_clip(src, out, options=None, audio=True):
    """Render a single clip through compose(options). Returns `out`."""
    graph = compose(options)
    info = probe(src)
    args = [FFMPEG, "-y", "-hide_banner", "-i", src, "-filter_complex", graph, "-map", "[vout]"]
    if audio and info["has_audio"]:
        args += ["-map", "0:a"]
    _run(args + _VENC + (_AENC if audio and info["has_audio"] else ["-an"])
         + ["-movflags", "+faststart", out])
    return out


def crossfade_clips(a, b, out, name="crossfade", duration=0.5, size=(1920, 1080), fps=FPS):
    """Join two clips with an xfade video transition + acrossfade audio. Returns `out`.

    Both clips are normalised (scale/pad/fps/pixfmt) first so xfade stays valid, then the
    offset is computed from clip A's (normalised) duration.
    """
    W, H = int(size[0]) // 2 * 2, int(size[1]) // 2 * 2
    norm = ("scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1,fps=%d,format=%s" % (W, H, W, H, fps, PIX))
    ia, ib = probe(a), probe(b)
    offset = max(0.0, ia["duration"] - duration)
    spec = transition(name, duration, offset)
    both_audio = ia["has_audio"] and ib["has_audio"]

    graph = ("[0:v]%s[v0];[1:v]%s[v1];[v0][v1]%s,format=%s[vout]"
             % (norm, norm, spec["video"], PIX))
    args = [FFMPEG, "-y", "-hide_banner", "-i", a, "-i", b]
    if both_audio:
        graph += ";[0:a][1:a]%s[aout]" % spec["audio"]
    args += ["-filter_complex", graph, "-map", "[vout]"]
    if both_audio:
        args += ["-map", "[aout]"]
    _run(args + _VENC + (_AENC if both_audio else ["-an"]) + ["-movflags", "+faststart", out])
    return out


# --------------------------------------------------------------------------- self-test
def _selftest():
    here = os.path.dirname(os.path.abspath(__file__))
    outdir = os.path.join(here, "_fx_demo")
    os.makedirs(outdir, exist_ok=True)
    print("fx_engine self-test -> %s" % outdir)

    a = make_test_clip(os.path.join(outdir, "src_a.mp4"), seconds=6, hz=220)
    b = make_test_clip(os.path.join(outdir, "src_b.mp4"), seconds=6, hz=330)
    print("  test clips:", probe(a), probe(b))

    accents = [1.0, 2.0, 3.0, 4.0, 5.0]
    examples = [
        ("example1_teal_orange", {"grade": "teal_orange", "accents": accents, "punch": True,
                                   "finishing": {"grain": 0.4, "vignette": True, "glow": 0.22,
                                                 "chroma": True, "intensity": 0.5}}),
        ("example2_warm_film", {"grade": "warm_film", "accents": accents,
                                 "punch": {"strength": 0.05},
                                 "finishing": {"grain": 0.5, "vignette": True, "intensity": 0.6}}),
        ("example3_cold_punch", {"grade": "cold_cinematic", "accents": [(2.0, 1.0), (4.0, 0.7)],
                                  "punch": {"strength": 0.08},
                                  "finishing": {"glow": 0.3, "shake": 0.6, "accents": [2.0, 4.0],
                                                "vignette": True, "intensity": 0.5}}),
    ]
    results = []
    for nm, opts in examples:
        graph = compose(opts)
        outp = os.path.join(outdir, nm + ".mp4")
        render_clip(a, outp, opts)
        results.append((nm, outp, probe(outp), graph))

    # Transition between a graded clip and clip B.
    xf = os.path.join(outdir, "example4_transition.mp4")
    graded = render_clip(a, os.path.join(outdir, "_graded.mp4"),
                         {"grade": "punch", "finishing": {"vignette": True, "intensity": 0.5}})
    crossfade_clips(graded, b, xf, name="whip_pan", duration=0.6)
    results.append(("example4_transition(whip_pan)", xf, probe(xf),
                    transition("whip_pan", 0.6)["video"]))

    # Speed-ramp demo (slow-mo middle).
    rs = os.path.join(outdir, "example5_speedramp.mp4")
    graph = ramp_speed([(0, 2, 1.0), (2, 4, 0.5), (4, 6, 1.6)])
    _run([FFMPEG, "-y", "-hide_banner", "-i", a, "-filter_complex",
          graph + ";[v]fps=30,format=%s[vout]" % PIX, "-map", "[vout]", "-map", "[a]"]
         + _VENC + _AENC + [rs])
    results.append(("example5_speedramp", rs, probe(rs), graph))

    print("\n=== RESULTS ===")
    ok = True
    for nm, outp, info, graph in results:
        good = info["width"] == 1920 and info["height"] == 1080 and info["pix_fmt"] == PIX and abs(info["fps"] - 30) < 0.5
        ok = ok and good
        print("\n[%s] %s" % ("OK" if good else "BAD", nm))
        print("  file : %s" % outp)
        print("  probe: %dx%d  %sfps  %s  %.2fs  audio=%s"
              % (info["width"], info["height"], info["fps"], info["pix_fmt"],
                 info["duration"], info["has_audio"]))
        print("  graph: %s" % graph)
    print("\nSELF-TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
