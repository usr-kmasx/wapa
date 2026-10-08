#!/usr/bin/env python3
"""wapa tray — processo separado em GTK3 (Ayatana exige Gtk.Menu, ausente no GTK4)."""
import argparse
import fcntl
import json
import os
import signal
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, AyatanaAppIndicator3 as AI

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wallpaper as wp
from lang import tr, set_lang

BASE_DIR = Path(__file__).resolve().parent


def _runtime_dir() -> Path:
    """Pasta gravável p/ estado (no AppImage o BASE_DIR é read-only)."""
    try:
        probe = BASE_DIR / ".wapa-write-test"
        probe.touch()
        probe.unlink()
        return BASE_DIR
    except OSError:
        d = Path.home() / ".config" / "wapa"
        d.mkdir(parents=True, exist_ok=True)
        return d


RUNTIME_DIR = _runtime_dir()
CONFIG_FILE = RUNTIME_DIR / "config.json"
MAIN_PID_FILE = RUNTIME_DIR / ".wapa-main.pid"
TRAY_PID_FILE = RUNTIME_DIR / ".wapa-tray.pid"
QUEUE_FILE = RUNTIME_DIR / ".wapa-queue.json"
TRAY_LOCK_FILE = RUNTIME_DIR / ".wapa-tray.lock"
MAIN_SCRIPT = BASE_DIR / "main.py"
FALLBACK_ICON = "preferences-desktop-wallpaper"


def load_cfg() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _settings_for_apply() -> tuple[str, str]:
    cfg = load_cfg()
    folder = cfg.get("folder", str(Path.home() / "Pictures" / "Wallpapers"))
    options = cfg.get("picture-options", "zoom")
    if options not in wp.VALID_OPTIONS:
        options = "zoom"
    return folder, options


def _open_main(_item):
    import subprocess
    try:
        subprocess.Popen([sys.executable, str(MAIN_SCRIPT)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception:
        pass


def _step(_item, direction: int):
    try:
        folder, options = _settings_for_apply()
        wp.step(folder, direction=direction, mode="both", options=options)
    except Exception:
        pass


def _random(_item):
    try:
        folder, options = _settings_for_apply()
        wp.random_wallpaper(folder, mode="both", options=options,
                            state_file=str(QUEUE_FILE))
    except Exception:
        pass


def _cleanup():
    try:
        if TRAY_PID_FILE.is_file():
            TRAY_PID_FILE.unlink()
    except OSError:
        pass


_lock_fd = None


def _single_instance() -> bool:
    """Garante um único tray (lock liberado sozinho se o processo morrer)."""
    global _lock_fd
    try:
        _lock_fd = open(str(TRAY_LOCK_FILE), "w")
        fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (OSError, IOError):
        return False


def _main_pid() -> int | None:
    """PID do main válido: pidfile existe, processo vivo E cmdline é o main.py."""
    try:
        pid = int(MAIN_PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if pid == os.getpid():
        return None
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmd = f.read().decode(errors="replace")
    except OSError:
        return None
    return pid if str(MAIN_SCRIPT) in cmd else None


def _quit(_item):
    pid = _main_pid()
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    _cleanup()
    Gtk.main_quit()


def build_menu() -> Gtk.Menu:
    menu = Gtk.Menu()

    item_open = Gtk.MenuItem(label=tr("open"))
    item_open.connect("activate", _open_main)
    menu.append(item_open)

    menu.append(Gtk.SeparatorMenuItem())

    item_next = Gtk.MenuItem(label=tr("next"))
    item_next.connect("activate", _step, 1)
    menu.append(item_next)

    item_prev = Gtk.MenuItem(label=tr("prev"))
    item_prev.connect("activate", _step, -1)
    menu.append(item_prev)

    item_rand = Gtk.MenuItem(label=tr("random"))
    item_rand.connect("activate", _random)
    menu.append(item_rand)

    menu.append(Gtk.SeparatorMenuItem())

    item_quit = Gtk.MenuItem(label=tr("quit"))
    item_quit.connect("activate", _quit)
    menu.append(item_quit)

    menu.show_all()
    return menu


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--icon", default="", help="caminho do icon.png (criado pelo usuário)")
    args = ap.parse_args()
    set_lang(load_cfg().get("lang", "pt_BR"))
    if not _single_instance():
        return 0  # outro tray já está rodando

    try:
        TRAY_PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass

    icon = args.icon if args.icon and Path(args.icon).is_file() else ""
    if not icon:
        for cand in ("icon.png", "icon.jpg"):
            if (BASE_DIR / cand).is_file():
                icon = str(BASE_DIR / cand)
                break
    if not icon:
        icon = FALLBACK_ICON
    try:
        ind = AI.Indicator.new("wapa", FALLBACK_ICON,
                               AI.IndicatorCategory.APPLICATION_STATUS)
        if icon != FALLBACK_ICON:
            ind.set_icon_full(icon, "wapa")
        ind.set_status(AI.IndicatorStatus.ACTIVE)
        ind.set_menu(build_menu())
    except Exception as e:
        print(f"wapa tray indisponível: {e}", file=sys.stderr)
        return 1

    from gi.repository import GLib
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM,
                         lambda: (_cleanup(), Gtk.main_quit(), True)[-1])
    try:
        Gtk.main()
    finally:
        _cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
