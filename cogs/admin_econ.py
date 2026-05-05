import discord
from discord import app_commands, ui
from discord.ext import commands
import json
import os
from datetime import datetime
import pytz
from auth import is_admin
from json_utils import atomic_write_json

CONFIG_FILE = 'data/econ_config.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                if not isinstance(cfg, dict):
                    cfg = {}
                cfg.setdefault("tot_per_min", 2)
                cfg.setdefault("payout_interval_sec", 120)
                cfg.setdefault("speed_multipliers", {})
                cfg.setdefault("time_multipliers", {})
                cfg.setdefault("rank_role_ids", {"top1": None, "top2": None, "top3": None})
                return cfg
        except Exception:
            pass
    return {
        "tot_per_min": 2,
        "payout_interval_sec": 120,
        "speed_multipliers": {},
        "time_multipliers": {},
        "rank_role_ids": {"top1": None, "top2": None, "top3": None},
    }


def save_config(cfg):
    atomic_write_json(CONFIG_FILE, cfg)

def fmt_sec(s):
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"

def check_perm(uid):
    return is_admin(uid)

def build_embed(cfg, bot):
    tot = cfg.get("tot_per_min", 2)
    payout_interval_sec = int(cfg.get("payout_interval_sec", 120))
    speed_mults = cfg.get("speed_multipliers", {})
    time_mults = cfg.get("time_multipliers", {})
    rank_role_ids = cfg.get("rank_role_ids", {})
    ciclo = tot * (payout_interval_sec / 60)

    # Speed lines
    slines = []
    if speed_mults:
        for uid_s, m in sorted(speed_mults.items(), key=lambda x: x[1], reverse=True):
            eff = tot * m
            slines.append(f"<@{uid_s}> → **{m}x** ({eff:.1f} ToT/min)")
        speed_txt = "\n".join(slines[:10])
        if len(slines) > 10:
            speed_txt += f"\n...e mais {len(slines) - 10}"
    else:
        speed_txt = "Nenhum personalizado (todos 1x)"

    # Time lines
    tlines = []
    if time_mults:
        for uid_s, m in sorted(time_mults.items(), key=lambda x: x[1], reverse=True):
            eff = payout_interval_sec * m
            tlines.append(f"<@{uid_s}> → **{m}x** ({eff:.0f}s reais contam p/ ranking)")
        time_txt = "\n".join(tlines[:10])
        if len(tlines) > 10:
            time_txt += f"\n...e mais {len(tlines) - 10}"
    else:
        time_txt = "Nenhum personalizado (todos 1x)"

    e = discord.Embed(title="Painel de Economia ToT", color=0xeab308)
    e.add_field(
        name="Taxa Base",
        value=(
            f"**{tot} ToT/min**\n"
            f"Intervalo de ganho: **{payout_interval_sec}s**\n"
            f"ToT por ciclo: **{ciclo:.2f}**"
        ),
        inline=False,
    )
    e.add_field(name="Multiplicadores de ToT (Veloc.)", value=speed_txt, inline=False)
    e.add_field(name="Multiplicadores de Tempo (Voz)", value=time_txt, inline=False)
    top1_role = f"<@&{rank_role_ids.get('top1')}>" if rank_role_ids.get("top1") else "Nao definido"
    top2_role = f"<@&{rank_role_ids.get('top2')}>" if rank_role_ids.get("top2") else "Nao definido"
    top3_role = f"<@&{rank_role_ids.get('top3')}>" if rank_role_ids.get("top3") else "Nao definido"
    e.add_field(
        name="Cargos do Ranking Fixo",
        value=(
            "Baseado somente na pagina 1 do `rfixo`.\n"
            f"Top 1: {top1_role}\n"
            f"Top 2: {top2_role}\n"
            f"Top 3: {top3_role}"
        ),
        inline=False
    )

    # Quem esta em call
    in_call = []
    for gid, uid, started_at in bot.iter_active_sessions():
        g = bot.get_guild(gid)
        if not g:
            continue
        m = g.get_member(uid)
        if m and m.voice and m.voice.channel and bot.voice_channel_counts_for_ranking(m.voice.channel):
            smult = speed_mults.get(str(uid), 1.0)
            tmult = time_mults.get(str(uid), 1.0)
            eff_tot = tot * smult
            now_aware = datetime.now(pytz.timezone('America/Sao_Paulo'))
            elapsed = (now_aware - started_at).total_seconds()
            eff_voz = elapsed * tmult
            in_call.append(f"{m.mention} — ToT **{smult}x** ({eff_tot:.1f}/min) — Voz **{tmult}x** ({fmt_sec(eff_voz)})")

    if in_call:
        e.add_field(name=f"Em Call ({len(in_call)})", value="\n".join(in_call[:6]) + (f"\n...+{len(in_call)-6}" if len(in_call) > 6 else ""), inline=False)

    e.set_footer(text="Use os menus abaixo para modificar")
    return e

