"""Script writing, 5 Claude calls:
  1. strategist: picks today's topic + angle from the queue using live YouTube trends
  2. research + plan
  3. draft
  4. harsh critic: scores the draft as a demanding viewer and a YouTube strategist
  5. editor: rewrites using the critique + image prompts + 2 Shorts"""
import json
from llm import chat_json

MOODS = ["calm", "warm", "melancholy", "mystery", "epic_soft"]

SYSTEM = """You are the head writer of a premium YouTube history channel making "Your Life as a ___" videos:
immersive SECOND-PERSON narration ("You wake before dawn..."), calm, cinematic, slightly dramatic, grounded
in accurate everyday detail (food, clothing, money, laws, work, dangers, social rank, beliefs).
The viewing experience: a comforting, beautifully told story people put on at bedtime, while resting or
unwinding - absorbing but never stressful. Warm, unhurried voice; gentle rhythm; sensory detail (sounds,
smells, light, textures); moments of quiet wonder; tension that rises and resolves; a peaceful, reflective
ending. Never shouty, never clickbait inside the story, no cliffhanger shocks near the end.
Rules you never break:
- Historically accurate. If something is uncertain, frame it as "historians believe" or leave it out.
- Advertiser-friendly and YouTube-policy-safe: violence, punishment, slavery, disease and death may be
  described soberly but never graphically; no sexual content; no minors in any sexual or violent context;
  no glorification of harm; respectful to all cultures and religions.
- Original writing only. No lists or headings inside narration.
- Output valid JSON only, no commentary."""

IMAGE_RULES = ("Image prompts: describe subject, action, setting, camera framing, lighting and mood for a "
               "WIDE 16:9 painting; describe characters by their fixed look (never by name); keep the main subject "
               "in the middle of the frame; no text, no gore, no nudity, no modern objects.")


def choose_topic(candidates, trend_text, recent):
    prompt = f"""You are a ruthless YouTube strategist for this channel. Live data - top videos in the niche over the
last 60 days (views per day):
{trend_text}

Our recent uploads: {json.dumps(recent[-10:], ensure_ascii=False)}
Candidate topics from our queue: {json.dumps(candidates, ensure_ascii=False)}

Judge each candidate on current demand, click appeal, bedtime-comfort fit, and freshness vs our recent uploads.
Be blunt. You may improve the wording of a candidate, or replace all of them with a clearly stronger topic that
the data supports (still "Your Life as a ___", still ours, not a copy of a competitor title).
Return JSON: {{"verdicts": [{{"topic": "...", "score": 1-10, "why": "one blunt line"}}],
 "chosen_from_queue": "exact candidate text you are using (or null if replaced)",
 "topic": "final topic wording", "angle": "the emotional/curiosity angle that will make people click and stay",
 "trend_insights": ["3-5 concrete lessons from the data: title patterns, lengths, themes that win right now"]}}"""
    return chat_json(prompt, SYSTEM, "strategist", 4000)


def research_and_plan(topic, minutes, angle="", insights=()):
    prompt = f"""Topic: "{topic}". Angle: {angle}
What is winning in the niche right now: {json.dumps(list(insights), ensure_ascii=False)}
Length: {minutes} minutes of narration (~{minutes*130} words).
Step 1: research. Step 2: plan the story. Return JSON:
{{"title_options": ["3 strong YouTube titles, <= 65 chars, honest, curiosity-driven"],
 "title": "the best one",
 "thumbnail_text": "2-4 punchy words, caps",
 "thumbnail_prompt": "close-up of the protagonist with a strong emotion, dramatic lighting, setting hint",
 "description": "2 short engaging paragraphs (no timestamps, no hashtags)",
 "hashtags": ["#history", "4 more"],
 "tags": ["12-15 search tags"],
 "music_mood": "one of {MOODS}",
 "era_setting": "one sentence: place, years, architecture, clothing, colour palette",
 "fact_sheet": ["18-25 specific, accurate facts to use: prices, foods, routines, laws, numbers, named places"],
 "characters": [{{"id": "you", "look": "fixed visual description: age, sex, build, face, hair, clothing, colours"}},
                {{"id": "short_id", "look": "..."}}],
 "chapters": [{{"title": "evocative 2-5 word chapter title", "summary": "what happens, 2-3 sentences"}}]}}
4-5 chapters forming a full life arc with rising tension and an emotional ending. 3-5 characters."""
    return chat_json(prompt, SYSTEM, "plan", 6000)


def draft(plan, minutes):
    prompt = f"""Plan:\n{json.dumps(plan, ensure_ascii=False)}

Write the full narration (~{minutes*130} words). The first 3 sentences must hook hard (a vivid moment +
a question or stake). Use many facts from the fact sheet. Vary sentence rhythm; no repeated openings.
Split every chapter into scenes of 18-28 words (one visual moment each).
Return JSON: {{"chapters": [{{"title": "...", "scenes": ["narration", "..."]}}]}}"""
    return chat_json(prompt, SYSTEM, "draft", 12000)


