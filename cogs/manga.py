import os
import re
import html
import io
import asyncio
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from typing import Any

import discord
import requests
from discord import app_commands
from discord.ext import commands
from PIL import Image

from cogs import _niadd as niadd
from cogs import _manga_perms as manga_perms


MANGA_ID = "sense_life"
MANGA_LABEL = "sense life"
EXTERNAL_MANGA_DIR = Path(r"D:\SENSE")
LOCAL_BASE_MANGA_DIR = Path(__file__).resolve().parents[1] / "data" / "mangas" / MANGA_ID
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MANGALIVRE_TIMEOUT = 20
MANGALIVRE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


@dataclass(frozen=True)
class MangalivreSite:
    """Config de scraping por host (tema WordPress Madara vs outro)."""

    key: str
    base_url: str
    manga_base: str
    chapter_flat_base: str
    list_seed: str
    pagination_mode: str


MANGALIVRE_BLOG_SITE = MangalivreSite(
    key="blog",
    base_url="https://mangalivre.blog",
    manga_base="https://mangalivre.blog/manga/",
    chapter_flat_base="https://mangalivre.blog/capitulo/",
    list_seed="https://mangalivre.blog/manga/?manga_status=em-lancamento&orderby=title",
    pagination_mode="query_paged",
)
MANGALIVRE_TO_SITE = MangalivreSite(
    key="to",
    base_url="https://mangalivre.to",
    manga_base="https://mangalivre.to/manga/",
    chapter_flat_base="",
    list_seed="https://mangalivre.to/manga/?m_orderby=alphabet",
    pagination_mode="wp_directory_page",
)

# Gêneros em https://mangalivre.to/genero/{slug}/ (taxonomia WordPress).
# Ordem: "Todos" + slugs (34 entradas). Select paginado: 23 + nav + 11 + nav (limite 25).
MANGALIVRE_TO_DEFAULT_CATEGORY = "Todos (A-Z)"
_MLTO_NAV_NEXT = "__mlto_cat_next__"
_MLTO_NAV_PREV = "__mlto_cat_prev__"
# Paginacao do select em /mangaconfig para categorias MLTO (usa valores distintos do painel mangasetup).
_MCF_MLTO_NAV_NEXT = "__mcf_mlto_next__"
_MCF_MLTO_NAV_PREV = "__mcf_mlto_prev__"
MANGALIVRE_TO_CATEGORY_ENTRIES: tuple[tuple[str, str | None], ...] = (
    (MANGALIVRE_TO_DEFAULT_CATEGORY, None),
    ("Acao", "https://mangalivre.to/genero/acao/"),
    ("Artes Marciais", "https://mangalivre.to/genero/artes-marciais/"),
    ("Aventura", "https://mangalivre.to/genero/aventura/"),
    ("Comedia", "https://mangalivre.to/genero/comedia/"),
    ("Demonios", "https://mangalivre.to/genero/demonios/"),
    ("Drama", "https://mangalivre.to/genero/drama/"),
    ("Escolar", "https://mangalivre.to/genero/escolar/"),
    ("Esportes", "https://mangalivre.to/genero/esportes/"),
    ("Fantasia", "https://mangalivre.to/genero/fantasia/"),
    ("Harem", "https://mangalivre.to/genero/harem/"),
    ("Historico", "https://mangalivre.to/genero/historico/"),
    ("Isekai", "https://mangalivre.to/genero/isekai/"),
    ("Light Novels", "https://mangalivre.to/genero/light-novels/"),
    ("Manga", "https://mangalivre.to/genero/manga/"),
    ("Manhuas", "https://mangalivre.to/genero/manhuas/"),
    ("Manhwa", "https://mangalivre.to/genero/manhwa/"),
    ("Psicologico", "https://mangalivre.to/genero/psicologico/"),
    ("Reencarnacao", "https://mangalivre.to/genero/reencarnacao/"),
    ("Romance", "https://mangalivre.to/genero/romance/"),
    ("Seinen", "https://mangalivre.to/genero/seinen/"),
    ("Shoujo", "https://mangalivre.to/genero/shoujo/"),
    ("Shounen", "https://mangalivre.to/genero/shounen/"),
    ("Slice of Life", "https://mangalivre.to/genero/slice-of-life/"),
    ("Sobrenatural", "https://mangalivre.to/genero/sobrenatural/"),
    ("Suspense", "https://mangalivre.to/genero/suspense/"),
    ("Tragedia", "https://mangalivre.to/genero/tragedia/"),
    ("Vampiros", "https://mangalivre.to/genero/vampiros/"),
    ("Webtoon", "https://mangalivre.to/genero/webtoon/"),
    ("Yuri", "https://mangalivre.to/genero/yuri/"),
)
_MLTO_CATEGORY_LABELS = {label for label, _ in MANGALIVRE_TO_CATEGORY_ENTRIES}

MANGALIVRE_BASE_URL = MANGALIVRE_BLOG_SITE.base_url
MANGALIVRE_MANGA_BASE = MANGALIVRE_BLOG_SITE.manga_base
MANGALIVRE_CHAPTER_BASE = MANGALIVRE_BLOG_SITE.chapter_flat_base
MANGALIVRE_SETUP_SOURCE = MANGALIVRE_BLOG_SITE.list_seed

# Leitor bem grande (~2.5× largura/altura vs original; maior nitidez ao ampliar no Discord).
MANGA_PAGE_DISPLAY_SCALE = 2.5


def _scale_manga_page_for_discord(data: bytes, ext: str = ".jpg") -> tuple[bytes, str]:
    """Redimensiona bytes de uma pagina estatica para leitura no Discord."""
    suf = (ext or ".jpg").lower()
    if not data:
        return data, suf
    try:
        with Image.open(io.BytesIO(data)) as im:
            if getattr(im, "n_frames", 1) > 1:
                return data, suf
            im.seek(0)
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS

            w, h = im.size
            if w < 2 or h < 2:
                return data, suf
            new_w = max(1, int(round(w * MANGA_PAGE_DISPLAY_SCALE)))
            new_h = max(1, int(round(h * MANGA_PAGE_DISPLAY_SCALE)))

            src = im
            if src.mode == "P" and "transparency" in src.info:
                src = src.convert("RGBA")
            elif src.mode == "RGBA":
                pass
            elif src.mode != "RGB":
                src = src.convert("RGB")

            resized = src.resize((new_w, new_h), resample)

            out = io.BytesIO()
            if resized.mode == "RGBA":
                resized.save(out, format="PNG", optimize=True)
                return out.getvalue(), ".png"

            resized.save(out, format="JPEG", quality=93, optimize=True)
            return out.getvalue(), ".jpg"
    except Exception:
        return data, suf


def _reader_embed_visual_frame(
    subtitle_lines: list[str],
    *,
    color: int,
    eyebrow: str = "",
    footer: str = "",
) -> discord.Embed:
    """Bloco de texto do leitor com mais hierarquia visual (combo com imagem ampliada)."""
    chunks: list[str] = []
    if eyebrow.strip():
        chunks.append(eyebrow.strip())
        chunks.append("")
    for line in subtitle_lines:
        s = line.strip()
        if s:
            chunks.append(f"**{s}**")
    desc = "\n".join(chunks).strip()
    embed = discord.Embed(description=desc, color=color)
    if footer:
        embed.set_footer(text=footer)
    return embed


def _format_perms_lines(block: dict[str, list[int]], empty_note: str) -> str:
    if not block:
        return empty_note
    lines: list[str] = []
    for cat, role_ids in sorted(block.items()):
        roles_text = ", ".join(f"<@&{rid}>" for rid in role_ids) or "(vazio)"
        lines.append(f"**{cat}** — {roles_text}")
    text = "\n".join(lines)
    if len(text) > 950:
        return text[:900] + "\n… (lista truncada — use o hub do servidor)"
    return text


def _embed_listar_niadd(guild: discord.Guild) -> discord.Embed:
    configs = manga_perms.list_all_configs(guild.id)
    embed = discord.Embed(
        title="Servidor 2 • Niadd — restricoes por categoria",
        color=0x10B981,
    )
    embed.description = _format_perms_lines(
        configs,
        "Nenhuma categoria restrita. Todas liberadas.",
    )
    embed.set_footer(text="Categorias nao listadas = publicas (niadd).")
    return embed


def _embed_listar_mlto(guild: discord.Guild) -> discord.Embed:
    configs = manga_perms.list_all_configs_mlto(guild.id)
    embed = discord.Embed(
        title="Servidor 3 • Manga Livre (.to) — restricoes por categoria",
        color=0x22C55E,
    )
    embed.description = _format_perms_lines(
        configs,
        "Nenhuma categoria restrita. Todas liberadas.",
    )
    embed.set_footer(text="Categorias nao listadas = publicas (M.Livre).")
    return embed


def _embed_listar_ambos(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title="Restricoes /mangasetup (Servidor 2 e 3)",
        color=0x6366F1,
    )
    ni = manga_perms.list_all_configs(guild.id)
    ml = manga_perms.list_all_configs_mlto(guild.id)
    embed.add_field(
        name="Servidor 2 • Niadd",
        value=_format_perms_lines(
            ni, "(nenhuma restricao — todos podem usar as categorias niadd)"
        ),
        inline=False,
    )
    embed.add_field(
        name="Servidor 3 • Manga Livre",
        value=_format_perms_lines(
            ml, "(nenhuma restricao — todos podem usar as categorias .to)"
        ),
        inline=False,
    )
    return embed


def _mangaconfig_main_embed() -> discord.Embed:
    return discord.Embed(
        title="Manga • Configuracao",
        description=(
            "Restringe categorias do **`/mangasetup`** por cargo.\n\n"
            "• **Servidor 2** — fonte **Niadd**\n"
            "• **Servidor 3** — **Manga Livre** (mangalivre.to)\n"
            "• **Listar todas** — visao geral dos dois\n\n"
            "Comandos de leitura (`/manga`, `/manga_site`, `/mangasetup`) continuam iguais."
        ),
        color=0x6366F1,
    )


def _mangalivre_site_for_setup_server(server: int) -> MangalivreSite:
    """Servidor 1 = mangalivre.blog, Servidor 3 = mangalivre.to."""
    if server == 3:
        return MANGALIVRE_TO_SITE
    return MANGALIVRE_BLOG_SITE


def _infer_mangalivre_site(url: str) -> MangalivreSite:
    host = urlparse(url or "").netloc.lower()
    if "mangalivre.to" in host:
        return MANGALIVRE_TO_SITE
    return MANGALIVRE_BLOG_SITE


def _mlto_category_list_seed(label: str) -> str:
    if label not in _MLTO_CATEGORY_LABELS:
        label = MANGALIVRE_TO_DEFAULT_CATEGORY
    for cat_label, url in MANGALIVRE_TO_CATEGORY_ENTRIES:
        if cat_label == label:
            return url or MANGALIVRE_TO_SITE.list_seed
    return MANGALIVRE_TO_SITE.list_seed


def _mlto_catalog_fetch_limits(category_label: str) -> tuple[int, int]:
    """(max_pages, max_items) — catalogo completo no .to exige mais paginas."""
    if category_label == MANGALIVRE_TO_DEFAULT_CATEGORY:
        return 85, 3200
    return 55, 1800


def _build_mlto_category_select_options(active: str, page_idx: int) -> list[discord.SelectOption]:
    entries = MANGALIVRE_TO_CATEGORY_ENTRIES
    first_page_count = 23
    opts: list[discord.SelectOption] = []

    if page_idx <= 0:
        for label, _ in entries[:first_page_count]:
            opts.append(
                discord.SelectOption(
                    label=label[:100],
                    value=label[:100],
                    default=(label == active),
                )
            )
        if len(entries) > first_page_count:
            opts.append(
                discord.SelectOption(
                    label="Mais categorias",
                    value=_MLTO_NAV_NEXT,
                    default=False,
                )
            )
        return opts

    opts.append(
        discord.SelectOption(
            label="Voltar categorias",
            value=_MLTO_NAV_PREV,
            default=False,
        )
    )
    for label, _ in entries[first_page_count:]:
        opts.append(
            discord.SelectOption(
                label=label[:100],
                value=label[:100],
                default=(label == active),
            )
        )
    return opts


def _mcflto_perm_category_options(
    page_idx: int, active_label: str
) -> list[discord.SelectOption]:
    entries = MANGALIVRE_TO_CATEGORY_ENTRIES
    first_page_count = 23
    opts: list[discord.SelectOption] = []
    if page_idx <= 0:
        for label, _ in entries[:first_page_count]:
            opts.append(
                discord.SelectOption(
                    label=label[:100],
                    value=label[:100],
                    default=(label == active_label),
                )
            )
        if len(entries) > first_page_count:
            opts.append(
                discord.SelectOption(
                    label="Mais categorias",
                    value=_MCF_MLTO_NAV_NEXT,
                    default=False,
                )
            )
        return opts
    opts.append(
        discord.SelectOption(
            label="Voltar categorias",
            value=_MCF_MLTO_NAV_PREV,
            default=False,
        )
    )
    for label, _ in entries[first_page_count:]:
        opts.append(
            discord.SelectOption(
                label=label[:100],
                value=label[:100],
                default=(label == active_label),
            )
        )
    return opts


def _natural_key(value: str):
    parts = re.split(r"(\d+)", value.lower())
    key = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part)
    return key


def _resolve_base_manga_dir() -> Path:
    if EXTERNAL_MANGA_DIR.exists():
        return EXTERNAL_MANGA_DIR
    return LOCAL_BASE_MANGA_DIR


def _resolve_chapters_dir() -> Path:
    base_dir = _resolve_base_manga_dir()
    chapters_dir = base_dir / "capitulos"
    if chapters_dir.exists():
        return chapters_dir
    return base_dir


