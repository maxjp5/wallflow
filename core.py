"""Settings, downloading, and Windows wallpaper plumbing."""
import copy
import ctypes
import ctypes.wintypes
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

from PIL import Image, ImageOps

import sources

APP_NAME = "Wallflow"
VERSION = "1.2.2"
DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CACHE_DIR = os.path.join(DATA_DIR, "cache")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
FAVORITES_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "Wallflow Favorites")
PACKS_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "Wallflow Packs")
PACK_META = "wallflow-pack.json"
MAX_DOWNLOAD = 40 * 1024 * 1024

NO_ROTATE = "Don't rotate"
INTERVALS = {  # label -> minutes
    "5 minutes": 5, "15 minutes": 15, "30 minutes": 30, "1 hour": 60,
    "3 hours": 180, "6 hours": 360, "12 hours": 720, "24 hours": 1440,
    NO_ROTATE: 0,               # keep the current wallpaper until you press Next
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
        "favorites": {"enabled": False},
    },
    "start_with_windows": False,
    "start_hidden": True,       # when started by Windows, stay in the tray
    "change_on_start": False,   # new wallpaper every time Wallflow starts
    "close_to_tray": True,
    "theme": "Dark",
    "accent": "White",
    "mica": True,
    "smooth_transition": True,  # cross-fade the desktop when the wallpaper changes
    "pause_on_battery": False,
    "pause_fullscreen": True,   # don't change while a game / full-screen app / presentation is up
    "check_updates": True,
    "match_screens": True,      # only pick wallpapers that fit your monitors, cropped to exact size
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


def _dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # real pixels, not scaled ones
    except Exception:
        pass


def screen_size():
    _dpi_aware()
    u = ctypes.windll.user32
    w, h = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    return (w, h) if w >= 640 else (1920, 1080)


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT), ("dwFlags", ctypes.c_ulong)]


def monitors():
    """Every connected monitor as {x, y, w, h, primary}, primary first."""
    _dpi_aware()
    out = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_void_p)

    def found(hmon, _hdc, _rect, _data):
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(_MonitorInfo)
        if ctypes.windll.user32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(info)):
            r = info.rcMonitor
            out.append({"x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top,
                        "primary": bool(info.dwFlags & 1)})
        return 1

    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, proc(found), None)
    except OSError:
        pass
    if not out:
        w, h = screen_size()
        out = [{"x": 0, "y": 0, "w": w, "h": h, "primary": True}]
    out.sort(key=lambda m: (not m["primary"], m["x"], m["y"]))
    return out


def target_size(settings, mons=None):
    """The exact wallpaper size that fits your screens.

    Span: one image across the whole desktop. Otherwise: your main screen's shape,
    big enough for your largest landscape screen."""
    mons = mons or monitors()
    if settings.get("style") == "Span" and len(mons) > 1:
        left = min(m["x"] for m in mons)
        top = min(m["y"] for m in mons)
        right = max(m["x"] + m["w"] for m in mons)
        bottom = max(m["y"] + m["h"] for m in mons)
        return right - left, bottom - top
    p = mons[0]
    scale = max([1.0] + [max(m["w"] / p["w"], m["h"] / p["h"]) for m in mons if m["w"] >= m["h"]])
    return round(p["w"] * scale), round(p["h"] * scale)


def wallpaper_size(settings):
    """Size to request from sources: exact fit when matching screens, else main screen."""
    return target_size(settings) if settings.get("match_screens", True) else screen_size()


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(self))


# IDesktopWallpaper: the modern wallpaper API. The visible cross-fade is done by
# desktop_fade.py, which fades the old picture out on the desktop layer.
_CLSID_DESKTOP_WALLPAPER = "{C2CF3110-460E-4fc1-B9D0-8A1C0C9CC4BD}"
_IID_IDESKTOP_WALLPAPER = "{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}"
_POSITIONS = {"Center": 0, "Tile": 1, "Stretch": 2, "Fit": 3, "Fill": 4, "Span": 5}


def _set_wallpaper_fade(path, style):
    ole32 = ctypes.oledll.ole32
    try:
        ole32.CoInitialize(None)                      # fine if this thread already has COM
    except OSError:
        pass
    obj = ctypes.c_void_p()
    ole32.CoCreateInstance(ctypes.byref(_GUID(_CLSID_DESKTOP_WALLPAPER)), None, 0x17,   # CLSCTX_ALL
                           ctypes.byref(_GUID(_IID_IDESKTOP_WALLPAPER)), ctypes.byref(obj))
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents

    def method(index, *argtypes):
        return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtbl[index])

    try:
        method(10, ctypes.c_int)(obj, _POSITIONS.get(style, 4))                       # SetPosition
        method(3, ctypes.c_wchar_p, ctypes.c_wchar_p)(obj, None, os.path.abspath(path))  # SetWallpaper (all screens)
    finally:
        method(2)(obj)                                                                # Release


def shown_wallpaper():
    """The image Windows is displaying right now (its own copy, so it survives cache cleanup)."""
    t = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Themes", "TranscodedWallpaper")
    if os.path.isfile(t):
        return t
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DESKTOP_KEY) as k:
            p = winreg.QueryValueEx(k, "WallPaper")[0]
        return p if os.path.isfile(p) else ""
    except OSError:
        return ""


