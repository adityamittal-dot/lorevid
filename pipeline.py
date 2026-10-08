"""lorevid pipeline orchestrator: script json -> final.mp4 (+thumbnail/srt) -> YouTube upload.

Usage:
  python pipeline.py scripts/queue/<id>.json [--upload] [--no-move]
"""
import argparse
from datetime import datetime, timedelta, timezone
import glob
import json
import os
import re
import sys
import zlib
from dotenv import load_dotenv
import requests

load_dotenv()
import images
import music as music_lib
import tts
import upload
import video
import visuals


def notify(msg: str, click: str = None) -> None:
    """Send alert via ntfy if NTFY_TOPIC is configured in the environment."""
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        return
    try:
        headers = {"Title": "lorevid"}
        if click:
            headers["Click"] = click
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=msg.encode("utf-8"),
            headers=headers,
            timeout=15,
        )
    except Exception as e:
        print(f"notify failed: {e}", flush=True)


def fmt_time(seconds: float) -> str:
    """Format seconds into M:SS (or H:MM:SS) timestamp for chapters."""
    s = int(round(seconds))
    m = s // 60
    sec = s % 60
    if m >= 60:
        h = m // 60
        m = m % 60
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def find_related_long_url(related_id: str) -> str | None:
    """Check scripts/done/ and scripts/queue/ to see if the related long video has published."""
    info = find_related_long(related_id)
    return info["url"] if info else None


def find_related_long(related_id: str) -> dict | None:
    """{"url", "title"} for a related long video once it has published (scripts/done/ or scripts/queue/),
    else None. Used both for the Short's description/comment and for the studio_todo.md related-video note
    (the Data API has no "related video" field to set directly; a human links it in YouTube Studio)."""
    for pattern in ("scripts/done/*.json", "scripts/queue/*.json"):
        for path in glob.glob(pattern):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("id") != related_id:
                    continue
                pub = data.get("published", {})
                url = (f"https://youtu.be/{pub['video_id']}" if pub.get("video_id") else pub.get("url"))
                if url:
                    return {"url": url, "title": data.get("title", "")}
            except Exception:
                continue
    return None


def append_studio_todo(line: str, data_dir: str = "data") -> None:
    """One manual follow-up line in data/studio_todo.md: things the YouTube Data API can't do itself
    (Test & Compare thumbnails, a Short's "related video" field), so a human checks them off in Studio."""
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "studio_todo.md")
    is_new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if is_new:
            f.write("# Studio To-Do\n\nManual YouTube Studio follow-ups the API can't do on its own. "
                    "Check items off as you handle them.\n\n")
        f.write(line.rstrip("\n") + "\n")


# Target seconds per picture. Top theory Shorts cut every ~0.8-1.2 s; the top faceless long videos in the niche
# (Facadify, Strawhatists: 140k-230k views) cut every ~1.2-1.5 s. Long beats run a little longer so manga pages
# can be read.
BEAT = {"short": 1.0, "long": 1.7}
MAX_BEATS = {"short": 4, "long": 3}
PAUSE_SCALE = {"short": 1.0, "long": 1.0}   # line ends are trimmed now (tts.py), so long needs no extra squeeze


MISSING_NAMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pronounce_missing.md")


def note_unknown_names(script_id: str, lines: list) -> None:
    """Names the voice had to guess (not in Kokoro's dictionary or pronounce.json) go to data/pronounce_missing.md,
    which the writer clears by adding pronounce.json entries (WRITER.md, Pronunciation)."""
    names = sorted({n for line in lines for n in tts.unknown_names(line.get("text", ""))})
    if not names:
        return
    print(f"  names without a pronunciation entry (guessed): {', '.join(names)}", flush=True)
    seen = set()
    if os.path.exists(MISSING_NAMES):
        with open(MISSING_NAMES, encoding="utf-8") as f:
            seen = {ln[2:].split(" (")[0] for ln in f if ln.startswith("- ")}
    new = [n for n in names if n not in seen]
    if not new:
        return
    if not os.path.exists(MISSING_NAMES):
        with open(MISSING_NAMES, "w", encoding="utf-8") as f:
            f.write("# Names the voice had to guess\n\nAdd each to pronounce.json (see WRITER.md, Pronunciation), "
                    "then delete its line here.\n\n")
    with open(MISSING_NAMES, "a", encoding="utf-8") as f:
        f.writelines(f"- {n} ({script_id})\n" for n in new)


