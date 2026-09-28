"""Validate a writer script before commit: python validate_script.py scripts/queue/<id>.json"""
import glob
import json
import os
import re
import sys

VALID_MOODS = {"hype", "suspense", "emotional", "epic", "chill"}
VALID_DELIVERY = {"normal", "punch", "reveal", "aside", "slow"}
VALID_FX = {"none", "zoom", "shake", "flash"}
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
    "long": {"min_lines": 90, "max_lines": 220, "min_words": 1600, "max_words": 2400},
}


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

        for name, pattern in BANNED_AI_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                err.append(f"line {i+1}: narration contains banned AI word/phrase '{name}'")

    # Format bounds
    if fmt in {"short", "long"}:
        limits = get_format_limits(channel_cfg, fmt)
        if not (limits["min_lines"] <= n_lines <= limits["max_lines"]):
            err.append(f"{fmt} lines count {n_lines} outside allowed range [{limits['min_lines']}, {limits['max_lines']}]")
        if not (limits["min_words"] <= total_words <= limits["max_words"]):
            err.append(f"{fmt} words count {total_words} outside allowed range [{limits['min_words']}, {limits['max_words']}]")

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
                if isinstance(ch_line, int):
                    prev_line = ch_line

        thumb = p.get("thumbnail")
        if not isinstance(thumb, dict):
            err.append("long video requires 'thumbnail' object")
        else:
            if not thumb.get("text") or not str(thumb.get("text")).strip():
                err.append("thumbnail missing 'text'")

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

    # One-line summary first
    rate = 2.7 if fmt == "short" else 2.5
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
