import discord
import math
from discord import ui
from datetime import datetime, timedelta

from images import img_voice, img_chat, img_econ
from database import all_chat, all_econ, voice_period, get_voice_totals, get_voice_since, get_chat_total_messages
from utils import now_brazil

PER_PAGE = 10


# ============================================================
# PAGINATION VIEW
# ============================================================
class ViewPag(ui.View):
    def __init__(self, bot, kind, data, guild, per_page=PER_PAGE, **kw):
        super().__init__(timeout=300)
        self.bot = bot
        self.kind = kind
        self.all_data = data
        self.guild = guild
        self.per_page = per_page
        self.page = 1
        self.total_pages = max(1, math.ceil(len(data) / per_page)) if data else 1
        self.prev_btn.disabled = True
        if self.total_pages <= 1:
            self.prev_btn.disabled = True
            self.next_btn.disabled = True

    def _get_page(self):
        s = (self.page - 1) * self.per_page
        return self.all_data[s:s + self.per_page]

    def _make(self):
        pg = self._get_page()
        if self.kind == 'voice':
            b = img_voice(pg, self.guild.name, self.bot, self.guild)
            fn, col = 'r.png', 0xfbbf24
        elif self.kind == 'chat':
            b = img_chat(pg, self.guild.name, self.bot, self.guild)
            fn, col = 'r.png', 0xa855f7
        else:
            b = img_econ(pg, self.guild.name, self.bot, self.guild)
            fn, col = 'r.png', 0xeab308
        return discord.File(fp=b, filename=fn), fn, col

    def _embed(self):
        _, _, col = self._make()
        return discord.Embed(
            title=f"RANKING {self.kind.upper()}",
            description=f"Pag **{self.page}/{self.total_pages}** | Total: **{len(self.all_data)}**",
            color=col)

    async def refresh(self, ix: discord.Interaction):
        self.prev_btn.disabled = self.page <= 1
        self.next_btn.disabled = self.page >= self.total_pages
        f, fn, col = self._make()
        e = self._embed()
        e.set_image(url=f'attachment://{fn}')
        try:
            await ix.response.edit_message(embed=e, attachments=[f], view=self)
        except discord.NotFound:
            self.stop()
        except discord.HTTPException:
            pass

    @ui.button(label='<', style=discord.ButtonStyle.primary)
    async def prev_btn(self, ix: discord.Interaction, b: ui.Button):
        if self.page > 1:
            self.page -= 1
            await self.refresh(ix)

    @ui.button(label='>', style=discord.ButtonStyle.primary)
    async def next_btn(self, ix: discord.Interaction, b: ui.Button):
        if self.page < self.total_pages:
            self.page += 1
            await self.refresh(ix)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ============================================================