# ============ MODALS ============
class SetTotModal(ui.Modal, title="Definir ToT por Minuto"):
    rate = ui.TextInput(
        label="ToT por minuto (ex: 5)",
        placeholder="Quantos ToT cada pessoa ganha por minuto em call",
        style=discord.TextStyle.short, required=True
    )

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.rate.default = str(config.get("tot_per_min", 2))

    async def on_submit(self, ix: discord.Interaction):
        try:
            v = float(self.rate.value)
            if v < 0:
                return await ix.response.send_message("Valor nao pode ser negativo.", ephemeral=True)
        except ValueError:
            return await ix.response.send_message("Numero invalido.", ephemeral=True)
        self.config["tot_per_min"] = round(v, 2)
        save_config(self.config)
        interval = int(self.config.get("payout_interval_sec", 120))
        payout = self.config["tot_per_min"] * (interval / 60)
        e = discord.Embed(
            title="Taxa Atualizada",
            description=(
                f"Nova taxa: **{self.config['tot_per_min']} ToT/min**\n"
                f"A cada ciclo ({interval}s): **{payout:.2f} ToT**"
            ),
            color=0x22c55e)
        await ix.response.send_message(embed=e, ephemeral=True)


class SetVelocModal(ui.Modal, title="Definir Velocidade de Voz"):
    mult_val = ui.TextInput(
        label="Multiplicador (ex: 2.0 = 2x)",
        placeholder="Ex: 2.0 = ganha em dobro, 0.5 = metade",
        style=discord.TextStyle.short, required=True
    )

    def __init__(self, config, uid, username):
        super().__init__()
        self.config = config
        self.uid = uid
        self.username = username
        current = config.get("speed_multipliers", {}).get(str(uid))
        self.mult_val.default = str(current) if current else ""

    async def on_submit(self, ix: discord.Interaction):
        try:
            v = float(self.mult_val.value)
            if v <= 0:
                return await ix.response.send_message("Multiplicador deve ser positivo.", ephemeral=True)
        except ValueError:
            return await ix.response.send_message("Numero invalido.", ephemeral=True)

        uid_s = str(self.uid)
        if v == 1.0:
            self.config["speed_multipliers"].pop(uid_s, None)
            e = discord.Embed(
                title="Velocidade Removida",
                description=f"**{self.username}** volta para **1x** (normal)",
                color=0xeab308)
        else:
            self.config["speed_multipliers"][uid_s] = v
            eff = self.config["tot_per_min"] * v
            e = discord.Embed(
                title="Velocidade Definida",
                description=f"**{self.username}** → **{v}x**\nEquivale a **{eff:.1f} ToT/min**",
                color=0x22c55e)
        save_config(self.config)
        await ix.response.send_message(embed=e, ephemeral=True)


