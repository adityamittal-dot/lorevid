"""3-step script writing: research+plan -> draft -> editor pass (facts, safety, pacing) + visuals + shorts."""
import json
from llm import chat_json

SYSTEM = """You are the head writer of a premium YouTube history channel making "Your Life as a ___" videos:
immersive SECOND-PERSON narration ("You wake before dawn..."), calm, cinematic, slightly dramatic, grounded
in accurate everyday detail (food, clothing, money, laws, work, dangers, social rank, beliefs).
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


def research_and_plan(topic, minutes):
    prompt = f"""Topic: "{topic}". Length: {minutes} minutes of narration (~{minutes*140} words).
Step 1: research. Step 2: plan the story. Return JSON:
{{"title_options": ["3 strong YouTube titles, <= 65 chars, honest, curiosity-driven"],
 "title": "the best one",
 "thumbnail_text": "2-4 punchy words, caps",
 "thumbnail_prompt": "close-up of the protagonist with a strong emotion, dramatic lighting, setting hint",
 "description": "2 short engaging paragraphs (no timestamps, no hashtags)",
 "hashtags": ["#history", "4 more"],
 "tags": ["12-15 search tags"],
 "era_setting": "one sentence: place, years, architecture, clothing, colour palette",
 "fact_sheet": ["18-25 specific, accurate facts to use: prices, foods, routines, laws, numbers, named places"],
 "characters": [{{"id": "you", "look": "fixed visual description: age, sex, build, face, hair, clothing, colours"}},
                {{"id": "short_id", "look": "..."}}],
 "chapters": [{{"title": "evocative 2-5 word chapter title", "summary": "what happens, 2-3 sentences"}}]}}
4-5 chapters forming a full life arc with rising tension and an emotional ending. 3-5 characters."""
    return chat_json(prompt, SYSTEM, "plan", 6000)


def draft(plan, minutes):
    prompt = f"""Plan:\n{json.dumps(plan, ensure_ascii=False)}

Write the full narration (~{minutes*140} words). The first 3 sentences must hook hard (a vivid moment +
a question or stake). Use many facts from the fact sheet. Vary sentence rhythm; no repeated openings.
Split every chapter into scenes of 18-28 words (one visual moment each).
Return JSON: {{"chapters": [{{"title": "...", "scenes": ["narration", "..."]}}]}}"""
    return chat_json(prompt, SYSTEM, "draft", 12000)


def edit_and_visualise(plan, draft_json):
    chars = "\n".join(f'- {c["id"]}: {c["look"]}' for c in plan["characters"])
    prompt = f"""Setting: {plan['era_setting']}
Characters:\n{chars}
Fact sheet:\n{json.dumps(plan['fact_sheet'], ensure_ascii=False)}
Draft:\n{json.dumps(draft_json, ensure_ascii=False)}

You are now the strict editor. 1) Fix any historical inaccuracy, policy-unsafe or graphic line, weak hook,
repetition, or slow passage; keep length within 5%. Keep scenes 18-28 words.
2) For every scene write an image prompt. {IMAGE_RULES}
3) Write 2 YouTube Shorts (each 100-120 words, 6-8 scenes of 12-20 words) retelling the most gripping
moments; first line is a hook, last line teases the full video. Each short scene reuses the image of a long-video
scene via "ref" = the scene's global index (0-based, counting across chapters).
Return JSON:
{{"chapters": [{{"title": "...", "scenes": [{{"narration": "...", "image_prompt": "...", "characters": ["ids visible"]}}]}}],
 "shorts": [{{"title": "<= 80 chars ending with #shorts", "description": "1-2 sentences + 3 hashtags",
             "scenes": [{{"narration": "...", "ref": 0}}]}}],
 "editor_notes": "one line on what you fixed"}}"""
    return chat_json(prompt, SYSTEM, "edit", 20000)


def build_long(topic, minutes, style):
    print("Step 1/3: research + plan")
    plan = research_and_plan(topic, minutes)
    print(f"  title: {plan['title']}")
    print("Step 2/3: draft")
    d = draft(plan, minutes)
    print("Step 3/3: editor pass + visuals + shorts")
    final = edit_and_visualise(plan, d)
    plan.update(chapters=final["chapters"], shorts=final.get("shorts", []),
                editor_notes=final.get("editor_notes", ""), style=style)
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
