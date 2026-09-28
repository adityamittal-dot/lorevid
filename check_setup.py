"""Checks every secret and dependency actually works. Run from GitHub Actions or locally."""
import json
import os
import sys
import requests

ok = True


def report(name, good, msg, optional=False):
    global ok
    is_opt = optional or name.startswith("(optional)")
    tag = "(optional) " if is_opt and not name.startswith("(optional)") else ""
    full_name = f"{tag}{name}"
    if not is_opt:
        ok = ok and bool(good)
    status = "PASS" if good else "FAIL"
    print(f"{status}  {full_name}: {msg}")


# --- YouTube credentials ---
channels_found = {}
cred_configs = [
    ("main", "yt_client_secret.json", "yt_token.json"),
    ("reserve", "yt_reserve_client_secret.json", "yt_reserve_token.json"),
]

existing_sets = [
    (label, sec, tok)
    for label, sec, tok in cred_configs
    if os.path.exists(sec) or os.path.exists(tok)
]

if not existing_sets:
    report("YouTube credentials", False, "no credential sets found (at least one set required: yt_client_secret.json / yt_token.json)")
else:
    for label, sec_file, tok_file in existing_sets:
        try:
            if not os.path.exists(sec_file):
                raise FileNotFoundError(f"client secret missing ({sec_file})")
            if not os.path.exists(tok_file):
                raise FileNotFoundError(f"token missing ({tok_file})")

            for f in (sec_file, tok_file):
                with open(f, "r", encoding="utf-8") as fp:
                    json.load(fp)

            import upload
            from googleapiclient.discovery import build

            upload.SECRET = sec_file
            upload.TOKEN = tok_file
            creds = upload.get_credentials(interactive=False)
            yt = build("youtube", "v3", credentials=creds)
            ch = yt.channels().list(part="snippet,status", mine=True).execute().get("items", [])
            if ch:
                ch_title = ch[0].get("snippet", {}).get("title", "Unknown")
                ch_id = ch[0].get("id", "")
                channels_found[label] = (ch_id, ch_title)
                report(f"YouTube credentials ({label})", True, f"logged in as channel '{ch_title}'")
            else:
                report(f"YouTube credentials ({label})", False, "login works but this Google account has no YouTube channel")
        except FileNotFoundError as e:
            report(f"YouTube credentials ({label})", False, str(e))
        except json.JSONDecodeError:
            report(f"YouTube credentials ({label})", False, f"not valid JSON in {sec_file} or {tok_file}")
        except BaseException as e:
            report(f"YouTube credentials ({label})", False, f"{e} (re-run `python auth.py` and update token)")

    if "main" in channels_found and "reserve" in channels_found:
        main_id, main_title = channels_found["main"]
        res_id, res_title = channels_found["reserve"]
        if (main_id and res_id and main_id == res_id) or main_title == res_title:
            report("YouTube channel match", True, f"both credential sets match channel '{main_title}'")
        else:
            report("YouTube channel match", False, f"channels differ: main is '{main_title}', reserve is '{res_title}'")


# --- NTFY ---
topic = os.getenv("NTFY_TOPIC")
if not topic:
    report("NTFY_TOPIC", False, "secret missing (environment variable NTFY_TOPIC not set)")
else:
    try:
        r = requests.post(
            f"https://ntfy.sh/{topic}",
            data="lorevid setup check: notifications work".encode("utf-8"),
            headers={"Title": "lorevid"},
            timeout=15,
        )
        report("NTFY_TOPIC", r.ok, "test notification sent, check your phone" if r.ok else f"HTTP {r.status_code}")
    except Exception as e:
        report("NTFY_TOPIC", False, str(e))


# --- Wiki image API ---
try:
    wiki_url = "https://onepiece.fandom.com/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srnamespace": "6",
        "srsearch": "Zoro",
        "format": "json",
    }
    headers = {"User-Agent": "lorevid/1.0 (+https://github.com/adityamittal-dot/lorevid)"}
    r = requests.get(wiki_url, params=params, headers=headers, timeout=15)
    if r.ok:
        data = r.json()
        search_results = data.get("query", {}).get("search", [])
        if search_results:
            report("Wiki image API", True, f"reachable ({len(search_results)} files found for 'Zoro')")
        else:
            report("Wiki image API", False, f"search for 'Zoro' returned 0 results: {r.text[:150]}")
    else:
        report("Wiki image API", False, f"HTTP {r.status_code}: {r.text[:150]}")
except Exception as e:
    report("Wiki image API", False, str(e))


# --- Cloudflare (optional backup) ---
acct, tok = os.getenv("CF_ACCOUNT_ID"), os.getenv("CF_API_TOKEN")
if not (acct and tok):
    missing_var = "CF_ACCOUNT_ID and CF_API_TOKEN" if not (acct or tok) else ("CF_ACCOUNT_ID" if not acct else "CF_API_TOKEN")
    report("CF_ACCOUNT_ID / CF_API_TOKEN", False, f"missing {missing_var} (optional AI fallback)", optional=True)
else:
    try:
        r = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/flux-1-schnell",
            headers={"Authorization": f"Bearer {tok}"},
            json={"prompt": "a candle", "steps": 1},
            timeout=60,
        )
        report("CF_ACCOUNT_ID + CF_API_TOKEN", r.ok, "image generated" if r.ok else f"HTTP {r.status_code}: {r.text[:150]}", optional=True)
    except Exception as e:
        report("CF_ACCOUNT_ID + CF_API_TOKEN", False, str(e), optional=True)


# --- Pollinations (optional fallback) ---
try:
    r = requests.get(
        "https://image.pollinations.ai/prompt/a%20candle?width=256&height=256&nologo=true",
        headers={"User-Agent": "lorevid/1.0 (+https://github.com/adityamittal-dot/lorevid)"},
        timeout=60,
    )
    is_img = r.ok and r.headers.get("content-type", "").startswith("image")
    report("Pollinations images", is_img, "image generated" if is_img else f"HTTP {r.status_code}", optional=True)
except Exception as e:
    report("Pollinations images", False, str(e), optional=True)


# --- Font ---
font_rel = "fonts/Anton-Regular.ttf"
font_abs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "Anton-Regular.ttf")
font_exists = os.path.isfile(font_rel) or os.path.isfile(font_abs)
report("fonts/Anton-Regular.ttf", font_exists, "font file exists" if font_exists else "missing fonts/Anton-Regular.ttf")


# --- Summary ---
print("\nALL GOOD" if ok else "\nSomething needs fixing (see FAIL lines above)")
sys.exit(0 if ok else 1)
