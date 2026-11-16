# Monday chapter reaction (one Claude Code session, by hand)

Monday's long is a reaction to the One Piece chapter that released on Sunday. Run this in a single Claude Code session
(local or claude.ai/code on this repo), **after the official Sunday chapter is out on MANGA Plus**, and push to `main`
**before 06:15 UTC Monday**. If nothing is pushed by then, `reserve.py fill` (render.yml, 06:15 UTC run) fills the slot
with a standard reserve long, so skipping a week costs nothing. Sunday ~12:00 UTC an ntfy reminder fires.

Pick **Sonnet** as the session model. Paste:

```text
Follow REACTION.md exactly.
```

---

## Steps
1. Run `python plan.py next 3`. The `CHAPTER-REACTION` id is the one to write: `<date>-L` plus its **1** Short `<date>-Ls1`.
   Write nothing else. If the `<date>-L` file already exists in scripts/backlog, stop and say so.
2. Research the new chapter: **official release only** (MANGA Plus, the Viz/Shueisha release, Oda's SBS). No leaks, no
   raw scans, no unofficial spoiler threads. Use WebSearch for the chapter number, what happens panel by panel, and the
   strongest fan reactions and theories (r/OnePiece, the wiki chapter page). Then `grep -n` `data/wiki/` packs for the
   background facts and their [Ch. N] citations the reaction leans on.
3. Start **one Sonnet writer** (Agent call, `model: "sonnet"`) for the long and its Short, with the chapter research, the
   ids, and this brief:
   > Read WRITER.md once (section 6: Long Video Rules, Format rotation, Chapter reaction (Mon)). Write
   > `scripts/backlog/<id>.json` (`"style": "reaction"`, 1800-2400 words) and `scripts/backlog/<id>s1.json`, plus
   > `notes/<id>.md` and `notes/<id>s1.md`, with **one Write call each**. Title: `<Topic> In One Piece <N> Explained` or
   > `One Piece <N>: <hook>` (the chapter number in the title, no leaks, searchable subject in the first 4 words). Line 1
   > states the title's subject and claim; chapter 1 (the cold open) is at most 110 words. The Short argues ONE side
   > point of the long, never its headline answer, and carries `end_text` plus a bridge line (WRITER.md, "Shorts vs
   > their long video"). Notes need Sources (3+ URLs), Angle, Self-review and a Fact check (each claim and the source that
   > supports it; drop what you couldn't support). Run `python validate_script.py` on both and fix all errors. List every
   > name not in pronounce.json as a `New names:` line in the notes. Don't commit. Reply only with the ids and "ok" or the remaining errors.
4. Then a **separate** Sonnet editor pass (a second Agent call, `model: "sonnet"`; never the writer, never yourself):
   > Read WRITER.md section 6 (Long Video Rules), scripts/backlog/<id>.json and the notes' Fact check. First check the
   > premise: is every character actually where and when the script puts them, and does the chapter really contain what
   > it claims? If the premise is false, reply "FALSE PREMISE" and change nothing. Then grep `data/wiki/` packs for every
   > chapter number and named event and fix what doesn't match. Then fix the opening: line 1 says the title's subject and
   > claim, and chapter 1 is at most 110 words. Then rewrite only the weak lines in one Edit pass, without adding new
   > facts. Then add `## Editor review` to notes/<id>.md, starting with the line `Reviewer: independent editor`, with
   > honest scores written like `hook: 8/10`, rewriting until every score is 8+. Never lower the bar to pass. Run
   > `python validate_script.py scripts/backlog/<id>.json` until it passes. Reply only "ok" or the errors.
5. If the editor said "FALSE PREMISE", or the script still fails validation, push nothing and say why (the reserve fills the slot).
6. Append the notes' `New names:` to `data/pronounce_missing.md` as `- Name (<id>)`. Commit once:
   `git add scripts/backlog notes data/pronounce_missing.md && git commit -m "script: <ids>"`, then push to `main`
   (`git pull --rebase origin main` first if rejected). The push must land before 06:15 UTC Monday.
7. Reply with the pushed ids and nothing else.
