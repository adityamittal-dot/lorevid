"""Music beds: real cinematic tracks under the narration instead of a synthesized pad.

Tracks are Scott Buckley's Creative Commons library (CC BY 4.0: free for monetized videos when credited).
His Smart Content ID looks for "Scott Buckley" in the description, so every video that uses a track gets
`credit()` appended to its description. The MP3s are not in git: CI runs `python music.py fetch` (cached).
Drop any other licensed MP3 into music/<mood>/ and it joins the pool (no credit line is added for those).

The top Shorts in the niche keep their music 5-8 dB under the voice and audible in every gap; ours sat 13-17 dB
under (inaudible). `bed()` cuts the track's most energetic stretch and levels it relative to the narration."""
import glob
import os
import random
import re
import subprocess
import sys

import numpy as np

BASE = "https://www.scottbuckley.com.au/library/wp-content/uploads/"
CREDIT = "{title} by Scott Buckley – released under CC-BY 4.0. www.scottbuckley.com.au"

# file, upload path, title, moods
TRACKS = [
    ("EyesInTheVoid.mp3", "2025/06/", "Eyes In The Void", ["suspense"]),
    ("Unraveling.mp3", "2026/05/", "Unraveling", ["suspense", "emotional"]),
    ("Penumbra.mp3", "2025/07/", "Penumbra", ["suspense", "emotional"]),
    ("Anabasis_II.mp3", "2026/09/", "Anabasis II", ["suspense", "hype"]),
    ("SongOfTheForge.mp3", "2025/11/", "Song Of The Forge", ["epic"]),
    ("Aphelion.mp3", "2026/04/", "Aphelion", ["epic"]),
    ("Starfire.mp3", "2026/01/", "Starfire", ["epic"]),
    ("Katabasis_II.mp3", "2026/09/", "Katabasis II", ["epic", "hype"]),
    ("BornOfTheSky.mp3", "2025/08/", "Born Of The Sky", ["hype"]),
    ("Convergence.mp3", "2026/04/", "Convergence", ["hype", "emotional"]),
    ("Wildflowers.mp3", "2025/12/", "Wildflowers", ["emotional"]),
    ("MemoriesOfStone.mp3", "2026/02/", "Memories Of Stone", ["emotional"]),
    ("EchoesOfHome.mp3", "2025/05/", "Echoes Of Home", ["chill", "emotional"]),
    ("Origami.mp3", "2025/10/", "Origami", ["chill"]),
    ("Phoenix2026.mp3", "2026/03/", "Phoenix", ["chill"]),
]
MOODS = ["hype", "suspense", "emotional", "epic", "chill"]
REPO_DIR = os.path.abspath(os.path.dirname(__file__))
LIB = os.path.join(REPO_DIR, "music", "library")
BED_BELOW_VOICE = {"short": 6.0, "long": 9.0}   # dB under the narration's loudness, before ducking


def _library_urls():
    try:
        html = subprocess.run(["curl", "-fsSL", "--max-time", "60", "https://www.scottbuckley.com.au/library/"],
                              stdout=subprocess.PIPE, check=True).stdout.decode(errors="replace")
        return {u.rsplit("/", 1)[-1]: u for u in re.findall(r"https?://[^\"']+?\.mp3", html)}
    except Exception as e:
        print(f"  music: library page unavailable ({e})")
        return {}


