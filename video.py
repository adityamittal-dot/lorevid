"""Rendering: Ken Burns scene clips -> crossfaded film with grain, vignette, chapter cards, music.
Also vertical Shorts and the thumbnail."""
import os, subprocess
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 30
XF = 1.0                      # soft crossfade seconds
FONT = next((p for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
                         "/usr/share/fonts/TTF/DejaVuSerif-Bold.ttf"] if os.path.exists(p)), None)
FONT_SANS = next((p for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                              "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"] if os.path.exists(p)), None)


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError("ffmpeg failed:\n" + p.stderr[-2000:])


def _motion(i, n):
    z = 0.08                  # slow, gentle motion
    return [(f"1+{z}*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
            (f"1+{z}-{z}*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
            ("1.07", f"(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"),
            ("1.07", f"(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"),
            (f"1.04+0.05*on/{n}", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(0.3+0.4*on/{n})")][i % 5]


def scene_clip(img, length, out, i, w=1920, h=1080):
    """Silent Ken Burns clip of `length` seconds."""
    n = max(2, int(round(length * FPS)))
    z, x, y = _motion(i, n)
    vf = (f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,crop={w*2}:{h*2},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={w}x{h}:fps={FPS},format=yuv420p")
    run(["ffmpeg", "-y", "-i", img, "-vf", vf, "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-an", out])


VOICE_FX = ("highpass=f=70,equalizer=f=180:t=q:w=1.2:g=2.5,equalizer=f=3200:t=q:w=1.5:g=1.5,"   # warmth + clarity
            "acompressor=threshold=-21dB:ratio=2.5:attack=8:release=160,"                     # even, close voice
            "aecho=0.85:0.6:32|53:0.07|0.05")                                                 # small warm room


def pad_audio(wav, seconds, out):
    run(["ffmpeg", "-y", "-i", wav, "-af", f"{VOICE_FX},apad=whole_dur={seconds:.3f},aresample=48000", "-ac", "2", out])


def add_ambience(narration, kind, out):
    """Quiet generated background bed under the whole narration: rain, wind, night, fire, none."""
    if kind not in ("rain", "wind", "night", "fire"):
        return narration
    color, fx = {"rain": ("pink", "highpass=f=400,lowpass=f=7000"),
                 "wind": ("brown", "lowpass=f=600,tremolo=f=0.12:d=0.7"),
                 "night": ("brown", "lowpass=f=300"),
                 "fire": ("brown", "lowpass=f=900,tremolo=f=7:d=0.5")}[kind]
    run(["ffmpeg", "-y", "-i", narration, "-f", "lavfi", "-i", f"anoisesrc=color={color}:amplitude=0.5:r=48000",
         "-filter_complex", f"[1:a]{fx},volume=0.05,aformat=channel_layouts=stereo[b];"
         "[0:a][b]amix=inputs=2:duration=first:normalize=0[a]", "-map", "[a]", "-c:a", "pcm_s16le", out])
    return out


def concat_audio(wavs, out):
    lst = out + ".txt"
    open(lst, "w").writelines(f"file '{os.path.abspath(w)}'\n" for w in wavs)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "pcm_s16le", out])
    os.remove(lst)


def _xfade_chain(clips, segs, chunk_dir):
    """Crossfade clips; clip k fades in exactly when narration segment k starts.
    Done in chunks of 20 to keep memory low. Returns path of the joined silent video."""
    def join(paths, seg_lens, out, last_has_tail):
        if len(paths) == 1:
            return paths[0]
        inputs, f, prev, offset = [], [], "[0:v]", 0.0
        for p in paths:
            inputs += ["-i", p]
        for k in range(1, len(paths)):
            offset += seg_lens[k - 1]
            lab = f"[v{k}]"
            f.append(f"{prev}[{k}:v]xfade=transition=fade:duration={XF}:offset={offset:.3f}{lab}")
            prev = lab
        run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(f), "-map", prev, "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", out])
        return out

    # level 1: chunks. Each chunk output keeps a XF-second tail (from its last clip) for the next join.
    size, parts, part_segs = 20, [], []
    for c in range(0, len(clips), size):
        ps, ss = clips[c:c + size], segs[c:c + size]
        parts.append(join(ps, ss, os.path.join(chunk_dir, f"chunk{c:04}.mp4"), True))
        part_segs.append(sum(ss))
    return join(parts, part_segs, os.path.join(chunk_dir, "joined.mp4"), False)


def render_long(images, segs, narration_wav, out, chapter_marks, music=None, work="."):
    """images[k] shown for segs[k] seconds (+XF overlap). chapter_marks: [(start_s, title)]."""
    clip_dir = os.path.join(work, "clips"); os.makedirs(clip_dir, exist_ok=True)
    clips = []
    for k, (img, s) in enumerate(zip(images, segs)):
        c = os.path.join(clip_dir, f"{k:04}.mp4")
        if not os.path.exists(c):
            scene_clip(img, s + (XF if k < len(images) - 1 else 0), c, k)
        clips.append(c)
    print("  crossfading...")
    joined = _xfade_chain(clips, segs, clip_dir)

    # chapter cards (skip the first one: the hook should start instantly)
    draw = []
    for n, (t0, title) in enumerate(chapter_marks[1:], 1):
        tf = os.path.join(work, f"chapter{n}.txt")
        open(tf, "w", encoding="utf-8").write(title.upper())
        a, b = t0 + 0.3, t0 + 4.3
        alpha = f"if(lt(t,{a}+0.6),(t-{a})/0.6,if(gt(t,{b}-0.6),({b}-t)/0.6,1))"
        draw.append(f"drawtext=fontfile={FONT}:textfile={tf}:fontsize=64:fontcolor=white:alpha='{alpha}':"
                    f"shadowcolor=black@0.8:shadowx=3:shadowy=3:x=(w-text_w)/2:y=h*0.78:enable='between(t,{a},{b})'")
    total = sum(segs)
    look = ("noise=alls=6:allf=t+u,vignette=angle=PI/5,eq=contrast=1.03:saturation=0.93:gamma=1.02,"
            "colorbalance=rs=0.03:bs=-0.03:rh=0.02,"          # warm, cosy grade
            f"fade=t=in:d=1.5,fade=t=out:st={max(0, total - 4):.2f}:d=4")
    vf = ",".join([look] + (draw if FONT else []))
    cmd = ["ffmpeg", "-y", "-i", joined, "-i", narration_wav]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music, "-filter_complex",
                f"[0:v]{vf}[v];[1:a]asplit[n1][n2];"
                f"[2:a]volume=0.22,lowpass=f=9000,afade=t=in:d=4,afade=t=out:st={max(0, total - 6):.2f}:d=6[m];"
                f"[m][n1]sidechaincompress=threshold=0.03:ratio=6:attack=80:release=900[md];"   # music dips under the voice
                f"[n2][md]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                f"loudnorm=I=-16:TP=-1.5[a]", "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", f"[0:v]{vf}[v];[1:a]loudnorm=I=-15:TP=-1.5[a]", "-map", "[v]", "-map", "[a]"]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a",
            "192k", "-shortest", "-movflags", "+faststart", out]
    print("  final encode...")
    run(cmd)


