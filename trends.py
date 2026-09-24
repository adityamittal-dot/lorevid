"""What viewers are watching right now in this niche, from the YouTube Data API (uses the same login as
uploads; ~400 of the 10,000 daily quota units). Returns top recent videos with views, so Claude can judge
topics and titles against real demand."""
import datetime, json, os

QUERIES = ["your life as a", "history for sleep", "what life was like in", "boring history to fall asleep",
           "medieval life documentary", "ancient history bedtime story"]


def fetch(max_per_query=12, days=60, cache="trends_cache.json"):
    today = datetime.date.today().isoformat()
    if os.path.exists(cache):
        c = json.load(open(cache))
        if c.get("date") == today:
            return c["videos"]
    try:
        from googleapiclient.discovery import build
        from upload import get_credentials
        yt = build("youtube", "v3", credentials=get_credentials())
    except BaseException as e:           # no credentials locally -> run without trends
        print(f"  trends unavailable ({e})")
        return []
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = []
    for q in QUERIES[:4]:
        try:
            r = yt.search().list(q=q, part="id", type="video", order="viewCount", publishedAfter=since,
                                 maxResults=max_per_query, relevanceLanguage="en").execute()
            ids += [i["id"]["videoId"] for i in r.get("items", [])]
        except Exception as e:
            print(f"  trend search failed: {e}")
    videos = []
    for k in range(0, len(ids), 50):
        r = yt.videos().list(id=",".join(ids[k:k + 50]), part="snippet,statistics,contentDetails").execute()
        for v in r.get("items", []):
            views = int(v["statistics"].get("viewCount", 0))
            age = max(1, (datetime.datetime.utcnow() - datetime.datetime.strptime(
                v["snippet"]["publishedAt"][:19], "%Y-%m-%dT%H:%M:%S")).days)
            videos.append({"title": v["snippet"]["title"], "channel": v["snippet"]["channelTitle"],
                           "views": views, "views_per_day": views // age, "duration": v["contentDetails"]["duration"]})
    seen, out = set(), []
    for v in sorted(videos, key=lambda v: -v["views_per_day"]):
        if v["title"] not in seen:
            seen.add(v["title"]); out.append(v)
    out = out[:40]
    json.dump({"date": today, "videos": out}, open(cache, "w"), indent=1)
    print(f"  trends: {len(out)} hot videos, top: {out[0]['title'] if out else '-'}")
    return out


def summary(videos, n=30):
    return "\n".join(f"- {v['title']} | {v['channel']} | {v['views_per_day']:,} views/day | {v['duration']}"
                     for v in videos[:n]) or "(no live trend data available today)"
