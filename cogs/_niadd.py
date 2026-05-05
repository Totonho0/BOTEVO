"""Cliente de scraping para https://br.niadd.com (PT-BR).

O site nao expoe API publica e a busca padrao do site sempre retorna vazio,
entao trabalhamos por scraping HTML em cima das listagens publicas:

- Catalogo: pagina por `/list/Hot-Manga/N.html` (60 mangas/pagina)
- Detalhes do manga + capitulos: `/manga/<slug>/chapters.html`
- Capitulo: `/chapter/<slug>/<chapter_id>.html` (e `<id>-N.html` para subpaginas)

Imagens vem de `wpimg.yx247.com`. Cada subpagina HTML do capitulo carrega
1 imagem real + previews das proximas; consideramos sempre a 1a imagem do
dominio `wpimg.yx247.com` que aparece no HTML da subpagina.
"""

from __future__ import annotations

import html as html_module
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from typing import Any, Iterable
from urllib.parse import quote, unquote, urljoin, urlparse

import requests


BASE_URL = "https://br.niadd.com"
HOT_MANGA_FIRST = f"{BASE_URL}/list/Hot-Manga/"
HOT_MANGA_PAGE = f"{BASE_URL}/list/Hot-Manga/{{page}}.html"
NEW_UPDATE_FIRST = f"{BASE_URL}/list/New-Update.html"
NEW_UPDATE_PAGE = f"{BASE_URL}/list/New-Update/{{page}}.html"

DEFAULT_TIMEOUT = 25
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": f"{BASE_URL}/",
}


_MANGA_LINK_RE = re.compile(r'href="(https?://br\.niadd\.com/manga/[^"/]+\.html)"', re.IGNORECASE)
_IMG_WITH_ALT_RE = re.compile(
    r'<img[^>]+(?:src|data-src)="(https?://[^"]+)"[^>]*alt="([^"]*)"',
    re.IGNORECASE,
)
_PAGE_IMAGE_RE = re.compile(
    r'(https?://(?:wpimg|img\d+)\.[^\s"\'<>]+\.(?:webp|jpg|jpeg|png))',
    re.IGNORECASE,
)
_CHAPTER_LINK_RE_TEMPLATE = r'href="(/chapter/{slug}[^"]*?/(\d+)/?(?:[^"]*)?)"'


def _http_get(url: str) -> str:
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.text


def _slug_from_manga_url(url: str) -> str:
    match = re.search(r"/manga/([^/]+)\.html", url, re.IGNORECASE)
    if not match:
        return ""
    return unquote(match.group(1))


def _canonical_manga_url(slug_decoded: str) -> str:
    """Slug decodificado (sem %XX) como o site aceita nos detalhes/capitulos."""
    s = (slug_decoded or "").strip()
    return f"{BASE_URL}/manga/{quote(s, safe='-_')}.html"


def _slug_from_chapter_url(url: str) -> str:
    match = re.search(r"/chapter/([^/]+)/", url)
    if not match:
        return ""
    return match.group(1)


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "", flags=re.IGNORECASE | re.DOTALL)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


_SLUG_ENTITY_MAP = {
    "_iacute_": "í",
    "_eacute_": "é",
    "_aacute_": "á",
    "_oacute_": "ó",
    "_uacute_": "ú",
    "_ccedil_": "ç",
    "_atilde_": "ã",
    "_otilde_": "õ",
    "_ntilde_": "ñ",
    "_acirc_": "â",
    "_ecirc_": "ê",
    "_ocirc_": "ô",
    "_aelig_": "æ",
    "_oslash_": "ø",
    "_szlig_": "ß",
}


def _slug_to_title(slug: str) -> str:
    if not slug:
        return "Manga"
    raw = slug.lower()
    for needle, repl in _SLUG_ENTITY_MAP.items():
        raw = raw.replace(needle, repl)
    cleaned = re.sub(r"[_\-]+", " ", raw).strip()
    if not cleaned:
        return "Manga"
    # Title-case, mas mantendo acentos.
    words = []
    for word in cleaned.split(" "):
        if not word:
            continue
        if word.isdigit():
            words.append(word)
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words) or "Manga"