def critique(plan, draft_json, trend_text):
    prompt = f"""Plan: {json.dumps({k: plan[k] for k in ("title", "chapters", "fact_sheet")}, ensure_ascii=False)}
Draft: {json.dumps(draft_json, ensure_ascii=False)}
What viewers watch right now:\n{trend_text}

Act as three harsh critics. Do not be polite; find every weakness.
1. The demanding viewer at bedtime: Where would I get bored, confused, or jolted out of the calm? Is it immersive
   and comforting? Do I feel like I am there?
2. The historian: every doubtful, anachronistic or oversimplified claim.
3. The YouTube strategist: first 30 seconds, retention dips, title/thumbnail promise vs delivery, repetition,
   AI-sounding phrases ("tapestry", "testament", "delve", "little did you know"), generic filler.
Return JSON: {{"scores": {{"hook": 1-10, "immersion": 1-10, "comfort": 1-10, "accuracy": 1-10, "pacing": 1-10,
 "originality": 1-10}}, "verdict": "2 blunt sentences", "must_fix": ["specific instruction referencing the passage"],
 "title_feedback": "is the title strong vs the trend data? suggest a better one if not"}}"""
    return chat_json(prompt, SYSTEM, "critic", 5000)


def edit_and_visualise(plan, draft_json, crit=None):
    chars = "\n".join(f'- {c["id"]}: {c["look"]}' for c in plan["characters"])
    prompt = f"""Setting: {plan['era_setting']}
Characters:\n{chars}
Fact sheet:\n{json.dumps(plan['fact_sheet'], ensure_ascii=False)}
Draft:\n{json.dumps(draft_json, ensure_ascii=False)}

Critic report (apply every must_fix; aim for 9+/10 on every score):
{json.dumps(crit or {}, ensure_ascii=False)}

You are now the editor. 1) Rewrite to fix every critic point and any historical inaccuracy, policy-unsafe or graphic line, weak hook,
repetition, or slow passage; keep length within 5%. Keep scenes 18-28 words.
2) For every scene write an image prompt. {IMAGE_RULES}
3) Write 2 YouTube Shorts (each 100-120 words, 6-8 scenes of 12-20 words) retelling the most gripping
moments; first line is a hook, last line teases the full video. Each short scene reuses the image of a long-video
scene via "ref" = the scene's global index (0-based, counting across chapters).
Return JSON:
{{"title": "final YouTube title (improve it if the critic was right)",
 "chapters": [{{"title": "...", "scenes": [{{"narration": "...", "image_prompt": "...", "characters": ["ids visible"]}}]}}],
 "shorts": [{{"title": "<= 80 chars ending with #shorts", "description": "1-2 sentences + 3 hashtags",
             "scenes": [{{"narration": "...", "ref": 0}}]}}],
 "editor_notes": "one line on what you fixed"}}"""
    return chat_json(prompt, SYSTEM, "edit", 20000)


def build_long(topic, minutes, style, strategy=None, trend_text=""):
    strategy = strategy or {}
    print("Step 2/5: research + plan")
    plan = research_and_plan(topic, minutes, strategy.get("angle", ""), strategy.get("trend_insights", []))
    print(f"  title: {plan['title']}")
    print("Step 3/5: draft")
    d = draft(plan, minutes)
    print("Step 4/5: critic")
    crit = critique(plan, d, trend_text)
    print(f"  scores {crit.get('scores')} - {crit.get('verdict')}")
    print("Step 5/5: editor + visuals + shorts")
    final = edit_and_visualise(plan, d, crit)
    plan.update(chapters=final["chapters"], shorts=final.get("shorts", []), critique=crit, strategy=strategy,
                editor_notes=final.get("editor_notes", ""), style=style, title=final.get("title") or plan["title"])
    plan["scenes"] = [dict(s, chapter=ci) for ci, ch in enumerate(plan["chapters"]) for s in ch["scenes"]]
    return plan


def new_topics(done, n=20):
    prompt = f"""Suggest {n} new "Your Life as a ___" video topics with high click potential. Mix: half popular
(Rome, medieval Europe, Vikings, Egypt, samurai, pirates, royal courts) and half under-covered (Mughal, Maratha,
Chola, Vijayanagara, Ottoman, Aztec, Mali, Joseon, Persian, Byzantine). Specific roles work best
(e.g. "Your Life as a Mughal Royal Elephant Keeper"). Avoid these already used:
{json.dumps(done[-60:], ensure_ascii=False)}
Return JSON: {{"topics": ["..."]}}"""
    return chat_json(prompt, SYSTEM, "topics", 3000)["topics"]
