#!/usr/bin/env python3
"""Janela separada do Wallhaven — busca, filtros completos, download p/ pasta do wapa."""
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib, Gdk

import wallpaper as wp
import wallhaven as wh
from lang import tr

CACHE_DIR = Path("/tmp/wapa-wh")
THUMB_W, THUMB_H = 220, 150


def _run_bg(fn):
    threading.Thread(target=fn, daemon=True).start()


class FullscreenWindow(Adw.Window):
    """Tela cheia com a foto ORIGINAL (full) — não o thumbnail."""

    def __init__(self, parent, item: dict):
        super().__init__(transient_for=parent, modal=True,
                         title=f"{item.get('id', '')} — wapa")
        self._item = dict(item)
        self.set_default_size(1280, 800)

        self._pic = Gtk.Picture()
        self._pic.set_can_shrink(True)
        self._pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._pic.set_hexpand(True)
        self._pic.set_vexpand(True)

        overlay = Gtk.Overlay()
        overlay.set_child(self._pic)
        overlay.set_vexpand(True)

        load_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        load_box.set_halign(Gtk.Align.CENTER)
        load_box.set_valign(Gtk.Align.CENTER)
        self._spinner = Gtk.Spinner(spinning=True)
        self._spinner.set_size_request(48, 48)
        self._spinner.set_halign(Gtk.Align.CENTER)
        load_box.append(self._spinner)
        self._status = Gtk.Label(label=tr("loading_full"))
        self._status.add_css_class("osd")
        load_box.append(self._status)
        overlay.add_overlay(load_box)
        self._load_box = load_box

        close_btn = Gtk.Button.new_from_icon_name("view-restore-symbolic")
        close_btn.add_css_class("osd")
        close_btn.set_halign(Gtk.Align.END)
        close_btn.set_valign(Gtk.Align.START)
        close_btn.set_margin_top(12)
        close_btn.set_margin_end(12)
        close_btn.set_tooltip_text(tr("fullscreen_tip"))
        close_btn.connect("clicked", lambda _b: self.close())
        overlay.add_overlay(close_btn)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        click = Gtk.GestureClick()
        click.set_button(0)
        click.connect("pressed", self._on_double_click)
        self._pic.add_controller(click)

        self.set_content(overlay)
        self.fullscreen()
        _run_bg(self._load_full)

    def _on_key(self, _ctl, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_double_click(self, gest, _n_press, _x, _y):
        if _n_press == 2:
            self.close()

    def _load_full(self):
        it = self._item
        url = it.get("full") or it.get("thumb_original") or it.get("thumb_large") \
            or it.get("thumb") or ""
        if not url:
            GLib.idle_add(self._done, None, "URL vazia")
            return
        try:
            ext = wh.filename_for(it.get("id", "full"), url).rsplit(".", 1)[-1]
            dest = CACHE_DIR / f"{it.get('id', 'full')}-full.{ext}"
            if not (dest.is_file() and dest.stat().st_size > 0):
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                wh.download(url, str(dest))
                wh.enforce_cache_limit(str(CACHE_DIR))
            GLib.idle_add(self._done, str(dest), None)
        except Exception as e:
            GLib.idle_add(self._done, None, str(e))

    def _done(self, path, err):
        try:
            self._spinner.stop()
            self._load_box.set_visible(False)
        except Exception:
            pass
        if err:
            try:
                self._load_box.set_visible(True)
                self._status.set_text(tr("preview_fail", e=err))
            except Exception:
                pass
        elif path:
            try:
                self._pic.set_filename(path)
            except Exception as e:
                try:
                    self._load_box.set_visible(True)
                    self._status.set_text(tr("preview_fail", e=e))
                except Exception:
                    pass
        return False


class WallhavenWindow(Adw.Window):
    def __init__(self, app, get_config, on_downloaded):
        super().__init__(application=app, title="Wallhaven — wapa")
        self.set_default_size(1050, 680)
        self._get_config = get_config
        self._on_downloaded = on_downloaded
        self.items: list[dict] = []
        self.selected: dict | None = None
        self.page = 1
        self.last_page = 1
        self.seed = ""
        self._busy_search = False
        self._busy_dl = False
        self._rebuilding = False
        self._syncing_page = False
        self._tags_cache: dict[str, list[dict]] = {}
        self._tags_gen = 0
        self._listing_gen = 0
        self._full_win = None

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main.append(Adw.HeaderBar())
        self.set_content(main)

        # ---- busca ----
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        search_row.set_margin_start(12)
        search_row.set_margin_end(12)
        search_row.set_margin_top(12)
        search_row.set_margin_bottom(6)
        self.entry_q = Gtk.SearchEntry(placeholder_text=tr("search_ph"))
        self.entry_q.set_hexpand(True)
        self.entry_q.set_tooltip_text(tr("search_tip"))
        self.entry_q.connect("activate", lambda _e: self.search(1))
        search_row.append(self.entry_q)
        btn_go = Gtk.Button(label=tr("search_btn"))
        btn_go.add_css_class("suggested-action")
        btn_go.connect("clicked", lambda _b: self.search(1))
        search_row.append(btn_go)
        main.append(search_row)

        # ---- filtros básicos ----
        filt = Gtk.FlowBox()
        filt.set_selection_mode(Gtk.SelectionMode.NONE)
        filt.set_max_children_per_line(20)
        filt.set_column_spacing(10)
        filt.set_row_spacing(6)
        filt.set_margin_start(12)
        filt.set_margin_end(12)
        filt.set_margin_bottom(6)

        self.chk_general = Gtk.CheckButton(label="General")
        self.chk_general.set_active(True)
        self.chk_anime = Gtk.CheckButton(label="Anime")
        self.chk_anime.set_active(True)
        self.chk_people = Gtk.CheckButton(label="People")
        self.chk_people.set_active(True)
        for c in (self.chk_general, self.chk_anime, self.chk_people):
            filt.append(c)

        filt.append(Gtk.Label(label=tr("sort_label")))
        self.cmb_sort = Gtk.DropDown.new_from_strings(
            ["relevance", "date_added", "views", "favorites", "toplist", "random"])
        self.cmb_sort.set_selected(4)  # padrão: toplist 1M
        self.cmb_sort.connect("notify::selected", lambda *_: self._sync_toprange())
        filt.append(self.cmb_sort)

        self.chk_desc = Gtk.CheckButton(label=tr("desc"))
        self.chk_desc.set_active(True)
        filt.append(self.chk_desc)

        sfw = Gtk.Label(label="SFW")
        sfw.add_css_class("caption")
        filt.append(sfw)

        self.chk_owned = Gtk.CheckButton(label=tr("hide_owned"))
        self.chk_owned.connect("toggled", lambda *_: self._render_flow())
        filt.append(self.chk_owned)
        main.append(filt)

        # ---- filtros avançados (dobrável) ----
        exp = Gtk.Expander(label=tr("adv"))
        exp.set_margin_start(12)
        exp.set_margin_end(12)
        exp.set_margin_bottom(6)
        adv = Gtk.FlowBox()
        adv.set_selection_mode(Gtk.SelectionMode.NONE)
        adv.set_max_children_per_line(20)
        adv.set_column_spacing(10)
        adv.set_row_spacing(6)

        adv.append(Gtk.Label(label=tr("res_exact")))
        self.cmb_res = Gtk.DropDown.new_from_strings([tr("any")] + wh.RESOLUTION_PRESETS)
        self.cmb_res.set_selected(0)
        adv.append(self.cmb_res)

        adv.append(Gtk.Label(label=tr("res_min")))
        self.cmb_min = Gtk.DropDown.new_from_strings([tr("any")] + wh.RESOLUTION_PRESETS)
        self.cmb_min.set_selected(0)
        self.cmb_min.set_tooltip_text(tr("res_min_tip"))
        adv.append(self.cmb_min)

        adv.append(Gtk.Label(label=tr("ratio")))
        self.cmb_ratio = Gtk.DropDown.new_from_strings([tr("any")] + wh.RATIO_PRESETS)
        self.cmb_ratio.set_selected(0)
        adv.append(self.cmb_ratio)

        adv.append(Gtk.Label(label=tr("color")))
        self.color_btn = Gtk.MenuButton()
        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.color_dot = Gtk.Box()
        self.color_dot.set_size_request(20, 20)
        self.color_dot.set_name("whc-none")
        self.color_lbl = Gtk.Label(label=tr("any"))
        color_box.append(self.color_dot)
        color_box.append(self.color_lbl)
        self.color_btn.set_child(color_box)
        pop = Gtk.Popover()
        grid = Gtk.Grid(column_spacing=3, row_spacing=3)
        grid.set_margin_start(8)
        grid.set_margin_end(8)
        grid.set_margin_top(8)
        grid.set_margin_bottom(8)
        self.sel_color = ""
        self._swatches: dict[str, Gtk.Button] = {}
        css = []
        for i, hx in enumerate(wh.WH_COLORS):
            b = Gtk.Button()
            b.set_size_request(24, 24)
            b.set_tooltip_text(tr("swatch_tip", hx=hx))
            b.set_name(f"whc-{hx}")
            b.connect("clicked", self._on_swatch, hx)
            grid.attach(b, i % 10, i // 10, 1, 1)
            self._swatches[hx] = b
            css.append(f"#whc-{hx} {{ background: #{hx}; border-radius: 6px; "
                       f"padding: 0; min-width: 24px; min-height: 24px; }}")
        css.append("#whc-none { background: transparent; border: 1px dashed #888a85; "
                   "border-radius: 6px; min-width: 20px; min-height: 20px; }")
        css.append("button.wh-sel { outline: 2px solid #3584e4; outline-offset: 1px; }")
        prov = Gtk.CssProvider()
        prov.load_from_string("\n".join(css))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        pop.set_child(grid)
        self.color_btn.set_popover(pop)
        self.color_pop = pop
        adv.append(self.color_btn)

        adv.append(Gtk.Label(label=tr("top")))
        self.cmb_top = Gtk.DropDown.new_from_strings(wh.TOPRANGES)
        self.cmb_top.set_selected(3)
        adv.append(self.cmb_top)
        self._sync_toprange()

        exp.set_child(adv)
        main.append(exp)

        # ---- conteúdo: resultados + painel ----
        content = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        content.set_position(710)
        content.set_vexpand(True)
        main.append(content)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left.set_margin_start(12)
        left.set_margin_end(6)
        left.set_margin_bottom(6)
        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_vexpand(True)
        self.flow = Gtk.FlowBox()
        self.flow.set_max_children_per_line(4)
        self.flow.set_homogeneous(True)
        self.flow.set_column_spacing(12)
        self.flow.set_row_spacing(12)
        self.flow.set_valign(Gtk.Align.START)  # fileiras com altura natural, sem esticar
        self.flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.flow.connect("selected-children-changed", self.on_select)
        self.scrolled.set_child(self.flow)
        left.append(self.scrolled)

        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        nav.set_halign(Gtk.Align.CENTER)
        self.btn_prev = Gtk.Button(label=tr("page_prev"))
        self.btn_prev.connect("clicked", lambda _b: self.search(self.page - 1))
        self.page_pre = Gtk.Label(label=tr("page_pre"))
        self.page_pre.set_valign(Gtk.Align.CENTER)
        self.spin_page = Gtk.Entry()
        self.spin_page.set_text("1")
        self.spin_page.set_width_chars(2)
        self.spin_page.set_max_width_chars(2)
        self.spin_page.set_max_length(4)
        self.spin_page.set_input_purpose(Gtk.InputPurpose.DIGITS)
        self.spin_page.set_alignment(0.5)
        self.spin_page.set_halign(Gtk.Align.CENTER)
        self.spin_page.set_valign(Gtk.Align.CENTER)
        self.spin_page.set_tooltip_text(tr("go_page_tip"))
        self.spin_page.add_css_class("page-field")
        self._page_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self._page_css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._apply_page_width(1)
        self.spin_page.connect("activate", lambda _e: self._go_spin_page())
        self.lbl_suf = Gtk.Label(label=tr("page_suf", l=1, t=0))
        self.lbl_suf.set_valign(Gtk.Align.CENTER)
        self.btn_next = Gtk.Button(label=tr("page_next"))
        self.btn_next.connect("clicked", lambda _b: self.search(self.page + 1))
        self.lbl_count = Gtk.Label(label="")
        self.lbl_count.set_valign(Gtk.Align.CENTER)
        self.lbl_count.add_css_class("caption")
        self.lbl_count.add_css_class("dim-label")
        nav.append(self.btn_prev)
        nav.append(self.page_pre)
        nav.append(self.spin_page)
        nav.append(self.lbl_suf)
        nav.append(self.lbl_count)
        nav.append(self.btn_next)
        left.append(nav)
        self.left_status = Gtk.Label(label="")
        self.left_status.set_wrap(True)
        self.left_status.set_xalign(0)
        self.left_status.set_halign(Gtk.Align.CENTER)
        self.left_status.set_visible(False)
        left.append(self.left_status)
        content.set_start_child(left)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        right.set_margin_start(6)
        right.set_margin_end(12)
        right.set_margin_bottom(12)
        right.set_size_request(300, -1)
        self.preview = Gtk.Picture()
        self.preview.set_size_request(280, 180)
        self.preview.set_can_shrink(True)
        self.preview.set_content_fit(Gtk.ContentFit.CONTAIN)
        frame = Gtk.Frame()
        frame.set_child(self.preview)
        preview_overlay = Gtk.Overlay()
        preview_overlay.set_child(frame)
        self.btn_full = Gtk.Button.new_from_icon_name("view-fullscreen-symbolic")
        self.btn_full.add_css_class("osd")
        self.btn_full.set_tooltip_text(tr("fullscreen_tip"))
        self.btn_full.set_sensitive(False)
        self.btn_full.connect("clicked", self.on_fullscreen)
        self.btn_close_preview = Gtk.Button.new_from_icon_name("window-close-symbolic")
        self.btn_close_preview.add_css_class("osd")
        self.btn_close_preview.set_tooltip_text(tr("close_preview"))
        self.btn_close_preview.connect("clicked", self.on_close_preview)
        overlay_btns = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        overlay_btns.set_halign(Gtk.Align.END)
        overlay_btns.set_valign(Gtk.Align.START)
        overlay_btns.set_margin_top(6)
        overlay_btns.set_margin_end(6)
        overlay_btns.append(self.btn_full)
        overlay_btns.append(self.btn_close_preview)
        preview_overlay.add_overlay(overlay_btns)
        right.append(preview_overlay)
        self.info = Gtk.Label(label=tr("sel_hint"))
        self.info.set_wrap(True)
        self.info.set_xalign(0)
        right.append(self.info)
        self.tags_view = Gtk.TextView()
        self.tags_view.set_editable(False)
        self.tags_view.set_cursor_visible(False)
        self.tags_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.tags_view.add_css_class("tag-view")
        try:
            self.tags_view.set_cursor_from_name("default")
        except Exception:
            pass
        self._chip_buttons: list = []
        self._chip_css = Gtk.CssProvider()
        self._chip_css.load_from_string(
            "button.wh-tag { min-width: 0; min-height: 0; padding: 1px 8px; "
            "font-size: 0.8em; border-radius: 999px; }"
            "textview.tag-view { background: transparent; }"
            "label.wh-owned { background-color: rgba(0, 0, 0, 0.55); color: white; "
            "border-radius: 999px; padding: 1px 7px; font-size: 0.8em; }")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self._chip_css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        right.append(self.tags_view)
        self.btn_dl = Gtk.Button(label=tr("download"))
        self.btn_dl.add_css_class("suggested-action")
        self.btn_dl.set_sensitive(False)
        self.btn_dl.connect("clicked", self.on_download)
        right.append(self.btn_dl)
        self.btn_queue = Gtk.Button(label=tr("queue_page"))
        self.btn_queue.set_sensitive(False)
        self.btn_queue.connect("clicked", self.on_queue)
        right.append(self.btn_queue)
        self._queue_busy = False
        self._queue_cancel = False
        self._queue_total = 0
        self._queue: list = []
        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        self.progress.set_visible(False)
        right.append(self.progress)
        self.status = Gtk.Label(label="")
        self.status.set_wrap(True)
        self.status.set_xalign(0)
        right.append(self.status)
        content.set_end_child(right)
        self.content = content
        self.right = right
        self.right.set_visible(False)
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_esc_key)
        self.add_controller(key)
        bg = Gtk.GestureClick()
        bg.set_button(1)
        bg.connect("pressed", self._on_grid_background)
        self.scrolled.add_controller(bg)

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _run_bg(lambda: wh.enforce_cache_limit(str(CACHE_DIR)))  # poda inicial de 50 MB
        self.search(1)

    def _hide_preview(self):
        self.selected = None
        self.btn_dl.set_sensitive(False)
        self.btn_full.set_sensitive(False)
        self._tags_gen += 1
        self._clear_chips()
        try:
            self.preview.set_filename(None)
        except Exception:
            pass
        self.right.set_visible(False)

    def _clear_chips(self):
        try:
            for w in getattr(self, "_chip_buttons", []):
                try:
                    w.destroy()
                except Exception:
                    pass
        except Exception:
            pass
        self._chip_buttons = []
        try:
            self.tags_view.get_buffer().set_text("")
        except Exception:
            pass

    def _show_chips(self, tags: list[dict], expanded: bool = False):
        self._clear_chips()
        try:
            buf = self.tags_view.get_buffer()
            names = [t for t in (tags or []) if t.get("name")]
            shown = names if expanded else names[:15]
            for i, t in enumerate(shown):
                name = t["name"]
                if i > 0:
                    buf.insert(buf.get_end_iter(), " ")
                anchor = buf.create_child_anchor(buf.get_end_iter())
                b = Gtk.Button(label=name)
                b.add_css_class("pill")
                b.add_css_class("wh-tag")
                b.set_tooltip_text(name)
                try:
                    b.set_cursor_from_name("pointer")
                except Exception:
                    pass
                b.connect("clicked", self._on_chip, name)
                self.tags_view.add_child_at_anchor(b, anchor)
                self._chip_buttons.append(b)
            if len(names) > 15 and not expanded:
                buf.insert(buf.get_end_iter(), "  ")
                anchor = buf.create_child_anchor(buf.get_end_iter())
                more = Gtk.Button(label=f"+{len(names) - 15}")
                more.add_css_class("pill")
                more.add_css_class("wh-tag")
                more.set_tooltip_text(tr("show_all_tags"))
                try:
                    more.set_cursor_from_name("pointer")
                except Exception:
                    pass
                more.connect("clicked", lambda _b: self._show_chips(tags, True))
                self.tags_view.add_child_at_anchor(more, anchor)
                self._chip_buttons.append(more)
        except Exception:
            pass

    def _on_chip(self, _btn, name: str):
        try:
            self.entry_q.set_text(name)
        except Exception:
            pass
        self.search(1)

    def _load_tags(self, wid: str, gen: int):
        try:
            tags = wh.details(wid)["tags"]
            GLib.idle_add(self._tags_done, wid, gen, tags)
        except Exception:
            GLib.idle_add(self._tags_done, wid, gen, None)

    def _tags_done(self, wid: str, gen: int, tags):
        if (gen != self._tags_gen or tags is None or self.selected is None
                or not isinstance(self.selected, dict)
                or self.selected.get("id") != wid):
            return False
        self._tags_cache[wid] = tags
        self._show_chips(tags)
        return False

    def _set_left_status(self, text: str):
        self.left_status.set_text(text)
        self.left_status.set_visible(bool(text.strip()))

    def _on_esc_key(self, _ctl, keyval, _keycode, _state):
        if keyval != Gdk.KEY_Escape:
            return False
        try:
            if self.entry_q.has_focus():
                return False
        except Exception:
            pass
        if not self.right.is_visible() and self.selected is None:
            return False
        self._rebuilding = True
        try:
            self.flow.unselect_all()
        except Exception:
            pass
        finally:
            self._rebuilding = False
        self._hide_preview()
        return True

    def _pick_ignores(self, x: float, y: float) -> bool:
        """True = clique em imagem/scrollbar: não fecha."""
        try:
            t = self.scrolled.pick(x, y, Gtk.PickFlags.DEFAULT)
        except Exception:
            return True
        w = t
        while w is not None and w is not self.scrolled:
            if isinstance(w, Gtk.FlowBoxChild):
                return True
            if isinstance(w, Gtk.Scrollbar):
                return True
            try:
                w = w.get_parent()
            except Exception:
                break
        return False

    def _on_grid_background(self, _gest, n_press: int, x: float, y: float):
        if n_press != 1:
            return
        if self._pick_ignores(x, y):
            return
        if not self.right.is_visible() and self.selected is None:
            return
        self._rebuilding = True
        try:
            self.flow.unselect_all()
        except Exception:
            pass
        finally:
            self._rebuilding = False
        self._hide_preview()

    # ---- filtros ----
    def _sync_toprange(self, *args):
        is_top = wh.SORTINGS[self.cmb_sort.get_selected()] == "toplist"
        self.cmb_top.set_sensitive(is_top)

    def _on_swatch(self, btn, hx: str):
        if self.sel_color == hx:
            self.sel_color = ""
            btn.get_style_context().remove_class("wh-sel")
        else:
            old = self._swatches.get(self.sel_color)
            if old is not None:
                old.get_style_context().remove_class("wh-sel")
            self.sel_color = hx
            btn.get_style_context().add_class("wh-sel")
        self.color_dot.set_name(f"whc-{hx}" if self.sel_color else "whc-none")
        self.color_lbl.set_text(f"#{hx}" if self.sel_color else tr("any"))
        self.color_pop.popdown()

    def _params(self, page: int) -> dict:
        cats = "".join("1" if c.get_active() else "0" for c in
                       (self.chk_general, self.chk_anime, self.chk_people))
        if cats == "000":
            cats = "100"
            self.chk_general.set_active(True)
        sorting = wh.SORTINGS[self.cmb_sort.get_selected()]
        i_res = self.cmb_res.get_selected()
        i_min = self.cmb_min.get_selected()
        i_ratio = self.cmb_ratio.get_selected()
        return {
            "q": self.entry_q.get_text(),
            "categories": cats,
            "sorting": sorting,
            "order": "desc" if self.chk_desc.get_active() else "asc",
            "page": page,
            "resolutions": wh.RESOLUTION_PRESETS[i_res - 1] if i_res > 0 else "",
            "atleast": wh.RESOLUTION_PRESETS[i_min - 1] if i_min > 0 else "",
            "ratios": wh.RATIO_PRESETS[i_ratio - 1] if i_ratio > 0 else "",
            "colors": self.sel_color,
            "toprange": wh.TOPRANGES[self.cmb_top.get_selected()] if sorting == "toplist" else "",
            "seed": self.seed if sorting == "random" else "",
        }

    # ---- busca ----
    def _apply_page_width(self, last_page: int):
        """Trava a largura do campo nos dígitos (min + max em chars)."""
        digits = min(4, max(2, len(str(max(1, int(last_page))))))
        try:
            self.spin_page.set_width_chars(digits)
            self.spin_page.set_max_width_chars(digits)
            self._page_css.load_from_string(
                "entry.page-field { min-width: 0; "
                "padding-left: 4px; padding-right: 4px; }")
        except Exception:
            pass

    def _go_spin_page(self):
        """Enter no campo da página: pula p/ a página digitada."""
        if getattr(self, "_syncing_page", False) or self._busy_search:
            return
        try:
            v = int(self.spin_page.get_text().strip())
        except Exception:
            v = self.page
        v = max(1, min(int(v), max(1, self.last_page)))
        if v == self.page:
            self._syncing_page = True
            try:
                self.spin_page.set_text(str(self.page))
            finally:
                self._syncing_page = False
            return
        self.search(v)

    def search(self, page: int):
        if self._busy_search:
            return
        page = max(1, page)
        if self.last_page and page > self.last_page:
            return
        if page == 1:
            self.seed = ""  # nova busca: seed fresco do random
        self._busy_search = True
        self.btn_dl.set_sensitive(False)
        self.btn_full.set_sensitive(False)
        self.btn_queue.set_sensitive(False)
        self._tags_gen += 1
        self._listing_gen += 1  # thumbs velhos param de baixar
        self._clear_chips()
        self.right.set_visible(False)
        self._set_left_status(tr("searching"))
        self.lbl_count.set_text("")
        params = self._params(page)
        _run_bg(lambda: self._do_search(params))

    def _do_search(self, params: dict):
        try:
            res = wh.search(**params)
            GLib.idle_add(self._show_results, res, None)
        except Exception as e:
            GLib.idle_add(self._show_results, None, str(e))

    def _show_results(self, res, err):
        self._busy_search = False
        if err or res is None:
            self._set_left_status(tr("error", e=err))
            self.lbl_count.set_text("")
            self.right.set_visible(False)
            return
        self.items = res["items"]
        self.page = res["page"]
        self.last_page = res["last_page"]
        if res.get("seed"):
            self.seed = res["seed"]  # fixa o embaralhamento entre páginas
        self._syncing_page = True
        try:
            self._apply_page_width(self.last_page)
            self.spin_page.set_text(str(self.page))
            self.lbl_suf.set_text(tr("page_suf", l=self.last_page, t=res["total"]))
        finally:
            self._syncing_page = False
        self.btn_prev.set_sensitive(self.page > 1)
        self.btn_next.set_sensitive(self.page < self.last_page)
        self._rebuilding = True  # limpeza/inserção não devem disparar seleção
        self.selected = None
        self.btn_dl.set_sensitive(False)
        self.btn_full.set_sensitive(False)
        self.btn_queue.set_sensitive(False)
        self._tags_gen += 1
        self._clear_chips()
        self.right.set_visible(False)
        self._rebuilding = False
        if not self.items:
            if self.page > 1:
                # filtro restrito esvaziou a página atual: recomeça da 1
                self.search(1)
                return
            self._set_left_status(tr("no_results"))
            self.lbl_count.set_text("")
            return
        self._render_flow()

    def _owned_path(self, it: dict):
        """Destino local do item na pasta configurada, ou None."""
        try:
            folder = (self._get_config().get("folder", "") or "").strip()
            if not folder or not it.get("full"):
                return None
            return Path(folder) / wh.filename_for(it.get("id", ""), it["full"])
        except Exception:
            return None

    def _is_owned(self, it: dict) -> bool:
        try:
            p = self._owned_path(it)
            return p is not None and p.is_file() and p.stat().st_size > 0
        except Exception:
            return False

    def _visible_items(self) -> list[dict]:
        try:
            hide = self.chk_owned.get_active()
        except Exception:
            hide = False
        if not hide:
            return list(self.items)
        return [it for it in self.items if not self._is_owned(it)]

    def _render_flow(self):
        """Reconstrói a grade da listagem atual (respeita ocultar-baixados)."""
        self._rebuilding = True
        try:
            child = self.flow.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                self.flow.remove(child)
                child = nxt
        finally:
            self._rebuilding = False
        vis = self._visible_items()
        if not vis:
            self._set_left_status(tr("no_results"))
            self.lbl_count.set_text("")
            return
        self._set_left_status("")
        self.lbl_count.set_text(tr("n_page", n=len(vis)))
        for it in vis:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            over = Gtk.Overlay()
            ph = Gtk.Image.new_from_icon_name("image-loading")
            ph.set_pixel_size(48)
            ph.set_size_request(220, 150)
            over.set_child(ph)
            badge = Gtk.Label(label="✓")
            badge.add_css_class("wh-owned")
            badge.set_halign(Gtk.Align.START)
            badge.set_valign(Gtk.Align.START)
            badge.set_margin_start(4)
            badge.set_margin_top(4)
            badge.set_tooltip_text(tr("owned_tip"))
            badge.set_visible(False)
            over.add_overlay(badge)
            box.append(over)
            name = Gtk.Label(label=f"{it['id']} • {it['resolution']}")
            name.set_ellipsize(3)
            box.append(name)
            box._wh_item = it
            box._wh_badge = badge
            self.flow.insert(box, -1)
        _run_bg(self._load_thumbs)

    def _mark_owned(self, item_id: str):
        """Selo ✓ imediato (ou some a fileira se o filtro owned ativo)."""
        try:
            hide = self.chk_owned.get_active()
        except Exception:
            hide = False
        child = self.flow.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            inner = child.get_child()
            it = getattr(inner, "_wh_item", None)
            if it and it.get("id") == item_id:
                if hide:
                    self._rebuilding = True
                    try:
                        self.flow.remove(child)
                    finally:
                        self._rebuilding = False
                    vis = self._visible_items()
                    if vis:
                        self.lbl_count.set_text(tr("n_page", n=len(vis)))
                    else:
                        self._set_left_status(tr("no_results"))
                        self.lbl_count.set_text("")
                else:
                    badge = getattr(inner, "_wh_badge", None)
                    if badge is not None:
                        try:
                            badge.set_visible(True)
                        except Exception:
                            pass
                break
            child = nxt

    def _load_thumbs(self):
        scale = max(1, self.flow.get_scale_factor())
        gen = self._listing_gen
        items = self._visible_items()
        for it in items:
            if gen != self._listing_gen:
                return  # listagem trocou: aborta sem gastar rate
            try:
                dest = CACHE_DIR / f"{it['id']}-small.jpg"
                if not dest.is_file() or dest.stat().st_size == 0:
                    data, _total = wh.fetch_bytes(it["thumb"])
                    dest.write_bytes(data)
                    wh.enforce_cache_limit(str(CACHE_DIR))
                px = wp.fit_pixbuf(str(dest), 220 * scale, 150 * scale)
                GLib.idle_add(self._set_thumb, it["id"], px, None)
            except Exception as e:
                GLib.idle_add(self._set_thumb, it["id"], None, str(e))

    def _set_thumb(self, item_id: str, px, _err):
        child = self.flow.get_first_child()
        while child:
            inner = child.get_child()
            it = getattr(inner, "_wh_item", None)
            if it and it["id"] == item_id:
                over = inner.get_first_child()
                if isinstance(over, Gtk.Overlay):
                    if px is not None:
                        pic = Gtk.Picture.new_for_pixbuf(px)
                        pic.set_content_fit(Gtk.ContentFit.CONTAIN)
                        pic.set_halign(Gtk.Align.CENTER)
                        pic.set_valign(Gtk.Align.START)
                        pic.set_can_shrink(True)
                        pic.set_size_request(THUMB_W, THUMB_H)
                        over.set_child(pic)
                    badge = getattr(inner, "_wh_badge", None)
                    if badge is not None:
                        try:
                            badge.set_visible(self._is_owned(it))
                        except Exception:
                            pass
                elif px is not None:
                    old = inner.get_first_child()
                    pic = Gtk.Picture.new_for_pixbuf(px)
                    pic.set_content_fit(Gtk.ContentFit.CONTAIN)
                    pic.set_halign(Gtk.Align.CENTER)
                    pic.set_valign(Gtk.Align.START)
                    pic.set_can_shrink(True)
                    pic.set_size_request(THUMB_W, THUMB_H)
                    inner.remove(old)
                    inner.prepend(pic)
                break
            child = child.get_next_sibling()
        return False

    # ---- seleção + download ----
    def _find_item(self, flow) -> dict | None:
        sel = flow.get_selected_children()
        if not sel:
            return None
        return getattr(sel[0].get_child(), "_wh_item", None)

    def on_select(self, flow):
        if self._rebuilding:
            return
        it = self._find_item(flow)
        if not it:
            self._hide_preview()
            return
        self.selected = it
        size = f"{it['file_size'] // 1024} KB" if it["file_size"] else "?"
        self.info.set_text(f"{it['id']}\n{it['resolution']} • {it['category']} • {size}")
        self.btn_dl.set_sensitive(True)
        self.btn_full.set_sensitive(True)
        if not self._queue_busy:
            self.btn_queue.set_label(tr("queue_page"))
            self.btn_queue.set_sensitive(True)
        self.right.set_visible(True)
        try:
            self.content.set_position(710)
        except Exception:
            pass
        self.preview.set_filename(None)
        _run_bg(lambda: self._load_preview(it))
        self._tags_gen += 1
        gen = self._tags_gen
        self._clear_chips()
        cached = self._tags_cache.get(it.get("id", ""))
        if cached is not None:
            self._show_chips(cached)
        else:
            _run_bg(lambda: self._load_tags(it.get("id", ""), gen))

    def on_fullscreen(self, _btn):
        if not self.selected:
            return
        try:
            if self._full_win is not None:
                self._full_win.destroy()
        except Exception:
            pass
        self._full_win = None
        self._full_win = FullscreenWindow(self, self.selected)
        self._full_win.connect("close-request", self._on_full_closed)
        self._full_win.present()

    def _on_full_closed(self, _win):
        self._full_win = None
        return False

    def on_close_preview(self, _btn):
        self._rebuilding = True
        try:
            self.flow.unselect_all()
        except Exception:
            pass
        finally:
            self._rebuilding = False
        self._hide_preview()

    def _load_preview(self, it: dict):
        wid = it.get("id", "")
        try:
            # original (inteira) em vez da large (o site corta as thumbs p/ 16:9)
            dest = CACHE_DIR / f"{it['id']}-orig.jpg"
            if not dest.is_file() or dest.stat().st_size == 0:
                data, _total = wh.fetch_bytes(it.get("thumb_original") or it["thumb_large"]
                                             or it["thumb"])
                dest.write_bytes(data)
                wh.enforce_cache_limit(str(CACHE_DIR))
            GLib.idle_add(self._preview_done, wid, str(dest), None)
        except Exception as e:
            GLib.idle_add(self._preview_done, wid, None, str(e))

    def _preview_done(self, wid: str, path, err):
        sel = self.selected if isinstance(self.selected, dict) else None
        if sel is None or sel.get("id") != wid:
            return False  # seleção trocou: descarta preview velho
        if err:
            self.status.set_text(tr("preview_fail", e=err))
        elif path:
            try:
                self.preview.set_filename(path)
            except Exception as e:
                self.status.set_text(tr("preview_fail", e=e))
        return False

    def on_download(self, _btn):
        if not self.selected or self._busy_dl or self._queue_busy:
            return
        it = self.selected
        cfg = self._get_config()
        folder = cfg.get("folder", "")
        if not folder:
            self.status.set_text(tr("no_folder"))
            return
        dest = str(Path(folder) / wh.filename_for(it["id"], it["full"]))
        if Path(dest).is_file() and Path(dest).stat().st_size > 0:
            self.status.set_text(tr("already", name=Path(dest).name))
            try:
                self._on_downloaded()
            except Exception:
                pass
            return
        self._busy_dl = True
        self.btn_dl.set_sensitive(False)
        self.progress.set_visible(True)
        self.progress.set_fraction(0.0)
        self.progress.set_text(tr("downloading"))
        _run_bg(lambda: self._do_download(it["full"], dest, it["id"]))

    def _do_download(self, url: str, dest: str, wid: str = ""):
        try:
            def prog(done: int, total: int):
                if total > 0:
                    frac = min(1.0, done / total)
                    GLib.idle_add(lambda: (self.progress.set_fraction(frac),
                                           self.progress.set_text(f"{done // 1024} / {total // 1024} KB"),
                                           False)[-1])
            wh.download(url, dest, progress=prog)
            GLib.idle_add(self._download_done, dest, None, wid)
        except Exception as e:
            GLib.idle_add(self._download_done, dest, str(e), wid)

    def _download_done(self, dest: str, err, wid: str = ""):
        self._busy_dl = False
        self.progress.set_visible(False)
        self.btn_dl.set_sensitive(True)
        if err:
            self.status.set_text(tr("dl_fail", e=err))
        else:
            self.status.set_text(tr("downloaded", name=Path(dest).name))
            if wid:
                self._mark_owned(wid)
            try:
                self._on_downloaded()
            except Exception:
                pass
        return False

    # ---- fila: baixar página ----
    def on_queue(self, _btn):
        if self._queue_busy:
            self._queue_cancel = True
            return
        if self._busy_dl:
            return
        cfg = self._get_config()
        folder = (cfg.get("folder", "") or "").strip()
        if not folder:
            self.status.set_text(tr("no_folder"))
            return
        items = [it for it in self._visible_items() if not self._is_owned(it)]
        if not items:
            self.status.set_text(tr("queue_empty"))
            return
        self._queue = items
        self._queue_total = len(items)
        self._queue_busy = True
        self._queue_cancel = False
        self.btn_queue.set_label(tr("cancel"))
        self.btn_dl.set_sensitive(False)
        self.progress.set_visible(True)
        self.progress.set_fraction(0.0)
        _run_bg(self._run_queue)

    def _run_queue(self):
        folder = (self._get_config().get("folder", "") or "").strip()
        total = self._queue_total
        done = 0
        for it in list(self._queue):
            if self._queue_cancel:
                break
            if self._is_owned(it):
                done += 1
                continue
            dest = str(Path(folder) / wh.filename_for(it["id"], it["full"]))
            idx = done + 1
            name = Path(dest).name

            def prog(feito: int, total_b: int, _idx=idx, _name=name):
                if total_b > 0:
                    frac = ((_idx - 1) + min(1.0, feito / total_b)) / max(1, total)
                    GLib.idle_add(lambda: (self.progress.set_fraction(frac),
                                           self.progress.set_text(f"{_idx}/{total} • {_name}"),
                                           False)[-1])
            try:
                wh.download(it["full"], dest, progress=prog)
                done += 1
                GLib.idle_add(self._queue_item_done, it["id"], None)
            except wh._RateLimited as e:
                GLib.idle_add(self._queue_item_done, it["id"], str(e))
                break
            except Exception as e:
                GLib.idle_add(self._queue_item_done, it["id"], str(e))
        GLib.idle_add(self._queue_finished, done, total, self._queue_cancel)

    def _queue_item_done(self, wid: str, err):
        if err:
            self.status.set_text(tr("dl_fail", e=err))
        elif wid:
            self._mark_owned(wid)
        return False

    def _queue_finished(self, done: int, total: int, canceled: bool):
        self._queue_busy = False
        self._queue_cancel = False
        self._queue = []
        self.progress.set_visible(False)
        self.btn_queue.set_label(tr("queue_page"))
        self.btn_queue.set_sensitive(True)
        self.btn_dl.set_sensitive(bool(self.selected))
        if canceled:
            self.status.set_text(tr("queue_canceled", d=done, n=total))
        else:
            self.status.set_text(tr("queue_done", d=done, n=total))
        try:
            self._on_downloaded()
        except Exception:
            pass
        return False
