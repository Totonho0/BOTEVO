import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".avi"}
ANTP_DIR = Path("antp")
SETTINGS_PATH = ANTP_DIR / "settings.json"
TIMEOUT_COUNTERS_PATH = ANTP_DIR / "timeout_counters.json"

DEFAULT_GUILD_CONFIG = {
    "log_channel_id": 0,
    "shame_channel_id": 0,
    "spam_allowed_channel_id": 0,
    "exempt_role_ids": [],
    "flood_limit": 5,
    "flood_window_sec": 8,
    "timeout_minutes": 4320,
    "score_threshold": 60,
    "enabled": True,
}

SPAM_PATTERNS = [
    {
        "name": "Convite Discord externo",
        "regex": re.compile(r"discord\.(gg|com/invite)/[a-zA-Z0-9]+", re.I),
        "score": 80,
    },
    {
        "name": "Crypto / NFT / Airdrop",
        "regex": re.compile(
            r"\b(airdrop|nft|free\s*crypto|pump|giveaway.*token|mint\s*now|claim.*token|presale)\b", re.I
        ),
        "score": 70,
    },
    {
        "name": 'Golpe estilo "Elon Musk"',
        "regex": re.compile(
            r"\b(elon\s*musk|elon)\b.{0,60}\b(crypto|bitcoin|btc|eth|token|double|investment)\b", re.I
        ),
        "score": 90,
    },
    {
        "name": "Spam NSFW / Cam",
        "regex": re.compile(
            r"\b(cam\s*girl|camgirl|nsfw|onlyfans|only\s*fans|join.*cam|cam.*discord)\b", re.I
        ),
        "score": 95,
    },
    {
        "name": "Link encurtado suspeito",
        "regex": re.compile(
            r"\b(bit\.ly|tinyurl\.com|t\.co|rb\.gy|cutt\.ly|short\.gg)\b.{0,40}\b(free|earn|join|click)\b",
            re.I,
        ),
        "score": 75,
    },
    {
        "name": "Promessa de dinheiro",
        "regex": re.compile(r"\b(earn|ganhe|ganhar|lucre)\b.{0,30}(\$|USD|BRL|reais)", re.I),
        "score": 65,
    },
]


