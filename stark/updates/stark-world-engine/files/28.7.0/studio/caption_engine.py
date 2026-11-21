"""
caption_engine.py  --  Broadcast-quality KINETIC captions & titles for Stark World Engine.

100% local. No network, no paid cloud APIs, no pip installs. Everything is produced
as libass-compatible ASS subtitle files (or an ffmpeg drawtext/subtitles filter
string) and burned in with ffmpeg / ffprobe, which must be on PATH.

The look: animated word-by-word captions, emphasis pops, clean lower-thirds, title
cards and end cards -- the kind of kinetic typography premium creators ship, but
readable and tasteful rather than cluttered.

Public API (all importable, no side effects on import):

    srt_to_ass(srt_path, style)              -> path to a styled .ass file
    word_level(words_with_times, style)      -> path to a word-by-word pop-on .ass
    title_card(text, subtitle, seconds, style)-> path to an animated title .ass
    lower_third(name, role, start, dur, ...) -> path to an animated name/role .ass
    end_card(lines, seconds, ...)            -> path to a subscribe/outro .ass
    burn(video_in, ass_or_srt, video_out, ...)-> video_out (runs ffmpeg)
    filter_string(ass_or_srt, w, h, ...)     -> the -vf string (for filter_complex)

A "style" is either a preset name string or a dict:
    {'preset': 'bold_pop'|'clean_lower'|'hype', 'orientation': '16:9'|'9:16',
     'font': 'Arial', 'accent': 'FFD23F', ...}

Presets:
    'bold_pop'    big bold centered captions, thick outline + shadow, each line
                  pops in with a quick scale, karaoke highlight sweep synced to timing.
    'clean_lower' tasteful lower-third, subtle fade in/out, no shake.
    'hype'        color-accented keywords + a slight shake on emphasised words.

Orientations are first-class: 16:9 (1920x1080) and 9:16 vertical (1080x1920). In
vertical the captions move to the lower third and scale up.

Fonts: a safe, already-installed Windows sans. Default 'Arial' (Bold weight for the
pop presets). No font is ever downloaded; libass is pointed at C:\\Windows\\Fonts.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

WINDOWS_FONTS_DIR = r"C:\Windows\Fonts"
DEFAULT_FONT = "Arial"            # installed on every Windows box
DEFAULT_ACCENT = "FFD23F"         # warm amber keyword/highlight colour (RRGGBB)
DEFAULT_TEXT = "FFFFFF"           # white body text

ORIENTATIONS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
}

# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #


def _ass_color(rgb: str, alpha: str = "00") -> str:
    """'RRGGBB' -> ASS '&HAABBGGRR' (ASS stores colours B,G,R with alpha first)."""
    rgb = rgb.lstrip("#").strip()
    if len(rgb) != 6:
        rgb = DEFAULT_TEXT
    rr, gg, bb = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"&H{alpha}{bb}{gg}{rr}".upper()


def _cs(seconds: float) -> int:
    """seconds -> centiseconds (ASS \\k and \\t units)."""
    return max(0, int(round(seconds * 100)))


def _ts(seconds: float) -> str:
    """seconds -> ASS timestamp H:MM:SS.cc"""
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    c = int(round((seconds - int(seconds)) * 100))
    if c == 100:        # rounding carry
        c = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _write(text: str, out_path: str | None, suffix: str = ".ass") -> str:
    """Write `text` to out_path (or a fresh temp file) and return the absolute path."""
    if out_path is None:
        fd, out_path = tempfile.mkstemp(suffix=suffix, prefix="capeng_")
        os.close(fd)
    out_path = os.path.abspath(out_path)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return out_path


def _escape_text(s: str) -> str:
    """Escape user text for an ASS Dialogue line (keep our own override braces out)."""
    return s.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


# --------------------------------------------------------------------------- #
# Style resolution
# --------------------------------------------------------------------------- #


class _Style:
    """Resolved render settings for one preset + orientation."""

    def __init__(self, style):
        if isinstance(style, str):
            style = {"preset": style}
        style = dict(style or {})

        self.preset = style.get("preset", "bold_pop")
        self.orientation = style.get("orientation", "16:9")
        if self.orientation not in ORIENTATIONS:
            self.orientation = "16:9"
        self.w, self.h = ORIENTATIONS[self.orientation]
        self.vertical = self.orientation == "9:16"

        self.font = style.get("font", DEFAULT_FONT)
        self.accent = style.get("accent", DEFAULT_ACCENT)
        self.text = style.get("text", DEFAULT_TEXT)

        v = self.vertical
        # Per-preset geometry. Sizes/margins differ for the two orientations so
        # captions stay readable and sit where they should.
        if self.preset == "clean_lower":
            self.fontsize = 66 if v else 52
            self.bold = 0
            self.outline = 2
            self.shadow = 1
            self.align = 2                      # bottom-centre
            self.marginv = 360 if v else 90     # true lower-third
            self.anim = "clean"
            self.karaoke = False
        elif self.preset == "hype":
            self.fontsize = 92 if v else 74
            self.bold = 1
            self.outline = 5
            self.shadow = 3
            self.align = 2
            self.marginv = 520 if v else 150
            self.anim = "hype"
            self.karaoke = False
        else:  # bold_pop (default)
            self.preset = "bold_pop"
            self.fontsize = 94 if v else 76
            self.bold = 1
            self.outline = 6
            self.shadow = 4
            self.align = 2
            self.marginv = 520 if v else 150
            self.anim = "pop"
            self.karaoke = True

        self.marginlr = 90 if not v else 60

    def header(self, style_name: str = "Cap", primary=None, secondary=None) -> str:
        """Full ASS header: [Script Info] + one [V4+ Styles] line + [Events] opener."""
        primary = primary or self.text
        # Secondary colour drives the karaoke sweep (un-highlighted words).
        secondary = secondary or self.text
        prim = _ass_color(self.accent if self.karaoke else primary)
        sec = _ass_color(secondary)
        outline_c = _ass_color("000000")
        back_c = _ass_color("000000", "64")
        return (
            "[Script Info]\n"
            "; Generated by caption_engine.py (Stark World Engine) -- local, libass.\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {self.w}\n"
            f"PlayResY: {self.h}\n"
            "WrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\n"
            "YCbCr Matrix: TV.709\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            f"Style: {style_name},{self.font},{self.fontsize},{prim},{sec},"
            f"{outline_c},{back_c},{self.bold},0,0,0,100,100,0,0,1,"
            f"{self.outline},{self.shadow},{self.align},"
            f"{self.marginlr},{self.marginlr},{self.marginv},1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            "Effect, Text\n"
        )


def _dialogue(start: float, end: float, text: str, style_name: str = "Cap",
              layer: int = 0) -> str:
    return (f"Dialogue: {layer},{_ts(start)},{_ts(end)},{style_name},,0,0,0,,"
            f"{text}\n")


# --------------------------------------------------------------------------- #
# Animation builders (inline ASS override tags)
# --------------------------------------------------------------------------- #


def _pop_in(dur: float) -> str:
    """Quick scale pop + fade. Starts small, overshoots, settles."""
    hold = max(120, int(dur * 1000) - 180)
    return (r"{\fad(90,70)\fscx58\fscy58"
            r"\t(0,170,\fscx107\fscy107)"
            r"\t(170,250,\fscx100\fscy100)}")


def _karaoke_run(words, total: float, accent: str, base: str) -> str:
    """Distribute `total` seconds across words by length; emit \\k highlight sweep."""
    weights = [max(1, len(w)) for w in words]
    tot_w = sum(weights) or 1
    out = []
    for w, wt in zip(words, weights):
        k = _cs(total * wt / tot_w)
        out.append(rf"{{\k{k}}}{_escape_text(w)} ")
    return "".join(out).rstrip()


_EMPH_RE = re.compile(r"[A-Za-z0-9']+")


def _is_emphasis(word: str) -> bool:
    core = word.strip(".,!?:;\"'()")
    if not core:
        return False
    if word.endswith("!") or word.endswith("?!"):
        return True
    if core.isupper() and len(core) >= 2:
        return True
    return False


def _hype_line(text: str, accent: str, base: str) -> str:
    """Accent emphasis keywords + a slight shake on the whole line."""
    acc = _ass_color(accent)
    wht = _ass_color(base)
    parts = []
    for tok in text.split(" "):
        if not tok:
            continue
        if _is_emphasis(tok):
            parts.append(rf"{{\c{acc}}}{_escape_text(tok)}{{\c{wht}}}")
        else:
            parts.append(_escape_text(tok))
    body = " ".join(parts)
    shake = (r"{\fad(80,80)\t(0,70,\frz2.5)\t(70,150,\frz-2.5)"
             r"\t(150,230,\frz1.3)\t(230,300,\frz0)}")
    return shake + body


# --------------------------------------------------------------------------- #
# SRT parsing
# --------------------------------------------------------------------------- #

_SRT_TIME = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")


def _srt_seconds(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / (10 ** len(ms))


def _parse_srt(path: str):
    """Return [(start, end, 'single line text'), ...]."""
    with open(path, "r", encoding="utf-8-sig") as fh:
        raw = fh.read()
    blocks = re.split(r"\n\s*\n", raw.strip())
    cues = []
    for blk in blocks:
        lines = [ln for ln in blk.splitlines() if ln.strip() != ""]
        if not lines:
            continue
        tline = None
        tidx = 0
        for i, ln in enumerate(lines):
            m = _SRT_TIME.search(ln)
            if m:
                tline = m
                tidx = i
                break
        if not tline:
            continue
        start = _srt_seconds(*tline.group(1, 2, 3, 4))
        end = _srt_seconds(*tline.group(5, 6, 7, 8))
        text = " ".join(lines[tidx + 1:]).strip()
        if text:
            cues.append((start, end, text))
    return cues


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def srt_to_ass(srt_path: str, style="bold_pop", out_path: str | None = None) -> str:
    """Convert a standard .srt into a styled, animated .ass subtitle.

    `style` is a preset name or a style dict (see module docstring). Returns the
    absolute path of the written .ass file.
    """
    st = _Style(style)
    cues = _parse_srt(srt_path)
    body = [st.header()]
    for start, end, text in cues:
        dur = max(0.2, end - start)
        text = re.sub(r"\s+", " ", text).strip()
        if st.anim == "pop":
            words = text.split(" ")
            line = _pop_in(dur) + _karaoke_run(words, dur, st.accent, st.text)
        elif st.anim == "hype":
            line = _hype_line(text, st.accent, st.text)
        else:  # clean
            line = r"{\fad(240,240)}" + _escape_text(text)
        body.append(_dialogue(start, end, line))
    return _write("".join(body), out_path)


def word_level(words_with_times, style="bold_pop", out_path: str | None = None,
               chunk: int = 3) -> str:
    """Build word-by-word pop-on captions from [(word, start, end), ...].

    A few words sit on screen at once (``chunk`` per group); the current word is
    emphasised via a karaoke highlight sweep synced to each word's timing, and the
    group pops in. If a tuple's end <= start (line-level timing only), timing is
    distributed evenly across the words in that group. Returns the .ass path.
    """
    st = _Style(style)
    # Normalise & repair timings.
    words = []
    for item in words_with_times:
        w, s, e = item[0], float(item[1]), float(item[2])
        words.append([str(w), s, e])
    # Fix any non-increasing spans by borrowing from neighbours / even split.
    for i, trip in enumerate(words):
        if trip[2] <= trip[1]:
            nxt = words[i + 1][1] if i + 1 < len(words) else trip[1] + 0.3
            trip[2] = max(trip[1] + 0.12, nxt)

    body = [st.header()]
    i = 0
    n = len(words)
    while i < n:
        grp = words[i:i + chunk]
        g_start = grp[0][1]
        g_end = grp[-1][2]
        dur = max(0.2, g_end - g_start)
        acc = _ass_color(st.accent)
        wht = _ass_color(st.text)
        # Karaoke: each word highlights across its own duration; pending words
        # held in secondary (white), highlighted word in accent.
        segs = [_pop_in(dur)]
        prev_end = g_start
        for (w, s, e) in grp:
            gap = max(0.0, s - prev_end)
            if gap > 0.01:
                segs.append(rf"{{\k{_cs(gap)}}}")  # lead-in silence
            segs.append(rf"{{\k{_cs(max(0.06, e - s))}}}{_escape_text(w)} ")
            prev_end = e
        body.append(_dialogue(g_start, g_end, "".join(segs).rstrip(), layer=0))
        i += chunk
    return _write("".join(body), out_path)


def title_card(text: str, subtitle: str = "", seconds: float = 3.0,
               style="bold_pop", out_path: str | None = None) -> str:
    """Animated intro / title card: slide + scale + fade in, hold, fade out.

    Returns an .ass path (overlay it on footage, or on a solid/blurred bg).
    """
    st = _Style(style)
    st.align = 5  # centred on screen for a title
    st.marginv = 0
    acc = _ass_color(st.accent)
    cx, cy = st.w // 2, st.h // 2
    fin, fout = 400, 500
    hold_ms = max(400, int(seconds * 1000) - fin - fout)
    # Title: rise + scale-in.
    t_anim = (rf"{{\an5\pos({cx},{cy})\fad({fin},{fout})"
              rf"\fscx70\fscy70\t(0,{fin},\fscx100\fscy100)"
              rf"\t(0,{fin},\frz0)}}")
    body = [st.header(primary=st.text)]
    body.append(_dialogue(0.0, seconds, t_anim + _escape_text(text)))
    if subtitle:
        sub_size = int(st.fontsize * 0.5)
        sy = cy + int(st.fontsize * 0.85)
        s_anim = (rf"{{\an5\pos({cx},{sy})\fs{sub_size}\c{acc}"
                  rf"\fad({fin + 150},{fout})"
                  rf"\alpha&HFF&\t({fin // 2},{fin + 150},\alpha&H00&)}}")
        body.append(_dialogue(0.0, seconds, s_anim + _escape_text(subtitle)))
    return _write("".join(body), out_path)


def lower_third(name: str, role: str = "", start: float = 0.0, dur: float = 4.0,
                style="clean_lower", out_path: str | None = None) -> str:
    """Animated name/role lower-third tag (slide in from the left, fade out).

    Returns the .ass path. Sits bottom-left; sizes adapt to orientation.
    """
    st = _Style(style)
    end = start + dur
    x = 90
    base_y = st.h - (520 if st.vertical else 170)
    name_size = int(st.fontsize * (1.05 if not st.vertical else 1.0))
    role_size = int(name_size * 0.6)
    acc = _ass_color(st.accent)
    wht = _ass_color(st.text)
    x_off = x - 120
    body = [st.header()]
    # Name: slide in from the left + fade.
    n_anim = (rf"{{\an1\pos({x},{base_y})\fs{name_size}\b1\c{wht}"
              rf"\fad(300,300)\t(0,260,\frz0)"
              rf"\move({x_off},{base_y},{x},{base_y},0,260)}}")
    body.append(_dialogue(start, end, n_anim + _escape_text(name)))
    if role:
        ry = base_y + int(role_size * 1.25)
        # bold + a solid dark outline/shadow so the accent line stays readable over bright footage
        r_anim = (rf"{{\an1\pos({x},{ry})\fs{role_size}\b1\c{acc}\3c&H000000&\4c&H000000&\bord4\shad3"
                  rf"\fad(450,300)\alpha&HFF&\t(150,420,\alpha&H00&)}}")
        body.append(_dialogue(start, end, r_anim + _escape_text(role)))
    return _write("".join(body), out_path)


def end_card(lines, seconds: float = 4.0, style="bold_pop",
             out_path: str | None = None) -> str:
    """Subscribe / outro card: stacked text lines, staggered fade/scale in.

    `lines` is a list of strings (first line is treated as the headline). Text
    only -- no logos. Returns the .ass path.
    """
    st = _Style(style)
    st.align = 5
    lines = [str(l) for l in lines if str(l).strip()]
    n = max(1, len(lines))
    cx = st.w // 2
    acc = _ass_color(st.accent)
    wht = _ass_color(st.text)
    body = [st.header()]
    line_h = int(st.fontsize * 1.35)
    block_top = st.h // 2 - (n - 1) * line_h // 2
    for idx, ln in enumerate(lines):
        y = block_top + idx * line_h
        headline = idx == 0
        size = st.fontsize if headline else int(st.fontsize * 0.62)
        col = wht if headline else acc
        delay = int(idx * 140)
        anim = (rf"{{\an5\pos({cx},{y})\fs{size}\c{col}"
                rf"\alpha&HFF&\fscx60\fscy60"
                rf"\t({delay},{delay + 220},\alpha&H00&\fscx100\fscy100)"
                rf"\fad(0,400)}}")
        body.append(_dialogue(0.0, seconds, anim + _escape_text(ln)))
    return _write("".join(body), out_path)


# --------------------------------------------------------------------------- #
# Burn-in / filter string
# --------------------------------------------------------------------------- #


def _ff_filter_path(path: str) -> str:
    """Escape a path for use inside an ffmpeg filter option value (quoted)."""
    p = os.path.abspath(path).replace("\\", "/")
    p = p.replace(":", r"\:").replace("'", r"\'")
    return f"'{p}'"


def filter_string(ass_or_srt: str, w: int = 1920, h: int = 1080,
                  fonts_dir: str = WINDOWS_FONTS_DIR,
                  force_style: str | None = None,
                  scale: bool = True) -> str:
    """Return the ``-vf`` filter string that scales to WxH, burns the subtitles,
    and outputs yuv420p. The lead can splice this into a larger filter_complex
    (drop the leading scale by passing scale=False).

    .ass -> uses the ass filter (keeps every override tag). .srt -> subtitles
    filter with optional force_style.
    """
    ext = os.path.splitext(ass_or_srt)[1].lower()
    fp = _ff_filter_path(ass_or_srt)
    fd = _ff_filter_path(fonts_dir)
    if ext == ".ass":
        sub = f"ass=filename={fp}:fontsdir={fd}"
    else:
        sub = f"subtitles=filename={fp}:fontsdir={fd}"
        if force_style:
            # Escape commas for the force_style sub-value.
            fs = force_style.replace("\\", r"\\").replace(":", r"\:")
            sub += f":force_style='{fs}'"
    parts = []
    if scale:
        parts.append(f"scale={w}:{h}:flags=lanczos")
    parts.append(sub)
    parts.append("format=yuv420p")
    return ",".join(parts)


def burn(video_in: str, ass_or_srt: str, video_out: str,
         w: int = 1920, h: int = 1080, fonts_dir: str = WINDOWS_FONTS_DIR,
         force_style: str | None = None, audio: str = "copy") -> str:
    """Burn subtitles into `video_in`, writing 1080p yuv420p `video_out`, keeping
    audio. Returns `video_out`. Raises RuntimeError with ffmpeg stderr on failure.

    `audio`: 'copy' to keep the source stream, or a codec like 'aac' to re-encode;
    if the source has no audio ffmpeg simply maps none.
    """
    vf = filter_string(ass_or_srt, w, h, fonts_dir, force_style, scale=True)
    cmd = ["ffmpeg", "-y", "-i", os.path.abspath(video_in),
           "-vf", vf,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
           "-preset", "medium"]
    if audio == "copy":
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", audio, "-b:a", "192k"]
    cmd += [os.path.abspath(video_out)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg burn failed:\n" + " ".join(shlex.quote(c) for c in cmd)
            + "\n--- stderr tail ---\n" + proc.stderr[-4000:])
    return os.path.abspath(video_out)


__all__ = [
    "srt_to_ass", "word_level", "title_card", "lower_third", "end_card",
    "burn", "filter_string",
]
