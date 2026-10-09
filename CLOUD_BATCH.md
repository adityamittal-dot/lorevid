# Cloud batch session (paid from the Claude cloud-session credit)

All lorevid writing happens here. Start it **by hand** at claude.ai/code on this repo, never as a scheduled routine
(routines billed the Pro plan on 2026-10-09). Check the credit balance before and after each session. Paste:

```text
Follow CLOUD_BATCH.md exactly.
```

---

One session writes **5 days of content: the next 20 missing scripts**, so the clone/setup cost is paid once per 20
scripts instead of once per script.

1. Read WRITER.md once, in full; every rule below comes from it.
2. Run `python plan.py next 20`.
3. Give each **long** ID to its own subagent (run them in parallel), together with the Short IDs cut from it
   (`<long-id>s1`). Each subagent: reads WRITER.md, researches, writes the long video and then its Short in the same
   context (no second research pass for the Short), runs the fact-check and editor-review passes, writes
   `scripts/backlog/<id>.json` + `notes/<id>.md` for both, and runs `python validate_script.py
   scripts/backlog/<id>.json` until both pass. Tell every subagent the other subagents' topics so no two scripts in
   the batch share a topic, and none repeats the last 60 titles.
4. Push to main once at the end: `git add scripts/backlog notes && git commit -m "script: <ids>" && git pull --rebase
   origin main && git push origin main`.
5. Finish with `python plan.py status` and list the IDs you pushed.
