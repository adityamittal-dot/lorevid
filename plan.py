"""Backlog planner: what scripts still need to be written, and how many days of content are covered.

  python plan.py next [N]     print the next N missing script IDs (format, series, publish date)
  python plan.py status       print how many days of content are already covered

Reads the schedule from channel.json ("long_schedule", "shorts_per_day") and treats any id already present
in scripts/backlog/, scripts/queue/, scripts/done/ or scripts/failed/ as already written. Pure stdlib: this
runs in the writer's cloud session and on a laptop with no extra installs.
"""
import datetime
import json
import os
import sys

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SCRIPT_DIRS = ["scripts/backlog", "scripts/queue", "scripts/done", "scripts/failed"]

# Non-long-day Shorts rotate series by weekday: One Piece every day except Tue (Naruto/Boruto) and Sat (JJK).
SHORT_SERIES_BY_WEEKDAY = {"Tue": "naruto", "Sat": "jjk"}
# Every 4th long video (counting all longs ever written, in date order) may break from One Piece.
LONG_OFF_SERIES = ["naruto", "jjk"]


def load_channel(repo_dir=REPO_DIR):
    path = os.path.join(repo_dir, "channel.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ist_today():
    """Today's date in IST (UTC+5:30), matching WRITER.md's "Date is today in IST"."""
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    return datetime.datetime.now(ist).date()


def long_days_for(schedule, day):
    """The weekday-name list in effect for `day`: the entry with the latest "from" date <= day, or [] if
    the schedule hasn't started yet."""
    best, best_from = None, None
    for entry in schedule or []:
        try:
            efrom = datetime.date.fromisoformat(entry["from"])
        except (KeyError, ValueError):
            continue
        if efrom <= day and (best_from is None or efrom > best_from):
            best, best_from = entry.get("days", []), efrom
    return best or []


def existing_ids(repo_dir=REPO_DIR):
    """{id: path} for every script already written anywhere in the pipeline (backlog/queue/done/failed)."""
    out = {}
    for sub in SCRIPT_DIRS:
        d = os.path.join(repo_dir, sub)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.endswith(".json"):
                out[name[:-5]] = os.path.join(sub, name)
    return out


def existing_long_count_before(existing, before_date_str):
    """How many long-video ids ("<date>-L") already exist with a date strictly before `before_date_str`,
    used to pick up the "every 4th long" count across sessions."""
    return sum(
        1 for sid in existing
        if sid.endswith("-L") and sid[:10] < before_date_str and _is_date(sid[:10])
    )


def _is_date(s):
    try:
        datetime.date.fromisoformat(s)
        return True
    except ValueError:
        return False


def plan_items(n, repo_dir=REPO_DIR):
    """The next n missing script items (dicts: id, format, series, publish_date), earliest first,
    skipping anything already written."""
    cfg = load_channel(repo_dir)
    schedule = cfg.get("long_schedule", [])
    shorts_per_day = int(cfg.get("shorts_per_day", 1))
    existing = existing_ids(repo_dir)

    start = ist_today() + datetime.timedelta(days=1)
    long_index = existing_long_count_before(existing, start.isoformat())

    items = []
    day = start
    for _ in range(730):            # hard stop so a broken schedule can't loop forever
        if len(items) >= n:
            break
        wd = WEEKDAYS[day.weekday()]
        date_str = day.isoformat()
        is_long_day = wd in long_days_for(schedule, day)

        if is_long_day:
            long_index += 1
            series = LONG_OFF_SERIES[(long_index // 4 - 1) % 2] if long_index % 4 == 0 else "onepiece"
            long_id = f"{date_str}-L"
            if long_id not in existing:
                items.append({"id": long_id, "format": "long", "series": series, "publish_date": date_str})
            for s in range(1, shorts_per_day + 1):
                sid = f"{date_str}-Ls{s}"
                if sid not in existing:
                    items.append({"id": sid, "format": "short", "series": series, "publish_date": date_str})
        else:
            series = SHORT_SERIES_BY_WEEKDAY.get(wd, "onepiece")
            for s in range(1, shorts_per_day + 1):
                sid = f"{date_str}-m{s}"
                if sid not in existing:
                    items.append({"id": sid, "format": "short", "series": series, "publish_date": date_str})
        day += datetime.timedelta(days=1)

    return items[:n]


def cmd_next(n):
    for item in plan_items(n):
        print(f"{item['id']}  format={item['format']}  series={item['series']}  publish={item['publish_date']}")


def cmd_status(repo_dir=REPO_DIR):
    """How many consecutive days from tomorrow already have every id they need (a "covered" streak),
    plus the total count still missing in the next 60 days."""
    cfg = load_channel(repo_dir)
    schedule = cfg.get("long_schedule", [])
    shorts_per_day = int(cfg.get("shorts_per_day", 1))
    existing = existing_ids(repo_dir)

    start = ist_today() + datetime.timedelta(days=1)
    long_index = existing_long_count_before(existing, start.isoformat())

    covered_days = 0
    missing_60d = 0
    day = start
    streak_broken = False
    for i in range(60):
        wd = WEEKDAYS[day.weekday()]
        date_str = day.isoformat()
        is_long_day = wd in long_days_for(schedule, day)
        needed = []
        if is_long_day:
            long_index += 1
            needed.append(f"{date_str}-L")
            needed += [f"{date_str}-Ls{s}" for s in range(1, shorts_per_day + 1)]
        else:
            needed += [f"{date_str}-m{s}" for s in range(1, shorts_per_day + 1)]
        day_missing = [sid for sid in needed if sid not in existing]
        missing_60d += len(day_missing)
        if not day_missing and not streak_broken:
            covered_days += 1
        else:
            streak_broken = True
        day += datetime.timedelta(days=1)

    print(f"Fully covered from tomorrow ({start.isoformat()}): {covered_days} day(s) in a row.")
    print(f"Missing scripts in the next 60 days: {missing_60d}.")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    cmd = args[0]
    if cmd == "next":
        n = int(args[1]) if len(args) > 1 else 6
        cmd_next(n)
    elif cmd == "status":
        cmd_status()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