def beat_cuts(seg: float, rel_words: list, n: int) -> list:
    """Split a line of `seg` seconds into n beats; cuts land on word starts so a picture changes with the words.
    Returns the n+1 boundaries in seconds from the line start (fewer beats if the line is too short)."""
    cuts = [0.0]
    starts = [w[0] for w in rel_words]
    for k in range(1, n):
        target = seg * k / n
        snap = min(starts, key=lambda s: abs(s - target)) if starts else target
        if abs(snap - target) > seg / (2 * n):
            snap = target
        if snap - cuts[-1] >= 0.6 and seg - snap >= 0.6:
            cuts.append(snap)
    return cuts + [seg]


def beat_clips(script, fmt, lines, segs, line_starts, line_words_rel, work, seed, ass=None):
    """1-4 pictures per line (Shorts) or 1-3 (long), each picked for that line from the wiki pages the video is
    about (visuals.rank), cut on word boundaries, with every clip's length laid on one 30 fps frame grid so
    hundreds of cuts never drift from the voice. Long videos: a line's `card` text appears over its first beat."""
    wiki = script.get("wiki", "onepiece.fandom.com")
    pool = {}
    pages = visuals.script_pages(script)
    for page in pages:
        pool.update(visuals.page_images(wiki, page))
    print(f"  image pool: {len(pool)} files from {len(pages)} wiki pages", flush=True)
    used, clips, last_img, k, jobs = visuals.Picks(), [], None, 0, []
    chapter_at = {ch["line"]: ch.get("title", "") for ch in script.get("chapters") or [] if ch.get("line")}
    used_log, seen_log, missing = used.order, [], 0
    for i, line in enumerate(lines):
        shot = line.get("shot", {})
        seg = segs[i]
        n = max(1, min(MAX_BEATS[fmt], round(seg / BEAT[fmt])))
        paths = [os.path.join(work, "img", f"{i:04d}_{b}.jpg") for b in range(n)]
        imgs = [p for p in paths if os.path.exists(p) and os.path.getsize(p) > 5000]
        fresh = not imgs
        if not imgs:
            if i == 0 and not shot.get("image") and visuals.pick_hook(shot, line.get("text", ""), wiki, pool, used,
                                                                      paths[0]):
                imgs = [paths[0]] + visuals.pick(dict(shot, image=None), line.get("text", ""), wiki, pool, used,
                                                 n - 1, paths[1:])
            else:
                imgs = visuals.pick(shot, line.get("text", ""), wiki, pool, used, n, paths)
        if not imgs and shot.get("fallback"):
            try:
                w, h = (768, 1344) if fmt == "short" else (1344, 768)
                images.generate(f"{shot['fallback']}, {visuals.ANIME_STYLE}", paths[0], seed + i, w, h)
                imgs = [paths[0]]
            except Exception as e:
                print(f"  line {i}: AI fallback failed ({e})", flush=True)
        if not imgs:
            if not last_img:
                last_img = paths[0]
                video.blank_image(last_img, fmt)
            print(f"  line {i}: no image found, reusing the previous one", flush=True)
            imgs = [last_img]
            missing += 1
        if fresh and len(used_log) > len(seen_log):
            print(f"  line {i}: " + " | ".join(t[5:] for t in used_log[len(seen_log):]), flush=True)
            seen_log[:] = used_log
        last_img = imgs[-1]
        tight = [False] * len(imgs)
        if len(imgs) < n:                                  # not enough matching pictures: punch in on the last one
            imgs, tight = imgs + [imgs[-1]], tight + [True]
        cuts = beat_cuts(seg, line_words_rel[i], len(imgs))
        for b in range(len(cuts) - 1):
            f0 = round((line_starts[i] + cuts[b]) * video.FPS)
            f1 = round((line_starts[i] + cuts[b + 1]) * video.FPS)
            clip = os.path.join(work, "clips", f"{i:04d}_{b}.mp4")
            if not os.path.exists(clip):
                title = ((chapter_at[i], b == 0, b == len(cuts) - 2) if fmt == "long" and i in chapter_at else None)
                jobs.append((imgs[b], f1 - f0, clip, k, line.get("fx", "none") if b == 0 else "none", tight[b], fmt,
                             line.get("card") if b == 0 and fmt == "long" and i not in chapter_at else None, title,
                             (ass, f0 / video.FPS) if ass else None))
            clips.append(clip)
            k += 1
    # every picture is chosen in order above (no repeats); the ffmpeg renders are independent, so run them side by side
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool_:
        list(pool_.map(lambda j: video.beat_clip(*j[:6], fmt=j[6], card=j[7], title=j[8], subs=j[9]), jobs))
    print(f"  {len(clips)} cuts, {sum(segs) / max(1, len(clips)):.2f} s per picture", flush=True)
    if missing > len(lines) / 2:                       # wiki and AI both down: retry on the next run, don't publish
        raise RuntimeError(f"no picture for {missing} of {len(lines)} lines (wiki or image backends unreachable)")
    return clips, pool


