"""Voice, chat, economy commands + NEW: /top, /leaderboard, /transferir, /loja, /ping, /avatar, /userinfo, /serverinfo"""
import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import math
from datetime import datetime, timedelta
import pytz
import json
import os
import random

def _get_brazil_tz():
    tz_file = 'data/timezone_config.json'
    tz = 'America/Sao_Paulo'
    if os.path.exists(tz_file):
        try:
            with open(tz_file, 'r') as f:
                config = json.load(f)
                tz = config.get('timezone', 'America/Sao_Paulo')
        except Exception:
            pass
    return pytz.timezone(tz)

def _now_brazil():
    return datetime.now(_get_brazil_tz())

def _ensure_aware(dt):
    if dt.tzinfo is None:
        return _get_brazil_tz().localize(dt)
    return dt

from images import img_voice, img_chat, img_econ, img_profile, img_saldo, img_leaderboard, fmt_time, get_member_name
from database import *
from cogs._views import ViewPag, RankingView, CfixoView, PER_PAGE
from auth import is_admin


def fmt_sec(s):
    s = max(0, int(s))
    h = s // 3600; m = (s % 3600) // 60; sec = s % 60
    if h > 0: return f"{h}h {m}m {sec}s"
    if m > 0: return f"{m}m {sec}s"
    return f"{sec}s"


