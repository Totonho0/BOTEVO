"""Ship system — Beautiful heart image, consistent percentage, !tosco command."""
import discord
from discord import app_commands
from discord.ext import commands
import io
import random
import os
import json
import hashlib
import math
from datetime import datetime, timedelta
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from database import (
    create_marriage_proposal,
    set_marriage_proposal_message,
    get_marriage_by_id,
    accept_marriage,
    reject_marriage,
    get_active_marriage_by_user,
    get_active_marriage_by_user_global,
    get_pending_marriage_by_partner,
    get_pending_marriage_by_partner_global,
    divorce_marriage,
    divorce_marriage_global,
    get_latest_marriage_history,
    marriage_row_to_dict,
    shared_voice_time,
    add_marriage_affection,
    add_marriage_click_stat,
    set_marriage_accepted_at,
    set_marriage_witness,
)
from auth import is_admin, is_owner
from utils import now_brazil, fmt_time, ensure_aware

DATA_DIR = 'dados'
SHIP_FILE = os.path.join(DATA_DIR, 'ship_data.json')
os.makedirs(DATA_DIR, exist_ok=True)
MARRIAGE_DATA_DIR = os.path.join('data', 'marriage')
MARRIAGE_RESOURCES_FILE = os.path.join(MARRIAGE_DATA_DIR, 'resources.json')
os.makedirs(MARRIAGE_DATA_DIR, exist_ok=True)

DEFAULT_AFFECTION_GIFS = {
    # Edite estas listas manualmente em data/marriage/resources.json
    "beijar": [
        "https://images-ext-1.discordapp.net/external/VZA5Lsi1kaqA2WOK7LYLq54Tlla_i47wSgCFuRChj2U/https/cdn.nekotina.com/images/iJWvLPo2.gif?width=400&height=207",
        "https://images-ext-1.discordapp.net/external/5mqct7QEXGtWfinchZcYzkFtA_G98kIJW8eUjczmWaM/https/cdn.nekotina.com/images/35AQ97Af.gif?width=400&height=228",
    ],
    "abracar": [
        "https://media.tenor.com/xI8X94Z_emgAAAAC/anime-hug.gif",
        "https://media.tenor.com/6b8vY6KyHRQAAAAC/hug-anime.gif",
    ],
}

DEFAULT_SLAP_GIFS = [
    "https://media.tenor.com/I9k6M8a8eE8AAAAC/anime-slap.gif",
    "https://media.tenor.com/3ctQ8b6M6PQAAAAC/slap-anime.gif",
]

DEFAULT_AFFECTION_INSULTS = [
    "Sai fora, talarico(a)! Pessoa casada tem dono(a)!",
    "Ta achando que e festa? Respeita o casamento dos outros!",
    "Ih ala, tentando furar casamento alheio... que fase.",
    "Vai arrumar teu proprio romance e para de mexer com casal!",
]


