"""Check a writer script before committing:  python validate_script.py scripts/2026-09-24.json"""
import json, sys

MOODS = {"calm", "warm", "melancholy", "mystery", "epic_soft"}
p = json.load(open(sys.argv[1], encoding="utf-8"))
err = []
for k in ["topic", "title", "description", "hashtags", "tags", "era_setting", "thumbnail_prompt", "thumbnail_text",
          "music_mood", "characters", "chapters", "shorts"]:
    if k not in p:
        err.append(f"missing key: {k}")
if p.get("music_mood") not in MOODS:
    err.append(f"music_mood must be one of {sorted(MOODS)}")
if len(p.get("title", "")) > 100:
    err.append("title longer than 100 chars")
ids = {c.get("id") for c in p.get("characters", [])}
scenes = [s for ch in p.get("chapters", []) for s in ch.get("scenes", [])]
words = 0
for i, s in enumerate(scenes):
    n = len(s.get("narration", "").split())
    words += n
    if not s.get("image_prompt"):
        err.append(f"scene {i}: no image_prompt")
    if not 10 <= n <= 40:
        err.append(f"scene {i}: narration has {n} words (want 18-28)")
    for c in s.get("characters", []):
        if c not in ids:
            err.append(f"scene {i}: unknown character id {c}")
for j, sh in enumerate(p.get("shorts", [])):
    for s in sh.get("scenes", []):
        if not 0 <= int(s.get("ref", -1)) < len(scenes):
            err.append(f"short {j}: bad ref {s.get('ref')}")
minutes = words / 130
print(f"{len(p.get('chapters', []))} chapters, {len(scenes)} scenes, {words} words ≈ {minutes:.1f} min at bedtime pace")
if not 8.5 <= minutes <= 11.5:
    err.append(f"length {minutes:.1f} min; aim for 9.5-10.5 min (~1250-1350 words)")
print("\n".join(err) if err else "OK")
sys.exit(1 if err else 0)
