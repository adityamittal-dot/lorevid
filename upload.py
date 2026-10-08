"""YouTube upload with scheduled publishing, credential fallback, playlists, and comments."""
import datetime
import json
import os
import time
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    ANALYTICS_SCOPE,
]
SECRET = "yt_client_secret.json"
TOKEN = "yt_token.json"
RESERVE_SECRET = "yt_reserve_client_secret.json"
RESERVE_TOKEN = "yt_reserve_token.json"
CREDENTIAL_SETS = [
    (SECRET, TOKEN),
    (RESERVE_SECRET, RESERVE_TOKEN),
]

_PLAYLISTS_CACHE = {}
_PLAYLISTS_LOADED = False


def get_credentials(interactive=False, secret=None, token=None):
    """Load or refresh credentials; interactive OAuth login if interactive=True."""
    s = secret or SECRET
    t = token or TOKEN
    # The token's own granted scopes, not SCOPES: refreshing with a scope the token was never granted (the
    # analytics one, before a re-auth) fails with invalid_scope and blocks every upload.
    creds = Credentials.from_authorized_user_file(t) if os.path.exists(t) else None
    if creds and creds.valid:
        return creds
    if creds and creds.refresh_token:
        try:
            creds.refresh(Request())
            try:
                with open(t, "w") as f:
                    f.write(creds.to_json())
            except Exception:
                pass
            return creds
        except Exception:
            pass
    if not interactive:
        if creds and creds.valid:
            return creds
        raise SystemExit(f"No valid {t} — run `python auth.py` on your laptop once.")
    creds = InstalledAppFlow.from_client_secrets_file(s, SCOPES).run_local_server(port=0)
    with open(t, "w") as f:
        f.write(creds.to_json())
    return creds


def get_available_credential_sets():
    """Return credential sets (secret, token) whose token file exists."""
    candidates = [
        (SECRET, TOKEN),
        (RESERVE_SECRET, RESERVE_TOKEN),
    ]
    seen = set()
    available = []
    for s, t in candidates:
        if t not in seen and os.path.exists(t):
            seen.add(t)
            available.append((s, t))
    return available


def channel_client():
    """Return an authorized YouTube client using the first working credential set, or None."""
    for sec, tok in get_available_credential_sets():
        try:
            creds = get_credentials(interactive=False, secret=sec, token=tok)
            if creds and creds.valid:
                return build("youtube", "v3", credentials=creds)
        except (Exception, SystemExit):
            continue
    return None


def analytics_client():
    """Authorized youtubeAnalytics v2 client using the first credential set that was granted
    ANALYTICS_SCOPE, or None if no token has it yet (older tokens predate the scope; re-auth to add it —
    see SETUP.md). insights.py uses this for AVD/AV%/watch-hours and skips that section without it."""
    for sec, tok in get_available_credential_sets():
        try:
            creds = get_credentials(interactive=False, secret=sec, token=tok)
            if creds and creds.valid and ANALYTICS_SCOPE in (creds.scopes or []):
                return build("youtubeAnalytics", "v2", credentials=creds)
        except (Exception, SystemExit):
            continue
    return None


def _is_quota_error(err):
    """Check if an HttpError indicates quota exhaustion or daily upload limits."""
    if not isinstance(err, HttpError):
        return False
    reasons = ("quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded")
    details = getattr(err, "error_details", None)
    if isinstance(details, list):
        for d in details:
            if isinstance(d, dict) and d.get("reason") in reasons:
                return True
    try:
        raw = err.content.decode("utf-8") if isinstance(err.content, bytes) else str(err.content)
        data = json.loads(raw)
        for item in data.get("error", {}).get("errors", []):
            if item.get("reason") in reasons:
                return True
    except Exception:
        pass
    reason_attr = getattr(err, "reason", None)
    if reason_attr in reasons:
        return True
    err_str = str(err)
    return any(r in err_str for r in reasons)