class AddUserVelocModal(ui.Modal, title="Adicionar Usuario com Velocidade"):
    uid_input = ui.TextInput(
        label="ID do usuario (apenas numeros)",
        placeholder="Ex: 123456789",
        style=discord.TextStyle.short, required=True
    )
    mult_val = ui.TextInput(
        label="Multiplicador (ex: 2.0 = 2x)",
        placeholder="Ex: 2.0, 3.5, 0.5",
        style=discord.TextStyle.short, required=True
    )

    async def on_submit(self, ix: discord.Interaction):
        try:
            uid = int(self.uid_input.value)
        except ValueError:
            return await ix.response.send_message("ID invalido. Use apenas numeros.", ephemeral=True)
        try:
            v = float(self.mult_val.value)
            if v <= 0:
                return await ix.response.send_message("Multiplicador deve ser positivo.", ephemeral=True)
        except ValueError:
            return await ix.response.send_message("Numero invalido.", ephemeral=True)

        config = load_config()
        member = ix.guild.get_member(uid)
        name = member.mention if member else f"<@{uid}>"

        if v == 1.0:
            config["speed_multipliers"].pop(str(uid), None)
            e = discord.Embed(title="Removido", description=f"{name} volta a **1x**", color=0xeab308)
        else:
            config["speed_multipliers"][str(uid)] = v
            eff = config["tot_per_min"] * v
            e = discord.Embed(
                title="Velocidade Adicionada",
                description=f"{name} → **{v}x** = **{eff:.1f} ToT/min**",
                color=0x22c55e)
        save_config(config)
        await ix.response.send_message(embed=e, ephemeral=True)


class RemoveVelocModal(ui.Modal, title="Remover Velocidade de Usuario"):
    uid_input = ui.TextInput(
        label="ID do usuario",
        placeholder="Ex: 123456789",
        style=discord.TextStyle.short, required=True
    )

    async def on_submit(self, ix: discord.Interaction):
        try:
            uid = int(self.uid_input.value)
        except ValueError:
            return await ix.response.send_message("ID invalido. Use apenas numeros.", ephemeral=True)

        config = load_config()
        uid_s = str(uid)
        member = ix.guild.get_member(uid)
        name = member.mention if member else f"<@{uid}>"

        if uid_s in config.get("speed_multipliers", {}):
            del config["speed_multipliers"][uid_s]
            save_config(config)
            e = discord.Embed(title="Removido", description=f"{name} volta a **1x** (normal)", color=0xeab308)
        else:
            e = discord.Embed(description=f"{name} ja esta em **1x** (sem multiplicador).", color=0x95A5A6)
        await ix.response.send_message(embed=e, ephemeral=True)


# --- TIME MULTIPLIER modals ---
class AddUserTimeModal(ui.Modal, title="Adicionar Multiplicador de Tempo"):
    uid_input = ui.TextInput(
        label="ID do usuario (apenas numeros)",
        placeholder="Ex: 123456789",
        style=discord.TextStyle.short, required=True
    )
    mult_val = ui.TextInput(
        label="Multiplicador tempo (ex: 2.0 = 2x)",
        placeholder="Ex: 2.0, 3.5, 0.5",
        style=discord.TextStyle.short, required=True
    )

    async def on_submit(self, ix: discord.Interaction):
        try:
            uid = int(self.uid_input.value)
        except ValueError:
            return await ix.response.send_message("ID invalido. Use apenas numeros.", ephemeral=True)
        try:
            v = float(self.mult_val.value)
            if v <= 0:
                return await ix.response.send_message("Multiplicador deve ser positivo.", ephemeral=True)
        except ValueError:
            return await ix.response.send_message("Numero invalido.", ephemeral=True)

        config = load_config()
        member = ix.guild.get_member(uid)
        name = member.mention if member else f"<@{uid}>"

        if v == 1.0:
            config["time_multipliers"].pop(str(uid), None)
            e = discord.Embed(title="Removido", description=f"{name} volta a **1x** tempo", color=0xeab308)
        else:
            config["time_multipliers"][str(uid)] = v
            eff = 120 * v
            e = discord.Embed(
                title="Tempo Adicionado",
                description=f"{name} → tempo **{v}x**\n{fmt_sec(120)} reais contam como **{fmt_sec(eff)}** no ranking",
                color=0x3498DB)
        save_config(config)
        await ix.response.send_message(embed=e, ephemeral=True)


