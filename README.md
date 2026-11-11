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
- Lives in the system tray, can start with Windows, and can restore your original wallpaper
- Safe-for-work content only

## Install

Download **`Wallflow-Setup-x.y.z.exe`** from the [Releases](../../releases) page and run it. You don't need admin rights; it installs for your user only.

> Windows SmartScreen may warn about an unrecognized app because the installer isn't code-signed. Click **More info → Run anyway**.

## Run from source

Requires Python 3.10+.

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
| `Wallflow.pyw` | The window, timer, pack downloader and tray icon |
| `core.py` | Settings, downloading, setting the wallpaper, start-with-Windows |
| `sources.py` | One function per wallpaper source |
| `installer.iss` | Inno Setup installer script |
| `build.ps1` | Builds the exe and the installer |

## Where data is stored

- Settings, image cache, original-wallpaper backup and error log: `%APPDATA%\Wallflow`
- Favorites: `Pictures\Wallflow Favorites`
- Packs: `Pictures\Wallflow Packs`

## Credits

Images come from [Wallhaven](https://wallhaven.cc), [Unsplash](https://unsplash.com), [NASA](https://images.nasa.gov) and [Lorem Picsum](https://picsum.photos). They belong to their creators. Use **Open page** in the app to see each image's source.

## License

MIT. See [LICENSE](LICENSE).
