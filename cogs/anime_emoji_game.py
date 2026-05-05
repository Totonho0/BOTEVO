"""Jogo: escolhe o VERSO (Naruto / Dragon Ball / Jujutsu) — 10 rodadas, cada uma um personagem desse mundo."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import random
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

ROUNDS = 10
ROUND_SECONDS = 50
POINT_MSG_SECONDS = 2.0


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower().strip())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _matches_guess(user_text: str, accepted: List[str]) -> bool:
    u = _norm(user_text)
    if len(u) < 2:
        return False
    for raw in accepted:
        a = _norm(raw)
        if not a:
            continue
        first_name = a.split()[0] if " " in a else a
        if u == a:
            return True
        if len(first_name) >= 3 and u == first_name:
            return True
        if len(a) >= 3 and a in u:
            return True
        if len(u) >= 3 and u in a and len(u) == len(a):
            return True
        for token in re.split(r"\s+|[^\w]+", u):
            if len(token) >= 3 and token == a:
                return True
            if len(first_name) >= 3 and token == first_name:
                return True
    return False


# id do personagem -> nome exibido, respostas aceites, dicas (emojis)
CHARACTERS: Dict[str, Dict[str, Any]] = {
    "naruto": {
        "label": "Naruto Uzumaki",
        "answers": ["naruto", "naruto uzumaki"],
        "hints": [
            "🦊🍜⚡", "🍥🍃🧡", "🦊👊🍥", "⚡🍜👤", "🌙🦊⚔️",
            "🍥🔥👊", "🐸🍥⚡", "🧡👊🍜", "🦊🗡️💨", "🏔️🍃🦊", "🍜🦊⭐", "👤🍥🔶",
        ],
    },
    "sasuke": {
        "label": "Sasuke Uchiha",
        "answers": ["sasuke", "sasuke uchiha", "uchiha sasuke"],
        "hints": [
            "🔥👁️⚡", "🐍🗡️🖤", "🔴⚫🔥", "🦅⚡🖤", "🌑🔥👁️",
            "🗡️💢⚡", "🖤🔥🐍", "👁️⚫🔥", "🦅🔵⚡", "⚡🐍🖤", "🔥🗡️👁️", "💜⚡👁️",
        ],
    },
    "sakura": {
        "label": "Sakura Haruno",
        "answers": ["sakura", "sakura haruno", "haruno sakura"],
        "hints": [
            "🌸👊💗", "💪🌸💢", "🏥🌸👊", "💗👊🌳", "🌸💢👊",
            "👊🌸✨", "🌸📚💪", "💗🌸⚕️", "🌸🔨💥", "🌸👊🍃", "💢🌸👊", "🌸💚👊",
        ],
    },
    "kakashi": {
        "label": "Kakashi Hatake",
        "answers": ["kakashi", "kakashi hatake", "hatake kakashi"],
        "hints": [
            "📖⚡🐶", "🍜📖⚡", "🐶🗡️⚫", "📓⚡🐕", "🐶📖👁️",
            "⚡📖🐶", "🗡️🐶⚡", "📖🐶🍥", "🐶⚫📓", "⚡🐶🗡️", "📖👁️🐶", "🍜🐶⚡",
        ],
    },
    "rock_lee": {
        "label": "Rock Lee",
        "answers": ["rock lee", "lee", "rocklee"],
        "hints": [
            "🥋💚👊", "🍶💪🔥", "🟢👊💨", "💚🔥🥋", "👊💚⚡",
            "🥋👊💢", "💚🍶👊", "🔥🥋💚", "👊🟢🥋", "💨💚👊", "🥋⚡💚", "💪🥋🟢",
        ],
    },
    "gaara": {
        "label": "Gaara",
        "answers": ["gaara"],
        "hints": [
            "🏜️🐚👦", "🐚💢🏜️", "🏜️👦🐚", "👦🏜️💢", "🐚👦🏜️",
            "💢🐚👦", "🏜️💢🐚", "👦🐚💢", "🐚🏜️👦", "💢🏜️👦", "👦💢🐚", "🏜️👦💢",
        ],
    },
    "shikamaru": {
        "label": "Shikamaru Nara",
        "answers": ["shikamaru", "shikamaru nara"],
        "hints": [
            "☁️🦌🧠", "🧠☁️🎮", "🦌🧠☁️", "☁️🧠🦌", "🎮☁️🧠",
            "🧠🦌🎮", "🦌☁️🎮", "🎮🧠🦌", "☁️🎮🦌", "🧠🎮☁️", "🦌🎮🧠", "🎮🦌☁️",
        ],
    },
    "hinata": {
        "label": "Hinata Hyuga",
        "answers": ["hinata", "hinata hyuga", "hyuga hinata"],
        "hints": [
            "👁️💜🌸", "🌸💜👁️", "💜🌸👁️", "👁️🌸💜", "🌸👁️💜",
            "💜👁️🌸", "👁️💜👊", "🌸👊💜", "💜👊👁️", "👊🌸👁️", "🌸💜👊", "👁️👊🌸",
        ],
    },
    "itachi": {
        "label": "Itachi Uchiha",
        "answers": ["itachi", "itachi uchiha", "uchiha itachi"],
        "hints": [
            "🐦‍⬛🔴👁️", "🔴👁️🐦", "👁️🔴🐦", "🐦👁️🔴", "🔴🐦👁️",
            "👁️🐦🔴", "🐦🔴👁️", "🔴🐦‍⬛", "👁️🐦‍⬛🔴", "🐦‍⬛👁️", "🔴👁️⚫", "⚫🐦🔴",
        ],
    },
    "neji": {
        "label": "Neji Hyuga",
        "answers": ["neji", "neji hyuga", "hyuga neji"],
        "hints": [
            "🌀👁️🥋", "👁️🌀🥋", "🥋🌀👁️", "🌀🥋👁️", "👁️🥋🌀",
            "🥋👁️🌀", "🌀👁️⚪", "⚪🌀👁️", "👁️⚪🥋", "🥋⚪🌀", "🌀🥋⚪", "⚪👁️🌀",
        ],
    },
    "goku": {
        "label": "Goku",
        "answers": ["goku", "son goku", "songoku"],
        "hints": [
            "🐉⚡🟠", "☄️💥👊", "🟠🐵⭐", "🍚👊💢", "⚡🟠🐉",
            "👊💨🟠", "🟠⭐⚡", "🐉👊🟠", "💥⚡🟠", "🟠🍜👊", "🐵⚡🟠", "⭐👊🐉",
        ],
    },
    "vegeta": {
        "label": "Vegeta",
        "answers": ["vegeta", "principe vegeta"],
        "hints": [
            "💙👑💢", "👑🔵💥", "💢💙⚡", "👑💙👊", "🔵💢👑",
            "💙⚡💥", "👑💢🔵", "💥👑💙", "⚡💙👑", "💢⚡💙", "👊💙👑", "💙💥👑",
        ],
    },
    "gohan": {
        "label": "Gohan",
        "answers": ["gohan", "son gohan", "songohan"],
        "hints": [
            "📚🐉👦", "🟣⚡👦", "👦📖⚡", "🐉👦📚", "👦🟣👊",
            "📖🐉👦", "⚡👦🟣", "👦💥📚", "🐉📚👦", "👦⚡🐉", "🟣👦📖", "👦👊🐉",
        ],
    },
    "piccolo": {
        "label": "Piccolo",
        "answers": ["piccolo", "pikolo"],
        "hints": [
            "💚👽🥋", "💚🗡️🌙", "🟢👊☄️", "👽💚⚡", "🥋💚👊",
            "🌙💚🗡️", "💚☄️🟢", "👊💚👽", "🟢🌙💚", "💚👊⚡", "🥋🟢💚", "👽🟢🥋",
        ],
    },
    "freeza": {
        "label": "Freeza",
        "answers": ["freeza", "frieza", "freezer"],
        "hints": [
            "❄️👑💜", "💜👑❄️", "👑💜⚡", "❄️💜👑", "💜❄️💢",
            "👑❄️💜", "💜💢👑", "❄️💢💜", "👑⚡💜", "💜👊❄️", "❄️💜⚡", "💢❄️👑",
        ],
    },
    "bulma": {
        "label": "Bulma",
        "answers": ["bulma", "buma"],
        "hints": [
            "💠🔵💇", "💇‍♀️🔧💙", "🔵💠📟", "💙🔧💇", "📟💙💠",
            "💇💙🔵", "🔧💠💙", "💙💇📟", "💠💙🔧", "🔵💇💠", "💇🔵💙", "📟🔵💇",
        ],
    },
    "krillin": {
        "label": "Kuririn",
        "answers": ["krillin", "kuririn", "kurilin"],
        "hints": [
            "💿👨‍🦲💥", "🟠👊💨", "👨‍🦲💢⚡", "💥👨‍🦲👊", "🟠💨👊",
            "👨‍🦲🟠💥", "💢👨‍🦲🟠", "👊💿🟠", "💨👨‍🦲💥", "🟠💥👨‍🦲", "👨‍🦲👊🟠", "💥🟠👊",
        ],
    },
    "trunks": {
        "label": "Trunks",
        "answers": ["trunks", "trunks briefs"],
        "hints": [
            "⚡🗡️💙", "🗡️💙⚡", "💙⚡🗡️", "⚡💙👦", "👦🗡️💙",
            "🗡️⚡👦", "💙👦⚡", "👦💙🗡️", "⚡👦🗡️", "🗡️👦⚡", "💙🗡️👦", "👦⚡💙",
        ],
    },
    "android_18": {
        "label": "Android 18",
        "answers": ["android 18", "androide 18", "c-18", "18"],
        "hints": [
            "🤖💛👩", "👩🤖💛", "💛👩🤖", "🤖👩💢", "💢🤖👩",
            "👩💛💢", "🤖💢💛", "💛🤖👩", "👩💢🤖", "💢👩💛", "🤖👩💛", "💛💢👩",
        ],
    },
    "cell": {
        "label": "Cell",
        "answers": ["cell", "celula"],
        "hints": [
            "🐛🟢👾", "👾🐛🟢", "🟢👾🐛", "🐛👾💚", "💚🐛👾",
            "👾💚🐛", "🟢💚👾", "🐛🟢💚", "💚👾🐛", "👾🟢🐛", "🟢👾💚", "💚🟢👾",
        ],
    },
    "gojo": {
        "label": "Satoru Gojo",
        "answers": ["gojo", "satoru gojo", "gojo satoru"],
        "hints": [
            "⚫🔴🕶️", "🕶️⚪💫", "🤞🔴⚪", "👓⚫∞", "🔴⚫🕶️",
            "🕶️💫⚪", "⚪🔴🕶️", "∞⚫👓", "🔴🕶️⚫", "⚫💫🔴", "🕶️⚫⚪", "⚪🕶️🔴",
        ],
    },
    "yuji": {
        "label": "Yuji Itadori",
        "answers": ["yuji", "yuji itadori", "itadori", "itadori yuji"],
        "hints": [
            "💪🏫👊", "🤜🩸👊", "🏫🧱👊", "👊💪🩸", "🏫👊💢",
            "🩸💪👊", "👊🏫💪", "🧱👊🏫", "💢👊🏫", "👊🩸🏫", "💪👊🧱", "🏫💪🩸",
        ],
    },
    "megumi": {
        "label": "Megumi Fushiguro",
        "answers": ["megumi", "megumi fushiguro", "fushiguro", "fushiguro megumi"],
        "hints": [
            "🐺🧿⚫", "🌑🐺⛩️", "⚫🐺🧿", "🐺⛩️🌑", "🧿⚫🐺",
            "⛩️🐺🌑", "🌑⚫🐺", "🐺🌑🧿", "⚫⛩️🐺", "🧿🐺⛩️", "🐺⚫🌑", "⛩️🧿🐺",
        ],
    },
    "nobara": {
        "label": "Nobara Kugisaki",
        "answers": ["nobara", "nobara kugisaki", "kugisaki", "kugisaki nobara"],
        "hints": [
            "🔨🌾💅", "💅🔨⭐", "🌾💅🔨", "⭐🔨🌾", "🔨💅⭐",
            "💅🌾⭐", "🌾⭐🔨", "⭐💅🌾", "🔨⭐💅", "💅⭐🔨", "🌾🔨💅", "⭐🌾🔨",
        ],
    },
    "sukuna": {
        "label": "Sukuna",
        "answers": ["sukuna", "ryomen sukuna", "ryomen"],
        "hints": [
            "👹🖐️🔴", "😈🔴👅", "🔴👹🖐️", "👅😈🔴", "🖐️🔴👹",
            "🔴😈👹", "👹🔴😈", "😈👹👅", "🔴👅🖐️", "👹😈🔴", "🖐️👹🔴", "👅🔴👹",
        ],
    },
    "nanami": {
        "label": "Kento Nanami",
        "answers": ["nanami", "kento nanami", "nanami kento"],
        "hints": [
            "👔⏰📐", "🧳💼⚔️", "⏰👔💼", "📐🧳👔", "💼⏰⚔️",
            "⚔️👔🧳", "👔🧳📐", "💼📐⏰", "🧳⚔️👔", "⏰💼🧳", "📐⚔️💼", "👔💼⏰",
        ],
    },
    "maki": {
        "label": "Maki Zenin",
        "answers": ["maki", "maki zenin", "zenin maki"],
        "hints": [
            "🗡️👓💢", "🏹💜👓", "👓🗡️💢", "💢🏹👓", "💜🗡️👓",
            "🗡️💜🏹", "👓💢🗡️", "🏹👓💜", "💢👓🏹", "👓🏹🗡️", "💜👓💢", "🗡️👓🏹",
        ],
    },
    "geto": {
        "label": "Suguru Geto",
        "answers": ["geto", "suguru geto", "geto suguru"],
        "hints": [
            "🤲☸️💀", "🐒👤💀", "☸️💀🤲", "👤🐒☸️", "💀🤲👤",
            "🤲💀🐒", "☸️👤💀", "🐒💀☸️", "👤🤲🐒", "💀☸️🤲", "🐒☸️👤", "👤💀🐒",
        ],
    },
    "todo": {
        "label": "Aoi Todo",
        "answers": ["todo", "aoi todo", "todo aoi"],
        "hints": [
            "👊🖐️✋", "💪🏫🤝", "🖐️👊💢", "✋💪🖐️", "🤝👊🏫",
            "👊💪✋", "🏫🖐️👊", "💢✋💪", "🖐️🤝👊", "✋🏫💪", "👊✋🖐️", "💪🖐️🤝",
        ],
    },
    "panda": {
        "label": "Panda",
        "answers": ["panda"],
        "hints": [
            "🐼👊🏫", "🐼💢⚫", "🏫🐼👊", "👊🐼💪", "🐼⚫👊",
            "💪🐼🏫", "⚫🐼💢", "👊⚫🐼", "🐼💪⚫", "🏫⚫🐼", "💢🐼🏫", "🐼🏫💪",
        ],
    },
}

# Escolha no menu = verso; cada rodada sorteia um personagem deste elenco.
VERSES: Dict[str, Dict[str, Any]] = {
    "verso_naruto": {
        "label": "Naruto",
        "menu_desc": "10 rodadas com personagens do mundo Naruto.",
        "roster": [
            "naruto", "sasuke", "sakura", "kakashi", "rock_lee",
            "gaara", "shikamaru", "hinata", "itachi", "neji",
        ],
    },
    "verso_dragon_ball": {
        "label": "Dragon Ball",
        "menu_desc": "10 rodadas com personagens de Dragon Ball.",
        "roster": [
            "goku", "vegeta", "gohan", "piccolo", "freeza",
            "bulma", "krillin", "trunks", "android_18", "cell",
        ],
    },
    "verso_jujutsu": {
        "label": "Jujutsu Kaisen",
        "menu_desc": "Gojo, Panda, Sukuna, Yuji, Megumi e mais — 10 rodadas.",
        "roster": [
            "gojo", "panda", "sukuna", "yuji", "megumi",
            "nobara", "nanami", "maki", "geto", "todo",
        ],
    },
}


def _roster_for_rounds(roster_ids: List[str]) -> List[str]:
    pool = [k for k in roster_ids if k in CHARACTERS]
    if not pool:
        return []
    if len(pool) >= ROUNDS:
        return random.sample(pool, ROUNDS)
    out: List[str] = []
    while len(out) < ROUNDS:
        batch = list(pool)
        random.shuffle(batch)
        for k in batch:
            out.append(k)
            if len(out) >= ROUNDS:
                return out
    return out[:ROUNDS]


def _verse_select_options() -> List[discord.SelectOption]:
    opts: List[discord.SelectOption] = []
    for key, data in VERSES.items():
        opts.append(
            discord.SelectOption(
                label=str(data["label"])[:100],
                description=str(data.get("menu_desc", ""))[:100],
                value=key,
                emoji="📺",
            )
        )
    return opts


class AnimeEmojiVerseView(discord.ui.View):
    def __init__(self, cog: "AnimeEmojiGame", host_id: int, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.host_id = host_id
        sel = discord.ui.Select(
            placeholder="Escolha o verso (universo) do quiz...",
            min_values=1,
            max_values=1,
            options=_verse_select_options(),
        )
        sel.callback = self._on_pick
        self.add_item(sel)

    async def _on_pick(self, interaction: discord.Interaction):
        if interaction.user.id != self.host_id:
            return await interaction.response.send_message(
                "So quem iniciou o comando pode escolher o verso.", ephemeral=True
            )
        raw = interaction.data.get("values") or []
        if not raw:
            return await interaction.response.send_message("Nenhuma opcao selecionada.", ephemeral=True)
        verse_key = raw[0]
        if verse_key not in VERSES:
            return await interaction.response.send_message("Verso invalido.", ephemeral=True)
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("Use em um canal de texto.", ephemeral=True)
        if not self.cog.register_game_channel(channel.id):
            return await interaction.response.send_message(
                "Ja existe uma partida em andamento neste canal. Espere terminar ou use outro canal.",
                ephemeral=True,
            )
        menu_message = interaction.message
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()
        asyncio.create_task(
            self.cog.run_match(
                channel=channel,
                verse_key=verse_key,
                host=interaction.user,
                menu_message=menu_message,
            )
        )

    async def on_timeout(self):
        try:
            if self.message:
                for item in self.children:
                    item.disabled = True
                await self.message.edit(view=self)
        except Exception:
            pass


class AnimeEmojiGame(commands.Cog):
    """Quiz: personagem pelos emojis, por verso."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._busy_channels: set[int] = set()

    def register_game_channel(self, channel_id: int) -> bool:
        if channel_id in self._busy_channels:
            return False
        self._busy_channels.add(channel_id)
        return True

    def release_game_channel(self, channel_id: int):
        self._busy_channels.discard(channel_id)

    def _pick_rounds(self, verse_key: str) -> Tuple[List[Dict[str, Any]], str]:
        meta = VERSES[verse_key]
        verse_label = meta["label"]
        order = _roster_for_rounds(list(meta["roster"]))
        rounds: List[Dict[str, Any]] = []
        for ck in order:
            ch = CHARACTERS[ck]
            emojis = random.choice(ch["hints"])
            rounds.append({"emojis": emojis, "answers": list(ch["answers"]), "char_label": ch["label"]})
        return rounds, verse_label

    async def run_match(
        self,
        channel: discord.TextChannel,
        verse_key: str,
        host: discord.abc.User,
        menu_message: Optional[discord.Message],
    ):
        scores: Dict[int, int] = {}
        match_start = datetime.now(timezone.utc)
        bot_message_ids: set[int] = set()
        try:
            rounds_data, verse_label = self._pick_rounds(verse_key)
            if menu_message:
                bot_message_ids.add(menu_message.id)

            for idx, item in enumerate(rounds_data, start=1):
                emojis = item["emojis"]
                answers: List[str] = item["answers"]
                embed = discord.Embed(
                    title=f"Rodada {idx}/{ROUNDS} — {verse_label}",
                    description=f"{emojis}\n\n**Digite o nome do personagem** deste verso no canal. "
                    f"O primeiro acerto ganha **1 ponto**!\n⏱️ {ROUND_SECONDS}s",
                    color=0xE91E63,
                )
                host_name = getattr(host, "display_name", None) or host.name
                embed.set_footer(text=f"Iniciado por {host_name}")

                round_msg = await channel.send(embed=embed)
                bot_message_ids.add(round_msg.id)

                winner_id = await self._wait_round(channel, answers)
                if winner_id is not None:
                    scores[winner_id] = scores.get(winner_id, 0) + 1
                    try:
                        w = channel.guild.get_member(winner_id) if channel.guild else None
                        mention = w.mention if w else f"<@{winner_id}>"
                    except Exception:
                        mention = f"<@{winner_id}>"
                    pmsg = await channel.send(
                        f"Acerto: {mention} **+1 ponto!**",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                    bot_message_ids.add(pmsg.id)
                    await asyncio.sleep(POINT_MSG_SECONDS)
                    try:
                        await pmsg.delete()
                    except discord.HTTPException:
                        pass
                else:
                    reveal = item.get("char_label") or answers[0]
                    reveal_msg = await channel.send(
                        f"⏰ Tempo esgotado na rodada {idx}. Era: **{reveal}**",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    bot_message_ids.add(reveal_msg.id)

            scoreboard_msg = await self._send_scoreboard(channel, scores, verse_label, host)
            await self._cleanup_match_messages(
                channel=channel,
                match_start=match_start,
                keep_message_ids={scoreboard_msg.id},
                fallback_bot_ids=bot_message_ids,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("anime emoji game: %s", e)
            try:
                await channel.send("Ocorreu um erro e a partida foi encerrada.")
            except Exception:
                pass
        finally:
            self.release_game_channel(channel.id)

    async def _wait_round(self, channel: discord.TextChannel, answers: List[str]) -> Optional[int]:
        deadline = time.monotonic() + ROUND_SECONDS

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                msg = await self.bot.wait_for(
                    "message",
                    timeout=min(remaining, 30.0),
                    check=lambda m: m.channel.id == channel.id and not m.author.bot,
                )
            except asyncio.TimeoutError:
                continue
            if _matches_guess(msg.content, answers):
                return msg.author.id

    async def _send_scoreboard(
        self,
        channel: discord.TextChannel,
        scores: Dict[int, int],
        verse_label: str,
        host: discord.abc.User,
    ) -> discord.Message:
        embed = discord.Embed(
            title="Fim de jogo — Placar",
            description=f"Verso: **{verse_label}**\n{ROUNDS} rodadas (personagens diferentes deste mundo).",
            color=0x9C27B0,
        )
        if not scores:
            embed.add_field(name="Pontos", value="Ninguem pontuou nesta partida.", inline=False)
        else:
            ranking = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
            lines = []
            for place, (uid, pts) in enumerate(ranking, start=1):
                mem = channel.guild.get_member(uid) if channel.guild else None
                name = mem.display_name if mem else f"Usuario {uid}"
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(place, f"{place}.")
                lines.append(f"{medal} **{name}** — {pts} ponto(s)")
            embed.add_field(name="Classificacao", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"Host: {getattr(host, 'display_name', None) or host.name}")
        return await channel.send(embed=embed)

    async def _cleanup_match_messages(
        self,
        channel: discord.TextChannel,
        match_start: datetime,
        keep_message_ids: set[int],
        fallback_bot_ids: set[int],
    ):
        # Limpa em lote para evitar muitos DELETEs sequenciais (429).
        try:
            await channel.purge(
                limit=None,
                after=match_start,
                check=lambda m: m.id not in keep_message_ids,
                bulk=True,
            )
            return
        except (discord.Forbidden, discord.HTTPException):
            pass

        # Sem permissao para limpar historico inteiro: remove ao menos as mensagens do bot.
        for msg_id in fallback_bot_ids:
            if msg_id in keep_message_ids:
                continue
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    @app_commands.command(
        name="adivinhe_anime",
        description="Jogo: escolhe o verso e adivinha o personagem pelos emojis (10 rodadas).",
    )
    async def adivinhe_anime(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Use este comando em um servidor (canal de texto).", ephemeral=True)
        if interaction.channel.id in self._busy_channels:
            return await interaction.response.send_message(
                "Ja ha uma partida neste canal.", ephemeral=True
            )
        lines = "\n".join(
            f"**{v['label']}** — {v.get('menu_desc', '')}" for v in VERSES.values()
        )
        embed = discord.Embed(
            title="Adivinhe o personagem pelos emojis",
            description=(
                "Escolhe o **verso** no menu: **Naruto**, **Dragon Ball** ou **Jujutsu Kaisen**.\n\n"
                f"Serao **{ROUNDS} rodadas**; em cada uma aparece um **personagem diferente** desse mundo "
                "(por exemplo Jujutsu: Gojo, Panda, Sukuna, Yuji, Megumi…).\n"
                "O **primeiro** a acertar o nome ganha **1 ponto**. A mensagem de ponto some apos "
                f"**{int(POINT_MSG_SECONDS)}s**.\n\n"
                f"**Versos:**\n{lines}\n\n"
                f"Tempo por rodada: **{ROUND_SECONDS}s**."
            ),
            color=0xFF9800,
        )
        view = AnimeEmojiVerseView(self, host_id=interaction.user.id, timeout=120)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(AnimeEmojiGame(bot))
