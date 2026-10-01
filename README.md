# lorevid

An automated YouTube channel producing high-retention anime theory, breakdown, and "What If" videos covering **One Piece**, **Naruto / Boruto**, and **Jujutsu Kaisen**.

The channel publishes roughly **7 vertical Shorts per day** alongside **long-form breakdown videos 3 times a week** (Monday, Wednesday, Friday).

---

## How It Works

1. **Scripting**: Automated writer routines run three times daily, follow `WRITER.md` for research and quality rules, and push validated script JSON files to `scripts/queue/<id>.json` alongside research notes in `notes/<id>.md`.
2. **Merging & Queuing**: The `render.yml` workflow runs on GitHub Actions, merging incoming script branches into `main` and processing queued scripts in chronological order.
3. **Audio & Visual Pipeline**:
   - `tts.py` generates speech with word-level timestamps using Kokoro TTS.
   - `visuals.py` builds a picture pool from the wiki articles the script is about and ranks files against each line; `framing.py` crops them to fill the vertical frame.
   - `video.py` renders the clips, animated subtitles, audio sidechain ducking, and sound effects via FFmpeg.
4. **Scheduled Upload**: `upload.py` uploads the finished video to YouTube, assigns it to the series playlist, and schedules it for the next free publish slot in `channel.json`. The script's discussion question is posted as the first comment once the video goes public (the 3-hourly run does this).
5. **Alerts & Archive**: After each upload, ntfy sends your phone the title, the scheduled time (IST) and the YouTube Studio link, and the script moves to `scripts/done/<id>.json`.
6. **Daily Insights**: `insights.yml` runs daily, querying the YouTube Data API to update `data/performance.md` (video stats and YPP progress) and `data/trends.md` (high-velocity niche search trends).

---

## Visuals, Voice & Editing

- **Visual Sourcing**: `visuals.py` pulls every image on the wiki articles in the script's `pages` (and its wiki `sources`) from the public Fandom MediaWiki APIs, adds a file search on each line's `shot.search`, and ranks files by how many words their descriptive names share with the search words and the spoken line ("Zoro Stabs Sommers Chest.png"). Manga panels and anime screenshots only: icons, logos, merchandise, figure lines and game renders are filtered out. Line 1 opens on the most colourful close-up match. AI images (`images.py`) are a last resort when the wiki has nothing. Stills only, shown under commentary; never episode footage.
- **Voice Narration**: Voiced by Kokoro TTS using a custom weighted blend (`voice_blend` in `channel.json`, defaulting to 65% `am_michael` + 35% `am_fenrir`) running locally on CPU.
- **Dynamic Editing**:
  - **Shorts**: Full-screen pictures (content-aware 9:16 crop, no blurred bars) that change about every second: each line is split into 1-4 beats on word boundaries, each beat a different matching picture (or a punch-in recut when only one matches), with push-in / pull-out / drift motion. Plus punch zooms, camera shakes, flashes, procedural sound effects (whoosh, hit, riser), top-screen hook text (~2.5s), and two-word ASS captions with the active word highlighted in yellow (`#FFD21E`). Endings loop naturally into the hook. This matches what the top theory Shorts in the niche do (a cut every 0.8-1.2 s, full-bleed art).
  - **Long Videos**: Cinematic 0.35s crossfades between shots, chapter title cards, YouTube chapters in the description, an uploaded caption track, and a 1280x720 thumbnail with 2-4 big words.

---

## Channel Controls

Key settings are configured in `channel.json` or through GitHub repository variables:

| Control | Where to Set | Options / Default | Description |
| :--- | :--- | :--- | :--- |
| **Publish Mode** | Repo Variable `PUBLISH_MODE` | `schedule` (default), `private`, `public` | Controls visibility of new YouTube uploads. |
| **Publish Slots** | `channel.json` (`publish`) | UTC times (e.g. `12:00`, `14:30`...) | Daily upload time slots and minimum lead hours. |
| **Long Video Days** | `channel.json` (`long_days`) | `["Mon", "Wed", "Fri"]` | Days when long-form breakdown videos publish. |
| **Voice Blend** | `channel.json` (`voice_blend`) | `{"am_michael": 0.65, "am_fenrir": 0.35}` | Weighted combination of Kokoro voice tensors. |
| **Voice Override** | Repo Variable `KOKORO_VOICE` | Voice ID (e.g. `am_michael`) | Overrides the voice blend with a single voice. |
| **Series & Weights** | `channel.json` (`series_weights`) | Franchise weight map | Topic distribution across One Piece, Naruto, and JJK. |
| **AI Disclosure** | Repo Variable `SYNTHETIC_DISCLOSURE` | `0` (default) or `1` | Sets YouTube's altered/synthetic content disclosure flag. |
| **Background Music** | Folder `music/<mood>/` | `hype`, `suspense`, `emotional`, `epic`, `chill` | Royalty-free MP3 tracks from YouTube Audio Library. |

*Note: If a mood folder is empty, the pipeline synthesizes a tasteful ambient background pad automatically.*

---

## Owner Routines

### Daily Routine (5 Minutes)
1. **Glance at Notifications**: When a video renders and uploads, ntfy pings your phone with the video title and Studio link.
2. **Review Scheduled Uploads**: Open YouTube Studio. Check the scheduled video and thumbnail; delete or reschedule if you want any adjustments before the publish time.
3. **Pin the First Comment**: A few hours after a video goes public, the pipeline posts its discussion question as the first comment. Pin it in YouTube Studio (the API cannot pin).
4. **Link Related Video on Shorts**: In YouTube Studio, edit the newly uploaded Short and set its **Related video** selector to the latest long-form video.

### Weekly Routine (10 Minutes)
- Review `data/performance.md` to see which topics, hooks, and formats generated the highest views per day and like rates.
- Review `data/trends.md` to inspect emerging high-velocity search queries across your series.

---

## Troubleshooting

- **Workflow Failures**: Check **GitHub Actions** > **render-and-publish**. Inspect logs on any failed step.
- **Failed Scripts**: If a script fails 3 consecutive render attempts, it is parked in `scripts/failed/` to avoid holding up the queue. Once resolved, move the JSON back to `scripts/queue/` to retry.
- **Quota Fallback**: If the main Google project hits a YouTube quota limit, uploads switch to the reserve project automatically (when its secrets are set).

---

## Monetization & Fair Use

- **YouTube Partner Program (YPP)**: Requires 1,000 subscribers and either 10M Shorts views in 90 days or 4,000 public watch hours. (Note: Starting 1 Feb 2027, new YPP thresholds adjust to 20M Shorts views or 8,000 watch hours). Long-form videos provide the most reliable path to meeting watch-hour criteria.
- **Copyright & Fair Use**: Content consists of original commentary illustrated by brief still images and manga panels. Raw anime footage or full scenes are never used. Content ID rarely matches still images; if a claim arrives, it usually only redirects that video's ad money. Dispute only when the video is clearly commentary.
- **Archive**: Former history-channel assets and scripts remain archived in `archive/history/`.