def run(script_path: str, upload_flag: bool = False, no_move_flag: bool = False) -> str:
    """Execute rendering pipeline for a single script file."""
    # 1. Load script + channel.json; setup work dir
    print(f"Step 1: Loading script {script_path}...", flush=True)
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    script_id = script["id"]
    fmt = script.get("format", "short")
    wiki = script.get("wiki", "onepiece.fandom.com")
    lines = script.get("lines", [])

    channel_cfg = {}
    if os.path.exists("channel.json"):
        try:
            with open("channel.json", encoding="utf-8") as f:
                channel_cfg = json.load(f)
        except Exception as e:
            print(f"Warning: could not read channel.json: {e}", flush=True)

    work = os.path.join("output", script_id)
    os.makedirs(work, exist_ok=True)
    os.makedirs(os.path.join(work, "audio"), exist_ok=True)
    os.makedirs(os.path.join(work, "img"), exist_ok=True)
    os.makedirs(os.path.join(work, "clips"), exist_ok=True)
    os.makedirs(os.path.join(work, "sfx"), exist_ok=True)

    seed = zlib.crc32(script_id.encode()) % 1_000_000
    voice = tts.voice_from_channel(channel_cfg)
    base_speed = channel_cfg.get("speed", {}).get(fmt, 1.12 if fmt == "short" else 1.04)

    # Chapters mapping
    chapters = script.get("chapters", [])
    chapter_line_map = {ch["line"]: ch.get("title", "") for ch in chapters}

    # 2. Narration TTS, padding, and word timestamp aggregation
    print(f"Step 2: Synthesizing narration ({len(lines)} lines)...", flush=True)
    padded_wavs = []
    segs = []
    line_starts = []
    line_words_rel = []
    words = []
    chapter_marks = []
    t = 0.0

    for i, line in enumerate(lines):
        if i in chapter_line_map:
            chapter_marks.append((t, chapter_line_map[i]))

        line_starts.append(t)
        delivery = line.get("delivery", "normal")
        sp_mult, pause_after = tts.DELIVERY.get(delivery, tts.DELIVERY["normal"])
        pause_after *= PAUSE_SCALE.get(fmt, 1.0)
        line_speed = base_speed * sp_mult

        wav_path = os.path.join(work, "audio", f"{i:04d}.wav")
        words_cache = os.path.join(work, "audio", f"{i:04d}.words.json")

        if os.path.exists(wav_path) and os.path.exists(words_cache):
            with open(words_cache, encoding="utf-8") as wf:
                line_words = json.load(wf)
        else:
            line_words = tts.speak_line(line.get("text", ""), wav_path, speed=line_speed, voice=voice)
            with open(words_cache, "w", encoding="utf-8") as wf:
                json.dump(line_words, wf)

        d = tts.duration(wav_path)
        is_before_chapter = (i + 1) in chapter_line_map and (i + 1) > 0
        seg = d + pause_after + (0.6 if is_before_chapter else 0.0)

        pw_path = os.path.join(work, "audio", f"{i:04d}.pad.wav")
        if not os.path.exists(pw_path):
            video.pad_audio(wav_path, seg, pw_path)

        line_words_rel.append(line_words)
        for w_start, w_end, w_text in line_words:
            words.append((w_start + t, w_end + t, w_text))

        padded_wavs.append(pw_path)
        segs.append(seg)
        t += seg

    total_duration = t
    try:
        note_unknown_names(script_id, lines)
    except Exception as e:
        print(f"  pronunciation check skipped ({e})", flush=True)
    narration_wav = os.path.join(work, "narration.wav")
    if not os.path.exists(narration_wav):
        print("  Concatenating padded audio...", flush=True)
        video.concat_audio(padded_wavs, narration_wav)

    # 3. Visuals & video clips
    print(f"Step 3: Fetching visuals and generating clips ({fmt})...", flush=True)
    long_ass = None
    if fmt == "long":                                  # burned into each beat clip (the joined video is stream-copied)
        long_ass = video.captions_ass(words, os.path.join(work, "captions_long.ass"), fmt)
    clips, pool = beat_clips(script, fmt, lines, segs, line_starts, line_words_rel, work, seed, ass=long_ass)
    last_img = next((p for p in sorted(glob.glob(os.path.join(work, "img", "*.jpg")))), None)

    # 4. SFX events
    print("Step 4: Scheduling SFX events...", flush=True)
    sfx_events = []
    sfx_cache = {}

    def get_sfx(kind: str) -> str:
        if kind not in sfx_cache:
            out_sfx = os.path.join(work, "sfx", f"{kind}.wav")
            sfx_cache[kind] = video.sfx(kind, out_sfx)
        return sfx_cache[kind]

    for i, line in enumerate(lines):
        fx = line.get("fx", "none")
        if fmt == "short" and fx != "none":
            sfx_events.append((line_starts[i], get_sfx("whoosh"), 0.35))
        if fx in ("shake", "flash"):
            sfx_events.append((line_starts[i], get_sfx("hit"), 0.5))

    first_reveal_idx = next((i for i, line in enumerate(lines) if line.get("delivery") == "reveal"), None)
    if first_reveal_idx is not None:
        riser_t = max(0.0, line_starts[first_reveal_idx] - 1.2)
        sfx_events.append((riser_t, get_sfx("riser"), 0.25))

    # 5. Captions, Music bed & Render
    print("Step 5: Generating subtitles, background track, and rendering...", flush=True)
    ass_path = None
    if fmt == "short":                                 # long videos burn captions per beat clip (step 3)
        ass_path = video.captions_ass(words, os.path.join(work, "captions.ass"), fmt,
                                      hook_text=script.get("hook_text"), hook_secs=2.6)

    mood = script.get("music_mood", "chill")
    music_tracks = []
    try:
        music, music_tracks = music_lib.bed(mood, work, total_duration, narration_wav, fmt, seed=seed)
    except Exception as e:
        print(f"  music bed failed ({e}); using the synthesized pad", flush=True)
        music = None
    music_leveled = bool(music)
    if not music:
        music = video.music_bed(mood, work, total_duration)
    print(f"  music: {', '.join(os.path.basename(t) for t in music_tracks) or 'synthesized pad'}", flush=True)

    final_mp4 = os.path.join(work, "final.mp4")
    if not os.path.exists(final_mp4):
        print(f"  Rendering final video: {final_mp4}...", flush=True)
        video.render(
            clips,
            segs,
            narration_wav,
            final_mp4,
            fmt,
            ass=ass_path,
            music=music,
            sfx_events=sfx_events,
            chapter_marks=chapter_marks,
            music_leveled=music_leveled,
        )

    # 6. Format checks & long assets
    print("Step 6: Processing format-specific assets and metadata...", flush=True)
    if fmt == "short":
        if total_duration > 180.0:
            raise ValueError(f"Short duration {total_duration:.1f}s exceeds YouTube Shorts 180s limit")
        if total_duration > 60.0:
            print(f"Warning: Short duration {total_duration:.1f}s is longer than 60s", flush=True)

    thumb_path = None
    thumb_b_path = None
    srt_path = None

    if fmt == "long":
        thumb_cfg = script.get("thumbnail") or {}
        device = thumb_cfg.get("device")
        thumb_path = os.path.join(work, "thumbnail.jpg")
        thumb_b_path = os.path.join(work, "thumbnail_b.jpg")
        if not os.path.exists(thumb_path):
            # the most colourful close-up for the thumbnail's search words (and a second character for a split)
            raws = []
            for key, name in (("search", "thumb_raw.jpg"), ("search2", "thumb_raw2.jpg")):
                raw = os.path.join(work, name)
                words_ = thumb_cfg.get(key) or (script.get("topic", "") if key == "search" else "")
                if not words_ and not (key == "search" and thumb_cfg.get("image")):
                    continue
                if not os.path.exists(raw):
                    shot = {"search": words_, "image": thumb_cfg.get("image") if key == "search" else None}
                    if shot["image"]:
                        visuals.pick(shot, words_, wiki, pool, visuals.Picks(), 1, [raw])
                    if not os.path.exists(raw):
                        visuals.pick_hook(shot, script.get("title", ""), wiki, pool, visuals.Picks(), raw, tries=6)
                if os.path.exists(raw):
                    raws.append(raw)
            if not raws and last_img:
                raws = [last_img]
            if raws:
                video.thumbnail(raws[0], thumb_cfg.get("text", ""), thumb_cfg.get("highlight", ""), thumb_path,
                                img2=raws[1] if len(raws) > 1 else None, device=device)
                # Variant B for a manual YouTube Studio Test & Compare (the Data API can't run A/B tests itself):
                # a different device if the main thumbnail used one, else a device added; always text-free, so
                # it's a genuinely different hypothesis rather than a copy with a pixel moved.
                b_device = None if device else "circle"
                if not os.path.exists(thumb_b_path):
                    video.thumbnail(raws[0], "", "", thumb_b_path, img2=raws[1] if len(raws) > 1 else None,
                                    device=b_device)
            else:
                thumb_path = None
                thumb_b_path = None

        srt_path = os.path.join(work, "captions.srt")
        if not os.path.exists(srt_path):
            tts.write_srt(words, srt_path)

    # Build description
    desc_blocks = [script.get("description", "").strip()]
    related_long_url = None
    if fmt == "long" and chapter_marks:
        ch_text = "Chapters:\n" + "\n".join(f"{fmt_time(tm)} {title}" for tm, title in chapter_marks)
        desc_blocks.append(ch_text)
    elif fmt == "short" and script.get("related_long"):
        rl_info = find_related_long(script["related_long"])
        if rl_info:
            related_long_url = rl_info["url"]
            desc_blocks.insert(0, related_long_url)          # the full video's link is the first line, not buried
            desc_blocks.append(f"Full breakdown: {rl_info['title']}")
        else:
            desc_blocks.append("Full breakdown on the channel")

    # Credits: rights holders of the series, the wiki the stills came from, the music (CC BY requires it, and the
    # composer's Content ID releases videos that credit him), and a plain fan-commentary note.
    series_cfg = next((s for s in channel_cfg.get("series", []) if s.get("id") == script.get("series")), {})
    credit_lines = [series_cfg.get("credit", ""), music_lib.credit(music_tracks), channel_cfg.get("fair_use_note", "")]
    credits = "\n".join(c for c in credit_lines if c)
    if credits:
        desc_blocks.append(credits)

    hashtags = script.get("hashtags", [])
    if hashtags:
        desc_blocks.append(" ".join(hashtags))

    full_description = "\n\n".join(b for b in desc_blocks if b)

    meta = {
        "id": script_id,
        "format": fmt,
        "title": script.get("title", ""),
        "description": full_description,
        "tags": script.get("tags", []),
        "final": final_mp4,
        "thumb": thumb_path if fmt == "long" else None,
        "thumb_b": thumb_b_path if fmt == "long" else None,
        "srt": srt_path if fmt == "long" else None,
        "duration": total_duration,
        "chapters": chapter_marks if fmt == "long" else None,
    }
    with open(os.path.join(work, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    # 7. Uploading
    if upload_flag:
        print("Step 7: Uploading to YouTube...", flush=True)
        mode = os.getenv("PUBLISH_MODE") or channel_cfg.get("publish", {}).get("mode", "schedule")
        publish_at = None
        privacy = "private"

        if mode == "schedule":
            taken = []
            for pattern in ("scripts/done/*.json", "scripts/queue/*.json"):
                for path in glob.glob(pattern):
                    try:
                        with open(path, encoding="utf-8") as f:
                            d = json.load(f)
                        pat = d.get("published", {}).get("publish_at")
                        if pat:
                            taken.append(pat)
                    except Exception:
                        continue
            id_date_match = re.match(r"(\d{4}-\d{2}-\d{2})-", script_id)
            min_date = id_date_match.group(1) if id_date_match else None
            publish_at = upload.next_slot(fmt, channel_cfg, taken, min_date=min_date)
            privacy = "private"
        elif mode == "public":
            privacy = "public"
            publish_at = None
        else:
            privacy = "private"
            publish_at = None

        series_id = script.get("series")
        series_info = next((s for s in channel_cfg.get("series", []) if s.get("id") == series_id), None)
        playlist_title = series_info.get("playlist") if series_info else None

        upload_meta = {
            "title": script.get("title", ""),
            "description": full_description,
            "tags": script.get("tags", []),
        }

        # The long video's link also opens the Short's first comment, same as the description (section 8).
        comment_text = script.get("comment")
        if related_long_url and comment_text:
            comment_text = f"{comment_text}\n{related_long_url}"

        video_id = upload.upload(
            video=final_mp4,
            meta=upload_meta,
            publish_at=publish_at,
            privacy=privacy,
            thumb=thumb_path if fmt == "long" else None,
            srt=srt_path if fmt == "long" else None,
            playlist=playlist_title,
            comment=comment_text if privacy == "public" and not publish_at else None,
        )
        print(f"  Uploaded video ID: {video_id}", flush=True)

        video_url = f"https://youtu.be/{video_id}"
        script["published"] = {
            "video_id": video_id,
            "publish_at": publish_at,
            "url": video_url,
            "comment": comment_text,                        # posted by `upload.py comments` once the video is public
            "comment_posted": privacy == "public" and not publish_at,
        }
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, indent=2, ensure_ascii=False)

        if not no_move_flag:
            os.makedirs("scripts/done", exist_ok=True)
            done_path = os.path.join("scripts", "done", f"{script_id}.json")
            os.replace(script_path, done_path)
            print(f"  Moved script to {done_path}", flush=True)

        # Human follow-ups the Data API can't do itself: a thumbnail A/B test, and an Ls Short's related video.
        if fmt == "long" and thumb_b_path and os.path.exists(thumb_b_path):
            append_studio_todo(f"- [ ] {script.get('title', '')} ({video_url}) -> thumbnail B saved at "
                               f"{thumb_b_path}; run YouTube Studio Test & Compare")
        if fmt == "short" and re.search(r"-L\d*s\d+$", script_id) and script.get("related_long"):
            rl_info = find_related_long(script["related_long"])
            if rl_info:
                append_studio_todo(f"- [ ] {script.get('title', '')} ({video_url}) -> related video: "
                                   f"{rl_info['title']} ({rl_info['url']})")

        studio_link = f"https://studio.youtube.com/video/{video_id}/edit"
        kind_label = "Short" if fmt == "short" else "Long"
        if publish_at:
            dt_utc = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
            ist_tz = timezone(timedelta(hours=5, minutes=30))
            dt_ist = dt_utc.astimezone(ist_tz)
            ist_time_str = dt_ist.strftime("%Y-%m-%d %H:%M IST")
            status_desc = f"scheduled {ist_time_str}"
        else:
            status_desc = privacy

        ntfy_msg = f"{kind_label} {status_desc} | {script.get('title')}\n{studio_link}"
        notify(ntfy_msg, click=studio_link)

    print(f"Finished pipeline for {script_id}: {final_mp4} ({fmt_time(total_duration)})", flush=True)
    return final_mp4


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="lorevid v2 pipeline orchestrator")
    parser.add_argument("script", help="Path to script json (e.g. scripts/queue/<id>.json)")
    parser.add_argument("--upload", action="store_true", help="Upload rendered video to YouTube")
    parser.add_argument("--no-move", action="store_true", help="Do not move script to scripts/done/ after upload")
    args = parser.parse_args()

    script_id = os.path.splitext(os.path.basename(args.script))[0]
    try:
        run(args.script, upload_flag=args.upload, no_move_flag=args.no_move)
    except Exception as e:
        if os.getenv("FINAL_ATTEMPT", "1") != "0":
            notify(f"Run failed for '{script_id}': {str(e)[:300]}")
        raise
