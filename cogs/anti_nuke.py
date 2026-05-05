import discord
from discord import app_commands
from discord.ext import commands
import json
import logging
import os
import datetime
import time
import copy
from typing import List, Dict, Optional, AsyncIterator
from database import add_mod_case

log = logging.getLogger(__name__)

MAX_ACTIONS_DEFAULT = {
    "ban": {"count": 3, "time": 10},
    "kick": {"count": 4, "time": 15},
    "channel_delete": {"count": 2, "time": 20},
    "channel_create": {"count": 3, "time": 20},
    "role_delete": {"count": 2, "time": 20},
    "role_create": {"count": 3, "time": 20},
    "webhook_create": {"count": 3, "time": 30},
    "member_role_update": {"count": 6, "time": 30},
    "permission_update": {"count": 4, "time": 25},
}

PUNISHMENT_LEVELS = {
    "none": "Apenas registrar",
    "remove_roles": "Remover cargos administrativos",
    "quarantine": "Colocar em quarentena",
    "kick": "Expulsar do servidor",
    "ban": "Banir do servidor",
}

FRIENDLY_NAMES = {
    "ban": "Banimentos",
    "kick": "Expulsoes",
    "channel_delete": "Delecao de canais",
    "channel_create": "Criacao de canais",
    "role_delete": "Delecao de cargos",
    "role_create": "Criacao de cargos",
    "webhook_create": "Criacao de webhooks",
    "member_role_update": "Atualizacoes de cargos",
    "permission_update": "Alteracoes de permissoes",
}