def ambient_pad(out, mood="calm", seconds=900):
    """Royalty-free fallback music: a slow, warm synth pad generated from scratch (no copyright at all)."""
    if os.path.exists(out):
        return out
    roots = {"calm": 110.0, "warm": 98.0, "melancholy": 87.31, "mystery": 92.5, "epic_soft": 82.41}
    r = roots.get(mood, 110.0)
    third = 1.189 if mood in ("melancholy", "mystery") else 1.26       # minor vs major colour
    tones = [r, r * third, r * 1.498, r * 2, r * 2 * third]
    expr = "+".join(f"{0.18/(k+1):.3f}*sin(2*PI*{f:.2f}*t)*(0.6+0.4*sin(2*PI*{0.03+0.011*k:.3f}*t))"
                    for k, f in enumerate(tones))
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={seconds}",
         "-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude=0.02:d={seconds}:r=48000",
         "-filter_complex", "[0:a]lowpass=f=1800,aecho=0.8:0.85:600|1100:0.35|0.25[p];"
         "[1:a]lowpass=f=500[n];[p][n]amix=inputs=2:normalize=0,volume=0.8,aformat=channel_layouts=stereo[a]",
         "-map", "[a]", out])
    return out


def short_clip(img, length, out, i):
    """Vertical 1080x1920: blurred full-screen background + moving 16:9 painting in the middle."""
    n = max(2, int(round(length * FPS)))
    z, x, y = _motion(i, n)
    fc = (f"[0:v]scale=2160:1215:force_original_aspect_ratio=increase,crop=2160:1215,"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s=1080x608:fps={FPS}[fg];"
          f"[1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:2,"
          f"eq=brightness=-0.12,fps={FPS}[bg];[bg][fg]overlay=0:(H-h)/2-80,format=yuv420p[v]")
    run(["ffmpeg", "-y", "-i", img, "-loop", "1", "-t", f"{length:.3f}", "-i", img, "-filter_complex", fc,
         "-map", "[v]", "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", out])


