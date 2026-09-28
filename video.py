"""Rendering: Ken Burns scene clips, ASS subtitles with word highlighting, procedural SFX,
music bed, and full video rendering for vertical Shorts and 16:9 long videos."""
import glob
import math
import os
import random
import subprocess
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

FPS = 30
XF = 0.35                     # crossfade length between shots in long videos
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


def shot_clip(img, seconds, out, i, fmt, fx):
    """Still image -> moving clip of exactly round(seconds*FPS) frames. Nothing important is cropped away:
    Short + landscape image: a tall slice that pans across the whole picture over a blurred copy of itself;
    otherwise the image fits a box and gets a gentle push-in / pull-out / drift (alternating by i).
    fx: zoom = fast punch-in, shake = decaying camera shake, flash = white flash; all in the first frames."""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    vw, vh = W[fmt], H[fmt]
    n = max(2, int(round(seconds * FPS)))
    try:
        with Image.open(img) as im:
            iw, ih = im.size
    except Exception:
        iw, ih = vw, vh
    bg = (f"[bg0]scale={vw}:{vh}:force_original_aspect_ratio=increase,crop={vw}:{vh},"
          f"gblur=sigma=30,eq=brightness=-0.2:saturation=0.8[bg]")
    if fmt == "short" and iw / ih > 1.15:
        ph = 1216                                         # pan window 1080x1216 over the image scaled to that height
        pw = max(vw + 2, int(round(iw * ph / ih / 2)) * 2)
        span = pw - vw
        x = f"{span}*(t/{seconds:.3f})" if i % 2 == 0 else f"{span}*(1-t/{seconds:.3f})"
        if fx == "zoom":                                  # start closer, then settle
            fg = (f"[fg0]scale={pw}:{ph},crop={vw}:{ph}:x='{x}':y=0,"
                  f"scale=w='{vw}*(1+0.12*max(0,1-t/0.3))':h=-2:eval=frame,crop={vw}:{ph}[fg]")
        else:
            fg = f"[fg0]scale={pw}:{ph},crop={vw}:{ph}:x='{x}':y=0[fg]"
    else:
        bw, bh = (1080, 1350) if fmt == "short" else (vw, vh)
        f = min(bw / iw, bh / ih)
        fw, fh = max(2, int(iw * f) // 2 * 2), max(2, int(ih * f) // 2 * 2)
        z = 0.07
        if fx == "zoom":
            zexpr = f"if(lt(on,9),1+0.14*(1-(1-on/9)*(1-on/9)),1.14+0.03*(on-9)/{max(1, n - 9)})"
        else:
            zexpr = [f"1+{z}*on/{n}", f"{1 + z}-{z}*on/{n}", f"1.04+0.03*on/{n}"][i % 3]
        xexpr = "iw/2-(iw/zoom/2)" if i % 3 != 2 else f"(iw-iw/zoom)*(0.35+0.3*on/{n})"
        fg = (f"[fg0]trim=end_frame=1,scale={fw * 2}:{fh * 2},"
              f"zoompan=z='{zexpr}':x='{xexpr}':y='ih/2-(ih/zoom/2)':d={n}:s={fw}x{fh}:fps={FPS}[fg]")
    post = ""
    if fx == "shake":
        post = (f",scale={int(vw * 1.06) // 2 * 2}:{int(vh * 1.06) // 2 * 2},crop={vw}:{vh}:"
                f"x='(in_w-out_w)/2+22*max(0,1-t/0.35)*sin(2*PI*17*t)':"
                f"y='(in_h-out_h)/2+16*max(0,1-t/0.35)*cos(2*PI*21*t)'")
    elif fx == "flash":
        post = ",fade=t=in:st=0:d=0.18:color=white"
    fc = (f"[0:v]split[bg0][fg0];{bg};{fg};"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=0{post},fps={FPS},format=yuv420p[v]")
    run(["ffmpeg", "-y", "-loop", "1", "-t", f"{seconds + 0.2:.3f}", "-i", img, "-filter_complex", fc,
         "-map", "[v]", "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-an", out])


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
        lines.append("Style: Default,Anton,104,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,40,40,730,1")
        lines.append("Style: Hook,Anton,112,&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,10,0,8,40,40,300,1")
    else:
        lines.append("Style: Default,Anton,58,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,130,1")

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
                if len(curr) >= 3 or gap > 0.25 or punct:
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


def _join_xfade(paths, seg_lens, out_path, xf=0.35):
    if len(paths) == 1:
        return paths[0]
    inputs = []
    for p in paths:
        inputs.extend(["-i", p])
    f_chain = []
    prev = "[0:v]"
    accum = 0.0
    for k in range(1, len(paths)):
        accum += seg_lens[k - 1]
        lab = f"[v{k}]"
        f_chain.append(f"{prev}[{k}:v]xfade=transition=fade:duration={xf}:offset={accum:.3f}{lab}")
        prev = lab
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(f_chain),
        "-map", prev,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        out_path
    ]
    run(cmd)
    return out_path


def _xfade_chain(clips, segs, chunk_dir, xf=0.35):
    os.makedirs(chunk_dir, exist_ok=True)
    if not clips:
        return ""
    if len(clips) == 1:
        return clips[0]

    size = 20
    parts = []
    part_segs = []
    for c in range(0, len(clips), size):
        ps = clips[c : c + size]
        ss = segs[c : c + size]
        if len(ps) == 1 and len(clips) > size:
            parts.append(ps[0])
            part_segs.append(ss[0])
        else:
            c_out = os.path.join(chunk_dir, f"chunk_{c // size:03d}.mp4")
            parts.append(_join_xfade(ps, ss, c_out, xf=xf))
            part_segs.append(sum(ss))
    if len(parts) == 1:
        return parts[0]
    final_joined = os.path.join(chunk_dir, "xfade_final.mp4")
    return _join_xfade(parts, part_segs, final_joined, xf=xf)


def render(clips, segs, narration_wav, out, fmt, ass=None, music=None, sfx_events=(), chapter_marks=()):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    temp_dir = os.path.join(os.path.dirname(os.path.abspath(out)), f"_tmp_{os.path.basename(out)}")
    os.makedirs(temp_dir, exist_ok=True)
    total_dur = max(0.1, float(sum(segs)))

    if fmt == "short":
        list_file = os.path.join(temp_dir, "clips.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for c in clips:
                f.write(f"file '{os.path.abspath(c)}'\n")
        joined_v = os.path.join(temp_dir, "joined.mp4")
        try:
            run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", joined_v])
        except Exception:
            run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", joined_v])
    else:
        joined_v = _xfade_chain(clips, segs, temp_dir, xf=XF)

    vfilters = []
    if fmt == "long" and chapter_marks and len(chapter_marks) > 1 and os.path.exists(FONT):
        for t0, title in chapter_marks[1:]:
            a = t0 + 0.3
            b = t0 + 4.3
            alpha = f"if(lt(t,{a}+0.5),(t-{a})/0.5,if(gt(t,{b}-0.5),({b}-t)/0.5,1))"
            c_text = title.upper().replace("'", "").replace(":", " - ")
            vfilters.append(
                f"drawtext=fontfile='{_esc(FONT)}':text='{c_text}':fontsize=72:fontcolor=white:"
                f"borderw=4:bordercolor=black:shadowx=3:shadowy=3:shadowcolor=black@0.8:"
                f"alpha='{alpha}':x=(w-text_w)/2:y=h*0.75:enable='between(t,{a:.2f},{b:.2f})'"
            )

    vfilters.append("noise=alls=4:allf=t,vignette=angle=PI/5,eq=contrast=1.04:saturation=1.02")

    if ass and os.path.exists(ass):
        vfilters.append(f"subtitles=filename='{_esc(ass)}':fontsdir='{_esc(FONTS_DIR)}'")

    v_chain = ",".join(vfilters)
    fc_parts = [f"[0:v]{v_chain},trim=0:{total_dur:.3f},setpts=PTS-STARTPTS[vout]"]

    cmd = ["ffmpeg", "-y", "-i", joined_v, "-i", narration_wav]
    next_idx = 2

    tracks_to_mix = []
    has_music = bool(music and os.path.exists(music))
    if has_music:
        cmd.extend(["-stream_loop", "-1", "-i", music])
        music_idx = next_idx
        next_idx += 1
        m_vol = 0.12 if fmt == "short" else 0.08
        fade_out_st = max(0.0, total_dur - 2.5)
        fc_parts.append(f"[1:a]asplit=2[narr_main][narr_sc]")
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
        fc_parts.append(f"[amix]loudnorm=I={target_i}:TP=-1.5,atrim=0:{total_dur:.3f},asetpts=PTS-STARTPTS[aout]")
    else:
        fc_parts.append(f"{tracks_to_mix[0]}loudnorm=I={target_i}:TP=-1.5,atrim=0:{total_dur:.3f},asetpts=PTS-STARTPTS[aout]")

    cmd.extend([
        "-filter_complex", ";".join(fc_parts),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
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


def thumbnail(img, text, highlight, out):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with Image.open(img) as source:
        im = source.convert("RGB")

    scale = max(1280 / im.width, 720 / im.height)
    new_w = int(math.ceil(im.width * scale))
    new_h = int(math.ceil(im.height * scale))
    im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)

    left = max(0, new_w - 1280)
    top = max(0, int((new_h - 720) * (0.08 if im.height > im.width else 0.5)))   # tall art: keep the face
    im = im.crop((left, top, left + 1280, top + 720))

    im = ImageEnhance.Color(im).enhance(1.25)
    im = ImageEnhance.Contrast(im).enhance(1.18)

    grad_w = 780
    mask = Image.new("L", (1280, 720), 0)
    draw_mask = ImageDraw.Draw(mask)
    for x in range(grad_w):
        val = int(230 * ((1.0 - (x / grad_w)) ** 1.3))
        draw_mask.line([(x, 0), (x, 720)], fill=val)
    dark_layer = Image.new("RGB", (1280, 720), (8, 6, 12))
    im = Image.composite(dark_layer, im, mask)

    vig = Image.new("L", (1280, 720), 0)
    ImageDraw.Draw(vig).ellipse((-160, -120, 1440, 840), fill=255)
    im = Image.composite(im, Image.new("RGB", (1280, 720), (0, 0, 0)), vig.filter(ImageFilter.GaussianBlur(100)))

    draw = ImageDraw.Draw(im)
    words = text.upper().split()[:5]
    total_chars = len(" ".join(words))
    size = 140 if total_chars <= 12 else 115 if total_chars <= 20 else 96

    font = None
    if os.path.exists(FONT):
        try:
            font = ImageFont.truetype(FONT, size)
        except Exception:
            pass
    if font is None:
        font = ImageFont.load_default()

    lines = [[]]
    for w in words:
        test_line = " ".join(lines[-1] + [w])
        if lines[-1] and draw.textlength(test_line, font=font) > 720:
            lines.append([w])
        else:
            lines[-1].append(w)

    hl_targets = {h.strip("?!.,:").upper() for h in highlight.split()} if highlight else set()
    if not hl_targets and words:
        hl_targets = {words[-1].strip("?!.,:")}

    line_h = int(size * 1.08)
    total_h = len(lines) * line_h
    start_y = max(40, (720 - total_h) // 2)

    y = start_y
    for line in lines:
        x = 55
        for w in line:
            clean_w = w.strip("?!.,:")
            is_hl = clean_w in hl_targets
            color = (255, 210, 30) if is_hl else (255, 255, 255)

            draw.text((x + 6, y + 8), w, font=font, fill=(0, 0, 0))
            draw.text((x, y), w, font=font, fill=color, stroke_width=8, stroke_fill=(0, 0, 0))

            x += draw.textlength(w + " ", font=font)
        y += line_h

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
    shot_clip(test_img, 3.0, c1, 0, fmt="short", fx="zoom")
    shot_clip(test_img, 3.0, c2, 1, fmt="short", fx="shake")

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
