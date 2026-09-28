"""Narration via Kokoro TTS with word timestamps and edge-tts fallback."""
import asyncio
import json
import os
import subprocess
import numpy as np
import soundfile as sf

ENGINE = os.getenv("TTS_ENGINE", "kokoro")
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "am_michael")
EDGE_VOICE = os.getenv("EDGE_VOICE", "en-US-GuyNeural")

_kpipes = {}
_blends = {}

VOICES = {
    "af_heart": "American female, soft, intimate",
    "af_bella": "American female, warm, expressive",
    "am_michael": "American male, calm, documentary",
    "am_fenrir": "American male, deep, commanding",
    "am_puck": "American male, energetic",
    "am_echo": "American male, clear, smooth",
    "am_eric": "American male, lively",
    "am_liam": "American male, conversational",
    "am_adam": "American male, gritty",
    "am_onyx": "American male, very deep",
    "bm_george": "British male, deep, warm storyteller",
    "bm_lewis": "British male, older, grave",
    "bm_fable": "British male, softer, fairy-tale feel",
    "bm_daniel": "British male, authoritative",
    "bf_emma": "British female, gentle, elegant",
    "bf_isabella": "British female, warm, mature",
}

DELIVERY = {
    "normal": (1.0, 0.22),
    "punch": (1.06, 0.12),
    "reveal": (0.94, 0.55),
    "aside": (1.08, 0.15),
    "slow": (0.9, 0.45),
}

def duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)]
    ).decode().strip()
    return float(out)


def voice_from_channel(cfg=None):
    env_voice = os.getenv("KOKORO_VOICE")
    if env_voice:
        return env_voice
    if isinstance(cfg, (str, bytes, os.PathLike)) and os.path.exists(cfg):
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = None
    if isinstance(cfg, dict):
        blend = cfg.get("voice_blend")
        if blend:
            return blend
        narrator = cfg.get("narrator_voice")
        if narrator:
            return narrator
    return "am_michael"


def _is_punct(s):
    return bool(s) and all(not c.isalnum() and not c.isspace() for c in s)


def _get_pipeline(lang_code):
    if lang_code not in _kpipes:
        from kokoro import KPipeline
        _kpipes[lang_code] = KPipeline(lang_code=lang_code)
    return _kpipes[lang_code]


def _resolve_voice(pipe, voice):
    if isinstance(voice, dict):
        blend_key = json.dumps(voice, sort_keys=True)
        if blend_key not in _blends:
            total_w = sum(voice.values()) or 1.0
            blended = None
            for vid, weight in voice.items():
                vt = pipe.load_voice(vid)
                term = vt * float(weight)
                if blended is None:
                    blended = term.clone() if hasattr(term, "clone") else term.copy()
                else:
                    blended = blended + term
            blended = blended / float(total_w)
            _blends[blend_key] = blended
        return _blends[blend_key]
    return voice


def word_times(text, start, dur):
    words = text.split()
    if not words:
        return []
    total = sum(len(w) + 1 for w in words) or 1
    t, out = start, []
    for w in words:
        d = dur * (len(w) + 1) / total
        out.append((round(t, 3), round(t + d, 3), w))
        t += d
    return out