class RemoveTimeModal(ui.Modal, title="Remover Multiplicador de Tempo"):
    uid_input = ui.TextInput(
        label="ID do usuario",
        placeholder="Ex: 123456789",
        style=discord.TextStyle.short, required=True
    )

    async def on_submit(self, ix: discord.Interaction):
        try:
            uid = int(self.uid_input.value)
        except ValueError:
            return await ix.response.send_message("ID invalido. Use apenas numeros.", ephemeral=True)

        config = load_config()
        uid_s = str(uid)
        member = ix.guild.get_member(uid)
        name = member.mention if member else f"<@{uid}>"

        if uid_s in config.get("time_multipliers", {}):
            del config["time_multipliers"][uid_s]
            save_config(config)
            e = discord.Embed(title="Removido", description=f"{name} volta a **1x** tempo", color=0x3498DB)
        else:
            e = discord.Embed(description=f"{name} ja esta em **1x** tempo.", color=0x95A5A6)
        await ix.response.send_message(embed=e, ephemeral=True)


class SetTotDirectModal(ui.Modal, title="Definir ToT Direto"):
    rate = ui.TextInput(
        label="Taxa ToT/min (substitui o valor atual)",
        placeholder="Ex: 10",
        style=discord.TextStyle.short, required=True
    )

    async def on_submit(self, ix: discord.Interaction):
        try:
            v = float(self.rate.value)
            if v < 0:
                return await ix.response.send_message("Nao pode ser negativo.", ephemeral=True)
        except ValueError:
            return await ix.response.send_message("Numero invalido.", ephemeral=True)

        config = load_config()
        config["tot_per_min"] = round(v, 2)
        save_config(config)
        interval = int(config.get("payout_interval_sec", 120))
        payout = config["tot_per_min"] * (interval / 60)
        e = discord.Embed(
            title="Taxa Definida",
            description=(
                f"Taxa agora: **{config['tot_per_min']} ToT/min**\n"
                f"A cada ciclo ({interval}s): **{payout:.2f} ToT**"
            ),
            color=0x22c55e)
        await ix.response.send_message(embed=e, ephemeral=True)


class SetPayoutIntervalModal(ui.Modal, title="Intervalo de Ganho"):
    interval = ui.TextInput(
        label="Intervalo (segundos)",
        placeholder="Ex: 120",
        style=discord.TextStyle.short,
        required=True,
    )

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.interval.default = str(config.get("payout_interval_sec", 120))

    async def on_submit(self, ix: discord.Interaction):
        try:
            seconds = int(self.interval.value)
        except ValueError:
            return await ix.response.send_message("Numero invalido. Use apenas segundos inteiros.", ephemeral=True)

        if seconds < 30 or seconds > 1800:
            return await ix.response.send_message("Use um intervalo entre 30 e 1800 segundos.", ephemeral=True)

        self.config["payout_interval_sec"] = seconds
        save_config(self.config)
        tot_per_cycle = self.config.get("tot_per_min", 2) * (seconds / 60)
        e = discord.Embed(
            title="Intervalo atualizado",
            description=(
                f"Novo intervalo: **{seconds}s**\n"
                f"Com taxa atual, cada ciclo paga **{tot_per_cycle:.2f} ToT**."
            ),
            color=0x22c55e,
        )
        await ix.response.send_message(embed=e, ephemeral=True)


