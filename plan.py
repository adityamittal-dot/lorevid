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


def _is_date(s):
    try:
        datetime.date.fromisoformat(s)
        return True
    except ValueError:
        return False


def longs_per_day(schedule, day):
    """How many long videos `day` gets: the matching schedule entry's "per_day" (default 1) on its days, else 0."""
    best, best_from = None, None
    for entry in schedule or []:
        try:
            efrom = datetime.date.fromisoformat(entry["from"])
        except (KeyError, ValueError):
            continue
        if efrom <= day and (best_from is None or efrom > best_from):
            best, best_from = entry, efrom
    if not best or WEEKDAYS[day.weekday()] not in best.get("days", []):
        return 0
    return int(best.get("per_day", 1))


def long_id(date_str, k):
    """The k-th long of a day (1-based): "<date>-L", "<date>-L2", ... Its Shorts are "<id>s1", "<id>s2"."""
    return f"{date_str}-L" if k == 1 else f"{date_str}-L{k}"


def day_items(schedule, shorts_per_day, day, long_index):
    """Every script a day needs, as (items, new long_index). Every 4th long breaks from One Piece; each
    long's Shorts are cut from it. A day with no long gets plain Shorts by weekday series."""
    date_str, items = day.isoformat(), []
    n_long = longs_per_day(schedule, day)
    for k in range(1, n_long + 1):
        long_index += 1
        series = LONG_OFF_SERIES[(long_index // 4 - 1) % 2] if long_index % 4 == 0 else "onepiece"
        lid = long_id(date_str, k)
        items.append({"id": lid, "format": "long", "series": series, "publish_date": date_str})
        items += [{"id": f"{lid}s{s}", "format": "short", "series": series, "publish_date": date_str}
                  for s in range(1, shorts_per_day + 1)]
    if not n_long:
        series = SHORT_SERIES_BY_WEEKDAY.get(WEEKDAYS[day.weekday()], "onepiece")
        items += [{"id": f"{date_str}-m{s}", "format": "short", "series": series, "publish_date": date_str}
                  for s in range(1, shorts_per_day + 1)]
    return items, long_index


def _walk(repo_dir, days):
    """(day, items) for `days` days from tomorrow (IST), with long rotation counted from the schedule start
    so a date's series never shifts between sessions."""
    cfg = load_channel(repo_dir)
    schedule = cfg.get("long_schedule", [])
    shorts_per_day = int(cfg.get("shorts_per_day", 1))
    start = ist_today() + datetime.timedelta(days=1)
    first = datetime.date.fromisoformat(schedule[0]["from"]) if schedule else start
    long_index = 0
    day = min(first, start)
    while day < start:
        long_index += longs_per_day(schedule, day)
        day += datetime.timedelta(days=1)
    for _ in range(days):
        items, long_index = day_items(schedule, shorts_per_day, day, long_index)
        yield day, items
        day += datetime.timedelta(days=1)


def plan_items(n, repo_dir=REPO_DIR):
    """The next n missing script items (dicts: id, format, series, publish_date), earliest first,
    skipping anything already written."""
    existing = existing_ids(repo_dir)
    out = []
    for _, items in _walk(repo_dir, 730):
        out += [it for it in items if it["id"] not in existing]
        if len(out) >= n:
            break
    return out[:n]


def cmd_next(n):
    for item in plan_items(n):
        print(f"{item['id']}  format={item['format']}  series={item['series']}  publish={item['publish_date']}")


def cmd_status(repo_dir=REPO_DIR):
    """How many consecutive days from tomorrow already have every id they need (a "covered" streak),
    plus the total count still missing in the next 60 days."""
    existing = existing_ids(repo_dir)
    start = ist_today() + datetime.timedelta(days=1)
    covered_days, missing_60d, streak_broken = 0, 0, False
    for _, items in _walk(repo_dir, 60):
        day_missing = [it for it in items if it["id"] not in existing]
        missing_60d += len(day_missing)
        if not day_missing and not streak_broken:
            covered_days += 1
        else:
            streak_broken = True

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
