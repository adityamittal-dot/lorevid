"""Reserve filler: standard evergreen longs (plus their Shorts) kept in scripts/reserve, moved into scripts/backlog
when a scheduled long slot is still empty, so the publish schedule never gaps.

  python reserve.py fill [--dry-run] [--today YYYY-MM-DD] [--hour H]
  python reserve.py check

fill: for every date from today (UTC) through tomorrow, for each long slot channel.json's schedule gives it, if
`<date>-L` is not in scripts/backlog, queue, done or failed, move the oldest reserve set (R##-L + R##-Ls1/Ls2,
preferring the series plan.py plans for that slot) into the backlog under that date. A chapter-reaction day
(Monday) is only filled on the day itself from 06:00 UTC, so a fresh reaction pushed before the 06:15 UTC run
wins; its leftover Short (Ls2) is parked in scripts/spare. --today/--hour simulate the clock for testing.
Pure stdlib.
"""
import datetime
import json
import os
import re
import subprocess
import sys

import plan

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
LOOKUP_DIRS = ["scripts/backlog", "scripts/queue", "scripts/done", "scripts/failed"]


def _present(repo, sid):
    return any(os.path.exists(os.path.join(repo, d, sid + ".json")) for d in LOOKUP_DIRS)


def reserve_sets(repo):
    """[(R## id, series)] oldest first; only sets whose long and Ls1 both exist."""
    out = []
    for rid, series, _title, _deep in plan.reserve_sets(repo):
        if all(os.path.exists(os.path.join(repo, "scripts", "reserve", f"{rid}-{p}.json")) for p in ("L", "Ls1")):
            out.append((rid, series))
    return out


def _mv(repo, src, dst):
    s, d = os.path.join(repo, src), os.path.join(repo, dst)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    r = subprocess.run(["git", "mv", src, dst], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        os.replace(s, d)


def _rewrite(repo, path, **fields):
    full = os.path.join(repo, path)
    with open(full, encoding="utf-8") as f:
        data = json.load(f)
    for k, v in fields.items():
        if k in data or k == "id":
            data[k] = v
    with open(full, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _move_set(repo, rid, date_str, lid, react):
    """Move one reserve set into the backlog as `lid`. Returns the new backlog ids."""
    moved = []
    for suffix, new in (("L", lid), ("Ls1", lid + "s1"), ("Ls2", lid + "s2")):
        src = f"scripts/reserve/{rid}-{suffix}.json"
        if not os.path.exists(os.path.join(repo, src)):
            continue
        notes_src = f"notes/reserve/{rid}-{suffix}.md"
        if suffix == "Ls2" and react:        # a reaction day has only 1 Short; park the leftover
            _mv(repo, src, f"scripts/spare/{rid}-Ls2.json")
            if os.path.exists(os.path.join(repo, notes_src)):
                _mv(repo, notes_src, f"notes/spare/{rid}-Ls2.md")
            continue
        dst = f"scripts/backlog/{new}.json"
        _mv(repo, src, dst)
        fields = {"id": new}
        if suffix == "L":
            fields["filled_from_reserve"] = rid   # validate_script.py skips the rotation gate for reserve fills
        if suffix != "L":
            fields["related_long"] = lid
        _rewrite(repo, dst, **fields)
        if os.path.exists(os.path.join(repo, notes_src)):
            _mv(repo, notes_src, f"notes/{new}.md")
        moved.append(new)
    return moved


def cmd_fill(repo, dry, today, hour):
    cfg = plan.load_channel(repo)
    schedule = cfg.get("long_schedule", [])
    sets = reserve_sets(repo)
    n_fills = 0
    for off in (0, 1):
        day = today + datetime.timedelta(days=off)
        date_str = day.isoformat()
        for k in range(1, plan.longs_per_day(schedule, day) + 1):
            lid = plan.long_id(date_str, k)
            if _present(repo, lid):
                continue
            react = k == 1 and plan.is_react_day(schedule, day)
            if react and not (off == 0 and hour >= 6):
                print(f"WAIT {lid}: chapter-reaction slot, fills only on the day from 06:00 UTC")
                continue
            if not sets:
                print(f"RESERVE EMPTY: nothing to fill {lid} with")
                continue
            want = plan.slot_series(repo, day, lid)
            pick = next((s for s in sets if s[1] == want), sets[0])
            sets.remove(pick)
            rid = pick[0]
            tag = "DRY-RUN " if dry else ""
            if dry:
                ids = [lid, lid + "s1"] + ([] if react else [lid + "s2"])
            else:
                ids = _move_set(repo, rid, date_str, lid, react)
            print(f"{tag}FILL {lid} <- {rid} (series={pick[1]}, planned={want}{', react day' if react else ''}): "
                  f"{' '.join(ids)}")
            n_fills += 1
    if not n_fills:
        print("nothing to fill")
    return 0


def cmd_check(repo):
    n = len(reserve_sets(repo))
    print(f"reserve sets remaining: {n}")
    return 0


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ("fill", "check"):
        print(__doc__)
        return 1
    now = datetime.datetime.now(datetime.timezone.utc)
    today, hour = now.date(), now.hour
    if "--today" in args:
        today = datetime.date.fromisoformat(args[args.index("--today") + 1])
    if "--hour" in args:
        hour = int(args[args.index("--hour") + 1])
    if args[0] == "check":
        return cmd_check(REPO_DIR)
    return cmd_fill(REPO_DIR, "--dry-run" in args, today, hour)


if __name__ == "__main__":
    sys.exit(main())
