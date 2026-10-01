"""Channel stats and niche trends via YouTube Data API -> data/*.md."""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import upload


def parse_duration(d_str: str) -> int:
    """Parse ISO 8601 duration (PT#H#M#S, P#DT#H#M#S) into integer seconds."""
    if not d_str or not isinstance(d_str, str):
        return 0
    s = d_str.strip()
    days, hours, minutes, seconds = 0, 0, 0, 0.0
    if "T" in s:
        date_part, time_part = s.split("T", 1)
        d_m = re.findall(r"(\d+)D", date_part)
        if d_m:
            days = int(d_m[0])
        h_m = re.findall(r"(\d+)H", time_part)
        if h_m:
            hours = int(h_m[0])
        m_m = re.findall(r"(\d+)M", time_part)
        if m_m:
            minutes = int(m_m[0])
        s_m = re.findall(r"(\d+(?:\.\d+)?)S", time_part)
        if s_m:
            seconds = float(s_m[0])
    else:
        d_m = re.findall(r"(\d+)D", s)
        if d_m:
            days = int(d_m[0])
    return int(days * 86400 + hours * 3600 + minutes * 60 + seconds)


def format_duration(seconds: int) -> str:
    """Format seconds into M:SS or H:MM:SS."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def parse_rfc3339(ts_str: str) -> datetime:
    """Parse RFC 3339 timestamp string to timezone-aware UTC datetime."""
    if not ts_str:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def load_search_terms(cfg_path: Path, cap: int = 9) -> list[str]:
    """Up to `cap` search terms from channel.json, shared out by series_weights with at least 2 per series,
    so a series listed late (JJK) is never starved by an earlier one's long term list. Each term costs
    2 searches (Shorts + long) = 200 quota units a day."""
    if not cfg_path.is_file():
        return []
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"Warning: could not read {cfg_path}: {e}")
        return []
    weights = cfg.get("series_weights", {})
    pools = []
    for s in cfg.get("series", []):
        terms = list(dict.fromkeys(str(t).strip() for t in s.get("search_terms", []) if str(t).strip()))
        if terms:
            pools.append([float(weights.get(s.get("id"), 1)), terms])
    quota = {i: min(len(t), 2) for i, (_, t) in enumerate(pools)}
    total_w = sum(w for w, _ in pools) or 1.0
    while sum(quota.values()) < cap:                     # hand the rest out by weight
        open_ = [i for i, (_, t) in enumerate(pools) if quota[i] < len(t)]
        if not open_:
            break
        i = max(open_, key=lambda j: pools[j][0] / total_w * cap - quota[j])
        quota[i] += 1
    out: list[str] = []
    for i, (_, terms) in enumerate(pools):
        out += [t for t in terms[:quota[i]] if t not in out]
    return out[:cap]


def update_performance(client, now_utc: datetime, data_dir: Path) -> None:
    """Fetch channel stats and last 50 uploads, writing data/performance.md."""
    ch_stats = {"subs": 0, "views": 0, "videos": 0}
    uploads_id = None

    try:
        ch_resp = client.channels().list(mine=True, part="contentDetails,statistics,snippet").execute()
        items = ch_resp.get("items", [])
        if items:
            item = items[0]
            st = item.get("statistics", {})
            ch_stats["subs"] = int(st.get("subscriberCount", 0))
            ch_stats["views"] = int(st.get("viewCount", 0))
            ch_stats["videos"] = int(st.get("videoCount", 0))
            uploads_id = item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    except Exception as e:
        print(f"Error fetching channel statistics: {e}")

    video_ids: list[str] = []
    if uploads_id:
        try:
            page = None
            while len(video_ids) < 200:                      # ~4 quota units; covers weeks at 6 uploads/day
                pl_resp = client.playlistItems().list(playlistId=uploads_id, part="contentDetails",
                                                      maxResults=50, pageToken=page).execute()
                video_ids += [it["contentDetails"]["videoId"] for it in pl_resp.get("items", [])]
                page = pl_resp.get("nextPageToken")
                if not page:
                    break
        except Exception as e:
            print(f"Error fetching uploads playlist items: {e}")

    if not video_ids:
        try:
            s_resp = client.search().list(
                forMine=True,
                type="video",
                order="date",
                maxResults=50,
                part="id",
            ).execute()
            for it in s_resp.get("items", []):
                vid = it.get("id", {}).get("videoId")
                if vid:
                    video_ids.append(vid)
        except Exception as e:
            print(f"Error searching uploads fallback: {e}")

    video_items = []
    if video_ids:
        try:
            for i in range(0, len(video_ids), 50):
                chunk = video_ids[i:i + 50]
                v_resp = client.videos().list(
                    id=",".join(chunk),
                    part="snippet,contentDetails,statistics",
                ).execute()
                video_items.extend(v_resp.get("items", []))
        except Exception as e:
            print(f"Error fetching videos.list for uploads: {e}")

    parsed_videos = []
    shorts_90d_views = 0

    for v in video_items:
        sn = v.get("snippet", {})
        cd = v.get("contentDetails", {})
        st = v.get("statistics", {})

        title = sn.get("title", "Untitled")
        pub_dt = parse_rfc3339(sn.get("publishedAt", ""))
        pub_date = pub_dt.strftime("%Y-%m-%d")

        dur_sec = parse_duration(cd.get("duration", ""))
        fmt = "short" if dur_sec <= 180 else "long"

        views = int(st.get("viewCount", 0))
        likes = int(st.get("likeCount", 0))
        comments = int(st.get("commentCount", 0))

        age_days = (now_utc - pub_dt).total_seconds() / 86400.0
        effective_age = max(age_days, 0.0416)
        views_per_day = views / effective_age
        like_rate = (likes / views * 100.0) if views > 0 else 0.0

        if fmt == "short" and age_days <= 90.0:
            shorts_90d_views += views

        parsed_videos.append({
            "pub_date": pub_date,
            "fmt": fmt,
            "title": title,
            "views": views,
            "views_per_day": views_per_day,
            "likes": likes,
            "comments": comments,
            "like_rate": like_rate,
        })

    parsed_videos.sort(key=lambda x: x["views_per_day"], reverse=True)

    subs = ch_stats["subs"]
    total_views = ch_stats["views"]
    total_videos = ch_stats["videos"]

    subs_prog = f"{subs:,}/1,000 ({min(100.0, subs / 1000 * 100):.1f}%)"
    shorts_prog = f"{shorts_90d_views:,}/10,000,000 ({min(100.0, shorts_90d_views / 10000000 * 100):.2f}%)"

    lines = [
        f"Updated {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        f"**Channel Summary:** {subs:,} subscribers | {total_views:,} views | {total_videos:,} videos",
        f"**YPP Progress:** {subs_prog} subs | Shorts views in last 90 days (approximate): {shorts_prog}",
        "",
        "| Published | Format | Title | Views | Views/Day | Likes | Comments | Like Rate |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for item in parsed_videos:
        clean_title = item["title"].replace("|", "-").replace("\n", " ").strip()
        lines.append(
            f"| {item['pub_date']} | {item['fmt']} | {clean_title} | {item['views']:,} | {item['views_per_day']:.1f} | {item['likes']:,} | {item['comments']:,} | {item['like_rate']:.1f}% |"
        )

    if not parsed_videos:
        lines.append("| - | - | *No uploads found* | 0 | 0.0 | 0 | 0 | 0.0% |")

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "performance.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def update_trends(client, search_terms: list[str], now_utc: datetime, data_dir: Path) -> None:
    """Fetch niche trends for search terms, writing data/trends.md."""
    after_dt = now_utc - timedelta(days=14)
    published_after = after_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        f"Updated {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Niche Trends (Last 14 Days)",
        "",
    ]

    if not search_terms:
        lines.append("*No search terms found in channel.json.*")

    for query, kind in [(q, k) for q in search_terms for k in ("short", "medium")]:
        lines.append(f"### \"{query}\" - {'Shorts / under 4 min' if kind == 'short' else 'long videos (4-20 min)'}")
        lines.append("")

        search_items = []
        try:
            s_resp = client.search().list(
                q=query,
                part="id,snippet",
                type="video",
                order="viewCount",
                publishedAfter=published_after,
                videoDuration=kind,
                maxResults=15,
            ).execute()
            search_items = s_resp.get("items", [])
        except Exception as e:
            print(f"Error searching for query '{query}': {e}")
            lines.append(f"*Search failed: {e}*")
            lines.append("")
            continue

        vids = []
        for it in search_items:
            vid = it.get("id", {}).get("videoId")
            if vid:
                vids.append(vid)

        if not vids:
            lines.append("*No videos found.*")
            lines.append("")
            continue

        video_items = []
        try:
            v_resp = client.videos().list(
                id=",".join(vids),
                part="snippet,contentDetails,statistics",
            ).execute()
            video_items = v_resp.get("items", [])
        except Exception as e:
            print(f"Error fetching video statistics for query '{query}': {e}")
            lines.append(f"*Video statistics lookup failed: {e}*")
            lines.append("")
            continue

        parsed = []
        for it in video_items:
            sn = it.get("snippet", {})
            st = it.get("statistics", {})
            cd = it.get("contentDetails", {})

            title = sn.get("title", "Untitled")
            channel = sn.get("channelTitle", "Unknown")
            pub_dt = parse_rfc3339(sn.get("publishedAt", ""))
            age_days = (now_utc - pub_dt).total_seconds() / 86400.0
            effective_age = max(age_days, 0.0416)

            views = int(st.get("viewCount", 0))
            views_per_day = views / effective_age
            dur_sec = parse_duration(cd.get("duration", ""))
            dur_str = format_duration(dur_sec)

            parsed.append({
                "title": title,
                "channel": channel,
                "views": views,
                "views_per_day": views_per_day,
                "age_days": age_days,
                "duration": dur_str,
            })

        parsed.sort(key=lambda x: x["views_per_day"], reverse=True)
        top_10 = parsed[:10]

        if not top_10:
            lines.append("*No video statistics retrieved.*")
            lines.append("")
            continue

        lines.append("| Title | Channel | Views | Views/Day | Age (days) | Duration |")
        lines.append("|---|---|---|---|---|---|")
        for item in top_10:
            clean_title = item["title"].replace("|", "-").replace("\n", " ").strip()
            clean_channel = item["channel"].replace("|", "-").replace("\n", " ").strip()
            lines.append(
                f"| {clean_title} | {clean_channel} | {item['views']:,} | {item['views_per_day']:.1f} | {item['age_days']:.1f} | {item['duration']} |"
            )
        lines.append("")

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "trends.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> None:
    repo_root = Path(__file__).resolve().parent
    token_candidates = [
        repo_root / "yt_token.json",
        repo_root / "yt_reserve_token.json",
        Path("yt_token.json"),
        Path("yt_reserve_token.json"),
    ]

    if not any(p.is_file() for p in token_candidates):
        print("Note: neither yt_token.json nor yt_reserve_token.json found; skipping insights.")
        sys.exit(0)

    try:
        client = upload.channel_client()
    except Exception as e:
        print(f"Note: failed to initialize YouTube client ({e}); skipping insights.")
        sys.exit(0)

    if not client:
        print("Note: no YouTube client returned from upload.channel_client(); skipping insights.")
        sys.exit(0)

    now_utc = datetime.now(timezone.utc)
    data_dir = repo_root / "data"

    update_performance(client, now_utc, data_dir)

    search_terms = load_search_terms(repo_root / "channel.json")
    update_trends(client, search_terms, now_utc, data_dir)


if __name__ == "__main__":
    main()

