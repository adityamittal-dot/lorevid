"""lorevid pipeline orchestrator: script json -> final.mp4 (+thumbnail/srt) -> YouTube upload.

Usage:
  python pipeline.py scripts/queue/<id>.json [--upload] [--no-move]
"""
import argparse
from datetime import datetime, timedelta, timezone
import glob
import json
import os
import sys
import zlib
from dotenv import load_dotenv
import requests

load_dotenv()
import images
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
    for pattern in ("scripts/done/*.json", "scripts/queue/*.json"):
        for path in glob.glob(pattern):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("id") == related_id:
                    pub = data.get("published", {})
                    if pub.get("video_id"):
                        return f"https://youtu.be/{pub['video_id']}"
                    if pub.get("url"):
                        return pub["url"]
            except Exception:
                continue
    return None


BEAT = 1.0           # target seconds per picture in a Short; top theory Shorts cut every ~0.8-1.2 s


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


def short_clips(script, lines, segs, line_starts, line_words_rel, work, seed) -> list:
    """Shorts: 1-4 full-screen pictures per line, each picked for that line from the wiki pages the Short is
    about (visuals.rank), cut on word boundaries, with every clip's length laid on one 30 fps frame grid so
    hundreds of cuts never drift from the voice."""
    wiki = script.get("wiki", "onepiece.fandom.com")
    pool = {}
    pages = visuals.script_pages(script)
    for page in pages:
        pool.update(visuals.page_images(wiki, page))
    print(f"  image pool: {len(pool)} files from {len(pages)} wiki pages", flush=True)
    used, clips, last_img, k = visuals.Picks(), [], None, 0
    used_log, seen_log, missing = used.order, [], 0
    for i, line in enumerate(lines):
        shot = line.get("shot", {})
        seg = segs[i]
        n = max(1, min(4, round(seg / BEAT)))
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
                images.generate(f"{shot['fallback']}, {visuals.ANIME_STYLE}", paths[0], seed + i, 768, 1344)
                imgs = [paths[0]]
            except Exception as e:
                print(f"  line {i}: AI fallback failed ({e})", flush=True)
        if not imgs:
            if not last_img:
                last_img = paths[0]
                video.blank_image(last_img, "short")
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
                video.beat_clip(imgs[b], f1 - f0, clip, k, line.get("fx", "none") if b == 0 else "none", tight[b])
            clips.append(clip)
            k += 1
    print(f"  {len(clips)} cuts, {sum(segs) / max(1, len(clips)):.2f} s per picture", flush=True)
    if missing > len(lines) / 2:                       # wiki and AI both down: retry on the next run, don't publish
        raise RuntimeError(f"no picture for {missing} of {len(lines)} lines (wiki or image backends unreachable)")
    return clips


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
    narration_wav = os.path.join(work, "narration.wav")
    if not os.path.exists(narration_wav):
        print("  Concatenating padded audio...", flush=True)
        video.concat_audio(padded_wavs, narration_wav)

    # 3. Visuals & video clips
    print(f"Step 3: Fetching visuals and generating clips ({fmt})...", flush=True)
    used_images = set()
    clips = []
    last_img = None
    if fmt == "short":
        clips = short_clips(script, lines, segs, line_starts, line_words_rel, work, seed)
    for i, line in enumerate(lines if fmt == "long" else []):
        img_path = os.path.join(work, "img", f"{i:04d}.jpg")
        clip_path = os.path.join(work, "clips", f"{i:04d}.mp4")
        shot = line.get("shot", {})

        vres = visuals.get(shot, wiki, img_path, used_images, seed + i, vertical=(fmt == "short"))
        if vres:
            last_img = vres["path"]
        elif last_img:
            print(f"  line {i}: no image found, reusing the previous one", flush=True)
        else:                                          # nothing at all yet: a plain dark frame
            video.blank_image(img_path, fmt)
            last_img = img_path
        # long videos crossfade: every clip but the last runs XF longer so picture and voice stay in sync
        seconds = segs[i] + (video.XF if fmt == "long" and i < len(lines) - 1 else 0)
        if not os.path.exists(clip_path):
            video.shot_clip(last_img, seconds, clip_path, i, fmt, line.get("fx", "none"))

        clips.append(clip_path)

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
    if fmt == "short":                                 # long videos get an uploaded caption track instead
        ass_path = video.captions_ass(words, os.path.join(work, "captions.ass"), fmt,
                                      hook_text=script.get("hook_text"), hook_secs=2.6)

    mood = script.get("music_mood", "chill")
    music = video.music_bed(mood, work, total_duration)

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
        )

    # 6. Format checks & long assets
    print("Step 6: Processing format-specific assets and metadata...", flush=True)
    if fmt == "short":
        if total_duration > 180.0:
            raise ValueError(f"Short duration {total_duration:.1f}s exceeds YouTube Shorts 180s limit")
        if total_duration > 60.0:
            print(f"Warning: Short duration {total_duration:.1f}s is longer than 60s", flush=True)

    thumb_path = None
    srt_path = None

    if fmt == "long":
        thumb_cfg = script.get("thumbnail", {})
        thumb_path = os.path.join(work, "thumbnail.jpg")
        if not os.path.exists(thumb_path):
            thumb_raw = os.path.join(work, "thumb_raw.jpg")
            if not os.path.exists(thumb_raw):
                thumb_shot = {
                    "image": thumb_cfg.get("image"),
                    "search": thumb_cfg.get("search") or script.get("topic", ""),
                    "fallback": f"{script.get('topic', '')}, anime style",
                }
                tres = visuals.get(thumb_shot, wiki, thumb_raw, set(), seed + 999, vertical=False)
                thumb_raw = tres["path"] if tres else (last_img or thumb_raw)
            video.thumbnail(thumb_raw, thumb_cfg.get("text", ""), thumb_cfg.get("highlight", ""), thumb_path)

        srt_path = os.path.join(work, "captions.srt")
        if not os.path.exists(srt_path):
            tts.write_srt(words, srt_path)

    # Build description
    desc_blocks = [script.get("description", "").strip()]
    if fmt == "long" and chapter_marks:
        ch_text = "Chapters:\n" + "\n".join(f"{fmt_time(tm)} {title}" for tm, title in chapter_marks)
        desc_blocks.append(ch_text)
    elif fmt == "short" and script.get("related_long"):
        rl_id = script["related_long"]
        rl_url = find_related_long_url(rl_id)
        if rl_url:
            desc_blocks.append(f"Full breakdown on the channel: {rl_url}")
        else:
            desc_blocks.append("Full breakdown on the channel")

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
            publish_at = upload.next_slot(fmt, channel_cfg, taken)
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

        video_id = upload.upload(
            video=final_mp4,
            meta=upload_meta,
            publish_at=publish_at,
            privacy=privacy,
            thumb=thumb_path if fmt == "long" else None,
            srt=srt_path if fmt == "long" else None,
            playlist=playlist_title,
            comment=script.get("comment") if privacy == "public" and not publish_at else None,
        )
        print(f"  Uploaded video ID: {video_id}", flush=True)

        video_url = f"https://youtu.be/{video_id}"
        script["published"] = {
            "video_id": video_id,
            "publish_at": publish_at,
            "url": video_url,
            "comment": script.get("comment"),              # posted by `upload.py comments` once the video is public
            "comment_posted": privacy == "public" and not publish_at,
        }
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, indent=2, ensure_ascii=False)

        if not no_move_flag:
            os.makedirs("scripts/done", exist_ok=True)
            done_path = os.path.join("scripts", "done", f"{script_id}.json")
            os.replace(script_path, done_path)
            print(f"  Moved script to {done_path}", flush=True)

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
