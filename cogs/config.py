"""Config do servidor — toggle slash/prefix por comando."""
import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from json_utils import atomic_write_json

CONFIG_FILE = 'data/server_config.json'
CHAT_COUNT_FILE = 'data/chat_count_config.json'
DEFAULT_PREFIX = '!'

# Categorias com comandos
COMMAND_CATEGORIES = {
    "Voz": ["call", "profile", "chattop", "saldo", "diario", "semanal", "mensal", "top", "rfixo", "cfixo", "rank", "levels"],
    "Economy": ["transferir", "loja", "addtot", "rtot", "setcoins"],
    "Info": ["ping", "avatar", "userinfo", "serverinfo"],
    "Admin": ["addhoras", "rmhoras", "reset_user", "reset_server", "reset_horas", "reset_chats", "level_config", "modconfig", "autoconfig"],
    "Utilidade": ["enquete", "sortear", "roleinfo", "calculadora", "limpar", "baninfo", "status"],
    "Seguranca": ["configurar_antilink", "antilink_info"],
    "Moderacao": ["warn", "warnings", "unwarn", "mute", "unmute", "kickm", "banm", "unbanm"],
    "Ship": ["ship", "casal", "topship", "shipstats", "shipme", "tosco", "sf"],
}

# Comandos SEMPRE slash (nao desativaveis)
ALWAYS_SLASH = {"antinuke", "antinuke_status", "slowmode", "anuncio", "nick", "help", "backup_server", "restore_server", "painel_econ", "ver_econ"}

# Todos os comandos controlaveis
ALL_TOGGLEABLE = set()
for cmds in COMMAND_CATEGORIES.values():
    ALL_TOGGLEABLE.update(cmds)


def _module_key(name: str) -> str:
    return (name or '').strip().lower()


def command_module(cmd_name: str):
    for category, commands_in_cat in COMMAND_CATEGORIES.items():
        if cmd_name in commands_in_cat:
            return category
    return None


def load_configs():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_configs(cfg):
    os.makedirs('data', exist_ok=True)
    atomic_write_json(CONFIG_FILE, cfg)


def get_prefix(guild_id):
    cfg = load_configs()
    gid = str(guild_id)
    prefix = cfg.get(gid, {}).get('prefix', DEFAULT_PREFIX)
    if not isinstance(prefix, str) or not prefix.strip():
        return DEFAULT_PREFIX
    return prefix[:5]


def set_prefix(guild_id, prefix):
    cfg = load_configs()
    gid = str(guild_id)
    if gid not in cfg:
        cfg[gid] = {'slash_cmds': {}, 'modules': {}, 'prefix': DEFAULT_PREFIX}
    cfg[gid]['prefix'] = (prefix or DEFAULT_PREFIX).strip()[:5] or DEFAULT_PREFIX
    save_configs(cfg)


def get_module_config(guild_id):
    cfg = load_configs()
    gid = str(guild_id)
    return cfg.get(gid, {}).get('modules', {})


def is_module_enabled(guild_id, module_name):
    mcfg = get_module_config(guild_id)
    key = _module_key(module_name)
    # default ON
    return mcfg.get(key, True)


def set_module_enabled(guild_id, module_name, enabled):
    cfg = load_configs()
    gid = str(guild_id)
    if gid not in cfg:
        cfg[gid] = {'slash_cmds': {}, 'modules': {}, 'prefix': DEFAULT_PREFIX}
    if 'modules' not in cfg[gid]:
        cfg[gid]['modules'] = {}
    cfg[gid]['modules'][_module_key(module_name)] = bool(enabled)
    save_configs(cfg)


def get_slash_config(guild_id):
    """Returns dict of {cmd: True/False} for slash enabled."""
    cfg = load_configs()
    gid = str(guild_id)
    return cfg.get(gid, {}).get('slash_cmds', {})


def is_slash_enabled(guild_id, cmd):
    """Check if a specific command has slash enabled."""
    if cmd in ALWAYS_SLASH:
        return True
    cfg = get_slash_config(guild_id)
    # Default: slash enabled if not configured
    return cfg.get(cmd, True)


