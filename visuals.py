"""Real anime visuals: screenshots and manga panels from the series' fandom wiki (MediaWiki API),
with an AI image (images.py) only as the last resort.

The writer uses the CLI to pick exact files:
  python visuals.py search onepiece.fandom.com "Zoro Mihawk"
  python visuals.py check onepiece.fandom.com "File:Zoro Fights Mihawk.png"
"""
import argparse, io, os, re, time
import requests
from PIL import Image

import images

UA = {"User-Agent": "lorevid/1.0 (+https://github.com/adityamittal-dot/lorevid)"}
BAD = re.compile(r"logo|icon|merch|bloks|figure|diorama|toy|card|sticker|funko|statue|dub\b|volume cover|poster|"
                 r"cosplay|live action|game|\.gif$|\.svg$", re.I)
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


def acceptable(title, i):
    return (title.lower().endswith(EXTS) and not BAD.search(title)
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


def get(shot, wiki, out_path, used, seed, vertical):
    """Fill out_path with the shot's image. Returns {"path", "source", "file"} or None (caller reuses the last image).
    Order: the writer's exact file -> wiki search (unused images first) -> AI fallback."""
    if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
        return {"path": out_path, "source": "cache", "file": ""}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if wiki and shot.get("image"):
        t = _title(shot["image"])
        i = info(wiki, [t]).get(t)
        if i and i.get("width", 0) >= 300 and _download(i["url"], out_path):      # the writer chose it: trust it
            used.add(t)
            return {"path": out_path, "source": "wiki", "file": t}
        print(f"  wiki file not usable: {t}", flush=True)
    if wiki and shot.get("search"):
        titles = search(wiki, shot["search"])
        infos = info(wiki, titles)
        ok = [t for t in titles if t in infos and acceptable(t, infos[t])]
        for t in [t for t in ok if t not in used] + [t for t in ok if t in used]:
            if _download(infos[t]["url"], out_path):
                used.add(t)
                return {"path": out_path, "source": "wiki", "file": t}
    if shot.get("fallback"):
        w, h = (768, 1344) if vertical else (1344, 768)
        try:
            images.generate(f"{shot['fallback']}, {ANIME_STYLE}", out_path, seed, w, h)
            return {"path": out_path, "source": "ai", "file": ""}
        except Exception as e:
            print(f"  AI fallback failed ({e})", flush=True)
    return None


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