def fetch():
    """Download any missing track into music/library/. Never fails the build: missing tracks fall back."""
    os.makedirs(LIB, exist_ok=True)
    found = None
    for name, path, _, _ in TRACKS:
        dest = os.path.join(LIB, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 100_000:
            continue
        urls = [BASE + path + name]
        for attempt in range(2):
            for u in urls:
                # curl, not urllib: the site's firewall answers urllib's request with HTTP 406
                p = subprocess.run(["curl", "-fsSL", "--retry", "3", "--max-time", "300", u],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if p.returncode:
                    print(f"  music: {name} failed from {u} ({p.stderr.decode(errors='replace').strip()})")
                    continue
                data = p.stdout
                if len(data) > 100_000:
                    with open(dest, "wb") as f:
                        f.write(data)
                    print(f"  music: {name} ({len(data) // 1_000_000} MB)")
                    break
            if os.path.exists(dest):
                break
            if found is None:                      # the file moved: look it up on the library page
                found = _library_urls()
            urls = [found[name]] if name in found else []
    have = [n for n, *_ in TRACKS if os.path.exists(os.path.join(LIB, n))]
    print(f"music library: {len(have)}/{len(TRACKS)} tracks")
    return have


def candidates(mood):
    """Library tracks tagged with the mood, plus any MP3 dropped into music/<mood>/."""
    out = [os.path.join(LIB, n) for n, _, _, moods in TRACKS
           if mood in moods and os.path.exists(os.path.join(LIB, n))]
    out += glob.glob(os.path.join(REPO_DIR, "music", mood, "*.mp3"))
    if not out:   # unknown or empty mood: any track beats a synthesized pad
        out = [os.path.join(LIB, n) for n, *_ in TRACKS if os.path.exists(os.path.join(LIB, n))]
        out += glob.glob(os.path.join(REPO_DIR, "music", "*", "*.mp3"))
    return sorted(set(out))


def credit(paths):
    titles = {n: t for n, _, t, _ in TRACKS}
    lines = [CREDIT.format(title=titles[os.path.basename(p)]) for p in paths if os.path.basename(p) in titles]
    return ("Music: " + "\n".join(lines)) if lines else ""


def _ff(cmd):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", *cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError("ffmpeg failed:\n" + p.stderr.decode(errors="replace")[-1500:])
    return p


def loudness(path):
    """Integrated loudness (LUFS) via ffmpeg's ebur128."""
    err = _ff(["-i", path, "-af", "ebur128", "-f", "null", "-"]).stderr.decode(errors="replace")
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    return float(m[-1]) if m else -23.0


def _energetic_start(path, seconds, rng):
    """Start offset of the loudest stretch of the track (orchestral tracks open quietly; a Short has no time to wait)."""
    raw = _ff(["-i", path, "-ac", "1", "-ar", "4000", "-f", "s16le", "-"]).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    total = len(x) / 4000.0
    if total <= seconds + 4:
        return 0.0
    env = np.sqrt(np.convolve(x ** 2, np.ones(4000) / 4000, mode="valid")[::4000])   # 1 s RMS
    win = int(min(seconds, 45))
    score = np.convolve(env, np.ones(win), mode="valid")
    top = np.argsort(score)[::-1][:5]               # a little variety between videos on the same track
    start = float(rng.choice(top))
    return max(0.0, min(start, total - seconds - 1))


def bed(mood, work, seconds, narration, fmt, seed=0):
    """Write work/music_bed.wav: leveled, faded music that covers `seconds`. Returns (path, [tracks used]) or (None, [])."""
    rng = random.Random(seed)
    pool = candidates(mood)
    if not pool:
        return None, []
    rng.shuffle(pool)
    out = os.path.join(work, "music_bed.wav")
    target = loudness(narration) - BED_BELOW_VOICE.get(fmt, 10.0)
    used, inputs, filters, t = [], [], [], 0.0
    need = seconds + 2.0
    xfade = 4.0
    while t < need and len(used) < 12:
        track = pool[len(used) % len(pool)]
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                             "-of", "default=nw=1:nk=1", track]).decode().strip())
        if not used:
            start = _energetic_start(track, need, rng)
            take = min(dur - start, need)
            t = take
        else:                                     # next track crossfades in over the last 4 s of the previous one
            start = 0.0
            take = min(dur, need - t + xfade)
            if take <= xfade + 0.5:
                break
            t += take - xfade
        i = len(used)
        inputs += ["-ss", f"{start:.2f}", "-t", f"{take:.2f}", "-i", track]
        filters.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[t{i}]")
        used.append(track)
    chain = "[t0]"
    for i in range(1, len(used)):
        filters.append(f"{chain}[t{i}]acrossfade=d=4:c1=tri:c2=tri[x{i}]")
        chain = f"[x{i}]"
    fade_out = max(0.0, seconds - 2.0)
    filters.append(f"{chain}atrim=0:{seconds:.3f},loudnorm=I={target:.1f}:TP=-3:LRA=11,"
                   f"afade=t=in:d=0.6,afade=t=out:st={fade_out:.2f}:d=2.0,aresample=48000[bed]")
    _ff(["-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[bed]", "-ac", "2", out])
    return out, used


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        fetch()
    else:
        print("usage: python music.py fetch")