class VoiceCog(commands.Cog, name="Comandos"):
    def __init__(self, bot):
        self.bot = bot

    def _cur_voice(self, guild_id):
        data = get_all_voice(guild_id)
        r = []
        for uid, saved in data:
            cur = 0
            jt = self.bot.get_active_session_start(guild_id, uid)
            if jt:
                g_mem = self.bot.get_guild(guild_id)
                m_mem = g_mem.get_member(uid) if g_mem else None
                if m_mem and m_mem.voice and m_mem.voice.channel and self.bot.voice_channel_counts_for_ranking(m_mem.voice.channel):
                    cur = int((_now_brazil() - _ensure_aware(jt)).total_seconds())
            r.append((uid, saved + cur))
        g = self.bot.get_guild(guild_id)
        if g:
            for _gid, uid, jt in self.bot.iter_active_sessions(guild_id):
                m = g.get_member(uid)
                if m and m.voice and m.voice.channel and self.bot.voice_channel_counts_for_ranking(m.voice.channel):
                    if not any(x[0] == uid for x in r):
                        r.append((uid, int((_now_brazil() - _ensure_aware(jt)).total_seconds())))
        r.sort(key=lambda x: x[1], reverse=True)
        return r

    # ============================================================
    # EXISTING COMMANDS — all prefix !
    # ============================================================
    @app_commands.command(name='call', description='Ranking de voz atual')
    async def call(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = self._cur_voice(interaction.guild.id)
        if not data:
            return await interaction.followup.send("Ranking vazio.")
        tp = max(1, math.ceil(len(data) / PER_PAGE))
        pg = data[:PER_PAGE]
        b = img_voice(pg, interaction.guild.name, self.bot, interaction.guild)
        f = discord.File(fp=b, filename='r.png')
        online = sum(1 for u, _ in pg if self.bot.is_user_in_active_session(interaction.guild.id, u))
        e = discord.Embed(
            title="RANKING DE VOZ",
            description=f"Pag **1**/{tp} | Total: **{len(data)}** | Em call: **{online}**",
            color=0xfbbf24)
        e.set_image(url='attachment://r.png')
        view = ViewPag(self.bot, 'voice', data, interaction.guild, PER_PAGE)
        await interaction.followup.send(embed=e, file=f, view=view)

    @app_commands.command(name='profile', description='Perfil de voz de um membro')
    @app_commands.describe(membro='Membro para ver o perfil')
    async def profile(self, interaction: discord.Interaction, membro: discord.Member = None):
        t = membro or interaction.user
        data = get_voice(interaction.guild.id, t.id)
        cur = self.bot.get_current_voice_time(interaction.guild.id, t.id)
        if not data:
            if cur == 0:
                return await interaction.response.send_message(f"Sem dados para {t.mention}.")
            data = (interaction.guild.id, t.id, cur, 1, cur, _now_brazil())
        else:
            d = list(data)
            d[2] += cur
            if cur > d[4]:
                d[4] = cur
            data = tuple(d)
        av2 = self._cur_voice(interaction.guild.id)
        pos = next((i + 1 for i, (u, _) in enumerate(av2) if u == t.id), 1)
        ic = self.bot.is_user_in_active_session(interaction.guild.id, t.id)
        img = img_profile(t, data, pos, ic)
        extra = " EM CALL AGORA" if ic else ""
        await interaction.response.send_message(content=extra, file=discord.File(fp=img, filename='profile.png'))

    @app_commands.command(name='chattop', description='Ranking de chat')
    async def chattop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = all_chat(interaction.guild.id, 'total_messages')
        if not data:
            return await interaction.followup.send("Sem dados de chat.")
        tp = max(1, math.ceil(len(data) / 10))
        view = ViewPag(self.bot, 'chat', data, interaction.guild, 10)
        pg = data[:10]
        b = img_chat(pg, interaction.guild.name, self.bot, interaction.guild)
        f = discord.File(fp=b, filename='r.png')
        e = discord.Embed(title="RANKING DE CHAT", description=f"Pag 1/{tp} | Total: {len(data)}", color=0xa855f7)
        e.set_image(url='attachment://r.png')
        await interaction.followup.send(embed=e, file=f, view=view)

    # rfixo e cfixo continuam como slash
    @app_commands.command(name='rfixo', description='Ranking fixo de voz com botoes')
    @app_commands.default_permissions(administrator=True)
    async def rfixo(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = RankingView(self.bot, interaction.guild)
        e, f = view._render()
        msg = await interaction.followup.send(embed=e, file=f, view=view)
        self.bot.auto_rankings[f"rfixo_{interaction.guild.id}_{msg.id}"] = {
            'guild_id': interaction.guild.id, 'channel_id': interaction.channel.id, 'message_id': msg.id}
        if hasattr(self.bot, 'save_auto_rankings'):
            self.bot.save_auto_rankings()

    @app_commands.command(name='cfixo', description='Ranking fixo de chat com botoes')
    @app_commands.default_permissions(administrator=True)
    async def cfixo(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = CfixoView(self.bot, interaction.guild)
        e, f = view._render()
        msg = await interaction.followup.send(embed=e, file=f, view=view)
        self.bot.auto_rankings[f"cfixo_{interaction.guild.id}_{msg.id}"] = {
            'guild_id': interaction.guild.id, 'channel_id': interaction.channel.id, 'message_id': msg.id,
            'view_type': 'cfixo'}
        if hasattr(self.bot, 'save_auto_rankings'):
            self.bot.save_auto_rankings()

    @app_commands.command(name='saldo', description='Ve seu saldo de ToT')
    async def saldo(self, interaction: discord.Interaction):
        econ = get_econ(interaction.guild.id, interaction.user.id)
        if not econ:
            ensure_econ(interaction.guild.id, interaction.user.id)
            econ = get_econ(interaction.guild.id, interaction.user.id) or (interaction.guild.id, interaction.user.id, 0, 0, None, None)

        ae = all_econ(interaction.guild.id)
        pos = next((i + 1 for i, (u, _) in enumerate(ae) if u == interaction.user.id), '-')
        daily_earned = econ[3] if econ and econ[3] else 0

        img = img_saldo(interaction.user, econ, pos, daily_earned)
        file = discord.File(fp=img, filename='saldo.png')
        e = discord.Embed(color=0xeab308)
        e.set_image(url="attachment://saldo.png")
        await interaction.response.send_message(file=file, embed=e)

    @commands.command(name='diario', description='Ve o resumo diario de voz, chat e ToT')
    async def diario(self, ctx):
        now = _now_brazil()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        conn = sqlite3.connect('voice_stats.db')
        c = conn.cursor()
        c.execute('SELECT user_id,SUM(duration) FROM voice_sessions WHERE guild_id=? AND leave_time>=? GROUP BY user_id ORDER BY SUM(duration) DESC',
                 (ctx.guild.id, today.isoformat()))
        vd = c.fetchall()
        conn.close()
        for _gid, u, jt in self.bot.iter_active_sessions(ctx.guild.id):
            m = ctx.guild.get_member(u)
            if m and m.voice and m.voice.channel and self.bot.voice_channel_counts_for_ranking(m.voice.channel):
                cur = int((now - jt).total_seconds())
                ext = [x[0] for x in vd]
                if u not in ext:
                    vd.append((u, cur))
                else:
                    for idx, (u2, v2) in enumerate(vd):
                        if u2 == u:
                            vd[idx] = (u2, v2 + cur)
                            break
        econ = get_econ(ctx.guild.id, ctx.author.id)
        dv = econ[3] if econ and econ[3] else 0
        cs = get_chat(ctx.guild.id, ctx.author.id)
        tm = cs[3] if cs else 0
        ct = all_chat(ctx.guild.id, 'today_messages')
        vv = voice_period(ctx.guild.id, ctx.author.id, today)
        e = discord.Embed(title="RESUMO DIARIO", description=now.strftime('%d/%m/%Y'), color=0x22c55e)
        e.add_field(name="Sua voz hoje", value=fmt_sec(vv), inline=True)
        e.add_field(name="Suas msgs", value=str(tm), inline=True)
        e.add_field(name="ToT hoje", value=f"{dv} ToT", inline=True)
        tvt = get_member_name(self.bot, vd[0][0], ctx.guild) if vd else "-"
        tvs = fmt_sec(vd[0][1]) if vd else "0s"
        e.add_field(name="Top voz", value=f"{tvt} - {tvs}", inline=True)
        tct = get_member_name(self.bot, ct[0][0], ctx.guild) if ct else "-"
        tcc = str(ct[0][1]) if ct else "0"
        e.add_field(name="Top chat", value=f"{tct} - {tcc} msgs", inline=True)
        e.add_field(name="Em call", value=f"{self.bot.count_active_sessions(ctx.guild.id)} users", inline=True)
        await ctx.send(embed=e)

    @commands.command(name='semanal', description='Ve o resumo semanal de voz e chat')
    async def semanal(self, ctx):
        now = _now_brazil()
        ws = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        vd = all_voice_period(ctx.guild.id, ws)
        ct = all_chat(ctx.guild.id, 'week_messages')
        tv = vd[0] if vd else None
        tc = ct[0] if ct else None
        cr = get_chat(ctx.guild.id, ctx.author.id)
        e = discord.Embed(title="RESUMO SEMANAL", description=f"Desde {ws.strftime('%d/%m')}", color=0x3b82f6)
        if tv:
            e.add_field(name="Top voz", value=f"{get_member_name(self.bot, tv[0], ctx.guild)} - {fmt_sec(tv[1])}", inline=True)
        if tc:
            e.add_field(name="Top chat", value=f"{get_member_name(self.bot, tc[0], ctx.guild)} - {tc[1]} msgs", inline=True)
        e.add_field(name="Sua voz", value=fmt_sec(voice_period(ctx.guild.id, ctx.author.id, ws)), inline=True)
        e.add_field(name="Suas msgs", value=str(cr[4] if cr else 0), inline=True)
        await ctx.send(embed=e)

    @commands.command(name='mensal', description='Ve o resumo mensal de voz e chat')
    async def mensal(self, ctx):
        now = datetime.now()
        ms = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        vd = all_voice_period(ctx.guild.id, ms)
        ct = all_chat(ctx.guild.id, 'month_messages')
        tv = vd[0] if vd else None
        tc = ct[0] if ct else None
        cr = get_chat(ctx.guild.id, ctx.author.id)
        e = discord.Embed(title="RESUMO MENSAL", description=now.strftime('%B %Y'), color=0xec4899)
        if tv:
            e.add_field(name="Top voz", value=f"{get_member_name(self.bot, tv[0], ctx.guild)} - {fmt_sec(tv[1])}", inline=True)
        if tc:
            e.add_field(name="Top chat", value=f"{get_member_name(self.bot, tc[0], ctx.guild)} - {tc[1]} msgs", inline=True)
        e.add_field(name="Sua voz", value=fmt_sec(voice_period(ctx.guild.id, ctx.author.id, ms)), inline=True)
        e.add_field(name="Suas msgs", value=str(cr[5] if cr else 0), inline=True)
        await ctx.send(embed=e)

    # ============================================================
    # NEW COMMANDS — slash commands
    # ============================================================
    @app_commands.command(name='top', description='Ve o top 5 de voz, chat e economia')
    async def top(self, interaction: discord.Interaction):
        voice_data = self._cur_voice(interaction.guild.id)[:5]
        chat_data = all_chat(interaction.guild.id, 'total_messages')[:5]
        econ_data = all_econ(interaction.guild.id)[:5]

        img = img_leaderboard(voice_data, chat_data, econ_data, interaction.guild.name, self.bot, interaction.guild)
        f = discord.File(fp=img, filename='leaderboard.png')
        e = discord.Embed(
            title=f"\U0001F3C6 Leaderboard — {interaction.guild.name}",
            description="Top 5 de voz, chat e economia",
            color=0xfbbf24)
        e.set_image(url="attachment://leaderboard.png")
        await interaction.response.send_message(file=f, embed=e)

    @app_commands.command(name='leaderboard', description='Ve o leaderboard completo')
    async def leaderboard(self, interaction: discord.Interaction):
        await self.top(interaction)

    @app_commands.command(name='transferir', description='Transfira ToT para outro membro')
    async def transferir(self, interaction: discord.Interaction, membro: discord.Member, quantidade: int):
        if membro.bot:
            return await interaction.response.send_message("Nao e possivel transferir para bots.", ephemeral=True)
        if membro.id == interaction.user.id:
            return await interaction.response.send_message("Nao pode transferir para si mesmo.", ephemeral=True)
        if quantidade <= 0:
            return await interaction.response.send_message("Quantidade deve ser positiva.", ephemeral=True)

        econ = get_econ(interaction.guild.id, interaction.user.id)
        balance = econ[2] if econ else 0
        if balance < quantidade:
            return await interaction.response.send_message(f"Saldo insuficiente. Voce tem **{balance} ToT**.", ephemeral=True)

        ok = transfer_coins(interaction.guild.id, interaction.user.id, membro.id, quantidade)
        if not ok:
            return await interaction.response.send_message(
                "Nao foi possivel completar a transferencia (saldo insuficiente ou conflito de dados).",
                ephemeral=True
            )

        e = discord.Embed(
            title="\U0001F4B8 Transferencia Concluida",
            description=f"**{interaction.user.display_name}** transferiu **{quantidade} ToT** para **{membro.display_name}**",
            color=0x22c55e)
        e.set_footer(text=f"Seu novo saldo: {balance - quantidade} ToT")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name='loja', description='Ve e compre itens na loja')
    @app_commands.describe(acao="Acao: ver, comprar, adicionar, remover", item_id="ID do item para comprar/remover")
    async def loja(self, interaction: discord.Interaction, acao: str = "ver", item_id: int = None):
        """
        Usage:
          /loja acao:ver — ver itens
          /loja acao:comprar item_id:1 — comprar item
          /loja acao:adicionar nome:X descricao:Y preco:100 emoji:💎 — adicionar item (admin)
          /loja acao:remover item_id:1 — remover item (admin)
        """
        is_admin = interaction.user.guild_permissions.administrator

        if acao == "ver":
            items = get_shop_items(interaction.guild.id)
            if not items:
                return await interaction.response.send_message("A loja esta vazia. Admins podem adicionar itens com `/loja acao:adicionar`.",
                                      ephemeral=True)
            e = discord.Embed(
                title=f"\U0001F6CD️ Loja — {interaction.guild.name}",
                description="Use `/loja acao:comprar item_id:X` para comprar!",
                color=0xeab308)
            for item in items:
                iid, gid, name, desc, price, role_id, emoji = item
                emoji = emoji or "\U0001F4B0"
                role_text = f" <@&{role_id}>" if role_id else ""
                e.add_field(
                    name=f"{emoji} **{name}** (ID: {iid})",
                    value=f"{desc or 'Sem descricao'}\nPreco: **{price} ToT**{role_text}",
                    inline=False)
            await interaction.response.send_message(embed=e)

        elif acao == "comprar":
            if item_id is None:
                return await interaction.response.send_message("Informe o ID do item. Ex: `/loja acao:comprar item_id:1`", ephemeral=True)
            item, err = buy_item(interaction.guild.id, interaction.user.id, item_id)
            if err:
                return await interaction.response.send_message(f"\u274C {err}", ephemeral=True)
            name, role_id, emoji = item[2], item[5], item[6]
            e = discord.Embed(
                title="\U0001F389 Compra Concluida!",
                description=f"Voce comprou **{name}** {emoji or ''}!",
                color=0x22c55e)
            if role_id:
                role = interaction.guild.get_role(role_id)
                if role:
                    try:
                        await interaction.user.add_roles(role, reason=f"Compra na loja: {name}")
                        e.add_field(name="Cargo Entregue", value=role.mention)
                    except Exception:
                        e.add_field(name="Erro", value="Nao consegui entregar o cargo. Contate um admin.")
            await interaction.response.send_message(embed=e)

        elif acao == "adicionar":
            if not is_admin:
                return await interaction.response.send_message("Apenas administradores podem adicionar itens.", ephemeral=True)
            # Default item for quick add — user can use a modal for full details
            name = "Item Novo"
            desc = "Descricao do item"
            price = 100
            emoji = "\U0001F4B0"
            role_id = None
            iid = add_shop_item(interaction.guild.id, name, desc, price, role_id, emoji)
            e = discord.Embed(
                title="\u2705 Item Adicionado",
                description=f"Item **{name}** adicionado a loja (ID: {iid}).\nUse `/loja acao:remover item_id:{iid}` para remover.",
                color=0x22c55e)
            await interaction.response.send_message(embed=e)

        elif acao == "remover":
            if not is_admin:
                return await interaction.response.send_message("Apenas administradores podem remover itens.", ephemeral=True)
            if item_id is None:
                return await interaction.response.send_message("Informe o ID do item.", ephemeral=True)
            delete_shop_item(interaction.guild.id, item_id)
            await interaction.response.send_message(f"Item {item_id} removido da loja.", ephemeral=True)

    @app_commands.command(name='daily', description='Resgate recompensa diaria de ToT')
    async def daily(self, interaction: discord.Interaction):
        amount = 120
        ok, streak = claim_daily(interaction.guild.id, interaction.user.id, amount)
        if not ok:
            return await interaction.response.send_message("Voce ja resgatou seu daily hoje.", ephemeral=True)
        await interaction.response.send_message(f"Daily resgatado: **+{amount} ToT** | Streak: **{streak}** dia(s).")

    @app_commands.command(name='work', description='Trabalhe para ganhar ToT')
    @app_commands.checks.cooldown(1, 3600.0)
    async def work(self, interaction: discord.Interaction):
        gain = random.randint(60, 180)
        add_coins(interaction.guild.id, interaction.user.id, gain)
        await interaction.response.send_message(f"Voce trabalhou e ganhou **{gain} ToT**.")

    @app_commands.command(name='crime', description='Tente um crime arriscado por ToT')
    @app_commands.checks.cooldown(1, 7200.0)
    async def crime(self, interaction: discord.Interaction):
        success = random.random() < 0.58
        if success:
            gain = random.randint(80, 260)
            add_coins(interaction.guild.id, interaction.user.id, gain)
            return await interaction.response.send_message(f"Crime bem sucedido! **+{gain} ToT**.")
        loss = random.randint(40, 120)
        remove_coins(interaction.guild.id, interaction.user.id, loss)
        await interaction.response.send_message(f"Voce foi pego! **-{loss} ToT**.")

    @app_commands.command(name='roubar', description='Tente roubar ToT de outro membro')
    @app_commands.checks.cooldown(1, 10800.0)
    async def roubar(self, interaction: discord.Interaction, alvo: discord.Member):
        if alvo.bot or alvo.id == interaction.user.id:
            return await interaction.response.send_message("Escolha um alvo valido.", ephemeral=True)
        victim_econ = get_econ(interaction.guild.id, alvo.id)
        victim_balance = victim_econ[2] if victim_econ else 0
        if victim_balance < 50:
            return await interaction.response.send_message("Esse alvo tem pouco saldo para roubo.", ephemeral=True)
        success = random.random() < 0.42
        if success:
            stolen = min(victim_balance, random.randint(40, 180))
            ok = transfer_coins(interaction.guild.id, alvo.id, interaction.user.id, stolen)
            if not ok:
                return await interaction.response.send_message("Roubo falhou por conflito de saldo.", ephemeral=True)
            return await interaction.response.send_message(f"Roubo bem sucedido! Voce roubou **{stolen} ToT** de {alvo.mention}.")
        penalty = random.randint(30, 90)
        remove_coins(interaction.guild.id, interaction.user.id, penalty)
        await interaction.response.send_message(f"Roubo falhou! Multa de **{penalty} ToT**.")

    @app_commands.command(name='market_list', description='Ver anuncios do mercado')
    async def market_list(self, interaction: discord.Interaction):
        rows = get_market_listings(interaction.guild.id, 20)
        if not rows:
            return await interaction.response.send_message("Mercado vazio.")
        desc = []
        for listing_id, seller_id, item_id, qty, price, _created, name, emoji in rows[:15]:
            item_name = name or f"Item {item_id}"
            desc.append(f"`{listing_id}` • {(emoji or '💠')} **{item_name}** x{qty} — {price} ToT (vendedor <@{seller_id}>)")
        e = discord.Embed(title="Mercado", description="\n".join(desc), color=0x22c55e)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name='market_sell', description='Anunciar item no mercado')
    async def market_sell(self, interaction: discord.Interaction, item_id: int, quantidade: int, preco: int):
        if quantidade < 1 or preco < 1:
            return await interaction.response.send_message("Quantidade e preco precisam ser positivos.", ephemeral=True)
        ok = adjust_inventory(interaction.guild.id, interaction.user.id, item_id, -int(quantidade))
        if not ok:
            return await interaction.response.send_message("Voce nao possui essa quantidade no inventario.", ephemeral=True)
        lid = create_market_listing(interaction.guild.id, interaction.user.id, item_id, int(quantidade), int(preco))
        await interaction.response.send_message(f"Anuncio criado no mercado com ID `{lid}`.")

    @app_commands.command(name='market_buy', description='Comprar um anuncio do mercado')
    async def market_buy(self, interaction: discord.Interaction, listing_id: int):
        ok, msg = buy_market_listing(interaction.guild.id, interaction.user.id, listing_id)
        if not ok:
            return await interaction.response.send_message(msg, ephemeral=True)
        await interaction.response.send_message("Compra concluida com sucesso.")

    @app_commands.command(name='ping', description='Ve a latencia do bot')
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        if latency < 100:
            color = 0x22c55e
            status = "\U0001F7E2 Excelente"
        elif latency < 200:
            color = 0xeab308
            status = "\U0001F7E1 Bom"
        elif latency < 400:
            color = 0xf97316
            status = "\U0001F7E0 Medio"
        else:
            color = 0xef4444
            status = "\U0001F534 Alto"

        e = discord.Embed(title="\U0001F3D3 Pong!", color=color)
        e.add_field(name="Latencia", value=f"**{latency}ms**", inline=True)
        e.add_field(name="Status", value=status, inline=True)
        e.set_footer(text=f"WebSocket: {self.bot.latency * 1000:.1f}ms")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name='avatar', description='Ve o avatar de um membro')
    @app_commands.describe(membro='Membro para ver o avatar')
    async def avatar(self, interaction: discord.Interaction, membro: discord.Member = None):
        m = membro or interaction.user
        e = discord.Embed(title=f"Avatar de {m.display_name}", color=0x5865f2)
        e.set_image(url=m.display_avatar.url)
        e.set_footer(text="Clique no link para ver em tamanho completo")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Abrir Imagem",
            url=m.display_avatar.url,
            style=discord.ButtonStyle.link))
        await interaction.response.send_message(embed=e, view=view)

    @app_commands.command(name='userinfo', description='Ve informacoes detalhadas de um membro')
    @app_commands.describe(membro='Membro para ver informacoes')
    async def userinfo(self, interaction: discord.Interaction, membro: discord.Member = None):
        m = membro or interaction.user
        guild = interaction.guild

        voice = get_voice(guild.id, m.id)
        voice_total = voice[2] if voice else 0
        voice_sessions = voice[3] if voice else 0
        voice_record = voice[4] if voice else 0

        chat = get_chat(guild.id, m.id)
        chat_total = chat[2] if chat else 0

        econ = get_econ(guild.id, m.id)
        coins = econ[2] if econ else 0

        voice_rank = self._cur_voice(guild.id)
        pos = next((i + 1 for i, (u, _) in enumerate(voice_rank) if u == m.id), '-')

        roles = [r.mention for r in m.roles if r != guild.me]
        roles_str = ', '.join(roles[-5:]) if roles else "Nenhum"
        if len(roles) > 5:
            roles_str += f" (+{len(roles) - 5})"

        e = discord.Embed(
            title=f"\U0001F464 {m.display_name}",
            description=f"ID: `{m.id}`",
            color=m.accent_color or 0x5865f2)
        e.set_thumbnail(url=m.display_avatar.url)

        e.add_field(name="Conta Criada", value=f"<t:{int(m.created_at.timestamp())}:R>", inline=True)
        e.add_field(name="Entrou em", value=f"<t:{int(m.joined_at.timestamp())}:R>", inline=True)

        stats_text = (
            f"**Voz:** {fmt_sec(voice_total)}\n"
            f"**Sessoes:** {voice_sessions}\n"
            f"**Recorde:** {fmt_sec(voice_record)}\n"
            f"**Ranking:** #{pos}\n"
            f"**Chat:** {chat_total} msgs\n"
            f"**ToT:** {coins}"
        )
        e.add_field(name="\U0001F4CA Estatisticas", value=stats_text, inline=False)

        if roles:
            e.add_field(name=f"Cargos ({len(roles)})", value=roles_str, inline=False)

        await interaction.response.send_message(embed=e)

    @app_commands.command(name='serverinfo', description='Ve informacoes do servidor')
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild

        humans = sum(1 for m in guild.members if not m.bot)
        bots = sum(1 for m in guild.members if m.bot)

        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)

        roles_count = len(guild.roles)
        emoji_count = len(guild.emojis)

        boost_level = guild.premium_tier
        boost_count = guild.premium_subscription_count or 0

        e = discord.Embed(
            title=f"\U0001F3F0 {guild.name}",
            description=guild.description or "Sem descricao.",
            color=0x5865f2)

        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)

        e.add_field(name="Dono", value=guild.owner.mention if guild.owner else "Desconhecido", inline=True)
        e.add_field(name="Criado em", value=f"<t:{int(guild.created_at.timestamp())}:R>", inline=True)
        e.add_field(name="ID", value=f"`{guild.id}`", inline=True)

        e.add_field(name="Membros", value=f"**{humans}** humanos, **{bots}** bots\nTotal: **{guild.member_count}**", inline=True)
        e.add_field(name="Canais", value=f"{text_channels} texto, {voice_channels} voz, {categories} categorias", inline=True)
        e.add_field(name="Boosts", value=f"Nivel **{boost_level}** ({boost_count} boosts)", inline=True)

        e.add_field(name="Emojis", value=f"{emoji_count} emojis", inline=True)
        e.add_field(name="Roles", value=f"{roles_count} cargos", inline=True)
        e.set_footer(text=f"Bot Primal System")

        if guild.banner:
            e.set_image(url=guild.banner.url)

        await interaction.response.send_message(embed=e)

    # ============================================================
    # ADMIN COMMANDS — slash commands
    # ============================================================
    def is_authorized(self, interaction):
        return is_admin(interaction.user.id)

    @app_commands.command(name='addhoras', description='Adiciona horas de voz a um membro')
    @app_commands.default_permissions(administrator=True)
    async def addhoras(self, interaction: discord.Interaction, membro: discord.Member, horas: int):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("Voce nao tem permissao para usar este comando.", ephemeral=True)
        if horas <= 0:
            return await interaction.response.send_message("Valor positivo.", ephemeral=True)
        add_voice_seconds(interaction.guild.id, membro.id, horas * 3600)
        await interaction.response.send_message(f"Adicionadas **{horas}h** a {membro.mention}!")

    @app_commands.command(name='rmhoras', description='Remove horas de voz de um membro')
    @app_commands.default_permissions(administrator=True)
    async def rmhoras(self, interaction: discord.Interaction, membro: discord.Member, horas: int):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("Voce nao tem permissao para usar este comando.", ephemeral=True)
        if horas <= 0:
            return await interaction.response.send_message("Valor positivo.", ephemeral=True)
        remove_voice_seconds(interaction.guild.id, membro.id, horas * 3600)
        await interaction.response.send_message(f"Removidas **{horas}h** de {membro.mention}!")

    @app_commands.command(name='debug_voice_session', description='Mostra o estado da sessao de voz de um membro')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(membro='Membro para inspecionar a sessao de voz')
    async def debug_voice_session(self, interaction: discord.Interaction, membro: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Apenas administradores podem usar este comando.", ephemeral=True)

        guild_id = interaction.guild.id
        session_start = self.bot.get_active_session_start(guild_id, membro.id)
        in_voice = bool(membro.voice and membro.voice.channel)
        channel = membro.voice.channel if in_voice else None
        channel_counts = self.bot.voice_channel_counts_for_ranking(channel) if channel else False

        if in_voice and channel_counts:
            state = "CONTANDO"
        elif in_voice and not channel_counts:
            state = "PAUSADO (canal excluido no rconfig)"
        elif session_start:
            state = "SESSAO ATIVA SEM CANAL (reconexao pendente)"
        else:
            state = "SEM SESSAO"

        current_seconds = self.bot.get_current_voice_time(guild_id, membro.id)
        total_row = get_voice(guild_id, membro.id)
        total_saved = total_row[2] if total_row else 0

        started_text = "-"
        elapsed_text = "0s"
        if session_start:
            started_text = _ensure_aware(session_start).strftime("%d/%m/%Y %H:%M:%S")
            elapsed_text = fmt_sec(max(0, int((_now_brazil() - _ensure_aware(session_start)).total_seconds())))

        e = discord.Embed(
            title="DEBUG VOICE SESSION",
            description=f"Inspecao de {membro.mention}",
            color=0x5865f2
        )
        e.add_field(name="Estado", value=state, inline=False)
        e.add_field(name="Em call agora", value="Sim" if in_voice else "Nao", inline=True)
        e.add_field(name="Canal atual", value=channel.mention if channel else "-", inline=True)
        e.add_field(name="Canal conta no ranking", value="Sim" if channel_counts else "Nao", inline=True)
        e.add_field(name="Sessao ativa em memoria", value="Sim" if session_start else "Nao", inline=True)
        e.add_field(name="Inicio da sessao", value=started_text, inline=True)
        e.add_field(name="Tempo corrido da sessao", value=elapsed_text, inline=True)
        e.add_field(name="Tempo atual que entra no profile", value=fmt_sec(current_seconds), inline=True)
        e.add_field(name="Tempo salvo no banco", value=fmt_sec(total_saved), inline=True)
        e.set_footer(text=f"guild={guild_id} | user={membro.id}")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name='reset_user', description='Reseta dados de um usuario')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.cooldown(1, 20.0)
    async def reset_user(self, interaction: discord.Interaction, membro: discord.Member):
        wipe_user(interaction.guild.id, membro.id)
        await interaction.response.send_message(f"Dados de {membro.mention} resetados.")

    @app_commands.command(name='reset_server', description='Reseta dados do servidor')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.cooldown(1, 60.0)
    async def reset_server(self, interaction: discord.Interaction):
        wipe_guild(interaction.guild.id)
        await interaction.response.send_message("**LIMPEZA GERAL:** Todos os dados foram resetados!")

    @app_commands.command(name='addtot', description='Adiciona ToT a um membro')
    @app_commands.default_permissions(administrator=True)
    async def add_tot(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("Voce nao tem permissao para usar este comando.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("Valor positivo.", ephemeral=True)
        add_coins(interaction.guild.id, member.id, amount)
        await interaction.response.send_message(f"Adicionadas **{amount} ToT** a {member.mention}!")

    @app_commands.command(name='rtot', description='Remove ToT de um membro')
    @app_commands.default_permissions(administrator=True)
    async def r_tot(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("Voce nao tem permissao para usar este comando.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("Valor positivo.", ephemeral=True)
        remove_coins(interaction.guild.id, member.id, amount)
        await interaction.response.send_message(f"Removidas **{amount} ToT** de {member.mention}!")

    @app_commands.command(name='setcoins', description='Define saldo de ToT de um membro')
    @app_commands.default_permissions(administrator=True)
    async def setcoins(self, interaction: discord.Interaction, membro: discord.Member, quantidade: int):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("Voce nao tem permissao.", ephemeral=True)
        if quantidade < 0:
            return await interaction.response.send_message("Valor nao pode ser negativo.", ephemeral=True)
        set_coins(interaction.guild.id, membro.id, quantidade)
        await interaction.response.send_message(f"Saldo de {membro.mention} definido para **{quantidade} ToT**.")

    # HELP fica como slash (em new_commands.py)


async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
