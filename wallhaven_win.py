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
        self.lbl_page = Gtk.Label(label=tr("page_lbl", p=1, l=1, t=0))
        self.btn_next = Gtk.Button(label=tr("page_next"))
        self.btn_next.connect("clicked", lambda _b: self.search(self.page + 1))
        nav.append(self.btn_prev)
        nav.append(self.lbl_page)
        nav.append(self.btn_next)
        left.append(nav)
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
        right.append(frame)
        self.info = Gtk.Label(label=tr("sel_hint"))
        self.info.set_wrap(True)
        self.info.set_xalign(0)
        right.append(self.info)
        self.btn_dl = Gtk.Button(label=tr("download"))
        self.btn_dl.add_css_class("suggested-action")
        self.btn_dl.set_sensitive(False)
        self.btn_dl.connect("clicked", self.on_download)
        right.append(self.btn_dl)
        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        self.progress.set_visible(False)
        right.append(self.progress)
        self.status = Gtk.Label(label="")
        self.status.set_wrap(True)
        self.status.set_xalign(0)
        right.append(self.status)
        content.set_end_child(right)

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _run_bg(lambda: wh.enforce_cache_limit(str(CACHE_DIR)))  # poda inicial de 50 MB
        self.search(1)

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
        self.status.set_text(tr("searching"))
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
            self.status.set_text(tr("error", e=err))
            return
        self.items = res["items"]
        self.page = res["page"]
        self.last_page = res["last_page"]
        if res.get("seed"):
            self.seed = res["seed"]  # fixa o embaralhamento entre páginas
        self.lbl_page.set_text(tr("page_lbl", p=res["page"], l=res["last_page"], t=res["total"]))
        self.btn_prev.set_sensitive(self.page > 1)
        self.btn_next.set_sensitive(self.page < self.last_page)
        self._rebuilding = True  # limpeza/inserção não devem disparar seleção
        self.selected = None
        self.btn_dl.set_sensitive(False)
        child = self.flow.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.flow.remove(child)
            child = nxt
        self._rebuilding = False
        if not self.items:
            if self.page > 1:
                # filtro restrito esvaziou a página atual: recomeça da 1
                self.search(1)
                return
            self.status.set_text(tr("no_results"))
            return
        self.status.set_text(tr("n_results", n=len(self.items)))
        for it in self.items:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            ph = Gtk.Image.new_from_icon_name("image-loading")
            ph.set_pixel_size(48)
            ph.set_size_request(220, 150)
            box.append(ph)
            name = Gtk.Label(label=f"{it['id']} • {it['resolution']}")
            name.set_ellipsize(3)
            box.append(name)
            box._wh_item = it
            self.flow.insert(box, -1)
        _run_bg(self._load_thumbs)

    def _load_thumbs(self):
        scale = max(1, self.flow.get_scale_factor())
        for it in self.items:
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
                old = inner.get_first_child()
                if px is not None:
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
            return
        self.selected = it
        size = f"{it['file_size'] // 1024} KB" if it["file_size"] else "?"
        self.info.set_text(f"{it['id']}\n{it['resolution']} • {it['category']} • {size}")
        self.btn_dl.set_sensitive(True)
        self.preview.set_filename(None)
        _run_bg(lambda: self._load_preview(it))

    def _load_preview(self, it: dict):
        try:
            # original (inteira) em vez da large (o site corta as thumbs p/ 16:9)
            dest = CACHE_DIR / f"{it['id']}-orig.jpg"
            if not dest.is_file() or dest.stat().st_size == 0:
                data, _total = wh.fetch_bytes(it.get("thumb_original") or it["thumb_large"]
                                             or it["thumb"])
                dest.write_bytes(data)
                wh.enforce_cache_limit(str(CACHE_DIR))
                wh.enforce_cache_limit(str(CACHE_DIR))
            GLib.idle_add(lambda: (self.preview.set_filename(str(dest)), False)[1])
        except Exception as e:
            GLib.idle_add(lambda: (self.status.set_text(tr("preview_fail", e=e)), False)[1])

    def on_download(self, _btn):
        if not self.selected or self._busy_dl:
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
        _run_bg(lambda: self._do_download(it["full"], dest))

    def _do_download(self, url: str, dest: str):
        try:
            def prog(done: int, total: int):
                if total > 0:
                    frac = min(1.0, done / total)
                    GLib.idle_add(lambda: (self.progress.set_fraction(frac),
                                           self.progress.set_text(f"{done // 1024} / {total // 1024} KB"),
                                           False)[-1])
            wh.download(url, dest, progress=prog)
            GLib.idle_add(self._download_done, dest, None)
        except Exception as e:
            GLib.idle_add(self._download_done, dest, str(e))

    def _download_done(self, dest: str, err):
        self._busy_dl = False
        self.progress.set_visible(False)
        self.btn_dl.set_sensitive(True)
        if err:
            self.status.set_text(tr("dl_fail", e=err))
        else:
            self.status.set_text(tr("downloaded", name=Path(dest).name))
            try:
                self._on_downloaded()
            except Exception:
                pass
        return False
