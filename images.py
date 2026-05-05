"""Image generation — rankings, profiles, shop, leaderboard with modern UI."""
import discord  # keep for reference
from PIL import Image, ImageDraw, ImageFont
import io
import os
import requests
from datetime import datetime

from database import *
from utils import get_tz, now_brazil, fmt_time, get_member_name, rank_badge, get_rank_color

# ============================================================
# HELPERS
# ============================================================
FONT_PATHS = [
    "assets/fonts/Primary.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf", "C:\\Windows\\Fonts\\arial.ttf",
    "C:\\Windows\\Fonts\\segoeuib.ttf", "C:\\Windows\\Fonts\\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/arialbd.ttf", "/usr/share/fonts/TTF/arial.ttf",
    "arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"
]

def _build_font_candidates():
    candidates = []
    env_font = os.environ.get("BOT_FONT_PATH")
    if env_font:
        candidates.append(env_font)
    candidates.extend(FONT_PATHS)
    try:
        import PIL
        pil_dir = os.path.dirname(PIL.__file__)
        candidates.extend([
            os.path.join(pil_dir, "fonts", "DejaVuSans-Bold.ttf"),
            os.path.join(pil_dir, "fonts", "DejaVuSans.ttf"),
        ])
    except Exception:
        pass
    # Keep order while removing duplicates.
    return list(dict.fromkeys(candidates))

def get_font(size):
    for p in _build_font_candidates():
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    # Last attempt by name in case pillow/fontconfig can resolve.
    for fallback_name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(fallback_name, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _fetch_avatar(url, sz=180):
    try:
        resp = requests.get(url, timeout=5)
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img = img.resize((sz, sz), Image.Resampling.LANCZOS)
        mask = Image.new('L', (sz, sz), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, sz, sz), fill=255)
        img.putalpha(mask)
        return img
    except Exception:
        return Image.new('RGBA', (sz, sz), (100, 100, 100, 255))

def _draw_gradient_bg(draw, W, H, top_color, bottom_color):
    for y in range(H):
        ratio = y / H
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * ratio)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * ratio)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * ratio)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    # Subtle top glow to improve depth/readability.
    draw.ellipse([(-W * 0.25, -H * 0.45), (W * 1.25, H * 0.35)], fill=(28, 38, 58))

def _draw_card(draw, x, y, w, h, radius=16, fill=(30, 41, 59), outline=None):
    """Draw a rounded rectangle card."""
    # Fake shadow under the card for depth.
    draw.rounded_rectangle([x + 2, y + 4, x + w + 2, y + h + 4], radius=radius, fill=(7, 10, 20))
    draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill)
    if outline:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, outline=outline, width=2)

