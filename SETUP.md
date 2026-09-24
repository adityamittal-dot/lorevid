# lorevid: setup checklist

Tick these off in order. Everything happens in your browser or terminal.

- [x] Repo on GitHub
- [x] Cloudflare (`CF_ACCOUNT_ID`, `CF_API_TOKEN` secrets)
- [ ] Step 1: Get the latest code onto GitHub
- [ ] Step 2: Phone notifications (ntfy)
- [ ] Step 3: YouTube channel ready
- [ ] Step 4: Google Cloud project + YouTube API
- [ ] Step 5: Log in to your channel from the laptop
- [ ] Step 6: Add the YouTube secrets to GitHub
- [ ] Step 7: Turn on GitHub Actions
- [ ] Step 8: Start the daily writer (Claude cloud session)
- [ ] Step 9: Review and publish the first video
- [ ] Step 10 (later): Add music

---

## Step 1: Get the latest code onto GitHub

In the terminal:
```bash
cd ~/Downloads/lorevid
git pull ~/Downloads/lorevid-update.bundle HEAD
git push
```
Check that https://github.com/adityamittal-dot/lorevid shows `WRITER.md`, `SETUP.md` and `validate_script.py`.

## Step 2: Phone notifications (ntfy)

1. On your phone, install **ntfy** (Play Store / App Store, the icon is a white bell on green).
2. Open it and tap the **+** button.
3. Topic name: make up something unique, e.g. `lorevid-aditya-7k29x`. Leave "Use another server" off.
   Tap **Subscribe**.
4. Add it to GitHub: open https://github.com/adityamittal-dot/lorevid/settings/secrets/actions →
   **New repository secret** → Name `NTFY_TOPIC` → Secret: your topic name → **Add secret**.
5. Test it (optional), in the terminal: `curl -d "hello from lorevid" ntfy.sh/lorevid-aditya-7k29x`
   Your phone should buzz.

## Step 3: YouTube channel ready

1. Open https://www.youtube.com and sign in with the Google account you want the channel on.
2. Profile picture (top right). If you see **Create a channel**, click it, set the channel name and
   picture → **Create channel**. If you see **Your channel**, you already have one.
3. Verify the channel (unlocks custom thumbnails and longer videos): open
   https://www.youtube.com/verify → choose India → phone number → enter the SMS code.
4. Turn on 2-step verification for this Google account: https://myaccount.google.com/signinoptions/two-step-verification

## Step 4: Google Cloud project + YouTube API

Use the **same Google account** as the channel.

**4a. Create the project**
1. Open https://console.cloud.google.com
2. If asked, pick your country, tick the terms box → **Agree and continue**.
3. At the top left, next to "Google Cloud", click the project picker (it may say "Select a project").
4. In the popup, click **New project** (top right of the popup).
5. Project name: `lorevid` → **Create**. Wait ~20 seconds.
6. Click the project picker again → click **lorevid** so it is selected (its name shows at the top).

**4b. Enable the YouTube API**
1. Open https://console.cloud.google.com/apis/library/youtube.googleapis.com
2. Check the top bar still says **lorevid**.
3. Click the blue **Enable** button. Wait until the page changes to "API enabled".

**4c. Set up the consent screen**
1. Open https://console.cloud.google.com/auth/overview
2. Click **Get started**.
3. App information: App name `lorevid`, User support email: pick your Gmail → **Next**.
4. Audience: select **External** → **Next**.
5. Contact information: type your Gmail → **Next**.
6. Tick "I agree to the Google API Services: User Data Policy" → **Continue** → **Create**.

**4d. Publish the app** (otherwise the login expires every 7 days)
1. In the left menu click **Audience**.
2. Under "Publishing status: Testing" click **Publish app** → **Confirm**.
3. It should now say **In production**.

**4e. Create the login file**
1. In the left menu click **Clients**.
2. Click **+ Create client**.
3. Application type: **Desktop app**. Name: `lorevid` → **Create**.
4. A popup shows the client. Click **Download JSON** (a file named `client_secret_....json` goes to
   your Downloads) → **OK**.

## Step 5: Log in to your channel from the laptop

