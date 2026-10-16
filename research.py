"""Wiki research packs for writers whose sandbox can't reach the fandom wikis.

  python research.py <wiki> <Page> [<Page> ...]   fetch pages into data/wiki/<series>/<Page>.md
  python research.py packs                        fetch every page in channel.json "research_pages"

Each pack is the page's prose with its citations kept inline as [Ch. 906, Ep. 885], so a writer can quote verified
chapter and episode numbers without opening the wiki. Galleries, navboxes, trivia tables and other templates are
dropped. Runs on a laptop or in GitHub Actions (both can reach fandom); pure stdlib.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(REPO_DIR, "data", "wiki")
MAX_CHARS = 60000          # long pages (Luffy, Imu) are cut here; the history sections come first
SKIP_SECTIONS = re.compile(r"^(gallery|trivia|references|notes|site navigation|external links|merchandise|"
                           r"video games?|translation and dub issues|other appearances|anime and manga differences)$", re.I)
WIKIS = {"onepiece": "onepiece.fandom.com", "naruto": "naruto.fandom.com", "jjk": "jujutsu-kaisen.fandom.com"}
CITE_KEYS = {"chap": "Ch.", "chapter": "Ch.", "ep": "Ep.", "episode": "Ep.", "vol": "Vol."}


def fetch_wikitext(wiki, page):
    q = urllib.parse.urlencode({"action": "parse", "page": page, "prop": "wikitext", "format": "json",
                                "formatversion": 2, "redirects": 1})
    req = urllib.request.Request(f"https://{wiki}/api.php?{q}", headers={"User-Agent": "lorevid-research/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if "error" in data:
        raise RuntimeError(data["error"].get("info", "unknown error"))
    return data["parse"]["title"], data["parse"]["wikitext"]


def _citation(params):
    """'[Ch. 906, Ep. 885]' from a citation template's params, or '' when it has no chapter/episode."""
    parts = []
    for p in params:
        k, _, v = p.partition("=")
        k, v = k.strip().lower(), v.strip()
        if k in CITE_KEYS and v:
            parts.append(f"{CITE_KEYS[k]} {v}")
    return f" [{', '.join(parts)}]" if parts else ""


def _templates(text):
    """Replace innermost {{...}} templates until none are left: citations become [Ch. N], {{Nihongo|English|..}}
    keeps its English, everything else is dropped."""
    pat = re.compile(r"\{\{([^{}]*)\}\}")
    while True:
        def sub(m):
            parts = m.group(1).split("|")
            name = parts[0].strip().lower()
            if "ref" in name or name.startswith("cite"):
                return _citation(parts[1:])
            if name in ("nihongo", "w", "wp") and len(parts) > 1:
                return parts[1].strip()
            return ""
        new = pat.sub(sub, text)
        if new == text:
            return new
        text = new


def _ref(body):
    """A <ref> body as an inline citation: template refs ({{Qref|chap=906}}) or free-text ones
    ("''Naruto'' chapter 590, page 12", "''Naruto: Shippūden'' episode 454"); anything else is dropped."""
    if "{{" in body:
        return _templates(body)
    plain = re.sub(r"'{2,}", "", body)
    hits = [f"{m.group(1).strip()} {m.group(2).capitalize()[:2]}. {m.group(3)}"
            for m in re.finditer(r"([A-Z][\w:ūō' -]{0,40}?)\s*(chapter|episode)s?\s+(\d+)", plain, re.I)]
    return f" [{'; '.join(hits)}]" if hits else ""


def to_markdown(wikitext):
    t = re.sub(r"<!--.*?-->", "", wikitext, flags=re.S)
    t = re.sub(r"<ref[^>/]*/>", "", t)
    # <ref>{{Qref|chap=1}}</ref>: keep only the citation inside
    t = re.sub(r"<ref[^>]*>(.*?)</ref>", lambda m: _ref(m.group(1)), t, flags=re.S)
    t = _templates(t)
    t = re.sub(r"\{\|.*?\|\}", "", t, flags=re.S)                       # wiki tables
    t = re.sub(r"\[\[(?:File|Image|Category|[a-z]{2}(?:-[a-z]+)?):[^\]]*\]\]", "", t)
    t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", t)            # [[Page|text]] -> text
    t = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", t)
    t = re.sub(r"'{2,}", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    out, skipping = [], False
    for line in t.splitlines():
        m = re.match(r"^(=+)\s*(.*?)\s*=+\s*$", line)
        if m:
            skipping = bool(SKIP_SECTIONS.match(m.group(2)))
            if not skipping:
                out.append(f"\n{'#' * min(len(m.group(1)) + 1, 5)} {m.group(2)}")
            continue
        line = line.strip()
        if skipping or not line or line.startswith(("|", "!", "{", "}")):
            continue
        out.append(line)
    md = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return md[:MAX_CHARS]


def save_pack(wiki, series, page):
    title, wt = fetch_wikitext(wiki, page)
    md = to_markdown(wt)
    n_cites = len(re.findall(r"\b(?:Ch|Ep)\. \d", md))
    path = os.path.join(OUT_DIR, series, re.sub(r"[^\w.-]+", "_", title) + ".md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\nSource: https://{wiki}/wiki/{urllib.parse.quote(title.replace(' ', '_'))} "
                f"(fetched {time.strftime('%Y-%m-%d')}). Bracketed [Ch. N] / [Ep. N] are the wiki's own citations.\n\n"
                f"{md}\n")
    return path, len(md), n_cites


def main():
    args = sys.argv[1:]
    with open(os.path.join(REPO_DIR, "channel.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    wiki_of = dict(WIKIS, **{s["id"]: s["wiki"] for s in cfg.get("series", []) if isinstance(s, dict) and s.get("wiki")})
    if args[:1] == ["packs"]:
        jobs = [(series, page) for series, pages in cfg.get("research_pages", {}).items() for page in pages]
    elif len(args) >= 2:
        series = next((k for k, w in wiki_of.items() if w == args[0] or k == args[0]), args[0])
        jobs = [(series, p) for p in args[1:]]
    else:
        print(__doc__)
        sys.exit(1)
    failed = 0
    for series, page in jobs:
        wiki = wiki_of.get(series, series)
        try:
            path, size, cites = save_pack(wiki, series, page)
            print(f"{os.path.relpath(path, REPO_DIR)}: {size} chars, {cites} chapter/episode citations")
        except Exception as e:
            failed += 1
            print(f"FAILED {series}/{page}: {e}")
        time.sleep(0.3)
    if args[:1] == ["packs"]:
        write_index()
    sys.exit(1 if failed == len(jobs) else 0)


def write_index():
    """data/wiki/INDEX.md: every pack with its size and citation count, so a writer picks pages in one read."""
    rows = []
    for series in sorted(os.listdir(OUT_DIR)):
        d = os.path.join(OUT_DIR, series)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            with open(os.path.join(d, name), encoding="utf-8") as f:
                text = f.read()
            cites = len(re.findall(r"\b(?:Ch|Ep)\. \d", text))
            rows.append(f"| {series} | `data/wiki/{series}/{name}` | {len(text) // 1000}k | {cites} |")
    with open(os.path.join(OUT_DIR, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# Wiki research packs\n\nRefreshed daily by the insights workflow (`python research.py packs`). "
                "Add pages to channel.json `research_pages`.\n\n| Series | File | Size | Citations |\n|---|---|---|---|\n"
                + "\n".join(rows) + "\n")


if __name__ == "__main__":
    main()