def _absolute(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return urljoin(BASE_URL, url)
    return url


def _build_listing_url(base_first: str, base_page: str, page: int) -> str:
    if page <= 1:
        return base_first
    return base_page.format(page=page)


_TITLE_HREF_RE = re.compile(
    r'<a[^>]*title="([^"]+)"[^>]*href="(https?://br\.niadd\.com/manga/([^"/]+)\.html)"',
    re.IGNORECASE,
)
_HREF_TITLE_RE = re.compile(
    r'<a[^>]*href="(https?://br\.niadd\.com/manga/([^"/]+)\.html)"[^>]*title="([^"]+)"',
    re.IGNORECASE,
)
_IMG_ALT_RE = re.compile(
    r'<img[^>]+(?:src|data-src)="([^"]+)"[^>]*alt="([^"]+)"',
    re.IGNORECASE,
)


def _isolate_main_list(html: str) -> str:
    """Recorta o HTML em `<div class="manga-list">...</div>` para ignorar
    sidebars (que repetem os mesmos populares em todas as paginas)."""
    start_match = re.search(
        r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bmanga-list\b[^"\']*["\']',
        html,
        re.IGNORECASE,
    )
    if not start_match:
        return html
    start = start_match.start()
    # Conta divs balanceadas a partir do match.
    depth = 0
    i = start
    n = len(html)
    while i < n:
        opener = html.find("<div", i)
        closer = html.find("</div", i)
        if closer == -1:
            return html[start:]
        if opener != -1 and opener < closer:
            depth += 1
            i = opener + 4
            continue
        depth -= 1
        i = closer + 5
        if depth == 0:
            return html[start:i]
    return html[start:]


def _parse_listing_page(html: str) -> list[dict[str, Any]]:
    """Extrai cards de manga (titulo, capa, url, slug) de uma pagina de listagem.

    Os cards usam o markup `<div class="manga-item">` contendo
    `<a title="Titulo" href=".../manga/SLUG.html"><img src="..." alt="Titulo">`.
    Como o `title=` do anchor e bem confiavel, usamos ele como fonte primaria
    do titulo e mapeamos a capa pelo `alt` da `<img>`.

    Para evitar pegar itens da sidebar (que repete os mesmos mangas populares em
    todas as paginas), so olhamos para o conteudo dentro de `<div class="manga-list">`.
    """
    main_html = _isolate_main_list(html)

    by_slug: dict[str, dict[str, Any]] = {}

    def _record(slug_encoded: str, _: str, title: str) -> None:
        slug = unquote(slug_encoded or "").strip()
        if not slug:
            return
        url = _canonical_manga_url(slug)
        title = _clean_text(title) or _slug_to_title(slug)
        existing = by_slug.get(slug)
        if existing is None:
            by_slug[slug] = {
                "slug": slug,
                "title": title,
                "url": url,
                "cover_url": "",
            }
            return
        if title and (len(title) > len(existing["title"])):
            existing["title"] = title

    for title, url, slug in _TITLE_HREF_RE.findall(main_html):
        _record(slug, url, title)
    for url, slug, title in _HREF_TITLE_RE.findall(main_html):
        _record(slug, url, title)

    cover_by_alt: dict[str, str] = {}
    for src, alt in _IMG_ALT_RE.findall(main_html):
        clean_alt = _clean_text(alt)
        if clean_alt:
            cover_by_alt.setdefault(clean_alt.lower(), _absolute(src))

    for entry in by_slug.values():
        if entry["cover_url"]:
            continue
        cover = cover_by_alt.get(entry["title"].lower(), "")
        if cover:
            entry["cover_url"] = cover

    return list(by_slug.values())


# Listas e categorias conhecidas do niadd. Sao combinadas em `fetch_catalog`
# com paths descobertos na home/listagens (`_DISCOVERY_HTML_SEEDS`) para
# incluir categorias extras (ex. rotulos em ingles).
_KNOWN_LIST_PATHS = [
    "/list/Hot-Manga/",
    "/list/New-Update.html",
    "/list/New-Manga/",
    "/list/New-Updated/",
]

# Categorias do niadd. Inclui as que aparecem no menu publico do site E
# as que sao acessiveis por URL direta (descobertas testando).
_KNOWN_CATEGORY_PATHS = [
    "/category/Aventura.html",
    "/category/Ação.html",
    "/category/Artes Marciais.html",
    "/category/Comédia.html",
    "/category/Drama.html",
    "/category/Escolar.html",
    "/category/Fantasia.html",
    "/category/Harém.html",
    "/category/Histórico.html",
    "/category/Manhwa.html",
    "/category/Romance.html",
    "/category/Sobrenatural.html",
    "/category/Super poderes.html",
    "/category/Webtoon.html",
    "/category/Demonios.html",
    "/category/Adulto (18+).html",
    "/category/Adulto (YAOI).html",
    # Categorias adicionais (URL direta)
    "/category/Horror.html",
    "/category/Shoujo.html",
    "/category/Colegial.html",
    "/category/Yaoi.html",
    "/category/Yuri.html",
    "/category/Mecha.html",
    "/category/Esportes.html",
    "/category/Mistério.html",
    "/category/Slice of Life.html",
    "/category/Tragédia.html",
    "/category/Sci-fi.html",
    "/category/Psicológico.html",
]


def _discover_extra_paths(html: str) -> list[str]:
    """Descobre listagens/categorias adicionais a partir de uma pagina."""
    paths = re.findall(r'href="(/(?:list|category)/[^"#?]+)"', html)
    return list(dict.fromkeys(paths))


def _listing_path_identity(path: str) -> str:
    """Chave estavel para deduplicar variantes do mesmo indice (ex. `/list/X/`
    vs `/list/X.html`) e evitar desperdicar um `max_sources` com a mesma listagem.
    """
    raw = (path or "").strip()
    if raw.startswith("http"):
        parsed = urlparse(raw)
        if "niadd.com" in (parsed.netloc or "").lower():
            raw = parsed.path or "/"
        else:
            return raw.lower()
    raw = raw.rstrip("/")
    if raw.endswith(".html"):
        raw = raw[:-5]
    return raw.lower()


_DISCOVERY_HTML_SEEDS: tuple[str, ...] = (
    "/",
    "/list/Hot-Manga/",
    "/list/New-Manga/",
)


def _harvest_discovery_paths(extra_html: Iterable[str]) -> list[str]:
    """Uniao ordenada de hrefs `/list/` e `/category/` extraidos de paginas-semilla."""
    out: list[str] = []
    seen: set[str] = set()
    for html in extra_html:
        for p in _discover_extra_paths(html):
            ident = _listing_path_identity(p)
            if ident in seen:
                continue
            if not (p.startswith("/list/") or p.startswith("/category/")):
                continue
            seen.add(ident)
            out.append(p)
    return out


def _absolute_listing_url(path: str) -> str:
    if path.startswith("http"):
        return path
    parts = path.split("/")
    encoded = "/".join(quote(p, safe="-_.~()") if p else p for p in parts)
    return f"{BASE_URL}{encoded}"


def _paginated_path(path: str, page: int) -> str:
    """Niadd usa o sufixo `-N.html` para paginar listagens (ambos `/list/` e
    `/category/`). A pagina 1 e o caminho original; as demais sao geradas
    substituindo `.html` por `-N.html` ou anexando `-N.html` ao final.
    """
    if page <= 1:
        return path
    if path.endswith(".html"):
        return path[:-5] + f"-{page}.html"
    return path.rstrip("/") + f"-{page}.html"


_CATALOG_CACHE_TTL = 30 * 60  # 30 minutos
_catalog_cache: dict[Any, tuple[float, list[dict[str, Any]]]] = {}
_catalog_lock = threading.Lock()


# Categorias expostas para o usuario na UI. A ordem aqui define a ordem do
# menu suspenso. Maximo recomendado: 25 (limite de opcoes do Discord Select).
CATEGORIES: dict[str, str | None] = {
    "Todos (catalogo combinado)": None,
    "Mais quentes": "/list/Hot-Manga/",
    "Recem atualizados": "/list/New-Update.html",
    "Novos": "/list/New-Manga/",
    "Aventura": "/category/Aventura.html",
    "Acao": "/category/Ação.html",
    "Romance": "/category/Romance.html",
    "Comedia": "/category/Comédia.html",
    "Drama": "/category/Drama.html",
    "Fantasia": "/category/Fantasia.html",
    "Manhwa": "/category/Manhwa.html",
    "Webtoon": "/category/Webtoon.html",
    "Sobrenatural": "/category/Sobrenatural.html",
    "Escolar": "/category/Escolar.html",
    "Artes Marciais": "/category/Artes Marciais.html",
    "Historico": "/category/Histórico.html",
    "Harem": "/category/Harém.html",
    "Super poderes": "/category/Super poderes.html",
    "Demonios": "/category/Demonios.html",
    "Horror": "/category/Horror.html",
    "Shoujo": "/category/Shoujo.html",
    "Slice of Life": "/category/Slice of Life.html",
    "Sci-fi": "/category/Sci-fi.html",
    "Adulto (18+)": "/category/Adulto (18+).html",
    "Adulto (YAOI)": "/category/Adulto (YAOI).html",
}

DEFAULT_CATEGORY = "Todos (catalogo combinado)"


def _fetch_listing_safely(path: str) -> list[dict[str, Any]]:
    try:
        html = _http_get(_absolute_listing_url(path))
    except requests.RequestException:
        return []
    return _parse_listing_page(html)


def _fetch_listing_paginated(path: str, max_pages: int = 5) -> list[dict[str, Any]]:
    """Faz paginacao automatica (`-N.html`) e para quando uma pagina nao
    traz nenhum slug novo em relacao as anteriores.
    """
    seen_slugs: set[str] = set()
    items: list[dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        page_path = _paginated_path(path, page)
        try:
            html = _http_get(_absolute_listing_url(page_path))
        except requests.RequestException:
            if page == 1:
                return []
            break

        page_items = _parse_listing_page(html)
        if not page_items and page == 1:
            return []

        added = 0
        for item in page_items:
            slug = item.get("slug")
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            items.append(item)
            added += 1

        if added == 0:
            break

    return items


def fetch_catalog(
    max_sources: int = 250,
    max_items: int = 6000,
    *,
    use_cache: bool = True,
    parallel: int = 14,
    pages_per_source: int = 12,
) -> list[dict[str, Any]]:
    """Baixa o catalogo combinando listagens/categorias do niadd
    com paginacao (`-N.html`) ate uma pagina nao trazer entradas novas.

    Paths vem das listas conhecidas + descoberta em `/`, Hot-Manga e
    Novos (`_DISCOVERY_HTML_SEEDS`), sem duplicar `/list/New-Update/`
    vs `.html`.

    Resultado cacheado por 30 min em memoria.
    """
    cache_key = ("combined_slugn", max_sources, max_items, pages_per_source)
    now = time.monotonic()

    if use_cache:
        with _catalog_lock:
            cached = _catalog_cache.get(cache_key)
            if cached and (now - cached[0]) < _CATALOG_CACHE_TTL:
                return list(cached[1])

    seen_identity: set[str] = set()
    sources: list[str] = []

    def register_source(rel_path: str) -> None:
        ident = _listing_path_identity(rel_path)
        if not ident:
            return
        if ident in seen_identity:
            return
        seen_identity.add(ident)
        sources.append(rel_path)

    for path in _KNOWN_LIST_PATHS + _KNOWN_CATEGORY_PATHS:
        register_source(path)

    discovery_html_chunks: list[str] = []
    for seed in _DISCOVERY_HTML_SEEDS:
        try:
            seed_url = f"{BASE_URL}/" if seed == "/" else _absolute_listing_url(seed)
            discovery_html_chunks.append(_http_get(seed_url))
        except requests.RequestException:
            continue

    for extra in _harvest_discovery_paths(discovery_html_chunks):
        register_source(extra)

    sources = sources[:max_sources]

    workers = max(1, min(parallel, len(sources)))
    results: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_listing_paginated, path, pages_per_source): path
            for path in sources
        }
        for future in futures:
            path = futures[future]
            try:
                results[path] = future.result()
            except Exception:
                results[path] = []

    catalog: list[dict[str, Any]] = []
    seen_slug_keys: set[str] = set()
    for path in sources:
        for item in results.get(path, []):
            skid = str(item.get("slug") or "").strip().lower()
            if not skid or skid in seen_slug_keys:
                continue
            seen_slug_keys.add(skid)
            catalog.append(item)
            if len(catalog) >= max_items:
                catalog.sort(key=lambda e: e["title"].lower())
                with _catalog_lock:
                    _catalog_cache[cache_key] = (now, list(catalog))
                return catalog

    catalog.sort(key=lambda entry: entry["title"].lower())
    with _catalog_lock:
        _catalog_cache[cache_key] = (now, list(catalog))
    return catalog


def fetch_category(
    label: str,
    *,
    use_cache: bool = True,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    """Retorna mangas de uma categoria especifica do niadd, ja paginada.

    - "Todos" devolve o catalogo combinado (cached: listagens + categorias extras).
    - Para qualquer outro rotulo, faz a paginacao automatica `-N.html` ate
      `max_pages` ou ate uma pagina nao trazer slugs novos.
    """
    path = CATEGORIES.get(label)
    if path is None:
        return fetch_catalog(use_cache=use_cache)

    cache_key = ("category", path, max_pages)
    now = time.monotonic()
    if use_cache:
        with _catalog_lock:
            cached = _catalog_cache.get(cache_key)
            if cached and (now - cached[0]) < _CATALOG_CACHE_TTL:
                return list(cached[1])

    items = _fetch_listing_paginated(path, max_pages=max_pages)
    items.sort(key=lambda entry: entry["title"].lower())
    with _catalog_lock:
        _catalog_cache[cache_key] = (now, list(items))
    return items


def _normalize_text(value: str) -> str:
    """Normaliza texto pra busca tolerante: minusculas, sem acentos, sem
    pontuacao redundante."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value.lower())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.strip()


def _tokenize(value: str) -> list[str]:
    if not value:
        return []
    return [tok for tok in re.split(r"[^a-z0-9]+", value) if tok]


def _score_entry(entry: dict[str, Any], norm_query: str, tokens: list[str]) -> float:
    title = str(entry.get("title") or "")
    slug = str(entry.get("slug") or "").replace("_", " ")
    norm_title = _normalize_text(title)
    norm_slug = _normalize_text(slug)
    haystack = f"{norm_title} {norm_slug}"

    if norm_query and norm_query in haystack:
        score = 5000.0
        if norm_title.startswith(norm_query):
            score += 3000.0
        if norm_title == norm_query:
            score += 5000.0
        score -= max(0, len(haystack) - len(norm_query)) * 0.1
        return score

    if tokens:
        matched = sum(1 for tok in tokens if tok in haystack)
        if matched > 0:
            pct = matched / len(tokens)
            return matched * 200.0 + pct * 400.0
        ratio = SequenceMatcher(None, norm_query, norm_title).ratio()
        if ratio >= 0.5:
            return ratio * 100.0

    return 0.0


def _native_site_search(raw_query: str) -> list[dict[str, Any]]:
    """Usa o endpoint de busca real do niadd (`/search/?wd=...`).

    Esse endpoint cobre o catalogo completo do site (nao so as listagens
    cacheadas), entao serve como complemento quando a busca local nao acha
    o titulo. Falhas de rede sao silenciosas.
    """
    if not raw_query:
        return []
    try:
        url = f"{BASE_URL}/search/?wd={quote(raw_query)}"
        html = _http_get(url)
    except requests.RequestException:
        return []
    return _parse_listing_page(html)


def search_titles(
    query: str,
    limit: int = 12,
    max_sources: int = 250,
    *,
    use_site_search: bool = True,
) -> list[dict[str, Any]]:
    """Busca tolerante: combina catalogo local (rapido, cache) com a busca
    nativa do niadd (cobre o site inteiro).

    Suporta:
    - case + acento + ordem livre + fuzzy (typos)
    - resultados ordenados por relevancia
    - dedup por slug
    """
    raw_query = (query or "").strip()
    if not raw_query:
        return []

    norm_query = _normalize_text(raw_query)
    if not norm_query:
        return []

    tokens = _tokenize(norm_query)

    # 1) Busca local em cima do catalogo combinado (instantanea com cache).
    local_catalog = fetch_catalog(max_sources=max_sources, max_items=2000)

    by_slug: dict[str, dict[str, Any]] = {}
    scored: list[tuple[float, str]] = []
    for entry in local_catalog:
        score = _score_entry(entry, norm_query, tokens)
        if score <= 0:
            continue
        slug = entry.get("slug", "")
        if not slug or slug in by_slug:
            continue
        by_slug[slug] = entry
        scored.append((score, slug))

    # 2) Complementa com a busca nativa do site (cobre o catalogo inteiro,
    # incluindo titulos que nao estao em nenhuma das listagens que cacheamos).
    if use_site_search:
        for entry in _native_site_search(raw_query):
            slug = entry.get("slug", "")
            if not slug or slug in by_slug:
                continue
            score = _score_entry(entry, norm_query, tokens)
            if score <= 0:
                # O proprio site achou esse titulo entao consideramos relevante
                # mesmo se nosso scorer nao bateu (acentos exoticos etc).
                score = 50.0
            by_slug[slug] = entry
            scored.append((score, slug))

    scored.sort(key=lambda pair: -pair[0])
    return [by_slug[slug] for _, slug in scored[:limit]]


def clear_catalog_cache() -> None:
    with _catalog_lock:
        _catalog_cache.clear()


def fetch_manga_detail(slug_or_url: str) -> dict[str, Any]:
    """Devolve titulo, capa, sinopse e lista (em ordem cronologica) de capitulos."""
    if slug_or_url.startswith("http"):
        slug = _slug_from_manga_url(slug_or_url)
    else:
        slug = slug_or_url.strip("/")

    if not slug:
        raise ValueError("Manga slug invalido.")

    page_url = f"{BASE_URL}/manga/{quote(slug)}.html"
    chapters_url = f"{BASE_URL}/manga/{quote(slug)}/chapters.html"

    main_html = _http_get(page_url)
    try:
        chapters_html = _http_get(chapters_url)
    except requests.RequestException:
        chapters_html = main_html

    title = ""
    og_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', main_html, re.IGNORECASE)
    if og_title:
        title = _clean_text(og_title.group(1))
        title = re.sub(r"\s*Details?\s*,?.*$", "", title, flags=re.IGNORECASE).strip()
    if not title:
        title = _slug_to_title(slug)

    cover = ""
    og_image = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', main_html, re.IGNORECASE)
    if og_image:
        cover = _absolute(og_image.group(1))

    chapter_re = re.compile(
        _CHAPTER_LINK_RE_TEMPLATE.format(slug=re.escape(slug)),
        re.IGNORECASE,
    )

    chapters: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for href, chapter_id in chapter_re.findall(chapters_html):
        if chapter_id in seen_ids:
            continue
        seen_ids.add(chapter_id)
        chapter_slug = _slug_from_chapter_url(href)
        chapter_title = _slug_to_title(chapter_slug.replace(slug, "").strip("_-")) or chapter_slug
        chapters.append(
            {
                "chapter_id": chapter_id,
                "chapter_slug": chapter_slug,
                "title": chapter_title,
                "url": _absolute(href.rstrip("/")) + (".html" if not href.endswith(".html") else ""),
            }
        )

    # O site lista do mais recente para o mais antigo. Inverter para crescente.
    def _key(ch: dict[str, Any]) -> tuple[int, ...]:
        nums = [int(x) for x in re.findall(r"\d+", ch["chapter_slug"])]
        return tuple(nums) if nums else (0,)

    chapters.sort(key=_key)

    return {
        "slug": slug,
        "title": title,
        "cover_url": cover,
        "url": page_url,
        "chapters": chapters,
    }


def _chapter_subpage_url(chapter_slug: str, chapter_id: str, page: int) -> str:
    if page <= 1:
        return f"{BASE_URL}/chapter/{quote(chapter_slug)}/{chapter_id}.html"
    return f"{BASE_URL}/chapter/{quote(chapter_slug)}/{chapter_id}-{page}.html"


def fetch_chapter_pages(chapter_slug: str, chapter_id: str, max_pages: int = 200) -> list[str]:
    """Coleta as URLs das paginas de um capitulo seguindo o padrao de subpaginas."""
    if not chapter_slug or not chapter_id:
        return []

    first_url = _chapter_subpage_url(chapter_slug, chapter_id, 1)
    try:
        first_html = _http_get(first_url)
    except requests.RequestException:
        return []

    sub_pattern = re.compile(
        rf"/chapter/{re.escape(chapter_slug)}/{re.escape(chapter_id)}(?:-(\d+))?\.html",
        re.IGNORECASE,
    )
    declared = sorted({int(n) for n in sub_pattern.findall(first_html) if n})
    total = max(declared) if declared else 1
    total = min(max(total, 1), max_pages)

    images: list[str] = []
    for page in range(1, total + 1):
        if page == 1:
            html = first_html
        else:
            try:
                html = _http_get(_chapter_subpage_url(chapter_slug, chapter_id, page))
            except requests.RequestException:
                continue

        # A primeira imagem do dominio wpimg/imgN nessa subpagina e a real.
        candidates = _PAGE_IMAGE_RE.findall(html)
        chosen = ""
        for url in candidates:
            if "wpimg.yx247.com" in url:
                chosen = url
                break
        if not chosen and candidates:
            chosen = candidates[0]
        if chosen and chosen not in images:
            images.append(_absolute(chosen))

    return images


def download_image_bytes(image_url: str) -> bytes:
    headers = dict(DEFAULT_HEADERS)
    headers["Referer"] = f"{BASE_URL}/"
    response = requests.get(image_url, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.content


__all__ = [
    "BASE_URL",
    "CATEGORIES",
    "DEFAULT_CATEGORY",
    "fetch_catalog",
    "fetch_category",
    "search_titles",
    "fetch_manga_detail",
    "fetch_chapter_pages",
    "download_image_bytes",
    "clear_catalog_cache",
]
