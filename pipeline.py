"""Daily run: next topic -> Claude script -> images -> voice -> 10-min film + 2 Shorts -> private upload -> notify.

  python pipeline.py --next-topic --upload        # what GitHub Actions runs
  python pipeline.py "Your Life as a Roman Gladiator"
Everything is cached in output/<slug>/, so re-running resumes where it stopped.
"""
import argparse, glob, json, os, random, re, zlib
from dotenv import load_dotenv

load_dotenv()
import images, tts, video
from script_gen import build_long, new_topics

STYLE = os.getenv("STYLE", "richly detailed semi-realistic digital oil painting, historical illustration, "
                           "cinematic volumetric lighting, warm muted earthy palette, soft painterly brushwork, "
                           "atmospheric depth, masterpiece")
MINUTES = int(os.getenv("MINUTES", "10"))
PAD = 0.45           # pause after each scene (s)
QUEUE = "topics/long.txt"


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def next_topic():
    lines = [l.rstrip("\n") for l in open(QUEUE, encoding="utf-8")] if os.path.exists(QUEUE) else []
    todo = [l for l in lines if l.strip() and not l.startswith("#")]
    if not todo:
        print("Topic queue empty — asking Claude for new topics")
        lines += new_topics([l[6:] for l in lines if l.startswith("#done ")])
        todo = [l for l in lines if l.strip() and not l.startswith("#")]
        open(QUEUE, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return todo[0]


def mark_done(topic):
    lines = [l.rstrip("\n") for l in open(QUEUE, encoding="utf-8")]
    open(QUEUE, "w", encoding="utf-8").write("\n".join(("#done " + l) if l == topic else l for l in lines) + "\n")


def pick_music():
    tracks = sorted(glob.glob("music/*.mp3"))
    return random.choice(tracks) if tracks else None


def fmt(t):
    return f"{int(t // 60)}:{int(t % 60):02}"


def notify(msg, click=None):
    topic = os.getenv("NTFY_TOPIC")
    if topic:
        import requests
        try:
            requests.post(f"https://ntfy.sh/{topic}", data=msg.encode(), timeout=15,
                          headers={"Title": "lorevid", **({"Click": click} if click else {})})
        except Exception as e:
            print(f"  notify failed: {e}")


def make(topic):
    work = os.path.join("output", slugify(topic))
    for d in ("img", "audio"):
        os.makedirs(os.path.join(work, d), exist_ok=True)
    sp = os.path.join(work, "script.json")
    if os.path.exists(sp):
        plan = json.load(open(sp, encoding="utf-8"))
    else:
        plan = build_long(topic, MINUTES, STYLE)
        json.dump(plan, open(sp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    scenes = plan["scenes"]
    print(f"{len(scenes)} scenes · editor: {plan.get('editor_notes', '')}")
    seed = zlib.crc32(topic.encode()) % 1_000_000

    # images + narration
    imgs, segs, padded, words, marks, t = [], [], [], [], [], 0.0
    for i, s in enumerate(scenes):
        if i == 0 or s["chapter"] != scenes[i - 1]["chapter"]:
            marks.append((t, plan["chapters"][s["chapter"]]["title"]))
        print(f"[{i+1}/{len(scenes)}] {s['narration'][:70]}")
        img = os.path.join(work, "img", f"{i:04}.jpg")
        images.generate(images.full_prompt(s, plan), img, seed + i)
        wav = os.path.join(work, "audio", f"{i:04}.wav")
        if not os.path.exists(wav):
            tts.speak(s["narration"], wav)
        d = tts.duration(wav)
        seg = d + PAD + (0.5 if i + 1 < len(scenes) and scenes[i + 1]["chapter"] != s["chapter"] else 0)
        pw = os.path.join(work, "audio", f"{i:04}.pad.wav")
        if not os.path.exists(pw):
            video.pad_audio(wav, seg, pw)
        words += tts.word_times(s["narration"], t, d)
        imgs.append(img); segs.append(seg); padded.append(pw)
        t += seg

    narration = os.path.join(work, "narration.wav")
    video.concat_audio(padded, narration)
    srt = os.path.join(work, "captions.srt")
    tts.write_srt(words, srt)

    thumb_raw = os.path.join(work, "thumb_raw.jpg")
    images.generate(f"{plan['thumbnail_prompt']}. {plan['era_setting']}. {STYLE}. extreme emotion, "
                    "dramatic rim lighting, high contrast, face in right half of frame, no text", thumb_raw, seed + 777)
    thumb = os.path.join(work, "thumbnail.jpg")
    video.thumbnail(thumb_raw, plan.get("thumbnail_text", ""), thumb)

    final = os.path.join(work, "final.mp4")
    music = pick_music()
    if not os.path.exists(final):
        print("Rendering film...")
        video.render_long(imgs, segs, narration, final, marks, music, work)

    chapters_txt = "\n".join(f"{fmt(a)} {title}" for a, title in marks)
    description = (f"{plan['description']}\n\nChapters:\n{chapters_txt}\n\n"
                   "Narration and illustrations are AI-assisted; scripts are researched and reviewed.\n\n"
                   + " ".join(plan.get("hashtags", ["#history"])))
    meta = {"title": plan["title"], "description": description, "tags": plan.get("tags", []),
            "final": final, "thumb": thumb, "srt": srt, "shorts": []}

    # shorts
    for si, sh in enumerate(plan.get("shorts", [])[:2]):
        sdir = os.path.join(work, f"short{si}"); os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, "short.mp4")
        clips, pads, swords, st = [], [], [], 0.0
        for k, sc in enumerate(sh["scenes"]):
            wav = os.path.join(sdir, f"{k:02}.wav")
            if not os.path.exists(wav):
                tts.speak(sc["narration"], wav, speed=1.05)
            d = tts.duration(wav)
            seg = d + 0.12
            pw = os.path.join(sdir, f"{k:02}.pad.wav"); video.pad_audio(wav, seg, pw)
            ref = min(max(int(sc.get("ref", k)), 0), len(imgs) - 1)
            c = os.path.join(sdir, f"{k:02}.mp4")
            if not os.path.exists(c):
                video.short_clip(imgs[ref], seg, c, k)
            swords += tts.word_times(sc["narration"], st, d)
            clips.append(c); pads.append(pw); st += seg
        if not os.path.exists(out):
            sn = os.path.join(sdir, "narration.wav"); video.concat_audio(pads, sn)
            ssrt = os.path.join(sdir, "captions.srt"); tts.write_srt(swords, ssrt, max_words=3)
            video.render_short(clips, sn, ssrt, sh["title"], out, music)
        title = sh["title"] if "#shorts" in sh["title"].lower() else sh["title"] + " #shorts"
        meta["shorts"].append({"title": title, "final": out,
                               "description": f"{sh.get('description', '')}\n\nFull story: {plan['title']}"})
    json.dump(meta, open(os.path.join(work, "meta.json"), "w"), indent=2, ensure_ascii=False)
    print(f"Done: {final} ({fmt(t)})")
    return work, meta


def publish(meta, privacy):
    from upload import upload
    vid = upload(meta["final"], meta["title"], meta["description"], meta["tags"], meta["thumb"], meta["srt"], privacy)
    links = [f"https://studio.youtube.com/video/{vid}/edit"]
    for sh in meta["shorts"]:
        sid = upload(sh["final"], sh["title"], sh["description"], meta["tags"][:10], privacy=privacy)
        links.append(f"https://studio.youtube.com/video/{sid}/edit")
    notify(f"New video ready to review ({privacy}): {meta['title']}\n" + "\n".join(links), links[0])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", nargs="?")
    ap.add_argument("--next-topic", action="store_true")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--privacy", default=os.getenv("PRIVACY", "private"), choices=["private", "unlisted", "public"])
    a = ap.parse_args()
    topic = next_topic() if a.next_topic else a.topic
    if not topic:
        ap.error("give a topic or --next-topic")
    print(f"== {topic}")
    try:
        work, meta = make(topic)
        if a.upload:
            publish(meta, a.privacy)
        if a.next_topic:
            mark_done(topic)
    except Exception as e:
        notify(f"Run failed for '{topic}': {str(e)[:300]}")
        raise