def _ensure_manga_structure():
    base_dir = _resolve_base_manga_dir()
    chapters_dir = _resolve_chapters_dir()
    chapters_dir.mkdir(parents=True, exist_ok=True)

    sample_chapter = chapters_dir / "capitulo_001"
    sample_chapter.mkdir(parents=True, exist_ok=True)

    readme_path = base_dir / "README.txt"
    if not readme_path.exists():
        readme_path.write_text(
            "Pasta do manga Sense Life.\n"
            "\n"
            "Como organizar:\n"
            f"1) Coloque os capitulos em {chapters_dir}\n"
            "2) Use pastas como: capitulo_001, capitulo_002, capitulo_003\n"
            "3) Dentro de cada capitulo, coloque as paginas em ordem:\n"
            "   001.png, 002.png, 003.png ...\n"
            "\n"
            "Extensoes aceitas: .png, .jpg, .jpeg, .webp, .gif\n",
            encoding="utf-8",
        )


def _get_chapters() -> list[Path]:
    _ensure_manga_structure()
    chapters_dir = _resolve_chapters_dir()
    chapters = [p for p in chapters_dir.iterdir() if p.is_dir()]
    chapters.sort(key=lambda p: _natural_key(p.name))
    return chapters


def _get_pages(chapter_path: Path) -> list[Path]:
    pages = [
        p for p in chapter_path.iterdir()
        if p.is_file() and p.suffix.lower() in ALLOWED_IMAGE_EXTS
    ]
    pages.sort(key=lambda p: _natural_key(p.name))
    return pages


def _to_absolute_url(url: str, site: MangalivreSite | None = None) -> str:
    raw = html.unescape(url.strip())
    if not raw:
        return ""
    if raw.startswith("//"):
        return f"https:{raw}"
    base = (site or _infer_mangalivre_site(raw)).base_url.rstrip("/")
    if raw.startswith("/"):
        return f"{base}{raw}"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"{base}/{raw.lstrip('/')}"


def _normalize_manga_url(url: str, site: MangalivreSite | None = None) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.netloc:
        resolved = _infer_mangalivre_site(url)
    else:
        resolved = site or MANGALIVRE_BLOG_SITE
    cleaned = _to_absolute_url(url, resolved).strip()
    if not cleaned:
        return ""
    if cleaned.endswith("/"):
        return cleaned
    return f"{cleaned}/"


def _extract_attr(tag: str, attr_name: str) -> str:
    pattern = rf'{attr_name}\s*=\s*["\']([^"\']+)["\']'
    match = re.search(pattern, tag, flags=re.IGNORECASE)
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


def _clean_text(raw: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r"\s+", " ", html.unescape(without_tags)).strip()
    return normalized


def _sanitize_manga_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", title).strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^em\s+lancamento\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+cap\.\s*\d+(?:[.,]\d+)?(?:\s+.*)?$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" -|")


def _slug_to_title(url: str) -> str:
    path = urlparse(url).path
    slug = path.strip("/").split("/")[-1]
    return slug.replace("-", " ").strip().title()


def _chapter_key_from_url(url: str) -> tuple[Any, ...]:
    slug = urlparse(url).path.strip("/").split("/")[-1]
    match = re.search(r"capitulo-(\d+(?:-\d+)*)", slug, flags=re.IGNORECASE)
    if not match:
        return (1, _natural_key(slug))
    parts = [int(part) for part in match.group(1).split("-") if part.isdigit()]
    return (0, tuple(parts))


def _http_get_text(url: str, site: MangalivreSite | None = None) -> str:
    headers = dict(MANGALIVRE_HEADERS)
    resolved = site or _infer_mangalivre_site(url)
    headers["Referer"] = f"{resolved.base_url}/"
    response = requests.get(url, headers=headers, timeout=MANGALIVRE_TIMEOUT)
    response.raise_for_status()
    return response.text