# RFIXO VIEW - Voice + Chat + Economy tabs
# ============================================================
class RankingView(ui.View):
    def __init__(self, bot, guild):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild = guild
        self.tab = 'voz'
        self.page = 1
        self.total_pages = 1

    def _data(self):
        now = now_brazil()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        if self.tab == 'voz':
            d = get_voice_totals(self.guild.id)
            for _gid, uid, jt in self.bot.iter_active_sessions(self.guild.id):
                g = self.bot.get_guild(self.guild.id)
                if g:
                    m = g.get_member(uid)
                    if m and m.voice and m.voice.channel and self.bot.voice_channel_counts_for_ranking(m.voice.channel):
                        cur = int((now - jt).total_seconds())
                        found = False
                        for idx, (u2, v2) in enumerate(d):
                            if u2 == uid:
                                d[idx] = (u2, v2 + cur)
                                found = True
                                break
                        if not found:
                            d.append((uid, cur))
            d.sort(key=lambda x: x[1], reverse=True)
            return d, 'voice'

        if self.tab == 'voz_d':
            d = get_voice_since(self.guild.id, today.isoformat())
            for _gid, uid, jt in self.bot.iter_active_sessions(self.guild.id):
                m = self.guild.get_member(uid)
                if m and m.voice and m.voice.channel and self.bot.voice_channel_counts_for_ranking(m.voice.channel):
                    cur = int((now - jt).total_seconds())
                    found = False
                    for idx, (u2, v2) in enumerate(d):
                        if u2 == uid:
                            d[idx] = (u2, v2 + cur)
                            found = True
                            break
                    if not found:
                        d.append((uid, cur))
            d.sort(key=lambda x: x[1], reverse=True)
            return d, 'voice'

        if self.tab in ('voz_s', 'voz_m'):
            start = week_start if self.tab == 'voz_s' else month_start
            d = get_voice_since(self.guild.id, start.isoformat())
            return d, 'voice'

        if self.tab == 'total':
            d = get_chat_total_messages(self.guild.id)
            return d, 'chat'

        if self.tab == 'tot':
            return all_econ(self.guild.id), 'econ'

        return [], 'voice'

    def _render(self):
        d, kind = self._data()
        self.total_pages = max(1, math.ceil(len(d) / PER_PAGE))
        s = (self.page - 1) * PER_PAGE
        e = s + PER_PAGE
        pg = d[s:e]

        titles = {
            'voz': (f"RANKING VOZ TOTAL: {self.guild.name[:15].upper()}", 0xfbbf24),
            'voz_d': (f"RANKING VOZ HOJE: {self.guild.name[:15].upper()}", 0x22c55e),
            'voz_s': (f"RANKING VOZ SEMANA: {self.guild.name[:15].upper()}", 0x3b82f6),
            'voz_m': (f"RANKING VOZ MES: {self.guild.name[:15].upper()}", 0xec4899),
            'total': (f"RANKING MSGS TOTAL: {self.guild.name[:15].upper()}", 0xa855f7),
            'tot': (f"RANKING ToT COINS: {self.guild.name[:15].upper()}", 0xeab308),
        }
        title, color = titles.get(self.tab, ('RANKING', 0x555555))

        if kind == 'voice':
            b = img_voice(pg, self.guild.name, self.bot, self.guild, title=title)
        elif kind == 'chat':
            b = img_chat(pg, self.guild.name, self.bot, self.guild, title=title)
        else:
            b = img_econ(pg, self.guild.name, self.bot, self.guild)

        emb = discord.Embed(title=title, description=f"Pag **{self.page}/{self.total_pages}** | Total: **{len(d)}**",
                            color=color)
        emb.set_image(url='attachment://r.png')
        return emb, discord.File(fp=b, filename='r.png')

    async def refresh(self, ix: discord.Interaction):
        e, f = self._render()
        self.prev.disabled = self.page <= 1
        self.next.disabled = self.page >= self.total_pages
        # Highlight active tab
        styles = {'voz': discord.ButtonStyle.primary, 'voz_d': discord.ButtonStyle.green,
                  'voz_s': discord.ButtonStyle.blurple, 'voz_m': discord.ButtonStyle.red,
                  'total': discord.ButtonStyle.primary, 'tot': discord.ButtonStyle.green}
        btn_map = [('voz', self.btn_voz), ('voz_d', self.btn_dia), ('voz_s', self.btn_sem),
                   ('voz_m', self.btn_men), ('total', self.btn_total_chat), ('tot', self.btn_tot)]
        for btn_name, btn in btn_map:
            btn.style = styles.get(btn_name, discord.ButtonStyle.secondary) if btn_name == self.tab else discord.ButtonStyle.secondary
        try:
            await ix.response.edit_message(embed=e, attachments=[f], view=self)
        except discord.NotFound:
            self.stop()
        except discord.HTTPException:
            pass

    def _set_tab(self, tab):
        self.tab = tab
        self.page = 1

    @ui.button(label='<')
    async def prev(self, ix: discord.Interaction, b: ui.Button):
        if self.page > 1:
            self.page -= 1
            await self.refresh(ix)

    @ui.button(label='>')
    async def next(self, ix: discord.Interaction, b: ui.Button):
        if self.page < self.total_pages:
            self.page += 1
            await self.refresh(ix)

    @ui.button(label='Voz', style=discord.ButtonStyle.primary)
    async def btn_voz(self, ix: discord.Interaction, b: ui.Button):
        self._set_tab('voz')
        await self.refresh(ix)

    @ui.button(label='Dia', style=discord.ButtonStyle.secondary)
    async def btn_dia(self, ix: discord.Interaction, b: ui.Button):
        self._set_tab('voz_d')
        await self.refresh(ix)

    @ui.button(label='Sem', style=discord.ButtonStyle.secondary)
    async def btn_sem(self, ix: discord.Interaction, b: ui.Button):
        self._set_tab('voz_s')
        await self.refresh(ix)

    @ui.button(label='Men', style=discord.ButtonStyle.secondary)
    async def btn_men(self, ix: discord.Interaction, b: ui.Button):
        self._set_tab('voz_m')
        await self.refresh(ix)

    @ui.button(label='Total', style=discord.ButtonStyle.secondary)
    async def btn_total_chat(self, ix: discord.Interaction, b: ui.Button):
        self._set_tab('total')
        await self.refresh(ix)

    @ui.button(label='ToT', style=discord.ButtonStyle.secondary)
    async def btn_tot(self, ix: discord.Interaction, b: ui.Button):
        self._set_tab('tot')
        await self.refresh(ix)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ============================================================