def _ensure_marriage_storage():
    """Keep a persistent place for marriage-related resources."""
    os.makedirs(MARRIAGE_DATA_DIR, exist_ok=True)
    payload = {
        "affection_gifs": DEFAULT_AFFECTION_GIFS,
        "slap_gifs": DEFAULT_SLAP_GIFS,
        "insults": DEFAULT_AFFECTION_INSULTS,
        "note": "Arquivo de recursos do sistema de casamento. Pode editar manualmente."
    }
    if not os.path.exists(MARRIAGE_RESOURCES_FILE):
        with open(MARRIAGE_RESOURCES_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return

    # Keep backward compatible shape if user removed keys.
    try:
        with open(MARRIAGE_RESOURCES_FILE, 'r', encoding='utf-8') as f:
            existing = json.load(f)
    except Exception:
        existing = {}
    changed = False
    if not isinstance(existing, dict):
        existing = {}
        changed = True
    if "affection_gifs" not in existing or not isinstance(existing.get("affection_gifs"), dict):
        existing["affection_gifs"] = payload["affection_gifs"]
        changed = True
    else:
        existing["affection_gifs"].setdefault("beijar", payload["affection_gifs"]["beijar"])
        existing["affection_gifs"].setdefault("abracar", payload["affection_gifs"]["abracar"])
    if "slap_gifs" not in existing or not isinstance(existing.get("slap_gifs"), list):
        existing["slap_gifs"] = payload["slap_gifs"]
        changed = True
    if "insults" not in existing or not isinstance(existing.get("insults"), list):
        existing["insults"] = payload["insults"]
        changed = True
    existing["note"] = payload["note"]
    if changed:
        with open(MARRIAGE_RESOURCES_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)


def _load_marriage_resources():
    _ensure_marriage_storage()
    try:
        with open(MARRIAGE_RESOURCES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {}
    affection = data.get("affection_gifs", {})
    return {
        "beijar": affection.get("beijar", DEFAULT_AFFECTION_GIFS["beijar"]),
        "abracar": affection.get("abracar", DEFAULT_AFFECTION_GIFS["abracar"]),
        "slap_gifs": data.get("slap_gifs", DEFAULT_SLAP_GIFS),
        "insults": data.get("insults", DEFAULT_AFFECTION_INSULTS),
    }

def _dt_from_iso(value):
    if not value:
        return None
    try:
        return ensure_aware(datetime.fromisoformat(value))
    except Exception:
        return None


def _member_text(guild, uid):
    m = guild.get_member(uid) if guild else None
    return m.mention if m else f"<@{uid}>"


def _fit_text(draw, text, max_width, start_size, min_size=18):
    size = start_size
    font = _get_font(size)
    while size > min_size and draw.textbbox((0, 0), text, font=font)[2] > max_width:
        size -= 2
        font = _get_font(size)
    return font

def _draw_soft_gradient(draw, w, h, top, bottom):
    for y in range(h):
        ratio = y / h
        r = int(top[0] + (bottom[0] - top[0]) * ratio)
        g = int(top[1] + (bottom[1] - top[1]) * ratio)
        b = int(top[2] + (bottom[2] - top[2]) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

def _draw_panel(draw, x, y, w, h, radius=24, fill=(26, 30, 52), outline=(70, 78, 110)):
    draw.rounded_rectangle([x + 2, y + 4, x + w + 2, y + h + 4], radius=radius, fill=(8, 10, 20))
    draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill, outline=outline, width=2)


class MarriageInviteView(discord.ui.View):
    def __init__(self, bot, guild_id, marriage_id, proposer_id, partner_id):
        super().__init__(timeout=86400)
        self.bot = bot
        self.guild_id = guild_id
        self.marriage_id = marriage_id
        self.proposer_id = proposer_id
        self.partner_id = partner_id

    async def _finalize_buttons(self, ix: discord.Interaction):
        for child in self.children:
            child.disabled = True
        try:
            await ix.response.edit_message(view=self)
        except Exception:
            pass
        self.stop()

    @discord.ui.button(label="Aceitar pedido", style=discord.ButtonStyle.success)
    async def accept_btn(self, ix: discord.Interaction, button: discord.ui.Button):
        if ix.user.id != self.partner_id:
            return await ix.response.send_message("Apenas a pessoa convidada pode responder.", ephemeral=True)

        row = get_marriage_by_id(self.marriage_id)
        info = marriage_row_to_dict(row)
        if not info or info['status'] != 'pending':
            return await ix.response.send_message("Esse pedido nao esta mais pendente.", ephemeral=True)

        if get_active_marriage_by_user_global(info['spouse_a']) or get_active_marriage_by_user_global(info['spouse_b']):
            reject_marriage(self.marriage_id, ix.user.id, "conflito: um dos usuarios ja casado")
            return await ix.response.send_message("Nao foi possivel aceitar: um dos dois ja esta casado.", ephemeral=True)

        accept_marriage(self.marriage_id)
        await self._finalize_buttons(ix)

        guild = self.bot.get_guild(self.guild_id)
        partner_txt = _member_text(guild, info['spouse_b'])
        proposer_txt = _member_text(guild, info['spouse_a'])
        witnesses = info.get('witnesses', [])
        padrinho_h = _member_text(guild, witnesses[0]) if len(witnesses) > 0 else "N/D"
        padrinho_m = _member_text(guild, witnesses[1]) if len(witnesses) > 1 else "N/D"
        dama_honra = _member_text(guild, witnesses[2]) if len(witnesses) > 2 else "N/D"
        celebrante = _member_text(guild, info.get('celebrant_id')) if info.get('celebrant_id') else "N/D"

        e = discord.Embed(
            title="💍 Casamento confirmado!",
            description=f"{proposer_txt} e {partner_txt} agora estao casados!",
            color=0x22c55e
        )
        e.add_field(name="Padrinho", value=padrinho_h, inline=True)
        e.add_field(name="Madrinha", value=padrinho_m, inline=True)
        e.add_field(name="Dama de Honra", value=dama_honra, inline=True)
        e.add_field(name="Celebrante", value=celebrante, inline=False)
        e.set_footer(text=f"ID do casamento: {self.marriage_id}")

        try:
            await ix.followup.send("Voce aceitou o pedido. Felicidades!", ephemeral=True)
        except Exception:
            pass
        try:
            proposer = await self.bot.fetch_user(self.proposer_id)
            await proposer.send(embed=e)
        except Exception:
            pass

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger)
    async def reject_btn(self, ix: discord.Interaction, button: discord.ui.Button):
        if ix.user.id != self.partner_id:
            return await ix.response.send_message("Apenas a pessoa convidada pode responder.", ephemeral=True)

        row = get_marriage_by_id(self.marriage_id)
        info = marriage_row_to_dict(row)
        if not info or info['status'] != 'pending':
            return await ix.response.send_message("Esse pedido nao esta mais pendente.", ephemeral=True)

        reject_marriage(self.marriage_id, ix.user.id, "pedido recusado")
        await self._finalize_buttons(ix)
        try:
            await ix.followup.send("Pedido recusado.", ephemeral=True)
        except Exception:
            pass
        try:
            proposer = await self.bot.fetch_user(self.proposer_id)
            await proposer.send("Seu pedido de casamento foi recusado.")
        except Exception:
            pass


class MarriageStatusView(discord.ui.View):
    def __init__(self, bot, marriage_id, requester_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.marriage_id = marriage_id
        self.requester_id = requester_id

    def _get_user_from_guild_or_cache(self, guild, uid):
        m = guild.get_member(uid) if guild else None
        if m:
            return m
        return self.bot.get_user(uid)

    def _build_status_card(self, guild, info):
        spouse_a_user = self._get_user_from_guild_or_cache(guild, info['spouse_a'])
        spouse_b_user = self._get_user_from_guild_or_cache(guild, info['spouse_b'])
        accepted_at = _dt_from_iso(info.get('accepted_at') or info.get('created_at'))
        days = max(0, (now_brazil() - accepted_at).days) if accepted_at else 0
        start_txt = accepted_at.strftime("%d/%m/%Y") if accepted_at else "N/D"
        shared_secs = shared_voice_time(info['guild_id'], info['spouse_a'], info['spouse_b'])
        kisses = int(info.get('kiss_count') or 0)
        hugs = int(info.get('hug_count') or 0)
        rejects = int(info.get('reject_click_count') or 0)

        W, H = 1120, 620
        img = Image.new("RGB", (W, H), (20, 16, 34))
        d = ImageDraw.Draw(img)
        _draw_soft_gradient(d, W, H, (20, 16, 34), (50, 16, 44))
        _draw_panel(d, 24, 20, W - 48, H - 40, radius=30, fill=(25, 20, 46), outline=(85, 70, 110))

        title_font = _get_font(54)
        body_font = _get_font(36)
        label_font = _get_font(28)
        d.text((W // 2, 56), "STATUS DO CASAMENTO", fill=(255, 184, 228), font=title_font, anchor="mm")
        d.rounded_rectangle([(W // 2 - 230, 86), (W // 2 + 230, 90)], radius=2, fill=(110, 96, 138))

        av_size = 190
        av_a = _fetch_avatar(spouse_a_user.display_avatar.url if spouse_a_user else "", av_size)
        av_b = _fetch_avatar(spouse_b_user.display_avatar.url if spouse_b_user else "", av_size)
        ax, ay = 180, 140
        bx, by = W - 180 - av_size, 140
        img.paste(av_a, (ax, ay), av_a)
        img.paste(av_b, (bx, by), av_b)

        name_a = (spouse_a_user.display_name if spouse_a_user else f"User {info['spouse_a']}")[:28]
        name_b = (spouse_b_user.display_name if spouse_b_user else f"User {info['spouse_b']}")[:28]
        name_a_font = _fit_text(d, name_a, 280, 30, 18)
        name_b_font = _fit_text(d, name_b, 280, 30, 18)
        d.text((ax + av_size // 2, ay + av_size + 34), name_a, fill=(255, 255, 255), font=name_a_font, anchor="mm")
        d.text((bx + av_size // 2, by + av_size + 34), name_b, fill=(255, 255, 255), font=name_b_font, anchor="mm")

        d.text((W // 2, 245), "X", fill=(255, 106, 165), font=_get_font(82), anchor="mm")
        d.text((W // 2, 350), f"{days} dias casados", fill=(255, 255, 255), font=body_font, anchor="mm")
        d.text((W // 2, 402), f"Inicio: {start_txt}", fill=(215, 215, 230), font=label_font, anchor="mm")
        d.text((W // 2, 448), f"Tempo em call juntos: {fmt_time(shared_secs)}", fill=(190, 220, 255), font=label_font, anchor="mm")
        _draw_panel(d, 70, 456, 320, 128, radius=20, fill=(31, 27, 56), outline=(86, 76, 120))
        d.text((90, 490), f"beijos: {kisses}", fill=(255, 184, 214), font=label_font, anchor="lm")
        d.text((90, 530), f"abracos: {hugs}", fill=(184, 224, 255), font=label_font, anchor="lm")
        d.text((90, 570), f"recusas: {rejects}", fill=(255, 199, 199), font=label_font, anchor="lm")

        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        return buf

    def _build_memories_card(self, guild, info):
        shared_secs = shared_voice_time(info['guild_id'], info['spouse_a'], info['spouse_b'])
        spouse_a_user = self._get_user_from_guild_or_cache(guild, info['spouse_a'])
        spouse_b_user = self._get_user_from_guild_or_cache(guild, info['spouse_b'])
        witnesses = info.get('witnesses', [])
        padrinho_user = self._get_user_from_guild_or_cache(guild, witnesses[0]) if len(witnesses) > 0 else None
        madrinha_user = self._get_user_from_guild_or_cache(guild, witnesses[1]) if len(witnesses) > 1 else None
        dama_honra_user = self._get_user_from_guild_or_cache(guild, witnesses[2]) if len(witnesses) > 2 else None

        W, H = 1380, 660
        img = Image.new("RGB", (W, H), (15, 24, 44))
        d = ImageDraw.Draw(img)
        _draw_soft_gradient(d, W, H, (15, 24, 44), (35, 56, 92))
        _draw_panel(d, 22, 20, W - 44, H - 40, radius=28, fill=(19, 30, 56), outline=(75, 108, 158))

        title_font = _get_font(44)
        name_font = _get_font(24)
        big_font = _get_font(36)
        d.text((W // 2, 54), "MEMORIAS DO CASAL", fill=(133, 208, 255), font=title_font, anchor="mm")
        d.rounded_rectangle([(W // 2 - 220, 82), (W // 2 + 220, 86)], radius=2, fill=(82, 128, 180))
        d.text((W // 2, 104), f"Tempo junto em call: {fmt_time(shared_secs)}", fill=(255, 255, 255), font=big_font, anchor="mm")

        av_size = 170
        spacing = 40
        total_w = av_size * 5 + spacing * 4
        start_x = (W - total_w) // 2
        y = 210

        slots = [
            ("Esposo(a) 1", spouse_a_user),
            ("Esposo(a) 2", spouse_b_user),
            ("Padrinho", padrinho_user),
            ("Madrinha", madrinha_user),
            ("Dama de Honra", dama_honra_user),
        ]

        for idx, (label, user_obj) in enumerate(slots):
            x = start_x + idx * (av_size + spacing)
            avatar = _fetch_avatar(user_obj.display_avatar.url if user_obj else "", av_size)
            img.paste(avatar, (x, y), avatar)
            display_name = (user_obj.display_name if user_obj else "Nao definido")[:18]
            display_font = _fit_text(d, display_name, av_size + 30, 24, 16)
            label_font = _fit_text(d, label, av_size + 40, 22, 14)
            d.text((x + av_size // 2, y + av_size + 24), display_name, fill=(255, 255, 255), font=display_font, anchor="mm")
            d.text((x + av_size // 2, y + av_size + 56), label, fill=(176, 198, 222), font=label_font, anchor="mm")

        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        return buf

    async def _guard(self, ix: discord.Interaction):
        if ix.user.id != self.requester_id:
            await ix.response.send_message("Apenas quem abriu o painel pode usar os botoes.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Status", style=discord.ButtonStyle.primary)
    async def status_btn(self, ix: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(ix):
            return
        await ix.response.defer()
        row = get_marriage_by_id(self.marriage_id)
        info = marriage_row_to_dict(row)
        if not info:
            return await ix.followup.send("Casamento nao encontrado.", ephemeral=True)
        img = self._build_status_card(ix.guild, info)
        e = discord.Embed(title="Status do Casamento", color=0xf472b6)
        e.set_image(url="attachment://casamento_status.png")
        await ix.edit_original_response(embed=e, attachments=[discord.File(fp=img, filename="casamento_status.png")], view=self)

    @discord.ui.button(label="Memorias", style=discord.ButtonStyle.secondary)
    async def memories_btn(self, ix: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(ix):
            return
        await ix.response.defer()
        row = get_marriage_by_id(self.marriage_id)
        info = marriage_row_to_dict(row)
        if not info:
            return await ix.followup.send("Casamento nao encontrado.", ephemeral=True)
        img = self._build_memories_card(ix.guild, info)
        e = discord.Embed(title="Memorias do Casal", color=0x60a5fa)
        e.set_image(url="attachment://casamento_memorias.png")
        await ix.edit_original_response(embed=e, attachments=[discord.File(fp=img, filename="casamento_memorias.png")], view=self)


class AffectionRetribuirView(discord.ui.View):
    def __init__(self, bot, marriage_id, actor_id, target_id, kind):
        super().__init__(timeout=900)
        self.bot = bot
        self.marriage_id = marriage_id
        self.actor_id = actor_id
        self.target_id = target_id
        self.kind = kind
        self.retributed = False

    @discord.ui.button(label="Retribuir", style=discord.ButtonStyle.primary)
    async def retribuir_btn(self, ix: discord.Interaction, button: discord.ui.Button):
        if ix.user.id != self.target_id:
            return await ix.response.send_message("Apenas quem recebeu pode retribuir.", ephemeral=True)
        if self.retributed:
            return await ix.response.send_message("Ja foi retribuido.", ephemeral=True)

        info = None
        if self.marriage_id:
            row = get_marriage_by_id(self.marriage_id)
            info = marriage_row_to_dict(row)
            if not info or info['status'] != 'active':
                return await ix.response.send_message("Casamento nao esta mais ativo.", ephemeral=True)
            add_marriage_affection(self.marriage_id, self.kind, 1)
            add_marriage_click_stat(self.marriage_id, 'retribute', 1)
        self.retributed = True
        for child in self.children:
            child.disabled = True
        await ix.response.edit_message(view=self)

        resources = _load_marriage_resources()
        gif_key = "beijar" if self.kind == "kiss" else "abracar"
        gif_pool = resources.get(gif_key, [])
        gif_url = random.choice(gif_pool) if gif_pool else None
        count_label = "beijos" if self.kind == "kiss" else "abracos"
        total = None
        if info:
            refreshed = marriage_row_to_dict(get_marriage_by_id(self.marriage_id))
            total = refreshed.get('kiss_count', 0) if self.kind == "kiss" else refreshed.get('hug_count', 0)

        target_user = self.bot.get_user(self.actor_id)
        e = discord.Embed(
            title="💞 Retribuicao",
            description=f"{ix.user.mention} retribuiu em {target_user.mention if target_user else f'<@{self.actor_id}>'}!",
            color=0xf472b6 if self.kind == "kiss" else 0x60a5fa
        )
        if total is not None:
            e.add_field(name=f"Total de {count_label}", value=f"**{total}**", inline=True)
        if gif_url:
            e.set_image(url=gif_url)

        next_view = AffectionRetribuirView(
            self.bot,
            self.marriage_id,
            actor_id=ix.user.id,
            target_id=self.actor_id,
            kind=self.kind
        )
        await ix.followup.send(embed=e, view=next_view)

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger)
    async def recusar_btn(self, ix: discord.Interaction, button: discord.ui.Button):
        if ix.user.id != self.target_id:
            return await ix.response.send_message("Apenas quem recebeu pode recusar.", ephemeral=True)

        if self.marriage_id:
            row = get_marriage_by_id(self.marriage_id)
            info = marriage_row_to_dict(row)
            if not info or info['status'] != 'active':
                return await ix.response.send_message("Casamento nao esta mais ativo.", ephemeral=True)
            add_marriage_click_stat(self.marriage_id, 'reject', 1)

        for child in self.children:
            child.disabled = True
        await ix.response.edit_message(view=self)

        slap_pool = _load_marriage_resources().get("slap_gifs", [])
        slap_url = random.choice(slap_pool) if slap_pool else None
        e = discord.Embed(
            title="🖐️ Recusado",
            description=f"{ix.user.mention} recusou e meteu um tapa!",
            color=0xef4444
        )
        if slap_url:
            e.set_image(url=slap_url)
        await ix.followup.send(embed=e, ephemeral=False)


# ============================================================
# PERCENTAGE — Saved permanently, never changes
# ============================================================
def _get_ship_key(uid1, uid2):
    return "_".join(sorted([str(uid1), str(uid2)]))


def _load_ship_data():
    if os.path.exists(SHIP_FILE):
        try:
            with open(SHIP_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_ship_data(data):
    with open(SHIP_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_or_create_percentage(uid1, uid2):
    """Get saved percentage or generate and save a new one. Once saved, NEVER changes."""
    data = _load_ship_data()
    a, b = sorted([str(uid1), str(uid2)])
    sk = _get_ship_key(uid1, uid2)

    # Check global first
    gk = "global"
    data.setdefault(gk, {})
    if sk in data[gk] and 'percentage' in data[gk][sk]:
        return data[gk][sk]['percentage']

    # Also check all guild keys (in case it was saved under a guild)
    for key in data:
        if key != "global" and sk in data[key] and 'percentage' in data[key][sk]:
            return data[key][sk]['percentage']

    h = hashlib.sha256(f"ship_{a}_{b}".encode()).hexdigest()
    pct = int(h[:8], 16) % 101

    data[gk][sk] = {
        'percentage': pct,
        'count': 0,
        'users': [int(a), int(b)],
        'first_ship': datetime.now().isoformat()
    }
    _save_ship_data(data)
    return pct


def _get_relationship_label(pct):
    if pct >= 90:
        return "ALMAS GEMEAS", "Destinados um ao outro!"
    elif pct >= 80:
        return "CASAL PERFEITO", "Quase explodem de amor!"
    elif pct >= 70:
        return "COMPATIVEL", "Rolou uma quimica forte!"
    elif pct >= 60:
        return "INTERESSANTE", "Tem potencial!"
    elif pct >= 50:
        return "PODE DAR CERTO", "Falta um pouco mais..."
    elif pct >= 40:
        return "AMIZADE COLORIDA", "Talvez com mais tempo..."
    elif pct >= 30:
        return "SO AMIGOS", "Friendzone confirmada..."
    elif pct >= 20:
        return "ESTRANHO", "Nada a ver juntos..."
    else:
        return "ZERO QUIMICA", "Impossivel ser pior..."


# ============================================================
# HEART — Mathematical parametric heart
# ============================================================
def _generate_heart_points(n=300):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t))
        pts.append((x, y))
    return pts


def _create_heart_partial_fill(size, top_color, bottom_color, percentage):
    """Create heart with partial fill from bottom based on percentage."""
    W, H = size, size

    heart_rgba = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(heart_rgba)
    pts = _generate_heart_points(n=300)
    max_x = max(p[0] for p in pts)
    max_y = max(p[1] for p in pts)
    min_y = min(p[1] for p in pts)
    scale = (size - 10) / max(max_x * 2, max_y - min_y)
    offset_x = size / 2
    offset_y = size / 2 + (max_y + min_y) / 2 * scale / 2
    abs_pts = [
        (int(p[0] * scale + offset_x), int(p[1] * scale + offset_y))
        for p in pts
    ]
    draw.polygon(abs_pts, fill=(255, 255, 255, 255))
    heart_rgba = heart_rgba.filter(ImageFilter.GaussianBlur(radius=1.2))
    heart_mask = heart_rgba.getchannel('A')

    # Dark heart (unfilled part)
    dark_img = Image.new('RGBA', (W, H), (30, 25, 40, 255))
    dark_img.putalpha(heart_mask)

    # Gradient image
    grad = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grad)
    for y in range(H):
        ratio = y / H
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * ratio)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * ratio)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * ratio)
        gdraw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    # Fill mask: bottom portion
    cut_y = int(H * (1 - percentage / 100))
    fill_mask = Image.new('L', (W, H), 0)
    fdraw = ImageDraw.Draw(fill_mask)
    if cut_y < H:
        fdraw.rectangle([0, cut_y, W, H], fill=255)
        fill_mask = fill_mask.filter(ImageFilter.GaussianBlur(radius=3))

    # Combine fill mask with heart shape
    combined_alpha = Image.new('L', (W, H), 0)
    for y in range(H):
        for x in range(W):
            hm = heart_mask.getpixel((x, y))
            fm = fill_mask.getpixel((x, y))
            combined_alpha.putpixel((x, y), min(hm, fm))

    grad.putalpha(combined_alpha)
    result = Image.alpha_composite(dark_img, grad)

    # Outline
    outline_img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(outline_img)
    odraw.polygon(abs_pts, outline=top_color, width=3)
    outline_img = outline_img.filter(ImageFilter.GaussianBlur(radius=0.8))
    result = Image.alpha_composite(result, outline_img)
    return result


# ============================================================
# AVATAR & FONT
# ============================================================
def _fetch_avatar(url, sz=128):
    try:
        resp = requests.get(url, timeout=5)
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img = img.resize((sz, sz), Image.Resampling.LANCZOS)
        mask = Image.new('L', (sz, sz), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, sz, sz), fill=255)
        img.putalpha(mask)
        return img
    except Exception:
        return Image.new('RGBA', (sz, sz), (80, 80, 80, 255))


def _get_font(size):
    # Mesma estrategia do `images.py`: lista multi-OS pra nao quebrar em host Linux (Discloud).
    paths = []
    env_font = os.environ.get("BOT_FONT_PATH")
    if env_font:
        paths.append(env_font)
    paths.extend([
        "assets/fonts/Primary.ttf",
        # Windows
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        # Linux (comum em containers)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/arialbd.ttf",
        "/usr/share/fonts/TTF/arial.ttf",
        # Fallbacks por nome (se estiver no cwd)
        "arialbd.ttf",
        "arial.ttf",
        "DejaVuSans-Bold.ttf",
        "DejaVuSans.ttf",
    ])
    try:
        import PIL
        pil_dir = os.path.dirname(PIL.__file__)
        paths.extend([
            os.path.join(pil_dir, "fonts", "DejaVuSans-Bold.ttf"),
            os.path.join(pil_dir, "fonts", "DejaVuSans.ttf"),
        ])
    except Exception:
        pass
    paths = list(dict.fromkeys(paths))
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    for fallback_name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(fallback_name, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ============================================================
# SHIP IMAGE
# ============================================================
def img_ship(user1, user2, percentage, ship_count=0):
    W, H = 800, 520
    img = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)

    if percentage >= 70:
        bg_top, bg_bot = (25, 10, 35), (55, 15, 40)
        accent, accent_light = (255, 60, 130), (255, 100, 170)
        heart_top, heart_bot = (255, 50, 120), (200, 30, 90)
    elif percentage >= 40:
        bg_top, bg_bot = (15, 20, 40), (35, 25, 50)
        accent, accent_light = (180, 80, 220), (140, 60, 200)
        heart_top, heart_bot = (180, 70, 210), (120, 40, 160)
    else:
        bg_top, bg_bot = (15, 18, 25), (25, 25, 35)
        accent, accent_light = (100, 100, 120), (80, 80, 100)
        heart_top, heart_bot = (80, 80, 100), (50, 50, 60)

    # Background gradient
    for y in range(H):
        ratio = y / H
        r = int(bg_top[0] + (bg_bot[0] - bg_top[0]) * ratio)
        g = int(bg_top[1] + (bg_bot[1] - bg_top[1]) * ratio)
        b = int(bg_top[2] + (bg_bot[2] - bg_top[2]) * ratio)
        d.line([(0, y), (W, y)], fill=(r, g, b))

    # Floating mini hearts
    random.seed(percentage * 7 + 42)
    for _ in range(35):
        hx = random.randint(10, W - 10)
        hy = random.randint(10, H - 10)
        hs = random.randint(6, 20)
        alpha = random.randint(8, 35)
        pts = _generate_heart_points(n=80)
        mx = max(p[0] for p in pts)
        my = max(p[1] for p in pts)
        mny = min(p[1] for p in pts)
        sc = hs / max(mx * 2, my - mny) * 0.6
        ox, oy = hx, hy + (my + mny) / 2 * sc / 2
        apts = [(int(p[0] * sc + ox), int(p[1] * sc + oy)) for p in pts]
        d.polygon(apts, fill=(accent[0], accent[1], accent[2], alpha))

    ft_title = _get_font(40)
    ft_name = _get_font(26)
    ft_label = _get_font(24)
    ft_pct = _get_font(58)
    ft_small = _get_font(18)

    d.text((W // 2, 28), "SHIP", font=ft_title, fill=accent, anchor="mm")

    card_x, card_y, card_w, card_h = 40, 75, W - 80, H - 110
    d.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                        radius=30, fill=(18, 22, 38), outline=(45, 35, 55), width=2)

    # Avatars
    av_size = 130
    av1 = _fetch_avatar(user1.display_avatar.url, av_size)
    av2 = _fetch_avatar(user2.display_avatar.url, av_size)
    av_y = card_y + 30
    av1_x = card_x + 50
    av2_x = card_x + card_w - 50 - av_size

    for gi in range(3, 0, -1):
        gr = av_size // 2 + gi * 7
        gc = (accent[0] // (gi + 2), accent[1] // (gi + 2), accent[2] // (gi + 2))
        d.ellipse([av1_x + av_size//2 - gr, av_y + av_size//2 - gr,
                    av1_x + av_size//2 + gr, av_y + av_size//2 + gr], fill=gc)
        d.ellipse([av2_x + av_size//2 - gr, av_y + av_size//2 - gr,
                    av2_x + av_size//2 + gr, av_y + av_size//2 + gr], fill=gc)

    img.paste(av1, (av1_x, av_y), av1)
    img.paste(av2, (av2_x, av_y), av2)

    n1 = user1.display_name[:16]
    n2 = user2.display_name[:16]
    d.text((av1_x + av_size // 2, av_y + av_size + 18), n1, font=ft_name, fill=(255, 255, 255), anchor="mm")
    d.text((av2_x + av_size // 2, av_y + av_size + 18), n2, font=ft_name, fill=(255, 255, 255), anchor="mm")

    # Heart
    center_x = W // 2
    heart_cy = av_y + av_size // 2
    heart_size = 140

    for gi in range(4, 0, -1):
        gr = heart_size // 2 + gi * 15
        gc = (accent[0] // (gi + 3), accent[1] // (gi + 3), accent[2] // (gi + 3))
        d.ellipse([center_x - gr, heart_cy - gr, center_x + gr, heart_cy + gr], fill=gc)

    heart_img = _create_heart_partial_fill(
        int(heart_size * 2.2), heart_top, heart_bot, percentage)
    img.paste(heart_img, (center_x - heart_img.width // 2, heart_cy - heart_img.height // 2), heart_img)

    d.text((center_x + 2, heart_cy + 2), f"{percentage}%", font=ft_pct, fill=(0, 0, 0), anchor="mm")
    d.text((center_x, heart_cy), f"{percentage}%", font=ft_pct, fill=(255, 255, 255), anchor="mm")
    d.text((center_x, av_y + av_size + 18), "x", font=ft_name, fill=accent_light, anchor="mm")

    # Compatibility bar
    bar_y = card_y + card_h - 130
    bar_h = 28
    bar_x = card_x + 60
    bar_w = card_w - 120
    d.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=14, fill=(12, 16, 30))
    fill_w = int(bar_w * percentage / 100)
    if fill_w > 0:
        for bx in range(fill_w):
            ratio = bx / max(fill_w, 1)
            r = int(heart_top[0] * (1 - ratio * 0.3) + heart_bot[0] * ratio * 0.3)
            g = int(heart_top[1] * (1 - ratio * 0.3) + heart_bot[1] * ratio * 0.3)
            b = int(heart_top[2] * (1 - ratio * 0.3) + heart_bot[2] * ratio * 0.3)
            d.rectangle([bar_x + bx, bar_y + 2, bar_x + bx + 1, bar_y + bar_h - 2], fill=(r, g, b))

    label, desc = _get_relationship_label(percentage)
    d.text((center_x, bar_y - 25), label, font=ft_label, fill=accent, anchor="mm")
    d.text((center_x, bar_y + bar_h + 20), desc, font=ft_small, fill=(130, 140, 160), anchor="mm")

    if ship_count > 0:
        d.text((center_x, bar_y + bar_h + 42), f"Shipados {ship_count} vezes",
               font=ft_small, fill=(90, 100, 120), anchor="mm")

    d.text((W // 2, H - 12), f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
           font=ft_small, fill=(55, 60, 75), anchor="mm")

    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return buf


# ============================================================
# RESOLVE MEMBER — Handles mention, ID, or username
# ============================================================
async def resolve_member(ctx, arg: str):
    """Try to resolve a member from @mention, user ID, username, or display name."""
    # Try mention (extract ID from <@123>)
    import re
    mention_match = re.search(r'<@!?(\d+)>', arg)
    if mention_match:
        uid = int(mention_match.group(1))
        return ctx.guild.get_member(uid)

    # Try direct ID
    if arg.isdigit():
        uid = int(arg)
        return ctx.guild.get_member(uid)

    # Try display name match
    arg_lower = arg.lower()
    for m in ctx.guild.members:
        if m.display_name.lower() == arg_lower or m.name.lower() == arg_lower:
            return m

    # Try partial match
    for m in ctx.guild.members:
        if arg_lower in m.display_name.lower() or arg_lower in m.name.lower():
            return m

    return None


# ============================================================
# COG
# ============================================================
class ShipCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _ensure_marriage_storage()

    async def _notify_marriage_party(self, guild, proposer, partner, participants):
        for role_name, member in participants:
            try:
                e = discord.Embed(
                    title="💍 Convocacao para casamento",
                    description=(
                        f"Voce foi convocado(a) para o casamento de {proposer.mention} e {partner.mention}.\n"
                        f"Seu papel sera: **{role_name}**."
                    ),
                    color=0xf472b6
                )
                e.add_field(name="Servidor", value=guild.name, inline=False)
                await member.send(embed=e)
            except Exception:
                pass

    async def _set_witness_role_by_prefix(self, ctx, role_label, slot_index, pessoa_id, membro_casal):
        if not is_admin(ctx.author.id):
            return await ctx.send("Voce nao tem permissao para usar este comando.")
        if pessoa_id <= 0:
            return await ctx.send("Use um ID valido (numero maior que 0).")

        pessoa = ctx.guild.get_member(pessoa_id)
        if not pessoa:
            return await ctx.send("Nao achei essa pessoa no servidor.")
        if pessoa.bot:
            return await ctx.send("Nao pode definir bot como padrinho/madrinha/dama.")

        target = membro_casal or ctx.author
        row = get_active_marriage_by_user(ctx.guild.id, target.id)
        info = marriage_row_to_dict(row) if row else None
        if not info:
            if membro_casal is None:
                return await ctx.send("Nenhum casamento ativo seu encontrado. Use: `!p <id_pessoa> <@membro_do_casal>`")
            return await ctx.send("Nao encontrei casamento ativo para esse membro.")

        if pessoa.id in (info['spouse_a'], info['spouse_b']):
            return await ctx.send("Essa pessoa e um dos noivos e nao pode ocupar esse papel.")

        witnesses = list(info.get('witnesses', []))
        while len(witnesses) <= 2:
            witnesses.append(0)
        witnesses[slot_index] = pessoa.id
        used = [wid for wid in witnesses if wid > 0]
        if len(used) != len(set(used)):
            return await ctx.send("Padrinho, madrinha e dama de honra devem ser pessoas diferentes.")

        ok = set_marriage_witness(info['id'], slot_index, pessoa.id)
        if not ok:
            return await ctx.send("Falha ao atualizar esse casamento.")

        spouse_a = _member_text(ctx.guild, info['spouse_a'])
        spouse_b = _member_text(ctx.guild, info['spouse_b'])
        e = discord.Embed(
            title="✅ Papel do casamento atualizado",
            description=f"{role_label} definido(a) como {pessoa.mention}.",
            color=0x22c55e
        )
        e.add_field(name="Casal", value=f"{spouse_a} x {spouse_b}", inline=False)
        await ctx.send(embed=e)

    # ============================================================
    # /ship
    # ============================================================
    @app_commands.command(name='ship', description='Descubra sua compatibilidade com alguem')
    @app_commands.describe(membro="Membro para shipar (opcional)")
    async def ship(self, interaction: discord.Interaction, membro: discord.Member = None):
        if membro is None:
            members = [m for m in interaction.guild.members if not m.bot and m.id != interaction.user.id]
            if not members:
                return await interaction.response.send_message("Nao tem ninguem para shipar!")
            membro = random.choice(members)
        if membro.bot:
            return await interaction.response.send_message("Nao posso shipar com bots!", ephemeral=True)
        if membro.id == interaction.user.id:
            return await interaction.response.send_message("Ship consigo mesmo? Que triste...", ephemeral=True)

        await interaction.response.defer()

        uid1, uid2 = interaction.user.id, membro.id
        pct = _get_or_create_percentage(uid1, uid2)

        data = _load_ship_data()
        gk = str(interaction.guild.id)
        data.setdefault(gk, {})
        sk = _get_ship_key(uid1, uid2)
        ship_entry = data[gk].get(sk, {})
        ship_count = ship_entry.get('count', 0) + 1
        data[gk][sk] = {
            'count': ship_count,
            'last_ship': datetime.now().isoformat(),
            'percentage': pct,
            'users': [uid1, uid2]
        }
        _save_ship_data(data)

        img = img_ship(interaction.user, membro, pct, ship_count)
        f = discord.File(fp=img, filename='ship.png')

        label, desc = _get_relationship_label(pct)
        e = discord.Embed(
            title=f"{interaction.user.display_name} x {membro.display_name}",
            description=f"**{label}**\n*{desc}*",
            color=0xff4d8d if pct >= 50 else 0x888888)
        e.add_field(name="Compatibilidade", value=f"**{pct}%**", inline=True)
        e.add_field(name="Vezes shipados", value=f"{ship_count}", inline=True)
        e.set_image(url="attachment://ship.png")
        await interaction.followup.send(file=f, embed=e)

    # ============================================================
    # /casal
    # ============================================================
    @app_commands.command(name='casal', description='Ve a compatibilidade entre dois membros')
    @app_commands.describe(membro1="Primeiro membro", membro2="Segundo membro")
    async def casal(self, interaction: discord.Interaction, membro1: discord.Member, membro2: discord.Member):
        if membro1.bot or membro2.bot:
            return await interaction.response.send_message("Nao shipo com bots!", ephemeral=True)
        if membro1.id == membro2.id:
            return await interaction.response.send_message("Sao a mesma pessoa!", ephemeral=True)

        await interaction.response.defer()

        pct = _get_or_create_percentage(membro1.id, membro2.id)
        data = _load_ship_data()
        gk = str(interaction.guild.id)
        data.setdefault(gk, {})
        sk = _get_ship_key(membro1.id, membro2.id)
        ship_count = data[gk].get(sk, {}).get('count', 0)
        _save_ship_data(data)

        img = img_ship(membro1, membro2, pct, ship_count)
        f = discord.File(fp=img, filename='casal.png')
        label, desc = _get_relationship_label(pct)
        e = discord.Embed(
            title=f"{membro1.display_name} x {membro2.display_name}",
            description=f"**{label}**\n*{desc}*",
            color=0xff4d8d if pct >= 50 else 0x888888)
        e.add_field(name="Compatibilidade", value=f"**{pct}%**", inline=True)
        e.add_field(name="Shipados", value=f"{ship_count} vezes", inline=True)
        e.set_image(url="attachment://casal.png")
        await interaction.followup.send(file=f, embed=e)

    # ============================================================
    # /topship
    # ============================================================
    @app_commands.command(name='topship', description='Ve os casais mais shipados do servidor')
    async def topship(self, interaction: discord.Interaction):
        data = _load_ship_data()
        gk = str(interaction.guild.id)
        guild_data = data.get(gk, {})
        if not guild_data:
            return await interaction.response.send_message("Nenhum ship registrado! Use /ship para comecar.", ephemeral=True)

        couples = []
        for sk, info in guild_data.items():
            uid1, uid2 = info.get('users', [0, 0])
            if uid1 and uid2:
                couples.append((uid1, uid2, info.get('percentage', 0), info.get('count', 0)))
        if not couples:
            return await interaction.response.send_message("Nenhum ship registrado!", ephemeral=True)

        couples.sort(key=lambda x: x[3], reverse=True)
        e = discord.Embed(title="Top Casais", description=f"Os mais shipados de {interaction.guild.name}", color=0xff4d8d)

        for i, (uid1, uid2, pct, count) in enumerate(couples[:10], 1):
            m1 = interaction.guild.get_member(uid1)
            m2 = interaction.guild.get_member(uid2)
            n1 = m1.display_name if m1 else f"User {uid1}"
            n2 = m2.display_name if m2 else f"User {uid2}"
            medal = "\U0001F947" if i == 1 else "\U0001F948" if i == 2 else "\U0001F949" if i == 3 else f"#{i}"
            label, _ = _get_relationship_label(pct)
            e.add_field(name=f"{medal} {n1} x {n2}",
                        value=f"{pct}% — {label}\nShipados **{count}** vezes", inline=False)
        await interaction.response.send_message(embed=e)

    # ============================================================
    # /shipstats
    # ============================================================
    @app_commands.command(name='shipstats', description='Ve suas estatisticas de ship')
    @app_commands.describe(membro="Membro para ver stats (opcional)")
    async def shipstats(self, interaction: discord.Interaction, membro: discord.Member = None):
        target = membro or interaction.user
        data = _load_ship_data()
        gk = str(interaction.guild.id)
        guild_data = data.get(gk, {})
        if not guild_data:
            return await interaction.response.send_message("Nenhum ship registrado!", ephemeral=True)

        user_ships = [info for sk, info in guild_data.items() if target.id in info.get('users', [])]
        if not user_ships:
            return await interaction.response.send_message(f"{target.mention} nunca foi shipado!", ephemeral=True)

        user_ships.sort(key=lambda x: x.get('count', 0), reverse=True)
        total_ships = sum(s.get('count', 0) for s in user_ships)
        best = user_ships[0]

        best_uid = None
        for uid in best.get('users', []):
            if uid != target.id:
                best_uid = uid
                break

        e = discord.Embed(title=f"Ship Stats — {target.display_name}", color=0xff4d8d)
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="Total Ships", value=f"**{total_ships}** vezes", inline=True)
        e.add_field(name="Parceiros", value=f"**{len(user_ships)}**", inline=True)

        if best_uid:
            bm = interaction.guild.get_member(best_uid)
            bname = bm.display_name if bm else f"User {best_uid}"
            label, _ = _get_relationship_label(best.get('percentage', 0))
            e.add_field(name="Melhor Ship", value=f"{target.display_name} x {bname}\n{best.get('percentage', 0)}% — {label}", inline=False)

        lines = []
        for s in user_ships[:5]:
            uid1, uid2 = s.get('users', [0, 0])
            other = uid2 if uid1 == target.id else uid1
            m = interaction.guild.get_member(other)
            n = m.display_name if m else f"User {other}"
            lines.append(f"{n} — {s.get('percentage', 0)}% ({s.get('count', 0)}x)")
        if lines:
            e.add_field(name="Seus Ships", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=e)

    # ============================================================
    # /shipme — Ship aleatorio com quem mandou
    # ============================================================
    @app_commands.command(name='shipme', description='Ship aleatorio com voce')
    async def shipme(self, interaction: discord.Interaction):
        members = [m for m in interaction.guild.members if not m.bot and m.id != interaction.user.id]
        if not members:
            return await interaction.response.send_message("Nao tem ninguem!", ephemeral=True)
        target = random.choice(members)
        await self.ship(interaction, membro=target)

    # ============================================================
    # /casar
    # ============================================================
    @app_commands.command(name='casar', description='Pede alguem em casamento com convite por DM')
    @app_commands.describe(
        parceiro="Pessoa que voce quer casar",
        padrinho_homem="Padrinho homem",
        padrinho_mulher="Padrinho mulher",
        dama_de_honra="Dama de honra",
        celebrante="Quem celebra o casamento",
    )
    async def casar(
        self,
        interaction: discord.Interaction,
        parceiro: discord.Member,
        padrinho_homem: discord.Member,
        padrinho_mulher: discord.Member,
        dama_de_honra: discord.Member,
        celebrante: discord.Member
    ):
        if parceiro.bot:
            return await interaction.response.send_message("Escolha uma pessoa valida para casar (sem bot).", ephemeral=True)
        self_marriage = parceiro.id == interaction.user.id
        if self_marriage and not is_owner(interaction.user.id):
            return await interaction.response.send_message("Auto-casamento e apenas para teste do dono.", ephemeral=True)
        if get_active_marriage_by_user_global(interaction.user.id):
            return await interaction.response.send_message("Voce ja esta casado(a). Use /divorcio antes.", ephemeral=True)
        if not self_marriage and get_active_marriage_by_user_global(parceiro.id):
            return await interaction.response.send_message("Essa pessoa ja esta casada.", ephemeral=True)

        if padrinho_homem.bot or padrinho_mulher.bot or dama_de_honra.bot or celebrante.bot:
            return await interaction.response.send_message("Padrinhos, dama de honra e celebrante nao podem ser bots.", ephemeral=True)
        allow_full_self_test = is_owner(interaction.user.id) and self_marriage
        if not allow_full_self_test:
            seen = {interaction.user.id, parceiro.id}
            ceremony_ids = [padrinho_homem.id, padrinho_mulher.id, dama_de_honra.id, celebrante.id]
            if len(set(ceremony_ids)) != 4 or any(cid in seen for cid in ceremony_ids):
                return await interaction.response.send_message(
                    "Padrinho, madrinha, dama de honra e celebrante devem ser 4 pessoas diferentes e nao podem ser os noivos.",
                    ephemeral=True
                )
        witnesses = [padrinho_homem.id, padrinho_mulher.id, dama_de_honra.id]

        pending = get_pending_marriage_by_partner_global(interaction.user.id, parceiro.id)
        if pending:
            return await interaction.response.send_message("Ja existe um pedido pendente para essa pessoa.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        marriage_id = create_marriage_proposal(
            interaction.guild.id,
            interaction.user.id,
            parceiro.id,
            witnesses,
            celebrante.id
        )

        if self_marriage:
            accept_marriage(marriage_id)
            e = discord.Embed(
                title="💍 Casamento de teste confirmado",
                description="Auto-casamento ativado para teste.",
                color=0x22c55e
            )
            e.add_field(name="Padrinho", value=padrinho_homem.mention, inline=True)
            e.add_field(name="Madrinha", value=padrinho_mulher.mention, inline=True)
            e.add_field(name="Dama de Honra", value=dama_de_honra.mention, inline=True)
            e.add_field(name="Celebrante", value=celebrante.mention, inline=False)
            return await interaction.followup.send(embed=e, ephemeral=True)

        view = MarriageInviteView(self.bot, interaction.guild.id, marriage_id, interaction.user.id, parceiro.id)
        e = discord.Embed(
            title="💌 Pedido de casamento",
            description=f"{interaction.user.mention} quer casar com voce!",
            color=0xf472b6
        )
        e.add_field(name="Servidor", value=interaction.guild.name, inline=False)
        e.add_field(name="Padrinho", value=padrinho_homem.mention, inline=True)
        e.add_field(name="Madrinha", value=padrinho_mulher.mention, inline=True)
        e.add_field(name="Dama de Honra", value=dama_de_honra.mention, inline=True)
        e.add_field(name="Celebrante", value=celebrante.mention, inline=False)
        e.set_footer(text="Voce tem 24h para aceitar ou recusar.")

        try:
            dm_msg = await parceiro.send(embed=e, view=view)
            set_marriage_proposal_message(marriage_id, dm_msg.channel.id, dm_msg.id)
            await self._notify_marriage_party(
                interaction.guild,
                interaction.user,
                parceiro,
                [
                    ("Padrinho", padrinho_homem),
                    ("Madrinha", padrinho_mulher),
                    ("Dama de Honra", dama_de_honra),
                    ("Celebrante", celebrante),
                ]
            )
            await interaction.followup.send(
                f"Pedido enviado por DM para {parceiro.mention}. Aguarde a resposta.",
                ephemeral=True
            )
        except Exception:
            reject_marriage(marriage_id, interaction.user.id, "falha ao enviar DM")
            await interaction.followup.send(
                "Nao consegui enviar DM para essa pessoa. Ela precisa liberar DM do servidor.",
                ephemeral=True
            )

    # ============================================================
    # /divorcio
    # ============================================================
    @app_commands.command(name='divorcio', description='Encerra seu casamento atual')
    @app_commands.describe(motivo="Motivo opcional para registrar")
    async def divorcio(self, interaction: discord.Interaction, motivo: str = None):
        row = divorce_marriage_global(interaction.user.id, motivo)
        info = marriage_row_to_dict(row) if row else None
        if not info:
            return await interaction.response.send_message("Voce nao esta casado(a).", ephemeral=True)
        spouse_id = info['spouse_b'] if info['spouse_a'] == interaction.user.id else info['spouse_a']
        spouse_txt = _member_text(interaction.guild, spouse_id)
        e = discord.Embed(
            title="💔 Divorcio registrado",
            description=f"Seu casamento com {spouse_txt} foi encerrado.",
            color=0xef4444
        )
        if motivo:
            e.add_field(name="Motivo", value=motivo[:500], inline=False)
        await interaction.response.send_message(embed=e)

    # ============================================================
    # /casamento_status
    # ============================================================
    @app_commands.command(name='casamento_status', description='Mostra painel com status do casamento')
    @app_commands.describe(membro="Ver casamento de outro membro (opcional)")
    async def casamento_status(self, interaction: discord.Interaction, membro: discord.Member = None):
        await interaction.response.defer()
        target = membro or interaction.user
        # Busca global primeiro para nao depender de guild_id legado/migrado.
        row = get_active_marriage_by_user_global(target.id)
        if not row and interaction.guild:
            row = get_active_marriage_by_user(interaction.guild.id, target.id)
        info = marriage_row_to_dict(row) if row else None
        if not info:
            return await interaction.followup.send("Nenhum casamento ativo encontrado.", ephemeral=True)
        view = MarriageStatusView(self.bot, info['id'], interaction.user.id)
        img = view._build_status_card(interaction.guild, info)
        emb = discord.Embed(title="Status do Casamento", color=0xf472b6)
        emb.set_image(url="attachment://casamento_status.png")
        await interaction.followup.send(
            embed=emb,
            file=discord.File(fp=img, filename="casamento_status.png"),
            view=view
        )

    @commands.command(name='tempcas', description='Define quantos dias um casal esta casado (prefixo)')
    async def tempcas(self, ctx, membro: discord.Member = None, dias: int = None):
        if not is_admin(ctx.author.id):
            return await ctx.send("Voce nao tem permissao para usar este comando.")
        if membro is None or dias is None:
            return await ctx.send("Uso: `!tempcas <@membro> <dias>`")
        if dias < 0 or dias > 36500:
            return await ctx.send("Dias deve ser entre 0 e 36500.")

        row = get_active_marriage_by_user(ctx.guild.id, membro.id)
        info = marriage_row_to_dict(row) if row else None
        if not info:
            return await ctx.send("Nenhum casamento ativo encontrado para esse membro.")

        new_date = now_brazil() - timedelta(days=dias)
        set_marriage_accepted_at(info['id'], new_date.isoformat())

        spouse_a = _member_text(ctx.guild, info['spouse_a'])
        spouse_b = _member_text(ctx.guild, info['spouse_b'])
        e = discord.Embed(
            title="⏱️ Tempo de casados atualizado",
            description=f"O casamento de {spouse_a} e {spouse_b} agora mostra **{dias}** dia(s) casados.",
            color=0x22c55e
        )
        e.add_field(name="Nova data de inicio", value=new_date.strftime("%d/%m/%Y"), inline=False)
        await ctx.send(embed=e)

    @commands.command(name='p', description='Define padrinho no casamento ativo (dono/IDs autorizados)')
    async def set_padrinho(self, ctx, pessoa_id: int = None, membro_casal: discord.Member = None):
        if pessoa_id is None:
            return await ctx.send("Uso: `!p <id_pessoa> [@membro_do_casal]`")
        await self._set_witness_role_by_prefix(ctx, "Padrinho", 0, pessoa_id, membro_casal)

    @commands.command(name='m', description='Define madrinha no casamento ativo (dono/IDs autorizados)')
    async def set_madrinha(self, ctx, pessoa_id: int = None, membro_casal: discord.Member = None):
        if pessoa_id is None:
            return await ctx.send("Uso: `!m <id_pessoa> [@membro_do_casal]`")
        await self._set_witness_role_by_prefix(ctx, "Madrinha", 1, pessoa_id, membro_casal)

    @commands.command(name='d', description='Define dama de honra no casamento ativo (dono/IDs autorizados)')
    async def set_dama_honra(self, ctx, pessoa_id: int = None, membro_casal: discord.Member = None):
        if pessoa_id is None:
            return await ctx.send("Uso: `!d <id_pessoa> [@membro_do_casal]`")
        await self._set_witness_role_by_prefix(ctx, "Dama de Honra", 2, pessoa_id, membro_casal)

    async def _affection_action(self, interaction: discord.Interaction, alvo: discord.Member, kind: str):
        if alvo.bot:
            return await interaction.response.send_message("Nao rola com bot.", ephemeral=True)
        if alvo.id == interaction.user.id and not is_owner(interaction.user.id):
            return await interaction.response.send_message("Voce nao pode usar isso em si mesmo.", ephemeral=True)

        resources = _load_marriage_resources()
        target_marriage_row = get_active_marriage_by_user(interaction.guild.id, alvo.id)
        target_marriage = marriage_row_to_dict(target_marriage_row) if target_marriage_row else None
        marriage_id_for_count = None
        if target_marriage:
            spouse_of_target = target_marriage['spouse_b'] if target_marriage['spouse_a'] == alvo.id else target_marriage['spouse_a']
            if interaction.user.id != spouse_of_target:
                insults = resources.get("insults", [])
                text = random.choice(insults) if insults else "Respeita o casamento dos outros."
                return await interaction.response.send_message(text)
            marriage_id_for_count = target_marriage['id']

        action_name = "beijou" if kind == "kiss" else "abracou"
        count_label = "beijos" if kind == "kiss" else "abracos"
        gif_key = "beijar" if kind == "kiss" else "abracar"
        gifs = resources.get(gif_key, [])
        gif_url = random.choice(gifs) if gifs else None

        total = None
        if marriage_id_for_count:
            add_marriage_affection(marriage_id_for_count, kind, 1)
            add_marriage_click_stat(marriage_id_for_count, 'affection', 1)
            refreshed = marriage_row_to_dict(get_marriage_by_id(marriage_id_for_count))
            total = refreshed.get('kiss_count', 0) if kind == "kiss" else refreshed.get('hug_count', 0)

        e = discord.Embed(
            title="💞 Momento fofo",
            description=f"{interaction.user.mention} {action_name} {alvo.mention}!",
            color=0xf472b6 if kind == "kiss" else 0x60a5fa
        )
        if total is not None:
            e.add_field(name=f"Total de {count_label}", value=f"**{total}**", inline=True)
        if gif_url:
            e.set_image(url=gif_url)
        view = AffectionRetribuirView(self.bot, marriage_id_for_count, interaction.user.id, alvo.id, kind)
        await interaction.response.send_message(embed=e, view=view)

    @app_commands.command(name='beijar', description='Da um beijo no seu esposo(a)')
    @app_commands.describe(alvo='Seu esposo(a)')
    async def beijar(self, interaction: discord.Interaction, alvo: discord.Member):
        await self._affection_action(interaction, alvo, 'kiss')

    @app_commands.command(name='abracar', description='Da um abraco no seu esposo(a)')
    @app_commands.describe(alvo='Seu esposo(a)')
    async def abracar(self, interaction: discord.Interaction, alvo: discord.Member):
        await self._affection_action(interaction, alvo, 'hug')


    # ============================================================
    # !tosco — Define porcentagem customizada para o proximo ship
    # ============================================================
    @commands.command(name='tosco', description='Define a porcentagem do seu proximo ship')
    async def tosko(self, ctx, porcentagem: int = None):
        if porcentagem is None:
            # Check if user has a pending tosko
            data = _load_ship_data()
            gk = str(ctx.guild.id)
            pending = data.get(gk, {}).get(f"tosco_{ctx.author.id}")
            if pending:
                e = discord.Embed(
                    title="\U0001F3AD Tosco Ativo!",
                    description=f"Seu proximo ship sera **{pending}%**!\nUse `!tosco cancelar` para remover.",
                    color=0xff4d8d)
            else:
                e = discord.Embed(
                    title="\U0001F3AD Tosco",
                    description="Define a porcentagem do seu proximo ship.\nUse: `!tosco <0-100>`\nEx: `!tosco 98` — proximo ship sera 98%\n`!tosco cancelar` — remove o tosko",
                    color=0x5865f2)
            return await ctx.send(embed=e)

        if isinstance(porcentagem, str) and porcentagem.lower() == "cancelar":
            data = _load_ship_data()
            gk = str(ctx.guild.id)
            data.get(gk, {}).pop(f"tosco_{ctx.author.id}", None)
            _save_ship_data(data)
            return await ctx.send("\U0001F3AD Tosco removido! Seus ships voltarao ao normal.")

        if porcentagem < 0 or porcentagem > 100:
            return await ctx.send("A porcentagem deve ser entre 0 e 100.")

        data = _load_ship_data()
        gk = str(ctx.guild.id)
        data.setdefault(gk, {})
        data[gk][f"tosco_{ctx.author.id}"] = {
            'percentage': porcentagem,
            'set_at': datetime.now().isoformat()
        }
        _save_ship_data(data)

        e = discord.Embed(
            title="\U0001F3AD Tosco Ativado!",
            description=f"Seu proximo ship sera **{porcentagem}%**!\nShip com alguem para ativar.",
            color=0x22c55e)
        await ctx.send(embed=e)

    def _check_tosco(self, ctx, uid1, uid2):
        """Check if either user has a pending tosko. Returns percentage or None."""
        data = _load_ship_data()
        gk = str(ctx.guild.id)
        guild_data = data.get(gk, {})

        for uid in [uid1, uid2]:
            key = f"tosco_{uid}"
            if key in guild_data:
                pct = guild_data[key]['percentage']
                # Remove the pending tosko
                del guild_data[key]
                _save_ship_data(data)
                return pct
        return None

    # ============================================================
    # !sf — Forceship (owner only) — accepts mention, ID, or name
    # ============================================================
    @commands.command(name='sf', description='FORCESHIP 100% - Apenas Dono')
    async def forceship(self, ctx, arg1: str = None, arg2: str = None):
        if not is_owner(ctx.author.id):
            return await ctx.send("Apenas o dono pode usar esse comando!")
        if arg1 is None or arg2 is None:
            return await ctx.send("Use: `!sf @user1 @user2` ou `!sf ID1 ID2` ou `!sf nome1 nome2`")

        user1 = await resolve_member(ctx, arg1)
        user2 = await resolve_member(ctx, arg2)

        if user1 is None:
            return await ctx.send(f"Nao encontrei o membro: `{arg1}`")
        if user2 is None:
            return await ctx.send(f"Nao encontrei o membro: `{arg2}`")
        if user1.bot or user2.bot:
            return await ctx.send("Nao posso fazer ship com bots!")
        if user1.id == user2.id:
            return await ctx.send("Os usuarios devem ser diferentes!")

        await ctx.defer()

        # Remove any pending tosko for these users
        data = _load_ship_data()
        gk = str(ctx.guild.id)
        data.setdefault(gk, {})
        data[gk].pop(f"tosco_{user1.id}", None)
        data[gk].pop(f"tosco_{user2.id}", None)

        sk = _get_ship_key(user1.id, user2.id)
        prev = data[gk].get(sk, {})
        prev_count = prev.get('count', 0)
        data[gk][sk] = {
            'count': prev_count + 1,
            'last_ship': datetime.now().isoformat(),
            'percentage': 100,
            'users': [user1.id, user2.id],
            'forced_by': ctx.author.id
        }
        _save_ship_data(data)

        img = img_ship(user1, user2, 100, prev_count + 1)
        f = discord.File(fp=img, filename='forceship.png')
        e = discord.Embed(
            title="FORCESHIP 100%",
            description=f"**{user1.display_name}** x **{user2.display_name}**\n*MATCH PERFEITO*",
            color=discord.Color.red())
        e.set_image(url="attachment://forceship.png")
        await ctx.send(file=f, embed=e)


async def setup(bot):
    await bot.add_cog(ShipCog(bot))