class AntpChannelsModal(discord.ui.Modal, title="ANTP • Canais"):
    def __init__(self, cog: "AntpCog", guild_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        cfg = self.cog.get_guild_config(guild_id)
        self.log_channel = discord.ui.TextInput(
            label="Canal de log (ID, 0 para limpar)",
            default=str(cfg.get("log_channel_id", 0)),
            required=True,
            max_length=24,
        )
        self.shame_channel = discord.ui.TextInput(
            label="Canal Hall of Shame (ID, 0 para limpar)",
            default=str(cfg.get("shame_channel_id", 0)),
            required=True,
            max_length=24,
        )
        self.spam_allowed_channel = discord.ui.TextInput(
            label="Canal liberado para spam (ID, 0 para limpar)",
            default=str(cfg.get("spam_allowed_channel_id", 0)),
            required=True,
            max_length=24,
        )
        self.add_item(self.log_channel)
        self.add_item(self.shame_channel)
        self.add_item(self.spam_allowed_channel)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            log_id = int(self.log_channel.value.strip())
            shame_id = int(self.shame_channel.value.strip())
            spam_allowed_id = int(self.spam_allowed_channel.value.strip())
            if log_id < 0 or shame_id < 0 or spam_allowed_id < 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("IDs invalidos. Use numeros inteiros >= 0.", ephemeral=True)

        cfg = self.cog.get_guild_config(self.guild_id)
        cfg["log_channel_id"] = log_id
        cfg["shame_channel_id"] = shame_id
        cfg["spam_allowed_channel_id"] = spam_allowed_id
        self.cog.save_settings()
        await interaction.response.send_message("Canais atualizados com sucesso.", ephemeral=True)


class AntpProtectionModal(discord.ui.Modal, title="ANTP • Protecao"):
    def __init__(self, cog: "AntpCog", guild_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        cfg = self.cog.get_guild_config(guild_id)
        self.threshold = discord.ui.TextInput(
            label="Score threshold (1-100)",
            default=str(cfg.get("score_threshold", 60)),
            required=True,
            max_length=3,
        )
        self.timeout_minutes = discord.ui.TextInput(
            label="Timeout em minutos (1-43200)",
            default=str(cfg.get("timeout_minutes", 4320)),
            required=True,
            max_length=5,
        )
        self.flood_limit = discord.ui.TextInput(
            label="Flood limit (2-20)",
            default=str(cfg.get("flood_limit", 5)),
            required=True,
            max_length=2,
        )
        self.flood_window = discord.ui.TextInput(
            label="Flood window em segundos (2-60)",
            default=str(cfg.get("flood_window_sec", 8)),
            required=True,
            max_length=2,
        )
        self.add_item(self.threshold)
        self.add_item(self.timeout_minutes)
        self.add_item(self.flood_limit)
        self.add_item(self.flood_window)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            threshold = int(self.threshold.value.strip())
            timeout_minutes = int(self.timeout_minutes.value.strip())
            flood_limit = int(self.flood_limit.value.strip())
            flood_window = int(self.flood_window.value.strip())
        except ValueError:
            return await interaction.response.send_message("Preencha todos os campos com numeros validos.", ephemeral=True)

        if not 1 <= threshold <= 100:
            return await interaction.response.send_message("Threshold deve ser entre 1 e 100.", ephemeral=True)
        if not 1 <= timeout_minutes <= 43200:
            return await interaction.response.send_message("Timeout deve ser entre 1 e 43200 minutos.", ephemeral=True)
        if not 2 <= flood_limit <= 20:
            return await interaction.response.send_message("Flood limit deve ser entre 2 e 20.", ephemeral=True)
        if not 2 <= flood_window <= 60:
            return await interaction.response.send_message("Flood window deve ser entre 2 e 60 segundos.", ephemeral=True)

        cfg = self.cog.get_guild_config(self.guild_id)
        cfg["score_threshold"] = threshold
        cfg["timeout_minutes"] = timeout_minutes
        cfg["flood_limit"] = flood_limit
        cfg["flood_window_sec"] = flood_window
        self.cog.save_settings()
        await interaction.response.send_message("Parametros de protecao atualizados.", ephemeral=True)


class AntpExemptRolesModal(discord.ui.Modal, title="ANTP • Cargos isentos"):
    def __init__(self, cog: "AntpCog", guild_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        cfg = self.cog.get_guild_config(guild_id)
        default = ",".join(str(rid) for rid in cfg.get("exempt_role_ids", []))
        self.role_ids = discord.ui.TextInput(
            label="IDs dos cargos (separados por virgula)",
            default=default[:4000],
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=4000,
        )
        self.add_item(self.role_ids)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.role_ids.value.strip()
        roles = []
        if raw:
            for part in raw.split(","):
                part = part.strip()
                if not part:
                    continue
                if not part.isdigit():
                    return await interaction.response.send_message(
                        f"ID de cargo invalido: `{part}`. Use apenas numeros.", ephemeral=True
                    )
                roles.append(int(part))
        cfg = self.cog.get_guild_config(self.guild_id)
        cfg["exempt_role_ids"] = sorted(set(roles))
        self.cog.save_settings()
        await interaction.response.send_message("Lista de cargos isentos atualizada.", ephemeral=True)


class AntpPanelView(discord.ui.View):
    def __init__(self, cog: "AntpCog", guild_id: int, owner_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Somente quem abriu o painel pode usar estes botoes.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ativar/Desativar", style=discord.ButtonStyle.green, row=0)
    async def toggle_enabled(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = self.cog.get_guild_config(self.guild_id)
        cfg["enabled"] = not cfg.get("enabled", True)
        self.cog.save_settings()
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction.guild), view=self)

    @discord.ui.button(label="Editar Protecao", style=discord.ButtonStyle.blurple, row=0)
    async def edit_protection(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(AntpProtectionModal(self.cog, self.guild_id))

    @discord.ui.button(label="Editar Canais", style=discord.ButtonStyle.blurple, row=0)
    async def edit_channels(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(AntpChannelsModal(self.cog, self.guild_id))

    @discord.ui.button(label="Definir log neste chat", style=discord.ButtonStyle.secondary, row=1)
    async def set_log_here(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = self.cog.get_guild_config(self.guild_id)
        cfg["log_channel_id"] = interaction.channel.id
        self.cog.save_settings()
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction.guild), view=self)

    @discord.ui.button(label="Definir shame neste chat", style=discord.ButtonStyle.secondary, row=1)
    async def set_shame_here(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = self.cog.get_guild_config(self.guild_id)
        cfg["shame_channel_id"] = interaction.channel.id
        self.cog.save_settings()
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction.guild), view=self)

    @discord.ui.button(label="Liberar spam neste chat", style=discord.ButtonStyle.secondary, row=1)
    async def set_spam_allowed_here(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = self.cog.get_guild_config(self.guild_id)
        cfg["spam_allowed_channel_id"] = interaction.channel.id
        self.cog.save_settings()
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction.guild), view=self)

    @discord.ui.button(label="Cargos Isentos", style=discord.ButtonStyle.secondary, row=2)
    async def edit_exempt_roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(AntpExemptRolesModal(self.cog, self.guild_id))

    @discord.ui.button(label="Limpar Canais", style=discord.ButtonStyle.red, row=2)
    async def clear_channels(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = self.cog.get_guild_config(self.guild_id)
        cfg["log_channel_id"] = 0
        cfg["shame_channel_id"] = 0
        cfg["spam_allowed_channel_id"] = 0
        self.cog.save_settings()
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction.guild), view=self)

    @discord.ui.button(label="Atualizar Painel", style=discord.ButtonStyle.gray, row=2)
    async def refresh_panel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction.guild), view=self)


class AntpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings = self._load_json(SETTINGS_PATH, {})
        self.timeout_counters = self._load_json(TIMEOUT_COUNTERS_PATH, {})
        # {(guild_id, user_id): {"messages": [(channel_id, content, timestamp), ...]}}
        self.flood_tracker = defaultdict(lambda: {"messages": []})

    def _load_json(self, path: Path, fallback):
        ANTP_DIR.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            return fallback
        try:
            with path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, type(fallback)):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return fallback

    def _save_json(self, path: Path, payload):
        ANTP_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)

    def get_guild_config(self, guild_id: int) -> dict:
        gid = str(guild_id)
        existing = self.settings.get(gid, {})
        cfg = dict(DEFAULT_GUILD_CONFIG)
        if isinstance(existing, dict):
            cfg.update(existing)
        self.settings[gid] = cfg
        return cfg

    def save_settings(self):
        self._save_json(SETTINGS_PATH, self.settings)

    def save_counters(self):
        self._save_json(TIMEOUT_COUNTERS_PATH, self.timeout_counters)

    def increment_timeout_count(self, guild_id: int, user_id: int) -> int:
        key = f"{guild_id}:{user_id}"
        current = int(self.timeout_counters.get(key, 0)) + 1
        self.timeout_counters[key] = current
        self.save_counters()
        return current

    @staticmethod
    def format_infection_count(count: int) -> str:
        if count == 1:
            return "PRIMEIRA"
        if count == 2:
            return "SEGUNDA"
        if count == 3:
            return "TERCEIRA"
        if count == 4:
            return "QUARTA"
        if count == 5:
            return "QUINTA"
        return f"{count}a"

    def is_exempt(self, member: discord.Member, cfg: dict) -> bool:
        if member.guild_permissions.administrator:
            return True
        member_role_ids = {r.id for r in member.roles}
        exempt_ids = {int(rid) for rid in cfg.get("exempt_role_ids", [])}
        return bool(member_role_ids & exempt_ids)

    def check_flood(self, cfg: dict, guild_id: int, user_id: int, channel_id: int, content: str) -> tuple[bool, str]:
        now = datetime.now(timezone.utc)
        window = timedelta(seconds=int(cfg["flood_window_sec"]))
        data = self.flood_tracker[(guild_id, user_id)]
        data["messages"] = [(ch, c, t) for ch, c, t in data["messages"] if now - t < window]
        data["messages"].append((channel_id, content, now))
        msgs = data["messages"]

        same_channel = [m for m in msgs if m[0] == channel_id]
        duplicates = sum(1 for _, c, _ in same_channel if c == content)
        if duplicates >= 3:
            return True, f"Conteudo identico enviado {duplicates}x no mesmo canal"
        if len(same_channel) >= int(cfg["flood_limit"]):
            return True, f"{len(same_channel)} msgs no mesmo canal em {cfg['flood_window_sec']}s"

        channels_used = {ch for ch, _, _ in msgs}
        if len(channels_used) >= 2:
            unique_contents = {c for _, c, _ in msgs}
            if len(unique_contents) <= 2:
                return True, f"Mesmo conteudo em {len(channels_used)} canais diferentes"

        if len(channels_used) >= 3 and len(msgs) >= 4:
            return True, f"Spam em {len(channels_used)} canais ({len(msgs)} msgs em {cfg['flood_window_sec']}s)"
        return False, ""

    def analyze_message(self, message: discord.Message) -> tuple[int, list[str]]:
        total_score = 0
        reasons: list[str] = []
        content = message.content or ""

        for pattern in SPAM_PATTERNS:
            if pattern["regex"].search(content):
                total_score += pattern["score"]
                reasons.append(pattern["name"])

        if message.mention_everyone:
            total_score += 100
            reasons.append("Mencao @everyone ou @here")

        unique_mentions = {m.id for m in message.mentions}
        if len(unique_mentions) >= 3:
            total_score += 70
            reasons.append(f"Multiplas mencoes ({len(unique_mentions)} usuarios)")

        media_attachments = [
            a for a in message.attachments if any(a.filename.lower().endswith(ext) for ext in MEDIA_EXTENSIONS)
        ]
        if len(media_attachments) >= 2:
            total_score += 80
            reasons.append(f"{len(media_attachments)} arquivos de midia anexados")

        has_mention = message.mention_everyone or len(unique_mentions) >= 3
        has_discord_link = bool(re.search(r"discord\.(gg|com/invite)/[a-zA-Z0-9]+", content, re.I))

        if has_mention and has_discord_link:
            total_score += 30
            reasons.append("Combinacao: mencao + convite Discord")
        if has_mention and len(media_attachments) >= 2:
            total_score += 30
            reasons.append("Combinacao: mencao + multiplos anexos")
        if len(media_attachments) >= 2 and has_discord_link:
            total_score += 30
            reasons.append("Combinacao: multiplos anexos + convite Discord")

        return min(total_score, 100), reasons

    async def punish(self, member: discord.Member, reason: str, timeout_minutes: int) -> bool:
        me = member.guild.me
        if me is None:
            return False
        if not getattr(me.guild_permissions, "moderate_members", False):
            return False
        if member == member.guild.owner:
            return False
        if me.top_role <= member.top_role:
            return False
        try:
            until = datetime.now(timezone.utc) + timedelta(minutes=timeout_minutes)
            await member.timeout(until, reason=reason)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def log_action(
        self, guild: discord.Guild, message: discord.Message, reasons: list[str], score: int, log_channel_id: int
    ):
        if not log_channel_id:
            return
        channel = guild.get_channel(log_channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(log_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if channel is None:
            return

        embed = discord.Embed(
            title="🚫 Spam removido",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=f"{message.author} (`{message.author.id}`)", inline=False)
        embed.add_field(name="Canal", value=message.channel.mention, inline=True)
        embed.add_field(name="Score", value=f"{score}/100", inline=True)
        embed.add_field(name="Motivos", value="\n".join(f"• {r}" for r in reasons), inline=False)
        if message.content:
            preview = message.content[:300] + ("..." if len(message.content) > 300 else "")
            embed.add_field(name="Conteudo", value=f"```{preview}```", inline=False)
        if message.attachments:
            attach_list = "\n".join(f"• {a.filename}" for a in message.attachments[:10])
            embed.add_field(name="Anexos", value=attach_list, inline=False)
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            return

    async def send_shame_wall(self, guild: discord.Guild, member: discord.Member, timeout_count: int, shame_channel_id: int):
        if not shame_channel_id:
            return
        channel = guild.get_channel(shame_channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(shame_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if channel is None:
            return

        occurrence = self.format_infection_count(timeout_count)
        if timeout_count >= 2:
            shame_text = (
                "⚡ **Hall of Shame** ⚡\n"
                f"{member.mention} foi infectado pela **{occurrence}** vez!\n"
                "Realmente uma pessoa dedicada, comprometida a baixar tudo e qualquer tipo de coisa que ve na frente!\n"
                "Nos vemos em breve novamente, zumbi roxo."
            )
        else:
            shame_text = (
                "⚡ **Hall of Shame** ⚡\n"
                f"{member.mention} foi infectado pela **{occurrence}** vez. Colocamos ele em quarentena! 💀\n"
                "Nos vemos em breve, companheiro!\n"
                "Recomendamos formatar o computador e ativar o Windows Defender! 💜⚡"
            )
        try:
            await channel.send(shame_text)
        except (discord.Forbidden, discord.HTTPException):
            return

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        cfg = self.get_guild_config(message.guild.id)
        if not cfg.get("enabled", True):
            return
        if int(cfg.get("spam_allowed_channel_id", 0)) == message.channel.id:
            return
        if self.is_exempt(message.author, cfg):
            return

        is_flood, flood_reason = self.check_flood(
            cfg, message.guild.id, message.author.id, message.channel.id, message.content or ""
        )
        score, reasons = self.analyze_message(message)
        spam_detected = is_flood or score >= int(cfg["score_threshold"])

        if not spam_detected:
            return

        if is_flood:
            reasons.insert(0, f"Flood: {flood_reason}")
            score = max(score, 85)

        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

        try:
            await message.channel.send(
                f"⚠️ {message.author.mention} Sua mensagem foi removida por violar as regras do servidor.",
                delete_after=8,
            )
        except discord.Forbidden:
            pass

        timeout_applied = await self.punish(
            message.author,
            reason=f"Spam: {', '.join(reasons)}",
            timeout_minutes=int(cfg["timeout_minutes"]),
        )
        await self.log_action(message.guild, message, reasons, score, int(cfg["log_channel_id"]))
        if timeout_applied:
            timeout_count = self.increment_timeout_count(message.guild.id, message.author.id)
            await self.send_shame_wall(message.guild, message.author, timeout_count, int(cfg["shame_channel_id"]))

    def build_status_embed(self, guild: discord.Guild) -> discord.Embed:
        cfg = self.get_guild_config(guild.id)
        exempt_roles = cfg.get("exempt_role_ids", [])
        role_mentions = [f"<@&{rid}>" for rid in exempt_roles[:10]]
        embed = discord.Embed(title="Painel ANTP", color=0x8B5CF6)
        embed.description = "Configure o anti-spam por botoes e modais abaixo."
        embed.add_field(name="Ativado", value="Sim" if cfg["enabled"] else "Nao", inline=True)
        embed.add_field(name="Threshold", value=str(cfg["score_threshold"]), inline=True)
        embed.add_field(name="Timeout", value=f"{cfg['timeout_minutes']} min", inline=True)
        embed.add_field(name="Flood", value=f"{cfg['flood_limit']} msgs / {cfg['flood_window_sec']}s", inline=False)
        embed.add_field(
            name="Canal de log",
            value=f"<#{cfg['log_channel_id']}>" if cfg["log_channel_id"] else "Nao configurado",
            inline=True,
        )
        embed.add_field(
            name="Hall of Shame",
            value=f"<#{cfg['shame_channel_id']}>" if cfg["shame_channel_id"] else "Nao configurado",
            inline=True,
        )
        embed.add_field(
            name="Canal liberado para spam",
            value=f"<#{cfg['spam_allowed_channel_id']}>" if cfg["spam_allowed_channel_id"] else "Nao configurado",
            inline=True,
        )
        embed.add_field(name="Cargos isentos", value=", ".join(role_mentions) if role_mentions else "Nenhum", inline=False)
        return embed

    @app_commands.command(name="antp", description="Painel de configuracao do anti-spam")
    @app_commands.checks.has_permissions(administrator=True)
    async def antp(self, interaction: discord.Interaction):
        view = AntpPanelView(self, interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(
            embed=self.build_status_embed(interaction.guild),
            view=view,
            ephemeral=True,
        )

    @commands.command(name="testspam", description="Testa se um texto seria detectado")
    @commands.has_permissions(administrator=True)
    async def test_spam(self, ctx, *, texto: str):
        total_score = 0
        reasons = []
        for pattern in SPAM_PATTERNS:
            if pattern["regex"].search(texto):
                total_score += pattern["score"]
                reasons.append(pattern["name"])
        score = min(total_score, 100)
        cfg = self.get_guild_config(ctx.guild.id)
        is_spam = score >= int(cfg["score_threshold"])

        embed = discord.Embed(
            title="🔍 Resultado da analise",
            color=discord.Color.red() if is_spam else discord.Color.green(),
        )
        embed.add_field(name="Score", value=f"{score}/100", inline=True)
        embed.add_field(name="E spam?", value="Sim ✅" if is_spam else "Nao ❌", inline=True)
        embed.add_field(
            name="Obs",
            value="Attachments, mencoes e cross-channel so sao analisados em mensagens reais.",
            inline=False,
        )
        if reasons:
            embed.add_field(name="Padroes encontrados", value="\n".join(f"• {r}" for r in reasons), inline=False)
        await ctx.reply(embed=embed)


async def setup(bot):
    cog = AntpCog(bot)
    await bot.add_cog(cog)
