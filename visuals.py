"""Real anime visuals: screenshots and manga panels from the series' fandom wiki (MediaWiki API),
with an AI image (images.py) only as the last resort.

The writer uses the CLI to pick exact files:
  python visuals.py search onepiece.fandom.com "Zoro Mihawk"
  python visuals.py check onepiece.fandom.com "File:Zoro Fights Mihawk.png"
"""
import argparse, io, os, re, time
import requests
from PIL import Image


UA = {"User-Agent": "lorevid/1.0 (+https://github.com/adityamittal-dot/lorevid)"}
BAD = re.compile(r"logo|icon|merch|bloks|figure|diorama|toy|card|sticker|funko|statue|dub\b|volume cover|poster|"
                 r"cosplay|live action|game|\.gif$|\.svg$|"
                 # video games, figure lines and promo renders that the wiki keeps next to real screenshots
                 r"burning blood|look up|dxf|dxglc|grandista|banpresto|figuarts|ichiban|pirate warriors|bounty rush|"
                 r"treasure cruise|thousand storm|unlimited world|world seeker|ultimate ninja|ninja storm|blazing|"
                 r"cursed clash|phantom parade|-share|\bplush|\bpvc\b|keychain|t-shirt|\bshirt\b|hungry days|"
                 r"unlimited adventure|unlimited cruise|grand adventure|gear spirit|grand battle|pirate's carnival|"
                 r"kaizoku musou|memorial museum|\bcollab|onepi no mi|collection|pop!|& tee|\btee\b|"
                 r"merchandise|\bmug\b|\bcake\b|\bcafe\b|restaurant|\bstore\b|\bshop\b|\bpromo", re.I)
EXTS = (".png", ".jpg", ".jpeg", ".webp")
ANIME_STYLE = ("anime key visual, cel shaded, dramatic lighting, detailed background, cinematic composition, "
               "no text, no watermark")


def _api(wiki, **params):
    url = f"https://{wiki.split('://')[-1].strip('/')}/api.php"
    for attempt in range(3):
        try:
            r = requests.get(url, params={"format": "json", **params}, headers=UA, timeout=60)
            time.sleep(0.3)                                  # be polite to the wiki
            if r.ok:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1.5 * (attempt + 1))
    return {}


def _title(t):
    t = t.strip().replace("_", " ")
    return t if t.startswith(("File:", "Image:")) else "File:" + t


def info(wiki, titles):
    """{title: {"url", "width", "height"}} for up to 30 file titles."""
    pages = _api(wiki, action="query", prop="imageinfo", iiprop="url|size",
                 titles="|".join(titles[:30])).get("query", {}).get("pages", {})
    return {p["title"]: p["imageinfo"][0] for p in pages.values() if p.get("imageinfo")}


def search(wiki, words, limit=30):
    hits = _api(wiki, action="query", list="search", srnamespace=6, srsearch=words,
                srlimit=min(limit, 50)).get("query", {}).get("search", [])
    return [h["title"] for h in hits]


MERCH = re.compile(r"^(File:|Image:)?[^ ]+-[^ ]+\.\w+$")    # "DXGLM9-Zoro.png", "POPSailingAgain-Zoro.png": product shots


def acceptable(title, i):
    return (title.lower().endswith(EXTS) and not BAD.search(title) and not MERCH.match(title)
            and i.get("width", 0) >= 400 and i.get("height", 0) >= 400)


def _download(url, out):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.ok:
                im = Image.open(io.BytesIO(r.content))
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA")
                    bg = Image.new("RGB", im.size)
                    bg.paste(im, mask=im.split()[3])
                    im = bg
                im.convert("RGB").save(out, "JPEG", quality=92)
                if os.path.getsize(out) > 5000:
                    return True
        except Exception as e:
            print(f"  download failed ({e})", flush=True)
        time.sleep(1.5 * (attempt + 1))
    return False


def page_images(wiki, page):
    """{file title: imageinfo} for every acceptable image used on a wiki article (fight, arc, character pages)."""
    out, cont = {}, {}
    for _ in range(4):
        r = _api(wiki, action="query", titles=page, generator="images", gimlimit=200, prop="imageinfo",
                 iiprop="url|size", redirects=1, **cont)
        for p in r.get("query", {}).get("pages", {}).values():
            if p.get("imageinfo") and acceptable(p["title"], p["imageinfo"][0]):
                out[p["title"]] = p["imageinfo"][0]
        cont = r.get("continue", {})
        if not cont:
            break
    return out


def script_pages(script):
    """Wiki articles the Short is about: the writer's "pages", plus every source URL on the same wiki."""
    from urllib.parse import unquote, urlparse
    wiki = script.get("wiki", "")
    pages = list(script.get("pages") or [])
    for u in script.get("sources", []):
        p = urlparse(u)
        if wiki and p.netloc.endswith(wiki) and p.path.startswith("/wiki/"):
            pages.append(unquote(p.path[6:]).replace("_", " "))
    return list(dict.fromkeys(t for t in pages if t and not t.startswith(("Special:", "Category:"))))


STOP = set("""a an and are as at be but by for from had has have he her his i if in into is it its just me my no not
of on or our over she so than that the their them then there these they this to up was we were what when which who why
will with you your file png jpg jpeg webp anime manga image picture vs""".split())
DULL = re.compile(r"infobox|portrait|concept art|color scheme|colour scheme|outfit|jolly roger|symbol|sbs|"
                  r"\bchapter \d+\.|\bepisode \d+\.|wanted poster|eyecatcher|\bmap\b|signature|avatar|title card", re.I)


def _tokens(s):
    words = re.findall(r"[a-z0-9]+", s.lower().replace("'s ", " ").replace("’s ", " "))
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words if w not in STOP and len(w) > 1}


