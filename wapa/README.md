# wapa

GNOME wallpaper changer with system tray and Wallhaven browser.

## Features

- **Local grid**: thumbnails with full-image preview, fit options (`zoom`, `scaled`, …), light/dark/both targets, one-click delete (Shift+click deletes directly)
- **Tray**: open, next/previous wallpaper, shuffle with no repeats, quit
- **Wallhaven browser** (SFW, no API key needed): full filters (categories, sorting, exact/min resolution presets, ratio presets, color palette, toplist range), pagination, download straight into your folder
- **Languages**: PT-BR and EN-US (switch in the header, app restarts itself)
- **Cache**: thumbnails capped at 50 MB, old entries evicted first

## Run from source

Requirements (system packages): Python 3, PyGObject, GTK4 + Libadwaita, Ayatana AppIndicator (for the tray), GNOME Shell.

```bash
python3 main.py
```

Closing the window hides it to the tray. Quit from the tray menu.

## Run the AppImage

Download `wapa-x86_64.AppImage` from
[Releases](https://github.com/usr-kmasx/wapa/releases), make it executable and run it:

```bash
chmod +x wapa-x86_64.AppImage
./wapa-x86_64.AppImage
```

No installation, no dependencies — settings live in `~/.config/wapa/`.

## Notes

- GNOME `zoom` fills the screen and crops (same as GNOME Settings); thumbnails always show the whole photo.
- Wallhaven `random` sorting reuses the server seed across pages (no repeats); local shuffle never repeats a photo before showing them all.
- `wallpaper` fit option tiles the image (GNOME behavior).
