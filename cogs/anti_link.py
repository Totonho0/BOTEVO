import discord
from discord import app_commands
from discord.ext import commands
import re
import json
import os
import datetime
from json_utils import atomic_write_json
from database import add_mod_case


class AntiLinkSetupModal(discord.ui.Modal, title="Configuracao Anti-Link"):
    def __init__(self, bot, guild_id: int, config: dict):
        super().__init__()
        self.bot = bot; self.guild_id = guild_id; self.config = config
        ch = ", ".join(str(c) for c in config.get("ignored_channels", []))
        self.ignored = discord.ui.TextInput(label="IDs de canais ignorados", default=ch, required=False, style=discord.TextStyle.paragraph)
        self.add_item(self.ignored)
        self.warning = discord.ui.TextInput(label="Mensagem de aviso", default=config.get("warning_message", "Links nao sao permitidos!"), required=False)
        self.add_item(self.warning)
        self.action = discord.ui.TextInput(label="Acao (warn, delete, kick, timeout)", default=config.get("action", "delete"), required=True)
        self.add_item(self.action)
        self.timeout = discord.ui.TextInput(label="Tempo de timeout (minutos)", default=str(config.get("timeout_minutes", 5)), required=False)
        self.add_item(self.timeout)
        self.log = discord.ui.TextInput(label="Canal de log (ID, vazio=off)", default=str(config.get("log_channel", "")), required=False)
        self.add_item(self.log)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            ignored = []
            if self.ignored.value:
                for c in self.ignored.value.split(","):
                    try:
                        ignored.append(int(c.strip()))
                    except ValueError:
                        pass
            act = self.action.value.lower().strip()
            if act not in ["warn", "delete", "kick", "timeout"]:
                return await interaction.response.send_message("Acao invalida! Use: warn, delete, kick, timeout.", ephemeral=True)
            tmin = 5
            if self.timeout.value:
                try:
                    tmin = max(1, min(int(self.timeout.value), 1440))
                except ValueError:
                    pass
            log_ch = None
            if self.log.value.strip():
                try:
                    log_ch = int(self.log.value.strip())
                except ValueError:
                    return await interaction.response.send_message("ID invalido.", ephemeral=True)
            self.config["ignored_channels"] = ignored
            self.config["warning_message"] = self.warning.value
            self.config["action"] = act
            self.config["timeout_minutes"] = tmin
            self.config["log_channel"] = log_ch
            self.bot.anti_link.update_config(self.guild_id)
            embed = discord.Embed(title="Anti-Link Configurado", description=f"Acao: {act.upper()}", color=discord.Color.green())
            if act == "timeout":
                embed.add_field(name="Timeout", value=f"{tmin} min", inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Erro: {e}", ephemeral=True)


class AntiLinkSettingsView(discord.ui.View):
    def __init__(self, bot, guild_id: int):
        super().__init__(timeout=180)
        self.bot = bot; self.guild_id = guild_id
        if str(guild_id) not in self.bot.anti_link.configs:
            self.bot.anti_link.load_config(guild_id)
        self.config = self.bot.anti_link.configs[str(guild_id)]
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("Apenas administradores podem usar este painel.", ephemeral=True)
        return False

    def _update_buttons(self):
        self.clear_items()
        s = discord.ui.Button(label="Desativar" if self.config["enabled"] else "Ativar",
                              style=discord.ButtonStyle.red if self.config["enabled"] else discord.ButtonStyle.green)
        s.callback = self.toggle; self.add_item(s)
        setup = discord.ui.Button(label="Configurar", style=discord.ButtonStyle.blurple)
        setup.callback = self.setup; self.add_item(setup)
        wl = discord.ui.Button(label="Whitelist", style=discord.ButtonStyle.blurple)
        wl.callback = self.whitelist; self.add_item(wl)

    async def toggle(self, interaction: discord.Interaction):
        if interaction.guild.id != self.guild_id:
            return await interaction.response.send_message("Este painel pertence a outro servidor.", ephemeral=True)
        self.config["enabled"] = not self.config["enabled"]
        self.bot.anti_link.update_config(self.guild_id)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def setup(self, interaction: discord.Interaction):
        if interaction.guild.id != self.guild_id:
            return await interaction.response.send_message("Este painel pertence a outro servidor.", ephemeral=True)
        await interaction.response.send_modal(AntiLinkSetupModal(self.bot, self.guild_id, self.config))

    async def whitelist(self, interaction: discord.Interaction):
        if interaction.guild.id != self.guild_id:
            return await interaction.response.send_message("Este painel pertence a outro servidor.", ephemeral=True)
        wl = self.config.get("whitelist", [])
        tx = "\n".join(f"\u2022 <@{u}>" for u in wl[:20]) if wl else "Vazia"
        embed = discord.Embed(title="Whitelist Anti-Link", value=tx, color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def create_embed(self):
        return discord.Embed(
            title="Configuracoes Anti-Link",
            description=f"Status: {'Ativado' if self.config['enabled'] else 'Desativado'}\nAcao: {self.config['action'].upper()}\nWhitelist: {len(self.config['whitelist'])}",
            color=discord.Color.blue() if self.config["enabled"] else discord.Color.red()
        )


class AntiLink(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.configs = {}
        self.config_file = "dados/antilink.json"
        os.makedirs("dados", exist_ok=True)
        self.load_configs()
        self.url_pattern = re.compile(
            r'(https?://[^\s]+|(?:www\.|(?!www))[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+)'
        )

    def load_configs(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.configs = json.load(f)
            else:
                self.configs = {}
                self.save_configs()
        except Exception as e:
            print(f"Erro anti-link load: {e}"); self.configs = {}

    def save_configs(self):
        try:
            atomic_write_json(self.config_file, self.configs)
        except Exception as e:
            print(f"Erro anti-link save: {e}")

    def load_config(self, guild_id):
        gid = str(guild_id)
        if gid not in self.configs:
            self.configs[gid] = {
                "enabled": False,
                "action": "delete",
                "warning_message": "Links nao sao permitidos!",
                "timeout_minutes": 5,
                "whitelist": [],
                "ignored_channels": [],
                "log_channel": None
            }
            self.save_configs()
        return self.configs[gid]

    def update_config(self, guild_id):
        self.save_configs()

    def check_for_links(self, content):
        match = self.url_pattern.search(content)
        if match:
            url = match.group(0)
            domain = re.sub(r'^(https?://)?(www\.)?', '', url).split('/')[0].split()[0]
            return True, domain
        return False, None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        gid = str(message.guild.id)
        if gid not in self.configs:
            self.load_config(message.guild.id)
        config = self.configs[gid]
        if not config["enabled"]:
            return
        if message.channel.id in config.get("ignored_channels", []):
            return
        if message.author.id in config.get("whitelist", []):
            return
        perms = message.channel.permissions_for(message.author)
        if perms.administrator or perms.manage_messages:
            return
        has_link, domain = self.check_for_links(message.content)
        if has_link:
            action = config.get("action", "delete")
            await self.log_violation(message, action, domain, config)
            if action in ("warn", "delete"):
                try:
                    await message.channel.send(f"{message.author.mention} {config.get('warning_message', '')}", delete_after=10)
                except Exception:
                    pass
                if action == "delete":
                    try:
                        await message.delete()
                    except Exception:
                        pass
            elif action == "kick":
                try:
                    await message.guild.kick(message.author, reason="Anti-Link: Envio de links")
                    await message.delete()
                except Exception:
                    try:
                        await message.delete()
                    except Exception:
                        pass
            elif action == "timeout":
                try:
                    mins = config.get("timeout_minutes", 5)
                    dur = datetime.timedelta(minutes=mins)
                    await message.author.timeout_for(dur, reason="Anti-Link")
                    await message.delete()
                except Exception:
                    pass

    async def log_violation(self, message, action, domain, config):
        lid = config.get("log_channel")
        if not lid:
            return
        try:
            ch = self.bot.get_channel(int(lid))
            if not ch:
                return
            content = message.content
            if len(content) > 500:
                content = content[:497] + "..."
            embed = discord.Embed(
                title="Anti-Link | Violacao",
                description=f"Usuario: {message.author.mention} ({message.author.id})\nCanal: {message.channel.mention}\nAcao: {action.upper()}\nDominio: `{domain}`\n\n```{content}```",
                color=discord.Color.orange(), timestamp=datetime.datetime.now()
            )
            await ch.send(embed=embed)
        except Exception:
            pass
        try:
            add_mod_case(
                message.guild.id,
                message.author.id,
                self.bot.user.id if self.bot.user else 0,
                f"anti_link_{action}",
                f"Dominio detectado: {domain}",
            )
        except Exception:
            pass

    @commands.command(name="configurar_antilink", description="Configure o Anti-Link")
    @commands.has_permissions(administrator=True)
    async def configurar_antilink(self, ctx):
        if str(ctx.guild.id) not in self.configs:
            self.load_config(ctx.guild.id)
        view = AntiLinkSettingsView(self.bot, ctx.guild.id)
        await ctx.send(embed=view.create_embed(), view=view)

    @commands.command(name="antilink_info", description="Ve o status do Anti-Link")
    async def antilink_info(self, ctx):
        if str(ctx.guild.id) not in self.configs:
            self.load_config(ctx.guild.id)
        config = self.configs[str(ctx.guild.id)]
        embed = discord.Embed(
            title="Anti-Link Info",
            description=f"Status: {'Ativado' if config['enabled'] else 'Desativado'}",
            color=discord.Color.blue() if config["enabled"] else discord.Color.red()
        )
        if config["enabled"]:
            embed.add_field(name="Acao", value=config['action'].upper(), inline=True)
            embed.add_field(name="Whitelist", value=f"{len(config['whitelist'])} membros", inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AntiLink(bot))