def rank(wiki, shot, text, pool):
    """Wiki files for one narration line, best first, as [(score, title, imageinfo, strong)].
    Score = words shared with the shot's search words (x3) and with the spoken line (x1); the wiki's own
    search hits and images on the Short's own wiki articles get a bonus; infoboxes, portraits and concept art
    (static, seen everywhere) lose points. strong = shares 2+ words with the line, or 1 and sits on those articles."""
    want, said = _tokens(shot.get("search", "")), _tokens(text)
    first = re.findall(r"[a-z0-9]+", shot.get("search", "").lower())
    subject = {first[0][:-1] if len(first[0]) > 4 and first[0].endswith("s") else first[0]} - STOP if first else set()
    cands = dict(pool)
    hits = {}
    if wiki and shot.get("search"):
        titles = search(wiki, shot["search"])
        infos = info(wiki, titles)
        for n, t in enumerate(titles):
            if t in infos and acceptable(t, infos[t]):
                cands[t] = infos[t]
                hits[t] = max(1.0, 3.0 - n * 0.1)
    out = []
    for t, i in cands.items():
        name = _tokens(t.rsplit(".", 1)[0])
        matched = len((want | said) & name)
        s = 3 * len(want & name) + len(said & name) + hits.get(t, 0) + (1 if t in pool else 0)
        if DULL.search(t):
            s -= 2
        if "-" in t or len(name) <= 1:                   # "Becoming a Hero - Zoro": songs/products; "Sukuna.png": a bare render
            s -= 1.5
        if subject and not subject & name:               # search starts with its subject: "Zoro ..." must show Zoro,
            s -= 3                                       # not "Douglas Bullet Using Supreme King Haki"
            matched = min(matched, 1)
        if s > 0:
            out.append((s, t, i, matched >= 2 or (t in pool and matched >= 1)))
    out.sort(key=lambda x: -x[0])
    return out


class Picks(dict):
    """{file title: times used} that also remembers pick order, for the render log."""
    def __init__(self):
        super().__init__()
        self.order = []

    def __setitem__(self, k, v):
        self.order.append(k)
        super().__setitem__(k, v)


def pick(shot, text, wiki, pool, used, n, out_paths):
    """Fill out_paths[:n] with distinct images for one line's beats. Returns the paths actually filled.
    Beat 1: the writer's exact file, else the best-ranked wiki file. Later beats need a real match (a search word
    in the file name), so a line only cuts to a new picture when that picture is about the line."""
    got, mine = [], set()
    if wiki and shot.get("image"):
        t = _title(shot["image"])
        i = info(wiki, [t]).get(t)
        if i and i.get("width", 0) >= 300 and _download(i["url"], out_paths[0]):
            used[t] = used.get(t, 0) + 1
            got.append(out_paths[0])
            mine.add(t)
    ranked = rank(wiki, shot, text, pool) if wiki else []
    best = ranked[0][0] if ranked else 0
    # unused first, then pictures used once; a file never appears more than twice in a Short
    order = [r for r in ranked if not used.get(r[1])] + [r for r in ranked if used.get(r[1]) == 1]
    if not got and order and not order[0][3]:          # weak best match (a bare "Zoro" search): an on-topic article
        strong = [r for r in order if r[3]]            # image, even one shown before, beats a random file
        order = strong[:1] + order if strong else order
    for s, t, i, strong in order:
        if len(got) >= n:
            break
        if t in mine or (got and not strong):         # extra cuts only for pictures that are clearly about the line
            continue
        if got and s < max(3, best * 0.35):
            break
        if _download(i["url"], out_paths[len(got)]):
            used[t] = used.get(t, 0) + 1
            got.append(out_paths[len(got)])
            mine.add(t)
            pool.setdefault(t, i)                      # what this Short already showed is on-topic for later lines
    return got


def pick_hook(shot, text, wiki, pool, used, out_path, tries=4):
    """First picture of a Short: among the best-matching files, the most colourful close-up (framing.hook_score).
    Top theory Shorts open on a vivid face, not on a grey crowd shot."""
    import framing
    ranked = rank(wiki, shot, text, pool) if wiki else []
    if not ranked:
        return None
    best, scored = ranked[0][0], []
    for s, t, i, _ in [r for r in ranked if r[0] >= ranked[0][0] * 0.6][:tries]:
        tmp = f"{out_path}.cand{len(scored)}.jpg"
        if _download(i["url"], tmp):
            try:
                with Image.open(tmp) as im:
                    scored.append((framing.hook_score(im) * (0.8 + 0.2 * s / best), t, tmp))
            except Exception:
                pass
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    _, t, tmp = scored[0]
    os.replace(tmp, out_path)
    for _, _, other in scored[1:]:
        try:
            os.remove(other)
        except OSError:
            pass
    used[t] = used.get(t, 0) + 1
    return t


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("wiki"); s.add_argument("words"); s.add_argument("-n", type=int, default=15)
    c = sub.add_parser("check"); c.add_argument("wiki"); c.add_argument("title")
    a = ap.parse_args()
    if a.cmd == "search":
        titles = search(a.wiki, a.words)
        infos = info(a.wiki, titles)
        good = [t for t in titles if t in infos and acceptable(t, infos[t])]
        for t in good[:a.n]:
            print(f"{t}  {infos[t]['width']}x{infos[t]['height']}")
        if not good:
            print("no usable images; try other words (character name + event, e.g. 'Luffy Gear 5')")
    else:
        t = _title(a.title)
        i = info(a.wiki, [t]).get(t)
        print(f"OK {i['width']}x{i['height']}" if i else "MISSING")
