# lorevid

Automatic "Your Life as a ___" history channel. Every day on GitHub's servers:

1. **Claude Opus 5.5** (Batch API, half price) researches the topic, writes a ~10-minute second-person
   script, then edits it for facts, pacing and YouTube safety, and writes 2 Shorts.
2. ~70 painted illustrations (Pollinations → Cloudflare fallback, free).
3. Kokoro narration (free, runs on the server; edge-tts fallback).
4. Film render: Ken Burns motion, crossfades, film grain and vignette, chapter cards, music, loudness normalised.
5. Upload as **private**: long video (thumbnail, captions, chapters in description, AI label) + 2 Shorts.
6. Phone notification with the Studio links → you review and publish.

Cost: ~$0.20–0.35 per day of Claude credits until `CLAUDE_UNTIL` (2026-11-10), then free Gemini. See `costs.csv`.

## Setup

### 1. Keys (GitHub → repo → Settings → Secrets and variables → Actions → New repository secret)

| Secret | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys |
| `GEMINI_API_KEY` | aistudio.google.com/apikey (free fallback) |
| `CF_ACCOUNT_ID`, `CF_API_TOKEN` | dash.cloudflare.com → AI → Workers AI → "Use REST API" (image fallback) |
| `NTFY_TOPIC` | any hard-to-guess name, e.g. `lorevid-aditya-83k2`; install the **ntfy** app and subscribe to it |
| `YT_CLIENT_SECRET`, `YT_TOKEN` | step 2 |
| `POLLINATIONS_TOKEN` | optional, auth.pollinations.ai (higher limits) |

### 2. YouTube API (one time, ~15 min)
1. console.cloud.google.com → New project `lorevid` → APIs & Services → Library → enable **YouTube Data API v3**.
2. OAuth consent screen → External → app name, your email → Scopes: skip → Test users: add your Gmail → Save.
   Then **Publish app** ("In production"). Otherwise the login expires every 7 days.
3. Credentials → Create credentials → OAuth client ID → **Desktop app** → Download JSON →
   rename to `yt_client_secret.json` in this folder. Paste its contents into secret `YT_CLIENT_SECRET`.
4. On your laptop:
   ```bash
   git clone https://github.com/adityamittal-dot/lorevid && cd lorevid
   python -m venv .venv && source .venv/bin/activate
   pip install google-api-python-client google-auth-oauthlib python-dotenv
   python auth.py        # browser → pick the channel → "unverified app" → Advanced → Continue
   ```
   Paste the printed JSON into secret `YT_TOKEN`.

### 3. First video
Actions tab → **daily-video** → Run workflow. About 40–70 min later you get a notification. The files are also
under the run's **Artifacts**. After that it runs every day at 08:47 IST.

## Daily routine
Open the notification → watch the private video → fix title/anything → set **Public** (or schedule it for
~05:30 IST = US evening). Do the same for the 2 Shorts (post them a few hours apart).

## Controls
- Topics: `topics/long.txt` (used ones get `#done`; empty → Claude adds 20 new ones).
- Music: put royalty-free tracks from **YouTube Studio → Audio Library** into `music/` (one is picked per video).
- Voice: repo variable `KOKORO_VOICE` (`bm_george`, `bm_fable`, `bm_lewis`, `am_michael`, `am_onyx`).
- Specific topic now: Run workflow → type the topic.

## Safety
Scripts are edited for accuracy and YouTube policy; image prompts exclude gore/nudity; every upload is marked as
synthetic media; only original scripts and Audio Library music are used; nothing goes public without you.
Turn on 2-step verification on the Google account that owns the channel.
