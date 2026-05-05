import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord
from discord.ext import commands, tasks
from datetime import datetime
import asyncio
import json
import threading
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from database import init, cleanup_old, vacuum
from utils import now_brazil, ensure_aware
from cogs.config import get_prefix as get_guild_prefix, command_module, is_module_enabled
from chat_rules import sanitize_chat_count_config, should_count_channel_message, should_count_voice_time, DEFAULT_CHAT_COUNT_CONFIG
from json_utils import atomic_write_json

def load_token():
    """First checks env var, then .env file in project root"""
    env_var = os.environ.get('DISCORD_TOKEN')
    if env_var:
        return env_var.strip().strip('"').strip("'")
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_file):
        with open(env_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                if '=' in line:
                    key, val = line.split('=', 1)
                    if key.strip() == 'DISCORD_TOKEN':
                        return val.strip().strip('"').strip("'")
    return None

TOKEN = load_token()
if not TOKEN:
    print("ERRO: Token nao encontrado! Edite o arquivo .env e coloque seu token.")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix=self.dynamic_prefix, intents=intents, help_command=None)
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.active_sessions = {}
        self.active_sessions_file = os.path.join(self.base_dir, 'data', 'active_voice_sessions.json')
        self.auto_rankings = {}
        self.auto_rankings_file = os.path.join(self.base_dir, 'data', 'auto_rankings.json')
        self.guild_configs = {}
        self.start_time = None
        self.chat_count_cfg_file = os.path.join(self.base_dir, 'data', 'chat_count_config.json')
        self._chat_count_cfg_cache = None
        self._chat_count_cfg_mtime = None
        self._chat_count_cfg_checked_at = None
        self.log = logging.getLogger("bot-primal")

    def _session_key(self, guild_id: int, user_id: int):
        return (int(guild_id), int(user_id))

    def load_active_sessions(self):
        sessions = {}
        try:
            if os.path.exists(self.active_sessions_file):
                with open(self.active_sessions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for raw_key, raw_started_at in data.items():
                        if not isinstance(raw_key, str) or ":" not in raw_key:
                            continue
                        g_raw, u_raw = raw_key.split(":", 1)
                        try:
                            gid = int(g_raw)
                            uid = int(u_raw)
                        except ValueError:
                            continue
                        try:
                            started = ensure_aware(datetime.fromisoformat(str(raw_started_at)))
                        except Exception:
                            continue
                        sessions[self._session_key(gid, uid)] = started
        except Exception as e:
            self.log.warning("Falha ao carregar sessoes de voz ativas: %s", e)
        self.active_sessions = sessions

    def save_active_sessions(self):
        try:
            payload = {
                f"{gid}:{uid}": ensure_aware(started_at).isoformat()
                for (gid, uid), started_at in self.active_sessions.items()
            }
            atomic_write_json(self.active_sessions_file, payload)
        except Exception as e:
            self.log.warning("Falha ao salvar sessoes de voz ativas: %s", e)

    def is_user_in_active_session(self, guild_id: int, user_id: int) -> bool:
        return self._session_key(guild_id, user_id) in self.active_sessions

    def get_active_session_start(self, guild_id: int, user_id: int):
        return self.active_sessions.get(self._session_key(guild_id, user_id))

    def iter_active_sessions(self, guild_id: int | None = None):
        for (gid, uid), started_at in self.active_sessions.items():
            if guild_id is None or gid == int(guild_id):
                yield gid, uid, started_at

    def count_active_sessions(self, guild_id: int | None = None) -> int:
        if guild_id is None:
            return len(self.active_sessions)
        return sum(1 for _gid, _uid, _started in self.iter_active_sessions(guild_id))

    def _load_chat_count_config(self):
        default_cfg = DEFAULT_CHAT_COUNT_CONFIG
        now = datetime.now()
        if self._chat_count_cfg_checked_at:
            if (now - self._chat_count_cfg_checked_at).total_seconds() < 5 and self._chat_count_cfg_cache is not None:
                return self._chat_count_cfg_cache

        self._chat_count_cfg_checked_at = now
        try:
            if not os.path.exists(self.chat_count_cfg_file):
                self._chat_count_cfg_cache = default_cfg
                self._chat_count_cfg_mtime = None
                return self._chat_count_cfg_cache

            mtime = os.path.getmtime(self.chat_count_cfg_file)
            if self._chat_count_cfg_cache is not None and self._chat_count_cfg_mtime == mtime:
                return self._chat_count_cfg_cache

            with open(self.chat_count_cfg_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            cfg = sanitize_chat_count_config(data)
            self._chat_count_cfg_cache = cfg
            self._chat_count_cfg_mtime = mtime
            return cfg
        except Exception as e:
            self.log.warning("Falha ao carregar chat_count_config: %s", e)
            return self._chat_count_cfg_cache or default_cfg

    def _should_count_chat_message(self, msg: discord.Message) -> bool:
        """Returns False for channels dedicated to voice/call chat."""
        ch = msg.channel
        if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
            return False

        cfg = self._load_chat_count_config()
        gid = str(msg.guild.id)
        channel_name = getattr(ch, "name", "") or ""
        category = getattr(ch, "category", None)
        category_name = getattr(category, "name", "") if category else ""
        return should_count_channel_message(ch.id, channel_name, category_name, gid, cfg)

    def voice_channel_counts_for_ranking(self, channel) -> bool:
        """True se o tempo neste canal de voz conta para ranking/rfixo/top (rconfig: IDs + palavras no nome do canal)."""
        if channel is None:
            return False
        cfg = self._load_chat_count_config()
        gid = str(channel.guild.id)
        channel_name = getattr(channel, "name", "") or ""
        return should_count_voice_time(channel.id, channel_name, gid, cfg)

    @staticmethod
    async def dynamic_prefix(bot, message):
        if not message.guild:
            return commands.when_mentioned_or('!')(bot, message)
        prefix = get_guild_prefix(message.guild.id)
        return commands.when_mentioned_or(prefix)(bot, message)

    def load_auto_rankings(self):
        try:
            if os.path.exists(self.auto_rankings_file):
                with open(self.auto_rankings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.auto_rankings = data
            self.log.info("Auto rankings carregados: %s", len(self.auto_rankings))
        except Exception as e:
            print(f"Failed to load auto rankings: {e}")

    def save_auto_rankings(self):
        try:
            atomic_write_json(self.auto_rankings_file, self.auto_rankings)
            self.log.info("Auto rankings salvos: %s", len(self.auto_rankings))
        except Exception as e:
            print(f"Failed to save auto rankings: {e}")

    async def setup_hook(self):
        self.tree.on_error = self.on_app_command_error
        self.load_active_sessions()
        self.load_auto_rankings()
        for folder in ["comandos", "cogs"]:
            d = f"./{folder}"
            if not os.path.exists(d):
                continue
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".py") and not fn.startswith("_"):
                    mod = f"{folder}.{fn[:-3]}"
                    try:
                        await self.load_extension(mod)
                        print(f"[OK] {mod}")
                    except Exception as e:
                        print(f"[ERRO] {mod}: {e}")
        print("Cogs loaded.")

    async def on_app_command_error(self, interaction: discord.Interaction, error: Exception):
        from discord import app_commands
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"Esse comando esta em cooldown. Tente novamente em {error.retry_after:.1f}s."
        elif isinstance(error, app_commands.MissingPermissions):
            msg = "Voce nao tem permissao para usar este comando."
        elif isinstance(error, app_commands.CheckFailure):
            msg = "Voce nao pode usar este comando."
        else:
            self.log.exception("Slash command error guild=%s user=%s cmd=%s: %s",
                               interaction.guild.id if interaction.guild else "dm",
                               interaction.user.id if interaction.user else "unknown",
                               interaction.command.name if interaction.command else "unknown",
                               error)
            msg = "Ocorreu um erro ao executar o comando."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

    async def on_ready(self):
        init()
        self.start_time = datetime.now()
        # Reconcile persisted sessions with members currently in eligible voice channels.
        from database import ensure_econ
        now = now_brazil()
        active_now = set()
        for guild in self.guilds:
            voice_like = list(guild.voice_channels)
            if hasattr(guild, "stage_channels"):
                voice_like.extend(guild.stage_channels)
            for vc in voice_like:
                if not self.voice_channel_counts_for_ranking(vc):
                    continue
                for member in vc.members:
                    if member.bot:
                        continue
                    sk = self._session_key(guild.id, member.id)
                    active_now.add(sk)
                    if sk not in self.active_sessions:
                        self.active_sessions[sk] = now
                    ensure_econ(guild.id, member.id)
        if self.active_sessions:
            stale = [sk for sk in self.active_sessions.keys() if sk not in active_now]
            for sk in stale:
                self.active_sessions.pop(sk, None)
        self.save_active_sessions()
        if not self.voice_coin_task.is_running():
            self.voice_coin_task.start()
        if not self.auto_ranking_task.is_running():
            self.auto_ranking_task.start()
        if not self.db_maint_task.is_running():
            self.db_maint_task.start()
        print(f"Bot online -> {self.user} | Hybrid commands active")
        for cmd in self.walk_commands():
            print(f"  {cmd.qualified_name}")
        # Sync slash commands (with retry for Discord 503s)
        from discord import DiscordServerError
        retries = 3
        for attempt in range(retries):
            try:
                await self.tree.sync()
                for g in self.guilds:
                    await self.tree.sync(guild=g)
                    print(f"Tree synced: {g.name}")
                print("All trees synced.")
                break
            except DiscordServerError:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    print(f"Discord 503 during sync, retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    print("Failed to sync trees after retries — commands may be out of date.")

    async def on_message(self, msg):
        if msg.author.bot or not msg.guild:
            return
        await self.process_commands(msg)
        try:
            from database import bump_msg, ensure_econ
            if self._should_count_chat_message(msg):
                bump_msg(msg.guild.id, msg.author.id)
            ensure_econ(msg.guild.id, msg.author.id)
        except Exception as e:
            self.log.warning("Falha em on_message stats guild=%s user=%s: %s", msg.guild.id, msg.author.id, e)

    async def on_interaction(self, interaction: discord.Interaction):
        """Bloqueia slash commands desativados individualmente."""
        if interaction.type != discord.InteractionType.application_command:
            return
        if not interaction.guild:
            return
        cmd_name = interaction.command.name if interaction.command else ''
        module = command_module(cmd_name)
        if module and not is_module_enabled(interaction.guild.id, module):
            e = discord.Embed(
                title="Modulo Desativado",
                description=f"O modulo **{module}** esta desativado neste servidor.",
                color=0xf87171,
            )
            await interaction.response.send_message(embed=e, ephemeral=True)
            return
        allowed = {
            'antinuke', 'antinuke_status',
            'slowmode', 'anuncio', 'nick',
            'painel_econ', 'ver_econ',
            'help', 'backup_server', 'restore_server',
            'adivinhe_anime',
        }
        if cmd_name in allowed:
            return

        # Check slash toggle config
        cfg_file = 'data/server_config.json'
        try:
            if not os.path.exists(cfg_file):
                return
            with open(cfg_file, 'r') as f:
                cfg = json.load(f)
            gid = str(interaction.guild.id)
            slash_cfg = cfg.get(gid, {}).get('slash_cmds', {})
            enabled = slash_cfg.get(cmd_name, True)  # default ON
            if not enabled:
                prefix = get_guild_prefix(interaction.guild.id)
                e = discord.Embed(
                    title="Slash Desativado",
                    description=f"O comando `/{cmd_name}` esta com slash desativado.\n"
                                f"Use `{prefix}{cmd_name}` no chat.",
                    color=0xfbbf24)
                await interaction.response.send_message(embed=e, ephemeral=True)
        except Exception as e:
            self.log.warning("Falha ao validar slash config guild=%s: %s", interaction.guild.id if interaction.guild else "none", e)

    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        from utils import now_brazil
        from database import add_voice, ensure_econ
        sk = self._session_key(member.guild.id, member.id)
        cfg = self._load_chat_count_config()
        gid = str(member.guild.id)

        def ch_counts(ch):
            if ch is None:
                return False
            name = getattr(ch, "name", "") or ""
            return should_count_voice_time(ch.id, name, gid, cfg)

        def finalize_session():
            jt = self.active_sessions.pop(sk, None)
            if not jt:
                return
            dur = int((now_brazil() - jt).total_seconds())
            if dur > 0:
                add_voice(member.guild.id, member.id, dur, jt)
            self.save_active_sessions()

        def discard_session():
            if self.active_sessions.pop(sk, None) is not None:
                self.save_active_sessions()

        b, a = before.channel, after.channel

        if b is None and a is not None:
            if ch_counts(a):
                self.active_sessions[sk] = now_brazil()
                self.save_active_sessions()
            else:
                discard_session()
            ensure_econ(member.guild.id, member.id)
            return

        if b is not None and a is None:
            if ch_counts(b):
                finalize_session()
            else:
                discard_session()
            return

        if b is not None and a is not None and b != a:
            bc, ac = ch_counts(b), ch_counts(a)
            if bc and not ac:
                finalize_session()
            elif not bc and ac:
                self.active_sessions[sk] = now_brazil()
                self.save_active_sessions()
            elif not bc and not ac:
                discard_session()
            return

    def get_current_voice_time(self, guild_id, user_id):
        session_start = self.get_active_session_start(guild_id, user_id)
        if not session_start:
            return 0
        g = self.get_guild(guild_id)
        m = g.get_member(user_id) if g else None
        if m and m.voice and m.voice.channel and not self.voice_channel_counts_for_ranking(m.voice.channel):
            return 0
        from utils import now_brazil, ensure_aware
        session_start = ensure_aware(session_start)
        return int((now_brazil() - session_start).total_seconds())

    @tasks.loop(seconds=120)
    async def voice_coin_task(self):
        """ToT com intervalo configuravel no painel de economia."""
        from database import add_coins, get_econ, set_daily_coins
        from utils import now_brazil
        cfg_file = 'data/econ_config.json'
        cfg = {"tot_per_min": 2, "payout_interval_sec": 120, "speed_multipliers": {}, "time_multipliers": {}}
        if os.path.exists(cfg_file):
            try:
                with open(cfg_file, 'r') as f:
                    cfg = json.load(f)
            except Exception:
                pass
        base = cfg.get("tot_per_min", 2)
        interval = int(cfg.get("payout_interval_sec", 120))
        interval = max(30, min(1800, interval))
        if int(self.voice_coin_task.seconds or 120) != interval:
            self.voice_coin_task.change_interval(seconds=interval)
        speed_mults = cfg.get("speed_multipliers", {})
        now_str = now_brazil().strftime('%Y-%m-%d')
        for gid, uid, _started in self.iter_active_sessions():
            g = self.get_guild(gid)
            if not g:
                continue
            m = g.get_member(uid)
            if m and m.voice and m.voice.channel and self.voice_channel_counts_for_ranking(m.voice.channel):
                smult = speed_mults.get(str(uid), 1.0)
                coins = max(1, int(base * (interval / 60) * smult))
                add_coins(g.id, uid, coins)
                ec = get_econ(g.id, uid)
                if ec:
                    set_daily_coins(g.id, uid, (ec[3] or 0) + coins, now_str)

    @voice_coin_task.before_loop
    async def _vc_before(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def auto_ranking_task(self):
        from cogs._views import RankingView, CfixoView
        from cogs.admin_econ import load_config
        for key, info in list(self.auto_rankings.items()):
            try:
                guild_id = int(info.get('guild_id', 0))
                channel_id = int(info['channel_id'])
                guild = self.get_guild(guild_id) if guild_id else None
                ch = None
                if guild:
                    ch = guild.get_channel(channel_id)
                if not ch:
                    ch = self.get_channel(channel_id)
                if not ch:
                    try:
                        fetched = await self.fetch_channel(channel_id)
                        if isinstance(fetched, discord.abc.Messageable):
                            ch = fetched
                    except discord.NotFound:
                        self.log.warning("Auto-rank removido (canal nao encontrado): %s", key)
                        del self.auto_rankings[key]
                        self.save_auto_rankings()
                        continue
                    except discord.Forbidden:
                        self.log.warning("Auto-rank sem permissao no canal (mantido): %s", key)
                        continue
                    except discord.HTTPException as http_error:
                        self.log.warning("Auto-rank falha ao buscar canal %s: HTTP %s", channel_id, http_error.status)
                        continue
                if not ch:
                    # Canal ainda nao acessivel/cached: mantem configuracao para proxima tentativa.
                    continue
                msg = None
                for attempt in range(3):
                    try:
                        msg = await ch.fetch_message(info['message_id'])
                        break
                    except discord.HTTPException as http_error:
                        if http_error.status in (500, 502, 503, 504) and attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        raise
                if info.get('view_type') == 'cfixo':
                    view = CfixoView(self, ch.guild)
                else:
                    view = RankingView(self, ch.guild)
                embed, file = view._render()
                for attempt in range(3):
                    try:
                        await msg.edit(embed=embed, attachments=[file], view=view)
                        break
                    except discord.HTTPException as http_error:
                        if http_error.status in (500, 502, 503, 504) and attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        raise
                if not info.get('view_type'):
                    await self._sync_rank_roles_for_guild(ch.guild, load_config())
            except discord.NotFound:
                del self.auto_rankings[key]
                self.save_auto_rankings()
            except discord.HTTPException as e:
                if e.status in (500, 502, 503, 504):
                    print(f"Auto-rank temporary HTTP {e.status}: {e}")
                else:
                    print(f"Auto-rank HTTP error {e.status}: {e}")
            except Exception as e:
                print(f"Auto-rank error: {e}")

    @auto_ranking_task.before_loop
    async def _ar_before(self):
        await self.wait_until_ready()

    async def _sync_rank_roles_for_guild(self, guild, config):
        rank_role_ids = config.get("rank_role_ids", {})
        configured = {
            1: rank_role_ids.get("top1"),
            2: rank_role_ids.get("top2"),
            3: rank_role_ids.get("top3"),
        }
        if not any(configured.values()):
            return

        ranking = []
        try:
            from database import get_voice_totals
            now = now_brazil()
            ranking = get_voice_totals(guild.id)
            for _gid, uid, jt in self.iter_active_sessions(guild.id):
                member = guild.get_member(uid)
                if member and member.voice and member.voice.channel and self.voice_channel_counts_for_ranking(member.voice.channel):
                    cur = int((now - ensure_aware(jt)).total_seconds())
                    found = False
                    for idx, (u2, v2) in enumerate(ranking):
                        if u2 == uid:
                            ranking[idx] = (u2, v2 + cur)
                            found = True
                            break
                    if not found:
                        ranking.append((uid, cur))
            ranking.sort(key=lambda x: x[1], reverse=True)
            top_members = {idx: guild.get_member(uid) for idx, (uid, _) in enumerate(ranking[:3], start=1)}
        except Exception as e:
            self.log.warning("Falha ao sincronizar ranking de cargos guild=%s: %s", guild.id, e)
            return

        managed_role_ids = {rid for rid in configured.values() if rid}
        if not managed_role_ids:
            return

        target_map = {configured[pos]: member for pos, member in top_members.items() if configured.get(pos)}

        for role_id in managed_role_ids:
            role = guild.get_role(role_id)
            if role is None:
                continue

            target_member = target_map.get(role_id)
            for member in list(role.members):
                if target_member is None or member.id != target_member.id:
                    try:
                        await member.remove_roles(role, reason="Atualizacao automatica do ranking fixo")
                    except Exception:
                        pass

            if target_member and role not in target_member.roles:
                try:
                    await target_member.add_roles(role, reason="Posicao atual no ranking fixo")
                except Exception:
                    pass

    @tasks.loop(seconds=21600)  # 6h
    async def db_maint_task(self):
        cleanup_old()
        vacuum()
        print("[DB] Maintenance done.")

    @db_maint_task.before_loop
    async def _dbm_before(self):
        await self.wait_until_ready()
bot = Bot()


@bot.check
async def _module_check(ctx):
    if not ctx.guild or not ctx.command:
        return True
    mod = command_module(ctx.command.name)
    if mod and not is_module_enabled(ctx.guild.id, mod):
        await ctx.send(f"O modulo **{mod}** esta desativado neste servidor.")
        return False
    return True


def start_web_panel():
    port = int(os.environ.get("PORT", os.environ.get("WEB_PORT", "8080")))

    def _start_stdlib_fallback(reason: str):
        class _FallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = (
                    "<html><body style='font-family:Arial,sans-serif;padding:24px;'>"
                    "<h2>Bot Primal Web Fallback</h2>"
                    "<p>O painel principal nao inicializou, mas o host HTTP esta ativo.</p>"
                    f"<p><b>Erro:</b> {reason}</p>"
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                return

        def _run():
            try:
                srv = HTTPServer(("0.0.0.0", port), _FallbackHandler)
                print(f"[WEB] Stdlib fallback listening on 0.0.0.0:{port}")
                srv.serve_forever()
            except Exception as e:
                print(f"[WEB] Stdlib fallback failed: {e}")

        threading.Thread(target=_run, daemon=True).start()

    if os.environ.get("WEB_PANEL_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return
    try:
        import uvicorn
        from web_panel import create_app
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, HTMLResponse
    except Exception as e:
        print(f"[WEB] Import error, using stdlib fallback: {e}")
        _start_stdlib_fallback(str(e))
        return

    try:
        app = create_app(bot)
    except Exception as e:
        print(f"[WEB] App init error, starting fallback panel: {e}")
        fallback = FastAPI(title="Bot Primal Web Fallback")

        @fallback.get("/health")
        async def _health():
            return JSONResponse({"ok": False, "fallback": True, "error": str(e)})

        @fallback.get("/", response_class=HTMLResponse)
        async def _home():
            return (
                "<html><body style='font-family:Arial,sans-serif;padding:24px;'>"
                "<h2>Painel em modo de fallback</h2>"
                "<p>O painel principal nao inicializou. Verifique os logs do bot para o erro detalhado.</p>"
                "<p>O bot principal continua online.</p>"
                "</body></html>"
            )

        app = fallback

    def _run():
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    print(f"[WEB] Panel listening on 0.0.0.0:{port}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.NotOwner):
        await ctx.send("Voce nao tem permissao.")
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("Voce nao tem permissao para usar este comando.")
        return
    print(f"Command error: {ctx.command} -> {error}")

start_web_panel()
bot.run(TOKEN)
