"""Validate a writer script before commit: python validate_script.py scripts/queue/<id>.json"""
import glob
import json
import os
import re
import sys

VALID_MOODS = {"hype", "suspense", "emotional", "epic", "chill"}
VALID_DELIVERY = {"normal", "punch", "reveal", "aside", "slow"}
VALID_FX = {"none", "zoom", "shake", "flash"}
VALID_THUMB_DEVICES = {"circle", "question", "blur", "split"}
REQUIRED_KEYS = [
    "id", "format", "series", "wiki", "topic", "title", "description",
    "hashtags", "tags", "music_mood", "comment", "lines", "sources", "self_check"
]

BANNED_AI_PATTERNS = [
    ("delve", r"\bdelv\w*"),
    ("tapestry", r"\btapestr\w*"),
    ("testament", r"\btestament\w*"),
    ("embark", r"\bembark\w*"),
    ("realm", r"\brealm\w*"),
    ("unleash", r"\bunleash\w*"),
    ("in this video", r"\bin this video\b"),
    ("let's dive", r"\blet'?s dive\b"),
    ("buckle up", r"\bbuckle up\b"),
    ("little did", r"\blittle did\b"),
    ("without further ado", r"\bwithout further ado\b"),
    ("journey", r"\bjourney\w*"),
    ("game-changer", r"\bgame[- ]?changer\w*"),
]

DEFAULT_LIMITS = {
    "short": {"min_lines": 8, "max_lines": 22, "min_words": 95, "max_words": 165},
    "long": {"min_lines": 100, "max_lines": 260, "min_words": 2200, "max_words": 3000},
}

# Fallback if channel.json has no "banned_phrases" (it does by default; see channel.json). Long videos only:
# these are stock narrator filler that reads as AI-generated and gets called out in comments.
DEFAULT_BANNED_PHRASES = [
    "to understand how we get there", "remember ", "let's dive in", "buckle up", "in this video",
    "thanks for watching", "don't forget to subscribe", "smash that like", "without further ado",
    "little did", "but here's the thing", "fast forward",
]

# The last line is the payoff, not a sign-off: these mark it as an outro instead.
OUTRO_PATTERNS = [
    ("subscribe", r"\bsubscribe\b"),
    ("thanks", r"\bthanks\b"),
    ("see you", r"\bsee you\b"),
    ("comment below", r"\bcomment below\b"),
]

HOOK_START_WORDS = {"but", "until", "except"}
SPOILER_CHAPTER_WORDS = re.compile(r"\b(revealed|explained|conclusion)\b", re.I)


def _banned_phrase_pattern(phrase):
    """Word-bounded, whitespace-flexible regex for one banned phrase. "remember " is handled separately
    (sentence-initial only), so it never reaches here as a generic pattern."""
    escaped = r"\s+".join(re.escape(w) for w in phrase.split())
    return re.compile(r"\b" + escaped + r"\b", re.I)


