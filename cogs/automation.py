import json
import os
import xml.etree.ElementTree as ET

import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks

from json_utils import atomic_write_json

AUTO_CFG_FILE = "data/automation_config.json"


def load_auto_cfg():
    if os.path.exists(AUTO_CFG_FILE):
        try:
            with open(AUTO_CFG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_auto_cfg(cfg):
    atomic_write_json(AUTO_CFG_FILE, cfg)


def get_guild_auto_cfg(guild_id: int):
    all_cfg = load_auto_cfg()
    gid = str(guild_id)
    if gid not in all_cfg:
        all_cfg[gid] = {
            "welcome_channel_id": 0,
            "welcome_message": "Bem-vindo(a), {user}, ao servidor {guild}!",
            "leave_channel_id": 0,
            "leave_message": "{user_name} saiu do servidor.",
            "autorole_id": 0,
            "reaction_roles": [],
            "content_alerts": [],
        }
        save_auto_cfg(all_cfg)
    return all_cfg[gid]


class AutomationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not self.content_alerts_task.is_running():
            self.content_alerts_task.start()

    def _cfg_all(self):
        return load_auto_cfg()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = get_guild_auto_cfg(member.guild.id)
        if cfg.get("autorole_id"):
            role = member.guild.get_role(int(cfg["autorole_id"]))
            if role:
                try:
                    await member.add_roles(role, reason="AutoRole")
                except Exception:
                    pass
        if cfg.get("welcome_channel_id"):
            ch = member.guild.get_channel(int(cfg["welcome_channel_id"]))
            if ch:
                msg = str(cfg.get("welcome_message") or "").replace("{user}", member.mention).replace("{guild}", member.guild.name)
                try:
                    await ch.send(msg)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        cfg = get_guild_auto_cfg(member.guild.id)
        if cfg.get("leave_channel_id"):
            ch = member.guild.get_channel(int(cfg["leave_channel_id"]))
            if ch:
                msg = str(cfg.get("leave_message") or "").replace("{user_name}", member.display_name).replace("{guild}", member.guild.name)
                try:
                    await ch.send(msg)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        cfg = get_guild_auto_cfg(payload.guild_id)
        for rr in cfg.get("reaction_roles", []):
            if int(rr.get("message_id", 0)) == payload.message_id and str(rr.get("emoji", "")) == str(payload.emoji):
                guild = self.bot.get_guild(payload.guild_id)
                if not guild:
                    return
                member = guild.get_member(payload.user_id)
                role = guild.get_role(int(rr.get("role_id", 0)))
                if member and role:
                    try:
                        await member.add_roles(role, reason="Reaction role")
                    except Exception:
                        pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        cfg = get_guild_auto_cfg(payload.guild_id)
        for rr in cfg.get("reaction_roles", []):
            if int(rr.get("message_id", 0)) == payload.message_id and str(rr.get("emoji", "")) == str(payload.emoji):
                guild = self.bot.get_guild(payload.guild_id)
                if not guild:
                    return
                member = guild.get_member(payload.user_id)
                role = guild.get_role(int(rr.get("role_id", 0)))
                if member and role:
                    try:
                        await member.remove_roles(role, reason="Reaction role remove")
                    except Exception:
                        pass

    @tasks.loop(minutes=3)
    async def content_alerts_task(self):
        all_cfg = self._cfg_all()
        changed = False
        for gid, cfg in all_cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            alerts = cfg.get("content_alerts", [])
            for alert in alerts:
                if not alert.get("enabled", True):
                    continue
                feed_url = alert.get("feed_url")
                channel_id = int(alert.get("channel_id") or 0)
                if not feed_url or not channel_id:
                    continue
                ch = guild.get_channel(channel_id)
                if not ch:
                    continue
                try:
                    resp = requests.get(feed_url, timeout=10)
                    resp.raise_for_status()
                    root = ET.fromstring(resp.text)
                    # RSS fallback
                    item = root.find(".//item")
                    if item is None:
                        # Atom fallback
                        item = root.find(".//{http://www.w3.org/2005/Atom}entry")
                    if item is None:
                        continue
                    title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "Novo conteudo").strip()
                    link = item.findtext("link") or ""
                    if not link:
                        atom_link = item.find("{http://www.w3.org/2005/Atom}link")
                        if atom_link is not None:
                            link = atom_link.attrib.get("href", "")
                    unique = f"{title}|{link}"
                    if unique and unique != alert.get("last_item"):
                        alert["last_item"] = unique
                        changed = True
                        try:
                            await ch.send(f"**{alert.get('name', 'Alerta')}**: novo conteudo publicado!\n{title}\n{link}")
                        except Exception:
                            pass
                except Exception:
                    continue
        if changed:
            save_auto_cfg(all_cfg)

    @content_alerts_task.before_loop
    async def _before_alerts(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="autoconfig", description="Configura automacoes de comunidade")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        acao="view, welcome, leave, autorole, rr_add, rr_rm, alert_add, alert_toggle",
        valor1="ID canal/mensagem/feed URL/nome",
        valor2="Mensagem/emoji/ID role",
        valor3="ID role/canal"
    )
    async def autoconfig(
        self,
        interaction: discord.Interaction,
        acao: str = "view",
        valor1: str = None,
        valor2: str = None,
        valor3: str = None,
    ):
        all_cfg = self._cfg_all()
        gid = str(interaction.guild.id)
        cfg = all_cfg.get(gid) or get_guild_auto_cfg(interaction.guild.id)
        act = (acao or "view").lower().strip()

        if act == "view":
            rr_txt = "\n".join(
                f"msg `{x.get('message_id')}` emoji `{x.get('emoji')}` => <@&{x.get('role_id')}>"
                for x in cfg.get("reaction_roles", [])[:10]
            ) or "Nenhum."
            alerts_txt = "\n".join(
                f"{i+1}. {x.get('name','Alert')} ({'on' if x.get('enabled', True) else 'off'})"
                for i, x in enumerate(cfg.get("content_alerts", [])[:10])
            ) or "Nenhum."
            e = discord.Embed(title="Automacoes", color=0x22c55e)
            e.add_field(name="Welcome", value=f"canal: {cfg.get('welcome_channel_id', 0)}", inline=True)
            e.add_field(name="Leave", value=f"canal: {cfg.get('leave_channel_id', 0)}", inline=True)
            e.add_field(name="AutoRole", value=f"role: {cfg.get('autorole_id', 0)}", inline=True)
            e.add_field(name="Reaction Roles", value=rr_txt, inline=False)
            e.add_field(name="Content Alerts", value=alerts_txt, inline=False)
            return await interaction.response.send_message(embed=e, ephemeral=True)

        if act == "welcome":
            cfg["welcome_channel_id"] = int(valor1 or 0)
            if valor2:
                cfg["welcome_message"] = valor2
        elif act == "leave":
            cfg["leave_channel_id"] = int(valor1 or 0)
            if valor2:
                cfg["leave_message"] = valor2
        elif act == "autorole":
            cfg["autorole_id"] = int(valor1 or 0)
        elif act == "rr_add":
            try:
                msg_id = int(valor1)
                emoji = str(valor2)
                role_id = int(valor3)
            except (TypeError, ValueError):
                return await interaction.response.send_message("Use: valor1=msg_id valor2=emoji valor3=role_id", ephemeral=True)
            cfg.setdefault("reaction_roles", []).append({"message_id": msg_id, "emoji": emoji, "role_id": role_id})
        elif act == "rr_rm":
            try:
                msg_id = int(valor1)
                emoji = str(valor2)
            except (TypeError, ValueError):
                return await interaction.response.send_message("Use: valor1=msg_id valor2=emoji", ephemeral=True)
            cfg["reaction_roles"] = [
                x for x in cfg.get("reaction_roles", [])
                if not (int(x.get("message_id", 0)) == msg_id and str(x.get("emoji", "")) == emoji)
            ]
        elif act == "alert_add":
            # valor1=name valor2=feed_url valor3=channel_id
            try:
                channel_id = int(valor3)
            except (TypeError, ValueError):
                return await interaction.response.send_message("Use valor3=channel_id valido.", ephemeral=True)
            cfg.setdefault("content_alerts", []).append(
                {"name": valor1 or "Feed", "feed_url": valor2 or "", "channel_id": channel_id, "enabled": True, "last_item": ""}
            )
        elif act == "alert_toggle":
            try:
                idx = int(valor1) - 1
            except (TypeError, ValueError):
                return await interaction.response.send_message("Use valor1 como indice (1,2,3...)", ephemeral=True)
            alerts = cfg.get("content_alerts", [])
            if idx < 0 or idx >= len(alerts):
                return await interaction.response.send_message("Indice invalido.", ephemeral=True)
            alerts[idx]["enabled"] = not bool(alerts[idx].get("enabled", True))
        else:
            return await interaction.response.send_message(
                "Acoes: view, welcome, leave, autorole, rr_add, rr_rm, alert_add, alert_toggle",
                ephemeral=True
            )

        all_cfg[gid] = cfg
        save_auto_cfg(all_cfg)
        await interaction.response.send_message("Automacao atualizada.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AutomationCog(bot))
