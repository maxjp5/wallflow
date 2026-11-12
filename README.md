<p align="center"><img src="logo.png" width="128" alt="Wallflow logo"></p>

# Wallflow

An automatic wallpaper changer for Windows. Wallflow pulls fresh wallpapers from popular galleries on a timer, or rotates through packs you download for offline use.

## Features

- **Auto-change on a timer**: every 5 minutes up to every 24 hours, with a live countdown
- **Multiple sources** (it picks one of the sources you turn on each time):
  - **Wallhaven**: search, plus Toplist (past day → past year), Hot, Most viewed, Most favorited, Latest, or any public collection link
  - **Unsplash**: topics, search, collections or random (needs a free [Unsplash access key](https://unsplash.com/developers))
  - **NASA**: space photos from the NASA Image Library
  - **Picsum**: random photos
  - **Your own folder**
- **Offline packs**: download 24–200 wallpapers from a search in one go, then rotate through them without internet
- Previous / Next, a clickable history of recent wallpapers, and ★ favorites saved to `Pictures\Wallflow Favorites`
- Fill / Fit / Stretch / Center / Span
- Two designs you can switch between: native **Windows 11** (Fluent, Mica) and **Liquid Glass**, where the window is your wallpaper with frosted panels
- Smooth animations, light/dark themes and accent colors
- Matches wallpapers to your monitors and crops them to your exact resolution
- Pauses while you game or run on battery
- Lives in the system tray, can start with Windows, and can restore your original wallpaper
- Safe-for-work content only

## Install

Download **`Wallflow-Setup-x.y.z.exe`** from the [Releases](../../releases) page and run it. You don't need admin rights; it installs for your user only.

> Windows SmartScreen may warn about an unrecognized app because the installer isn't code-signed. Click **More info → Run anyway**.

## Run from source

Requires Python 3.10+ (built with PySide6 and PySide6-Fluent-Widgets).

```
pip install -r requirements.txt
pythonw Wallflow.pyw
```

## Build the installer

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`).

```
powershell -ExecutionPolicy Bypass -File build.ps1
```

This creates `dist\Wallflow\Wallflow.exe` and `release\Wallflow-Setup-<version>.exe`. The version number is set in `core.py`.

## Files

| File | What it does |
|---|---|
| `Wallflow.pyw` | Starts the app: single instance, tray, main window |
| `controller.py` | The engine the window talks to: timer, fetching, history |
| `ui_home.py` | Home page: now-showing card, progress bar, animated gallery |
| `ui_sources.py` | Sources page |
| `ui_packs.py` | Packs page and the pack download dialog |
| `ui_settings.py` | Settings page |
| `ui_glass.py` | The Liquid Glass design |
| `ui_feedback.py` | Favorite feedback for each design |
| `shell.py` | Tray, close-to-tray, messages and design switching |
| `desktop_fade.py` | Cross-fades the desktop when the wallpaper changes |
| `theme.py` | Accent colors |
| `make_icon.py` | Draws the logo (`wallflow.ico`, `logo.png`) |
| `core.py` | Settings, downloading, screen detection, setting the wallpaper |
| `sources.py` | One function per wallpaper source |
| `installer.iss` / `build.ps1` | Builds the exe and the installer |

## Where data is stored

- Settings, image cache, original-wallpaper backup and error log: `%APPDATA%\Wallflow`
- Favorites: `Pictures\Wallflow Favorites`
- Packs: `Pictures\Wallflow Packs`

## Credits

Images come from [Wallhaven](https://wallhaven.cc), [Unsplash](https://unsplash.com), [NASA](https://images.nasa.gov) and [Lorem Picsum](https://picsum.photos). They belong to their creators. Use **Open page** in the app to see each image's source.

## License

MIT. See [LICENSE](LICENSE).
