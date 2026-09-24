# lorevid

A calm, beautifully told "Your Life as a ___" history video every day, made automatically on GitHub.

## What happens each day (08:47 IST)
1. **Trends**: pulls the fastest-growing videos in the niche (last 60 days) from YouTube.
2. **Strategist (Claude)**: scores the next 6 topics in `topics/long.txt` against that data, picks or improves one,
   and chooses the angle.
3. **Research + plan → draft → harsh critic → editor (Claude Opus 5.5, Batch API)**. The critic scores hook,
   immersion, bedtime comfort, accuracy, pacing and originality, and the editor rewrites until every point is fixed.
4. ~70 painted illustrations, Kokoro narration (slow, warm), soft 1-second crossfades, gentle camera motion,
   warm film grade, chapter cards, mood-matched music that dips under the voice, fade to black at the end.
5. Uploads privately: the 10-min video (thumbnail, captions, chapters) + 2 Shorts. You get a phone notification.

Claude credits: about $0.25–0.40 a day, logged in `costs.csv`. Claude is used until `CLAUDE_UNTIL` (2026-11-10).

---

## Setup, step by step (about 45 minutes, once)

### Step 1: Put the code on GitHub (5 min)
On your laptop (Omarchy terminal):
```bash
cd ~/Downloads
unzip lorevid.zip
cd lorevid
git push -u origin main
```
If it asks for a password, use a GitHub token (github.com → Settings → Developer settings → Personal access
tokens → Fine-grained → repo `lorevid` → Contents: Read and write), or run `gh auth login` first.
Check github.com/adityamittal-dot/lorevid shows the files.

### Step 2: Anthropic key (2 min)
console.anthropic.com → **API Keys** → Create key → copy it (starts with `sk-ant-`).

### Step 3: Cloudflare, backup image generator (5 min)
1. Sign up at dash.cloudflare.com (free).
2. Copy your **Account ID** (right sidebar on the home page, or in the URL after `dash.cloudflare.com/`).
3. My Profile → **API Tokens** → Create Token → use template **Workers AI** → Continue → Create → copy the token.

### Step 4: Phone notifications (2 min)
Install the **ntfy** app (Play Store / App Store) → **+** → subscribe to a topic with a hard-to-guess name,
e.g. `lorevid-aditya-7k29x`. Use the same name as the `NTFY_TOPIC` secret.

### Step 5: YouTube API (15 min)
1. Go to console.cloud.google.com with **the Google account that owns your channel** → project drop-down →
   **New project** → name `lorevid` → Create → select it.
2. Menu → APIs & Services → **Library** → search "YouTube Data API v3" → **Enable**.
3. APIs & Services → **OAuth consent screen** (may be called "Google Auth Platform") → Get started →
   App name `lorevid`, your email → Audience: **External** → contact email → Create.
4. **Audience** → Test users → add your Gmail. Then click **Publish app** → Confirm (so the login does not expire
   after 7 days; Google will show it as "unverified", which is fine for your own use).
5. **Clients** (or Credentials) → Create client → Application type **Desktop app** → name `lorevid` → Create →
   **Download JSON**. Rename the file to `yt_client_secret.json` and put it in the `lorevid` folder.
6. In the `lorevid` folder:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install google-api-python-client google-auth-oauthlib python-dotenv
   python auth.py
   ```
   A browser opens → pick your **channel** (not just the Google account) → "Google hasn't verified this app" →
   **Advanced → Go to lorevid** → allow all. The terminal prints a JSON block. That is your `YT_TOKEN`.

### Step 6: Add the secrets (5 min)
github.com/adityamittal-dot/lorevid → **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | from step 2 |
| `CF_ACCOUNT_ID` | from step 3 |
| `CF_API_TOKEN` | from step 3 |
| `NTFY_TOPIC` | from step 4 |
| `YT_CLIENT_SECRET` | the full text of `yt_client_secret.json` (`cat yt_client_secret.json`) |
| `YT_TOKEN` | the JSON printed by `python auth.py` (`cat yt_token.json`) |

Optional later: `GEMINI_API_KEY` (free fallback after 10 November), `POLLINATIONS_TOKEN`.

### Step 7: Music (10 min, strongly recommended)
YouTube Studio → **Audio Library** → filter Genre *Ambient* / *Cinematic* / *Classical*, Mood *Calm* / *Sad* /
*Dramatic*, and "Attribution not required". Download 2–4 tracks per mood (instrumental, slow, no drums) into:
```
music/calm/  music/warm/  music/melancholy/  music/mystery/  music/epic_soft/
```
Claude picks the mood for each video. Then run `git add music && git commit -m music && git push`.
Without tracks the pipeline makes a soft ambient pad itself (copyright-free, but plainer).

### Step 8: First video
Repo → **Actions** → enable workflows if asked → **daily-video** → **Run workflow** → Run.
It takes about 45–75 minutes (the first run downloads the voice model). Watch progress by clicking the run.
When your phone buzzes, open the link → watch → edit the title if you like → **Visibility: Public**
(or schedule it for about 05:30–07:30 IST, which is evening in the US).
The files are also under the run's **Artifacts** (kept 7 days).

From then on it runs every day by itself.

---

## Daily routine (10–15 min)
Watch the private video (1.5× is fine) → fix anything → publish. Publish the 2 Shorts a few hours apart.
Reply to early comments.

## Weekly (30 min)
YouTube Studio → Analytics: click-through rate, average view duration, which topics won. Reorder or rewrite
`topics/long.txt` to lean into winners (the strategist also reads live trends daily).

## Controls
| What | How |
|---|---|
| Specific topic today | Actions → Run workflow → type the topic |
| Voice | repo **Variables** tab → `KOKORO_VOICE` = `bm_george` (default), `bm_fable`, `bm_lewis`, `am_michael`, `am_onyx` |
| Time of day | `.github/workflows/make.yml` cron (UTC; IST = UTC+5:30) |
| See spend | `costs.csv` in the repo |

## If something fails
You get a notification. Open Actions → the red run → the failed step → copy the last ~30 lines and send them
to Claude. Re-running is safe: a topic is only marked done after a successful upload.

## Staying safe on YouTube
Original scripts only; every upload is labelled as synthetic media; Audio Library or generated music only;
violence and hardship are handled soberly; nothing goes public without you. Turn on 2-step verification.