class SetRankRolesModal(ui.Modal, title="Configurar Cargos do Ranking"):
    top1_role_id = ui.TextInput(
        label="ID do cargo Top 1",
        placeholder="Deixe vazio para desativar",
        style=discord.TextStyle.short,
        required=False
    )
    top2_role_id = ui.TextInput(
        label="ID do cargo Top 2",
        placeholder="Deixe vazio para desativar",
        style=discord.TextStyle.short,
        required=False
    )
    top3_role_id = ui.TextInput(
        label="ID do cargo Top 3",
        placeholder="Deixe vazio para desativar",
        style=discord.TextStyle.short,
        required=False
    )

    def __init__(self, config):
        super().__init__()
        self.config = config
        rank_role_ids = config.get("rank_role_ids", {})
        self.top1_role_id.default = str(rank_role_ids.get("top1") or "")
        self.top2_role_id.default = str(rank_role_ids.get("top2") or "")
        self.top3_role_id.default = str(rank_role_ids.get("top3") or "")

    def _parse_role_id(self, raw_value):
        value = (raw_value or "").strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            raise ValueError("Use apenas IDs numericos dos cargos.")

    async def on_submit(self, ix: discord.Interaction):
        try:
            top1 = self._parse_role_id(self.top1_role_id.value)
            top2 = self._parse_role_id(self.top2_role_id.value)
            top3 = self._parse_role_id(self.top3_role_id.value)
        except ValueError as exc:
            return await ix.response.send_message(str(exc), ephemeral=True)

        role_ids = [rid for rid in (top1, top2, top3) if rid]
        if len(role_ids) != len(set(role_ids)):
            return await ix.response.send_message("Os cargos de top 1, 2 e 3 precisam ser diferentes.", ephemeral=True)

        missing_roles = [rid for rid in role_ids if ix.guild.get_role(rid) is None]
        if missing_roles:
            return await ix.response.send_message(
                f"Nao encontrei estes cargos no servidor: {', '.join(str(rid) for rid in missing_roles)}",
                ephemeral=True
            )

        self.config["rank_role_ids"] = {"top1": top1, "top2": top2, "top3": top3}
        save_config(self.config)
        desc = (
            "Os cargos serao atualizados automaticamente usando apenas a pagina 1 do `rfixo`.\n"
            f"Top 1: {f'<@&{top1}>' if top1 else 'Desativado'}\n"
            f"Top 2: {f'<@&{top2}>' if top2 else 'Desativado'}\n"
            f"Top 3: {f'<@&{top3}>' if top3 else 'Desativado'}"
        )
        e = discord.Embed(title="Cargos do ranking atualizados", description=desc, color=0x22c55e)
        await ix.response.send_message(embed=e, ephemeral=True)