def _sentences(text):
    """Split one line's narration into sentences (a line is usually one, but "aside" lines can hold two)."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def _ends_hooky(text):
    """True if a line ends on a cliffhanger ("?", "...", "…") or opens with a hook word (But/Until/Except) —
    the shape that makes a viewer want the next chapter instead of leaving."""
    t = text.strip()
    if t.endswith("?") or t.endswith("...") or t.endswith("…"):
        return True
    first = re.match(r"[A-Za-z']+", t)
    return bool(first and first.group(0).lower() in HOOK_START_WORDS)


def load_channel_config(repo_dir):
    candidates = [
        os.path.join(repo_dir, "channel.json"),
        os.path.join(os.getcwd(), "channel.json"),
        "channel.json",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def get_format_limits(channel_cfg, fmt):
    defaults = DEFAULT_LIMITS.get(fmt, {"min_lines": 1, "max_lines": 9999, "min_words": 1, "max_words": 99999})
    limits = dict(defaults)
    formats_cfg = channel_cfg.get("formats", {})
    if isinstance(formats_cfg, dict) and fmt in formats_cfg:
        f_entry = formats_cfg[fmt]
        if isinstance(f_entry, dict):
            if "min_lines" in f_entry:
                limits["min_lines"] = f_entry["min_lines"]
            if "max_lines" in f_entry:
                limits["max_lines"] = f_entry["max_lines"]
            if "min_words" in f_entry:
                limits["min_words"] = f_entry["min_words"]
            if "max_words" in f_entry:
                limits["max_words"] = f_entry["max_words"]
            if "lines" in f_entry and isinstance(f_entry["lines"], (list, tuple)) and len(f_entry["lines"]) >= 2:
                limits["min_lines"], limits["max_lines"] = f_entry["lines"][0], f_entry["lines"][1]
            if "words" in f_entry and isinstance(f_entry["words"], (list, tuple)) and len(f_entry["words"]) >= 2:
                limits["min_words"], limits["max_words"] = f_entry["words"][0], f_entry["words"][1]
    return limits


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_script.py scripts/queue/<id>.json")
        sys.exit(1)

    script_path = sys.argv[1]
    if not os.path.exists(script_path):
        print(f"ERROR: script file not found: {script_path}")
        sys.exit(1)

    try:
        with open(script_path, "r", encoding="utf-8") as f:
            p = json.load(f)
    except Exception as e:
        print(f"ERROR: failed parsing JSON in {script_path}: {e}")
        sys.exit(1)

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    channel_cfg = load_channel_config(repo_dir)
    banned_phrases = channel_cfg.get("banned_phrases") or DEFAULT_BANNED_PHRASES

    err = []
    warn = []

    # 1. Schema check & required keys
    for k in REQUIRED_KEYS:
        if k not in p:
            err.append(f"missing required key: '{k}'")

    script_id = str(p.get("id", ""))
    filename_id = os.path.splitext(os.path.basename(script_path))[0]
    if script_id != filename_id:
        err.append(f"id '{script_id}' does not match filename '{filename_id}'")

    fmt = p.get("format")
    if fmt not in {"short", "long"}:
        err.append(f"format must be 'short' or 'long' (got '{fmt}')")

    # Series check
    configured_series = {
        s.get("id") for s in channel_cfg.get("series", []) if isinstance(s, dict) and "id" in s
    }
    valid_series = configured_series if configured_series else {"onepiece", "naruto", "jjk"}
    if p.get("series") not in valid_series:
        err.append(f"series must be one of {sorted(valid_series)} (got '{p.get('series')}')")

    if p.get("music_mood") not in VALID_MOODS:
        err.append(f"music_mood must be one of {sorted(VALID_MOODS)} (got '{p.get('music_mood')}')")

    if not isinstance(p.get("wiki"), str) or not p.get("wiki", "").strip():
        err.append("wiki domain must be a non-empty string")

    # 2. Line narration and word counts
    lines = p.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        err.append("lines must be a non-empty list")
        lines = []

    n_lines = len(lines)
    total_words = 0

    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            err.append(f"line {i+1}: must be an object")
            continue

        text = line.get("text", "")
        if not isinstance(text, str) or not text.strip():
            err.append(f"line {i+1}: narration text is empty")
            continue

        w_list = text.split()
        lw = len(w_list)
        total_words += lw

        if lw < 3 or lw > 30:
            err.append(f"line {i+1}: narration has {lw} words (allowed 3-24 words, max 30)")
        elif lw > 24:
            warn.append(f"line {i+1}: narration has {lw} words (warn: exceeds 24 words)")

        sym_matches = [ch for ch in ["%", "&", "/"] if ch in text]
        if sym_matches:
            warn.append(f"line {i+1}: text contains symbols {sym_matches}; spell out numbers and symbols")

        deliv = line.get("delivery")
        if deliv not in VALID_DELIVERY:
            err.append(f"line {i+1}: delivery must be one of {sorted(VALID_DELIVERY)} (got '{deliv}')")

        fx = line.get("fx")
        if fx not in VALID_FX:
            err.append(f"line {i+1}: fx must be one of {sorted(VALID_FX)} (got '{fx}')")

        shot = line.get("shot")
        if not isinstance(shot, dict):
            err.append(f"line {i+1}: missing shot object")
        else:
            has_search = bool(shot.get("search") and str(shot.get("search")).strip())
            has_fallback = bool(shot.get("fallback") and str(shot.get("fallback")).strip())
            if not has_search and not has_fallback:
                err.append(f"line {i+1}: shot must have at least 'search' or 'fallback'")
            elif has_search and len(str(shot.get("search")).split()) < 2:
                warn.append(f"line {i+1}: shot.search '{shot.get('search')}' is one word; name the character AND the "
                            f"action or event (e.g. 'Zoro Sommers steel heart')")

        for name, pattern in BANNED_AI_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                err.append(f"line {i+1}: narration contains banned AI word/phrase '{name}'")

        if fmt == "long":
            for phrase in banned_phrases:
                if phrase == "remember ":
                    if any(re.match(r"^Remember\b", s) for s in _sentences(text)):
                        err.append(f"line {i+1}: starts a sentence with 'Remember ' (stock recap phrase); "
                                   f"cut it or rewrite the sentence without the word at the start")
                elif _banned_phrase_pattern(phrase).search(text):
                    err.append(f"line {i+1}: narration contains banned stock phrase '{phrase}'")

    # Format bounds
    if fmt in {"short", "long"}:
        limits = get_format_limits(channel_cfg, fmt)
        if not (limits["min_lines"] <= n_lines <= limits["max_lines"]):
            err.append(f"{fmt} lines count {n_lines} outside allowed range [{limits['min_lines']}, {limits['max_lines']}]")
        if not (limits["min_words"] <= total_words <= limits["max_words"]):
            err.append(f"{fmt} words count {total_words} outside allowed range [{limits['min_words']}, {limits['max_words']}]")

    # Picture pool: wiki articles named in "pages" or linked in "sources"
    pages = p.get("pages", [])
    if pages is not None and (not isinstance(pages, list) or not all(isinstance(x, str) and x.strip() for x in pages)):
        err.append("pages must be a list of wiki article titles (strings)")
    else:
        wiki_links = [u for u in p.get("sources", []) if isinstance(u, str) and str(p.get("wiki", "")) in u and "/wiki/" in u]
        if len(pages or []) + len(wiki_links) < 2:
            warn.append("fewer than 2 wiki articles in 'pages' + wiki 'sources'; add 2-5 specific article titles to "
                        "'pages' so the renderer has on-topic pictures (see WRITER.md section 7)")

    # 3. Title check
    title = str(p.get("title", ""))
    max_title = 60 if fmt == "short" else 70
    if not title:
        err.append("title is missing or empty")
    else:
        if len(title) > max_title:
            err.append(f"title length ({len(title)} chars) exceeds limit of {max_title} chars for {fmt}")
        if "#" in title:
            err.append("title must not contain hashtags")
        title_alpha_words = re.findall(r"\b[A-Za-z]+\b", title)
        all_caps = [w for w in title_alpha_words if len(w) >= 2 and w.isupper()]
        if len(all_caps) > 1:
            err.append(f"title has more than 1 ALL-CAPS word ({', '.join(all_caps)}); at most 1 allowed")

    # 4. Hashtags check
    hashtags = p.get("hashtags")
    if not isinstance(hashtags, list) or not (3 <= len(hashtags) <= 5):
        err.append(f"hashtags must have 3-5 items (got {len(hashtags) if isinstance(hashtags, list) else 0})")
    else:
        for tag in hashtags:
            if not isinstance(tag, str) or not tag.startswith("#") or len(tag.strip()) <= 1 or " " in tag:
                err.append(f"invalid hashtag '{tag}': must start with '#' and have no spaces")

    # 5. Tags check
    tags = p.get("tags")
    if not isinstance(tags, list) or not (8 <= len(tags) <= 15):
        err.append(f"tags must have 8-15 items (got {len(tags) if isinstance(tags, list) else 0})")

    # 6. Format-specific checks
    if fmt == "short":
        hook_text = p.get("hook_text")
        if not hook_text or not isinstance(hook_text, str):
            err.append("shorts require 'hook_text'")
        else:
            hw = len(hook_text.strip().split())
            if not (2 <= hw <= 6):
                err.append(f"hook_text must be 2-6 words (got {hw})")

    elif fmt == "long":
        chapters = p.get("chapters")
        if not isinstance(chapters, list) or len(chapters) < 3:
            err.append(f"long video requires at least 3 chapters (got {len(chapters) if isinstance(chapters, list) else 0})")
        else:
            if chapters[0].get("line") != 0:
                err.append(f"first chapter must start at line 0 (got {chapters[0].get('line')})")
            prev_line = -1
            for ci, ch in enumerate(chapters):
                ch_line = ch.get("line")
                ch_title = ch.get("title")
                if not isinstance(ch_line, int) or ch_line < 0 or (n_lines > 0 and ch_line >= n_lines):
                    err.append(f"chapter {ci+1}: invalid line index {ch_line}")
                elif ch_line <= prev_line:
                    err.append(f"chapter {ci+1}: line {ch_line} must be strictly greater than previous chapter line {prev_line}")
                if not ch_title or not str(ch_title).strip():
                    err.append(f"chapter {ci+1}: missing title")
                else:
                    ch_title_s = str(ch_title).strip()
                    if len(ch_title_s.split()) > 6:
                        err.append(f"chapter {ci+1} title '{ch_title_s}' is more than 6 words; "
                                   f"chapter titles are teasers on screen, not sentences")
                    if SPOILER_CHAPTER_WORDS.search(ch_title_s):
                        warn.append(f"chapter {ci+1} title '{ch_title_s}' reads like a spoiler label "
                                    f"(contains 'revealed'/'explained'/'conclusion'); tease the question, not the answer")
                if isinstance(ch_line, int):
                    prev_line = ch_line

            # The line right before every chapter 2..n (the last beat of the chapter before it) is the re-hook:
            # it has to make the viewer want the next chapter, not just stop. Same bar for the cold-open's own
            # last line, found by the ~30s mark (long narration runs ~3 words/second, see `rate` below).
            hook_line_idxs = {}
            for ci in range(1, len(chapters)):
                ch_line = chapters[ci].get("line")
                ch_title = chapters[ci].get("title")
                if isinstance(ch_line, int) and 0 < ch_line <= n_lines:
                    hook_line_idxs[ch_line - 1] = f"before chapter {ci+1} ('{ch_title}')"
            cum_words, cold_open_idx = 0, None
            for i, line in enumerate(lines):
                if not isinstance(line, dict):
                    continue
                cum_words += len(str(line.get("text", "")).split())
                if cum_words / 3.0 >= 30.0:
                    cold_open_idx = max(0, i - 1)
                    break
            if cold_open_idx is not None:
                hook_line_idxs.setdefault(cold_open_idx, "the cold open's last line (~30s mark)")
            for idx, where in sorted(hook_line_idxs.items()):
                if idx >= len(lines) or not isinstance(lines[idx], dict):
                    continue
                line_text = str(lines[idx].get("text", ""))
                if line_text.strip() and not _ends_hooky(line_text):
                    err.append(f"line {idx+1} ({where}) must end with '?' or '...'/'…', or open with "
                               f"'But'/'Until'/'Except' — it's a re-hook, so it has to leave something "
                               f"unresolved instead of just finishing a thought")

        thumb = p.get("thumbnail")
        if not isinstance(thumb, dict):
            err.append("long video requires 'thumbnail' object")
        else:
            if len(str(thumb.get("text") or "").split()) > 3:
                err.append("thumbnail 'text' must be 0-3 words (none is fine for What If videos)")
            if not (thumb.get("search") or thumb.get("image")):
                err.append("thumbnail needs 'search' (character + emotion/event) or an exact 'image'")
            device = thumb.get("device")
            if device is not None and device not in VALID_THUMB_DEVICES:
                err.append(f"thumbnail 'device' must be one of {sorted(VALID_THUMB_DEVICES)} or omitted (got '{device}')")

        cards = [ln.get("card") for ln in lines if isinstance(ln, dict) and ln.get("card")]
        for c in cards:
            if not isinstance(c, str) or len(c) > 28:
                err.append(f"card '{c}' must be a string of at most 28 characters")
        per_min = len(cards) / max(1.0, total_words / 180)
        if per_min > 1.5:
            warn.append(f"{len(cards)} cards is a lot ({per_min:.1f} a minute); keep them for key names and numbers")

        # Open question or stakes within the first 3 lines: a long video has to earn the next 12 minutes fast.
        first3 = " ".join(str(ln.get("text", "")) for ln in lines[:3] if isinstance(ln, dict))
        if "?" not in first3:
            err.append("no '?' in the first 3 lines; open on the core question or stakes "
                       "(WRITER.md, cold open) so the viewer knows what's being decided")

        # The last line is the payoff, never a sign-off.
        if lines and isinstance(lines[-1], dict):
            last_text = str(lines[-1].get("text", ""))
            for name, pattern in OUTRO_PATTERNS:
                if re.search(pattern, last_text, re.IGNORECASE):
                    err.append(f"last line reads like an outro (contains '{name}'); end on the payoff line "
                               f"instead, then let the description/end screen point to the related video")
                    break

    # 7. notes/<id>.md check
    notes_candidates = [
        os.path.join(repo_dir, "notes", f"{script_id}.md"),
        os.path.join(os.getcwd(), "notes", f"{script_id}.md"),
        os.path.join("notes", f"{script_id}.md"),
    ]
    notes_path = next((path for path in notes_candidates if os.path.exists(path)), None)
    if not notes_path:
        err.append(f"notes/{script_id}.md not found")
    else:
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                notes_content = f.read()

            sources_match = re.search(r"^##\s*Sources\b(.*?)(?=^##|\Z)", notes_content, re.M | re.S | re.I)
            if not sources_match:
                err.append(f"notes/{script_id}.md missing '## Sources' section")
            else:
                sec_text = sources_match.group(1)
                urls = set(re.findall(r"https?://[^\s)\]>]+", sec_text))
                if len(urls) < 3:
                    err.append(f"notes/{script_id}.md '## Sources' must contain at least 3 URLs (found {len(urls)})")

            if not re.search(r"^##\s*Self-review\b", notes_content, re.M | re.I):
                err.append(f"notes/{script_id}.md missing '## Self-review' section")

            # Long videos and the Shorts cut from them (-Ls1, -Ls2, ...) must pass a fact-check subagent pass
            # (WRITER.md, Fact check step) before push; its findings and fixes are recorded here.
            needs_fact_check = fmt == "long" or bool(re.search(r"-Ls\d+$", script_id))
            if needs_fact_check and not re.search(r"^##\s*Fact check\b", notes_content, re.M | re.I):
                err.append(f"notes/{script_id}.md missing '## Fact check' section (required for long videos "
                           f"and their -Ls Shorts; run the fact-check subagent before pushing, see WRITER.md)")
        except Exception as e:
            err.append(f"failed reading notes/{script_id}.md: {e}")

    # 8. Duplicate title check
    canonical_self = os.path.realpath(os.path.abspath(script_path))
    curr_title = title.strip().lower()
    if curr_title:
        seen_paths = set()
        search_dirs = [repo_dir, os.getcwd(), "."]
        for base in search_dirs:
            for sub in ["queue", "done"]:
                for other_fp in glob.glob(os.path.join(base, "scripts", sub, "*.json")):
                    real_fp = os.path.realpath(os.path.abspath(other_fp))
                    if real_fp == canonical_self or real_fp in seen_paths:
                        continue
                    seen_paths.add(real_fp)
                    try:
                        with open(real_fp, "r", encoding="utf-8") as f:
                            other_data = json.load(f)
                        other_title = str(other_data.get("title", "")).strip().lower()
                        if other_title and other_title == curr_title:
                            err.append(f"duplicate title '{p.get('title')}' already exists in {os.path.basename(real_fp)}")
                            break
                    except Exception:
                        pass
            if any("duplicate title" in e for e in err):
                break

    # 9. Variety check (long only): opening on the same first 8 words as a recent long reads as a template.
    if fmt == "long" and lines and isinstance(lines[0], dict):
        curr_open = " ".join(str(lines[0].get("text", "")).split()[:8]).strip().lower()
        if curr_open:
            seen_paths = set()
            search_dirs = [repo_dir, os.getcwd(), "."]
            for base in search_dirs:
                for sub in ["queue", "done", "backlog"]:
                    for other_fp in glob.glob(os.path.join(base, "scripts", sub, "*.json")):
                        real_fp = os.path.realpath(os.path.abspath(other_fp))
                        if real_fp == canonical_self or real_fp in seen_paths:
                            continue
                        seen_paths.add(real_fp)
                        try:
                            with open(real_fp, "r", encoding="utf-8") as f:
                                other_data = json.load(f)
                            if other_data.get("format") != "long":
                                continue
                            other_lines = other_data.get("lines") or []
                            if not other_lines or not isinstance(other_lines[0], dict):
                                continue
                            other_open = " ".join(str(other_lines[0].get("text", "")).split()[:8]).strip().lower()
                            if other_open and other_open == curr_open:
                                err.append(f"line 1's first 8 words match {os.path.basename(real_fp)}'s line 1 "
                                           f"('{curr_open}'); open on a different archetype (WRITER.md)")
                                break
                        except Exception:
                            pass
                if any("line 1's first 8 words match" in e for e in err):
                    break

    # One-line summary first
    rate = 2.7 if fmt == "short" else 3.0      # long: speed 1.18 with tighter pauses, ~180 words a minute
    est_s = round(total_words / rate) if rate > 0 else 0
    print(f"{script_id} {fmt} {n_lines} lines, {total_words} words ~{est_s} s")

    for w in warn:
        print(f"WARN: {w}")

    if err:
        for e in err:
            print(f"ERROR: {e}")
        sys.exit(1)

    print("OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
