# Cloud batch session (paid from the Claude cloud-session credit)

All lorevid writing happens here. Start it **by hand** at claude.ai/code on this repo, never as a scheduled routine
(routines billed the Pro plan on 2026-10-09). Pick **Haiku 5.5** as the session model. Paste:

```text
Follow CLOUD_BATCH.md exactly.
```

---

**Budget: about $5 for 20 scripts.** The first batch cost $15. Most of that was long agent loops that re-sent big
contexts every turn, plus a separate fact-check round. Every rule below is there to cut turns and context.

## Models
- You (main session, Haiku 5.5): plan, hand out IDs, push. Never write or review scripts yourself.
- Writers: `model: "haiku"`. One writer per long video; it also writes that long's Short.
- Editor: one `model: "sonnet"` pass per long video, reading only the finished script (no research).

## Steps
1. Run `python plan.py next 20` and `python -c "import json,glob;print('\n'.join(json.load(open(f))['title'] for f in
   sorted(glob.glob('scripts/*/*.json'))[-60:]))"` (recent titles). Don't read WRITER.md yourself.
2. Pick the topics yourself up front, one line each, all different and not in the recent titles. Then start one Haiku
   writer per long ID **in parallel** with: its IDs (long + `<long-id>s1`), its topic, the full topic list, and this
   brief:
   > Read WRITER.md once. Research with **at most 6 WebSearch calls** and no WebFetch (the sentences you use must
   > come from search results). Write the long JSON and notes with **one Write call each**, then the Short the same
   > way, reusing the same research. Notes need Sources (3+ URLs from your searches), Angle, Self-review, and Fact
   > check (list each claim and the search result that supports it; drop any claim you couldn't support). Run
   > `python validate_script.py` on both and fix all errors in a single Edit per file. Don't touch pronounce.json or
   > any other file. Don't commit. Reply only with the IDs and "ok" or the remaining errors.
3. When a writer finishes, start one Sonnet editor for that long with this brief:
   > Read WRITER.md section 6 (Long Video Rules) and scripts/backlog/<id>.json. Rewrite only the weak lines
   > (flat hooks, written-not-spoken sentences, slow chapters) in one Edit pass, without adding new facts. Then add
   > `## Editor review` to notes/<id>.md with honest scores written like `hook: 8/10`, rewriting until every score
   > is 8+. Run `python validate_script.py scripts/backlog/<id>.json` until it passes. Reply only "ok" or the errors.
4. Commit once: `git add scripts/backlog notes && git commit -m "script: <ids>"`, then push to the branch this
   session is set up to use.
5. Reply with `python plan.py status` and the pushed IDs. Nothing else.
