"""Cliente da API pública do Wallhaven — só stdlib (urllib + json).

SFW não precisa de chave. NSFW exigiria apikey (não usado pelo wapa).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://wallhaven.cc/api/v1"
TIMEOUT = 25
CACHE_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
# a API limita em 45 req/min (HTTP 429)
RETRYABLE_CODES = (429, 500, 502, 503, 504)
RETRY_DELAYS = (1.0, 2.0, 4.0)

SORTINGS = ["relevance", "date_added", "views", "favorites", "toplist", "random"]
RATIO_PRESETS = [
    "16x9", "16x10", "21x9", "32x9", "48x9",
    "9x16", "10x16", "9x18", "1x1", "3x2", "4x3", "5x4",
]
# paleta oficial do site (sem #, minúsculas)
WH_COLORS = [
    "660000", "990000", "cc0000", "cc3333", "ea4c88",
    "993399", "663399", "333399", "0066cc", "0099cc",
    "66cccc", "77cc33", "669900", "336600", "666600",
    "999900", "cccc33", "ffff00", "ffcc33", "ff9900",
    "ff6600", "cc6633", "996633", "663300", "000000",
    "999999", "cccccc", "ffffff", "424153",
]
TOPRANGES = ["1d", "3d", "1w", "1M", "3M", "6M", "1y"]
# presets do site, do menor ao maior (por área)
RESOLUTION_PRESETS = [
    "1280x720", "1280x800", "1280x960", "1280x1024",
    "1600x900", "1600x1000", "1600x1200", "1600x1280",
    "1920x1080", "1920x1200", "1920x1440", "2560x1080",
    "1920x1536", "2560x1440", "2560x1600", "2560x1920",
    "3440x1440", "2560x2048", "3840x1600", "3840x2160",
    "3840x2400", "3840x2880", "3840x3072",
]


class _RateLimited(ConnectionError):
    """429 esgotado após retries — mensagem já traduzida, não reembrulhar."""


def _retry_after(err) -> float | None:
    """Segundos do header Retry-After (teto 30s) ou None."""
    try:
        v = err.headers.get("Retry-After")
        if v is None:
            return None
        return min(30.0, max(0.0, float(str(v).strip())))
    except Exception:
        return None


def _urlopen_with_retry(req, timeout):
    """urlopen com retry em 429/5xx (backoff 1s→2s→4s, honra Retry-After).

    Retorna a resposta aberta. Esgotado o 429, levanta _RateLimited
    (mensagem traduzida); demais falhas, a exceção original.
    """
    last = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            last = e
            if e.code not in RETRYABLE_CODES or attempt >= len(RETRY_DELAYS):
                break
            time.sleep(_retry_after(e) or RETRY_DELAYS[attempt])
        except Exception:
            raise
    if last is not None and getattr(last, "code", None) == 429:
        from lang import tr
        raise _RateLimited(tr("rate_limited")) from last
    raise last


def search(q: str = "", categories: str = "111", sorting: str = "relevance",
           order: str = "desc", page: int = 1, resolutions: str = "",
           atleast: str = "", ratios: str = "", colors: str = "", toprange: str = "",
           seed: str = "") -> dict:
    """Busca wallpapers. Retorna {'items', 'page', 'last_page', 'total', 'seed'}.

    categories: 3 dígitos General/Anime/People, ex '100'. purity sempre 100 (SFW).
    relevance sem texto vira date_added (a API retorna vazio sem query).
    """
    if sorting not in SORTINGS:
        raise ValueError(f"sorting inválido: {sorting}")
    if not q.strip() and sorting == "relevance":
        sorting = "date_added"
    if sorted(categories) and (len(categories) != 3 or set(categories) - set("01")):
        raise ValueError("categories deve ter 3 dígitos 0/1, ex '111'")
    if categories == "000":
        raise ValueError("marque ao menos uma categoria")
    params = {
        "categories": categories,
        "purity": "100",  # SFW travado
        "sorting": sorting,
        "order": order if order in ("desc", "asc") else "desc",
        "page": max(1, int(page)),
    }
    if q.strip():
        params["q"] = q.strip()
    if resolutions.strip():
        params["resolutions"] = resolutions.strip().replace(" ", "")
    if atleast.strip():
        params["atleast"] = atleast.strip().replace(" ", "")
    if ratios.strip():
        params["ratios"] = ratios.strip().replace(" ", "")
    if colors.strip():
        params["colors"] = colors.strip().replace(" ", "").lstrip("#")
    if sorting == "toplist" and toprange in TOPRANGES:
        params["toprange"] = toprange
    if sorting == "random" and seed:
        params["seed"] = seed
    url = API_BASE + "/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "wapa/1.0"})
    try:
        with _urlopen_with_retry(req, timeout=TIMEOUT) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except _RateLimited:
        raise
    except Exception as e:
        raise ConnectionError(f"falha ao falar com wallhaven.cc: {e}") from e
    items = []
    for it in payload.get("data", []):
        thumbs = it.get("thumbs", {})
        items.append({
            "id": it.get("id", ""),
            "resolution": it.get("resolution", ""),
            "file_size": it.get("file_size", 0),
            "full": it.get("path", ""),
            "thumb": thumbs.get("small", ""),
            "thumb_large": thumbs.get("large", ""),
            "thumb_original": thumbs.get("original", ""),
            "category": it.get("category", ""),
            "purity": it.get("purity", ""),
        })
    meta = payload.get("meta", {})
    return {
        "items": items,
        "page": meta.get("current_page", page),
        "last_page": meta.get("last_page", page),
        "total": meta.get("total", 0),
        "seed": meta.get("seed") or "",
    }


def details(wallpaper_id: str) -> dict:
    """Detalhe de um wallpaper: {'id', 'tags': [{'id', 'name'}]}.

    Sem apikey: NSFW bloqueado (wapa é SFW, ok).
    """
    wid = (wallpaper_id or "").strip()
    if not wid:
        raise ValueError("id vazio")
    url = API_BASE + "/w/" + urllib.parse.quote(wid, safe="")
    req = urllib.request.Request(url, headers={"User-Agent": "wapa/1.0"})
    try:
        with _urlopen_with_retry(req, timeout=TIMEOUT) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except _RateLimited:
        raise
    except Exception as e:
        raise ConnectionError(f"falha ao detalhar {wid}: {e}") from e
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    tags = []
    for t in data.get("tags", []) or []:
        if isinstance(t, dict) and t.get("name"):
            tags.append({"id": t.get("id", ""), "name": str(t["name"])})
    return {"id": data.get("id", wid), "tags": tags}


def fetch_bytes(url: str, timeout: int = TIMEOUT) -> tuple[bytes, int]:
    """Baixa URL para memória. Retorna (bytes, total)."""
    req = urllib.request.Request(url, headers={"User-Agent": "wapa/1.0"})
    try:
        with _urlopen_with_retry(req, timeout=timeout) as r:
            total = int(r.headers.get("Content-Length", 0) or 0)
            return r.read(), total
    except _RateLimited:
        raise
    except Exception as e:
        raise ConnectionError(f"falha ao baixar {url}: {e}") from e


def download(url: str, dest_path: str, progress=None,
             timeout: int = 120) -> str:
    """Baixa arquivo com progresso progress(feitos, total). Retorna dest_path.

    Em 429 persistente, recomeça do zero (sem resume), até 3 tentativas.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "wapa/1.0"})
    for attempt in range(3):
        try:
            with _urlopen_with_retry(req, timeout=timeout) as r:
                total = int(r.headers.get("Content-Length", 0) or 0)
                done = 0
                Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            return dest_path
        except _RateLimited:
            try:
                os.unlink(dest_path)
            except OSError:
                pass
            if attempt >= 2:
                raise
        except Exception as e:
            try:
                os.unlink(dest_path)
            except OSError:
                pass
            raise ConnectionError(f"falha ao baixar: {e}") from e
    return dest_path


def filename_for(item_id: str, full_url: str) -> str:
    ext = full_url.rsplit(".", 1)[-1].lower() if "." in full_url else "jpg"
    ext = "".join(c for c in ext if c.isalnum()) or "jpg"
    return f"wallhaven-{item_id}.{ext}"


def enforce_cache_limit(cache_dir: str, max_bytes: int = CACHE_MAX_BYTES) -> int:
    """Apaga os arquivos mais antigos até o cache caber em max_bytes.

    Retorna o total de bytes restante. Silencioso ante erros.
    """
    try:
        files = [p for p in Path(cache_dir).iterdir() if p.is_file()]
    except OSError:
        return 0
    try:
        sizes = {p: p.stat().st_size for p in files}
    except OSError:
        return 0
    total = sum(sizes.values())
    if total <= max_bytes:
        return total
    try:
        by_age = sorted(files, key=lambda p: p.stat().st_mtime)
    except OSError:
        return total
    for p in by_age:
        if total <= max_bytes:
            break
        try:
            p.unlink()
            total -= sizes[p]
        except OSError:
            pass
    return total
