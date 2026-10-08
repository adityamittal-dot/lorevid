"""Rendering: full-frame beat clips with Ken Burns motion, ASS subtitles with word highlighting, procedural SFX,
music bed, and full video rendering for vertical Shorts and 16:9 long videos."""
import glob
import math
import os
import random
import subprocess
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

FPS = 30
W = {"short": 1080, "long": 1920}
H = {"short": 1920, "long": 1080}

REPO_DIR = os.path.abspath(os.path.dirname(__file__))
FONTS_DIR = os.path.join(REPO_DIR, "fonts")
FONT = os.path.join(FONTS_DIR, "Anton-Regular.ttf")

VOICE_FX = (
    "highpass=f=80,"
    "equalizer=f=3000:t=q:w=1.5:g=2.0,"
    "equalizer=f=7000:t=q:w=2.0:g=-2.5,"
    "acompressor=threshold=-18dB:ratio=3:attack=10:release=120"
)


def run(cmd):
    if cmd[0] == "ffmpeg":
        cmd = [cmd[0], "-hide_banner", "-loglevel", "error", *cmd[1:]]
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError("ffmpeg failed:\n" + p.stderr[-2000:])


def _esc(p):
    s = os.path.abspath(p).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'")


def blank_image(out, fmt):
    """Dark gradient frame used only when no image could be found at all."""
    im = Image.new("RGB", (W[fmt], H[fmt]))
    d = ImageDraw.Draw(im)
    for y in range(H[fmt]):
        c = int(10 + 30 * y / H[fmt])
        d.line([(0, y), (W[fmt], y)], fill=(c, c // 2, c + 10))
    im.save(out, "JPEG", quality=90)


def _framed(im, cw, ch):
    """A manga page or portrait still on a wide frame, the way the big analysis channels show pages: the whole
    picture at ~92% height over a blurred, darkened copy of itself, with a soft shadow."""
    bg = im.resize((cw, int(im.height * cw / im.width)) if im.width / im.height < cw / ch else
                   (int(im.width * ch / im.height), ch), Image.LANCZOS)
    bg = bg.crop(((bg.width - cw) // 2, (bg.height - ch) // 2, (bg.width - cw) // 2 + cw, (bg.height - ch) // 2 + ch))
    bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(40))).enhance(0.5)
    fh = int(ch * 0.92)
    fw = min(int(cw * 0.94), int(im.width * fh / im.height))
    fh = int(im.height * fw / im.width)
    fg = im.resize((fw, fh), Image.LANCZOS)
    x, y = (cw - fw) // 2, (ch - fh) // 2
    shadow = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(shadow).rectangle((x + 12, y + 16, x + fw + 12, y + fh + 16), fill=170)
    bg.paste((0, 0, 0), (0, 0), shadow.filter(ImageFilter.GaussianBlur(18)))
    bg.paste(fg, (x, y))
    return bg


def _card_filter(card, n):
    """Big keyword card over the first ~1.6 s of a beat ("CHAPTER 1194", "OUMU"): darkened frame, Anton text."""
    text = "".join(c for c in str(card).upper() if c not in "'\\:%,;\"").strip()[:28]
    if not text:
        return ""
    cd = min(1.6, n / FPS)
    size = int(min(170, 1700 / (0.47 * max(1, len(text)))))
    alpha = f"if(lt(t,0.12),t/0.12,if(gt(t,{cd - 0.15:.2f}),max(0,({cd:.2f}-t)/0.15),1))"
    return (f",drawbox=x=0:y=0:w=iw:h=ih:color=black@0.45:t=fill:enable='lt(t,{cd:.2f})',"
            f"drawtext=fontfile='{_esc(FONT)}':text='{text}':fontsize={size}:fontcolor=white:borderw=9:"
            f"bordercolor=black:shadowx=5:shadowy=6:shadowcolor=black@0.7:x=(w-text_w)/2:y=(h-text_h)/2:"
            f"alpha='{alpha}':enable='lt(t,{cd:.2f})'")


def _title_filter(title, n, fade_in, fade_out):
    """Chapter title along the lower quarter, faded in on the chapter's first beat and out on its last."""
    text = "".join(c for c in str(title).upper() if c not in "'\\:%;\"").strip()[:40]
    if not text:
        return ""
    d = n / FPS
    a_in = "min(1,t/0.5)" if fade_in else "1"
    a_out = f"min(1,max(0,({d:.2f}-t)/0.5))" if fade_out else "1"
    return (f",drawtext=fontfile='{_esc(FONT)}':text='{text}':fontsize=72:fontcolor=white:borderw=4:bordercolor=black:"
            f"shadowx=3:shadowy=3:shadowcolor=black@0.8:alpha='{a_in}*{a_out}':x=(w-text_w)/2:y=h*0.75")


def beat_clip(img, frames, out, k, fx="none", tight=False, fmt="short", card=None, title=None, subs=None):
    """One beat: a still that fills the whole frame (content-aware crop, no blurred bars) and moves:
    push-in, pull-out or a slow drift, rotating by k. fx: zoom = punch-in, shake = decaying camera shake, flash = white flash. Exactly `frames` frames.
    tight: a punch-in recut of the same picture (70% of the crop, upper middle) so a line never holds one frame.
    Long videos: portrait pictures (manga pages) are shown whole on a blurred backdrop instead of cropped,
    and `card` puts a big keyword over the first 1.6 s. title = (text, first beat?, last beat?) draws the chapter
    title; long beats also carry the vignette, since long videos are not re-encoded after joining.
    subs = (ass path, start second of this beat in the video): burns the captions in (long videos are joined by
    stream copy, so captions are drawn per beat, with timestamps shifted to the beat's place in the video)."""
    import framing
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    vw, vh = W[fmt], H[fmt]
    n = max(2, int(frames))
    with Image.open(img) as src:
        im = src.convert("RGB")
    canvas = os.path.splitext(out)[0] + ".canvas.jpg"
    scale = 1.5 if fmt == "short" else 1.15               # oversized canvas keeps zoompan smooth (1080p needs less)
    cw, ch = int(vw * scale) // 2 * 2, int(vh * scale) // 2 * 2
    framed = fmt == "long" and im.width / im.height < 1.25 and not tight
    if framed:
        frame = _framed(im, cw, ch)
    else:
        box = framing.crop_box(im, aspect=vw / vh)
        if tight:
            x0, y0, x1, y1 = box
            bw, bh = (x1 - x0) * 0.7, (y1 - y0) * 0.7
            cx, cy = (x0 + x1) / 2, y0 + (y1 - y0) * 0.42
            box = (int(cx - bw / 2), int(max(y0, cy - bh / 2)), int(cx + bw / 2), int(max(y0, cy - bh / 2) + bh))
        frame = im.crop(box).resize((cw, ch), Image.LANCZOS)
    frame.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3)).save(canvas, "JPEG", quality=93)
    if fx == "zoom":                                      # punch in hard on the first frames, then keep creeping
        z = f"if(lt(on,8),1.22-0.12*on/8,1.10+0.05*on/{n})"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif framed:                                          # pages: a gentle push so the panel stays readable
        z, x, y = f"1.0+0.05*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    else:
        z, x, y = [
            (f"1.0+0.10*on/{n}", "iw/2-(iw/zoom/2)", "ih*0.42-(ih/zoom*0.42)"),              # push in
            (f"1.12-0.10*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),                   # pull out
            ("1.10", f"(iw-iw/zoom)*(0.15+0.7*on/{n})", "ih/2-(ih/zoom/2)"),                 # drift across
        ][k % 3]
    post = ""
    if fx == "shake":
        post = (f",scale={int(vw * 1.06) // 2 * 2}:{int(vh * 1.06) // 2 * 2},crop={vw}:{vh}:"
                f"x='(in_w-out_w)/2+22*max(0,1-t/0.35)*sin(2*PI*17*t)':"
                f"y='(in_h-out_h)/2+16*max(0,1-t/0.35)*cos(2*PI*21*t)'")
    elif fx == "flash":
        post = ",fade=t=in:st=0:d=0.18:color=white"
    if fmt == "long":
        post += ",vignette=angle=PI/5"
    if card and os.path.exists(FONT):
        post += _card_filter(card, n)
    if title and os.path.exists(FONT):
        post += _title_filter(title[0], n, title[1], title[2])
    if subs and subs[0] and os.path.exists(subs[0]):
        post += (f",setpts=PTS+{subs[1]:.3f}/TB,subtitles=filename='{_esc(subs[0])}':fontsdir='{_esc(FONTS_DIR)}',"
                 f"setpts=PTS-STARTPTS")
    vf = (f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={vw}x{vh}:fps={FPS},"
          f"eq=contrast=1.05:saturation=1.10{post},format=yuv420p")
    run(["ffmpeg", "-y", "-i", canvas, "-vf", vf, "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18" if fmt == "short" else "20", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an", out])
    try:
        os.remove(canvas)
    except OSError:
        pass


def sfx(kind, out):
    if os.path.exists(out) and os.path.getsize(out) > 100:
        return out
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    if kind == "whoosh":
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anoisesrc=d=0.35:c=pink:r=48000",
            "-af", "bandpass=f=1200:w=800,afade=t=in:d=0.15,afade=t=out:st=0.15:d=0.20,volume=0.35,aformat=channel_layouts=stereo",
            out
        ]
    elif kind == "hit":
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "aevalsrc=sin(2*PI*55*t)*exp(-8*t):s=48000:d=0.6",
            "-f", "lavfi", "-i", "anoisesrc=d=0.08:c=white:r=48000",
            "-filter_complex", (
                "[1:a]afade=t=out:st=0.01:d=0.07,volume=0.25[clk];"
                "[0:a][clk]amix=inputs=2:normalize=0,volume=0.5,aformat=channel_layouts=stereo[a]"
            ),
            "-map", "[a]", out
        ]
    elif kind == "riser":
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anoisesrc=d=1.2:c=pink:r=48000",
            "-f", "lavfi", "-i", "aevalsrc=0.5*sin(2*PI*(150*t+312.5*t*t)):s=48000:d=1.2",
            "-filter_complex", (
                "[0:a]afade=t=in:d=1.0:curve=qsin,afade=t=out:st=1.1:d=0.1,lowpass=f=3500,volume=0.25[n];"
                "[1:a]afade=t=in:d=1.0:curve=qsin,afade=t=out:st=1.1:d=0.1,volume=0.15[s];"
                "[n][s]amix=inputs=2:normalize=0,aformat=channel_layouts=stereo[a]"
            ),
            "-map", "[a]", out
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anoisesrc=d=0.2:c=pink:r=48000",
            "-af", "afade=t=out:st=0.05:d=0.15,volume=0.2,aformat=channel_layouts=stereo",
            out
        ]
    run(cmd)
    return out