def _extract_manga_links_from_html(page_html: str, site: MangalivreSite) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    manga_prefix = site.manga_base.lower()
    pattern = re.compile(
        r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(page_html):
        href = _normalize_manga_url(match.group(1), site)
        if not href.lower().startswith(manga_prefix):
            continue
        if href in seen:
            continue
        if href.rstrip("/").lower() == manga_prefix.rstrip("/"):
            continue

        parts = [p for p in urlparse(href).path.strip("/").split("/") if p]
        if len(parts) != 2 or parts[0].lower() != "manga":
            continue
        if parts[1].lower() in {"feed", "page"}:
            continue

        label = _sanitize_manga_title(_clean_text(match.group(2)))
        if not label or label.lower() in {"inicio", "todos os mangas", "em lancamento"}:
            label = _slug_to_title(href)
        seen.add(href)
        results.append({"title": label, "url": href})
    return results


def _extract_madara_cards_from_listing(page_html: str, site: MangalivreSite) -> list[dict[str, str]]:
    """Lista do tema Madara (mangalivre.to): `page-item-detail manga`."""
    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    prefix = site.manga_base.rstrip("/")
    href_re = re.compile(rf'href=["\']({re.escape(prefix)}/[^"\']+)["\'](?:[^>]*)?', re.I)
    title_re = re.compile(r'\btitle=["\']([^"\']+)["\']', re.I)

    starts = [
        m.start()
        for m in re.finditer(
            r'<div[^>]+class=["\'][^"\']*\bpage-item-detail\b[^"\']*\bmanga\b[^"\']*["\']',
            page_html,
            flags=re.IGNORECASE,
        )
    ]
    for idx, pos in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(page_html)
        block = page_html[pos:end]
        href_m = href_re.search(block)
        if not href_m:
            continue
        url = _normalize_manga_url(href_m.group(1), site)
        path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
        if len(path_parts) != 2 or path_parts[0].lower() != "manga":
            continue
        if path_parts[1].lower() in {"feed", "page"}:
            continue
        if url in seen:
            continue

        title = ""
        anchor_start = max(0, href_m.start() - 120)
        anchor_snip = block[anchor_start : href_m.end()]
        title_m = title_re.search(anchor_snip)
        if title_m:
            title = _sanitize_manga_title(_clean_text(title_m.group(1)))
        if not title:
            h3 = re.search(
                r'<h3[^>]*>.*?<a[^>]+>(.*?)</a>',
                block,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if h3:
                title = _sanitize_manga_title(_clean_text(h3.group(1)))
        if not title:
            title = _slug_to_title(url)

        cover_url = ""
        img_m = re.search(r'<img[^>]+class=["\'][^"\']*img-responsive[^"\']*["\'][^>]*>', block, re.I)
        if img_m:
            tag = img_m.group(0)
            cover_url = _to_absolute_url(_extract_attr(tag, "src"), site)
            if not cover_url:
                srcset = _extract_attr(tag, "srcset")
                if srcset:
                    cover_url = _to_absolute_url(
                        srcset.split(",")[0].strip().split(" ")[0].strip(), site
                    )

        seen.add(url)
        cards.append({"title": title, "url": url, "cover_url": cover_url})

    return cards


def _extract_mangalivre_to_grid_cards(page_html: str, site: MangalivreSite) -> list[dict[str, str]]:
    """Grade `div.manga-item` (principal no .to homepage e em /genero/)."""
    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    prefix = site.manga_base.rstrip("/")

    opener = re.compile(
        r'<div[^>]+class=["\'][^"\']*\bmanga-item\b[^"\']*["\'][^>]*>',
        flags=re.IGNORECASE,
    )
    for block_start in opener.finditer(page_html):
        block = page_html[block_start.start() : block_start.start() + 4000]
        href_m = re.search(
            rf'href=["\']({re.escape(prefix)}/[^"\']+/)["\']',
            block,
            flags=re.IGNORECASE,
        )
        if not href_m:
            continue
        url = _normalize_manga_url(href_m.group(1), site)
        path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
        if len(path_parts) != 2 or path_parts[0].lower() != "manga":
            continue
        if path_parts[1].lower() in {"feed", "page"}:
            continue
        if url in seen:
            continue

        title = ""
        h3 = re.search(
            r'<h3[^>]+class=["\'][^"\']*manga-title[^"\']*["\'][^>]*>(.*?)</h3>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if h3:
            title = _sanitize_manga_title(_clean_text(h3.group(1)))
        if not title:
            title = _slug_to_title(url)

        cover_url = ""
        img_m = re.search(
            r'<img[^>]+class=["\'][^"\']*wp-post-image[^"\']*["\'][^>]*>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if img_m:
            tag = img_m.group(0)
            cover_url = _to_absolute_url(_extract_attr(tag, "src"), site)
            if not cover_url:
                srcset = _extract_attr(tag, "srcset")
                if srcset:
                    cover_url = _to_absolute_url(
                        srcset.split(",")[0].strip().split(" ")[0].strip(), site
                    )

        seen.add(url)
        cards.append({"title": title, "url": url, "cover_url": cover_url})

    return cards


def _merge_card_results(
    primary: list[dict[str, str]], secondary: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Preserva capa/titulo do primeiro quando o segundo repete a URL."""
    by_url: dict[str, dict[str, str]] = {}
    for entry in secondary:
        u = str(entry.get("url") or "").strip()
        if u:
            by_url[u] = dict(entry)
    for entry in primary:
        u = str(entry.get("url") or "").strip()
        if not u:
            continue
        base = by_url.get(u, {})
        merged = {**base, **entry}
        by_url[u] = merged
    return list(by_url.values())


def _extract_manga_cards_from_listing(page_html: str, site: MangalivreSite) -> list[dict[str, str]]:
    if site.key == "to":
        grid = _extract_mangalivre_to_grid_cards(page_html, site)
        madara = _extract_madara_cards_from_listing(page_html, site)
        return _merge_card_results(grid, madara)

    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    article_pattern = re.compile(
        r"<article[^>]+class=[\"'][^\"']*manga-card[^\"']*[\"'][^>]*>(.*?)</article>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    for block in article_pattern.findall(page_html):
        href_match = re.search(
            rf'href=["\']({re.escape(site.manga_base)}[^"\']+)["\']',
            block,
            flags=re.IGNORECASE,
        )
        if not href_match:
            continue
        url = _normalize_manga_url(href_match.group(1), site)
        parsed = urlparse(url)
        if parsed.query:
            continue
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(path_parts) != 2 or path_parts[0] != "manga":
            continue
        if url in seen:
            continue

        title = ""
        title_match = re.search(
            r'<h3[^>]+class=["\'][^"\']*manga-card-title[^"\']*["\'][^>]*>(.*?)</h3>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if title_match:
            title = _sanitize_manga_title(_clean_text(title_match.group(1)))
        if not title:
            title = _slug_to_title(url)

        cover_url = ""
        img_match = re.search(
            r'<img[^>]+class=["\'][^"\']*attachment-manga-cover[^"\']*["\'][^>]*>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if img_match:
            img_tag = img_match.group(0)
            cover_url = _to_absolute_url(_extract_attr(img_tag, "src"), site)
            if not cover_url:
                srcset = _extract_attr(img_tag, "srcset")
                if srcset:
                    cover_url = _to_absolute_url(
                        srcset.split(",")[0].strip().split(" ")[0].strip(), site
                    )

        seen.add(url)
        cards.append({"title": title, "url": url, "cover_url": cover_url})

    return cards


def _search_manga_online(query: str, limit: int = 8, site: MangalivreSite | None = None) -> list[dict[str, str]]:
    query = query.strip()
    if not query:
        return []

    s = site or MANGALIVRE_BLOG_SITE
    manga_base = s.manga_base.rstrip("/")
    base_url = s.base_url.rstrip("/")

    if s.key == "to":
        # Busca global (ex.: https://mangalivre.to/?s=Black+Clover)
        search_urls = [
            f"{base_url}/?s={quote_plus(query)}",
            f"{manga_base}/?s={quote_plus(query)}",
        ]
    else:
        search_urls = [
            f"{manga_base}/?s={quote_plus(query)}",
            f"{base_url}/?s={quote_plus(query)}",
            f"{manga_base}/",
        ]

    aggregated: dict[str, dict[str, str]] = {}
    for url in search_urls:
        try:
            page_html = _http_get_text(url, s)
        except requests.RequestException:
            continue

        def _merge_entry(row: dict[str, str]):
            href = str(row.get("url") or "").strip()
            if not href:
                return
            cur = aggregated.get(href, {"title": "", "url": href})
            if row.get("title"):
                cur["title"] = str(row["title"])
            if row.get("cover_url"):
                cur["cover_url"] = str(row["cover_url"])
            aggregated[href] = cur

        for entry in _extract_manga_cards_from_listing(page_html, s):
            _merge_entry(entry)
        for entry in _extract_manga_links_from_html(page_html, s):
            _merge_entry(entry)

    if not aggregated:
        return []

    tokens = [token for token in re.split(r"\s+", query.lower()) if token]

    def score(entry: dict[str, str]) -> tuple[int, int, str]:
        title_part = str(entry.get("title") or "")
        href = str(entry.get("url") or "")
        haystack = f"{title_part} {href}".lower()
        token_hits = sum(1 for token in tokens if token in haystack)
        exact = 1 if query.lower() in haystack else 0
        return (-exact, -token_hits, title_part)

    sorted_items = sorted(aggregated.values(), key=score)
    filtered = [
        item
        for item in sorted_items
        if query.lower()
        in f"{str(item.get('title') or '')} {str(item.get('url') or '')}".lower()
    ]
    return (filtered or sorted_items)[:limit]


def _extract_cover_url(page_html: str, site: MangalivreSite) -> str:
    # 1) Prioriza a capa real do card do manga.
    cover_img_patterns = [
        r'<img[^>]+class=["\'][^"\']*attachment-manga-cover[^"\']*["\'][^>]*>',
        r'<img[^>]+class=["\'][^"\']*wp-post-image[^"\']*["\'][^>]*>',
    ]
    for pattern in cover_img_patterns:
        for tag in re.findall(pattern, page_html, flags=re.IGNORECASE | re.DOTALL):
            src = _extract_attr(tag, "src")
            if src:
                return _to_absolute_url(src, site)
            srcset = _extract_attr(tag, "srcset")
            if srcset:
                first = srcset.split(",")[0].strip().split(" ")[0].strip()
                if first:
                    return _to_absolute_url(first, site)

    # 2) Fallback para OpenGraph.
    match = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        page_html,
        flags=re.IGNORECASE,
    )
    if match:
        return _to_absolute_url(match.group(1), site)
    return ""


def _extract_title_from_manga_page(page_html: str, fallback_url: str) -> str:
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, flags=re.IGNORECASE | re.DOTALL)
    if h1_match:
        title = _clean_text(h1_match.group(1))
        if title:
            return title
    title_tag = re.search(r"<title[^>]*>(.*?)</title>", page_html, flags=re.IGNORECASE | re.DOTALL)
    if title_tag:
        title = _clean_text(title_tag.group(1)).split(" - ")[0].strip()
        if title:
            return title
    return _slug_to_title(fallback_url)


def _chapter_href_qualifies(url: str, site: MangalivreSite) -> bool:
    href = url.lower()
    if site.key == "to":
        return "/manga/" in urlparse(url).path.lower() and "/capitulo-" in href
    fb = site.chapter_flat_base.rstrip("/").lower()
    return fb != "" and href.startswith(fb + "/")


def _extract_chapters_from_manga_page(page_html: str, site: MangalivreSite) -> list[dict[str, str]]:
    pattern = re.compile(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )

    chapters_map: dict[str, dict[str, str]] = {}
    for match in pattern.finditer(page_html):
        href = _normalize_manga_url(match.group(1), site)
        if not _chapter_href_qualifies(href, site):
            continue
        label = _clean_text(match.group(2))
        if not label:
            url_slug = urlparse(href).path.strip("/").split("/")[-1]
            number_match = re.search(r"capitulo-(\d+(?:-\d+)*)", url_slug, flags=re.IGNORECASE)
            label = (
                f"Capitulo {number_match.group(1).replace('-', '.')}"
                if number_match
                else _slug_to_title(href)
            )

        # Prefer "Ler"/chapter-item anchors from chapter list over generic nav links.
        old = chapters_map.get(href)
        if old is None or len(label) > len(old["title"]):
            chapters_map[href] = {"title": label, "url": href}

    chapters = list(chapters_map.values())
    chapters.sort(key=lambda chapter: _chapter_key_from_url(chapter["url"]))
    return chapters


def _get_manga_online_data(manga_url: str, site: MangalivreSite | None = None) -> dict[str, Any]:
    s = site or _infer_mangalivre_site(manga_url)
    page_html = _http_get_text(manga_url, s)
    return {
        "title": _extract_title_from_manga_page(page_html, manga_url),
        "url": _normalize_manga_url(manga_url, s),
        "cover_url": _extract_cover_url(page_html, s),
        "chapters": _extract_chapters_from_manga_page(page_html, s),
    }


def _extract_chapter_images(chapter_html: str, site: MangalivreSite) -> list[str]:
    image_tags = re.findall(r"<img\b[^>]*>", chapter_html, flags=re.IGNORECASE | re.DOTALL)
    images: list[str] = []
    seen: set[str] = set()

    for tag in image_tags:
        class_attr = _extract_attr(tag, "class").lower()
        url = (
            _extract_attr(tag, "data-src")
            or _extract_attr(tag, "data-original")
            or _extract_attr(tag, "data-lazy-src")
            or _extract_attr(tag, "src")
        )
        if not url:
            srcset = _extract_attr(tag, "srcset")
            if srcset:
                url = srcset.split(",")[0].strip().split(" ")[0].strip()
        url = _to_absolute_url(url, site)
        if not url or url in seen:
            continue
        # Prefer imagens da area de leitura, mas aceita fallback geral do uploads.
        if "/wp-content/uploads/" not in url:
            continue
        if not re.search(r"\.(png|jpe?g|webp|gif)(\?|$)", url, flags=re.IGNORECASE):
            continue
        if class_attr and "avatar" in class_attr:
            continue
        seen.add(url)
        images.append(url)

    if images:
        return images

    # Fallback: algumas paginas injetam URLs em JSON/script, sem <img> pronto.
    raw_urls = re.findall(
        r"https?:\\?/\\?/[^\"'\s<>]+/wp-content/uploads/[^\"'\s<>]+\.(?:png|jpe?g|webp|gif)(?:\?[^\"'\s<>]*)?",
        chapter_html,
        flags=re.IGNORECASE,
    )
    for raw_url in raw_urls:
        candidate = raw_url.replace("\\/", "/")
        candidate = html.unescape(candidate)
        candidate = _to_absolute_url(candidate, site)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        images.append(candidate)

    if images:
        return images

    # Ultimo fallback: qualquer src de img com extensao valida.
    for tag in image_tags:
        src = _to_absolute_url(_extract_attr(tag, "src"), site)
        if not src or src in seen:
            continue
        if not re.search(r"\.(png|jpe?g|webp|gif)(\?|$)", src, flags=re.IGNORECASE):
            continue
        seen.add(src)
        images.append(src)

    return images


def _get_chapter_online_pages(chapter_url: str) -> list[str]:
    site = _infer_mangalivre_site(chapter_url)
    chapter_html = _http_get_text(chapter_url, site)
    return _extract_chapter_images(chapter_html, site)


def _download_image_bytes(image_url: str) -> bytes:
    headers = dict(MANGALIVRE_HEADERS)
    headers["Referer"] = f"{_infer_mangalivre_site(image_url).base_url}/"
    response = requests.get(image_url, headers=headers, timeout=MANGALIVRE_TIMEOUT)
    response.raise_for_status()
    return response.content


class PageInputModal(discord.ui.Modal, title="Selecionar Pagina"):
    page = discord.ui.TextInput(
        label="Numero da pagina",
        placeholder="Ex: 12",
        required=True,
        min_length=1,
        max_length=5,
    )

    def __init__(self, parent_view: "MangaReaderView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.page).strip()
        if not raw.isdigit():
            return await interaction.response.send_message("Digite um numero valido.", ephemeral=True)

        index = int(raw) - 1
        pages = self.parent_view.current_pages()
        if not pages:
            return await interaction.response.send_message("Esse capitulo ainda nao tem paginas.", ephemeral=True)
        if index < 0 or index >= len(pages):
            return await interaction.response.send_message(
                f"Pagina invalida. Escolha entre 1 e {len(pages)}.",
                ephemeral=True,
            )

        self.parent_view.page_index = index
        embed, file = self.parent_view.render_embed_file()
        await interaction.response.edit_message(embed=embed, attachments=[file] if file else [], view=self.parent_view)


class ChapterInputModal(discord.ui.Modal, title="Selecionar Capitulo"):
    chapter = discord.ui.TextInput(
        label="Numero do capitulo",
        placeholder="Ex: 1",
        required=True,
        min_length=1,
        max_length=5,
    )

    def __init__(self, parent_view: "MangaReaderView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.chapter).strip()
        if not raw.isdigit():
            return await interaction.response.send_message("Digite um numero valido.", ephemeral=True)

        target_chapter = int(raw)
        chapters = self.parent_view.chapters
        if target_chapter < 1 or target_chapter > len(chapters):
            return await interaction.response.send_message(
                f"Capitulo invalido. Escolha entre 1 e {len(chapters)}.",
                ephemeral=True,
            )

        self.parent_view.chapter_index = target_chapter - 1
        self.parent_view.page_index = 0
        embed, file = self.parent_view.render_embed_file()
        await interaction.response.edit_message(embed=embed, attachments=[file] if file else [], view=self.parent_view)


class OnlinePageInputModal(discord.ui.Modal, title="Selecionar Pagina"):
    page = discord.ui.TextInput(
        label="Numero da pagina",
        placeholder="Ex: 12",
        required=True,
        min_length=1,
        max_length=5,
    )

    def __init__(self, parent_view: "OnlineMangaReaderView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.page).strip()
        if not raw.isdigit():
            return await interaction.response.send_message("Digite um numero valido.", ephemeral=True)

        pages = await self.parent_view.current_pages()
        if not pages:
            return await interaction.response.send_message("Esse capitulo ainda nao tem paginas.", ephemeral=True)

        index = int(raw) - 1
        if index < 0 or index >= len(pages):
            return await interaction.response.send_message(
                f"Pagina invalida. Escolha entre 1 e {len(pages)}.",
                ephemeral=True,
            )

        self.parent_view.page_index = index
        await self.parent_view.update_message(interaction)


class OnlineChapterInputModal(discord.ui.Modal, title="Selecionar Capitulo"):
    chapter = discord.ui.TextInput(
        label="Numero do capitulo",
        placeholder="Ex: 1",
        required=True,
        min_length=1,
        max_length=5,
    )

    def __init__(self, parent_view: "OnlineMangaReaderView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.chapter).strip()
        if not raw.isdigit():
            return await interaction.response.send_message("Digite um numero valido.", ephemeral=True)

        target_chapter = int(raw)
        if target_chapter < 1 or target_chapter > len(self.parent_view.chapters):
            return await interaction.response.send_message(
                f"Capitulo invalido. Escolha entre 1 e {len(self.parent_view.chapters)}.",
                ephemeral=True,
            )

        self.parent_view.chapter_index = target_chapter - 1
        self.parent_view.page_index = 0
        await self.parent_view.update_message(interaction)


class MangaReaderView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=900)
        self.user_id = user_id
        self.chapters = _get_chapters()
        self.chapter_index = 0
        self.page_index = 0
        self._sync_button_states()

    def current_chapter(self) -> Path | None:
        if not self.chapters:
            return None
        if self.chapter_index < 0:
            self.chapter_index = 0
        if self.chapter_index >= len(self.chapters):
            self.chapter_index = len(self.chapters) - 1
        return self.chapters[self.chapter_index]

    def current_pages(self) -> list[Path]:
        chapter = self.current_chapter()
        if chapter is None:
            return []
        return _get_pages(chapter)

    def _sync_button_states(self):
        pages = self.current_pages()
        has_pages = len(pages) > 0

        if has_pages:
            self.prev_btn.disabled = self.page_index <= 0
            self.next_btn.disabled = self.page_index >= len(pages) - 1
            self.download_btn.disabled = False
            self.pick_page_btn.disabled = False
        else:
            self.page_index = 0
            self.prev_btn.disabled = True
            self.next_btn.disabled = True
            self.download_btn.disabled = True
            self.pick_page_btn.disabled = True

        # Mantem o seletor de capitulo ativo apenas quando houver
        # mais de um capitulo disponivel para escolha.
        self.pick_chapter_btn.disabled = len(self.chapters) <= 1

    def render_embed_file(self) -> tuple[discord.Embed, discord.File | None]:
        self.chapters = _get_chapters()
        chapter = self.current_chapter()
        pages = self.current_pages()

        if chapter is None:
            self._sync_button_states()
            embed = discord.Embed(
                description="Nenhum capitulo encontrado.",
                color=0xEF4444,
            )
            return embed, None

        if self.page_index >= len(pages):
            self.page_index = max(0, len(pages) - 1)

        self._sync_button_states()
        chapter_number = self.chapter_index + 1

        if not pages:
            embed = _reader_embed_visual_frame(
                [
                    f"Capitulo {chapter_number}",
                    "Pagina 0/0",
                ],
                eyebrow=MANGA_LABEL.upper(),
                color=0xF59E0B,
            )
            return embed, None

        page_path = pages[self.page_index]
        raw = page_path.read_bytes()
        scaled, sfx = _scale_manga_page_for_discord(raw, page_path.suffix.lower() or ".jpg")
        filename = f"{page_path.stem}{sfx}"
        file = discord.File(io.BytesIO(scaled), filename=filename)
        embed = _reader_embed_visual_frame(
            [
                f"Capitulo {chapter_number} / {len(self.chapters)}",
                f"Pagina {self.page_index + 1} / {len(pages)}",
            ],
            eyebrow=MANGA_LABEL.upper(),
            color=0x22C55E,
            footer=f"Painel maior (~{int(MANGA_PAGE_DISPLAY_SCALE * 100)}% escala)",
        )
        embed.set_image(url=f"attachment://{filename}")
        return embed, file

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Somente quem abriu pode usar este painel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.page_index > 0:
            self.page_index -= 1
        embed, file = self.render_embed_file()
        await interaction.response.edit_message(embed=embed, attachments=[file] if file else [], view=self)

    @discord.ui.button(label="Proxima", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        pages = self.current_pages()
        if self.page_index < len(pages) - 1:
            self.page_index += 1
        embed, file = self.render_embed_file()
        await interaction.response.edit_message(embed=embed, attachments=[file] if file else [], view=self)

    @discord.ui.button(label="Baixar capitulo zip", style=discord.ButtonStyle.primary)
    async def download_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        chapter = self.current_chapter()
        pages = self.current_pages()
        if chapter is None or not pages:
            return await interaction.response.send_message("Sem paginas para baixar neste capitulo.", ephemeral=True)

        zip_name = f"{MANGA_ID}_{chapter.name}.zip"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        temp_zip_path = temp_file.name
        temp_file.close()

        try:
            with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                for page in pages:
                    zipf.write(page, arcname=page.name)

            try:
                await interaction.user.send(
                    content=f"Aqui esta o capitulo **{chapter.name}** de {MANGA_LABEL}.",
                    file=discord.File(temp_zip_path, filename=zip_name),
                )
            except discord.Forbidden:
                return await interaction.response.send_message(
                    "Nao consegui te enviar DM. Ative mensagens privadas e tente novamente.",
                    ephemeral=True,
                )

            await interaction.response.send_message("Capitulo enviado no seu PV em .zip.", ephemeral=True)
        finally:
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)

    @discord.ui.button(label="Selecionar pagina", style=discord.ButtonStyle.success)
    async def pick_page_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(PageInputModal(self))

    @discord.ui.button(label="Selecionar capitulo", style=discord.ButtonStyle.success)
    async def pick_chapter_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(ChapterInputModal(self))

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class OnlineMangaReaderView(discord.ui.View):
    def __init__(self, user_id: int, manga_data: dict[str, Any]):
        super().__init__(timeout=900)
        self.user_id = user_id
        self.manga_title = str(manga_data.get("title") or "Manga")
        self.cover_url = str(manga_data.get("cover_url") or "")
        self.chapters: list[dict[str, Any]] = []

        for chapter in manga_data.get("chapters", []):
            self.chapters.append(
                {
                    "title": str(chapter.get("title") or "Capitulo"),
                    "url": str(chapter.get("url") or ""),
                    "pages": None,
                }
            )

        self.chapter_index = 0
        self.page_index = 0
        self._sync_button_states([])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Somente quem abriu pode usar este painel.", ephemeral=True)
            return False
        return True

    def current_chapter(self) -> dict[str, Any] | None:
        if not self.chapters:
            return None
        if self.chapter_index < 0:
            self.chapter_index = 0
        if self.chapter_index >= len(self.chapters):
            self.chapter_index = len(self.chapters) - 1
        return self.chapters[self.chapter_index]

    async def current_pages(self) -> list[str]:
        chapter = self.current_chapter()
        if chapter is None:
            return []
        if chapter["pages"] is None:
            chapter_url = str(chapter.get("url") or "")
            pages = await asyncio.to_thread(_get_chapter_online_pages, chapter_url)
            chapter["pages"] = pages
        return list(chapter["pages"])

    def _sync_button_states(self, pages: list[str]):
        has_pages = len(pages) > 0
        if has_pages:
            self.prev_btn.disabled = self.page_index <= 0
            self.next_btn.disabled = self.page_index >= len(pages) - 1
            self.download_btn.disabled = False
            self.pick_page_btn.disabled = False
        else:
            self.page_index = 0
            self.prev_btn.disabled = True
            self.next_btn.disabled = True
            self.download_btn.disabled = True
            self.pick_page_btn.disabled = True

        self.prev_chapter_btn.disabled = self.chapter_index <= 0
        self.next_chapter_btn.disabled = self.chapter_index >= len(self.chapters) - 1
        self.pick_chapter_btn.disabled = len(self.chapters) <= 1

    async def render_embed_file(self) -> tuple[discord.Embed, discord.File | None]:
        chapter = self.current_chapter()
        pages = await self.current_pages()
        self._sync_button_states(pages)

        if chapter is None:
            return discord.Embed(description="Nenhum capitulo encontrado.", color=0xEF4444), None

        if self.page_index >= len(pages):
            self.page_index = max(0, len(pages) - 1)

        chapter_number = self.chapter_index + 1
        chapter_name = str(chapter.get("title") or f"Capitulo {chapter_number}")

        if not pages:
            embed = _reader_embed_visual_frame(
                [
                    f"Capitulo: {chapter_name}",
                    f"Indice: {chapter_number}/{len(self.chapters)}",
                    "Pagina: 0/0",
                ],
                eyebrow=str(self.manga_title),
                color=0xF59E0B,
                footer="Mangalivre (.to / blog)",
            )
            return embed, None

        page_url = pages[self.page_index]
        embed = _reader_embed_visual_frame(
            [
                f"Capitulo: {chapter_name}",
                f"Indice: {chapter_number}/{len(self.chapters)}",
                f"Pagina: {self.page_index + 1}/{len(pages)}",
            ],
            eyebrow=str(self.manga_title),
            color=0x22C55E,
            footer=f"Mangalivre (~{int(MANGA_PAGE_DISPLAY_SCALE * 100)}% maior)",
        )
        try:
            image_bytes = await asyncio.to_thread(_download_image_bytes, page_url)
            extension = Path(urlparse(page_url).path).suffix or ".jpg"
            scaled, sfx = await asyncio.to_thread(
                _scale_manga_page_for_discord, image_bytes, extension
            )
            filename = f"page_{self.page_index + 1:03d}{sfx}"
            file = discord.File(io.BytesIO(scaled), filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            return embed, file
        except requests.RequestException:
            embed.color = 0xF59E0B
            desc = embed.description or ""
            embed.description = (
                desc
                + "\n\n*Nao consegui carregar a imagem agora.*"
            ).strip()
            return embed, None

    async def update_message(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        embed, file = await self.render_embed_file()
        attachments = [file] if file else []
        await interaction.edit_original_response(embed=embed, attachments=attachments, view=self)

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.page_index > 0:
            self.page_index -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="Proxima", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        pages = await self.current_pages()
        if self.page_index < len(pages) - 1:
            self.page_index += 1
        await self.update_message(interaction)

    @discord.ui.button(label="Selecionar pagina", style=discord.ButtonStyle.success, row=0)
    async def pick_page_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(OnlinePageInputModal(self))

    @discord.ui.button(label="Selecionar capitulo", style=discord.ButtonStyle.success, row=0)
    async def pick_chapter_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(OnlineChapterInputModal(self))

    @discord.ui.button(label="Capitulo -", style=discord.ButtonStyle.secondary, row=1)
    async def prev_chapter_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.chapter_index > 0:
            self.chapter_index -= 1
            self.page_index = 0
        await self.update_message(interaction)

    @discord.ui.button(label="Capitulo +", style=discord.ButtonStyle.secondary, row=1)
    async def next_chapter_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.chapter_index < len(self.chapters) - 1:
            self.chapter_index += 1
            self.page_index = 0
        await self.update_message(interaction)

    @discord.ui.button(label="Baixar capitulo zip", style=discord.ButtonStyle.primary, row=1)
    async def download_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        chapter = self.current_chapter()
        pages = await self.current_pages()
        if chapter is None or not pages:
            return await interaction.followup.send("Sem paginas para baixar neste capitulo.", ephemeral=True)

        chapter_name = str(chapter.get("title") or f"capitulo_{self.chapter_index + 1}")
        sanitized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", chapter_name.lower())
        zip_name = f"mangalivre_{sanitized}.zip"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        temp_zip_path = temp_file.name
        temp_file.close()

        try:
            with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                for idx, page_url in enumerate(pages, start=1):
                    try:
                        image_bytes = await asyncio.to_thread(_download_image_bytes, page_url)
                    except requests.RequestException:
                        continue
                    extension = Path(urlparse(page_url).path).suffix or ".jpg"
                    arcname = f"{idx:03d}{extension}"
                    zipf.writestr(arcname, image_bytes)

            try:
                await interaction.user.send(
                    content=f"Aqui esta o capitulo **{chapter_name}** de {self.manga_title}.",
                    file=discord.File(temp_zip_path, filename=zip_name),
                )
            except discord.Forbidden:
                return await interaction.followup.send(
                    "Nao consegui te enviar DM. Ative mensagens privadas e tente novamente.",
                    ephemeral=True,
                )

            await interaction.followup.send("Capitulo enviado no seu PV em .zip.", ephemeral=True)
        finally:
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class MangaLauncherView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Somente quem executou o comando pode usar este botao.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label=MANGA_LABEL, style=discord.ButtonStyle.primary)
    async def open_reader(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = MangaReaderView(interaction.user.id)
        embed, file = view.render_embed_file()
        await interaction.response.edit_message(
            embed=embed,
            attachments=[file] if file else [],
            view=view,
        )


def _build_manga_setup_embed(
    entry: dict[str, str] | None,
    index: int,
    total: int,
    cover_url: str,
    *,
    mode_line: str = "Em lancamento",
    source_host: str = "mangalivre.blog",
) -> discord.Embed:
    if not entry:
        embed = discord.Embed(
            title=f"Manga Setup | {mode_line}",
            description=f"Nao encontrei itens no catalogo no momento ({source_host}).",
            color=0xEF4444,
        )
        embed.set_footer(text="Sem itens para exibir")
        return embed

    title = str(entry.get("title") or "Manga")
    embed = discord.Embed(
        title=title,
        description=f"{mode_line} | Item **{index}/{total}**",
        color=0x3B82F6,
    )
    if cover_url:
        embed.set_image(url=cover_url)
    embed.set_footer(text=f"Use Pagina - / Pagina + • {source_host}")
    return embed


def _build_manga_setup_list_embed(
    catalog: list[dict[str, str]],
    start_index: int,
    page_size: int = 8,
    *,
    source_host: str = "mangalivre.blog",
) -> discord.Embed:
    if not catalog:
        embed = discord.Embed(
            title="Manga Setup | Lista",
            description="Nenhum manga encontrado no momento.",
            color=0xEF4444,
        )
        embed.set_footer(text="Sem itens para exibir")
        return embed

    total = len(catalog)
    start = max(0, min(start_index, total - 1))
    end = min(total, start + page_size)
    lines = []
    for idx in range(start, end):
        title = str(catalog[idx].get("title") or "Manga")
        lines.append(f"`{idx + 1:02d}` {title}")

    embed = discord.Embed(
        title="Manga Setup | Modo Lista",
        description="\n".join(lines),
        color=0x3B82F6,
    )
    embed.set_footer(
        text=f"Mostrando {start + 1}-{end} de {total} • {source_host} • Use 'Selecionar numero'"
    )
    return embed


async def _open_online_reader_from_url(interaction: discord.Interaction, user_id: int, manga_url: str) -> bool:
    try:
        manga_data = await asyncio.to_thread(_get_manga_online_data, manga_url)
    except requests.RequestException:
        await interaction.followup.send(
            "Falha ao acessar o site agora. Tenta novamente em instantes.",
            ephemeral=True,
        )
        return False

    if not manga_data.get("chapters"):
        await interaction.followup.send(
            "Encontrei o manga, mas sem capitulos disponiveis.",
            ephemeral=True,
        )
        return False

    view = OnlineMangaReaderView(user_id, manga_data)
    embed, file = await view.render_embed_file()
    await interaction.edit_original_response(
        embed=embed,
        attachments=[file] if file else [],
        view=view,
    )
    return True


def _get_manga_cover_quick(manga_url: str) -> str:
    site = _infer_mangalivre_site(manga_url)
    try:
        page_html = _http_get_text(manga_url, site)
    except requests.RequestException:
        return ""
    return _extract_cover_url(page_html, site)


def _extract_max_pages_from_manga_list(page_html: str) -> int:
    candidates: set[int] = set()
    for match in re.finditer(r"/manga/page/(\d+)/", page_html, flags=re.IGNORECASE):
        try:
            candidates.add(int(match.group(1)))
        except ValueError:
            continue
    for match in re.finditer(
        r'/genero/[^/"\']+/page/(\d+)/', page_html, flags=re.IGNORECASE
    ):
        try:
            candidates.add(int(match.group(1)))
        except ValueError:
            continue
    for match in re.finditer(r"[?&](?:paged|page|sf_paged)=(\d+)", page_html, flags=re.IGNORECASE):
        try:
            candidates.add(int(match.group(1)))
        except ValueError:
            continue
    return max(candidates) if candidates else 1


def _build_setup_page_url(list_seed: str, page: int, pagination_mode: str) -> str:
    if page <= 1:
        return list_seed
    if pagination_mode == "wp_directory_page":
        if "?" in list_seed:
            path_part, query = list_seed.split("?", 1)
            path_part = path_part.rstrip("/")
            return f"{path_part}/page/{page}/?{query}"
        return f"{list_seed.rstrip('/')}/page/{page}/"

    sep = "&" if "?" in list_seed else "?"
    return f"{list_seed}{sep}paged={page}"


def _get_setup_manga_catalog(
    max_pages: int = 8,
    max_items: int = 120,
    site: MangalivreSite | None = None,
    list_seed: str | None = None,
    allow_loose_fallback: bool = True,
) -> list[dict[str, str]]:
    s = site or MANGALIVRE_BLOG_SITE
    seed = (list_seed if list_seed is not None else s.list_seed).strip()
    if not seed:
        seed = s.list_seed
    catalog: list[dict[str, str]] = []
    seen: set[str] = set()
    discovered_pages = 1

    for page in range(1, max_pages + 1):
        target_url = _build_setup_page_url(seed, page, s.pagination_mode)
        try:
            page_html = _http_get_text(target_url, s)
        except requests.RequestException:
            if page == 1:
                break
            continue

        discovered_pages = max(discovered_pages, _extract_max_pages_from_manga_list(page_html))
        page_items = _extract_manga_cards_from_listing(page_html, s)
        if not page_items and allow_loose_fallback:
            page_items = _extract_manga_links_from_html(page_html, s)
        if not page_items and page > 1:
            break

        new_count = 0
        for item in page_items:
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            catalog.append(item)
            new_count += 1
            if len(catalog) >= max_items:
                return catalog

        if new_count == 0 and page > 1:
            break
        if page >= discovered_pages:
            break

    return catalog


class NiaddPageInputModal(discord.ui.Modal, title="Selecionar Pagina"):
    page = discord.ui.TextInput(
        label="Numero da pagina",
        placeholder="Ex: 12",
        required=True,
        min_length=1,
        max_length=5,
    )

    def __init__(self, parent_view: "NiaddReaderView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.page).strip()
        if not raw.isdigit():
            return await interaction.response.send_message("Digite um numero valido.", ephemeral=True)

        pages = await self.parent_view.current_pages()
        if not pages:
            return await interaction.response.send_message("Esse capitulo ainda nao tem paginas.", ephemeral=True)

        index = int(raw) - 1
        if index < 0 or index >= len(pages):
            return await interaction.response.send_message(
                f"Pagina invalida. Escolha entre 1 e {len(pages)}.",
                ephemeral=True,
            )

        self.parent_view.page_index = index
        await self.parent_view.update_message(interaction)


class NiaddChapterInputModal(discord.ui.Modal, title="Selecionar Capitulo"):
    chapter = discord.ui.TextInput(
        label="Numero do capitulo",
        placeholder="Ex: 1",
        required=True,
        min_length=1,
        max_length=5,
    )

    def __init__(self, parent_view: "NiaddReaderView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.chapter).strip()
        if not raw.isdigit():
            return await interaction.response.send_message("Digite um numero valido.", ephemeral=True)

        target = int(raw)
        if target < 1 or target > len(self.parent_view.chapters):
            return await interaction.response.send_message(
                f"Capitulo invalido. Escolha entre 1 e {len(self.parent_view.chapters)}.",
                ephemeral=True,
            )

        self.parent_view.chapter_index = target - 1
        self.parent_view.page_index = 0
        await self.parent_view.update_message(interaction)


class NiaddReaderView(discord.ui.View):
    def __init__(self, user_id: int, manga_data: dict[str, Any]):
        super().__init__(timeout=900)
        self.user_id = user_id
        self.manga_title = str(manga_data.get("title") or "Manga")
        self.cover_url = str(manga_data.get("cover_url") or "")
        self.manga_slug = str(manga_data.get("slug") or "")
        self.chapters: list[dict[str, Any]] = []

        for chapter in manga_data.get("chapters", []) or []:
            self.chapters.append(
                {
                    "title": str(chapter.get("title") or "Capitulo"),
                    "chapter_id": str(chapter.get("chapter_id") or ""),
                    "chapter_slug": str(chapter.get("chapter_slug") or ""),
                    "url": str(chapter.get("url") or ""),
                    "pages": None,
                }
            )

        self.chapter_index = 0
        self.page_index = 0
        self._sync_button_states([])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Somente quem abriu pode usar este painel.", ephemeral=True)
            return False
        return True

    def current_chapter(self) -> dict[str, Any] | None:
        if not self.chapters:
            return None
        if self.chapter_index < 0:
            self.chapter_index = 0
        if self.chapter_index >= len(self.chapters):
            self.chapter_index = len(self.chapters) - 1
        return self.chapters[self.chapter_index]

    async def current_pages(self) -> list[str]:
        chapter = self.current_chapter()
        if chapter is None:
            return []
        if chapter["pages"] is None:
            slug = chapter.get("chapter_slug") or ""
            cid = chapter.get("chapter_id") or ""
            if not slug or not cid:
                chapter["pages"] = []
            else:
                try:
                    chapter["pages"] = await asyncio.to_thread(niadd.fetch_chapter_pages, slug, cid)
                except requests.RequestException:
                    chapter["pages"] = []
        return list(chapter["pages"] or [])

    def _sync_button_states(self, pages: list[str]):
        has_pages = len(pages) > 0
        if has_pages:
            self.prev_btn.disabled = self.page_index <= 0
            self.next_btn.disabled = self.page_index >= len(pages) - 1
            self.download_btn.disabled = False
            self.pick_page_btn.disabled = False
        else:
            self.page_index = 0
            self.prev_btn.disabled = True
            self.next_btn.disabled = True
            self.download_btn.disabled = True
            self.pick_page_btn.disabled = True

        self.prev_chapter_btn.disabled = self.chapter_index <= 0
        self.next_chapter_btn.disabled = self.chapter_index >= len(self.chapters) - 1
        self.pick_chapter_btn.disabled = len(self.chapters) <= 1
        self.first_chapter_btn.disabled = len(self.chapters) <= 1 or self.chapter_index == 0
        self.last_chapter_btn.disabled = (
            len(self.chapters) <= 1 or self.chapter_index == len(self.chapters) - 1
        )

    async def render_embed_file(self) -> tuple[discord.Embed, discord.File | None]:
        chapter = self.current_chapter()
        pages = await self.current_pages()
        self._sync_button_states(pages)

        if chapter is None:
            return discord.Embed(description="Nenhum capitulo encontrado.", color=0xEF4444), None

        if self.page_index >= len(pages):
            self.page_index = max(0, len(pages) - 1)

        chapter_number = self.chapter_index + 1
        chapter_name = str(chapter.get("title") or f"Capitulo {chapter_number}")

        if not pages:
            embed = _reader_embed_visual_frame(
                [
                    f"Capitulo: {chapter_name}",
                    f"Indice: {chapter_number}/{len(self.chapters)}",
                    "Sem paginas disponiveis.",
                ],
                eyebrow=str(self.manga_title),
                color=0xF59E0B,
                footer=f"niadd • {self.manga_slug}",
            )
            return embed, None

        page_url = pages[self.page_index]
        embed = _reader_embed_visual_frame(
            [
                f"Capitulo: {chapter_name}",
                f"Indice: {chapter_number}/{len(self.chapters)}",
                f"Pagina: {self.page_index + 1}/{len(pages)}",
            ],
            eyebrow=str(self.manga_title),
            color=0x22C55E,
            footer=(
                f"niadd • {self.manga_slug} • "
                f"~{int(MANGA_PAGE_DISPLAY_SCALE * 100)}% • Inicio / Fim mudam capitulo"
            ),
        )

        try:
            image_bytes = await asyncio.to_thread(niadd.download_image_bytes, page_url)
            extension = Path(urlparse(page_url).path).suffix or ".jpg"
            scaled, sfx = await asyncio.to_thread(
                _scale_manga_page_for_discord, image_bytes, extension
            )
            filename = f"page_{self.page_index + 1:03d}{sfx}"
            file = discord.File(io.BytesIO(scaled), filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            return embed, file
        except requests.RequestException:
            embed.color = 0xF59E0B
            desc = embed.description or ""
            embed.description = (
                desc
                + "\n\n*Nao consegui carregar a imagem agora.*"
            ).strip()
            return embed, None

    async def update_message(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        embed, file = await self.render_embed_file()
        attachments = [file] if file else []
        await interaction.edit_original_response(embed=embed, attachments=attachments, view=self)

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.page_index > 0:
            self.page_index -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="Proxima", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        pages = await self.current_pages()
        if self.page_index < len(pages) - 1:
            self.page_index += 1
        await self.update_message(interaction)

    @discord.ui.button(label="Selecionar pagina", style=discord.ButtonStyle.success, row=0)
    async def pick_page_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(NiaddPageInputModal(self))

    @discord.ui.button(label="Selecionar capitulo", style=discord.ButtonStyle.success, row=0)
    async def pick_chapter_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(NiaddChapterInputModal(self))

    @discord.ui.button(label="Baixar capitulo zip", style=discord.ButtonStyle.primary, row=0)
    async def download_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        chapter = self.current_chapter()
        pages = await self.current_pages()
        if chapter is None or not pages:
            return await interaction.followup.send("Sem paginas para baixar neste capitulo.", ephemeral=True)

        chapter_name = str(chapter.get("title") or f"capitulo_{self.chapter_index + 1}")
        sanitized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", chapter_name.lower())
        zip_name = f"niadd_{sanitized}.zip"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        temp_zip_path = temp_file.name
        temp_file.close()

        try:
            with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                for idx, page_url in enumerate(pages, start=1):
                    try:
                        image_bytes = await asyncio.to_thread(niadd.download_image_bytes, page_url)
                    except requests.RequestException:
                        continue
                    extension = Path(urlparse(page_url).path).suffix or ".jpg"
                    arcname = f"{idx:03d}{extension}"
                    zipf.writestr(arcname, image_bytes)

            try:
                await interaction.user.send(
                    content=f"Aqui esta o capitulo **{chapter_name}** de {self.manga_title}.",
                    file=discord.File(temp_zip_path, filename=zip_name),
                )
            except discord.Forbidden:
                return await interaction.followup.send(
                    "Nao consegui te enviar DM. Ative mensagens privadas e tente novamente.",
                    ephemeral=True,
                )

            await interaction.followup.send("Capitulo enviado no seu PV em .zip.", ephemeral=True)
        finally:
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)

    @discord.ui.button(label="Inicio", style=discord.ButtonStyle.secondary, row=1)
    async def first_chapter_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.chapters and self.chapter_index != 0:
            self.chapter_index = 0
            self.page_index = 0
        await self.update_message(interaction)

    @discord.ui.button(label="Capitulo -", style=discord.ButtonStyle.secondary, row=1)
    async def prev_chapter_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.chapter_index > 0:
            self.chapter_index -= 1
            self.page_index = 0
        await self.update_message(interaction)

    @discord.ui.button(label="Capitulo +", style=discord.ButtonStyle.secondary, row=1)
    async def next_chapter_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.chapter_index < len(self.chapters) - 1:
            self.chapter_index += 1
            self.page_index = 0
        await self.update_message(interaction)

    @discord.ui.button(label="Fim", style=discord.ButtonStyle.secondary, row=1)
    async def last_chapter_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.chapters and self.chapter_index != len(self.chapters) - 1:
            self.chapter_index = len(self.chapters) - 1
            self.page_index = 0
        await self.update_message(interaction)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


async def _open_niadd_reader_from_slug(interaction: discord.Interaction, user_id: int, slug: str) -> bool:
    try:
        manga_data = await asyncio.to_thread(niadd.fetch_manga_detail, slug)
    except (requests.RequestException, ValueError):
        await interaction.followup.send(
            "Falha ao acessar o niadd agora. Tenta novamente em instantes.",
            ephemeral=True,
        )
        return False

    if not manga_data.get("chapters"):
        await interaction.followup.send(
            "Encontrei o manga, mas sem capitulos disponiveis no niadd.",
            ephemeral=True,
        )
        return False

    view = NiaddReaderView(user_id, manga_data)
    embed, file = await view.render_embed_file()
    await interaction.edit_original_response(
        embed=embed,
        attachments=[file] if file else [],
        view=view,
    )
    return True


def _build_niadd_setup_embed(
    entry: dict[str, Any] | None,
    index: int,
    total: int,
    category: str = "Todos (catalogo combinado)",
    search_query: str = "",
) -> discord.Embed:
    is_search = bool(search_query)
    header_title = (
        f"Resultados para: {search_query!r}" if is_search else f"niadd | {category}"
    )
    color = 0x6366F1 if is_search else 0x10B981

    if not entry:
        embed = discord.Embed(
            title=header_title,
            description=(
                "Nao encontrei nenhum manga com esse termo."
                if is_search
                else "Nao encontrei mangas nessa categoria no momento."
            ),
            color=0xEF4444,
        )
        embed.set_footer(
            text=(
                "Tente outras palavras ou verifique a grafia"
                if is_search
                else "Tente outra categoria pelo menu de baixo"
            )
        )
        return embed

    title = str(entry.get("title") or "Manga")
    if is_search:
        description = (
            f"Busca: **{search_query}**\n"
            f"**Item:** {index}/{total}"
        )
        footer = "Niadd PT-BR • Trocar categoria limpa a busca"
    else:
        description = (
            f"**Categoria:** {category}\n"
            f"**Item:** {index}/{total}"
        )
        footer = "Niadd PT-BR • Pagina -/+ navega • Modo Lista mostra varios"

    embed = discord.Embed(title=title, description=description, color=color)
    cover = str(entry.get("cover_url") or "")
    if cover:
        embed.set_image(url=cover)
    embed.set_footer(text=footer)
    return embed


def _build_niadd_setup_list_embed(
    catalog: list[dict[str, Any]],
    start_index: int,
    page_size: int = 8,
    category: str = "Todos (catalogo combinado)",
    search_query: str = "",
) -> discord.Embed:
    is_search = bool(search_query)
    header_title = (
        f"Resultados para: {search_query!r}" if is_search else f"niadd | Lista | {category}"
    )
    color = 0x6366F1 if is_search else 0x10B981

    if not catalog:
        embed = discord.Embed(
            title=header_title,
            description=(
                "Nao encontrei nenhum manga com esse termo."
                if is_search
                else "Nenhum manga encontrado nessa categoria."
            ),
            color=0xEF4444,
        )
        embed.set_footer(
            text=(
                "Tente outras palavras ou verifique a grafia"
                if is_search
                else "Tente outra categoria pelo menu de baixo"
            )
        )
        return embed

    total = len(catalog)
    start = max(0, min(start_index, total - 1))
    end = min(total, start + page_size)
    lines = []
    for idx in range(start, end):
        title = str(catalog[idx].get("title") or "Manga")
        lines.append(f"`{idx + 1:03d}` {title}")

    embed = discord.Embed(
        title=header_title,
        description="\n".join(lines),
        color=color,
    )
    embed.set_footer(
        text=f"Mostrando {start + 1}-{end} de {total} • Selecionar numero pula direto"
    )
    return embed


class MangaSetupSearchModal(discord.ui.Modal, title="Pesquisar Manga"):
    termo = discord.ui.TextInput(
        label="Nome ou URL do manga",
        placeholder="Ex: gamer ga isekai",
        required=True,
        min_length=2,
        max_length=180,
    )

    def __init__(self, parent_view: "MangaSetupView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        raw = str(self.termo).strip()

        if self.parent_view.server == 2:
            # A busca usa a categoria atual como contexto: se a categoria
            # estiver restrita, a busca tambem fica.
            if not self.parent_view._user_can_use(interaction.user):
                roles_text = self.parent_view._format_required_roles(
                    self.parent_view.guild_id, self.parent_view.category
                )
                return await interaction.followup.send(
                    f"Voce nao tem cargo permitido pra usar a categoria "
                    f"**{self.parent_view.category}**.\nCargo(s) liberado(s): {roles_text}",
                    ephemeral=True,
                )

            # 1) URL direta -> abre na hora
            niadd_match = re.search(r"br\.niadd\.com/manga/([^/?#]+)\.html", raw)
            if niadd_match:
                slug = niadd_match.group(1)
                return await _open_niadd_reader_from_slug(
                    interaction, interaction.user.id, slug
                )

            # 2) Busca tolerante (case + acentos + typos + ordem livre)
            suggestions = await asyncio.to_thread(niadd.search_titles, raw, 12, 25)

            if not suggestions:
                return await interaction.followup.send(
                    f"Nao achei nenhum manga com **{raw}**.\n"
                    "Tenta outras palavras, parte do titulo ou o autor.",
                    ephemeral=True,
                )

            # 3a) Match unico -> abre direto
            if len(suggestions) == 1:
                slug = str(suggestions[0]["slug"])
                if not slug:
                    return await interaction.followup.send(
                        "Nao consegui identificar o manga.", ephemeral=True
                    )
                return await _open_niadd_reader_from_slug(
                    interaction, interaction.user.id, slug
                )

            # 3b) Varios resultados -> mostra os no painel pra escolher
            self.parent_view.apply_search_results(raw, suggestions)
            embed = await self.parent_view.build_embed()
            return await interaction.edit_original_response(
                embed=embed, view=self.parent_view
            )

        if self.parent_view.server == 3:
            if not self.parent_view._user_can_use_mlto(interaction.user):
                roles_text = self.parent_view._format_required_roles_mlto(
                    self.parent_view.guild_id, self.parent_view.category_mlto
                )
                return await interaction.followup.send(
                    f"Voce nao tem cargo permitido pra usar a categoria "
                    f"**{self.parent_view.category_mlto}** (Manga Livre).\n"
                    f"Cargo(s) liberado(s): {roles_text}",
                    ephemeral=True,
                )

        site_ml = _mangalivre_site_for_setup_server(self.parent_view.server)
        manga_url = ""
        if "/manga/" in raw:
            manga_url = _normalize_manga_url(raw, site_ml)
        else:
            suggestions = await asyncio.to_thread(_search_manga_online, raw, 12, site_ml)
            if not suggestions:
                return await interaction.followup.send("Nao achei esse manga.", ephemeral=True)
            manga_url = suggestions[0]["url"]
        await _open_online_reader_from_url(interaction, interaction.user.id, manga_url)


class MangaSetupNumberModal(discord.ui.Modal, title="Selecionar Manga por Numero"):
    numero = discord.ui.TextInput(
        label="Numero do manga",
        placeholder="Ex: 3",
        required=True,
        min_length=1,
        max_length=4,
    )

    def __init__(self, parent_view: "MangaSetupView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.numero).strip()
        if not raw.isdigit():
            return await interaction.response.send_message("Digite um numero valido.", ephemeral=True)
        if not self.parent_view.catalog:
            return await interaction.response.send_message("A lista esta vazia no momento.", ephemeral=True)

        index = int(raw) - 1
        if index < 0 or index >= len(self.parent_view.catalog):
            return await interaction.response.send_message(
                f"Numero invalido. Escolha entre 1 e {len(self.parent_view.catalog)}.",
                ephemeral=True,
            )

        self.parent_view.item_index = index
        entry = self.parent_view._current_entry()
        if not entry:
            return await interaction.response.send_message("Nao consegui abrir esse manga.", ephemeral=True)

        if self.parent_view.server == 2 and not self.parent_view._user_can_use(interaction.user):
            roles_text = self.parent_view._format_required_roles(
                self.parent_view.guild_id, self.parent_view.category
            )
            return await interaction.response.send_message(
                f"Voce nao tem cargo permitido pra abrir mangas da categoria "
                f"**{self.parent_view.category}**.\nCargo(s) liberado(s): {roles_text}",
                ephemeral=True,
            )

        if self.parent_view.server == 3 and not self.parent_view._user_can_use_mlto(interaction.user):
            roles_text = self.parent_view._format_required_roles_mlto(
                self.parent_view.guild_id, self.parent_view.category_mlto
            )
            return await interaction.response.send_message(
                f"Voce nao tem cargo permitido pra abrir mangas da categoria "
                f"**{self.parent_view.category_mlto}** (Manga Livre).\n"
                f"Cargo(s) liberado(s): {roles_text}",
                ephemeral=True,
            )

        await interaction.response.defer()

        if self.parent_view.server == 2:
            slug = str(entry.get("slug") or "")
            if not slug:
                return await interaction.followup.send("Nao consegui abrir esse manga.", ephemeral=True)
            return await _open_niadd_reader_from_slug(interaction, interaction.user.id, slug)

        manga_url = str(entry.get("url") or "")
        if not manga_url:
            return await interaction.followup.send("Nao consegui abrir esse manga.", ephemeral=True)
        await _open_online_reader_from_url(interaction, interaction.user.id, manga_url)


_ADULT_CATEGORY_KEYWORDS = (
    "18",
    "+18",
    "adult",
    "ecchi",
    "hentai",
    "nsfw",
    "doujin",
    "porno",
    "porn",
    "erot",
)


def _is_adult_category_label(label: str) -> bool:
    norm = (label or "").strip().lower()
    if not norm:
        return False
    return any(key in norm for key in _ADULT_CATEGORY_KEYWORDS)


def _safe_niadd_categories() -> list[str]:
    categories = [str(k) for k in niadd.CATEGORIES.keys() if not _is_adult_category_label(str(k))]
    if not categories:
        categories = [niadd.DEFAULT_CATEGORY]
    if niadd.DEFAULT_CATEGORY in categories:
        categories.sort(key=lambda x: (x != niadd.DEFAULT_CATEGORY, x.lower()))
    else:
        categories.sort(key=lambda x: x.lower())
    return categories


def _build_category_options(active: str) -> list[discord.SelectOption]:
    options: list[discord.SelectOption] = []
    safe_categories = _safe_niadd_categories()
    current = active if active in safe_categories else safe_categories[0]
    for label in safe_categories:
        # Discord limita o label da opcao em 100 chars; nossos labels sao curtos.
        options.append(
            discord.SelectOption(
                label=label[:100],
                value=label[:100],
                default=(label == current),
            )
        )
    return options


class MangaSetupView(discord.ui.View):
    def __init__(self, user_id: int, server: int = 1, guild_id: int = 0):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.guild_id = int(guild_id or 0)
        self.server = 1 if server not in (1, 2, 3) else server
        self.catalog: list[dict[str, Any]] = []
        self.item_index = 0
        self.cover_cache: dict[str, str] = {}
        self.list_mode = False
        self.list_page_size = 8
        safe_cats = _safe_niadd_categories()
        self.category = niadd.DEFAULT_CATEGORY if niadd.DEFAULT_CATEGORY in safe_cats else safe_cats[0]
        self.category_mlto = MANGALIVRE_TO_DEFAULT_CATEGORY
        self.mlto_cat_page = 0
        self.search_query: str = ""
        self._refresh_lock = asyncio.Lock()
        self._sync_buttons()

    def _user_can_use(self, user: discord.abc.User | None, category: str | None = None) -> bool:
        cat = category or self.category
        return manga_perms.member_can_access(user, self.guild_id, cat)

    def _user_can_use_mlto(
        self,
        user: discord.abc.User | None,
        category_label: str | None = None,
    ) -> bool:
        lab = category_label if category_label is not None else self.category_mlto
        return manga_perms.member_can_access_mlto(user, self.guild_id, lab)

    @staticmethod
    def _format_required_roles(guild_id: int, category: str) -> str:
        ids = manga_perms.get_required_roles(guild_id, category)
        if not ids:
            return ""
        return ", ".join(f"<@&{rid}>" for rid in ids)

    @staticmethod
    def _format_required_roles_mlto(guild_id: int, category_label: str) -> str:
        ids = manga_perms.get_required_roles_mlto(guild_id, category_label)
        if not ids:
            return ""
        return ", ".join(f"<@&{rid}>" for rid in ids)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Somente quem abriu pode usar este painel.", ephemeral=True)
            return False
        return True

    async def load_catalog(self):
        # Recarregar o catalogo sempre limpa o estado de busca.
        self.search_query = ""
        if self.server == 2:
            try:
                catalog = await asyncio.to_thread(niadd.fetch_category, self.category)
            except requests.RequestException:
                catalog = []
        elif self.server == 3:
            ml_pages, ml_items = _mlto_catalog_fetch_limits(self.category_mlto)
            seed = _mlto_category_list_seed(self.category_mlto)
            catalog = await asyncio.to_thread(
                _get_setup_manga_catalog, ml_pages, ml_items, MANGALIVRE_TO_SITE, seed, False
            )
        else:
            site_ml = _mangalivre_site_for_setup_server(self.server)
            catalog = await asyncio.to_thread(_get_setup_manga_catalog, 8, 120, site_ml)

        self.catalog = catalog
        self.cover_cache.clear()
        self.item_index = 0
        self._sync_buttons()

    def apply_search_results(self, query: str, results: list[dict[str, Any]]):
        """Substitui o catalogo pelos resultados de busca (modo busca ativo)."""
        self.search_query = query
        self.catalog = list(results)
        self.cover_cache.clear()
        self.item_index = 0
        self.list_mode = False
        self._sync_buttons()

    def _current_entry(self) -> dict[str, Any] | None:
        if not self.catalog:
            return None
        if self.item_index < 0:
            self.item_index = 0
        if self.item_index >= len(self.catalog):
            self.item_index = len(self.catalog) - 1
        return self.catalog[self.item_index]

    def _list_start_index(self) -> int:
        if not self.catalog:
            return 0
        page = self.item_index // self.list_page_size
        return page * self.list_page_size

    def _refresh_category_select_options(self):
        if self.server == 2:
            self.category_select.options = _build_category_options(self.category)
            return
        if self.server == 3:
            self.category_select.options = _build_mlto_category_select_options(
                self.category_mlto,
                self.mlto_cat_page,
            )
            return
        self.category_select.options = [
            discord.SelectOption(label="—", value="—", default=True),
        ]

    def _sync_buttons(self):
        self._refresh_category_select_options()
        has_catalog = len(self.catalog) > 0

        if self.server == 1:
            active_server = "1"
        elif self.server == 2:
            active_server = "2"
        else:
            active_server = "3"
        self.server_select.options = [
            discord.SelectOption(label="Servidor 1 (mangalivre.blog)", value="1", default=(active_server == "1")),
            discord.SelectOption(label="Servidor 2 (Niadd)", value="2", default=(active_server == "2")),
            discord.SelectOption(label="Servidor 3 (Manga Livre .to)", value="3", default=(active_server == "3")),
        ]
        self.server_select.placeholder = "Escolher servidor"

        if self.server == 2:
            self.category_select.disabled = False
            self.category_select.placeholder = f"Niadd: {self.category}"
        elif self.server == 3:
            self.category_select.disabled = False
            self.category_select.placeholder = (
                f"M.Livre: {self.category_mlto}" + (" (pag.2)" if self.mlto_cat_page else "")
            )
        else:
            self.category_select.disabled = True
            self.category_select.placeholder = "Categoria"

        if not has_catalog:
            self.prev_page_btn.disabled = True
            self.next_page_btn.disabled = True
            self.select_btn.disabled = True
            self.select_number_btn.disabled = True
            self.mode_btn.label = "Modo Lista" if not self.list_mode else "Modo Foto"
            return

        if self.list_mode:
            start = self._list_start_index()
            self.prev_page_btn.disabled = start <= 0
            self.next_page_btn.disabled = (start + self.list_page_size) >= len(self.catalog)
            self.select_btn.disabled = True
            self.select_number_btn.disabled = False
            self.mode_btn.label = "Modo Foto"
        else:
            self.prev_page_btn.disabled = self.item_index <= 0
            self.next_page_btn.disabled = self.item_index >= len(self.catalog) - 1
            self.select_btn.disabled = False
            self.select_number_btn.disabled = True
            self.mode_btn.label = "Modo Lista"

    async def build_embed(self) -> discord.Embed:
        self._sync_buttons()

        if self.server == 2:
            if self.list_mode:
                return _build_niadd_setup_list_embed(
                    self.catalog,
                    self._list_start_index(),
                    self.list_page_size,
                    self.category,
                    self.search_query,
                )
            current = self._current_entry()
            return _build_niadd_setup_embed(
                current,
                self.item_index + 1 if current else 0,
                len(self.catalog),
                self.category,
                self.search_query,
            )

        if self.server == 3:
            mode_line = f"Catalogo • {self.category_mlto}"
            source_host = "mangalivre.to"
        else:
            mode_line = "Em lancamento"
            source_host = "mangalivre.blog"

        if self.list_mode:
            return _build_manga_setup_list_embed(
                self.catalog,
                self._list_start_index(),
                self.list_page_size,
                source_host=source_host,
            )

        current = self._current_entry()
        if not current:
            self._sync_buttons()
            return _build_manga_setup_embed(None, 0, 0, "", mode_line=mode_line, source_host=source_host)

        current_url = str(current.get("url") or "")
        cover_url = str(current.get("cover_url") or "")
        if cover_url:
            self.cover_cache[current_url] = cover_url
        else:
            cover_url = self.cover_cache.get(current_url, "")
        if not cover_url and current_url:
            cover_url = await asyncio.to_thread(_get_manga_cover_quick, current_url)
            self.cover_cache[current_url] = cover_url

        self._sync_buttons()
        return _build_manga_setup_embed(
            current,
            self.item_index + 1,
            len(self.catalog),
            cover_url,
            mode_line=mode_line,
            source_host=source_host,
        )

    async def refresh(self, interaction: discord.Interaction, *, reload_catalog: bool = False):
        async with self._refresh_lock:
            can_use_original_response = True
            if not interaction.response.is_done():
                try:
                    await interaction.response.defer()
                except discord.NotFound:
                    # Interacao expirou antes do ACK (Discord code 10062).
                    # Ainda tentamos atualizar a mensagem da view diretamente.
                    can_use_original_response = False
            if reload_catalog or not self.catalog:
                await self.load_catalog()
            embed = await self.build_embed()
            if can_use_original_response:
                try:
                    await interaction.edit_original_response(embed=embed, view=self)
                    return
                except discord.NotFound:
                    # Token expirado: cai para edicao direta da mensagem.
                    pass

            if interaction.message is not None:
                await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Pagina -", style=discord.ButtonStyle.secondary, row=0)
    async def prev_page_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.catalog:
            return await interaction.response.send_message("A lista esta vazia no momento.", ephemeral=True)
        if self.list_mode:
            self.item_index = max(0, self.item_index - self.list_page_size)
        elif self.item_index > 0:
            self.item_index -= 1
        await self.refresh(interaction)

    @discord.ui.button(label="Pagina +", style=discord.ButtonStyle.secondary, row=0)
    async def next_page_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.catalog:
            return await interaction.response.send_message("A lista esta vazia no momento.", ephemeral=True)
        if self.list_mode:
            self.item_index = min(len(self.catalog) - 1, self.item_index + self.list_page_size)
        elif self.item_index < len(self.catalog) - 1:
            self.item_index += 1
        await self.refresh(interaction)

    @discord.ui.button(label="Modo Lista", style=discord.ButtonStyle.secondary, row=1)
    async def mode_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.list_mode = not self.list_mode
        await self.refresh(interaction)

    @discord.ui.button(label="Selecionar/Ler", style=discord.ButtonStyle.success, row=1)
    async def select_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        current = self._current_entry()
        if not current:
            return await interaction.response.send_message("Nao consegui abrir esse manga.", ephemeral=True)

        if self.server == 2 and not self._user_can_use(interaction.user):
            roles_text = self._format_required_roles(self.guild_id, self.category)
            return await interaction.response.send_message(
                f"Voce nao tem cargo permitido pra abrir mangas da categoria **{self.category}**.\n"
                f"Cargo(s) liberado(s): {roles_text}",
                ephemeral=True,
            )

        if self.server == 3 and not self._user_can_use_mlto(interaction.user):
            roles_text = self._format_required_roles_mlto(self.guild_id, self.category_mlto)
            return await interaction.response.send_message(
                f"Voce nao tem cargo permitido pra abrir mangas da categoria "
                f"**{self.category_mlto}** (Manga Livre).\n"
                f"Cargo(s) liberado(s): {roles_text}",
                ephemeral=True,
            )

        await interaction.response.defer()

        if self.server == 2:
            slug = str(current.get("slug") or "")
            if not slug:
                return await interaction.followup.send("Nao consegui abrir esse manga.", ephemeral=True)
            return await _open_niadd_reader_from_slug(interaction, interaction.user.id, slug)

        manga_url = str(current.get("url") or "")
        if not manga_url:
            return await interaction.followup.send("Nao consegui abrir esse manga.", ephemeral=True)
        await _open_online_reader_from_url(interaction, interaction.user.id, manga_url)

    @discord.ui.button(label="Selecionar numero", style=discord.ButtonStyle.success, row=1)
    async def select_number_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(MangaSetupNumberModal(self))

    @discord.ui.button(label="Pesquisar manga", style=discord.ButtonStyle.primary, row=4)
    async def search_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(MangaSetupSearchModal(self))

    @discord.ui.select(
        placeholder="Escolher servidor",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Servidor 1 (mangalivre.blog)", value="1", default=True),
            discord.SelectOption(label="Servidor 2 (Niadd)", value="2"),
            discord.SelectOption(label="Servidor 3 (Manga Livre .to)", value="3"),
        ],
        row=2,
    )
    async def server_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        chosen = select.values[0] if select.values else "1"
        try:
            new_server = int(chosen)
        except ValueError:
            new_server = 1
        if new_server not in (1, 2, 3):
            new_server = 1
        if new_server == self.server:
            return await self.refresh(interaction)
        self.server = new_server
        self.list_mode = False
        self.search_query = ""
        if self.server == 3:
            self.category_mlto = MANGALIVRE_TO_DEFAULT_CATEGORY
            self.mlto_cat_page = 0
        if self.server != 2:
            safe_cats = _safe_niadd_categories()
            self.category = niadd.DEFAULT_CATEGORY if niadd.DEFAULT_CATEGORY in safe_cats else safe_cats[0]
        await self.refresh(interaction, reload_catalog=True)

    @discord.ui.select(
        placeholder="Categoria (apenas Servidor 2)",
        min_values=1,
        max_values=1,
        options=[discord.SelectOption(label="Todos", value="Todos", default=True)],
        row=3,
    )
    async def category_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        chosen = select.values[0] if select.values else niadd.DEFAULT_CATEGORY

        if self.server == 3:
            await interaction.response.defer()
            if chosen == _MLTO_NAV_NEXT:
                self.mlto_cat_page = 1
                await interaction.edit_original_response(embed=await self.build_embed(), view=self)
                return
            if chosen == _MLTO_NAV_PREV:
                self.mlto_cat_page = 0
                await interaction.edit_original_response(embed=await self.build_embed(), view=self)
                return

            if chosen not in _MLTO_CATEGORY_LABELS:
                await interaction.followup.send("Categoria invalida.", ephemeral=True)
                return
            if not self._user_can_use_mlto(interaction.user, chosen):
                roles_text = self._format_required_roles_mlto(self.guild_id, chosen)
                return await interaction.followup.send(
                    f"Voce nao tem cargo permitido pra usar a categoria **{chosen}** "
                    "(Manga Livre).\n"
                    f"Cargo(s) liberado(s): {roles_text}",
                    ephemeral=True,
                )
            if chosen == self.category_mlto:
                await interaction.edit_original_response(embed=await self.build_embed(), view=self)
                return
            self.category_mlto = chosen
            self.list_mode = False
            async with self._refresh_lock:
                await self.load_catalog()
                await interaction.edit_original_response(embed=await self.build_embed(), view=self)
            return

        if self.server != 2:
            return await interaction.response.send_message(
                "O filtro por categoria so funciona nos Servidor 2 (Niadd) e Servidor 3 (Manga Livre).",
                ephemeral=True,
            )

        safe_cats = _safe_niadd_categories()
        if chosen not in safe_cats:
            return await interaction.response.send_message("Categoria indisponivel.", ephemeral=True)

        if not self._user_can_use(interaction.user, chosen):
            roles_text = self._format_required_roles(self.guild_id, chosen)
            return await interaction.response.send_message(
                f"Voce nao tem cargo permitido pra usar a categoria **{chosen}**.\n"
                f"Cargo(s) liberado(s): {roles_text}",
                ephemeral=True,
            )

        if chosen == self.category:
            # Re-renderiza so pra atualizar visualmente o default.
            return await self.refresh(interaction)
        self.category = chosen
        self.list_mode = False
        await self.refresh(interaction, reload_catalog=True)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ---------------------------------------------------------------------------
# /mangaconfig — painel em botoes (Servidor 2 Niadd + Servidor 3 mangalivre.to)
# ---------------------------------------------------------------------------


def _niadd_category_discord_select_options() -> list[discord.SelectOption]:
    return [
        discord.SelectOption(label=key[:100], value=key[:100])
        for key in _safe_niadd_categories()
    ]


async def _mangaconfig_interaction_gate(
    interaction: discord.Interaction, moderator_id: int
) -> bool:
    if interaction.user.id != moderator_id:
        await interaction.response.send_message(
            "Somente quem abriu o painel pode usar estes botoes.", ephemeral=True
        )
        return False
    if interaction.guild is None:
        await interaction.response.send_message(
            "Use dentro de um servidor.", ephemeral=True
        )
        return False
    member = interaction.guild.get_member(interaction.user.id)
    if member is None or not member.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "Precisa da permissao **Gerenciar servidor**.", ephemeral=True
        )
        return False
    return True


class MangaCfgNiaddCategorySelect(discord.ui.Select):
    """Menu de categorias niadd para views de configuracao."""

    def __init__(self, placeholder: str, row: int = 0):
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            row=row,
            options=_niadd_category_discord_select_options(),
        )

    async def callback(self, interaction: discord.Interaction):
        cat = self.values[0] if self.values else ""
        setattr(self.view, "_selected_category", cat)
        await interaction.response.defer(ephemeral=True)


class MangaCfgRolePick(discord.ui.RoleSelect):
    def __init__(self, row: int = 1):
        super().__init__(
            placeholder="Escolha o cargo",
            min_values=1,
            max_values=1,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        setattr(self.view, "_selected_role", role)
        await interaction.response.defer(ephemeral=True)


class MangaConfigAdicionarView(discord.ui.View):
    def __init__(self, moderator_id: int):
        super().__init__(timeout=420)
        self._mod_id = moderator_id
        self._selected_category = ""
        self._selected_role: discord.Role | None = None
        self.add_item(MangaCfgNiaddCategorySelect("1) Categoria niadd"))
        self.add_item(MangaCfgRolePick(row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _mangaconfig_interaction_gate(interaction, self._mod_id)

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.success, row=2)
    async def confirm_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._selected_category:
            return await interaction.response.send_message(
                "Selecione uma categoria no menu.", ephemeral=True
            )
        if self._selected_role is None:
            return await interaction.response.send_message(
                "Selecione um cargo.", ephemeral=True
            )
        assert interaction.guild is not None
        cat = self._selected_category
        role = self._selected_role
        added = manga_perms.add_required_role(interaction.guild.id, cat, role.id)
        if added:
            roles_text = ", ".join(
                f"<@&{rid}>"
                for rid in manga_perms.get_required_roles(interaction.guild.id, cat)
            )
            msg = f"Categoria **{cat}** agora exige um destes cargos: {roles_text}"
        else:
            msg = f"O cargo {role.mention} ja estava liberado em **{cat}**."
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.secondary, row=2)
    async def close_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(content="Painel auxiliar encerrado.", view=None)


class MangaConfigRemoverView(discord.ui.View):
    def __init__(self, moderator_id: int):
        super().__init__(timeout=420)
        self._mod_id = moderator_id
        self._selected_category = ""
        self._selected_role: discord.Role | None = None
        self.add_item(MangaCfgNiaddCategorySelect("Categoria onde remover o cargo"))
        self.add_item(MangaCfgRolePick(row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _mangaconfig_interaction_gate(interaction, self._mod_id)

    @discord.ui.button(label="Confirmar remocao", style=discord.ButtonStyle.success, row=2)
    async def confirm_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._selected_category:
            return await interaction.response.send_message(
                "Selecione uma categoria no menu.", ephemeral=True
            )
        if self._selected_role is None:
            return await interaction.response.send_message(
                "Selecione um cargo.", ephemeral=True
            )
        assert interaction.guild is not None
        cat = self._selected_category
        role = self._selected_role
        removed = manga_perms.remove_required_role(interaction.guild.id, cat, role.id)
        if removed:
            remaining = manga_perms.get_required_roles(interaction.guild.id, cat)
            if remaining:
                roles_text = ", ".join(f"<@&{rid}>" for rid in remaining)
                msg = (
                    f"Removi {role.mention} de **{cat}**. Cargos restantes: {roles_text}"
                )
            else:
                msg = (
                    f"Removi {role.mention} de **{cat}**. A categoria voltou a ser "
                    "publica (sem restricao)."
                )
        else:
            msg = f"O cargo {role.mention} nao estava configurado em **{cat}**."
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.secondary, row=2)
    async def close_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(content="Painel auxiliar encerrado.", view=None)


class MangaConfigLimparView(discord.ui.View):
    def __init__(self, moderator_id: int):
        super().__init__(timeout=420)
        self._mod_id = moderator_id
        self._selected_category = ""
        self.add_item(MangaCfgNiaddCategorySelect("Categoria para liberar (todos)", row=0))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _mangaconfig_interaction_gate(interaction, self._mod_id)

    @discord.ui.button(label="Limpar cargos da categoria", style=discord.ButtonStyle.danger, row=2)
    async def confirm_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._selected_category:
            return await interaction.response.send_message(
                "Selecione uma categoria no menu.", ephemeral=True
            )
        assert interaction.guild is not None
        cleared = manga_perms.clear_category(interaction.guild.id, self._selected_category)
        cat = self._selected_category
        if cleared:
            msg = f"Categoria **{cat}** liberada para todos."
        else:
            msg = f"A categoria **{cat}** ja nao tinha restricoes."
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.secondary, row=2)
    async def close_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(content="Painel auxiliar encerrado.", view=None)


def _clone_mlto_perm_nav_view(nav_view: discord.ui.View, new_page: int) -> discord.ui.View:
    mid = getattr(nav_view, "_mod_id")
    sr = getattr(nav_view, "_selected_role", None)
    if isinstance(nav_view, MangaConfigMltoAdicionarView):
        return MangaConfigMltoAdicionarView(mid, page=new_page, selected_role=sr)
    if isinstance(nav_view, MangaConfigMltoRemoverView):
        return MangaConfigMltoRemoverView(mid, page=new_page, selected_role=sr)
    if isinstance(nav_view, MangaConfigMltoLimparView):
        return MangaConfigMltoLimparView(mid, page=new_page)
    raise RuntimeError("View MLTO invalida")


class MangaCfgMltoPagedCategorySelect(discord.ui.Select):
    def __init__(self, host: discord.ui.View, row: int = 0):
        page = getattr(host, "mlto_perm_page", 0)
        mark = getattr(host, "_selected_category", "") or ""
        super().__init__(
            placeholder="Categoria Manga Livre (.to)",
            min_values=1,
            max_values=1,
            row=row,
            options=_mcflto_perm_category_options(page, mark),
        )

    async def callback(self, interaction: discord.Interaction):
        vw = self.view
        chosen = self.values[0] if self.values else ""
        if chosen == _MCF_MLTO_NAV_NEXT:
            nx = _clone_mlto_perm_nav_view(vw, 1)
            await interaction.response.edit_message(
                content=(interaction.message.content or "").strip(),
                view=nx,
            )
            return
        if chosen == _MCF_MLTO_NAV_PREV:
            prv = _clone_mlto_perm_nav_view(vw, 0)
            await interaction.response.edit_message(
                content=(interaction.message.content or "").strip(),
                view=prv,
            )
            return
        if chosen not in _MLTO_CATEGORY_LABELS:
            return await interaction.response.send_message(
                "Categoria invalida.", ephemeral=True
            )
        setattr(vw, "_selected_category", chosen)
        await interaction.response.defer(ephemeral=True)


class MangaConfigMltoAdicionarView(discord.ui.View):
    def __init__(
        self,
        moderator_id: int,
        page: int = 0,
        selected_role: discord.Role | None = None,
    ):
        super().__init__(timeout=420)
        self._mod_id = moderator_id
        self.mlto_perm_page = page
        self._selected_category = ""
        self._selected_role = selected_role
        self.add_item(MangaCfgMltoPagedCategorySelect(self, row=0))
        self.add_item(MangaCfgRolePick(row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _mangaconfig_interaction_gate(interaction, self._mod_id)

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.success, row=2)
    async def confirm_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._selected_category:
            return await interaction.response.send_message(
                "Selecione uma categoria no menu.", ephemeral=True
            )
        if self._selected_role is None:
            return await interaction.response.send_message(
                "Selecione um cargo.", ephemeral=True
            )
        assert interaction.guild is not None
        lab = self._selected_category
        role = self._selected_role
        added = manga_perms.add_required_role_mlto(interaction.guild.id, lab, role.id)
        if added:
            roles_text = ", ".join(
                f"<@&{rid}>"
                for rid in manga_perms.get_required_roles_mlto(interaction.guild.id, lab)
            )
            msg = f"M.Livre **{lab}** agora exige um destes cargos: {roles_text}"
        else:
            msg = f"O cargo {role.mention} ja estava liberado em **{lab}** (.to)."
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.secondary, row=2)
    async def close_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(content="Painel auxiliar encerrado.", view=None)


class MangaConfigMltoRemoverView(discord.ui.View):
    def __init__(
        self,
        moderator_id: int,
        page: int = 0,
        selected_role: discord.Role | None = None,
    ):
        super().__init__(timeout=420)
        self._mod_id = moderator_id
        self.mlto_perm_page = page
        self._selected_category = ""
        self._selected_role = selected_role
        self.add_item(MangaCfgMltoPagedCategorySelect(self, row=0))
        self.add_item(MangaCfgRolePick(row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _mangaconfig_interaction_gate(interaction, self._mod_id)

    @discord.ui.button(label="Confirmar remocao", style=discord.ButtonStyle.success, row=2)
    async def confirm_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._selected_category:
            return await interaction.response.send_message(
                "Selecione uma categoria no menu.", ephemeral=True
            )
        if self._selected_role is None:
            return await interaction.response.send_message(
                "Selecione um cargo.", ephemeral=True
            )
        assert interaction.guild is not None
        lab = self._selected_category
        role = self._selected_role
        removed = manga_perms.remove_required_role_mlto(interaction.guild.id, lab, role.id)
        if removed:
            remaining = manga_perms.get_required_roles_mlto(interaction.guild.id, lab)
            if remaining:
                roles_text = ", ".join(f"<@&{rid}>" for rid in remaining)
                msg = (
                    f"Removi {role.mention} de **{lab}** (.to). "
                    f"Cargos restantes: {roles_text}"
                )
            else:
                msg = (
                    f"Removi {role.mention} de **{lab}** (.to). Voltou liberada pra todos."
                )
        else:
            msg = f"O cargo {role.mention} nao estava em **{lab}** (.to)."
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.secondary, row=2)
    async def close_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(content="Painel auxiliar encerrado.", view=None)


class MangaConfigMltoLimparView(discord.ui.View):
    def __init__(self, moderator_id: int, page: int = 0):
        super().__init__(timeout=420)
        self._mod_id = moderator_id
        self.mlto_perm_page = page
        self._selected_category = ""
        self.add_item(MangaCfgMltoPagedCategorySelect(self, row=0))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _mangaconfig_interaction_gate(interaction, self._mod_id)

    @discord.ui.button(label="Limpar categoria (.to)", style=discord.ButtonStyle.danger, row=2)
    async def confirm_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._selected_category:
            return await interaction.response.send_message(
                "Selecione uma categoria no menu.", ephemeral=True
            )
        assert interaction.guild is not None
        cleared = manga_perms.clear_category_mlto(
            interaction.guild.id,
            self._selected_category,
        )
        lab = self._selected_category
        msg = (
            f"Categoria **{lab}** (.to) liberada para todos."
            if cleared
            else f"Categoria **{lab}** (.to) ja estava livre."
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.secondary, row=2)
    async def close_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(content="Painel auxiliar encerrado.", view=None)


class MangaConfigNiaddResetConfirmView(discord.ui.View):
    def __init__(self, moderator_id: int):
        super().__init__(timeout=180)
        self._mod_id = moderator_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _mangaconfig_interaction_gate(interaction, self._mod_id)

    @discord.ui.button(
        label="Sim, apagar restricoes Niadd",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def yes_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        assert interaction.guild is not None
        manga_perms.reset_guild(interaction.guild.id)
        await interaction.response.edit_message(
            content="**Niadd.** Todas as restricoes do Servidor 2 foram removidas.",
            view=None,
        )

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, row=0)
    async def no_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(
            content="Reset Niadd cancelado.",
            view=None,
        )


class MangaConfigMltoResetConfirmView(discord.ui.View):
    def __init__(self, moderator_id: int):
        super().__init__(timeout=180)
        self._mod_id = moderator_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _mangaconfig_interaction_gate(interaction, self._mod_id)

    @discord.ui.button(
        label="Sim, apagar restricoes M.Livre",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def yes_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        assert interaction.guild is not None
        manga_perms.reset_guild_mlto(interaction.guild.id)
        await interaction.response.edit_message(
            content="**Manga Livre.** Todas as restricoes do Servidor 3 foram removidas.",
            view=None,
        )

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, row=0)
    async def no_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(
            content="Reset M.Livre cancelado.",
            view=None,
        )


class MangaConfigNiaddHubView(discord.ui.View):
    def __init__(self, moderator_id: int):
        super().__init__(timeout=420)
        self._mod_id = moderator_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _mangaconfig_interaction_gate(interaction, self._mod_id)

    @discord.ui.button(label="Listar Niadd", style=discord.ButtonStyle.secondary, row=0)
    async def btn_li(self, interaction: discord.Interaction, _: discord.ui.Button):
        assert interaction.guild is not None
        await interaction.response.send_message(
            embed=_embed_listar_niadd(interaction.guild),
            ephemeral=True,
        )

    @discord.ui.button(label="Adicionar", style=discord.ButtonStyle.primary, row=0)
    async def btn_add(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            content=(
                "**Servidor 2 / Niadd** — escolha categoria + cargo nos menus e "
                "**Confirmar** na proxima mensagem."
            ),
            view=MangaConfigAdicionarView(self._mod_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Remover", style=discord.ButtonStyle.secondary, row=1)
    async def btn_rm(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            content="**Niadd** — remover um cargo especifico.",
            view=MangaConfigRemoverView(self._mod_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Limpar cat.", style=discord.ButtonStyle.danger, row=1)
    async def btn_clr(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            content="**Niadd** — limpa todos os cargos de uma categoria.",
            view=MangaConfigLimparView(self._mod_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Reset Niadd", style=discord.ButtonStyle.danger, row=1)
    async def btn_rst(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            content="**Reset** apenas configuracoes do **Niadd** (Servidor 2).",
            view=MangaConfigNiaddResetConfirmView(self._mod_id),
            ephemeral=True,
        )

    @discord.ui.button(label="⬅ Menu", style=discord.ButtonStyle.success, row=2)
    async def btn_back(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(embed=_mangaconfig_main_embed(), view=MangaConfigRootView(self._mod_id))


class MangaConfigMltoHubView(discord.ui.View):
    def __init__(self, moderator_id: int):
        super().__init__(timeout=420)
        self._mod_id = moderator_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _mangaconfig_interaction_gate(interaction, self._mod_id)

    @discord.ui.button(label="Listar M.Livre", style=discord.ButtonStyle.secondary, row=0)
    async def btn_li(self, interaction: discord.Interaction, _: discord.ui.Button):
        assert interaction.guild is not None
        await interaction.response.send_message(
            embed=_embed_listar_mlto(interaction.guild),
            ephemeral=True,
        )

    @discord.ui.button(label="Adicionar", style=discord.ButtonStyle.primary, row=0)
    async def btn_add(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            content=(
                "**Servidor 3 / Manga Livre** — categoria pode precisar de "
                "**Mais categorias** no primeiro menu para ver todas."
            ),
            view=MangaConfigMltoAdicionarView(self._mod_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Remover", style=discord.ButtonStyle.secondary, row=1)
    async def btn_rm(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            content="**M.Livre** — remover um cargo.",
            view=MangaConfigMltoRemoverView(self._mod_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Limpar cat.", style=discord.ButtonStyle.danger, row=1)
    async def btn_clr(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            content="**M.Livre** — liberar uma categoria (todos os cargos).",
            view=MangaConfigMltoLimparView(self._mod_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Reset .to", style=discord.ButtonStyle.danger, row=1)
    async def btn_rst(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            content="**Reset** apenas **Manga Livre** (Servidor 3).",
            view=MangaConfigMltoResetConfirmView(self._mod_id),
            ephemeral=True,
        )

    @discord.ui.button(label="⬅ Menu", style=discord.ButtonStyle.success, row=2)
    async def btn_back(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(embed=_mangaconfig_main_embed(), view=MangaConfigRootView(self._mod_id))


class MangaConfigRootView(discord.ui.View):
    def __init__(self, moderator_id: int):
        super().__init__(timeout=600)
        self._mod_id = moderator_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _mangaconfig_interaction_gate(interaction, self._mod_id)

    @discord.ui.button(label="Servidor 2 (Niadd)", style=discord.ButtonStyle.primary, row=0)
    async def hub_n(self, interaction: discord.Interaction, _: discord.ui.Button):
        eb = discord.Embed(
            title="Config • Servidor 2 (Niadd)",
            description="Restringe cada **categoria niadd** do `/mangasetup` por cargo.",
            color=0x10B981,
        )
        await interaction.response.edit_message(embed=eb, view=MangaConfigNiaddHubView(self._mod_id))

    @discord.ui.button(label="Servidor 3 (M.Livre)", style=discord.ButtonStyle.success, row=0)
    async def hub_m(self, interaction: discord.Interaction, _: discord.ui.Button):
        eb = discord.Embed(
            title="Config • Servidor 3 (Manga Livre .to)",
            description="Restringe cada **categoria** (genero/catalogo .to) do `/mangasetup`.",
            color=0x22C55E,
        )
        await interaction.response.edit_message(embed=eb, view=MangaConfigMltoHubView(self._mod_id))

    @discord.ui.button(label="Listar tudo", style=discord.ButtonStyle.secondary, row=1)
    async def lst_all(self, interaction: discord.Interaction, _: discord.ui.Button):
        assert interaction.guild is not None
        await interaction.response.send_message(
            embed=_embed_listar_ambos(interaction.guild),
            ephemeral=True,
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class MangaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _ensure_manga_structure()

    @app_commands.command(name="manga", description="Abre o leitor de manga Sense Life")
    async def manga(self, interaction: discord.Interaction):
        _ensure_manga_structure()
        view = MangaReaderView(interaction.user.id)
        embed, file = view.render_embed_file()
        kwargs: dict[str, Any] = {"embed": embed, "view": view}
        if file:
            kwargs["file"] = file
        await interaction.response.send_message(**kwargs)

    @app_commands.command(name="manga_site", description="Abre leitor de manga online do Mangalivre")
    @app_commands.describe(termo="Nome do manga ou URL da pagina do manga")
    async def manga_site(self, interaction: discord.Interaction, termo: str):
        await interaction.response.defer(thinking=True)

        raw = termo.strip()
        manga_url = ""
        suggestions: list[dict[str, str]] = []
        if "/manga/" in raw:
            manga_url = _normalize_manga_url(raw)
        else:
            rl = raw.lower()
            if "mangalivre.blog" in rl:
                site_ml = MANGALIVRE_BLOG_SITE
            elif "mangalivre.to" in rl:
                site_ml = MANGALIVRE_TO_SITE
            else:
                site_ml = MANGALIVRE_TO_SITE  # https://mangalivre.to/?s=
            suggestions = await asyncio.to_thread(_search_manga_online, raw, 8, site_ml)
            if not suggestions:
                return await interaction.followup.send(
                    "Nao achei esse manga no Mangalivre.",
                    ephemeral=True,
                )
            manga_url = suggestions[0]["url"]

        try:
            manga_data = await asyncio.to_thread(_get_manga_online_data, manga_url)
        except requests.RequestException:
            return await interaction.followup.send(
                "Falha ao acessar o Mangalivre agora. Tenta de novo em alguns segundos.",
                ephemeral=True,
            )

        if not manga_data.get("chapters"):
            return await interaction.followup.send(
                "Encontrei o manga, mas nao achei capitulos disponiveis nessa pagina.",
                ephemeral=True,
            )

        view = OnlineMangaReaderView(interaction.user.id, manga_data)
        embed, file = await view.render_embed_file()
        kwargs: dict[str, Any] = {"embed": embed, "view": view}
        if file:
            kwargs["file"] = file
        await interaction.followup.send(**kwargs)

    @app_commands.command(name="mangasetup", description="Painel de mangas com busca rapida")
    async def mangasetup(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        guild_id = interaction.guild.id if interaction.guild else 0
        view = MangaSetupView(interaction.user.id, guild_id=guild_id)
        await view.load_catalog()
        embed = await view.build_embed()
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(
        name="mangaconfig",
        description="Botoes: restricoes por cargo no /mangasetup (Servidor 2 e 3).",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def mangaconfig(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        await interaction.response.send_message(
            embed=_mangaconfig_main_embed(),
            view=MangaConfigRootView(interaction.user.id),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MangaCog(bot))