In the terminal, one line at a time:
```bash
cd ~/Downloads/lorevid
mv ~/Downloads/client_secret_*.json yt_client_secret.json
python -m venv .venv
source .venv/bin/activate
pip install google-api-python-client google-auth-oauthlib python-dotenv
python auth.py
```
A browser tab opens:
1. Choose your Google account.
2. If it asks to pick a channel or brand account, pick **your YouTube channel**.
3. "Google hasn't verified this app" → click **Advanced** → **Go to lorevid (unsafe)**.
   (It is your own app; this is normal.)
4. Tick **every** checkbox → **Continue**.
5. The tab says "The authentication flow has completed". Close it.

The terminal now prints a block of text starting with `{"token":`. A file `yt_token.json` was also saved.
Never commit these two files (`.gitignore` already blocks them).

## Step 6: Add the YouTube secrets to GitHub

1. In the terminal: `cat yt_client_secret.json` → select all of the output (from `{` to `}`) and copy.
2. https://github.com/adityamittal-dot/lorevid/settings/secrets/actions → **New repository secret** →
   Name `YT_CLIENT_SECRET` → paste → **Add secret**.
3. In the terminal: `cat yt_token.json` → copy all of it.
4. **New repository secret** → Name `YT_TOKEN` → paste → **Add secret**.

You should now see 5 secrets: `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `NTFY_TOPIC`, `YT_CLIENT_SECRET`, `YT_TOKEN`.

## Step 7: Turn on GitHub Actions

1. Open https://github.com/adityamittal-dot/lorevid/actions
2. If you see "Workflows aren't being run on this repository", click **I understand my workflows, go ahead
   and enable them**.
3. You should see **daily-video** in the left list.

## Step 8: Start the daily writer (Claude cloud session)

**8a. Install the Claude GitHub App on the repo** (lets cloud sessions clone and push)
1. Open https://github.com/apps/claude → **Install** (or **Configure** if already installed).
2. Choose your account `adityamittal-dot`.
3. Select **Only select repositories** → pick **lorevid** → **Install** / **Save**.

**8b. Test it once by hand**
1. Open https://claude.ai/code (sign in with your Pro account). If it walks you through onboarding, accept the
   **Default** environment and connect GitHub when asked.
2. In the repository picker next to the message box, choose **adityamittal-dot/lorevid**.
3. Send:
   > Follow WRITER.md exactly and push today's script.
4. It finishes in 10-20 minutes and pushes a branch `claude/script-<date>`.
5. https://github.com/adityamittal-dot/lorevid/actions → **daily-video** starts on its own.

**8c. Make it automatic every day (routine)**
1. Open https://claude.ai/code/routines → **New routine**.
2. Name: `lorevid daily writer`.
3. Instructions (prompt):
   > Follow WRITER.md exactly and push today's script.
4. Model: pick the strongest one available (Opus).
5. Repositories: add **adityamittal-dot/lorevid**. Environment: **Default**.
6. Trigger: **Schedule** → **Daily** → **08:00** (your local time).
7. Connectors: remove all (it does not need them).
8. **Create**. You can press **Run now** any time for an extra video.

Routines use your Claude plan's usage; there is also a daily cap on routine runs, visible at
https://claude.ai/code/routines.

## Step 9: Review and publish the first video

1. Your phone buzzes with links to YouTube Studio.
2. Open the long video → watch it (1.5x is fine) → check title, thumbnail, facts.
3. **Visibility** → **Public** (or **Schedule** for 06:00-07:30 IST, which is evening in the US) → **Save**.
4. Do the same for the 2 Shorts, a few hours apart.

If a run shows a red ✗ in Actions: click it → click the red step → copy the last 30 lines → send them to Claude.

## Step 10 (later): Add music

1. https://studio.youtube.com → **Audio Library** (left menu).
2. Filter: Genre *Ambient* or *Cinematic* or *Classical*; Mood *Calm* / *Sad* / *Dramatic*; License type:
   **You can use this song in any of your videos** (no attribution).
3. Download 2-4 slow instrumental tracks per mood into the matching folder:
   `music/calm`, `music/warm`, `music/melancholy`, `music/mystery`, `music/epic_soft`.
4. `git add music && git commit -m "music" && git push`
