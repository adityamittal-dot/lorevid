"""Checks every secret actually works. Run from GitHub: Actions -> check-setup -> Run workflow."""
import base64, json, os, sys
import requests

ok = True


def report(name, good, msg):
    global ok
    ok &= good or name.startswith("(optional)")
    print(f"{'PASS' if good else 'FAIL'}  {name}: {msg}")


# YouTube
try:
    from googleapiclient.discovery import build
    from upload import get_credentials
    for f in ("yt_client_secret.json", "yt_token.json"):
        json.load(open(f))
    yt = build("youtube", "v3", credentials=get_credentials())
    ch = yt.channels().list(part="snippet,status", mine=True).execute().get("items", [])
    if ch:
        report("YT_CLIENT_SECRET + YT_TOKEN", True, f"logged in as channel '{ch[0]['snippet']['title']}'")
    else:
        report("YT_CLIENT_SECRET + YT_TOKEN", False, "login works but this Google account has no YouTube channel")
except FileNotFoundError as e:
    report("YT_CLIENT_SECRET / YT_TOKEN", False, f"secret missing ({e.filename})")
except json.JSONDecodeError:
    report("YT_CLIENT_SECRET / YT_TOKEN", False, "not valid JSON: paste the whole file content, from { to }")
except BaseException as e:
    report("YT_CLIENT_SECRET + YT_TOKEN", False, f"{e}  (re-run `python auth.py` and update YT_TOKEN)")

# ntfy
topic = os.getenv("NTFY_TOPIC")
if not topic:
    report("NTFY_TOPIC", False, "secret missing")
else:
    r = requests.post(f"https://ntfy.sh/{topic}", data="lorevid setup check: notifications work".encode(),
                      headers={"Title": "lorevid"}, timeout=15)
    report("NTFY_TOPIC", r.ok, "test notification sent, check your phone" if r.ok else f"HTTP {r.status_code}")

# Cloudflare (optional backup)
acct, tok = os.getenv("CF_ACCOUNT_ID"), os.getenv("CF_API_TOKEN")
if not (acct and tok):
    report("CF_ACCOUNT_ID / CF_API_TOKEN", False, f"missing {'CF_ACCOUNT_ID' if not acct else 'CF_API_TOKEN'}: "
           "without it every render fails whenever Pollinations is down")
else:
    r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/flux-1-schnell",
                      headers={"Authorization": f"Bearer {tok}"}, json={"prompt": "a candle", "steps": 1}, timeout=60)
    report("CF_ACCOUNT_ID + CF_API_TOKEN", r.ok, "image generated" if r.ok else f"HTTP {r.status_code}: {r.text[:150]}")

# Pollinations (no secret needed)
try:
    r = requests.get("https://image.pollinations.ai/prompt/a%20candle?width=256&height=256&nologo=true", timeout=120)
    report("Pollinations images", r.ok and r.headers.get("content-type", "").startswith("image"), f"HTTP {r.status_code}")
except Exception as e:
    report("Pollinations images", False, str(e))

print("\nALL GOOD" if ok else "\nSomething needs fixing (see FAIL lines above)")
sys.exit(0 if ok else 1)
