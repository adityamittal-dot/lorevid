"""Rendering: Ken Burns scene clips -> crossfaded film with grain, vignette, chapter cards, music.
Also vertical Shorts and the thumbnail."""
import os, subprocess
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 30
XF = 0.6                      # crossfade seconds
FONT = next((p for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
                         "/usr/share/fonts/TTF/DejaVuSerif-Bold.ttf"] if os.path.exists(p)), None)
FONT_SANS = next((p for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                              "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"] if os.path.exists(p)), None)


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError("ffmpeg failed:\n" + p.stderr[-2000:])


def _motion(i, n):
    z = 0.13
    return [(f"1+{z}*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
            (f"1+{z}-{z}*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
            ("1.1", f"(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"),
            ("1.1", f"(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"),
            (f"1.05+0.08*on/{n}", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(0.3+0.4*on/{n})")][i % 5]


def scene_clip(img, length, out, i, w=1920, h=1080):
    """Silent Ken Burns clip of `length` seconds."""
    n = max(2, int(round(length * FPS)))
    z, x, y = _motion(i, n)
    vf = (f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,crop={w*2}:{h*2},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={w}x{h}:fps={FPS},format=yuv420p")
    run(["ffmpeg", "-y", "-i", img, "-vf", vf, "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-an", out])


def pad_audio(wav, seconds, out):
    run(["ffmpeg", "-y", "-i", wav, "-af", f"apad=whole_dur={seconds:.3f},aresample=48000", "-ac", "2", out])


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
    look = "noise=alls=7:allf=t+u,vignette=angle=PI/5,eq=contrast=1.04:saturation=0.95"
    vf = ",".join([look] + (draw if FONT else []))
    cmd = ["ffmpeg", "-y", "-i", joined, "-i", narration_wav]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music, "-filter_complex",
                f"[0:v]{vf}[v];[2:a]volume=0.09,afade=t=in:d=3[m];[1:a][m]amix=inputs=2:duration=first:"
                f"dropout_transition=0:normalize=0,loudnorm=I=-15:TP=-1.5[a]", "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", f"[0:v]{vf}[v];[1:a]loudnorm=I=-15:TP=-1.5[a]", "-map", "[v]", "-map", "[a]"]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a",
            "192k", "-shortest", "-movflags", "+faststart", out]
    print("  final encode...")
    run(cmd)


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


def thumbnail(img, text, out):
    im = Image.open(img).convert("RGB")
    im = im.resize((1280, int(im.height * 1280 / im.width)))
    top = max(0, (im.height - 720) // 2)
    im = im.crop((0, top, 1280, top + 720))
    # darken bottom-left for text contrast
    grad = Image.new("L", (1280, 720))
    ImageDraw.Draw(grad).rectangle((0, 380, 1280, 720), fill=150)
    im = Image.composite(Image.new("RGB", im.size, (0, 0, 0)), im, grad.filter(ImageFilter.GaussianBlur(90)))
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(FONT_SANS, 104) if FONT_SANS else ImageFont.load_default()
    words, lines = text.upper().split(), [""]
    for w in words:
        if d.textlength((lines[-1] + " " + w).strip(), font=font) > 1100:
            lines.append(w)
        else:
            lines[-1] = (lines[-1] + " " + w).strip()
    y = 720 - 60 - 115 * len(lines)
    for line in lines:
        d.text((60, y), line, font=font, fill=(255, 214, 80), stroke_width=6, stroke_fill=(0, 0, 0))
        y += 115
    im.save(out, "JPEG", quality=92)