class AntiNukeSettings(discord.ui.View):
    def __init__(self, bot, guild_id: int, owner_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.page = 0
        self.anti_nuke = self.bot.get_cog("AntiNuke")
        if str(guild_id) not in self.anti_nuke.configs:
            self.anti_nuke.load_config(guild_id)
        self.config = self.anti_nuke.configs[str(guild_id)]
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Somente quem abriu o painel pode usar este menu.", ephemeral=True)
            return False
        return True

    def _update_buttons(self):
        self.clear_items()
        if self.page > 0:
            prev_button = discord.ui.Button(label="Anterior", style=discord.ButtonStyle.gray)
            prev_button.callback = self.prev_page
            self.add_item(prev_button)
        if self.page != 0:
            home_button = discord.ui.Button(label="Inicio", style=discord.ButtonStyle.gray)
            home_button.callback = self.home_page
            self.add_item(home_button)
        if self.page == 0:
            status_button = discord.ui.Button(
                label="Desativar" if self.config["enabled"] else "Ativar",
                style=discord.ButtonStyle.red if self.config["enabled"] else discord.ButtonStyle.green,
            )
            status_button.callback = self.toggle_status
            self.add_item(status_button)
            limits_button = discord.ui.Button(label="Configurar Limites", style=discord.ButtonStyle.blurple)
            limits_button.callback = self.show_limits
            self.add_item(limits_button)
            punish_button = discord.ui.Button(label="Configurar Punicoes", style=discord.ButtonStyle.blurple)
            punish_button.callback = self.show_punishments
            self.add_item(punish_button)
            whitelist_button = discord.ui.Button(label="Usuarios Confiaveis", style=discord.ButtonStyle.blurple)
            whitelist_button.callback = self.show_whitelist
            self.add_item(whitelist_button)
            advanced_button = discord.ui.Button(label="Avancadas", style=discord.ButtonStyle.gray)
            advanced_button.callback = self.show_advanced
            self.add_item(advanced_button)
        elif self.page == 1:
            select = self.create_limit_select()
            self.add_item(select)
        elif self.page == 2:
            select = self.create_punishment_select()
            self.add_item(select)
        elif self.page == 3:
            add_button = discord.ui.Button(label="Adicionar Usuario", style=discord.ButtonStyle.green)
            add_button.callback = self.add_trusted_user
            self.add_item(add_button)
            remove_button = discord.ui.Button(label="Remover Usuario", style=discord.ButtonStyle.red)
            remove_button.callback = self.remove_trusted_user
            self.add_item(remove_button)
            roles_button = discord.ui.Button(label="Cargos Confiaveis", style=discord.ButtonStyle.blurple)
            roles_button.callback = self.edit_trusted_roles
            self.add_item(roles_button)
        elif self.page == 4:
            log_button = discord.ui.Button(label="Definir Canal de Log", style=discord.ButtonStyle.blurple)
            log_button.callback = self.set_log_channel
            self.add_item(log_button)
            log_here_button = discord.ui.Button(label="Log neste canal", style=discord.ButtonStyle.secondary)
            log_here_button.callback = self.set_log_here
            self.add_item(log_here_button)
            notify_button = discord.ui.Button(
                label="Notificacoes: " + ("On" if self.config.get("notify_admins", True) else "Off"),
                style=discord.ButtonStyle.gray,
            )
            notify_button.callback = self.toggle_notifications
            self.add_item(notify_button)
            clear_button = discord.ui.Button(label="Limpar Historico", style=discord.ButtonStyle.red)
            clear_button.callback = self.clear_history
            self.add_item(clear_button)

    def create_limit_select(self):
        options = []
        for action_type, details in MAX_ACTIONS_DEFAULT.items():
            current = self.config["limits"].get(action_type, details)
            options.append(discord.SelectOption(
                label=FRIENDLY_NAMES.get(action_type, action_type),
                description=f"Atual: {current['count']} acoes em {current['time']}s",
                value=action_type
            ))
        select = discord.ui.Select(placeholder="Escolha um tipo de acao", options=options)
        select.callback = self.limit_selected
        return select

    def create_punishment_select(self):
        options = []
        for action_type in MAX_ACTIONS_DEFAULT.keys():
            current_punishment = self.config["punishments"].get(action_type, "none")
            options.append(discord.SelectOption(
                label=FRIENDLY_NAMES.get(action_type, action_type),
                description=f"Punicao: {PUNISHMENT_LEVELS.get(current_punishment, current_punishment)}",
                value=action_type
            ))
        select = discord.ui.Select(placeholder="Escolha a punicao", options=options)
        select.callback = self.punishment_selected
        return select

    async def prev_page(self, interaction: discord.Interaction):
        self.page -= 1; self._update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    async def home_page(self, interaction: discord.Interaction):
        self.page = 0; self._update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    async def toggle_status(self, interaction: discord.Interaction):
        self.config["enabled"] = not self.config["enabled"]
        self.anti_nuke.update_config(self.guild_id)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    async def show_limits(self, interaction: discord.Interaction):
        self.page = 1; self._update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    async def show_punishments(self, interaction: discord.Interaction):
        self.page = 2; self._update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    async def show_whitelist(self, interaction: discord.Interaction):
        self.page = 3; self._update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    async def show_advanced(self, interaction: discord.Interaction):
        self.page = 4; self._update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    async def limit_selected(self, interaction: discord.Interaction):
        action_type = interaction.data["values"][0]
        current = self.config["limits"].get(action_type, MAX_ACTIONS_DEFAULT[action_type])
        modal = LimitConfigModal(action_type, current, FRIENDLY_NAMES.get(action_type, action_type))
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.completed:
            self.config["limits"][action_type] = {"count": modal.count, "time": modal.time}
            self.anti_nuke.update_config(self.guild_id)
            self._update_buttons()
            await interaction.edit_original_response(embed=self.get_current_embed(), view=self)

    async def punishment_selected(self, interaction: discord.Interaction):
        action_type = interaction.data["values"][0]
        current = self.config["punishments"].get(action_type, "none")
        view = PunishmentSelectView(self, action_type, current, FRIENDLY_NAMES.get(action_type, action_type))
        embed = view.create_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def add_trusted_user(self, interaction: discord.Interaction):
        modal = TrustedUserModal(self.anti_nuke, self.guild_id, is_add=True)
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.completed:
            self.config = self.anti_nuke.configs[str(self.guild_id)]
            await interaction.edit_original_response(embed=self.get_current_embed(), view=self)

    async def remove_trusted_user(self, interaction: discord.Interaction):
        modal = TrustedUserModal(self.anti_nuke, self.guild_id, is_add=False)
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.completed:
            self.config = self.anti_nuke.configs[str(self.guild_id)]
            await interaction.edit_original_response(embed=self.get_current_embed(), view=self)

    async def edit_trusted_roles(self, interaction: discord.Interaction):
        modal = TrustedRolesModal(self.anti_nuke, self.guild_id)
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.completed:
            self.config = self.anti_nuke.configs[str(self.guild_id)]
            await interaction.edit_original_response(embed=self.get_current_embed(), view=self)

    async def set_log_channel(self, interaction: discord.Interaction):
        modal = LogChannelModal(self.anti_nuke, self.guild_id, self.config.get("log_channel"))
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.completed:
            self.config = self.anti_nuke.configs[str(self.guild_id)]
            self._update_buttons()
            await interaction.edit_original_response(embed=self.get_current_embed(), view=self)

    async def set_log_here(self, interaction: discord.Interaction):
        self.config["log_channel"] = interaction.channel.id
        self.anti_nuke.update_config(self.guild_id)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    async def toggle_notifications(self, interaction: discord.Interaction):
        self.config["notify_admins"] = not self.config.get("notify_admins", True)
        self.anti_nuke.update_config(self.guild_id)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    async def clear_history(self, interaction: discord.Interaction):
        confirm_view = ConfirmView()
        await interaction.response.send_message("Tem certeza que deseja limpar todo o historico?", view=confirm_view, ephemeral=True)
        await confirm_view.wait()
        if confirm_view.value:
            self.anti_nuke.clear_history(self.guild_id)
            await interaction.edit_original_response(content="Historico limpo!", view=None)
        else:
            await interaction.edit_original_response(content="Cancelado.", view=None)

    def get_current_embed(self):
        return [self.get_main_embed, self.get_limits_embed, self.get_punishments_embed,
                self.get_whitelist_embed, self.get_advanced_embed][self.page]()

    def get_main_embed(self):
        trusted_users_count = len(self.config.get("trusted_users", []))
        trusted_roles_count = len(self.config.get("trusted_role_ids", []))
        active_punishments = sorted({p for p in self.config["punishments"].values() if p != "none"})
        embed = discord.Embed(
            title="Sistema Anti-Nuke",
            description=(
                f"Status: **{'Ativado' if self.config['enabled'] else 'Desativado'}**\n"
                "Use os botoes abaixo para personalizar limites, punicoes e confianca."
            ),
            color=discord.Color.blue() if self.config["enabled"] else discord.Color.red(),
        )
        embed.add_field(name="Usuarios Confiaveis", value=str(trusted_users_count), inline=True)
        embed.add_field(name="Cargos Confiaveis", value=str(trusted_roles_count), inline=True)
        embed.add_field(
            name="Punicoes Ativas",
            value=", ".join(PUNISHMENT_LEVELS.get(p, p) for p in active_punishments) or "Nenhuma",
            inline=False,
        )
        recent = self.anti_nuke.get_recent_incidents(self.guild_id)
        if recent:
            embed.add_field(
                name="Atividade Recente",
                value="\n".join(
                    f"{FRIENDLY_NAMES.get(inc['action_type'], inc['action_type'])} por <@{inc['user_id']}> (<t:{int(inc['timestamp'])}:R>)"
                    for inc in recent[:3]
                ), inline=False
            )
        guild = self.bot.get_guild(self.guild_id)
        if self.config["enabled"] and not self.anti_nuke.audit_log_ready(guild):
            embed.color = discord.Color.orange()
        embed.add_field(
            name="Registro de auditoria",
            value=self.anti_nuke.audit_log_status_text(guild),
            inline=False,
        )
        return embed

    def get_limits_embed(self):
        embed = discord.Embed(title="Configuracao de Limites", description="Selecione um tipo de acao para configurar", color=discord.Color.blue())
        for at, fn in FRIENDLY_NAMES.items():
            current = self.config["limits"].get(at, MAX_ACTIONS_DEFAULT[at])
            embed.add_field(name=fn, value=f"{current['count']} acoes em {current['time']}s", inline=True)
        return embed

    def get_punishments_embed(self):
        embed = discord.Embed(title="Configuracao de Punicoes", description="Selecione para configurar a punicao", color=discord.Color.gold())
        for at, fn in FRIENDLY_NAMES.items():
            p = self.config["punishments"].get(at, "none")
            embed.add_field(name=fn, value=f"Punicao: {PUNISHMENT_LEVELS.get(p, p)}", inline=True)
        embed.add_field(name="Niveis de Punicao", value="\n".join(f"**{k}**: {v}" for k, v in PUNISHMENT_LEVELS.items()), inline=False)
        return embed

    def get_whitelist_embed(self):
        embed = discord.Embed(title="Usuarios Confiaveis", description="Usuarios isentos das restricoes do Anti-Nuke", color=discord.Color.green())
        trusted = self.config.get("trusted_users", [])
        trusted_roles = self.config.get("trusted_role_ids", [])
        if trusted:
            embed.add_field(name="Lista", value="\n".join(f"\u2022 <@{u}> (ID: {u})" for u in trusted[:20]), inline=False)
        else:
            embed.add_field(name="Lista", value="Nenhum usuario confiavel", inline=False)
        if trusted_roles:
            embed.add_field(
                name="Cargos confiaveis",
                value="\n".join(f"\u2022 <@&{rid}> (ID: {rid})" for rid in trusted_roles[:20]),
                inline=False,
            )
        else:
            embed.add_field(name="Cargos confiaveis", value="Nenhum cargo confiavel", inline=False)
        return embed

    def get_advanced_embed(self):
        embed = discord.Embed(title="Configuracoes Avancadas", color=discord.Color.dark_gray())
        log_ch = self.config.get("log_channel")
        embed.add_field(name="Canal de Log", value=f"<#{log_ch}>" if log_ch else "Nenhum", inline=True)
        embed.add_field(name="Notificacoes", value="Ativadas" if self.config.get("notify_admins", True) else "Desativadas", inline=True)
        return embed


class LimitConfigModal(discord.ui.Modal):
    def __init__(self, action_type, current, friendly_name):
        super().__init__(title=f"Limites: {friendly_name}")
        self.action_type = action_type; self.current = current; self.completed = False; self.count = None; self.time = None
        self.count_input = discord.ui.TextInput(label="Numero de acoes", default=str(current["count"]), required=True, min_length=1, max_length=2)
        self.add_item(self.count_input)
        self.time_input = discord.ui.TextInput(label="Tempo (segundos)", default=str(current["time"]), required=True, min_length=1, max_length=3)
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.count_input.value); t = int(self.time_input.value)
            if count < 1:
                return await interaction.response.send_message("Minimo: 1.", ephemeral=True)
            if t < 5 or t > 300:
                return await interaction.response.send_message("Tempo entre 5 e 300s.", ephemeral=True)
            self.count = count; self.time = t; self.completed = True
            await interaction.response.send_message(f"Limites atualizados: {count} acoes em {t}s", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Insira apenas numeros.", ephemeral=True)


class PunishmentSelectView(discord.ui.View):
    def __init__(self, parent_view, action_type, current, friendly_name):
        super().__init__(timeout=60)
        self.parent = parent_view; self.action_type = action_type
        options = [discord.SelectOption(label=name, description=desc, value=key, default=(key == current))
                   for key, desc in PUNISHMENT_LEVELS.items()]
        sel = discord.ui.Select(placeholder="Escolha a punicao", options=options)
        sel.callback = self.cb; self.add_item(sel)

    def create_embed(self):
        return discord.Embed(title=f"Punicao: {self.parent.config['punishments'].get(self.action_type, 'none')}", color=discord.Color.gold())

    async def cb(self, interaction: discord.Interaction):
        p = interaction.data["values"][0]
        self.parent.config["punishments"][self.action_type] = p
        self.parent.anti_nuke.update_config(self.parent.guild_id)
        await interaction.response.edit_message(content=f"Punicao atualizada para: {PUNISHMENT_LEVELS[p]}", embed=None, view=None)


class TrustedUserModal(discord.ui.Modal):
    def __init__(self, anti_nuke, guild_id, is_add=True):
        super().__init__(title="Adicionar Usuario Confiavel" if is_add else "Remover Usuario Confiavel")
        self.anti_nuke = anti_nuke; self.guild_id = guild_id; self.completed = False; self.is_add = is_add
        self.user_id = discord.ui.TextInput(label="ID do Usuario", required=True, min_length=17, max_length=20)
        self.add_item(self.user_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id.value.strip())
            config = self.anti_nuke.configs[str(self.guild_id)]
            if "trusted_users" not in config:
                config["trusted_users"] = []
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"ID {uid}"
            if self.is_add:
                if uid in config["trusted_users"]:
                    return await interaction.response.send_message(f"{name} ja esta na lista.", ephemeral=True)
                config["trusted_users"].append(uid)
                self.anti_nuke.update_config(self.guild_id)
                self.completed = True
                await interaction.response.send_message(f"{name} adicionado!", ephemeral=True)
            else:
                if uid not in config["trusted_users"]:
                    return await interaction.response.send_message(f"{name} nao esta na lista.", ephemeral=True)
                config["trusted_users"].remove(uid)
                self.anti_nuke.update_config(self.guild_id)
                self.completed = True
                return await interaction.response.send_message(f"{name} removido da lista!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("ID invalido.", ephemeral=True)


class TrustedRolesModal(discord.ui.Modal, title="Cargos Confiaveis"):
    def __init__(self, anti_nuke, guild_id):
        super().__init__()
        self.anti_nuke = anti_nuke
        self.guild_id = guild_id
        self.completed = False
        cfg = self.anti_nuke.configs.get(str(guild_id), {})
        current = ",".join(str(rid) for rid in cfg.get("trusted_role_ids", []))
        self.role_ids = discord.ui.TextInput(
            label="IDs dos cargos (separe por virgula)",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=4000,
            default=current[:4000],
        )
        self.add_item(self.role_ids)

    async def on_submit(self, interaction: discord.Interaction):
        parsed_ids: List[int] = []
        raw = self.role_ids.value.strip()
        if raw:
            for part in raw.split(","):
                item = part.strip()
                if not item:
                    continue
                if not item.isdigit():
                    return await interaction.response.send_message(
                        f"ID invalido: `{item}`. Use somente numeros separados por virgula.",
                        ephemeral=True,
                    )
                role_id = int(item)
                if interaction.guild.get_role(role_id) is None:
                    return await interaction.response.send_message(
                        f"Nao achei o cargo `{role_id}` neste servidor.",
                        ephemeral=True,
                    )
                parsed_ids.append(role_id)
        cfg = self.anti_nuke.configs[str(self.guild_id)]
        cfg["trusted_role_ids"] = sorted(set(parsed_ids))
        self.anti_nuke.update_config(self.guild_id)
        self.completed = True
        await interaction.response.send_message("Cargos confiaveis atualizados.", ephemeral=True)


class LogChannelModal(discord.ui.Modal, title="Canal de Log"):
    def __init__(self, anti_nuke, guild_id, current_channel=None):
        super().__init__()
        self.anti_nuke = anti_nuke; self.guild_id = guild_id; self.completed = False
        self.channel_id = discord.ui.TextInput(label="ID do Canal", default=str(current_channel) if current_channel else "", required=False)
        self.add_item(self.channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            config = self.anti_nuke.configs[str(self.guild_id)]
            if not self.channel_id.value.strip():
                config["log_channel"] = None; self.anti_nuke.update_config(self.guild_id)
                self.completed = True
                return await interaction.response.send_message("Canal de log desativado!", ephemeral=True)
            cid = int(self.channel_id.value.strip())
            ch = interaction.guild.get_channel(cid)
            if not ch:
                return await interaction.response.send_message("Canal nao encontrado.", ephemeral=True)
            config["log_channel"] = cid; self.anti_nuke.update_config(self.guild_id)
            self.completed = True
            await interaction.response.send_message(f"Canal de log: {ch.mention}", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("ID invalido.", ephemeral=True)


class ConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.value = None

    @discord.ui.button(label="Sim", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True; self.stop(); await interaction.response.defer()

    @discord.ui.button(label="Nao", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False; self.stop(); await interaction.response.defer()


class AntiNuke(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.configs = {}
        self.config_file = "dados/antinuke.json"
        self.action_queues = {}
        os.makedirs("dados", exist_ok=True)
        self.load_configs()

    def load_configs(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.configs = json.load(f)
            else:
                self.configs = {}
                self.save_configs()
        except Exception as e:
            print(f"Erro anti-nuke load: {e}"); self.configs = {}

    def save_configs(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.configs, f, indent=4)
        except Exception as e:
            print(f"Erro anti-nuke save: {e}")

    def load_config(self, guild_id):
        gid = str(guild_id)
        if gid not in self.configs:
            self.configs[gid] = {
                "enabled": False,
                "limits": copy.deepcopy(MAX_ACTIONS_DEFAULT),
                "punishments": {k: "none" for k in MAX_ACTIONS_DEFAULT.keys()},
                "trusted_users": [],
                "trusted_role_ids": [],
                "log_channel": None,
                "notify_admins": True,
                "action_history": []
            }
            self.save_configs()
        else:
            cfg = self.configs[gid]
            cfg.setdefault("trusted_users", [])
            cfg.setdefault("trusted_role_ids", [])
            cfg.setdefault("limits", copy.deepcopy(MAX_ACTIONS_DEFAULT))
            cfg.setdefault("punishments", {k: "none" for k in MAX_ACTIONS_DEFAULT.keys()})
        return self.configs[gid]

    def update_config(self, guild_id):
        self.save_configs()

    def audit_log_ready(self, guild: Optional[discord.Guild]) -> bool:
        if not guild:
            return False
        me = guild.me
        return bool(me and me.guild_permissions.view_audit_log)

    def audit_log_status_text(self, guild: Optional[discord.Guild]) -> str:
        if not guild:
            return "Servidor nao encontrado no cache do bot."
        me = guild.me
        if not me:
            return (
                "Nao foi possivel verificar o cargo do bot. Garanta intents de **membros** e que o bot esteja no servidor; "
                "e conceda **Ver registro de auditoria**."
            )
        if not me.guild_permissions.view_audit_log:
            return (
                "**Sem permissao** — ative **Ver registro de auditoria** no cargo do bot "
                "(Servidor > Cargos ou permissoes da integracao). Sem isso o Anti-Nuke nao sabe quem fez cada acao."
            )
        return "OK — o bot pode ler o registro e atribuir acoes aos moderadores."

    def track_action(self, guild_id, user_id, action_type):
        gid = str(guild_id)
        if gid not in self.configs or not self.configs[gid]["enabled"]:
            return False, None
        config = self.configs[gid]
        if user_id in config.get("trusted_users", []):
            return False, None
        guild = self.bot.get_guild(guild_id)
        if guild:
            member = guild.get_member(user_id)
            if member:
                trusted_role_ids = {int(rid) for rid in config.get("trusted_role_ids", [])}
                member_role_ids = {role.id for role in member.roles}
                if trusted_role_ids & member_role_ids:
                    return False, None
        sq = self.action_queues.setdefault(gid, {})
        aq = sq.setdefault(action_type, [])
        now = time.time()
        aq.append((user_id, now))
        limit_cfg = config["limits"].get(action_type, MAX_ACTIONS_DEFAULT[action_type])
        cutoff = now - limit_cfg["time"]
        aq[:] = [a for a in aq if a[1] > cutoff]
        user_actions = sum(1 for uid, _ in aq if uid == user_id)
        if user_actions >= limit_cfg["count"]:
            entry = {"user_id": user_id, "action_type": action_type, "count": user_actions, "timestamp": now, "exceeded_limit": True}
            config.setdefault("action_history", []).append(entry)
            self.update_config(guild_id)
            return True, config["punishments"].get(action_type, "none")
        return False, None

    def get_recent_incidents(self, guild_id, limit=5):
        gid = str(guild_id)
        if gid not in self.configs:
            return []
        history = self.configs[gid].get("action_history", [])
        incidents = [e for e in history if e.get("exceeded_limit", False)]
        incidents.sort(key=lambda x: x["timestamp"], reverse=True)
        return incidents[:limit]

    def clear_history(self, guild_id):
        gid = str(guild_id)
        if gid in self.configs:
            self.configs[gid]["action_history"] = []
            self.save_configs()

    async def apply_punishment(self, guild, user_id, p_type):
        try:
            member = await guild.fetch_member(user_id)
            if not member or member.bot or member.id == guild.owner_id:
                return False
            await self.log_punishment(guild.id, user_id, p_type)
            try:
                add_mod_case(
                    guild.id,
                    user_id,
                    self.bot.user.id if self.bot.user else 0,
                    f"anti_nuke_{p_type}",
                    "Punicao automatica Anti-Nuke",
                )
            except Exception:
                pass
            if p_type == "none":
                return True
            elif p_type == "remove_roles":
                roles = [r for r in member.roles if r.position < guild.me.top_role.position and
                         (r.permissions.administrator or r.permissions.manage_guild or r.permissions.ban_members)]
                for r in roles:
                    try:
                        await member.remove_roles(r, reason="Anti-Nuke")
                    except Exception:
                        pass
                return True
            elif p_type == "quarantine":
                q_role = discord.utils.get(guild.roles, name="Anti-Nuke Quarantine")
                if not q_role:
                    try:
                        q_role = await guild.create_role(name="Anti-Nuke Quarantine", permissions=discord.Permissions.none())
                    except Exception:
                        return False
                for r in member.roles:
                    if r.position < guild.me.top_role.position and r != guild.me:
                        try:
                            await member.remove_roles(r, reason="Anti-Nuke")
                        except Exception:
                            pass
                await member.add_roles(q_role)
                return True
            elif p_type == "kick":
                try:
                    await guild.kick(member, reason="Anti-Nuke")
                    return True
                except Exception:
                    return False
            elif p_type == "ban":
                try:
                    await guild.ban(member, reason="Anti-Nuke", delete_message_days=1)
                    return True
                except Exception:
                    return False
        except Exception:
            return False

    async def log_punishment(self, guild_id, user_id, p_type):
        try:
            gid = str(guild_id)
            if gid not in self.configs:
                return
            config = self.configs[gid]
            log_cid = config.get("log_channel")
            if not log_cid:
                return
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return
            ch = guild.get_channel(log_cid)
            if not ch:
                return
            embed = discord.Embed(
                title="Anti-Nuke | Punicao Aplicada",
                description=f"Usuario: <@{user_id}> ({user_id})\nPunicao: {PUNISHMENT_LEVELS.get(p_type, p_type)}",
                color=discord.Color.red(), timestamp=datetime.datetime.now()
            )
            await ch.send(embed=embed)
            if config.get("notify_admins", True):
                admins = [m for m in guild.members if not m.bot and m.guild_permissions.administrator and m.id != user_id]
                for a in admins[:3]:
                    try:
                        dm = discord.Embed(
                            title=f"Alerta de Seguranca em {guild.name}",
                            description=f"Anti-Nuke detectou atividade suspeita.\nUsuario: <@{user_id}>\nPunicao: {PUNISHMENT_LEVELS.get(p_type, p_type)}",
                            color=discord.Color.red(), timestamp=datetime.datetime.now()
                        )
                        await a.send(embed=dm)
                    except Exception:
                        pass
        except Exception:
            pass

    async def _iter_audit_log(self, guild: discord.Guild, **kwargs) -> AsyncIterator[discord.AuditLogEntry]:
        me = guild.me
        if not me or not me.guild_permissions.view_audit_log:
            return
        try:
            async for entry in guild.audit_logs(**kwargs):
                yield entry
        except discord.HTTPException as e:
            log.debug(
                "Anti-nuke: audit_logs falhou (guild=%s action=%s): %s",
                guild.id,
                kwargs.get("action"),
                e,
            )
            return

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        async for entry in self._iter_audit_log(guild, limit=1, action=discord.AuditLogAction.ban):
            if entry.user.id == self.bot.user.id:
                return
            exceeded, p = self.track_action(guild.id, entry.user.id, "ban")
            if exceeded:
                await self.apply_punishment(guild, entry.user.id, p)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        async for entry in self._iter_audit_log(guild, limit=1, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id and entry.user.id != self.bot.user.id:
                exceeded, p = self.track_action(guild.id, entry.user.id, "kick")
                if exceeded:
                    await self.apply_punishment(guild, entry.user.id, p)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        guild = channel.guild
        async for entry in self._iter_audit_log(guild, limit=1, action=discord.AuditLogAction.channel_delete):
            if entry.user.id != self.bot.user.id:
                exceeded, p = self.track_action(guild.id, entry.user.id, "channel_delete")
                if exceeded:
                    await self.apply_punishment(guild, entry.user.id, p)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        guild = channel.guild
        async for entry in self._iter_audit_log(guild, limit=1, action=discord.AuditLogAction.channel_create):
            if entry.user.id != self.bot.user.id:
                exceeded, p = self.track_action(guild.id, entry.user.id, "channel_create")
                if exceeded:
                    await self.apply_punishment(guild, entry.user.id, p)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        guild = role.guild
        async for entry in self._iter_audit_log(guild, limit=1, action=discord.AuditLogAction.role_delete):
            if entry.user.id != self.bot.user.id:
                exceeded, p = self.track_action(guild.id, entry.user.id, "role_delete")
                if exceeded:
                    await self.apply_punishment(guild, entry.user.id, p)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        guild = role.guild
        async for entry in self._iter_audit_log(guild, limit=1, action=discord.AuditLogAction.role_create):
            if entry.user.id != self.bot.user.id:
                exceeded, p = self.track_action(guild.id, entry.user.id, "role_create")
                if exceeded:
                    await self.apply_punishment(guild, entry.user.id, p)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        guild = channel.guild
        async for entry in self._iter_audit_log(guild, limit=1, action=discord.AuditLogAction.webhook_create):
            if entry.user.id != self.bot.user.id:
                exceeded, p = self.track_action(guild.id, entry.user.id, "webhook_create")
                if exceeded:
                    await self.apply_punishment(guild, entry.user.id, p)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles != after.roles:
            guild = before.guild
            async for entry in self._iter_audit_log(guild, limit=1, action=discord.AuditLogAction.member_role_update):
                if entry.target.id == before.id and entry.user.id != self.bot.user.id:
                    exceeded, p = self.track_action(guild.id, entry.user.id, "member_role_update")
                    if exceeded:
                        await self.apply_punishment(guild, entry.user.id, p)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if before.overwrites != after.overwrites:
            guild = before.guild
            async for entry in self._iter_audit_log(guild, limit=1, action=discord.AuditLogAction.overwrite_update):
                if entry.target.id == before.id and entry.user.id != self.bot.user.id:
                    exceeded, p = self.track_action(guild.id, entry.user.id, "permission_update")
                    if exceeded:
                        await self.apply_punishment(guild, entry.user.id, p)

    @app_commands.command(name="antinuke", description="Configura o sistema Anti-Nuke")
    @app_commands.default_permissions(administrator=True)
    async def antinuke_command(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("Precisa ser admin!", ephemeral=True)
        try:
            view = AntiNukeSettings(self.bot, interaction.guild.id, interaction.user.id)
            await interaction.response.send_message(embed=view.get_current_embed(), view=view, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Erro: {e}", ephemeral=True)

    @app_commands.command(name="antinuke_status", description="Status do Anti-Nuke")
    async def antinuke_status_command(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        if gid not in self.configs:
            self.load_config(interaction.guild.id)
        config = self.configs[gid]
        guild = interaction.guild
        audit_ok = self.audit_log_ready(guild)
        color = discord.Color.blue() if config["enabled"] else discord.Color.red()
        if config["enabled"] and not audit_ok:
            color = discord.Color.orange()
        embed = discord.Embed(
            title="Status do Anti-Nuke",
            description=f"Status: {'Ativado' if config['enabled'] else 'Desativado'}",
            color=color,
        )
        if config["enabled"]:
            embed.add_field(name="Usuarios Confiaveis", value=f"{len(config.get('trusted_users', []))}", inline=True)
            recent = self.get_recent_incidents(interaction.guild.id, limit=3)
            if recent:
                embed.add_field(name="Recentes", value="\n".join(
                    f"{FRIENDLY_NAMES.get(i['action_type'])} por <@{i['user_id']}>" for i in recent
                ), inline=False)
        embed.add_field(
            name="Registro de auditoria",
            value=self.audit_log_status_text(guild),
            inline=False,
        )
        embed.set_footer(text="Use /antinuke para configurar")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(AntiNuke(bot))