def _ass_stamp(sec):
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    cs = int(round((s - int(s)) * 100))
    s_int = int(s)
    if cs >= 100:
        cs -= 100
        s_int += 1
    return f"{h}:{m:02d}:{s_int:02d}.{cs:02d}"


def captions_ass(words, path, fmt, hook_text=None, hook_secs=2.6):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    is_short = fmt == "short"
    rx = 1080 if is_short else 1920
    ry = 1920 if is_short else 1080

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {rx}",
        f"PlayResY: {ry}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    ]

    if is_short:
        lines.append("Style: Default,Anton,116,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8,3,2,40,40,730,1")
        lines.append("Style: Hook,Anton,112,&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,10,0,8,40,40,300,1")
    else:
        lines.append("Style: Default,Anton,66,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,80,80,70,1")

    lines.extend(["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"])

    if is_short and hook_text and hook_secs > 0:
        h_words = hook_text.upper().replace("{", "").replace("}", "").split()
        if len(h_words) > 3:
            mid = (len(h_words) + 1) // 2
            h_text = " ".join(h_words[:mid]) + "\\N" + " ".join(h_words[mid:])
        else:
            h_text = " ".join(h_words)
        lines.append(f"Dialogue: 1,0:00:00.00,{_ass_stamp(hook_secs)},Hook,,0,0,0,,{h_text}")

    if not words:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return path

    if is_short:
        chunks = []
        curr = []
        for w_item in words:
            s, e, text = w_item
            if curr:
                prev_s, prev_e, prev_t = curr[-1]
                gap = s - prev_e
                punct = any(prev_t.endswith(p) for p in [".", "!", "?", ",", ";", ":", "—", "-"])
                if len(curr) >= 2 or gap > 0.25 or punct:
                    chunks.append(curr)
                    curr = []
            curr.append(w_item)
        if curr:
            chunks.append(curr)

        for chunk in chunks:
            for idx, (ws, we, wt) in enumerate(chunk):
                start_str = _ass_stamp(ws)
                if idx < len(chunk) - 1:
                    end_val = max(ws + 0.05, min(chunk[idx + 1][0], we))
                else:
                    end_val = max(ws + 0.05, we)
                end_str = _ass_stamp(end_val)

                txt_parts = []
                for j, (_, _, w_str) in enumerate(chunk):
                    clean = w_str.replace("{", "").replace("}", "").strip()
                    if j == idx:
                        txt_parts.append(r"{\c&H1ED2FF&}" + clean.upper() + r"{\c&HFFFFFF&}")
                    else:
                        txt_parts.append(clean.upper())
                pop = r"{\fscx110\fscy110\t(0,90,\fscx100\fscy100)}" if idx == 0 else ""
                dialogue_text = pop + " ".join(txt_parts)
                lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{dialogue_text}")
    else:
        chunks = []
        curr = []
        for w_item in words:
            s, e, text = w_item
            if curr:
                prev_s, prev_e, prev_t = curr[-1]
                gap = s - prev_e
                punct = any(prev_t.endswith(p) for p in [".", "!", "?", ";", ":"])
                if len(curr) >= 7 or (len(curr) >= 4 and punct) or gap > 0.35:
                    chunks.append(curr)
                    curr = []
            curr.append(w_item)
        if curr:
            chunks.append(curr)

        for chunk in chunks:
            start_str = _ass_stamp(chunk[0][0])
            end_str = _ass_stamp(max(chunk[0][0] + 0.05, chunk[-1][1]))
            sentence = " ".join(w[2].replace("{", "").replace("}", "").strip().upper() for w in chunk)
            lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{sentence}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def render(clips, segs, narration_wav, out, fmt, ass=None, music=None, sfx_events=(), chapter_marks=(), music_leveled=False):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    temp_dir = os.path.join(os.path.dirname(os.path.abspath(out)), f"_tmp_{os.path.basename(out)}")
    os.makedirs(temp_dir, exist_ok=True)
    total_dur = max(0.1, float(sum(segs)))

    # hard cuts for both formats: the top channels cut every 1-1.5 s, and crossfades at that pace read as mush
    list_file = os.path.join(temp_dir, "clips.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for c in clips:
            f.write(f"file '{os.path.abspath(c)}'\n")
    joined_v = os.path.join(temp_dir, "joined.mp4")
    try:
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", joined_v])
    except Exception:
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", joined_v])

    # Long videos: grade, vignette and chapter titles are already baked into each beat clip (rendered in parallel),
    # so the joined video is stream-copied; re-encoding 15 minutes of 1080p a second time took longer than the video.
    # Shorts are re-encoded once to burn in the word-by-word captions across clips.
    fc_parts = []
    if fmt == "short":
        vfilters = ["noise=alls=4:allf=t,vignette=angle=PI/5,eq=contrast=1.04:saturation=1.02"]
        if ass and os.path.exists(ass):
            vfilters.append(f"subtitles=filename='{_esc(ass)}':fontsdir='{_esc(FONTS_DIR)}'")
        fc_parts.append(f"[0:v]{','.join(vfilters)},trim=0:{total_dur:.3f},setpts=PTS-STARTPTS[vout]")

    cmd = ["ffmpeg", "-y", "-i", joined_v, "-i", narration_wav]
    next_idx = 2

    tracks_to_mix = []
    has_music = bool(music and os.path.exists(music))
    if has_music:
        cmd.extend(["-stream_loop", "-1", "-i", music])
        music_idx = next_idx
        next_idx += 1
        fc_parts.append(f"[1:a]asplit=2[narr_main][narr_sc]")
        if music_leveled:
            # music.bed() already sits 6-9 dB under the voice and is faded; duck ~4-6 dB under words so the
            # music stays audible in every gap, like the niche's top Shorts (bed 5-8 dB under the voice)
            fc_parts.append(
                f"[{music_idx}:a]anull[m_pre];"
                f"[m_pre][narr_sc]sidechaincompress=threshold=0.06:ratio=2.5:attack=30:release=350:makeup=1[m_ducked]"
            )
        else:
            m_vol = 0.12 if fmt == "short" else 0.08
            fade_out_st = max(0.0, total_dur - 2.5)
            fc_parts.append(
                f"[{music_idx}:a]volume={m_vol},afade=t=in:d=1.5,afade=t=out:st={fade_out_st:.2f}:d=2.0[m_pre];"
                f"[m_pre][narr_sc]sidechaincompress=threshold=0.03:ratio=4:attack=50:release=400[m_ducked]"
            )
        tracks_to_mix.append("[narr_main]")
        tracks_to_mix.append("[m_ducked]")
    else:
        tracks_to_mix.append("[1:a]")

    for idx, (s_time, s_path, s_vol) in enumerate(sfx_events):
        if os.path.exists(s_path) and s_time < total_dur:
            cmd.extend(["-i", s_path])
            delay_ms = max(0, int(round(s_time * 1000)))
            fc_parts.append(
                f"[{next_idx}:a]volume={s_vol:.2f},adelay={delay_ms}|{delay_ms},aformat=channel_layouts=stereo[sfx_{idx}]"
            )
            tracks_to_mix.append(f"[sfx_{idx}]")
            next_idx += 1

    target_i = -14 if fmt == "short" else -16
    if len(tracks_to_mix) > 1:
        mix_inputs = "".join(tracks_to_mix)
        fc_parts.append(f"{mix_inputs}amix=inputs={len(tracks_to_mix)}:duration=first:normalize=0[amix]")
        fc_parts.append(f"[amix]loudnorm=I={target_i}:TP=-1.5,aresample=48000,atrim=0:{total_dur:.3f},asetpts=PTS-STARTPTS[aout]")
    else:
        fc_parts.append(f"{tracks_to_mix[0]}loudnorm=I={target_i}:TP=-1.5,aresample=48000,atrim=0:{total_dur:.3f},asetpts=PTS-STARTPTS[aout]")

    video_out = (["-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                  "-pix_fmt", "yuv420p"] if fmt == "short" else ["-map", "0:v", "-map", "[aout]", "-c:v", "copy"])
    cmd.extend([
        "-filter_complex", ";".join(fc_parts),
        *video_out,
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out
    ])
    run(cmd)

    for item in glob.glob(os.path.join(temp_dir, "*")):
        try:
            os.remove(item)
        except Exception:
            pass
    try:
        os.rmdir(temp_dir)
    except Exception:
        pass


def pad_audio(wav, seconds, out):
    run([
        "ffmpeg", "-y", "-i", wav,
        "-af", f"{VOICE_FX},apad=whole_dur={seconds:.3f},aresample=48000",
        "-ac", "2", out
    ])


def concat_audio(wavs, out):
    lst = out + ".concat.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for w in wavs:
            f.write(f"file '{os.path.abspath(w)}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "pcm_s16le", out])
    if os.path.exists(lst):
        os.remove(lst)


def ambient_pad(out, mood="calm", seconds=900):
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return out
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    roots = {
        "hype": 130.81,
        "suspense": 92.50,
        "emotional": 87.31,
        "epic": 82.41,
        "chill": 110.0,
        "calm": 110.0,
        "warm": 98.0,
    }
    r = roots.get(mood, 110.0)
    third = 1.189 if mood in ("suspense", "emotional", "epic") else 1.26
    tones = [r, r * third, r * 1.498, r * 2.0, r * 2.0 * third]
    expr_parts = []
    for k, freq in enumerate(tones):
        amp = 0.16 / (k + 1)
        mod_rate = 0.03 + 0.012 * k
        expr_parts.append(f"{amp:.3f}*sin(2*PI*{freq:.2f}*t)*(0.6+0.4*sin(2*PI*{mod_rate:.3f}*t))")
    expr = "+".join(expr_parts)
    dur = max(10, int(seconds))
    fc = (
        "[0:a]lowpass=f=1800,aecho=0.8:0.85:500|1000:0.3|0.2[p];"
        "[1:a]lowpass=f=450,volume=0.03[n];"
        "[p][n]amix=inputs=2:normalize=0,volume=0.75,aformat=channel_layouts=stereo[a]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={dur}",
        "-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude=0.02:d={dur}:r=48000",
        "-filter_complex", fc,
        "-map", "[a]",
        out
    ]
    run(cmd)
    return out


def music_bed(mood, work, seconds):
    candidates = []
    for base in [REPO_DIR, "."]:
        candidates.extend(glob.glob(os.path.join(base, "music", mood, "*.mp3")))
    if candidates:
        return random.choice(candidates)
    for base in [REPO_DIR, "."]:
        candidates.extend(glob.glob(os.path.join(base, "music", "*", "*.mp3")))
        candidates.extend(glob.glob(os.path.join(base, "music", "*.mp3")))
    if candidates:
        return random.choice(candidates)
    pad_file = os.path.join(work, f"pad_{mood}_{int(seconds)}.wav")
    return ambient_pad(pad_file, mood=mood, seconds=seconds)


def _thumb_part(img, w, h):
    """The most detailed w:h window of a picture, tightened a little toward its upper middle (faces)."""
    import framing
    with Image.open(img) as src:
        im = src.convert("RGB")
    x0, y0, x1, y1 = framing.crop_box(im, aspect=w / h)
    bw, bh = (x1 - x0) * 0.88, (y1 - y0) * 0.88
    cx, cy = (x0 + x1) / 2, y0 + (y1 - y0) * 0.45
    left, top = max(0, min(im.width - bw, cx - bw / 2)), max(0, min(im.height - bh, cy - bh / 2))
    return im.crop((int(left), int(top), int(left + bw), int(top + bh))).resize((w, h), Image.LANCZOS)


SUBJECT_FRAC = 0.62   # the subject fills 55-70% of the frame width; the rest is the "empty third" for text


def _compose_offcenter(im):
    """Place a full-frame crop off-centre: crisp on whichever side holds more picture detail (the subject),
    a blurred/darkened atmospheric extension on the other (the empty third where text goes). Returns
    (canvas, text_side) with text_side "left" or "right"."""
    import framing
    tw, th = im.size
    e, s = framing._energy(im)
    half = e.shape[1] // 2
    subject_side = "left" if e[:, :half].sum() >= e[:, half:].sum() else "right"
    text_side = "right" if subject_side == "left" else "left"

    subj_w = int(tw * SUBJECT_FRAC)
    x0 = 0 if subject_side == "left" else tw - subj_w
    crop = im.crop((x0, 0, x0 + subj_w, th))

    backdrop = ImageEnhance.Brightness(im.filter(ImageFilter.GaussianBlur(30))).enhance(0.55)
    canvas = backdrop.copy()
    feather = max(24, subj_w // 10)
    mask = Image.new("L", (subj_w, th), 255)
    md = ImageDraw.Draw(mask)
    for i in range(feather):                              # feather only the inner edge (toward the empty side)
        a = int(255 * (i / feather))
        if subject_side == "left":
            md.line([(subj_w - feather + i, 0), (subj_w - feather + i, th)], fill=255 - a)
        else:
            md.line([(i, 0), (i, th)], fill=a)
    canvas.paste(crop, (x0, 0), mask)
    return canvas, text_side


def _detail_peak(im):
    """Pixel coordinates of the single most detailed point in an image (framing's edge/colour energy)."""
    import numpy as np
    import framing
    e, s = framing._energy(im)
    y, x = np.unravel_index(int(np.argmax(e)), e.shape)
    return int(x / s), int(y / s)


def _device_circle(im):
    """Red ring + arrow on the most detailed region (the thing the viewer's eye should land on first)."""
    d = ImageDraw.Draw(im)
    cx, cy = _detail_peak(im)
    r = int(min(im.size) * 0.14)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(225, 30, 30), width=10)
    ax, ay = int(im.width * 0.07), int(im.height * 0.93)
    hx, hy = cx - r * 0.7, cy + r * 0.7
    d.line([(ax, ay), (hx, hy)], fill=(225, 30, 30), width=10)
    ang = math.atan2(ay - hy, ax - hx)
    for da in (0.5, -0.5):
        d.line([(hx, hy), (hx + 26 * math.cos(ang + da), hy + 26 * math.sin(ang + da))], fill=(225, 30, 30), width=10)
    return im


def _device_question(im):
    """Big yellow '?' badge in the top corner — a cheap, high-contrast curiosity cue."""
    d = ImageDraw.Draw(im)
    r = int(min(im.size) * 0.12)
    cx, cy = im.width - r - 26, r + 26
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 210, 30), outline=(0, 0, 0), width=6)
    font = ImageFont.truetype(FONT, int(r * 1.3)) if os.path.exists(FONT) else ImageFont.load_default()
    tl = d.textlength("?", font=font)
    d.text((cx - tl / 2, cy - r * 0.8), "?", font=font, fill=(0, 0, 0))
    return im


def _device_blur(im):
    """Blur the most detailed region and stamp a '?' over it — a mystery box instead of a spoiler."""
    cx, cy = _detail_peak(im)
    r = int(min(im.size) * 0.17)
    box = (max(0, cx - r), max(0, cy - r), min(im.width, cx + r), min(im.height, cy + r))
    im.paste(im.crop(box).filter(ImageFilter.GaussianBlur(24)), box)
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(FONT, int(r * 1.1)) if os.path.exists(FONT) else ImageFont.load_default()
    bx, by = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    tl = d.textlength("?", font=font)
    d.text((bx - tl / 2 + 6, by - r * 0.55 + 6), "?", font=font, fill=(0, 0, 0))
    d.text((bx - tl / 2, by - r * 0.55), "?", font=font, fill=(255, 210, 30), stroke_width=6, stroke_fill=(0, 0, 0))
    return im


DEVICES = {"circle": _device_circle, "question": _device_question, "blur": _device_blur}


def thumbnail(img, text, highlight, out, img2=None, device=None):
    """1280x720 thumbnail in the style of the niche's top long videos (GrandLineReview, Facadify, Strawhatists):
    the subject off-centre, filling 55-70% of the frame, with the rest a blurred atmospheric "empty third" for
    0-3 words of text (none at all is normal for What If videos); punchier colour (x1.3 saturation, x1.1
    contrast); a slanted two-character split when img2 is given (or `device="split"`); otherwise an optional
    `device` ("circle": ring + arrow on the busiest detail, "question": a yellow "?" badge, "blur": blur that
    detail and stamp a "?" over it) for extra curiosity without spoiling the payoff."""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tw, th = 1280, 720
    if img2 or device == "split":
        left = _thumb_part(img, 700, th).crop((0, 0, 700, th))
        canvas = Image.new("RGB", (tw, th))
        canvas.paste(left, (0, 0))
        right = _thumb_part(img2 or img, 700, th)
        mask = Image.new("L", (tw, th), 0)
        ImageDraw.Draw(mask).polygon([(680, 0), (tw, 0), (tw, th), (560, th)], fill=255)
        canvas.paste(right, (tw - 700, 0), mask.crop((tw - 700, 0, tw, th)))
        d = ImageDraw.Draw(canvas)
        d.line([(680, 0), (560, th)], fill=(0, 0, 0), width=22)
        d.line([(680, 0), (560, th)], fill=(255, 210, 30), width=8)
        im, text_col = canvas, (0, tw)
    else:
        base = _thumb_part(img, tw, th)
        im, text_side = _compose_offcenter(base)
        subj_w = int(tw * SUBJECT_FRAC)
        text_col = (tw - subj_w, tw) if text_side == "right" else (0, tw - subj_w)

    im = ImageEnhance.Color(im).enhance(1.3)
    im = ImageEnhance.Contrast(im).enhance(1.1)
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=90, threshold=2))
    vig = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(vig).ellipse((-220, -160, tw + 220, th + 160), fill=255)
    im = Image.composite(im, Image.new("RGB", (tw, th), (0, 0, 0)), vig.filter(ImageFilter.GaussianBlur(110)))

    if device in DEVICES:
        im = DEVICES[device](im)

    words = [w for w in str(text or "").upper().split()][:3]
    if words:
        col_x0, col_x1 = text_col
        col_w = col_x1 - col_x0
        grad = Image.new("L", (tw, th), 0)
        gd = ImageDraw.Draw(grad)
        for y in range(th // 2, th):                      # darken the bottom so the words always read
            gd.line([(col_x0, y), (col_x1, y)], fill=int(200 * ((y - th / 2) / (th / 2)) ** 1.6))
        im = Image.composite(Image.new("RGB", (tw, th), (0, 0, 0)), im, grad)
        draw = ImageDraw.Draw(im)
        size = 140
        while size > 56:
            font = ImageFont.truetype(FONT, size) if os.path.exists(FONT) else ImageFont.load_default()
            if draw.textlength(" ".join(words), font=font) <= col_w - 70:
                break
            size -= 6
        hl = {h.strip("?!.,:").upper() for h in str(highlight or "").split()}
        total = draw.textlength(" ".join(words), font=font)
        x, y = col_x0 + (col_w - total) / 2, th - size * 1.18 - 34
        for w in words:
            color = (255, 210, 30) if w.strip("?!.,:") in hl else (255, 255, 255)
            draw.text((x + 6, y + 8), w, font=font, fill=(0, 0, 0))
            draw.text((x, y), w, font=font, fill=color, stroke_width=9, stroke_fill=(0, 0, 0))
            x += draw.textlength(w + " ", font=font)
    im.save(out, "JPEG", quality=95)


if __name__ == "__main__":
    test_dir = "/tmp/lorevid_test"
    os.makedirs(test_dir, exist_ok=True)
    test_img = os.path.join(test_dir, "grad.jpg")

    im = Image.new("RGB", (1080, 1920), (20, 25, 45))
    d = ImageDraw.Draw(im)
    for y in range(0, 1920, 4):
        d.line([(0, y), (1080, y)], fill=(int(20 + 160 * y / 1920), int(25 + 60 * y / 1920), int(45 + 120 * y / 1920)))
    d.rectangle([200, 500, 880, 1300], fill=(220, 70, 40))
    im.save(test_img, "JPEG")

    c1 = os.path.join(test_dir, "c1.mp4")
    c2 = os.path.join(test_dir, "c2.mp4")
    beat_clip(test_img, 90, c1, 0, fx="zoom")
    beat_clip(test_img, 90, c2, 1, fx="shake")

    wav = os.path.join(test_dir, "narr.wav")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "aevalsrc=0.15*sin(2*PI*280*t):s=48000:d=6.0", "-ac", "1", wav])

    words = [
        (0.4, 1.2, "LOREVID"),
        (1.2, 2.0, "PIPELINE"),
        (2.0, 2.8, "READY"),
        (3.2, 4.0, "SYSTEM"),
        (4.0, 5.2, "ONLINE"),
    ]
    ass_path = os.path.join(test_dir, "subs.ass")
    captions_ass(words, ass_path, "short", hook_text="SYSTEM TEST", hook_secs=2.5)

    whoosh_wav = os.path.join(test_dir, "whoosh.wav")
    sfx("whoosh", whoosh_wav)

    out_mp4 = "/tmp/lorevid_selftest.mp4"
    render([c1, c2], [3.0, 3.0], wav, out_mp4, fmt="short", ass=ass_path, sfx_events=[(3.0, whoosh_wav, 0.35)])
    print("Rendered:", out_mp4, "Size:", os.path.getsize(out_mp4))