def _draw_section_header(draw, W, title, accent_color):
    title_font = get_font(48)
    subtitle_font = get_font(20)
    now = now_brazil()
    draw.text((W // 2, 52), title, font=title_font, fill=accent_color, anchor="mm")
    draw.text(
        (W // 2, 86),
        f"Atualizado em {now.strftime('%d/%m/%Y %H:%M:%S')}",
        font=subtitle_font,
        fill=(148, 163, 184),
        anchor="mm",
    )
    draw.rounded_rectangle([(W // 2 - 220, 102), (W // 2 + 220, 106)], radius=2, fill=(71, 85, 105))

def _truncate_name(text, max_len=22):
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"

def _draw_progress_bar(draw, x, y, w, h, pct, color):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=(15, 23, 42))
    fill_w = max(2, int(w * max(0.0, min(1.0, pct))))
    draw.rounded_rectangle([x, y, x + fill_w, y + h], radius=h // 2, fill=color)

# ============================================================
# RANKING VOZ
# ============================================================
def img_voice(data, guild_name, bot=None, guild=None, title=None):
    W, rh, hh = 960, 108, 150
    H = hh + len(data) * rh
    img = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    _draw_gradient_bg(d, W, H, (15, 23, 42), (30, 27, 45))

    fr = get_font(30)
    fv = get_font(26)

    t = title or f"RANKING VOZ: {guild_name[:20].upper()}"
    _draw_section_header(d, W, t, (251, 191, 36))

    for i, (uid, val) in enumerate(data, 1):
        y = 115 + i * 15 + (i - 1) * (rh - 15)
        medal = rank_badge(i)
        col = get_rank_color(i)

        _draw_card(
            d, 30, y, W - 60, rh - 15, radius=14,
            fill=(30, 41, 59) if i > 3 else (40, 35, 50),
            outline=(55, 65, 81) if i <= 3 else None
        )

        nm = get_member_name(bot, uid, guild) if guild else f"User {uid}"
        d.text((55, y + (rh - 15) // 2), f"{medal}  {_truncate_name(nm)}", font=fr, fill=(255, 255, 255), anchor="lm")

        bar_x = W - 360
        bar_y = y + (rh - 15) // 2 + 10
        bar_w = 170
        bar_h = 10
        max_val = data[0][1] if data else 1
        fill_pct = val / max_val if max_val > 0 else 0
        _draw_progress_bar(d, bar_x, bar_y, bar_w, bar_h, fill_pct, col)

        d.text((W - 50, y + (rh - 15) // 2 - 5), fmt_time(val), font=fv, fill=col, anchor="rm")

    b = io.BytesIO()
    img.save(b, 'PNG')
    b.seek(0)
    return b

# ============================================================
# RANKING CHAT
# ============================================================
def img_chat(data, guild_name, bot=None, guild=None, title=None):
    W, rh, hh = 960, 108, 150
    H = hh + len(data) * rh
    img = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    _draw_gradient_bg(d, W, H, (15, 23, 42), (25, 18, 40))

    fr = get_font(30)
    fv = get_font(26)

    t = title or f"RANKING CHAT: {guild_name[:20].upper()}"
    _draw_section_header(d, W, t, (168, 85, 247))

    for i, (uid, cnt) in enumerate(data, 1):
        y = 115 + i * 15 + (i - 1) * (rh - 15)
        medal = rank_badge(i)
        col = get_rank_color(i)

        _draw_card(
            d, 30, y, W - 60, rh - 15, radius=14,
            fill=(30, 41, 59) if i > 3 else (40, 35, 50),
            outline=(55, 65, 81) if i <= 3 else None
        )

        nm = get_member_name(bot, uid, guild) if guild else f"User {uid}"
        d.text((55, y + (rh - 15) // 2), f"{medal}  {_truncate_name(nm)}", font=fr, fill=(255, 255, 255), anchor="lm")

        max_cnt = data[0][1] if data else 1
        fill_pct = cnt / max_cnt if max_cnt > 0 else 0
        bar_x = W - 360
        bar_y = y + (rh - 15) // 2 + 10
        bar_w = 170
        bar_h = 10
        _draw_progress_bar(d, bar_x, bar_y, bar_w, bar_h, fill_pct, col)

        d.text((W - 50, y + (rh - 15) // 2 - 5), f"{cnt} msgs", font=fv, fill=col, anchor="rm")

    b = io.BytesIO()
    img.save(b, 'PNG')
    b.seek(0)
    return b

# ============================================================
# RANKING ECONOMY
# ============================================================
def img_econ(data, guild_name, bot=None, guild=None):
    W, rh, hh = 960, 108, 150
    H = hh + len(data) * rh
    img = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    _draw_gradient_bg(d, W, H, (15, 23, 42), (20, 30, 25))

    fr = get_font(30)
    fv = get_font(26)

    _draw_section_header(d, W, f"RANKING ToT: {guild_name[:20].upper()}", (234, 179, 8))

    for i, (uid, coins) in enumerate(data, 1):
        y = 115 + i * 15 + (i - 1) * (rh - 15)
        medal = rank_badge(i)
        col = get_rank_color(i)

        _draw_card(
            d, 30, y, W - 60, rh - 15, radius=14,
            fill=(30, 41, 59) if i > 3 else (40, 35, 50),
            outline=(55, 65, 81) if i <= 3 else None
        )

        nm = get_member_name(bot, uid, guild) if guild else f"User {uid}"
        d.text((55, y + (rh - 15) // 2), f"{medal}  {_truncate_name(nm)}", font=fr, fill=(255, 255, 255), anchor="lm")

        max_c = data[0][1] if data else 1
        fill_pct = coins / max_c if max_c > 0 else 0
        bar_x = W - 360
        bar_y = y + (rh - 15) // 2 + 10
        bar_w = 170
        bar_h = 10
        _draw_progress_bar(d, bar_x, bar_y, bar_w, bar_h, fill_pct, col)

        d.text((W - 50, y + (rh - 15) // 2 - 5), f"{coins} ToT", font=fv, fill=col, anchor="rm")

    b = io.BytesIO()
    img.save(b, 'PNG')
    b.seek(0)
    return b

# ============================================================
# PROFILE
# ============================================================
def img_profile(user, data, rank, in_call=False):
    W, H = 1000, 700
    img = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    _draw_gradient_bg(d, W, H, (15, 23, 42), (30, 27, 55))

    # Outer card
    _draw_card(d, 20, 20, W - 40, H - 40, radius=40, fill=(20, 30, 50), outline=(50, 60, 80))

    # Avatar
    av_size = 160
    av = _fetch_avatar(user.display_avatar.url, av_size)
    img.paste(av, ((W - av_size) // 2, 40), av)

    # Name
    fn = get_font(52)
    fb = get_font(28)
    fv = get_font(48)

    d.text((W // 2, 230), _truncate_name(user.display_name, 24), font=fn, fill=(255, 255, 255), anchor="mm")

    # Status pill
    ic = (34, 197, 94) if in_call else (107, 114, 128)
    lb = "EM CALL" if in_call else "OFFLINE"
    pill_w, pill_h = 220, 36
    pill_x = (W - pill_w) // 2
    d.rounded_rectangle([pill_x, 265, pill_x + pill_w, 265 + pill_h], radius=18, fill=ic)
    d.text((W // 2, 265 + pill_h // 2), lb, font=fb, fill=(255, 255, 255), anchor="mm")

    # Rank badge
    badge_col = get_rank_color(rank) if isinstance(rank, int) else (100, 116, 139)
    d.ellipse([(W // 2 - 35, 315), (W // 2 + 35, 385)], fill=(30, 41, 59), outline=badge_col, width=3)
    d.text((W // 2, 350), f"#{rank}", font=get_font(36), fill=badge_col, anchor="mm")

    # Stats cards
    card_w, card_h, gap, sy = 250, 120, 20, 420
    total_cards = 3
    total_w = total_cards * card_w + (total_cards - 1) * gap
    sx = (W - total_w) // 2

    stats = [
        ("TEMPO TOTAL", fmt_time(data[2]), (59, 130, 246)),
        ("SESSOES", str(data[3]), (245, 158, 11)),
        ("RECORDE", fmt_time(data[4]), (239, 68, 68)),
    ]
    for i, (lb, v, cl) in enumerate(stats):
        x = sx + i * (card_w + gap)
        _draw_card(d, x, sy, card_w, card_h, radius=20, fill=(25, 35, 55))
        # Accent line at top
        d.rounded_rectangle([x + 20, sy + 2, x + card_w - 20, sy + 6], radius=3, fill=cl)
        d.text((x + card_w // 2, sy + 35), lb, font=fb, fill=(148, 163, 184), anchor="mm")
        d.text((x + card_w // 2, sy + 78), v, font=fv, fill=(255, 255, 255), anchor="mm")

    # Footer
    d.text((W // 2, H - 45), f"Gerado em {now_brazil().strftime('%d/%m/%Y %H:%M:%S')}",
           font=get_font(18), fill=(70, 80, 100), anchor="mm")

    b = io.BytesIO()
    img.save(b, 'PNG')
    b.seek(0)
    return b

# ============================================================
# SALDO / WALLET
# ============================================================
def img_saldo(user, econ_data, rank, daily_earned=None):
    W, H = 800, 460
    img = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    _draw_gradient_bg(d, W, H, (15, 23, 42), (25, 20, 50))

    header_font = get_font(30)
    text_font = get_font(24)
    small_font = get_font(20)
    number_font = get_font(56)

    # Title
    _draw_section_header(d, W, "CARTEIRA ToT", (234, 179, 8))

    # Avatar
    av_size = 80
    av = _fetch_avatar(user.display_avatar.url, av_size)
    img.paste(av, ((W - av_size) // 2, 65), av)

    # Name
    d.text((W // 2, 165), _truncate_name(user.display_name, 22), font=header_font, fill=(255, 255, 255), anchor="mm")

    # Rank
    if rank and rank != '-':
        badge_col = get_rank_color(rank) if isinstance(rank, int) else (100, 116, 139)
        d.ellipse([(W // 2 - 30, 190), (W // 2 + 30, 250)], fill=(30, 41, 59), outline=badge_col, width=3)
        d.text((W // 2, 220), f"#{rank}", font=get_font(30), fill=badge_col, anchor="mm")

    # Balance card
    card_x, card_y, card_w, card_h = 100, 260, 600, 100
    _draw_card(d, card_x, card_y, card_w, card_h, radius=20, fill=(25, 35, 55))
    d.rounded_rectangle([card_x + 30, card_y + 4, card_x + card_w - 30, card_y + 8], radius=4, fill=(234, 179, 8))

    balance = econ_data[2] if econ_data else 0
    d.text((card_x + card_w // 2, card_y + card_h // 2 + 5),
           f"{balance} ToT", font=number_font, fill=(234, 179, 8), anchor="mm")

    # Daily earnings
    if daily_earned and daily_earned > 0:
        d.text((W // 2, 380), f"Ganho hoje: +{daily_earned} ToT", font=text_font, fill=(34, 197, 94), anchor="mm")

    # Footer
    d.text((W // 2, 425), "Ganhe 2 ToT a cada 2 min em call!", font=small_font, fill=(100, 116, 139), anchor="mm")

    b = io.BytesIO()
    img.save(b, 'PNG')
    b.seek(0)
    return b

# ============================================================
# STATS TABLE
# ============================================================
def img_stats_table(lines, title, subt, color=(79, 70, 229)):
    W = 900; hh = 140; lh = 70
    H = hh + len(lines) * lh + 30
    img = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    _draw_gradient_bg(d, W, H, (15, 23, 42), (30, 27, 45))

    fs = get_font(30)
    fn = get_font(30)

    _draw_section_header(d, W, _truncate_name(title, 32), color)
    if subt:
        d.text((W // 2, 125), _truncate_name(subt, 48), font=fs, fill=(148, 163, 184), anchor="mm")

    for i, (lb, v) in enumerate(lines):
        y = hh + i * lh + 15
        _draw_card(d, 30, y, W - 60, lh - 10, radius=12, fill=(30, 41, 59))
        d.text((60, y + lh // 2 - 5), _truncate_name(lb, 28), font=fn, fill=(255, 255, 255), anchor="lm")
        d.text((W - 60, y + lh // 2 - 5), v, font=fn, fill=(251, 191, 36), anchor="rm")

    b = io.BytesIO()
    img.save(b, 'PNG')
    b.seek(0)
    return b

# ============================================================
# SHOP CARD
# ============================================================
def img_shop_item(item, buyer_name=None):
    """Generate a card for a shop item."""
    W, H = 500, 250
    img = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    _draw_gradient_bg(d, W, H, (15, 23, 42), (20, 30, 25))

    title_f = get_font(36)
    desc_f = get_font(22)
    price_f = get_font(32)
    emoji_f = get_font(60)

    # Card
    _draw_card(d, 15, 15, W - 30, H - 30, radius=25, fill=(25, 35, 55), outline=(50, 60, 80))

    # Emoji
    emoji = item[6] or "\U0001F4B0"  # default 💰
    d.text((60, 70), emoji, font=emoji_f, fill=(234, 179, 8), anchor="mm")

    # Name
    name_text = _truncate_name(item[2], 25)  # name column
    d.text((260, 55), name_text, font=title_f, fill=(255, 255, 255), anchor="mm")

    # Description
    desc = item[3] or "Sem descricao."  # description column
    # Word wrap
    words = desc.split()
    lines = []
    line = ""
    for w in words:
        test = line + " " + w if line else w
        if len(test) > 35:
            lines.append(line)
            line = w
        else:
            line = test
    if line:
        lines.append(line)
    for i, ln in enumerate(lines[:3]):
        d.text((260, 95 + i * 28), ln, font=desc_f, fill=(148, 163, 184), anchor="mm")

    # Price
    price = item[4]  # price column
    price_text = f"{price} ToT"
    if buyer_name:
        price_text = f"{price} ToT • {_truncate_name(buyer_name, 14)}"
    d.text((W // 2, H - 50), price_text, font=price_f, fill=(234, 179, 8), anchor="mm")

    b = io.BytesIO()
    img.save(b, 'PNG')
    b.seek(0)
    return b

# ============================================================
# LEADERBOARD COMBINED
# ============================================================
def img_leaderboard(voice_top, chat_top, econ_top, guild_name, bot=None, guild=None):
    """Combined leaderboard showing top of voice, chat, and economy."""
    W, H = 900, 500
    img = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    _draw_gradient_bg(d, W, H, (15, 23, 42), (30, 27, 45))

    fr = get_font(28)
    fv = get_font(24)

    # Title
    _draw_section_header(d, W, f"LEADERBOARD: {guild_name[:20].upper()}", (251, 191, 36))

    columns = [
        ("VOZ", (251, 191, 36), voice_top, fmt_time),
        ("CHAT", (168, 85, 247), chat_top, lambda x: f"{x} msgs"),
        ("ToT", (234, 179, 8), econ_top, lambda x: f"{x} ToT"),
    ]
    col_w = 270
    gap = 15
    start_x = (W - (col_w * 3 + gap * 2)) // 2

    for ci, (label, col_color, top_data, fmt_fn) in enumerate(columns):
        cx = start_x + ci * (col_w + gap)
        cy = 100

        # Column header
        d.rounded_rectangle([cx, cy, cx + col_w, cy + 40], radius=12, fill=col_color)
        d.text((cx + col_w // 2, cy + 20), label, font=get_font(26), fill=(15, 23, 42), anchor="mm")

        for i, (uid, val) in enumerate(top_data[:5], 1):
            y = cy + 55 + i * 72
            medal = rank_badge(i)
            nm = get_member_name(bot, uid, guild) if guild else f"User {uid}"
            _draw_card(d, cx + 5, y, col_w - 10, 58, radius=10, fill=(30, 41, 59))
            d.text((cx + 18, y + 29), f"{medal} {_truncate_name(nm, 14)}", font=fr, fill=(255, 255, 255), anchor="lm")
            d.text((cx + col_w - 18, y + 29), fmt_fn(val), font=fv, fill=col_color, anchor="rm")

    b = io.BytesIO()
    img.save(b, 'PNG')
    b.seek(0)
    return b
