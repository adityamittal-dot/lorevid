"""Daily run: next topic -> Claude script -> images -> voice -> 10-min film + 2 Shorts -> private upload -> notify.

  python pipeline.py --next-topic --upload        # what GitHub Actions runs
  python pipeline.py "Your Life as a Roman Gladiator"
Everything is cached in output/<slug>/, so re-running resumes where it stopped.
"""
import argparse, glob, json, os, random, re, zlib
from dotenv import load_dotenv

load_dotenv()
import images, tts, video
import trends
from script_gen import MOODS, build_long, choose_topic, new_topics

STYLE = os.getenv("STYLE", "richly detailed semi-realistic digital oil painting, historical illustration, "
                           "cinematic volumetric lighting, warm muted earthy palette, soft painterly brushwork, "
                           "atmospheric depth, masterpiece")
MINUTES = int(os.getenv("MINUTES", "10"))
PAD = 0.7            # calm pause after each scene (s)
QUEUE = "topics/long.txt"


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def queue_candidates(n=6):
    lines = [l.rstrip("\n") for l in open(QUEUE, encoding="utf-8")] if os.path.exists(QUEUE) else []
    todo = [l for l in lines if l.strip() and not l.startswith("#")]
    if not todo:
        print("Topic queue empty — asking Claude for new topics")
        lines += new_topics([l[6:] for l in lines if l.startswith("#done ")])
        todo = [l for l in lines if l.strip() and not l.startswith("#")]
        open(QUEUE, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return todo[:n], [l[6:] for l in lines if l.startswith("#done ")]


def plan_topic(forced=None):
    """Strategist picks today's topic from the queue using live trends. Returns (topic, queue_item, strategy, trend_text)."""
    print("Step 1/5: trends + strategist")
    trend_text = trends.summary(trends.fetch())
    cands, done = queue_candidates()
    if forced:
        cands = [forced]
    s = choose_topic(cands, trend_text, done)
    for v in s.get("verdicts", []):
        print(f"  {v.get('score')}/10 {v.get('topic')} - {v.get('why')}")
    topic = s.get("topic") or cands[0]
    print(f"  chosen: {topic} | angle: {s.get('angle')}")
    return topic, (s.get("chosen_from_queue") or (cands[0] if forced else None)), s, trend_text


def mark_done(queue_item, topic):
    lines = [l.rstrip("\n") for l in open(QUEUE, encoding="utf-8")]
    if queue_item in lines:
        lines = [("#done " + topic) if l == queue_item else l for l in lines]
    else:
        lines.append("#done " + topic)
    open(QUEUE, "w", encoding="utf-8").write("\n".join(lines) + "\n")


def pick_music(mood, work):
    """music/<mood>/*.mp3 first, then any track in music/, else a generated soft ambient pad."""
    for pattern in (f"music/{mood}/*.mp3", "music/*/*.mp3", "music/*.mp3"):
        tracks = sorted(glob.glob(pattern))
        if tracks:
            pick = random.choice(tracks)
            print(f"  music: {pick}")
            return pick
    print("  music: no tracks in music/ - using generated ambient pad")
    return video.ambient_pad(os.path.join(work, "pad.wav"), mood)


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


def current_style():
    """Rotate the art style every N long videos (N from styles.json; each video also carries 2 Shorts)."""
    try:
        cfg = json.load(open("styles.json"))
    except FileNotFoundError:
        return {"name": "painted", "prompt": STYLE}
    done = len(glob.glob("scripts/done/*.json"))
    st = cfg["styles"][(done // cfg.get("every", 15)) % len(cfg["styles"])]
    print(f"art style: {st['name']} (video #{done + 1}, changes every {cfg.get('every', 15)})")
    return st


def normalise(plan):
    st = current_style()
    plan["style"] = plan.get("style_override") or st["prompt"]
    plan["style_name"] = st["name"]
    plan["scenes"] = [dict(s, chapter=ci) for ci, ch in enumerate(plan["chapters"]) for s in ch["scenes"]]
    return plan


def make(topic, strategy=None, trend_text="", plan=None):
    work = os.path.join("output", slugify(topic))
    for d in ("img", "audio"):
        os.makedirs(os.path.join(work, d), exist_ok=True)
    sp = os.path.join(work, "script.json")
    if plan is not None:
        plan = normalise(plan)
        json.dump(plan, open(sp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    elif os.path.exists(sp):
        plan = json.load(open(sp, encoding="utf-8"))
    else:
        plan = build_long(topic, MINUTES, STYLE, strategy, trend_text)
        json.dump(plan, open(sp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    scenes = plan["scenes"]
    print(f"{len(scenes)} scenes · editor: {plan.get('editor_notes', '')}")
    seed = zlib.crc32(topic.encode()) % 1_000_000

    # images + narration
    imgs, segs, padded, words, marks, t = [], [], [], [], [], 0.0
    voice = plan.get("narrator_voice") if plan.get("narrator_voice") in tts.VOICES else None
    print(f"narrator: {voice or tts.KOKORO_VOICE}")
    for i, s in enumerate(scenes):
        tone = tts.TONES.get(s.get("tone", "calm"), tts.TONES["calm"])
        if i == 0 or s["chapter"] != scenes[i - 1]["chapter"]:
            marks.append((t, plan["chapters"][s["chapter"]]["title"]))
        print(f"[{i+1}/{len(scenes)}] {s['narration'][:70]}")
        img = os.path.join(work, "img", f"{i:04}.jpg")
        images.generate(images.full_prompt(s, plan), img, seed + i)
        wav = os.path.join(work, "audio", f"{i:04}.wav")
        if not os.path.exists(wav):
            tts.speak(s["narration"], wav, speed=0.9 * tone[0], voice=voice)
        d = tts.duration(wav)
        seg = d + tone[1] + (1.2 if i + 1 < len(scenes) and scenes[i + 1]["chapter"] != s["chapter"] else 0)
        pw = os.path.join(work, "audio", f"{i:04}.pad.wav")
        if not os.path.exists(pw):
            video.pad_audio(wav, seg, pw)
        words += tts.word_times(s["narration"], t, d)
        imgs.append(img); segs.append(seg); padded.append(pw)
        t += seg

    narration = os.path.join(work, "narration.wav")
    video.concat_audio(padded, narration)
    narration = video.add_ambience(narration, plan.get("ambience", "none"), os.path.join(work, "narration_amb.wav"))
    srt = os.path.join(work, "captions.srt")
    tts.write_srt(words, srt)

    # 3 thumbnail variants (upload uses #1; use YouTube Studio "Test & compare" to A/B test all three)
    variants = plan.get("thumbnails") or [{"text": plan.get("thumbnail_text", ""), "prompt": plan["thumbnail_prompt"]}]
    thumbs = []
    for k, tv in enumerate(variants[:3]):
        raw = os.path.join(work, f"thumb_raw{k}.jpg")
        images.generate(f"{tv['prompt']}. {plan['era_setting']}. {plan['style']}. extreme close-up of the face, intense "
                        "readable emotion, eyes toward the viewer, face filling the right half of the frame, dark "
                        "simple background on the left, dramatic rim light, high contrast, vivid colours, no text",
                        raw, seed + 777 + k)
        tp = os.path.join(work, f"thumbnail{k + 1}.jpg")
        video.thumbnail(raw, tv.get("text", ""), tp, tv.get("highlight", ""), plan.get("thumbnail_label", ""))
        thumbs.append(tp)
    thumb = thumbs[0]

    final = os.path.join(work, "final.mp4")
    music = pick_music(plan.get("music_mood", "calm") if plan.get("music_mood") in MOODS else "calm", work)
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
                tts.speak(sc["narration"], wav, speed=1.0, voice=voice)
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


def publish(meta, privacy, reserve=False):
    from upload import upload
    vid = upload(meta["final"], meta["title"], meta["description"], meta["tags"], meta["thumb"],
                 None if reserve else meta["srt"], privacy)   # reserve: skip captions to save upload quota
    links = [f"https://studio.youtube.com/video/{vid}/edit"]
    for sh in meta["shorts"]:
        sid = upload(sh["final"], sh["title"], sh["description"], meta["tags"][:10], privacy=privacy)
        links.append(f"https://studio.youtube.com/video/{sid}/edit")
    head = "Reserve video saved (private, schedule it later)" if reserve else f"New video ready to review ({privacy})"
    notify(f"{head}: {meta['title']}\n" + "\n".join(links), links[0])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", nargs="?")
    ap.add_argument("--next-topic", action="store_true")
    ap.add_argument("--reserve", action="store_true", help="reserve render: upload privately, keep for later")
    ap.add_argument("--script", help="render a script written by the Claude writer session (scripts/*.json)")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--privacy", default=os.getenv("PRIVACY", "private"), choices=["private", "unlisted", "public"])
    a = ap.parse_args()
    if a.script:
        plan = json.load(open(a.script, encoding="utf-8"))
        topic, queue_item, strategy, trend_text = plan["topic"], plan.get("queue_item"), None, ""
    elif a.next_topic or a.topic:
        plan = None
        topic, queue_item, strategy, trend_text = plan_topic(None if a.next_topic else a.topic)
    else:
        ap.error("give --script, a topic, or --next-topic")
    print(f"== {topic}")
    try:
        work, meta = make(topic, strategy, trend_text, plan)
        if a.upload:
            publish(meta, "private" if a.reserve else a.privacy, a.reserve)
        if a.reserve:
            os.makedirs("scripts/reserve/uploaded", exist_ok=True)
            os.replace(a.script, os.path.join("scripts/reserve/uploaded", os.path.basename(a.script)))
        else:
            mark_done(queue_item, topic)
        if a.script and not a.reserve:
            os.makedirs("scripts/done", exist_ok=True)
            os.replace(a.script, os.path.join("scripts/done", os.path.basename(a.script)))
    except Exception as e:
        if os.getenv("FINAL_ATTEMPT", "1") == "1":     # the workflow retries; only buzz the phone on the last try
            notify(f"Run failed for '{topic}': {str(e)[:300]}")
        raise