# CFIXO VIEW - Chat only
# ============================================================
class CfixoView(ui.View):
    def __init__(self, bot, guild):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild = guild
        self.tab = 'diario'
        self.page = 1
        self.total_pages = 1

    def _data(self):
        fields = {'diario': 'today_messages', 'semanal': 'week_messages',
                  'mensal': 'month_messages', 'total': 'total_messages'}
        return all_chat(self.guild.id, fields.get(self.tab, 'total_messages')), 'chat'

    def _render(self):
        d, kind = self._data()
        self.total_pages = max(1, math.ceil(len(d) / PER_PAGE))
        s = (self.page - 1) * PER_PAGE
        e = s + PER_PAGE
        pg = d[s:e]

        titles = {
            'diario': (f"RANKING CHAT HOJE: {self.guild.name[:15].upper()}", 0x22c55e),
            'semanal': (f"RANKING CHAT SEMANA: {self.guild.name[:15].upper()}", 0x3b82f6),
            'mensal': (f"RANKING CHAT MES: {self.guild.name[:15].upper()}", 0xec4899),
            'total': (f"RANKING CHAT TOTAL: {self.guild.name[:15].upper()}", 0xa855f7),
        }
        title, color = titles.get(self.tab, ('RANKING', 0x555555))

        b = img_chat(pg, self.guild.name, self.bot, self.guild, title=title)
        emb = discord.Embed(title=title, description=f"Pag **{self.page}/{self.total_pages}** | Total: **{len(d)}**",
                            color=color)
        emb.set_image(url='attachment://r.png')
        return emb, discord.File(fp=b, filename='r.png')

    async def refresh(self, ix: discord.Interaction):
        e, f = self._render()
        self.prev.disabled = self.page <= 1
        self.next.disabled = self.page >= self.total_pages
        styles = {'diario': discord.ButtonStyle.green, 'semanal': discord.ButtonStyle.blurple,
                  'mensal': discord.ButtonStyle.red, 'total': discord.ButtonStyle.primary}
        for btn_name, btn in [('diario', self.btn_dia), ('semanal', self.btn_sem), ('mensal', self.btn_men),
                               ('total', self.btn_tot)]:
            btn.style = styles.get(btn_name, discord.ButtonStyle.secondary) if btn_name == self.tab else discord.ButtonStyle.secondary
        try:
            await ix.response.edit_message(embed=e, attachments=[f], view=self)
        except discord.NotFound:
            self.stop()
        except discord.HTTPException:
            pass

    def _set_tab(self, tab):
        self.tab = tab
        self.page = 1

    @ui.button(label='<')
    async def prev(self, ix: discord.Interaction, b: ui.Button):
        if self.page > 1:
            self.page -= 1
            await self.refresh(ix)

    @ui.button(label='>')
    async def next(self, ix: discord.Interaction, b: ui.Button):
        if self.page < self.total_pages:
            self.page += 1
            await self.refresh(ix)

    @ui.button(label='Diario', style=discord.ButtonStyle.green)
    async def btn_dia(self, ix: discord.Interaction, b: ui.Button):
        self._set_tab('diario')
        await self.refresh(ix)

    @ui.button(label='Semanal', style=discord.ButtonStyle.secondary)
    async def btn_sem(self, ix: discord.Interaction, b: ui.Button):
        self._set_tab('semanal')
        await self.refresh(ix)

    @ui.button(label='Mensal', style=discord.ButtonStyle.secondary)
    async def btn_men(self, ix: discord.Interaction, b: ui.Button):
        self._set_tab('mensal')
        await self.refresh(ix)

    @ui.button(label='Total', style=discord.ButtonStyle.secondary)
    async def btn_tot(self, ix: discord.Interaction, b: ui.Button):
        self._set_tab('total')
        await self.refresh(ix)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
