"""Narration. TTS_ENGINE=kokoro (best free voice, runs on CPU) or edge (Microsoft neural, needs internet).
Kokoro failures fall back to edge-tts automatically. Word timings for captions are spread over each
clip by character length (accurate enough for 3-7 word captions)."""
import asyncio, os, subprocess

ENGINE = os.getenv("TTS_ENGINE", "kokoro")
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "bm_george")        # British male storyteller; try bm_fable, am_michael
EDGE_VOICE = os.getenv("EDGE_VOICE", "en-GB-RyanNeural")
_kpipe = None


def duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "default=nw=1:nk=1", path]).strip())


def _kokoro(text, out_wav, speed):
    global _kpipe
    import numpy as np, soundfile as sf
    from kokoro import KPipeline
    if _kpipe is None:
        _kpipe = KPipeline(lang_code=KOKORO_VOICE[0])
    parts = [r.audio.numpy() if hasattr(r.audio, "numpy") else r.audio
             for r in _kpipe(text, voice=KOKORO_VOICE, speed=speed)]
    sf.write(out_wav, np.concatenate(parts), 24000)


def _edge(text, out_wav, speed):
    import edge_tts
    rate = f"{int(round((speed - 1) * 100)):+d}%"
    mp3 = out_wav + ".mp3"
    for attempt in range(4):
        try:
            asyncio.run(edge_tts.Communicate(text, EDGE_VOICE, rate=rate).save(mp3))
            break
        except Exception as e:
            print(f"  edge-tts error {e}")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, out_wav], check=True)
    os.remove(mp3)


def speak(text, out_wav, speed=0.95):
    global ENGINE
    if ENGINE == "kokoro":
        try:
            return _kokoro(text, out_wav, speed)
        except Exception as e:
            print(f"  Kokoro failed ({e}); switching to edge-tts")
            ENGINE = "edge"
    _edge(text, out_wav, speed)


def word_times(text, start, dur):
    words = text.split()
    total = sum(len(w) + 1 for w in words) or 1
    t, out = start, []
    for w in words:
        d = dur * (len(w) + 1) / total
        out.append((t, t + d, w))
        t += d
    return out


def _ts(t):
    return f"{int(t // 3600):02}:{int(t % 3600 // 60):02}:{t % 60:06.3f}".replace(".", ",")


def write_srt(words, path, max_words=7):
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w[0] - cur[-1][1] > 0.3 or cur[-1][2][-1] in ".?!"):
            groups.append(cur); cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    open(path, "w", encoding="utf-8").write("\n".join(
        f"{n}\n{_ts(g[0][0])} --> {_ts(g[-1][1])}\n{' '.join(x[2] for x in g)}\n" for n, g in enumerate(groups, 1)))
