"""Wallpaper sources. Each source returns a list of Candidate images.

Every source function has the signature fn(cfg, screen, page=None):
  cfg    - that source's settings dict
  screen - (width, height) of the monitor
  page   - results page to fetch (1, 2, 3…), or None for "surprise me"
"""
import json
import os
import random
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

UA = "Wallflow/1.0 (desktop wallpaper changer)"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


@dataclass
class Candidate:
    url: str          # http(s) URL or local file path
    source: str       # source key, e.g. "wallhaven"
    title: str = ""
    page: str = ""    # web page to open for credit / details
    local: bool = False
    ping: str = ""    # URL to call when the image is used (Unsplash download tracking)


class SourceError(Exception):
    pass


def http_get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_json(url, headers=None):
    return json.loads(http_get(url, headers).decode("utf-8"))


# ---------------------------------------------------------------- Wallhaven

WALLHAVEN_SORTS = {  # label -> API sorting value
    "Random": "random", "Toplist": "toplist", "Hot": "hot",
    "Most viewed": "views", "Most favorited": "favorites", "Latest": "date_added",
}
WALLHAVEN_RANGES = {  # label -> topRange
    "Past day": "1d", "Past 3 days": "3d", "Past week": "1w", "Past month": "1M",
    "Past 3 months": "3M", "Past 6 months": "6M", "Past year": "1y",
}


def _wallhaven_items(data, w_min):
    out = []
    for item in data.get("data", []):
        if item.get("purity", "sfw") != "sfw":
            continue
        if item.get("dimension_x", w_min) < w_min or item.get("dimension_x", 1) < item.get("dimension_y", 0):
            continue
        out.append(Candidate(item["path"], "wallhaven",
                             f"Wallhaven #{item.get('id', '')} · {item.get('resolution', '')} · "
                             f"♥ {item.get('favorites', 0)}",
                             item.get("url", "")))
    return out


WALLHAVEN_RATIOS = {"16x9": 16 / 9, "16x10": 1.6, "21x9": 64 / 27, "32x9": 32 / 9, "48x9": 48 / 9,
                    "4x3": 4 / 3, "5x4": 1.25, "3x2": 1.5}


def nearest_ratio(w, h):
    import math
    r = w / h
    return min(WALLHAVEN_RATIOS, key=lambda k: abs(math.log(WALLHAVEN_RATIOS[k] / r)))


def wallhaven(cfg, screen, page=None):
    match = cfg.get("_match")
    w, h = (screen if match else (min(screen[0], 1920), min(screen[1], 1080)))
    key = cfg.get("api_key", "").strip()
    sort = WALLHAVEN_SORTS.get(cfg.get("sort", "Random"), "random")

    link = cfg.get("collection", "").strip()
    if link:
        m = re.search(r"user/([^/]+)/favorites/(\d+)", link)
        if not m:
            raise SourceError("Collection link should look like wallhaven.cc/user/NAME/favorites/123")
        params = {"page": page or random.randint(1, 3)}
        if key:
            params["apikey"] = key
        data = get_json(f"https://wallhaven.cc/api/v1/collections/{m.group(1)}/{m.group(2)}?"
                        + urllib.parse.urlencode(params))
        if not data.get("data") and page is None and params["page"] > 1:
            return wallhaven(cfg, screen, page=1)        # small collection: go back to page 1
        return _wallhaven_items(data, 1280)

    params = {
        "q": cfg.get("query", "").strip(),
        "categories": "1" + ("1" if cfg.get("anime") else "0") + "0",   # general / anime / people
        "purity": "100",                                                # SFW only
        "sorting": sort,
        "atleast": f"{w}x{h}",
        "ratios": nearest_ratio(w, h) if match else "landscape",
        "page": page or (1 if sort == "random" else random.randint(1, 3)),
    }
    if sort == "toplist":
        params["topRange"] = WALLHAVEN_RANGES.get(cfg.get("range", "Past month"), "1M")
    if cfg.get("_dark"):
        params["colors"] = "000000"          # Wallhaven color filter: images with lots of black
    if key:
        params["apikey"] = key
    data = get_json("https://wallhaven.cc/api/v1/search?" + urllib.parse.urlencode(params))
    if not data.get("data") and page is None and params["page"] > 1:
        return wallhaven(cfg, screen, page=1)
    if not data.get("data") and cfg.get("_dark"):          # too narrow with the color filter: drop it
        return wallhaven({**cfg, "_dark": False}, screen, page)
    return _wallhaven_items(data, 1280)


def wallhaven_count(cfg, screen):
    """How many Wallhaven results match these settings (for the Settings page)."""
    match = cfg.get("_match")
    w, h = screen
    params = {"q": cfg.get("query", "").strip(), "categories": "1" + ("1" if cfg.get("anime") else "0") + "0",
              "purity": "100", "atleast": f"{w}x{h}", "ratios": nearest_ratio(w, h) if match else "landscape"}
    return get_json("https://wallhaven.cc/api/v1/search?" + urllib.parse.urlencode(params)).get(
        "meta", {}).get("total", 0)


# ---------------------------------------------------------------- Unsplash

UNSPLASH_MODES = ["Topic", "Search", "Collection", "Random"]