def _get_or_create_playlist(yt, title):
    """Find public playlist ID by title (cached per run) or create it."""
    global _PLAYLISTS_LOADED
    if title in _PLAYLISTS_CACHE:
        return _PLAYLISTS_CACHE[title]

    if not _PLAYLISTS_LOADED:
        page_token = None
        while True:
            res = yt.playlists().list(
                part="snippet",
                mine=True,
                maxResults=50,
                pageToken=page_token,
            ).execute()
            for it in res.get("items", []):
                snippet = it.get("snippet", {})
                t = snippet.get("title")
                if t:
                    _PLAYLISTS_CACHE[t] = it.get("id")
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        _PLAYLISTS_LOADED = True

    if title in _PLAYLISTS_CACHE:
        return _PLAYLISTS_CACHE[title]

    pl_res = yt.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title},
            "status": {"privacyStatus": "public"},
        },
    ).execute()
    pl_id = pl_res["id"]
    _PLAYLISTS_CACHE[title] = pl_id
    return pl_id


def existing(yt, title):
    """Video id if the channel's last 50 uploads already have this exact title (so a retry never re-uploads). ~2 quota units."""
    try:
        ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
        pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        for it in yt.playlistItems().list(part="snippet", playlistId=pl, maxResults=50).execute().get("items", []):
            if it["snippet"]["title"] == title[:100]:
                return it["snippet"]["resourceId"]["videoId"]
    except HttpError as e:
        if _is_quota_error(e):
            raise
        print(f"  duplicate check skipped ({e})")
    except Exception as e:
        print(f"  duplicate check skipped ({e})")
    return None


def next_slot(fmt, cfg, taken=None, min_date=None):
    """Return earliest slot >= now + min_lead_hours (and >= min_date, if given) not in taken, as an RFC3339 UTC
    string. `min_date` is the script's own intended publish date (its id's "YYYY-MM-DD" prefix): a script queued
    ahead of its date (the backlog release step moves it in early, or a render catches up) must not jump the
    queue and publish before the day it was written for."""
    fmt = str(fmt).lower()
    pub = cfg.get("publish", cfg) if isinstance(cfg, dict) else {}
    min_lead = int(pub.get("min_lead_hours", 3))
    default_slots = (
        ["14:30", "17:00"]
        if fmt == "short"
        else ["15:00"]
    )
    slot_strings = pub.get(f"{fmt}_slots_utc") or default_slots

    parsed_slots = []
    for s in slot_strings:
        parts = s.strip().split(":")
        parsed_slots.append((int(parts[0]), int(parts[1])))
    parsed_slots.sort()

    taken_set = set(taken or [])
    now = datetime.datetime.now(datetime.timezone.utc)
    earliest = now + datetime.timedelta(hours=min_lead)

    if min_date:
        min_day = min_date if isinstance(min_date, datetime.date) else datetime.datetime.strptime(
            min_date, "%Y-%m-%d").date()
        min_dt = datetime.datetime(min_day.year, min_day.month, min_day.day, 0, 0, 0, tzinfo=datetime.timezone.utc)
        if min_dt > earliest:
            earliest = min_dt

    today = now.date()
    for day_offset in range(365):
        day = today + datetime.timedelta(days=day_offset)
        for h, m in parsed_slots:
            slot_dt = datetime.datetime(
                day.year, day.month, day.day, h, m, 0, tzinfo=datetime.timezone.utc
            )
            if slot_dt >= earliest:
                rfc_str = slot_dt.strftime("%Y-%m-%dT%H:%M:00Z")
                if rfc_str not in taken_set:
                    return rfc_str

    return earliest.strftime("%Y-%m-%dT%H:%M:00Z")


