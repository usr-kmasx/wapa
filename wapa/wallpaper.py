"""Lógica de wallpaper GNOME — só usa stdlib + Gio (já instalado)."""
import json
import random
from pathlib import Path
from urllib.parse import quote
from urllib.request import url2pathname
from urllib.parse import urlparse

try:
    import gi
    gi.require_version("Gio", "2.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gio, GdkPixbuf
    _HAS_GIO = True
except Exception:
    _HAS_GIO = False
    GdkPixbuf = None

BACKGROUND_SCHEMA = "org.gnome.desktop.background"
VALID_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".svg", ".tif", ".tiff"}
VALID_OPTIONS = ["none", "wallpaper", "centered", "scaled", "stretched", "zoom", "spanned"]


def list_images(folder: str) -> list[str]:
    p = Path(folder).expanduser()
    if not p.is_dir():
        return []
    out = []
    for f in sorted(p.iterdir()):
        if f.is_file() and f.suffix.lower() in VALID_EXTS:
            out.append(str(f))
    return out


def to_file_uri(path: str) -> str:
    p = Path(path).expanduser().resolve()
    # quote preserva / mas escapa espaço, acentos etc.
    return "file://" + quote(str(p), safe="/")


def from_file_uri(uri: str) -> str:
    uri = uri.strip().strip("'\"")
    if uri.startswith("file://"):
        parsed = urlparse(uri)
        return url2pathname(parsed.path)  # já decodifica %XX sozinho
    return uri


def _settings():
    if not _HAS_GIO:
        raise RuntimeError("PyGObject (gi) não disponível")
    return Gio.Settings.new(BACKGROUND_SCHEMA)


def get_current() -> dict:
    s = _settings()
    return {
        "picture-uri": s.get_string("picture-uri"),
        "picture-uri-dark": s.get_string("picture-uri-dark"),
        "picture-options": s.get_string("picture-options"),
    }


def set_wallpaper(path: str, mode: str = "both", options: str | None = None) -> dict:
    """mode: 'light' | 'dark' | 'both'. Retorna estado final."""
    if mode not in ("light", "dark", "both"):
        raise ValueError("mode deve ser light, dark ou both")
    if options is not None and options not in VALID_OPTIONS:
        raise ValueError(f"options inválido: {options}")
    if not Path(path).expanduser().is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    uri = to_file_uri(path)
    s = _settings()
    if options is not None:
        s.set_string("picture-options", options)
    if mode in ("light", "both"):
        s.set_string("picture-uri", uri)
    if mode in ("dark", "both"):
        s.set_string("picture-uri-dark", uri)
    Gio.Settings.sync()
    return get_current()


def set_options(options: str) -> dict:
    """Troca só o ajuste (zoom, fill...) sem mexer nas imagens. Retorna estado final."""
    if options not in VALID_OPTIONS:
        raise ValueError(f"options inválido: {options}")
    s = _settings()
    s.set_string("picture-options", options)
    Gio.Settings.sync()
    return get_current()


def current_path() -> str | None:
    """Caminho do wallpaper atual (modo claro), ou None se não for arquivo local."""
    uri = get_current()["picture-uri"]
    p = from_file_uri(uri)
    return p if Path(p).is_file() else None


def _ordered(folder: str) -> list[str]:
    images = list_images(folder)
    if not images:
        raise FileNotFoundError(f"Nenhuma imagem em: {folder}")
    return images


def step(folder: str, direction: int = 1, mode: str = "both",
         options: str | None = None) -> str:
    """Aplica próxima (+1) ou anterior (-1) imagem em relação à atual. Retorna o caminho."""
    images = _ordered(folder)
    cur = current_path()
    try:
        idx = images.index(cur) if cur else None
    except ValueError:
        idx = None
    if idx is None:
        nxt = images[0] if direction >= 0 else images[-1]
    else:
        nxt = images[(idx + direction) % len(images)]
    set_wallpaper(nxt, mode=mode, options=options)
    return nxt


def random_wallpaper(folder: str, mode: str = "both",
                     options: str | None = None,
                     state_file: str | None = None) -> str:
    """Aleatório sem repetir: embaralha todas e só repete após exibir cada uma.

    state_file guarda a fila restante entre execuções. Retorna o caminho aplicado.
    """
    images = _ordered(folder)
    remaining: list[str] = []
    if state_file:
        try:
            saved = json.loads(Path(state_file).read_text(encoding="utf-8"))
            have = set(images)
            remaining = [p for p in saved if p in have] if isinstance(saved, list) else []
        except (OSError, ValueError, TypeError):
            remaining = []
    # incorpora fotos novas (da pasta) que ainda não estão na fila
    unseen = [p for p in images if p not in set(remaining)]
    random.shuffle(unseen)
    remaining += unseen
    # evita repetir a atual em sequência quando houver alternativa
    cur = current_path()
    if len(remaining) > 1 and remaining[0] == cur:
        for i in range(1, len(remaining)):
            if remaining[i] != cur:
                remaining[0], remaining[i] = remaining[i], remaining[0]
                break
    pick = remaining.pop(0)
    if state_file:
        try:
            Path(state_file).write_text(json.dumps(remaining), encoding="utf-8")
        except OSError:
            pass
    set_wallpaper(pick, mode=mode, options=options)
    return pick


def fit_pixbuf(path: str, maxw: int, maxh: int):
    """Reduz a imagem para caber INTEIRA em maxw x maxh (sem cortar)."""
    if GdkPixbuf is None:
        raise RuntimeError("GdkPixbuf não disponível")
    src = GdkPixbuf.Pixbuf.new_from_file(path)
    w, h = src.get_width(), src.get_height()
    s = min(1.0, maxw / w, maxh / h)
    if s >= 1.0:
        return src
    return src.scale_simple(max(1, int(w * s)), max(1, int(h * s)),
                           GdkPixbuf.InterpType.BILINEAR) or src
