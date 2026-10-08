#!/usr/bin/env python3
"""wapa — trocar wallpaper GNOME. GTK4 + Libadwaita. Só usa o que já tem no PC."""
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Gio, GLib, Gdk

import wallpaper as wp
from lang import tr, set_lang

APP_ID = "local.wapa"
APP_NAME = "Wapa"
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
ICON_FILES = (BASE_DIR / "icon.png", BASE_DIR / "icon.jpg")
DEFAULT_FOLDER = str(Path.home() / "Pictures" / "Wallpapers")


def _find_icon() -> str:
    for cand in ICON_FILES:
        if cand.is_file():
            return str(cand)
    return ""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _read_pid(path: Path) -> int | None:
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
        return pid if _pid_alive(pid) else None
    except (OSError, ValueError):
        return None


def _tray_running() -> bool:
    return _read_pid(TRAY_PID_FILE) is not None


def _ensure_tray() -> None:
    """Garante o tray rodando (processo separado GTK3). Silencioso se indisponível."""
    if _tray_running():
        return
    try:
        subprocess.Popen([sys.executable, str(BASE_DIR / "tray.py"),
                          "--icon", _find_icon()],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception:
        pass


def load_config() -> dict:
    cfg = {"folder": DEFAULT_FOLDER, "picture-options": "zoom", "lang": "pt_BR"}
    if CONFIG_FILE.is_file():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


THUMB_W, THUMB_H = 220, 150


def thumb_pixbuf(path: str, scale: int = 1):
    """Reduz a foto para caber inteira no thumbnail (nítido em HiDPI)."""
    return wp.fit_pixbuf(path, THUMB_W * scale, THUMB_H * scale)


class WallpaperWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(1050, 650)
        self.cfg = load_config()
        self.selected: str | None = None
        self.thumb_buttons: list[Gtk.Widget] = []
        self._thumbs: dict = {}
        self._last_folder: str | None = None
        self._preview_path: str | None = None

        # Header
        header = Adw.HeaderBar()
        self.folder_label = Gtk.Label(label=self.cfg["folder"], xalign=0)
        self.folder_label.set_ellipsize(3)  # end ellipsis
        header.set_title_widget(self.folder_label)

        btn_folder = Gtk.Button(label=tr("change_folder"))
        btn_folder.connect("clicked", self.on_pick_folder)
        header.pack_end(btn_folder)

        self.wh_win = None
        btn_wh = Gtk.Button(label="Wallhaven")
        btn_wh.connect("clicked", self.on_open_wallhaven)
        header.pack_start(btn_wh)

        lang_btn = Gtk.MenuButton(label=tr("lang_btn"))
        lang_menu = Gio.Menu()
        lang_menu.append("Português (BR)", "win.lang_pt")
        lang_menu.append("English (US)", "win.lang_en")
        lang_btn.set_menu_model(lang_menu)
        lang_btn.set_tooltip_text(tr("lang_btn"))
        header.pack_start(lang_btn)
        for code, act in (("pt_BR", "lang_pt"), ("en_US", "lang_en")):
            a = Gio.SimpleAction.new(act, None)
            a.connect("activate", self._on_lang, code)
            self.add_action(a)

        # Layout principal: esquerda lista, direita preview
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main.append(header)

        content = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        content.set_position(710)
        content.set_vexpand(True)
        main.append(content)

        # Esquerda: busca + grade
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left.set_margin_start(12)
        left.set_margin_end(6)
        left.set_margin_top(12)
        left.set_margin_bottom(12)

        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_vexpand(True)
        self.flow = Gtk.FlowBox()
        self.flow.set_max_children_per_line(4)
        self.flow.set_homogeneous(True)
        self.flow.set_column_spacing(12)
        self.flow.set_row_spacing(12)
        self.flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.flow.connect("selected-children-changed", self.on_select)
        self.scrolled.set_child(self.flow)
        left.append(self.scrolled)

        # Direita: preview + opções + botões
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        right.set_margin_start(6)
        right.set_margin_end(12)
        right.set_margin_top(12)
        right.set_margin_bottom(12)
        right.set_size_request(300, -1)

        self.preview = Gtk.Picture()
        self.preview.set_size_request(280, 180)
        self.preview.set_can_shrink(True)
        frame = Gtk.Frame()
        frame.set_child(self.preview)
        right.append(frame)

        self.info = Gtk.Label(label=tr("select_image"), xalign=0)
        self.info.set_wrap(True)
        right.append(self.info)

        # picture-options
        opt_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        opt_row.append(Gtk.Label(label=tr("adjust")))
        self.opt_combo = Gtk.DropDown.new_from_strings(wp.VALID_OPTIONS)
        try:
            self.opt_combo.set_selected(wp.VALID_OPTIONS.index(self.cfg.get("picture-options", "zoom")))
        except ValueError:
            self.opt_combo.set_selected(5)
        self.opt_combo.connect("notify::selected", self.on_option_changed)
        opt_row.append(self.opt_combo)
        right.append(opt_row)

        # modo claro/escuro
        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mode_row.append(Gtk.Label(label=tr("mode_label")))
        self.mode_combo = Gtk.DropDown.new_from_strings(
            [tr("mode_both"), tr("mode_light"), tr("mode_dark")])
        mode_row.append(self.mode_combo)
        right.append(mode_row)

        btn_apply = Gtk.Button(label=tr("apply"))
        btn_apply.add_css_class("suggested-action")
        btn_apply.connect("clicked", self.on_apply)
        right.append(btn_apply)

        self.status = Gtk.Label(label="", xalign=0)
        self.status.set_wrap(True)
        right.append(self.status)

        content.set_start_child(left)
        content.set_end_child(right)
        self.set_content(main)

        self.reload_folder()

    # ---- pasta ----
    def reload_folder(self):
        folder = self.cfg["folder"]
        self.folder_label.set_text(folder)
        if folder != self._last_folder:
            self._thumbs.clear()  # pasta trocou: descarta o cache
            self._last_folder = folder
        # limpa
        child = self.flow.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.flow.remove(child)
            child = nxt
        self.thumb_buttons.clear()
        self.selected = None

        images = wp.list_images(folder)
        if not images:
            self.info.set_text(tr("no_images", folder=folder))
            self.status.set_text(tr("hint_folder"))
            return
        for path in images:
            btn = self._thumb_button(path)
            self.flow.insert(btn, -1)
        self.info.set_text(tr("found", n=len(images)))

    def _thumb_button(self, path: str) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        try:
            # Gtk.Image mostra como ÍCONE (sempre pequeno) — para foto usar Picture
            px = self._thumbs.get(path)
            if px is None:
                px = thumb_pixbuf(path, scale=max(1, self.flow.get_scale_factor()))
                self._thumbs[path] = px
            thumb = Gtk.Picture.new_for_pixbuf(px)
            thumb.set_content_fit(Gtk.ContentFit.CONTAIN)
            thumb.set_halign(Gtk.Align.CENTER)
            thumb.set_valign(Gtk.Align.START)
            thumb.set_can_shrink(True)
            thumb.set_size_request(THUMB_W, THUMB_H)
            box.append(thumb)
        except Exception:
            fallback = Gtk.Image.new_from_icon_name("image-missing")
            fallback.set_pixel_size(64)
            fallback.set_size_request(THUMB_W, THUMB_H)
            box.append(fallback)
        name = Gtk.Label(label=Path(path).name, max_width_chars=20)
        name.set_ellipsize(3)
        name.set_hexpand(True)
        name.set_xalign(0.5)
        trash = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        trash.add_css_class("destructive-action")
        trash.set_tooltip_text(tr("trash_tip"))
        trash.set_valign(Gtk.Align.CENTER)
        gest = Gtk.GestureClick()
        gest.connect("pressed", self._on_trash_pressed, path)
        trash.add_controller(gest)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.append(name)
        row.append(trash)
        box.append(row)
        # guarda path no widget
        box._wall_path = path
        return box

    def _on_trash_pressed(self, gest, _n_press, _x, _y, path: str):
        shift = bool(gest.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)
        if shift:
            self._delete_file(path)
        else:
            self._trash_confirm(path)

    def _trash_confirm(self, path: str):
        dlg = Adw.MessageDialog(transient_for=self, heading=tr("delete_title"),
                                body=tr("delete_body", name=Path(path).name))
        dlg.add_response("cancel", tr("cancel"))
        dlg.add_response("delete", tr("delete_btn"))
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")
        dlg.connect("response", self._on_trash_response, path)
        dlg.present()

    def _on_trash_response(self, _dlg, resp: str, path: str):
        if resp == "delete":
            self._delete_file(path)

    def _delete_file(self, path: str):
        try:
            cur = wp.current_path()
            was_current = cur is not None and Path(cur).resolve() == Path(path).resolve()
        except OSError:
            was_current = False
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            self.status.set_text(tr("not_deleted", e=e))
            return
        msg = tr("deleted", name=Path(path).name)
        if was_current:
            try:
                nxt = wp.step(self.cfg["folder"], 1, mode="both",
                              options=self.cfg.get("picture-options", "zoom"))
                msg += tr("deleted_current", name=Path(nxt).name)
            except Exception as e:
                msg += tr("deleted_empty", e=e)
        if self.selected == path:
            self.selected = None
        # remoção cirúrgica: tira só o item, sem recarregar todas as fotos
        self._thumbs.pop(path, None)
        if self._preview_path == path:
            self.preview.set_filename(None)
            self._preview_path = None
        child = self.flow.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            if getattr(child.get_child(), "_wall_path", None) == path:
                self.flow.remove(child)
                break
            child = nxt
        remaining = wp.list_images(self.cfg["folder"])
        if self.selected and not Path(self.selected).is_file():
            self.selected = None  # era fantasma: limpa
        if self.selected:
            self.info.set_text(Path(self.selected).name)
        elif remaining:
            self.info.set_text(tr("found", n=len(remaining)))
        else:
            self.info.set_text(tr("no_images", folder=self.cfg["folder"]))
        self.status.set_text(msg)

    def on_select(self, flow):
        sel = flow.get_selected_children()
        if not sel:
            return
        widget = sel[0].get_child()
        # FlowBoxChild -> nosso box
        box = widget
        # quando insert com Widget direto, get_child retorna o widget
        path = getattr(box, "_wall_path", None)
        if path is None and hasattr(widget, "get_first_child"):
            # fallback: procura atributo nos filhos
            c = widget.get_first_child()
            while c:
                if hasattr(c, "_wall_path"):
                    path = c._wall_path
                    break
                c = c.get_next_sibling()
        if path:
            if not Path(path).is_file():
                # fantasma (apagado por shift+clique): ignora e limpa
                self.selected = None
                if self._preview_path == path:
                    self.preview.set_filename(None)
                    self._preview_path = None
                return
            self.selected = path
            self._preview_path = path
            try:
                self.preview.set_filename(path)
            except Exception:
                pass
            self.info.set_text(Path(path).name)

    # ---- config ----
    def on_option_changed(self, combo, _pspec):
        opt = wp.VALID_OPTIONS[combo.get_selected()]
        self.cfg["picture-options"] = opt
        save_config(self.cfg)
        # aplica na hora, igual ao GNOME (só o ajuste, sem trocar a imagem)
        try:
            wp.set_options(opt)
            self.status.set_text(tr("applied_opt", opt=opt))
        except Exception as e:
            self.status.set_text(tr("error", e=e))

    def on_pick_folder(self, _btn):
        dlg = Gtk.FileChooserDialog(
            title=tr("pick_folder_title"),
            transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dlg.add_button(tr("cancel"), Gtk.ResponseType.CANCEL)
        dlg.add_button(tr("choose"), Gtk.ResponseType.ACCEPT)
        dlg.connect("response", self._on_folder_response)
        dlg.show()

    def _on_folder_response(self, dlg, resp):
        if resp == Gtk.ResponseType.ACCEPT:
            f = dlg.get_file()
            if f:
                self.cfg["folder"] = f.get_path()
                save_config(self.cfg)
                self.reload_folder()
        dlg.destroy()

    # ---- wallhaven ----
    def on_open_wallhaven(self, _btn):
        if self.wh_win is None:
            from wallhaven_win import WallhavenWindow
            self.wh_win = WallhavenWindow(self.get_application(), load_config,
                                          self.reload_folder)
            self.wh_win.connect("close-request", self._on_wh_closed)
        self.wh_win.present()

    def _on_wh_closed(self, _win):
        self.wh_win = None
        return False

    # ---- aplicar ----
    def on_apply(self, _btn):
        if not self.selected:
            self.status.set_text(tr("select_first"))
            return
        modes = ["both", "light", "dark"]
        mode = modes[self.mode_combo.get_selected()]
        opt = wp.VALID_OPTIONS[self.opt_combo.get_selected()]
        try:
            wp.set_wallpaper(self.selected, mode=mode, options=opt)
            self.cfg["picture-options"] = opt
            save_config(self.cfg)
            nomes = {"both": tr("applied_both"), "light": tr("applied_light"),
                     "dark": tr("applied_dark")}
            self.status.set_text(tr("applied", mode=nomes[mode], name=Path(self.selected).name))
        except Exception as e:
            self.status.set_text(tr("error", e=e))

    # ---- idioma ----
    def _on_lang(self, _act, _p, code: str):
        from lang import get_lang
        if get_lang() == code:
            return
        self.cfg["lang"] = code
        save_config(self.cfg)
        self._restart_app()

    def _restart_app(self):
        # mata o tray certo (confere cmdline p/ não acertar PID reciclado)
        try:
            pid = _read_pid(TRAY_PID_FILE)
            if pid is not None:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    if "tray.py" in f.read().decode(errors="replace"):
                        os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        # espera o processo atual morrer de verdade (sem race de single-instance)
        subprocess.Popen(
            ["bash", "-c",
             'ppid=$1; while kill -0 "$ppid" 2>/dev/null; do sleep 0.2; done;'
             ' exec "$3" "$2"',
             "wapa-restart", str(os.getpid()), str(BASE_DIR / "main.py"),
             sys.executable],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        self.get_application().quit()


class WallpaperApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self._win = None

    def do_activate(self):
        if not self._win:
            self._win = WallpaperWindow(self)
            self._win.connect("close-request", self._on_close)
            # armadilha: janela escondida + tray morto = app fantasma inalcançável.
            # Se isso acontecer, encerra para o próximo lançamento abrir do zero.
            GLib.timeout_add_seconds(15, self._watch_ghost)
        self._win.present()

    def _watch_ghost(self):
        if self._win is not None and not self._win.is_visible() and not _tray_running():
            self.quit()
            return False
        return True

    def _on_close(self, _win):
        # fechar esconde para o tray; sair de verdade pelo menu do tray
        if _tray_running():
            self._win.hide()
            return True  # impede destruir a janela
        return False  # sem tray: fecha normal

    def do_shutdown(self):
        try:
            if MAIN_PID_FILE.is_file():
                MAIN_PID_FILE.unlink()
        except OSError:
            pass
        Adw.Application.do_shutdown(self)


def main():
    cfg = load_config()
    set_lang(cfg.get("lang", "pt_BR"))
    # garante pasta padrão só em runtime (não cria nada fora na instalação)
    try:
        Path(cfg["folder"]).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        MAIN_PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    _ensure_tray()
    app = WallpaperApp()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM,
                         lambda: (app.quit(), True)[1])
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