def set_wallpaper(path, style="Fill"):
    ws, tile = STYLES.get(style, STYLES["Fill"])
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DESKTOP_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, ws)
        winreg.SetValueEx(k, "TileWallpaper", 0, winreg.REG_SZ, tile)
    try:
        _set_wallpaper_fade(path, style)
        return
    except OSError:
        pass                                          # fall back to the old-style call
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
    style = next((n for n, v in STYLES.items() if v == (o.get("style", "10"), o.get("tile", "0"))), "Fill")
    try:
        _set_wallpaper_fade(o["path"], style)
    except OSError:
        ctypes.windll.user32.SystemParametersInfoW(20, 0, o["path"], 3)


def launch_command():
    if getattr(sys, "frozen", False):          # running as the packaged Wallflow.exe
        return f'"{sys.executable}" --autostart'
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Wallflow.pyw")
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return f'"{exe}" "{script}" --autostart'


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]


def on_battery():
    st = _PowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return False
    return st.ACLineStatus == 0 and st.BatteryFlag != 128   # 128 = no battery (desktop PC)


def fullscreen_app_running():
    """True while a game, full-screen video/app or presentation is in front."""
    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except (AttributeError, OSError):
        return False
    return state.value in (2, 3, 4)   # BUSY, RUNNING_D3D_FULL_SCREEN, PRESENTATION_MODE


GITHUB_REPO = "maxjp5/wallflow"


def latest_release():
    """(version, page_url) of the newest GitHub release."""
    data = sources.get_json(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                            {"Accept": "application/vnd.github+json"})
    return data.get("tag_name", "").lstrip("v"), data.get("html_url", "")


def is_newer(version, than=VERSION):
    def parts(v):
        return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)
    return parts(version) > parts(than)


def folder_size(folder):
    total = 0
    for root, _dirs, files in os.walk(folder):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


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

def download_image(cand, dest_dir=CACHE_DIR, name=None, target=None):
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
    if target and not cand.local:
        tw, th = target
        if w < tw * 0.8 or h < th * 0.8:
            raise ValueError(f"too small for your screen ({w}x{h} < {tw}x{th})")
        if abs((w / h) / (tw / th) - 1) > 0.25:
            raise ValueError(f"wrong shape for your screen ({w}x{h})")
        img = ImageOps.fit(img.convert("RGB"), (tw, th), Image.LANCZOS)   # exact fit, centered crop
    if max(img.size) > 15360:
        img.thumbnail((15360, 15360))
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
        match = settings.get("match_screens", True)
        cfg = {**settings["sources"][key], "_match": match}
        try:
            cands = fn(cfg, screen)
        except Exception as e:  # noqa: BLE001 - surface any source failure
            errors.append(f"{label}: {e}")
            continue
        fresh = [c for c in cands if c.url not in seen] or cands
        random.shuffle(fresh)
        for cand in fresh[:6]:
            try:
                log(f"Downloading from {label}…")
                path = download_image(cand, target=screen if match else None)
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
                  cancelled=lambda: False, match=False):
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
            cands = fn({**cfg, "_match": match}, screen, page=page)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"{label}: {e}") from e
        new = [c for c in cands if c.url not in have]
        empty_pages = empty_pages + 1 if not new else 0
        for cand in new:
            if done >= count or cancelled():
                break
            fname = f"{source_key}_{hashlib.sha1(cand.url.encode()).hexdigest()[:12]}.jpg"
            try:
                download_image(cand, folder, fname, target=screen if match else None)
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


FAVORITES_META = "wallflow-favorites.json"


def _fav_meta():
    try:
        with open(os.path.join(FAVORITES_DIR, FAVORITES_META), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_fav_meta(meta):
    os.makedirs(FAVORITES_DIR, exist_ok=True)
    with open(os.path.join(FAVORITES_DIR, FAVORITES_META), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)


def favorite_path(entry):
    """Where this wallpaper lives (or would live) in the favorites folder."""
    p = entry["path"]
    if os.path.normcase(os.path.dirname(os.path.abspath(p))) == os.path.normcase(FAVORITES_DIR):
        return p                                    # it already is a favorite file
    return os.path.join(FAVORITES_DIR, f"{entry['source']}_{os.path.basename(p)}")


def is_favorite(entry):
    return bool(entry) and os.path.isfile(favorite_path(entry))


def save_favorite(entry):
    os.makedirs(FAVORITES_DIR, exist_ok=True)
    dest = favorite_path(entry)
    if not os.path.isfile(dest):
        shutil.copy2(entry["path"], dest)
        os.utime(dest)                              # sort by when you saved it, newest first
    meta = _fav_meta()
    meta[os.path.basename(dest)] = {"title": entry.get("title", ""), "page": entry.get("page", ""),
                                    "source": entry.get("source", ""), "ping": entry.get("ping", "")}
    _write_fav_meta(meta)
    return dest


def remove_favorite(entry):
    dest = favorite_path(entry)
    if os.path.isfile(dest):
        os.remove(dest)
    meta = _fav_meta()
    if meta.pop(os.path.basename(dest), None) is not None:
        _write_fav_meta(meta)


def list_favorites():
    """Favorites as history-style entries, newest first."""
    if not os.path.isdir(FAVORITES_DIR):
        return []
    meta = _fav_meta()
    out = []
    for p in sources.list_images(FAVORITES_DIR):
        if os.path.dirname(p) != FAVORITES_DIR:
            continue                                # only the top folder
        m = meta.get(os.path.basename(p), {})
        src = m.get("source") or os.path.basename(p).split("_", 1)[0]
        out.append({"path": p, "source": src, "title": m.get("title") or os.path.basename(p),
                    "page": m.get("page") or p, "time": os.path.getmtime(p), "favorite": True})
    out.sort(key=lambda e: e["time"], reverse=True)
    return out