# ============ SELECT MENUS ============
class TotSelectMenu(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Definir Taxa", description="Defina quanto ToT/min direto", emoji="💎", value="set_tot"),
            discord.SelectOption(label="Intervalo de Ganho", description="Defina de quanto em quanto tempo paga", emoji="⏱️", value="set_interval"),
            discord.SelectOption(label="Adicionar ToT", description="Adiciona X a taxa atual", emoji="➕", value="add_tot"),
            discord.SelectOption(label="Remover ToT", description="Remove X da taxa atual", emoji="➖", value="rm_tot"),
            discord.SelectOption(label="Resetar Taxa", description="Volta para 2 ToT/min", emoji="🔄", value="reset_tot"),
        ]
        super().__init__(placeholder="Selecione acao de ToT...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, ix: discord.Interaction):
        if not check_perm(ix.user.id):
            return await ix.response.send_message("Sem permissao.", ephemeral=True)
        config = load_config()
        val = self.values[0]

        if val == "set_tot":
            await ix.response.send_modal(SetTotDirectModal())
        elif val == "set_interval":
            await ix.response.send_modal(SetPayoutIntervalModal(config))
        elif val == "add_tot":
            await ix.response.send_modal(AddSubTotModal(config, "add"))
        elif val == "rm_tot":
            await ix.response.send_modal(AddSubTotModal(config, "rm"))
        elif val == "reset_tot":
            config["tot_per_min"] = 2
            save_config(config)
            e = discord.Embed(title="Taxa Resetada", description="Volta para **2 ToT/min**.", color=0x22c55e)
            await ix.response.send_message(embed=e, ephemeral=True)


class AddSubTotModal(ui.Modal):
    value = ui.TextInput(
        label="Quantidade",
        placeholder="Ex: 5",
        style=discord.TextStyle.short, required=True
    )

    def __init__(self, config, action):
        title = "Adicionar ToT/min" if action == "add" else "Remover ToT/min"
        super().__init__(title=title)
        self.config = config
        self.action = action

    async def on_submit(self, ix: discord.Interaction):
        try:
            v = float(self.value.value)
            if v < 0:
                return await ix.response.send_message("Nao pode ser negativo.", ephemeral=True)
        except ValueError:
            return await ix.response.send_message("Numero invalido.", ephemeral=True)

        cur = self.config["tot_per_min"]
        if self.action == "add":
            self.config["tot_per_min"] = round(cur + v, 2)
        else:
            self.config["tot_per_min"] = round(max(0, cur - v), 2)
        save_config(self.config)
        interval = int(self.config.get("payout_interval_sec", 120))
        payout = self.config["tot_per_min"] * (interval / 60)
        e = discord.Embed(
            title="Taxa Atualizada",
            description=(
                f"Nova taxa: **{self.config['tot_per_min']} ToT/min**\n"
                f"A cada ciclo ({interval}s): **{payout:.2f} ToT**"
            ),
            color=0x22c55e)
        await ix.response.send_message(embed=e, ephemeral=True)


class VelocSelectMenu(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Adicionar Usuario", description="Define multiplicador p/ usuario", emoji="⚡", value="add_user"),
            discord.SelectOption(label="Remover Usuario", description="Remove multiplicador do usuario", emoji="🐌", value="rm_user"),
            discord.SelectOption(label="Resetar Todos", description="Remove todos multiplicadores", emoji="💥", value="reset_all"),
            discord.SelectOption(label="Ver Todos", description="Lista todos com multiplicador", emoji="📋", value="list_all"),
        ]
        super().__init__(placeholder="Selecione acao de Velocidade...", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, ix: discord.Interaction):
        if not check_perm(ix.user.id):
            return await ix.response.send_message("Sem permissao.", ephemeral=True)
        val = self.values[0]

        if val == "add_user":
            await ix.response.send_modal(AddUserVelocModal())
        elif val == "rm_user":
            await ix.response.send_modal(RemoveVelocModal())
        elif val == "reset_all":
            config = load_config()
            config["speed_multipliers"] = {}
            save_config(config)
            e = discord.Embed(title="Velocidades Resetadas", description="Todos voltam a **1x**.", color=0x22c55e)
            await ix.response.send_message(embed=e, ephemeral=True)
        elif val == "list_all":
            config = load_config()
            mults = config.get("speed_multipliers", {})
            if not mults:
                return await ix.response.send_message("Nenhum multiplicador definido.", ephemeral=True)
            txt = ""
            for uid_s, m in sorted(mults.items(), key=lambda x: x[1], reverse=True):
                eff = config["tot_per_min"] * m
                txt += f"<@{uid_s}> → **{m}x** = {eff:.1f} ToT/min\n"
            e = discord.Embed(title="Multiplicadores Ativos", description=txt, color=0xeab308)
            await ix.response.send_message(embed=e, ephemeral=True)


class TimeSelectMenu(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Adicionar Usuario", description="Define multiplicador de tempo", emoji="⏩", value="add_time"),
            discord.SelectOption(label="Remover Usuario", description="Remove multiplicador de tempo", emoji="⏪", value="rm_time"),
            discord.SelectOption(label="Resetar Todos", description="Remove todos mult. de tempo", emoji="💥", value="reset_time"),
            discord.SelectOption(label="Ver Todos", description="Lista todos com mult. tempo", emoji="📋", value="list_time"),
        ]
        super().__init__(placeholder="Selecione acao de Tempo...", min_values=1, max_values=1, options=options, row=2)

    async def callback(self, ix: discord.Interaction):
        if not check_perm(ix.user.id):
            return await ix.response.send_message("Sem permissao.", ephemeral=True)
        val = self.values[0]

        if val == "add_time":
            await ix.response.send_modal(AddUserTimeModal())
        elif val == "rm_time":
            await ix.response.send_modal(RemoveTimeModal())
        elif val == "reset_time":
            config = load_config()
            config["time_multipliers"] = {}
            save_config(config)
            e = discord.Embed(title="Tempo Resetado", description="Todos voltam a **1x** tempo.", color=0x3498DB)
            await ix.response.send_message(embed=e, ephemeral=True)
        elif val == "list_time":
            config = load_config()
            tms = config.get("time_multipliers", {})
            if not tms:
                return await ix.response.send_message("Nenhum multiplicador de tempo definido.", ephemeral=True)
            txt = ""
            for uid_s, m in sorted(tms.items(), key=lambda x: x[1], reverse=True):
                interval = int(config.get("payout_interval_sec", 120))
                eff = interval * m
                txt += f"<@{uid_s}> → **{m}x** ({fmt_sec(eff)} no ranking)\n"
            e = discord.Embed(title="Multiplicadores de Tempo Ativos", description=txt, color=0x3498DB)
            await ix.response.send_message(embed=e, ephemeral=True)


class RefreshSelectMenu(ui.Select):
    def __init__(self, view):
        options = [
            discord.SelectOption(label="Configurar cargos do ranking", description="Define os cargos do top 1, 2 e 3 do rfixo", emoji="🏆", value="rank_roles"),
            discord.SelectOption(label="Atualizar Painel", description="Recarrega a embed com dados novos", emoji="🔄", value="refresh"),
            discord.SelectOption(label="Desativar Botoes", description="Desativa o painel", emoji="🔒", value="disable"),
        ]
        super().__init__(placeholder="Gerenciar painel...", min_values=1, max_values=1, options=options, row=3)
        self.view_ref = view

    async def callback(self, ix: discord.Interaction):
        if not check_perm(ix.user.id):
            return await ix.response.send_message("Sem permissao.", ephemeral=True)
        val = self.values[0]
        if val == "rank_roles":
            cfg = load_config()
            await ix.response.send_modal(SetRankRolesModal(cfg))
        elif val == "refresh":
            await ix.response.defer(ephemeral=True)
            cfg = load_config()
            e = build_embed(cfg, ix.client)
            v = self.view_ref
            v.clear_items()
            v.add_item(TotSelectMenu())
            v.add_item(VelocSelectMenu())
            v.add_item(TimeSelectMenu())
            v.add_item(RefreshSelectMenu(v))
            await ix.edit_original_response(embed=e, view=v)
            await ix.followup.send("Painel atualizado!", ephemeral=True)
        elif val == "disable":
            v = self.view_ref
            for child in v.children:
                child.disabled = True
            await ix.response.edit_message(view=v)
            await ix.followup.send("Painel desativado.", ephemeral=True)


# ============ MAIN VIEW ============
class AdminEconPanel(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(TotSelectMenu())
        self.add_item(VelocSelectMenu())
        self.add_item(TimeSelectMenu())
        self.add_item(RefreshSelectMenu(self))


# ============ COG ============
class AdminEconCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="painel_econ", description="Cria painel admin de economia ToT")
    async def painel_econ(self, interaction: discord.Interaction):
        if not check_perm(interaction.user.id):
            return await interaction.response.send_message("Apenas admins autorizados.", ephemeral=True)

        config = load_config()
        embed = build_embed(config, self.bot)
        view = AdminEconPanel(self.bot)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="ver_econ", description="Ver configs atuais de ToT")
    async def ver_econ(self, interaction: discord.Interaction):
        if not check_perm(interaction.user.id):
            return await interaction.response.send_message("Apenas admins autorizados.", ephemeral=True)

        config = load_config()
        embed = build_embed(config, self.bot)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(AdminEconCog(bot))
