import json
import os
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from database import add_mod_case, get_mod_cases, get_warn_count, remove_warn_case
from json_utils import atomic_write_json

MOD_CFG_FILE = "data/moderation_config.json"


def load_mod_cfg():
    if os.path.exists(MOD_CFG_FILE):
        try:
            with open(MOD_CFG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_mod_cfg(cfg):
    atomic_write_json(MOD_CFG_FILE, cfg)


def get_guild_mod_cfg(guild_id: int):
    cfg = load_mod_cfg()
    gid = str(guild_id)
    if gid not in cfg:
        cfg[gid] = {
            "modlog_channel_id": 0,
            "warn_escalation": {
                "3": "timeout:30",
                "5": "kick",
                "7": "ban",
            },
        }
        save_mod_cfg(cfg)
    return cfg[gid]


class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send_modlog(self, guild: discord.Guild, text: str):
        cfg = get_guild_mod_cfg(guild.id)
        cid = int(cfg.get("modlog_channel_id") or 0)
        if not cid:
            return
        ch = guild.get_channel(cid)
        if ch:
            try:
                await ch.send(text)
            except Exception:
                pass

    async def _record_case(self, guild, target_id, moderator_id, action, reason=None, expires_at=None):
        case_id = add_mod_case(guild.id, target_id, moderator_id, action, reason=reason, expires_at=expires_at)
        await self._send_modlog(
            guild,
            f"Case #{case_id} | `{action}` | alvo `{target_id}` | mod `{moderator_id}` | motivo: {reason or 'Sem motivo'}",
        )
        return case_id

    async def _apply_warn_escalation(self, interaction: discord.Interaction, member: discord.Member, warn_count: int):
        cfg = get_guild_mod_cfg(interaction.guild.id)
        rule = cfg.get("warn_escalation", {}).get(str(warn_count))
        if not rule:
            return
        try:
            if rule.startswith("timeout:"):
                mins = int(rule.split(":", 1)[1])
                await member.timeout_for(timedelta(minutes=max(1, mins)), reason=f"Escalonamento de warns ({warn_count})")
                await self._record_case(interaction.guild, member.id, interaction.user.id, "timeout_auto", f"Escalonamento warn {warn_count}")
            elif rule == "kick":
                await member.kick(reason=f"Escalonamento de warns ({warn_count})")
                await self._record_case(interaction.guild, member.id, interaction.user.id, "kick_auto", f"Escalonamento warn {warn_count}")
            elif rule == "ban":
                await member.ban(reason=f"Escalonamento de warns ({warn_count})", delete_message_days=0)
                await self._record_case(interaction.guild, member.id, interaction.user.id, "ban_auto", f"Escalonamento warn {warn_count}")
        except Exception as e:
            await interaction.followup.send(f"Falha ao aplicar escalonamento: {e}", ephemeral=True)

    @app_commands.command(name="warn", description="Aplicar advertencia a um membro")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, membro: discord.Member, motivo: str = "Sem motivo"):
        case_id = await self._record_case(interaction.guild, membro.id, interaction.user.id, "warn", motivo)
        wc = get_warn_count(interaction.guild.id, membro.id)
        await interaction.response.send_message(f"Warn aplicado em {membro.mention}. Case #{case_id}. Total warns: {wc}")
        await self._apply_warn_escalation(interaction, membro, wc)

    @app_commands.command(name="warnings", description="Listar advertencias de um membro")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, membro: discord.Member):
        rows = get_mod_cases(interaction.guild.id, target_id=membro.id, action="warn", limit=20)
        if not rows:
            return await interaction.response.send_message("Nenhum warn para esse membro.", ephemeral=True)
        lines = []
        for cid, _tid, mod_id, _action, reason, created, _exp in rows:
            lines.append(f"#{cid} por <@{mod_id}> em {created[:16]} — {reason or 'Sem motivo'}")
        e = discord.Embed(title=f"Warnings de {membro.display_name}", description="\n".join(lines[:15]), color=0xf59e0b)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="unwarn", description="Remover warn por case id")
    @app_commands.default_permissions(moderate_members=True)
    async def unwarn(self, interaction: discord.Interaction, case_id: int):
        ok = remove_warn_case(interaction.guild.id, case_id)
        if not ok:
            return await interaction.response.send_message("Case nao encontrado ou nao e warn.", ephemeral=True)
        await self._record_case(interaction.guild, interaction.user.id, interaction.user.id, "unwarn", f"removeu case {case_id}")
        await interaction.response.send_message(f"Warn #{case_id} removido.", ephemeral=True)

    @app_commands.command(name="mute", description="Aplicar timeout (mute temporario)")
    @app_commands.default_permissions(moderate_members=True)
    async def mute(self, interaction: discord.Interaction, membro: discord.Member, minutos: int = 10, motivo: str = "Sem motivo"):
        minutos = max(1, min(minutos, 43200))
        await membro.timeout_for(timedelta(minutes=minutos), reason=motivo)
        await self._record_case(interaction.guild, membro.id, interaction.user.id, "mute", motivo)
        await interaction.response.send_message(f"{membro.mention} mutado por {minutos} minutos.")

    @app_commands.command(name="unmute", description="Remover timeout de um membro")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, membro: discord.Member, motivo: str = "Sem motivo"):
        await membro.timeout_for(None, reason=motivo)
        await self._record_case(interaction.guild, membro.id, interaction.user.id, "unmute", motivo)
        await interaction.response.send_message(f"Timeout removido de {membro.mention}.")

    @app_commands.command(name="kickm", description="Expulsar membro")
    @app_commands.default_permissions(kick_members=True)
    async def kickm(self, interaction: discord.Interaction, membro: discord.Member, motivo: str = "Sem motivo"):
        await membro.kick(reason=motivo)
        await self._record_case(interaction.guild, membro.id, interaction.user.id, "kick", motivo)
        await interaction.response.send_message(f"{membro.mention} expulso.")

    @app_commands.command(name="banm", description="Banir membro")
    @app_commands.default_permissions(ban_members=True)
    async def banm(self, interaction: discord.Interaction, membro: discord.Member, motivo: str = "Sem motivo"):
        await membro.ban(reason=motivo, delete_message_days=0)
        await self._record_case(interaction.guild, membro.id, interaction.user.id, "ban", motivo)
        await interaction.response.send_message(f"{membro.mention} banido.")

    @app_commands.command(name="unbanm", description="Desbanir membro por ID")
    @app_commands.default_permissions(ban_members=True)
    async def unbanm(self, interaction: discord.Interaction, user_id: str, motivo: str = "Sem motivo"):
        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.response.send_message("ID invalido.", ephemeral=True)
        user = discord.Object(id=uid)
        await interaction.guild.unban(user, reason=motivo)
        await self._record_case(interaction.guild, uid, interaction.user.id, "unban", motivo)
        await interaction.response.send_message(f"Usuario `{uid}` desbanido.")

    @app_commands.command(name="modconfig", description="Configurar modulo de moderacao")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(acao="view, modlog, escalate", valor1="canal_id ou warns", valor2="acao: timeout:30|kick|ban")
    async def modconfig(self, interaction: discord.Interaction, acao: str = "view", valor1: str = None, valor2: str = None):
        cfg_all = load_mod_cfg()
        gid = str(interaction.guild.id)
        cfg = cfg_all.get(gid) or get_guild_mod_cfg(interaction.guild.id)
        act = acao.lower().strip()
        if act == "view":
            esc = cfg.get("warn_escalation", {})
            esc_txt = "\n".join(f"{k} warns => {v}" for k, v in sorted(esc.items(), key=lambda x: int(x[0]))) or "Nenhum."
            e = discord.Embed(title="Moderacao Config", color=0x60a5fa)
            e.add_field(name="Canal modlog", value=f"<#{cfg.get('modlog_channel_id', 0)}>" if cfg.get("modlog_channel_id") else "Nao definido", inline=False)
            e.add_field(name="Escalonamento de warns", value=esc_txt, inline=False)
            return await interaction.response.send_message(embed=e, ephemeral=True)
        if act == "modlog":
            try:
                cid = int(valor1)
            except (TypeError, ValueError):
                return await interaction.response.send_message("Informe o ID do canal em valor1.", ephemeral=True)
            cfg["modlog_channel_id"] = cid
        elif act == "escalate":
            try:
                warns = int(valor1)
            except (TypeError, ValueError):
                return await interaction.response.send_message("valor1 deve ser numero de warns.", ephemeral=True)
            rule = (valor2 or "").strip().lower()
            if not (rule.startswith("timeout:") or rule in {"kick", "ban"}):
                return await interaction.response.send_message("valor2 deve ser timeout:X, kick ou ban.", ephemeral=True)
            cfg.setdefault("warn_escalation", {})[str(warns)] = rule
        else:
            return await interaction.response.send_message("Acoes: view, modlog, escalate.", ephemeral=True)
        cfg_all[gid] = cfg
        save_mod_cfg(cfg_all)
        await interaction.response.send_message("Configuracao de moderacao atualizada.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
