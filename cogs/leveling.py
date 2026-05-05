import math
import random
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import (
    add_coins,
    add_xp,
    get_level_config,
    get_level_reward,
    get_level_rewards,
    get_level_stats,
    set_level_reward,
    top_levels,
    update_level_config,
)
from images import img_stats_table, get_member_name
from utils import now_brazil


def xp_for_level(level: int) -> int:
    # Progressive but not absurd curve.
    return int(120 * (level ** 2) + 200 * level + 100)


def level_from_xp(xp: int) -> int:
    lvl = 0
    while xp >= xp_for_level(lvl + 1):
        lvl += 1
    return lvl


class LevelingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._message_cooldowns = {}
        self._voice_xp_checkpoint = {}
        if not self.voice_xp_task.is_running():
            self.voice_xp_task.start()

    def _cfg_dict(self, guild_id: int):
        row = get_level_config(guild_id)
        # guild_id, enabled, msg_min, msg_max, cooldown, voice_xp_per_min, announce
        return {
            "enabled": bool(row[1]),
            "message_xp_min": int(row[2]),
            "message_xp_max": int(row[3]),
            "message_cooldown_sec": int(row[4]),
            "voice_xp_per_min": float(row[5]),
            "announce_levelup": bool(row[6]),
        }

    async def _apply_level_rewards(self, guild: discord.Guild, member: discord.Member, level: int):
        reward = get_level_reward(guild.id, level)
        if not reward:
            return
        _lvl, role_id, coins_reward = reward
        if role_id:
            role = guild.get_role(int(role_id))
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Recompensa de nivel {level}")
                except Exception:
                    pass
        if coins_reward and int(coins_reward) > 0:
            add_coins(guild.id, member.id, int(coins_reward))

    async def _try_gain_message_xp(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        cfg = self._cfg_dict(message.guild.id)
        if not cfg["enabled"]:
            return
        key = (message.guild.id, message.author.id)
        now = now_brazil()
        last = self._message_cooldowns.get(key)
        if last and (now - last).total_seconds() < cfg["message_cooldown_sec"]:
            return
        self._message_cooldowns[key] = now

        gained = random.randint(cfg["message_xp_min"], cfg["message_xp_max"])
        stats = get_level_stats(message.guild.id, message.author.id)
        current_xp, current_level = int(stats[2]), int(stats[3])
        new_xp = current_xp + gained
        new_level = level_from_xp(new_xp)
        add_xp(message.guild.id, message.author.id, gained, new_level)
        if new_level > current_level:
            member = message.author
            await self._apply_level_rewards(message.guild, member, new_level)
            if cfg["announce_levelup"]:
                await message.channel.send(
                    f"{member.mention} subiu para o **nivel {new_level}**!",
                    delete_after=12
                )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._try_gain_message_xp(message)

    @tasks.loop(seconds=60)
    async def voice_xp_task(self):
        for gid, uid, started_at in self.bot.iter_active_sessions():
            guild = self.bot.get_guild(gid)
            if not guild:
                continue
            member = guild.get_member(uid)
            if not member or not member.voice or not member.voice.channel:
                continue
            if not self.bot.voice_channel_counts_for_ranking(member.voice.channel):
                continue
            cfg = self._cfg_dict(gid)
            if not cfg["enabled"]:
                continue
            key = (gid, uid)
            now = now_brazil()
            last_tick = self._voice_xp_checkpoint.get(key, started_at)
            elapsed_min = max(0.0, (now - last_tick).total_seconds() / 60.0)
            if elapsed_min < 0.9:
                continue
            gained = max(1, int(elapsed_min * cfg["voice_xp_per_min"]))
            stats = get_level_stats(gid, uid)
            current_xp, current_level = int(stats[2]), int(stats[3])
            new_xp = current_xp + gained
            new_level = level_from_xp(new_xp)
            add_xp(gid, uid, gained, new_level)
            self._voice_xp_checkpoint[key] = now
            if new_level > current_level:
                await self._apply_level_rewards(guild, member, new_level)
                if cfg["announce_levelup"]:
                    try:
                        await member.send(f"Voce subiu para o nivel **{new_level}** em **{guild.name}**!")
                    except Exception:
                        pass

    @voice_xp_task.before_loop
    async def _before_voice_xp(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="rank", description="Mostra seu rank de nivel")
    @app_commands.describe(membro="Membro para consultar")
    async def rank(self, interaction: discord.Interaction, membro: discord.Member = None):
        target = membro or interaction.user
        stats = get_level_stats(interaction.guild.id, target.id)
        xp = int(stats[2])
        level = int(stats[3])
        next_xp = xp_for_level(level + 1)
        current_level_xp = xp_for_level(level)
        progress = max(0, xp - current_level_xp)
        need = max(1, next_xp - current_level_xp)
        pct = min(100, int((progress / need) * 100))
        lines = [
            ("Nivel", str(level)),
            ("XP total", str(xp)),
            ("Progresso", f"{progress}/{need} ({pct}%)"),
        ]
        img = img_stats_table(lines, f"RANK DE {target.display_name}", f"Servidor: {interaction.guild.name}", color=(56, 189, 248))
        await interaction.response.send_message(file=discord.File(fp=img, filename="rank.png"))

    @app_commands.command(name="levels", description="Top niveis do servidor")
    async def levels(self, interaction: discord.Interaction):
        data = top_levels(interaction.guild.id, 10)
        if not data:
            return await interaction.response.send_message("Ainda nao ha dados de niveis.")
        lines = []
        for idx, (uid, xp, level) in enumerate(data, 1):
            nm = get_member_name(self.bot, uid, interaction.guild)
            lines.append((f"{idx}. {nm}", f"Lv {level} • {xp} XP"))
        img = img_stats_table(lines, "TOP NIVEIS", interaction.guild.name, color=(34, 197, 94))
        await interaction.response.send_message(file=discord.File(fp=img, filename="levels.png"))

    @app_commands.command(name="level_config", description="Configura o sistema de niveis")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        acao="view, toggle, msgxp, cooldown, voicexp, reward",
        valor1="Valor principal (ex: on/off, min, segundos, nivel)",
        valor2="Valor secundario (ex: max xp, coins recompensa)",
        role="Cargo para recompensa do nivel"
    )
    async def level_config(
        self,
        interaction: discord.Interaction,
        acao: str = "view",
        valor1: str = None,
        valor2: str = None,
        role: discord.Role = None
    ):
        guild_id = interaction.guild.id
        action = (acao or "view").strip().lower()
        cfg = self._cfg_dict(guild_id)
        if action == "view":
            rewards = get_level_rewards(guild_id)
            rewards_txt = "\n".join(
                f"Lv {lvl}: role={f'<@&{rid}>' if rid else '-'} coins={coins}"
                for lvl, rid, coins in rewards[:10]
            ) or "Nenhuma recompensa definida."
            e = discord.Embed(title="Configuracao de Leveling", color=0x38bdf8)
            e.add_field(name="Ativo", value="Sim" if cfg["enabled"] else "Nao", inline=True)
            e.add_field(name="XP msg", value=f"{cfg['message_xp_min']} - {cfg['message_xp_max']}", inline=True)
            e.add_field(name="Cooldown msg", value=f"{cfg['message_cooldown_sec']}s", inline=True)
            e.add_field(name="XP voz/min", value=f"{cfg['voice_xp_per_min']}", inline=True)
            e.add_field(name="Anunciar level up", value="Sim" if cfg["announce_levelup"] else "Nao", inline=True)
            e.add_field(name="Recompensas", value=rewards_txt, inline=False)
            return await interaction.response.send_message(embed=e, ephemeral=True)

        if action == "toggle":
            enabled = str(valor1 or "").lower() in {"on", "1", "true", "sim", "yes"}
            update_level_config(guild_id, enabled=enabled)
            return await interaction.response.send_message(f"Leveling {'ativado' if enabled else 'desativado'}.", ephemeral=True)

        if action == "msgxp":
            try:
                mn = int(valor1)
                mx = int(valor2)
            except (TypeError, ValueError):
                return await interaction.response.send_message("Use valor1=min e valor2=max (inteiros).", ephemeral=True)
            if mn < 1 or mx < mn:
                return await interaction.response.send_message("Valores invalidos para XP de mensagem.", ephemeral=True)
            update_level_config(guild_id, message_xp_min=mn, message_xp_max=mx)
            return await interaction.response.send_message(f"XP por mensagem ajustado para {mn}-{mx}.", ephemeral=True)

        if action == "cooldown":
            try:
                sec = int(valor1)
            except (TypeError, ValueError):
                return await interaction.response.send_message("Informe segundos inteiros em valor1.", ephemeral=True)
            sec = max(5, min(sec, 600))
            update_level_config(guild_id, message_cooldown_sec=sec)
            return await interaction.response.send_message(f"Cooldown de mensagem ajustado para {sec}s.", ephemeral=True)

        if action == "voicexp":
            try:
                vpm = float(valor1)
            except (TypeError, ValueError):
                return await interaction.response.send_message("Informe XP por minuto em valor1.", ephemeral=True)
            vpm = max(0.1, min(vpm, 100))
            update_level_config(guild_id, voice_xp_per_min=vpm)
            return await interaction.response.send_message(f"XP de voz/min ajustado para {vpm}.", ephemeral=True)

        if action == "reward":
            try:
                lvl = int(valor1)
                coins = int(valor2 or 0)
            except (TypeError, ValueError):
                return await interaction.response.send_message("Use valor1=nivel e valor2=coins.", ephemeral=True)
            set_level_reward(guild_id, lvl, role_id=role.id if role else None, coins_reward=max(0, coins))
            return await interaction.response.send_message("Recompensa de nivel atualizada.", ephemeral=True)

        await interaction.response.send_message(
            "Acoes: view, toggle, msgxp, cooldown, voicexp, reward.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(LevelingCog(bot))