def render_short(clips, narration_wav, srt, title, out, music=None):
    lst = out + ".txt"
    open(lst, "w").writelines(f"file '{os.path.abspath(c)}'\n" for c in clips)
    joined = out + ".v.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])
    tf = out + ".title.txt"
    open(tf, "w", encoding="utf-8").write(title.replace("#shorts", "").strip().upper()[:38])
    style = ("FontName=DejaVu Sans,FontSize=15,Bold=1,Outline=3,Shadow=0,PrimaryColour=&H0000E1FF,"
             "Alignment=2,MarginV=55")
    vf = (f"subtitles={srt}:force_style='{style}',"
          f"drawtext=fontfile={FONT_SANS}:textfile={tf}:fontsize=52:fontcolor=white:borderw=4:bordercolor=black:"
          f"x=(w-text_w)/2:y=h*0.17,noise=alls=5:allf=t")
    cmd = ["ffmpeg", "-y", "-i", joined, "-i", narration_wav]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music, "-filter_complex",
                f"[0:v]{vf}[v];[2:a]volume=0.10[m];[1:a][m]amix=inputs=2:duration=first:normalize=0,"
                f"loudnorm=I=-14:TP=-1.5[a]", "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", f"[0:v]{vf}[v];[1:a]loudnorm=I=-14:TP=-1.5[a]", "-map", "[v]", "-map", "[a]"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", out]
    run(cmd)
    os.remove(lst); os.remove(joined); os.remove(tf)


def thumbnail(img, text, out, highlight="", label=""):
    """Niche-standard high-CTR layout: emotional close-up on the right, dark left side, 2-4 huge words
    (one highlighted word in yellow, the rest white), small era label, punchy contrast."""
    from PIL import ImageEnhance
    im = Image.open(img).convert("RGB")
    sc = max(1280 / im.width, 720 / im.height)                      # cover the frame, no bars
    im = im.resize((max(1280, round(im.width * sc)), max(720, round(im.height * sc))))
    left, top = max(0, (im.width - 1280) // 2), max(0, (im.height - 720) // 2)
    im = im.crop((left, top, left + 1280, top + 720))
    im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.25)).enhance(1.15)
    # dark gradient on the left 55% for the text
    mask = Image.new("L", (1280, 720))
    md = ImageDraw.Draw(mask)
    for x in range(0, 760):
        md.line([(x, 0), (x, 720)], fill=int(215 * (1 - x / 760) ** 1.3))
    im = Image.composite(Image.new("RGB", im.size, (8, 6, 4)), im, mask)
    # soft vignette
    vig = Image.new("L", (1280, 720), 0)
    ImageDraw.Draw(vig).ellipse((-200, -160, 1480, 880), fill=255)
    im = Image.composite(im, Image.new("RGB", im.size, (0, 0, 0)), vig.filter(ImageFilter.GaussianBlur(120)))
    d = ImageDraw.Draw(im)
    words = text.upper().split()[:5]
    size = 150 if len(" ".join(words)) <= 12 else 124 if len(" ".join(words)) <= 20 else 104
    font = ImageFont.truetype(FONT_SANS, size) if FONT_SANS else ImageFont.load_default()
    lines = [[]]
    for w in words:
        if lines[-1] and d.textlength(" ".join(lines[-1] + [w]), font=font) > 760:
            lines.append([w])
        else:
            lines[-1].append(w)
    hl = {h.upper() for h in highlight.split()} or {words[-1] if words else ""}
    y = (720 - len(lines) * int(size * 1.08)) // 2 + 20
    for line in lines:
        x = 50
        for w in line:
            col = (255, 208, 40) if w.strip("?!.,") in hl else (255, 255, 255)
            d.text((x + 6, y + 8), w, font=font, fill=(0, 0, 0))                     # drop shadow
            d.text((x, y), w, font=font, fill=col, stroke_width=7, stroke_fill=(0, 0, 0))
            x += d.textlength(w + " ", font=font)
        y += int(size * 1.08)
    if label:
        lf = ImageFont.truetype(FONT_SANS, 34) if FONT_SANS else font
        lw = d.textlength(label.upper(), font=lf)
        d.rounded_rectangle((44, 36, 44 + lw + 32, 88), radius=8, fill=(170, 20, 20))
        d.text((60, 42), label.upper(), font=lf, fill=(255, 255, 255))
    im.save(out, "JPEG", quality=92)
