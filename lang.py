"""Textos do wapa em PT-BR e EN-US — só stdlib, sem gettext."""

STRINGS = {
    "pt_BR": {
        # janela principal
        "change_folder": "Trocar pasta",
        "select_image": "Selecione uma imagem",
        "no_images": "Nenhuma imagem em:\n{folder}",
        "hint_folder": "Dica: coloque JPG/PNG/WebP nessa pasta.",
        "found": "{n} imagens encontradas.",
        "adjust": "Ajuste:",
        "mode_label": "Aplicar em:",
        "mode_both": "Ambos",
        "mode_light": "Claro",
        "mode_dark": "Escuro",
        "apply": "Aplicar wallpaper",
        "select_first": "Selecione uma imagem primeiro.",
        "applied": "Aplicado em {mode}: {name}",
        "applied_both": "claro + escuro",
        "applied_light": "claro",
        "applied_dark": "escuro",
        "applied_opt": "Ajuste aplicado: {opt}",
        "error": "Erro: {e}",
        "pick_folder_title": "Escolher pasta de wallpapers",
        "cancel": "Cancelar",
        "choose": "Escolher",
        "trash_tip": "Apagar (Shift+clique apaga direto)",
        "delete_title": "Apagar wallpaper?",
        "delete_body": '"{name}" será apagado para sempre.',
        "delete_btn": "Apagar",
        "deleted": "Apagado: {name}",
        "deleted_current": " — era o atual, apliquei: {name}",
        "deleted_empty": " — pasta ficou vazia ou falhou: {e}",
        "not_deleted": "Não apagou: {e}",
        "lang_btn": "Idioma",
        # tray
        "open": "Abrir wapa",
        "next": "Próximo wallpaper",
        "prev": "Wallpaper anterior",
        "random": "Wallpaper aleatório",
        "quit": "Sair",
        # wallhaven
        "search_ph": "Buscar… ex: mountains +lake -people @user like:abc123 type:jpg",
        "search_tip": ("Avançado: +tag exige, -tag exclui, @user filtra autor, "
                       "like:id acha similares, type:jpg/png filtra tipo"),
        "search_btn": "Buscar",
        "sort_label": "Ordem:",
        "desc": "Decrescente",
        "res_exact": "Res. exata:",
        "res_min": "Res. mínima:",
        "res_min_tip": "No mínimo esta resolução (atleast)",
        "ratio": "Prop.:",
        "color": "Cor:",
        "top": "Top:",
        "adv": "Filtros avançados",
        "any": "Qualquer",
        "swatch_tip": "#{hx} (clique de novo p/ limpar)",
        "page_prev": "◀ Anterior",
        "page_next": "Próxima ▶",
        "page_lbl": "Página {p} de {l} ({t} resultados)",
        "sel_hint": "Busque e clique numa imagem",
        "download": "Baixar para minha pasta",
        "no_results": "Nada encontrado — ajuste busca/filtros.",
        "n_results": "{n} resultados.",
        "searching": "Buscando…",
        "no_folder": "Defina a pasta de wallpapers na janela principal.",
        "downloading": "Baixando…",
        "downloaded": "Baixado: {name}",
        "already": "Já baixado: {name}",
        "dl_fail": "Download falhou: {e}",
        "preview_fail": "Preview falhou: {e}",
    },
    "en_US": {
        # main window
        "change_folder": "Change folder",
        "select_image": "Select an image",
        "no_images": "No images in:\n{folder}",
        "hint_folder": "Tip: put JPG/PNG/WebP in that folder.",
        "found": "{n} images found.",
        "adjust": "Fit:",
        "mode_label": "Apply to:",
        "mode_both": "Both",
        "mode_light": "Light",
        "mode_dark": "Dark",
        "apply": "Apply wallpaper",
        "select_first": "Select an image first.",
        "applied": "Applied to {mode}: {name}",
        "applied_both": "light + dark",
        "applied_light": "light",
        "applied_dark": "dark",
        "applied_opt": "Fit applied: {opt}",
        "error": "Error: {e}",
        "pick_folder_title": "Choose wallpapers folder",
        "cancel": "Cancel",
        "choose": "Choose",
        "trash_tip": "Delete (Shift+click deletes directly)",
        "delete_title": "Delete wallpaper?",
        "delete_body": '"{name}" will be deleted forever.',
        "delete_btn": "Delete",
        "deleted": "Deleted: {name}",
        "deleted_current": " — it was current, applied: {name}",
        "deleted_empty": " — folder empty or failed: {e}",
        "not_deleted": "Could not delete: {e}",
        "lang_btn": "Language",
        # tray
        "open": "Open wapa",
        "next": "Next wallpaper",
        "prev": "Previous wallpaper",
        "random": "Random wallpaper",
        "quit": "Quit",
        # wallhaven
        "search_ph": "Search… e.g.: mountains +lake -people @user like:abc123 type:jpg",
        "search_tip": ("Advanced: +tag requires, -tag excludes, @user filters author, "
                       "like:id finds similar, type:jpg/png filters type"),
        "search_btn": "Search",
        "sort_label": "Sort:",
        "desc": "Descending",
        "res_exact": "Exact res.:",
        "res_min": "Min res.:",
        "res_min_tip": "At least this resolution (atleast)",
        "ratio": "Ratio:",
        "color": "Color:",
        "top": "Top:",
        "adv": "Advanced filters",
        "any": "Any",
        "swatch_tip": "#{hx} (click again to clear)",
        "page_prev": "◀ Previous",
        "page_next": "Next ▶",
        "page_lbl": "Page {p} of {l} ({t} results)",
        "sel_hint": "Search and click an image",
        "download": "Download to my folder",
        "no_results": "Nothing found — adjust search/filters.",
        "n_results": "{n} results.",
        "searching": "Searching…",
        "no_folder": "Set the wallpapers folder in the main window.",
        "downloading": "Downloading…",
        "downloaded": "Downloaded: {name}",
        "already": "Already downloaded: {name}",
        "dl_fail": "Download failed: {e}",
        "preview_fail": "Preview failed: {e}",
    },
}

_current = "pt_BR"


def set_lang(code: str) -> str:
    """Define o idioma atual. Retorna o código efetivo."""
    global _current
    _current = code if code in STRINGS else "pt_BR"
    return _current


def get_lang() -> str:
    return _current


def tr(key: str, **kw) -> str:
    """Texto traduzido; formata {placeholders} se dados."""
    s = STRINGS.get(_current, {}).get(key, STRINGS["pt_BR"].get(key, key))
    return s.format(**kw) if kw else s