def _upload_with_client(
    yt,
    video,
    meta,
    publish_at=None,
    privacy="private",
    thumb=None,
    srt=None,
    playlist=None,
    comment=None,
):
    title, description, tags = meta.get("title", ""), meta.get("description", ""), meta.get("tags", [])
    title = str(title).replace("<", "").replace(">", "")[:100]      # YouTube rejects angle brackets
    description = str(description).replace("<", "").replace(">", "")[:4900]
    tag_list, used = [], 0
    for t in tags:                                   # YouTube rejects the upload if tags exceed 500 characters
        t = str(t).replace("<", "").replace(">", "").strip()
        cost = len(t) + (2 if " " in t else 0) + 1
        if t and used + cost <= 480:
            tag_list.append(t); used += cost

    vid = existing(yt, title)
    if vid:
        print(f"  already on the channel, not uploading again: https://youtu.be/{vid}")
        return vid

    status = {
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": os.environ.get("SYNTHETIC_DISCLOSURE") == "1",
    }
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    else:
        status["privacyStatus"] = privacy

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tag_list,
            "categoryId": "1",
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": status,
    }

    req = yt.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(video, chunksize=16 * 1024 * 1024, resumable=True),
    )

    resp = None
    retries = 0
    while resp is None:
        try:
            st, resp = req.next_chunk()
            if st:
                print(f"  upload {int(st.progress() * 100)}%")
            retries = 0
        except HttpError as e:
            if _is_quota_error(e):
                raise
            status_code = getattr(e.resp, "status", 0) if hasattr(e, "resp") else 0
            if status_code >= 500 and retries < 3:
                retries += 1
                time.sleep(retries * 2)
                continue
            raise
        except (OSError, IOError):
            if retries < 3:
                retries += 1
                time.sleep(retries * 2)
                continue
            raise

    vid = resp["id"]
    print(f"  uploaded https://youtu.be/{vid}")

    if thumb and os.path.exists(thumb):
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumb)).execute()
        except Exception as e:
            print(f"  thumbnail skipped ({e}) — verify your channel by phone to enable custom thumbnails")

    if srt and os.path.exists(srt):
        try:
            yt.captions().insert(
                part="snippet",
                body={"snippet": {"videoId": vid, "language": "en", "name": "English", "isDraft": False}},
                media_body=MediaFileUpload(srt),
            ).execute()
        except Exception as e:
            print(f"  captions skipped ({e})")

    if playlist:
        try:
            pl_id = _get_or_create_playlist(yt, playlist)
            yt.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": pl_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": vid,
                        },
                    }
                },
            ).execute()
        except Exception as e:
            print(f"  playlist skipped ({e})")

    if comment:
        post_comment(yt, vid, comment)

    return vid


def post_comment(yt, vid, text):
    """First comment from the channel (only works once the video is public). True on success."""
    try:
        yt.commentThreads().insert(part="snippet", body={"snippet": {
            "videoId": vid, "topLevelComment": {"snippet": {"textOriginal": text}}}}).execute()
        return True
    except Exception as e:
        print(f"  comment skipped ({e})")
        return False


def post_pending_comments(done_dir="scripts/done"):
    """Scheduled videos cannot take comments until they go public: post each queued first comment
    once its publish time has passed, and mark it in the script file. Returns how many were posted."""
    import glob
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
    yt, n = None, 0
    for path in sorted(glob.glob(os.path.join(done_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        pub = d.get("published") or {}
        if not pub.get("comment") or pub.get("comment_posted") or (pub.get("publish_at") or "9") > now:
            continue
        yt = yt or channel_client()
        if yt is None:
            print("  no YouTube credentials; comments stay queued")
            return n
        if post_comment(yt, pub["video_id"], pub["comment"]):
            pub["comment_posted"] = True
            with open(path, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2, ensure_ascii=False)
            n += 1
    return n


def upload(
    video,
    meta,
    publish_at=None,
    privacy="private",
    thumb=None,
    srt=None,
    playlist=None,
    comment=None,
):
    """Upload video to YouTube with scheduled publishing, playlist assignment, and quota fallback."""
    cred_sets = get_available_credential_sets()
    if not cred_sets:
        get_credentials(interactive=False)

    last_error = None
    for idx, (sec, tok) in enumerate(cred_sets):
        try:
            creds = get_credentials(interactive=False, secret=sec, token=tok)
            yt = build("youtube", "v3", credentials=creds)
            return _upload_with_client(
                yt,
                video,
                meta,
                publish_at=publish_at,
                privacy=privacy,
                thumb=thumb,
                srt=srt,
                playlist=playlist,
                comment=comment,
            )
        except HttpError as e:
            last_error = e
            if _is_quota_error(e):
                if idx + 1 < len(cred_sets):
                    print(f"  quota exceeded for {tok}, retrying with next credential set...")
                    continue
                raise
            raise
        except (Exception, SystemExit) as e:
            last_error = e
            if idx + 1 < len(cred_sets):
                print(f"  credentials error for {tok} ({e}), trying next credential set...")
                continue
            raise

    if last_error:
        raise last_error


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["comments"]:
        print(f"posted {post_pending_comments()} queued comments")