def set_slash_cmd(guild_id, cmd, enabled):
    cfg = load_configs()
    gid = str(guild_id)
    if gid not in cfg:
        cfg[gid] = {'slash_cmds': {}}
    if 'slash_cmds' not in cfg[gid]:
        cfg[gid]['slash_cmds'] = {}
    cfg[gid]['slash_cmds'][cmd] = enabled
    save_configs(cfg)


def load_chat_count_config():
    default_cfg = {
        "exclude_name_keywords": ["call", "calls", "voice", "voz"],
        "exclude_channel_ids_by_guild": {},
        "include_voice_channel_ids_by_guild": {},
        "voice_allowlist_enabled_by_guild": {},
    }
    if os.path.exists(CHAT_COUNT_FILE):
        try:
            with open(CHAT_COUNT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg = dict(default_cfg)
                cfg.update(data)
                cfg.setdefault("exclude_name_keywords", default_cfg["exclude_name_keywords"])
                cfg.setdefault("exclude_channel_ids_by_guild", {})
                cfg.setdefault("include_voice_channel_ids_by_guild", {})
                cfg.setdefault("voice_allowlist_enabled_by_guild", {})
                return cfg
        except Exception:
            pass
    return default_cfg


def save_chat_count_config(cfg):
    atomic_write_json(CHAT_COUNT_FILE, cfg)


def build_rconfig_embed(guild: discord.Guild):
    cfg = load_chat_count_config()
    gid = str(guild.id)
    channel_ids = cfg.get("exclude_channel_ids_by_guild", {}).get(gid, [])
    keywords = cfg.get("exclude_name_keywords", [])

    channel_mentions = []
    for raw_id in channel_ids:
        try:
            cid = int(raw_id)
        except (TypeError, ValueError):
            continue
        ch = guild.get_channel(cid)
        channel_mentions.append(ch.mention if ch else f"`{cid}`")

    channels_text = "\n".join(channel_mentions) if channel_mentions else "Nenhum canal configurado."
    voice_text = (
        "Todos os canais de voz contam por padrao.\n"
        "Somente canais no campo **Canais excluidos** nao contam."
    )
    keywords_text = ", ".join(f"`{k}`" for k in keywords) if keywords else "Nenhuma"

    e = discord.Embed(
        title="rconfig - Chat de Voz/Call",
        description=(
            "**Chat:** canais/palavras (nome + categoria) nao contam no ranking de chat.\n"
            "**Voz:** todos os canais contam, exceto IDs em **Canais excluidos**."
        ),
        color=0x5865f2
    )
    e.add_field(name="Voz", value=voice_text, inline=False)
    e.add_field(name="Palavras-chave (exclusao)", value=keywords_text, inline=False)
    e.add_field(name="Canais excluidos (texto + voz)", value=channels_text, inline=False)
    e.set_footer(text="Use os botoes abaixo para editar.")
    return e


class RconfigTextModal(discord.ui.Modal):
    def __init__(self, mode: str):
        title_map = {
            "add_canal": "Adicionar canal excluido",
            "rm_canal": "Remover canal excluido",
            "add_palavra": "Adicionar palavra-chave",
            "rm_palavra": "Remover palavra-chave",
            "add_voz_perm": "Voz: excluir canal por ID",
            "rm_voz_perm": "Voz: remover canal excluido",
        }
        super().__init__(title=title_map.get(mode, "rconfig"))
        self.mode = mode
        label_map = {
            "add_canal": "ID do canal",
            "rm_canal": "ID do canal",
            "add_palavra": "Palavra-chave",
            "rm_palavra": "Palavra-chave",
            "add_voz_perm": "ID do canal de voz para excluir",
            "rm_voz_perm": "ID do canal de voz para recontar",
        }
        placeholder_map = {
            "add_canal": "Ex: 123456789012345678",
            "rm_canal": "Ex: 123456789012345678",
            "add_palavra": "Ex: voz-chat",
            "rm_palavra": "Ex: call",
            "add_voz_perm": "Ex: 123456789012345678",
            "rm_voz_perm": "Ex: 123456789012345678",
        }
        self.value_input = discord.ui.TextInput(
            label=label_map.get(mode, "Valor"),
            placeholder=placeholder_map.get(mode, ""),
            required=True,
            max_length=100
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_chat_count_config()
        gid = str(interaction.guild.id)
        channels_by_guild = cfg.setdefault("exclude_channel_ids_by_guild", {})
        current_ids = channels_by_guild.setdefault(gid, [])
        keywords = cfg.setdefault("exclude_name_keywords", ["call", "calls", "voice", "voz"])
        raw = (self.value_input.value or "").strip()

        if self.mode in {"add_voz_perm", "rm_voz_perm"}:
            try:
                cid = int(raw)
            except ValueError:
                return await interaction.response.send_message("ID de canal invalido.", ephemeral=True)
            ch = interaction.guild.get_channel(cid)
            if ch is None or not isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                return await interaction.response.send_message(
                    "Use o ID de um canal de **voz** ou **palco** deste servidor.", ephemeral=True
                )
            if self.mode == "add_voz_perm":
                if cid not in current_ids:
                    current_ids.append(cid)
                save_chat_count_config(cfg)
                msg = f"{ch.mention} excluido da contagem de voz."
            else:
                if cid in current_ids:
                    current_ids.remove(cid)
                save_chat_count_config(cfg)
                msg = f"{ch.mention} voltou a contar no tempo de voz."
            view = RconfigView(interaction.user.id)
            await interaction.response.edit_message(embed=build_rconfig_embed(interaction.guild), view=view)
            await interaction.followup.send(msg, ephemeral=True)
            return

        if self.mode in {"add_canal", "rm_canal"}:
            try:
                cid = int(raw)
            except ValueError:
                return await interaction.response.send_message("ID de canal invalido.", ephemeral=True)
            if interaction.guild.get_channel(cid) is None:
                return await interaction.response.send_message("Canal nao encontrado neste servidor.", ephemeral=True)

            if self.mode == "add_canal":
                if cid not in current_ids:
                    current_ids.append(cid)
                    save_chat_count_config(cfg)
                msg = f"Canal `{cid}` adicionado a exclusao."
            else:
                if cid in current_ids:
                    current_ids.remove(cid)
                    save_chat_count_config(cfg)
                msg = f"Canal `{cid}` removido da exclusao."
        else:
            word = raw.lower()
            if not word:
                return await interaction.response.send_message("Palavra invalida.", ephemeral=True)
            if self.mode == "add_palavra":
                if word not in keywords:
                    keywords.append(word)
                    save_chat_count_config(cfg)
                msg = f"Palavra `{word}` adicionada."
            else:
                if word in keywords:
                    keywords.remove(word)
                    save_chat_count_config(cfg)
                msg = f"Palavra `{word}` removida."

        view = RconfigView(interaction.user.id)
        await interaction.response.edit_message(embed=build_rconfig_embed(interaction.guild), view=view)
        await interaction.followup.send(msg, ephemeral=True)


class RconfigView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=600)
        self.owner_id = owner_id

    def _can_use(self, interaction: discord.Interaction) -> bool:
        return bool(interaction.user.guild_permissions.administrator)

    async def _deny(self, interaction: discord.Interaction):
        await interaction.response.send_message("Apenas administradores podem usar este painel.", ephemeral=True)

    @discord.ui.button(label="Adicionar canal", style=discord.ButtonStyle.green, row=0)
    async def add_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_use(interaction):
            return await self._deny(interaction)
        await interaction.response.send_modal(RconfigTextModal("add_canal"))

    @discord.ui.button(label="Remover canal", style=discord.ButtonStyle.red, row=0)
    async def remove_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_use(interaction):
            return await self._deny(interaction)
        await interaction.response.send_modal(RconfigTextModal("rm_canal"))

    @discord.ui.button(label="Usar canal atual", style=discord.ButtonStyle.primary, row=0)
    async def add_current_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_use(interaction):
            return await self._deny(interaction)
        cfg = load_chat_count_config()
        gid = str(interaction.guild.id)
        channels_by_guild = cfg.setdefault("exclude_channel_ids_by_guild", {})
        current_ids = channels_by_guild.setdefault(gid, [])
        cid = interaction.channel.id
        if cid not in current_ids:
            current_ids.append(cid)
            save_chat_count_config(cfg)
        await interaction.response.edit_message(embed=build_rconfig_embed(interaction.guild), view=RconfigView(interaction.user.id))
        await interaction.followup.send(f"Canal atual `{cid}` adicionado a exclusao.", ephemeral=True)

    @discord.ui.button(label="Adicionar palavra", style=discord.ButtonStyle.green, row=1)
    async def add_keyword(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_use(interaction):
            return await self._deny(interaction)
        await interaction.response.send_modal(RconfigTextModal("add_palavra"))

    @discord.ui.button(label="Remover palavra", style=discord.ButtonStyle.red, row=1)
    async def remove_keyword(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_use(interaction):
            return await self._deny(interaction)
        await interaction.response.send_modal(RconfigTextModal("rm_palavra"))

    @discord.ui.button(label="Resetar", style=discord.ButtonStyle.secondary, row=2)
    async def reset_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_use(interaction):
            return await self._deny(interaction)
        cfg = load_chat_count_config()
        gid = str(interaction.guild.id)
        cfg.setdefault("exclude_channel_ids_by_guild", {})[gid] = []
        cfg["exclude_name_keywords"] = ["call", "calls", "voice", "voz"]
        save_chat_count_config(cfg)
        await interaction.response.edit_message(embed=build_rconfig_embed(interaction.guild), view=RconfigView(interaction.user.id))
        await interaction.followup.send("Configuracao resetada para o padrao.", ephemeral=True)

    @discord.ui.button(label="Atualizar", style=discord.ButtonStyle.blurple, row=2)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_use(interaction):
            return await self._deny(interaction)
        await interaction.response.edit_message(embed=build_rconfig_embed(interaction.guild), view=RconfigView(interaction.user.id))

    @discord.ui.button(label="Voz: excluir (ID)", style=discord.ButtonStyle.green, row=4)
    async def add_voice_allowed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_use(interaction):
            return await self._deny(interaction)
        await interaction.response.send_modal(RconfigTextModal("add_voz_perm"))

    @discord.ui.button(label="Voz: remover exclusao", style=discord.ButtonStyle.red, row=4)
    async def remove_voice_allowed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_use(interaction):
            return await self._deny(interaction)
        await interaction.response.send_modal(RconfigTextModal("rm_voz_perm"))

    @discord.ui.button(label="Excluir esta call", style=discord.ButtonStyle.primary, row=4)
    async def allow_current_voice(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_use(interaction):
            return await self._deny(interaction)
        m = interaction.user
        vc = m.voice.channel if m and m.voice else None
        if vc is None or not isinstance(vc, (discord.VoiceChannel, discord.StageChannel)):
            return await interaction.response.send_message(
                "Entre em um **canal de voz** deste servidor e clique de novo.", ephemeral=True
            )
        cfg = load_chat_count_config()
        gid = str(interaction.guild.id)
        channels_by_guild = cfg.setdefault("exclude_channel_ids_by_guild", {})
        excluded_ids = channels_by_guild.setdefault(gid, [])
        cid = vc.id
        added = False
        if cid not in excluded_ids:
            excluded_ids.append(cid)
            added = True
        save_chat_count_config(cfg)
        if added:
            note = f"{vc.mention} adicionado em **canais excluidos** (nao conta voz)."
        else:
            note = f"{vc.mention} ja estava em **canais excluidos**."
        await interaction.response.edit_message(embed=build_rconfig_embed(interaction.guild), view=RconfigView(interaction.user.id))
        await interaction.followup.send(note, ephemeral=True)

    @discord.ui.button(label="Preview neste canal", style=discord.ButtonStyle.secondary, row=3)
    async def preview_here(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_use(interaction):
            return await self._deny(interaction)
        cfg = load_chat_count_config()
        channel_name = (getattr(interaction.channel, "name", "") or "").lower()
        category_name = (getattr(getattr(interaction.channel, "category", None), "name", "") or "").lower()
        target = f"{channel_name} {category_name}"
        gid = str(interaction.guild.id)
        excluded_ids = set(cfg.get("exclude_channel_ids_by_guild", {}).get(gid, []))
        keywords = [str(k).strip().lower() for k in cfg.get("exclude_name_keywords", []) if str(k).strip()]
        by_id = interaction.channel.id in excluded_ids
        by_keyword = any(k in target for k in keywords)
        status = "NAO conta no chat ranking" if (by_id or by_keyword) else "Conta normalmente no chat ranking"
        reason = []
        if by_id:
            reason.append("canal em lista de exclusao")
        if by_keyword:
            reason.append("nome/categoria bate com palavra-chave")
        reason_text = ", ".join(reason) if reason else "nenhuma regra de exclusao ativa para este canal"
        await interaction.response.send_message(
            f"Preview: **{status}**.\nMotivo: {reason_text}.",
            ephemeral=True
        )


class CategorySelect(discord.ui.Select):
    def __init__(self, view):
        self.view_ref = view
        options = []
        for cat in COMMAND_CATEGORIES.keys():
            options.append(discord.SelectOption(label=cat, value=cat))
        super().__init__(placeholder="Selecione a categoria...", options=options)

    async def callback(self, ix: discord.Interaction):
        self.view_ref.current_cat = self.values[0]
        await self.view_ref.refresh(ix)


class ToggleButton(discord.ui.Button):
    def __init__(self, cmd, enabled, prefix):
        style = discord.ButtonStyle.green if enabled else discord.ButtonStyle.red
        label = f"ON  /{cmd}" if enabled else f"OFF {prefix}{cmd}"
        super().__init__(label=label, style=style)
        self.cmd = cmd
        self.enabled = enabled
        self.prefix = prefix

    async def callback(self, ix: discord.Interaction):
        self.enabled = not self.enabled
        set_slash_cmd(ix.guild.id, self.cmd, self.enabled)
        self.style = discord.ButtonStyle.green if self.enabled else discord.ButtonStyle.red
        self.label = f"ON  /{self.cmd}" if self.enabled else f"OFF {self.prefix}{self.cmd}"
        view = self.view
        view.cmd_states[self.cmd] = self.enabled
        await view.update_embed(ix)


class ConfigView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.prefix = get_prefix(guild_id)
        self.current_cat = "Voz"
        self.cmd_states = {}
        # Load all current states
        for cmds in COMMAND_CATEGORIES.values():
            for cmd in cmds:
                self.cmd_states[cmd] = is_slash_enabled(guild_id, cmd)
        self.add_item(CategorySelect(self))
        self._build_buttons()

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if ix.user.guild_permissions.administrator:
            return True
        await ix.response.send_message("Apenas administradores podem alterar essa configuracao.", ephemeral=True)
        return False

    def _build_buttons(self):
        # Remove old buttons (keep the select)
        for child in list(self.children):
            if isinstance(child, discord.ui.Button):
                self.remove_item(child)
        # Add new buttons for current category
        cmds = COMMAND_CATEGORIES.get(self.current_cat, [])
        for cmd in cmds:
            state = self.cmd_states.get(cmd, True)
            btn = ToggleButton(cmd, state, self.prefix)
            self.add_item(btn)

    def _make_embed(self):
        lines = []
        cmds = COMMAND_CATEGORIES.get(self.current_cat, [])
        slash_count = 0
        total = len(cmds)
        for cmd in cmds:
            state = self.cmd_states.get(cmd, True)
            icon = "\U0001F7E2" if state else "\U0001F534"
            mode = "Slash ON" if state else "Prefix ON"
            lines.append(f"{icon} `{cmd}` — {mode}")
            if state:
                slash_count += 1

        e = discord.Embed(
            title=f"\u2699\uFE0F Slash Config — {self.current_cat}",
            description="\n".join(lines),
            color=0x5865f2)
        e.set_footer(text=f"Slash: {slash_count}/{total} ativos | Verde=ON Slash | Vermelho=ON Prefix")
        return e

    async def refresh(self, ix: discord.Interaction):
        self._build_buttons()
        await ix.response.edit_message(embed=self._make_embed(), view=self)

    async def update_embed(self, ix: discord.Interaction):
        await ix.response.edit_message(embed=self._make_embed(), view=self)


class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='config', description='Configurar slash/prefix por comando')
    @commands.has_permissions(administrator=True)
    async def config(self, ctx):
        guild_id = ctx.guild.id
        prefix = get_prefix(guild_id)
        # Build summary
        total_on = 0
        total_off = 0
        for cmds in COMMAND_CATEGORIES.values():
            for cmd in cmds:
                if is_slash_enabled(guild_id, cmd):
                    total_on += 1
                else:
                    total_off += 1

        e = discord.Embed(
            title="\u2699\uFE0F Configuracao de Slash/Prefix",
            description=f"Atualmente: **{total_on}** comandos com slash | **{total_off}** comandos com prefix\n\n"
                        f"Selecione uma categoria abaixo para alternar cada comando.\n"
                        f"\U0001F7E2 Verde = Slash ativo (`/comando`)\n"
                        f"\U0001F534 Vermelho = Prefix ativo (`{prefix}comando`)",
            color=0x5865f2)
        e.set_footer(text=f"Comandos SEMPRE slash: {', '.join(sorted(ALWAYS_SLASH))}")

        view = ConfigView(guild_id)
        await ctx.send(embed=e, view=view)

    @commands.hybrid_command(name='setprefix', description='Define o prefixo do servidor')
    @commands.has_permissions(administrator=True)
    async def setprefix(self, ctx, *, prefix: str):
        p = (prefix or '').strip()
        if not p:
            return await ctx.send("Informe um prefixo valido.")
        if len(p) > 5:
            return await ctx.send("Prefixo muito longo (maximo 5 caracteres).")
        set_prefix(ctx.guild.id, p)
        await ctx.send(f"Prefixo atualizado para `{p}`.")

    @commands.hybrid_command(name='modulo', description='Ativa/Desativa modulo por servidor')
    @commands.has_permissions(administrator=True)
    async def modulo(self, ctx, modulo_nome: str, estado: str = "status"):
        modules = {k.lower(): k for k in COMMAND_CATEGORIES.keys()}
        key = (modulo_nome or '').strip().lower()
        if key not in modules:
            return await ctx.send(f"Modulo invalido. Opcoes: {', '.join(COMMAND_CATEGORIES.keys())}")
        display = modules[key]
        st = estado.strip().lower()
        if st in ("on", "ativar", "enable", "enabled"):
            set_module_enabled(ctx.guild.id, display, True)
            return await ctx.send(f"Modulo **{display}** ativado.")
        if st in ("off", "desativar", "disable", "disabled"):
            set_module_enabled(ctx.guild.id, display, False)
            return await ctx.send(f"Modulo **{display}** desativado.")
        enabled = is_module_enabled(ctx.guild.id, display)
        await ctx.send(f"Modulo **{display}**: {'Ativo' if enabled else 'Desativado'}.")

    @app_commands.command(name='rconfig', description='Painel para configurar regras de chat de call/voz')
    @app_commands.checks.cooldown(2, 15.0)
    @app_commands.default_permissions(administrator=True)
    async def rconfig(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=build_rconfig_embed(interaction.guild),
            view=RconfigView(interaction.user.id),
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
