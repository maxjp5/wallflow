"""Settings, downloading, and Windows wallpaper plumbing."""
import copy
import ctypes
import hashlib
import io
import json
import os
import random
import re
import shutil
import sys
import time
import winreg

from PIL import Image

import sources

APP_NAME = "Wallflow"
VERSION = "1.0.0"
DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CACHE_DIR = os.path.join(DATA_DIR, "cache")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
FAVORITES_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "Wallflow Favorites")
PACKS_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "Wallflow Packs")
PACK_META = "wallflow-pack.json"
MAX_DOWNLOAD = 40 * 1024 * 1024

INTERVALS = {  # label -> minutes
    "5 minutes": 5, "15 minutes": 15, "30 minutes": 30, "1 hour": 60,
    "3 hours": 180, "6 hours": 360, "12 hours": 720, "24 hours": 1440,
}

DEFAULTS = {
    "running": True,
    "interval": "30 minutes",
    "style": "Fill",
    "sources": {
        "wallhaven": {"enabled": True, "query": "nature", "sort": "Toplist", "range": "Past month",
                      "collection": "", "anime": False, "api_key": ""},
        "unsplash": {"enabled": False, "mode": "Topic", "query": "wallpapers", "access_key": ""},
        "nasa": {"enabled": True, "query": ""},
        "picsum": {"enabled": True},
        "local": {"enabled": False, "folder": ""},
        "packs": {"enabled": False, "selected": []},
    },
    "start_with_windows": False,
    "close_to_tray": True,
    "keep_history": 40,
    "history": [],          # newest first: {path, source, title, page, time}
    "seen": [],             # URLs already shown
    "original": None,       # backup of user's wallpaper before Wallflow
}


# ---------------------------------------------------------------- settings

def load_settings():
    os.makedirs(CACHE_DIR, exist_ok=True)
    s = copy.deepcopy(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        for k, v in saved.items():
            if k == "sources":
                for sk, sv in v.items():
                    if sk in s["sources"]:
                        s["sources"][sk].update(sv)
            else:
                s[k] = v
    except (OSError, ValueError):
        pass
    s["history"] = [h for h in s["history"] if os.path.exists(h.get("path", ""))]
    return s


def save_settings(s):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)


# ---------------------------------------------------------------- windows

STYLES = {  # name -> (WallpaperStyle, TileWallpaper)
    "Fill": ("10", "0"), "Fit": ("6", "0"), "Stretch": ("2", "0"),
    "Center": ("0", "0"), "Tile": ("0", "1"), "Span": ("22", "0"),
}
DESKTOP_KEY = r"Control Panel\Desktop"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def screen_size():
    u = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    w, h = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    return (w, h) if w >= 640 else (1920, 1080)


def set_wallpaper(path, style="Fill"):
    ws, tile = STYLES.get(style, STYLES["Fill"])
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DESKTOP_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, ws)
        winreg.SetValueEx(k, "TileWallpaper", 0, winreg.REG_SZ, tile)
    # SPI_SETDESKWALLPAPER = 20, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE = 3
    if not ctypes.windll.user32.SystemParametersInfoW(20, 0, os.path.abspath(path), 3):
        raise ctypes.WinError()


def backup_original(settings):
    """Save a copy of the wallpaper the user had before Wallflow touched it (first run only)."""
    if settings.get("original"):
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DESKTOP_KEY) as k:
            current = winreg.QueryValueEx(k, "WallPaper")[0]
            style = winreg.QueryValueEx(k, "WallpaperStyle")[0]
            tile = winreg.QueryValueEx(k, "TileWallpaper")[0]
    except OSError:
        current, style, tile = "", "10", "0"
    src = current if current and os.path.isfile(current) else os.path.join(
        os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Themes", "TranscodedWallpaper")
    dest = ""
    if os.path.isfile(src):
        dest = os.path.join(DATA_DIR, "original_wallpaper" + (os.path.splitext(src)[1] or ".jpg"))
        shutil.copy2(src, dest)
    settings["original"] = {"path": dest, "style": style, "tile": tile}
    save_settings(settings)


def restore_original(settings):
    o = settings.get("original") or {}
    if not o.get("path") or not os.path.isfile(o["path"]):
        raise RuntimeError("No backup of your original wallpaper was found.")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DESKTOP_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, o.get("style", "10"))
        winreg.SetValueEx(k, "TileWallpaper", 0, winreg.REG_SZ, o.get("tile", "0"))
    ctypes.windll.user32.SystemParametersInfoW(20, 0, o["path"], 3)


def launch_command():
    if getattr(sys, "frozen", False):          # running as the packaged Wallflow.exe
        return f'"{sys.executable}" --minimized'
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Wallflow.pyw")
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return f'"{exe}" "{script}" --minimized'


