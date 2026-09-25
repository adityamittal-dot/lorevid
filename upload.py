"""YouTube upload (one Google Cloud project: 1 long + 2 shorts + captions ≈ 5,300 of 10,000 daily units).
Files: yt_client_secret.json (OAuth desktop client) and yt_token.json (made once by `python auth.py`)."""
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
SECRET, TOKEN = "yt_client_secret.json", "yt_token.json"


def get_credentials(interactive=False):
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES) if os.path.exists(TOKEN) else None
    if creds and creds.valid:
        return creds
    if creds and creds.refresh_token:
        creds.refresh(Request())
        return creds
    if not interactive:
        raise SystemExit("No valid yt_token.json — run `python auth.py` on your laptop once.")
    creds = InstalledAppFlow.from_client_secrets_file(SECRET, SCOPES).run_local_server(port=0)
    open(TOKEN, "w").write(creds.to_json())
    return creds


def existing(yt, title):
    """Video id if the channel's last 50 uploads already have this exact title (so a retry never re-uploads). ~2 quota units."""
    try:
        ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
        pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        for it in yt.playlistItems().list(part="snippet", playlistId=pl, maxResults=50).execute().get("items", []):
            if it["snippet"]["title"] == title[:100]:
                return it["snippet"]["resourceId"]["videoId"]
    except Exception as e:
        print(f"  duplicate check skipped ({e})")
    return None


def upload(video, title, description, tags, thumb=None, srt=None, privacy="private"):
    yt = build("youtube", "v3", credentials=get_credentials())
    vid = existing(yt, title)
    if vid:
        print(f"  already on the channel, not uploading again: https://youtu.be/{vid}")
        return vid
    body = {"snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:30],
                        "categoryId": "27", "defaultLanguage": "en", "defaultAudioLanguage": "en"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(video, chunksize=16 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        st, resp = req.next_chunk()
        if st:
            print(f"  upload {int(st.progress() * 100)}%")
    vid = resp["id"]
    print(f"  uploaded https://youtu.be/{vid}")
    if thumb:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumb)).execute()
        except Exception as e:
            print(f"  thumbnail skipped ({e}) — verify your channel by phone to enable custom thumbnails")
    if srt:
        try:
            yt.captions().insert(part="snippet", body={"snippet": {"videoId": vid, "language": "en",
                                 "name": "English", "isDraft": False}}, media_body=MediaFileUpload(srt)).execute()
        except Exception as e:
            print(f"  captions skipped ({e})")
    return vid