def _kokoro(text, out_wav, speed=1.0, voice=None):
    if not voice:
        voice = os.getenv("KOKORO_VOICE", "am_michael")

    if isinstance(voice, dict):
        lang_code = next(iter(voice.keys()))[0]
    else:
        lang_code = str(voice)[0]

    pipe = _get_pipeline(lang_code)
    kokoro_voice = _resolve_voice(pipe, voice)

    parts = []
    words = []
    total_samples = 0
    has_missing_timestamps = False
    prefix_punct = ""

    for r in pipe(text, voice=kokoro_voice, speed=speed):
        audio = r.audio
        if hasattr(audio, "detach"):
            audio = audio.detach()
        if hasattr(audio, "cpu"):
            audio = audio.cpu()
        if hasattr(audio, "numpy"):
            audio = audio.numpy()
        elif not isinstance(audio, np.ndarray):
            audio = np.array(audio)

        audio = np.squeeze(audio)
        if audio.ndim == 0 or len(audio) == 0:
            continue

        chunk_samples = len(audio)
        chunk_offset = total_samples / 24000.0
        parts.append(audio)
        total_samples += chunk_samples

        tokens = getattr(r, "tokens", None)
        if tokens is None:
            has_missing_timestamps = True
            continue

        for tok in tokens:
            tok_text = getattr(tok, "text", "")
            if not tok_text:
                continue

            tok_str = tok_text.strip()
            if not tok_str:
                continue

            start_ts = getattr(tok, "start_ts", None)
            end_ts = getattr(tok, "end_ts", None)
            if start_ts is None or end_ts is None:
                has_missing_timestamps = True
                continue

            abs_start = round(chunk_offset + float(start_ts), 3)
            abs_end = round(chunk_offset + float(end_ts), 3)
            if abs_end <= abs_start:
                abs_end = round(abs_start + 0.05, 3)

            if _is_punct(tok_str):
                if words:
                    prev_start, prev_end, prev_w = words[-1]
                    words[-1] = (prev_start, max(prev_end, abs_end), prev_w + tok_str)
                else:
                    prefix_punct += tok_str
            else:
                w_text = prefix_punct + tok_str
                prefix_punct = ""
                words.append((abs_start, abs_end, w_text))

    if prefix_punct and words:
        prev_start, prev_end, prev_w = words[-1]
        words[-1] = (prev_start, prev_end, prev_w + prefix_punct)
        prefix_punct = ""

    if not parts:
        raise RuntimeError("Kokoro produced no audio")

    audio_data = np.concatenate(parts)
    parent = os.path.dirname(os.path.abspath(out_wav))
    if parent:
        os.makedirs(parent, exist_ok=True)
    sf.write(out_wav, audio_data, 24000)

    total_dur = len(audio_data) / 24000.0
    if has_missing_timestamps or not words:
        words = word_times(text, 0.0, total_dur)
    else:
        words = [(s, min(e, round(total_dur, 3)), w) for s, e, w in words]

    return words


def _edge(text, out_wav, speed=1.0):
    import edge_tts
    rate = f"{int(round((speed - 1) * 100)):+d}%"
    mp3 = out_wav + ".mp3"
    for attempt in range(4):
        try:
            asyncio.run(edge_tts.Communicate(text, EDGE_VOICE, rate=rate).save(mp3))
            break
        except Exception as e:
            print(f"  edge-tts error {e}")
            if attempt == 3:
                raise
    parent = os.path.dirname(os.path.abspath(out_wav))
    if parent:
        os.makedirs(parent, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ar", "24000", "-ac", "1", out_wav],
        check=True,
    )
    if os.path.exists(mp3):
        try:
            os.remove(mp3)
        except OSError:
            pass


def _edge_line(text, out_wav, speed=1.0):
    _edge(text, out_wav, speed)
    dur = duration(out_wav)
    return word_times(text, 0.0, dur)


def speak_line(text, out_wav, speed=1.0, voice=None):
    global ENGINE
    if voice is None:
        voice = os.getenv("KOKORO_VOICE", "am_michael")

    if ENGINE == "kokoro":
        try:
            return _kokoro(text, out_wav, speed, voice)
        except Exception as e:
            print(f"  Kokoro failed ({e}); switching to edge-tts")
            ENGINE = "edge"

    return _edge_line(text, out_wav, speed)


def _ts(t):
    return f"{int(t // 3600):02}:{int(t % 3600 // 60):02}:{t % 60:06.3f}".replace(".", ",")


def write_srt(words, path, max_words=7):
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w[0] - cur[-1][1] > 0.3 or (cur[-1][2] and cur[-1][2][-1] in ".?!")):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(
            f"{n}\n{_ts(g[0][0])} --> {_ts(g[-1][1])}\n{' '.join(x[2] for x in g)}\n"
            for n, g in enumerate(groups, 1)
        ))