def set_startup(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


def single_instance():
    """Return True if this is the only running copy."""
    ctypes.windll.kernel32.CreateMutexW(None, False, "Wallflow_SingleInstance_Mutex")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


# ---------------------------------------------------------------- fetching

def download_image(cand, dest_dir=CACHE_DIR, name=None):
    """Download/convert a candidate to a jpg in dest_dir and return its path.

    Local jpg/png/bmp files are used in place (no copy)."""
    if cand.local:
        if cand.url.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
            return cand.url
        with open(cand.url, "rb") as f:
            raw = f.read()
    else:
        req = sources.urllib.request.Request(cand.url, headers={"User-Agent": sources.UA})
        with sources.urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read(MAX_DOWNLOAD + 1)
        if len(raw) > MAX_DOWNLOAD:
            raise ValueError("image too large")
    img = Image.open(io.BytesIO(raw))
    img.load()
    w, h = img.size
    if not cand.local and (w < 1280 or w < h):
        raise ValueError(f"not wallpaper-shaped ({w}x{h})")
    if max(w, h) > 7680:
        img.thumbnail((7680, 7680))
    img = img.convert("RGB")
    name = name or hashlib.sha1(cand.url.encode()).hexdigest()[:16] + ".jpg"
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, name)
    img.save(path, "JPEG", quality=93)
    return path


def fetch_new(settings, screen, log=lambda m: None):
    """Pick an enabled source, get an unseen image, and return a history entry."""
    enabled = [k for k, v in settings["sources"].items() if v.get("enabled")]
    if not enabled:
        raise RuntimeError("Turn on at least one source.")
    random.shuffle(enabled)
    seen = set(settings["seen"])
    errors = []
    for key in enabled:
        label, fn = sources.SOURCES[key]
        log(f"Searching {label}…")
        try:
            cands = fn(settings["sources"][key], screen)
        except Exception as e:  # noqa: BLE001 - surface any source failure
            errors.append(f"{label}: {e}")
            continue
        fresh = [c for c in cands if c.url not in seen] or cands
        random.shuffle(fresh)
        for cand in fresh[:6]:
            try:
                log(f"Downloading from {label}…")
                path = download_image(cand)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{label}: {e}")
                continue
            settings["seen"] = (settings["seen"] + [cand.url])[-1500:]
            return {"path": path, "source": key, "title": cand.title,
                    "page": cand.page, "ping": cand.ping, "time": time.time()}
    raise RuntimeError("Couldn't get a wallpaper. " + (errors[-1] if errors else ""))


def ping_used(entry):
    """Tell Unsplash a photo was used (required by their API guidelines). Best effort."""
    if entry.get("ping"):
        try:
            sources.http_get(entry["ping"], timeout=10)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- packs

def safe_name(name):
    name = re.sub(r'[<>:"/\|?*]+', " ", name).strip(" .")
    return name[:60] or "Pack"


def read_pack_meta(folder):
    try:
        with open(os.path.join(folder, PACK_META), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def list_packs():
    """[(name, image_count)] for every folder in the packs directory."""
    if not os.path.isdir(PACKS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(PACKS_DIR), key=str.lower):
        folder = os.path.join(PACKS_DIR, name)
        if os.path.isdir(folder):
            out.append((name, len(sources.list_images(folder))))
    return out


def download_pack(name, source_key, cfg, screen, count, progress=lambda done, total, msg: None,
                  cancelled=lambda: False):
    """Download up to `count` new images from a source into a pack folder.

    Re-running with the same name tops the pack up with images it doesn't have yet."""
    folder = os.path.join(PACKS_DIR, safe_name(name))
    os.makedirs(folder, exist_ok=True)
    meta = read_pack_meta(folder)
    have = {v.get("url") for v in meta.values()}
    label, fn = sources.SOURCES[source_key]
    done, page, empty_pages = 0, 1, 0
    while done < count and page <= 40 and empty_pages < 3 and not cancelled():
        progress(done, count, f"Looking through {label}, page {page}…")
        try:
            cands = fn(cfg, screen, page=page)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"{label}: {e}") from e
        new = [c for c in cands if c.url not in have]
        empty_pages = empty_pages + 1 if not new else 0
        for cand in new:
            if done >= count or cancelled():
                break
            fname = f"{source_key}_{hashlib.sha1(cand.url.encode()).hexdigest()[:12]}.jpg"
            try:
                download_image(cand, folder, fname)
            except Exception:  # noqa: BLE001 - skip images that fail or aren't wallpaper-shaped
                have.add(cand.url)
                continue
            have.add(cand.url)
            meta[fname] = {"url": cand.url, "title": cand.title, "page": cand.page, "ping": cand.ping}
            done += 1
            progress(done, count, f"Downloaded {done} of {count}")
            if done % 5 == 0:
                _write_meta(folder, meta)
        page += 1
        time.sleep(1.2)          # stay well under Wallhaven's 45 requests/minute limit
    _write_meta(folder, meta)
    return os.path.basename(folder), done


def _write_meta(folder, meta):
    with open(os.path.join(folder, PACK_META), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)


def prune_cache(settings):
    keep = {os.path.normcase(h["path"]) for h in settings["history"]}
    for f in os.listdir(CACHE_DIR):
        p = os.path.join(CACHE_DIR, f)
        if os.path.normcase(p) not in keep:
            try:
                os.remove(p)
            except OSError:
                pass


def save_favorite(entry):
    os.makedirs(FAVORITES_DIR, exist_ok=True)
    name = f"{entry['source']}_{os.path.basename(entry['path'])}"
    dest = os.path.join(FAVORITES_DIR, name)
    shutil.copy2(entry["path"], dest)
    return dest
