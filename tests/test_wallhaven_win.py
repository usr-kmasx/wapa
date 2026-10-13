#!/usr/bin/env python3
"""Teste antecipado (test-ahead) da janela Wallhaven — sem mostrar UI, sem rede.

Cobre as regressões recentes: preview que não abre, seleção perdida no reflow,
grade que não desce para 1 coluna, +N removido.

Uso:  python3 tests/test_wallhaven_win.py   (a partir de wapa/)
Requer display (usa o DISPLAY atual); nada é apresentado na tela.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gtk, GLib, GdkPixbuf

import wallhaven_win
import wallpaper as wp
import wallhaven as wh

TMP = tempfile.mkdtemp(prefix="wapa-test-")
ITEMS = [{
    "id": f"w{i}",
    "resolution": "1920x1080",
    "file_size": 1024,
    "full": f"http://x/w{i}.jpg",
    "thumb": f"http://x/w{i}-s.jpg",
    "thumb_large": f"http://x/w{i}-l.jpg",
    "thumb_original": f"http://x/w{i}-o.jpg",
    "category": "general",
    "purity": "SFW",
} for i in range(1, 7)]
TAGS = [{"id": i, "name": f"tag{i}"} for i in range(9)]

# rede simulada + thumb simulado (pixbuf real, sem arquivos)
wh.search = lambda **kw: {"items": list(ITEMS), "page": 1, "last_page": 3,
                          "total": 72, "seed": ""}
wh.details = lambda wid: {"id": wid, "tags": list(TAGS)}
wh.fetch_bytes = lambda url, timeout=25: (b"x" * 100, 100)
wp.fit_pixbuf = lambda path, w, h: GdkPixbuf.Pixbuf.new(
    GdkPixbuf.Colorspace.RGB, True, 8, 8, 8)
wallhaven_win.CACHE_DIR = __import__("pathlib").Path(TMP)
wallhaven_win._run_bg = lambda fn: fn()  # síncrono: determinístico


def pump(cap=2000):
    ctx = GLib.MainContext.default()
    for _ in range(cap):
        if not ctx.pending():
            break
        ctx.iteration(False)


def children(flow):
    out, c = [], flow.get_first_child()
    while c:
        out.append(c)
        c = c.get_next_sibling()
    return out


def is_shown(pic):
    """True se o Picture tem algo exibido (paintable presente)."""
    try:
        return pic.get_paintable() is not None
    except Exception:
        return False


PASS = []


def check(name, cond):
    PASS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        raise SystemExit(f"teste falhou: {name}")


app = Adw.Application(application_id="test.wapa")
win = wallhaven_win.WallhavenWindow(
    app, lambda: {"folder": TMP, "picture-options": "zoom"}, lambda: None)
pump()
check("busca inicial lista 6 itens", len(children(win.flow)) == 6)

# S1: seleciona -> preview abre com o original + todas as tags, sem +N
first = win.flow.get_first_child()
win.flow.select_child(first)
pump()
check("preview abre (painel visível)", win.right.get_visible())
fn = os.path.join(TMP, "w1-orig.jpg")
check("preview mostra o original",
      is_shown(win.preview) and os.path.isfile(fn))
labels = [c.get_child().get_label() for c in children(win.tags_flow)]
check("todas as 9 tags, sem +N",
      len(labels) == 9 and not any(str(x).startswith("+") for x in labels))
sel_id = win.selected["id"]

# S3: desseleção transitória (reflow) mantém o preview e restaura a seleção
win.flow.unselect_all()
check("transitório não fecha o preview", win.right.get_visible())
restored = win.flow.get_selected_children()
check("seleção restaurada no mesmo item",
      len(restored) == 1 and restored[0].get_child()._wh_item["id"] == sel_id)
pump()
check("preview segue aberto após idle", win.right.get_visible())

# S2: grade dos wallpapers é a original (sem ajuste de colunas dirigido)
check("grade original sem _fit_columns", not hasattr(win, "_fit_columns"))
check("grade original teto 30", win.flow.get_max_children_per_line() == 30)

# S6: matemática da moldura que abraça a foto
PBF = wallhaven_win.WallhavenWindow._preview_box_for
check("caixa quadrada segue a largura", PBF(300, 6666, 6666) == (300, 300))
check("caixa menor que o painel usa a foto", PBF(300, 200, 100) == (200, 100))
check("retrato alto respeita o teto", PBF(300, 400, 800) == (210, 420))
check("foto minúscula respeita o piso", PBF(300, 50, 40) == (120, 80))
check("medidas inválidas -> None",
      PBF(0, 100, 100) is None and PBF(300, 0, 100) is None)
win._preview_done("w1", os.path.join(TMP, "lixo.png"), None)
check("arquivo inválido não quebra nem muda a caixa",
      win._preview_overlay.get_halign() == Gtk.Align.FILL)

# S7b: CSS sem seletor global que apague a marca de seleção das grades
_src = open("wallhaven_win.py", encoding="utf-8").read()
_bare = [ln for ln in _src.splitlines()
         if "flowboxchild" in ln and "tags-flow > flowboxchild" not in ln]
check("sem flowboxchild sem escopo no CSS", not _bare)
win._preview_overlay.set_size_request(500, 420)
mh_wrap = win.right_scroll.measure(Gtk.Orientation.VERTICAL, -1)[0]
mh_inner = win.right.measure(Gtk.Orientation.VERTICAL, -1)[0]
check("scroll do painel absorve a altura", mh_wrap <= 120 < mh_inner)

# S4: desseleção real (item sumiu) esconde
win.items = []
win.flow.unselect_all()
pump()
check("desseleção real esconde o preview", not win.right.get_visible())

print("\n--- auditoria de mínimos (min-larg x min-alt) ---")


def audit(name, w):
    try:
        mw = w.measure(Gtk.Orientation.HORIZONTAL, -1)
        mh = w.measure(Gtk.Orientation.VERTICAL, -1)
        print(f"{name:14s} min {mw[0]:4d}x{mh[0]:4d}  nat {mw[1]:4d}x{mh[1]:4d}")
    except Exception as e:  # noqa: BLE001
        print(f"{name:14s} ERRO {e}")


left = win.content.get_start_child()
kids = []
c = left.get_first_child()
while c:
    kids.append(c)
    c = c.get_next_sibling()
nav_w = kids[1] if len(kids) > 1 else None
for _name, _w in (("window", win), ("content", win.content), ("left", left),
                  ("scrolled", win.scrolled), ("flow", win.flow),
                  ("nav", nav_w), ("right", win.right),
                  ("preview", win.preview),
                  ("overlay", win._preview_overlay),
                  ("tags_scroll", win.tags_scroll),
                  ("tags_flow", win.tags_flow)):
    if _w is not None:
        audit(_name, _w)

print(f"\nOK: {len(PASS)} verificações, pasta {TMP}")
