# Setup & Migration Guide

Follow this checklist to switch lorevid over to the anime theory channel. Because the underlying infrastructure is shared with the previous channel setup, most secrets and configurations are already in place.

---

### 1. Verify GitHub Secrets & Reserve Quota

Ensure the following repository secrets are set under **Settings > Secrets and variables > Actions**:

- `YT_CLIENT_SECRET` & `YT_TOKEN`: Primary YouTube Data API credentials.
- `NTFY_TOPIC`: Topic key for push notifications to your phone.
- `CF_ACCOUNT_ID` & `CF_API_TOKEN`: Cloudflare credentials for fallback image generation.

**Optional Reserve YouTube Credentials:**
To prevent pipeline halts when YouTube's daily upload or API quota is reached, configure a second Google Cloud project pointing to the exact same YouTube channel:
- Add repository secrets `YT_RESERVE_CLIENT_SECRET` and `YT_RESERVE_TOKEN`.
- Generate the reserve token locally by running:
  ```bash
  python auth.py reserve
  ```
The pipeline automatically falls back to these reserve credentials if the primary quota is exceeded.

---

### 2. Run Setup Verification

1. Go to **Actions** in your GitHub repository.
2. Select the **check-setup** workflow from the left sidebar.
3. Click **Run workflow**.
4. Ensure every required diagnostic check outputs **PASS** before continuing.

---

### 3. Script Writing

Automated Claude writer routines have been disconnected. You can author scripts following `WRITER.md` and place them directly into `scripts/backlog/<YYYY-MM-DD-id>.json` or `scripts/queue/<id>.json`.

---

### 4. YouTube Studio One-Time Settings

Open [YouTube Studio](https://studio.youtube.com/) and make the following channel adjustments:

1. **Branding**: Update channel banner, avatar, and handle for anime content. Update the channel description with relevant niche keywords: *"One Piece theories, Naruto, Jujutsu Kaisen"*.
2. **Clean Niche History**: Set older history-channel uploads to **Unlisted** or **Private** so new viewers and the YouTube algorithm see a single, focused anime niche.
3. **Upload Defaults**:
   - Go to **Settings > Upload defaults > Basic info / Advanced settings**.
   - Set **Category** to **Film & Animation**.
   - Set **Video language** to **English**.

---

### 5. Optional Configurations

- **Background Music**: Download royalty-free tracks from the YouTube Audio Library and drop MP3 files into the corresponding mood folders:
  `music/hype/`, `music/suspense/`, `music/emotional/`, `music/epic/`, `music/chill/`.
- **Safe Launch Review**: In GitHub **Settings > Secrets and variables > Actions > Variables**, add `PUBLISH_MODE` with value `private`. Every render then uploads as a private video and nothing goes public until you publish it yourself. Recommended for the first 2-3 days; delete the variable to switch back to automatic scheduling.

---

### 6. Test First Render

1. Go to **Actions > render-and-publish > Run workflow**.
2. Leave the **upload** checkbox unchecked.
3. Run the workflow to test-render pending scripts in `scripts/queue/`.
4. Once finished, download the workflow artifact to view and verify the generated `final.mp4` video files.

---

### 7. Enable Watch-Hour & Retention Analytics (AVD/AV%, YPP watch hours)

`insights.py` can add Average View Duration, Average View Percentage, and a watch-hours-toward-YPP header to
`data/performance.md` via the YouTube Analytics API (`yt-analytics.readonly`), but only once your stored token
has been granted that scope. If `YT_TOKEN`/`YT_RESERVE_TOKEN` predate this feature, re-authorize once:

1. On your laptop (not in CI): `python auth.py` (or `python auth.py reserve` for the reserve project). A
   browser opens; sign in with the channel's Google account. The scope list now includes
   `https://www.googleapis.com/auth/yt-analytics.readonly` automatically (`upload.py`'s `SCOPES`), so this
   single re-auth covers upload, comments and analytics together.
2. Copy the full token JSON it prints.
3. In GitHub **Settings > Secrets and variables > Actions**, update the `YT_TOKEN` secret (or
   `YT_RESERVE_TOKEN`) with that value, overwriting the old one.
4. The next `insights.yml` run picks it up automatically. If no stored token has the scope yet,
   `insights.py` logs a note and skips the AVD/AV%/watch-hours section — everything else in
   `data/performance.md` still updates normally.
