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
VOICES = {"bm_george", "bm_fable", "bm_lewis", "am_michael", "am_onyx", "bf_emma", "bf_isabella", "af_heart", "af_bella"}
TONES = {"calm", "warm", "tender", "sad", "awe", "tense", "urgent", "reflective"}
if p.get("narrator_voice") not in VOICES:
    err.append(f"narrator_voice must be one of {sorted(VOICES)}")
if p.get("ambience") not in {"rain", "wind", "night", "fire", "none"}:
    err.append("ambience must be one of rain, wind, night, fire, none")
th = p.get("thumbnails", [])
if len(th) != 3 or any(len(t.get("text", "").split()) > 4 or not t.get("prompt") for t in th):
    err.append("thumbnails: need exactly 3, each with text (<= 4 words), highlight and prompt")
if not p.get("thumbnail_label"):
    err.append("thumbnail_label missing (era/place, 2-3 words)")
if len(p.get("title", "")) > 100:
    err.append("title longer than 100 chars")
ids = {c.get("id") for c in p.get("characters", [])}
scenes = [s for ch in p.get("chapters", []) for s in ch.get("scenes", [])]
words = 0
for i, s in enumerate(scenes):
    n = len(s.get("narration", "").split())
    words += n
    if s.get("tone") not in TONES:
        err.append(f"scene {i}: tone must be one of {sorted(TONES)}")
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
# ---- evidence that the process was followed (notes/<date>/) ----
import os, re
date = os.path.splitext(os.path.basename(sys.argv[1]))[0]
nd = os.path.join("notes", date)
def note(name):
    p = os.path.join(nd, name)
    if not os.path.exists(p):
        err.append(f"missing {p} (see WRITER.md)")
        return ""
    return open(p, encoding="utf-8").read()
URL = r"https?://[^\s)\]>]+"
t = note("trends.md")
if t:
    q = t.split("## Searches")[-1].split("##")[0] if "## Searches" in t else ""
    if len([l for l in q.splitlines() if l.strip()]) < 6:
        err.append("trends.md: list at least 6 searches under '## Searches'")
    if len(set(re.findall(URL, t))) < 6:
        err.append("trends.md: needs at least 6 distinct source URLs in findings")
if note("topic.md") and "Chosen:" not in note("topic.md"):
    err.append("topic.md: add 'Chosen:' and 'Angle:' lines")
r = note("research.md")
if r:
    facts = [l for l in r.splitlines() if re.match(r"\s*\d+\.", l) and re.search(URL, l)]
    domains = {re.sub(r"^www\.", "", re.findall(r"https?://([^/\s]+)", l)[0]) for l in facts}
    if len(facts) < 20:
        err.append(f"research.md: {len(facts)} numbered facts with a source URL (need 20+)")
    if len(domains) < 5:
        err.append(f"research.md: facts come from {len(domains)} websites (need 5+ different sources)")
d1 = note("draft1.md")
if d1 and len(d1.split()) < 900:
    err.append("draft1.md: save the full first draft (it looks too short)")
c = note("critique.md")
if c:
    for sec in ["## Bedtime viewer", "## Historian", "## YouTube strategist", "## Round 1 scores",
                "## Must fix", "## Round 2 scores"]:
        if sec not in c:
            err.append(f"critique.md: missing section '{sec}'")
    mf = c.split("## Must fix")[-1].split("## Round 2")[0] if "## Must fix" in c else ""
    if len(re.findall(r"^\s*\d+\.", mf, re.M)) < 8:
        err.append("critique.md: 'Must fix' needs at least 8 numbered items")
if d1 and scenes:
    final = " ".join(s.get("narration", "") for s in scenes)
    a, b = set(d1.lower().split()), set(final.lower().split())
    if a and len(a & b) / len(a | b) > 0.9:
        err.append("final script is almost identical to draft1.md; apply the critic's must-fix list")
low = [k for k, v in (p.get("critic_scores") or {}).items() if isinstance(v, (int, float)) and v < 9]
if not p.get("critic_scores"):
    err.append("critic_scores missing")
elif low:
    err.append(f"critic_scores below 9 for {low}: do another critic + rewrite round")

minutes = words / 130
print(f"{len(p.get('chapters', []))} chapters, {len(scenes)} scenes, {words} words ≈ {minutes:.1f} min at bedtime pace")
if not 8.5 <= minutes <= 11.5:
    err.append(f"length {minutes:.1f} min; aim for 9.5-10.5 min (~1250-1350 words)")
print("\n".join(err) if err else "OK")
sys.exit(1 if err else 0)