def unsplash(cfg, screen, page=None):
    key = cfg.get("access_key", "").strip()
    if not key:
        raise SourceError("Unsplash needs a free Access Key (unsplash.com/developers)")
    mode = cfg.get("mode", "Topic")
    text = cfg.get("query", "").strip()
    pg = page or random.randint(1, 3)
    base = {"orientation": "landscape", "per_page": 30, "page": pg}

    if mode == "Search":
        if not text:
            raise SourceError("Type something to search Unsplash for")
        url = "https://api.unsplash.com/search/photos?" + urllib.parse.urlencode(
            {**base, "query": text, "order_by": "relevant", "content_filter": "high"})
    elif mode == "Collection":
        m = re.search(r"collections/([A-Za-z0-9_-]+)", text) or re.fullmatch(r"([A-Za-z0-9_-]+)", text)
        if not m:
            raise SourceError("Paste an Unsplash collection link, e.g. unsplash.com/collections/1065976/…")
        base.pop("orientation")      # collections endpoint ignores it; filtered on download
        url = f"https://api.unsplash.com/collections/{m.group(1)}/photos?" + urllib.parse.urlencode(base)
    elif mode == "Random":
        params = {"orientation": "landscape", "count": 30, "content_filter": "high"}
        if text:
            params["query"] = text
        url = "https://api.unsplash.com/photos/random?" + urllib.parse.urlencode(params)
    else:  # Topic
        m = re.search(r"/t/([A-Za-z0-9_-]+)", text)
        slug = m.group(1) if m else (text.lower().replace(" ", "-") or "wallpapers")
        url = f"https://api.unsplash.com/topics/{slug}/photos?" + urllib.parse.urlencode(
            {**base, "order_by": "popular"})

    data = get_json(url, {"Authorization": f"Client-ID {key}", "Accept-Version": "v1"})
    items = data.get("results", data) if isinstance(data, dict) else data
    if not items and page is None and pg > 1:
        return unsplash(cfg, screen, page=1)

    out = []
    for item in items:
        if item.get("width", 1) < item.get("height", 0):
            continue
        raw = item["urls"]["raw"]
        who = item.get("user", {}).get("name", "unknown")
        desc = (item.get("alt_description") or item.get("description") or "Unsplash photo").capitalize()
        ping = item.get("links", {}).get("download_location", "")
        if ping:
            ping += ("&" if "?" in ping else "?") + "client_id=" + key
        size = (f"&w={screen[0]}&h={screen[1]}&fit=crop&crop=entropy" if cfg.get("_match")
                else f"&w={screen[0]}&fit=max")
        out.append(Candidate(f"{raw}{size}&q=90&fm=jpg", "unsplash",
                             f"{desc[:90]}, by {who}", item.get("links", {}).get("html", ""),
                             ping=ping))
    return out


# ---------------------------------------------------------------- others

def nasa(cfg, screen, page=None):
    q = cfg.get("query", "").strip() or random.choice(
        ["nebula", "galaxy", "earth from space", "hubble", "webb telescope", "aurora", "planet"])
    data = get_json("https://images-api.nasa.gov/search?" + urllib.parse.urlencode(
        {"q": q, "media_type": "image", "page": page or random.randint(1, 3)}))
    out = []
    for item in data.get("collection", {}).get("items", []):
        try:
            meta = item["data"][0]
            thumb = item["links"][0]["href"]
        except (KeyError, IndexError):
            continue
        nid = meta.get("nasa_id", "")
        base = thumb.rsplit("~", 1)[0]
        out.append(Candidate(base + "~orig.jpg", "nasa", meta.get("title", "NASA image")[:120],
                             f"https://images.nasa.gov/details/{urllib.parse.quote(nid)}"))
    return out


def picsum(cfg, screen, page=None):
    w, h = screen
    if w > 5000:                      # Picsum's size limit; the image is scaled to fit afterwards
        w, h = 5000, round(h * 5000 / w)
    out = []
    for _ in range(6 if page else 1):
        seed = random.randint(1, 10_000_000)
        out.append(Candidate(f"https://picsum.photos/seed/{seed}/{w}/{h}", "picsum",
                             "Random photo from Lorem Picsum", "https://picsum.photos"))
    return out


def list_images(folder):
    out = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(IMAGE_EXTS):
                out.append(os.path.join(root, f))
    return out


def local(cfg, screen, page=None):
    folder = cfg.get("folder", "").strip()
    if not folder or not os.path.isdir(folder):
        raise SourceError("Pick a folder of images first")
    out = [Candidate(p, "local", os.path.basename(p), p, local=True) for p in list_images(folder)]
    if not out:
        raise SourceError("No images found in that folder")
    return out


def packs(cfg, screen, page=None):
    import core  # local import to avoid a cycle
    chosen = cfg.get("selected", [])
    if not chosen:
        raise SourceError("Tick at least one pack to rotate through")
    out = []
    for name in chosen:
        folder = os.path.join(core.PACKS_DIR, name)
        meta = core.read_pack_meta(folder)
        for p in list_images(folder):
            info = meta.get(os.path.basename(p), {})
            out.append(Candidate(p, "packs", info.get("title") or f"{name} · {os.path.basename(p)}",
                                 info.get("page") or p, local=True, ping=info.get("ping", "")))
    if not out:
        raise SourceError("Your ticked packs are empty")
    return out


def favorites(cfg, screen, page=None):
    import core  # local import to avoid a cycle
    out = [Candidate(e["path"], "favorites", e["title"], e["page"], local=True) for e in core.list_favorites()]
    if not out:
        raise SourceError("You haven't saved any favorites yet")
    return out


SOURCES = {  # key -> (label, function)
    "wallhaven": ("Wallhaven", wallhaven),
    "unsplash": ("Unsplash", unsplash),
    "nasa": ("NASA Space Photos", nasa),
    "picsum": ("Picsum (random photos)", picsum),
    "local": ("My Folder", local),
    "packs": ("My Packs (offline)", packs),
    "favorites": ("My Favorites", favorites),
}
PACK_SOURCES = ["wallhaven", "unsplash", "nasa"]   # sources you can download a pack from
