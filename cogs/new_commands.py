"""New commands: reset horas, reset chats, help interativo, backup/restore servidor."""
import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime

from database import (
    reset_all_voice, reset_all_chat,
    get_voice, get_chat,
    get_all_voice, get_all_user_ids_voice, get_all_user_ids_chat,
    shared_voice_time, wipe_guild
)
from utils import fmt_time, get_member_name, now_brazil, ensure_aware
from auth import is_owner, is_admin


class HelpSelectMenu(discord.ui.Select):
    """Dropdown para selecionar categoria do help."""
    def __init__(self, user_id: int):
        self.user_id = user_id
        options = [
            discord.SelectOption(label="Comandos de Voz", description="call, profile, addhoras, rmhoras...", emoji="\U0001F3A4", value="voz"),
            discord.SelectOption(label="Comandos de Chat", description="chattop, diario, semanal, mensal...", emoji="\U0001F4AC", value="chat"),
            discord.SelectOption(label="Economia", description="saldo, addToT, rToT, painel_econ...", emoji="\U0001F4B0", value="econ"),
            discord.SelectOption(label="Rankings", description="rfixo, cfixo (rankings fixos)", emoji="\U0001F4CA", value="ranking"),
            discord.SelectOption(label="Administracao", description="reset_horas, reset_chats, reset_user...", emoji="\U0001F6E1\uFE0F", value="admin"),
            discord.SelectOption(label="Utilidade", description="enquete, sortear, anuncio, limpar...", emoji="\U0001F527", value="util"),
            discord.SelectOption(label="Relacionamento", description="ship, casar, divorcio, casamento_status", emoji="💍", value="relacionamento"),
            discord.SelectOption(label="Anti-Nuke / Anti-Link", description="antinuke, antilink, status...", emoji="\U0001F6E1\uFE0F", value="seguranca"),
            discord.SelectOption(label="Backup (Dono)", description="backup_server, restore_server...", emoji="\U0001F4BE", value="dono"),
            discord.SelectOption(label="Restrito (Dono + IDs)", description="comandos permitidos so para IDs autorizados", emoji="🔐", value="restrito"),
        ]
        super().__init__(
            placeholder="Selecione uma categoria...",
            min_values=1, max_values=1,
            options=options
        )

    async def callback(self, ix: discord.Interaction):
        cat = self.values[0]
        if cat == "restrito" and not is_admin(ix.user.id):
            return await ix.response.send_message("Voce nao pode abrir essa categoria.", ephemeral=True)
        embed = self._embed_for(cat)
        await ix.response.edit_message(embed=embed, view=self.view)

    def _embed_for(self, cat):
        colors = {
            "voz": 0xfbbf24, "chat": 0xa855f7, "econ": 0xeab308,
            "ranking": 0x3b82f6, "admin": 0xef4444, "util": 0x22c55e,
            "relacionamento": 0xf472b6, "seguranca": 0xf97316, "dono": 0xec4899, "restrito": 0x0ea5e9,
        }
        col = colors.get(cat, 0x5865f2)
        fields = {
            "voz": (
                "\U0001F3A4 Comandos de Voz",
                ("/call - Ranking de voz atual\n"
                 "/profile [membro] - Perfil de voz\n"
                 "/rfixo - Ranking fixo de voz com botoes (admin)\n"
                 "/addhoras <membro> <horas> - Adiciona horas (admin)\n"
                 "/rmhoras <membro> <horas> - Remove horas (admin)")
            ),
            "chat": (
                "\U0001F4AC Comandos de Chat",
                ("/chattop - Ranking de chat\n"
                 "/cfixo - Ranking fixo de chat com botoes (admin)\n"
                 "!diario - Resumo diario (prefix)\n"
                 "!semanal - Resumo semanal (prefix)\n"
                 "!mensal - Resumo mensal (prefix)")
            ),
            "econ": (
                "\U0001F4B0 Economia",
                ("/saldo - Ver seu saldo ToT\n"
                 "!addToT <membro> <quantia> - Adiciona ToT (admin)\n"
                 "!rToT <membro> <quantia> - Remove ToT (admin)\n"
                 "/painel_econ - Painel admin de economia\n"
                 "/ver_econ - Ver configs atuais de ToT\n"
                 "Ganhe 2 ToT a cada 2 min em call!")
            ),
            "ranking": (
                "\U0001F4CA Rankings",
                ("/rfixo - Ranking fixo de voz (voz/dia/semana/mes/total/tot)\n"
                 "/cfixo - Ranking fixo de chat (diario/semanal/mensal/total)\n"
                 "Atualizam automaticamente a cada 30s!")
            ),
            "admin": (
                "\U0001F6E1\uFE0F Administracao",
                ("/reset_horas - Reseta horas do leaderboard (ADM)\n"
                 "/reset_chats - Reseta chats do leaderboard (ADM)\n"
                 "/reset_user <membro> - Reseta dados de um usuario (ADM)\n"
                 "/reset_server - Apaga tudo do servidor (ADM)")
            ),
            "util": (
                "\U0001F527 Utilidade",
                ("/enquete - Criar enquete com reacoes\n"
                 "/sortear - Sortear membro do servidor\n"
                 "/anuncio - Enviar anuncio formatado\n"
                 "/roleinfo - Info de um cargo\n"
                 "/calculadora - Calculadora simples\n"
                 "/limpar <qtd> - Limpar mensagens do canal\n"
                 "/slowmode <segundos> - Slowmode no canal\n"
                 "/nick <membro> <nick> - Mudar nickname\n"
                 "/status - Status do bot")
            ),
            "relacionamento": (
                "💍 Relacionamento",
                ("/ship [membro] - Ship com alguem\n"
                 "/casal <membro1> <membro2> - Compatibilidade entre duas pessoas\n"
                 "/casar <parceiro> <padrinho> <madrinha> <dama_de_honra> <celebrante> - Pedido de casamento por DM\n"
                 "/divorcio [motivo] - Encerra casamento atual\n"
                 "/casamento_status [membro] - Painel com status e memorias\n"
                 "!tempcas <membro> <dias> - Ajusta dias de casados (prefix)")
            ),
            "seguranca": (
                "\U0001F6E1\uFE0F Seguranca",
                ("/antinuke - Configurar Anti-Nuke\n"
                 "/antinuke_status - Status do Anti-Nuke\n"
                 "/configurar_antilink - Configurar Anti-Link\n"
                 "/antilink_info - Info do Anti-Link")
            ),
            "dono": (
                "\U0001F4BE Backup (Apenas Dono)",
                ("/backup_server - Gera backup completo de cargos e canais\n"
                 "/restore_server - Deleta e recria cargos/canais do backup\n"
                 "Apenas o dono do bot pode usar!")
            ),
            "restrito": (
                "🔐 Restrito (Dono + IDs autorizados)",
                ("!reset_horas - Reseta horas do leaderboard\n"
                 "!reset_chats - Reseta chats do leaderboard\n"
                 "!tempcas <membro> <dias> - Ajusta tempo de casados\n"
                 "!p/!m/!d <id_pessoa> [membro_casal] - Define padrinho/madrinha/dama\n"
                 "Disponivel apenas para dono do bot e IDs autorizados.")
            ),
        }
        title, desc = fields.get(cat, ("?", "Categoria desconhecida"))
        e = discord.Embed(title=title, description=desc, color=col)
        e.set_footer(text="Use /help para voltar ao menu principal")
        return e


class HelpView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        menu = HelpSelectMenu(user_id)
        self.add_item(menu)


class NewCommandsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._backup_data = {}
        self._latest_backup_id = None

    # ============================================================
    # /help - Help interativo com categorias (SLASH)
    # ============================================================
    @app_commands.command(name='help', description='Lista de comandos com categorias')
    @app_commands.describe(cmd="Buscar comando especifico")
    async def help_cmd(self, interaction: discord.Interaction, cmd: str = None):
        if cmd:
            c = self.bot.get_command(cmd)
            if c:
                e = discord.Embed(
                    title=f"/{c.name}",
                    description=c.description or "Sem descricao.",
                    color=0x3b82f6)
                return await interaction.response.send_message(embed=e)
            return await interaction.response.send_message(f"Comando `{cmd}` nao encontrado.")

        e = discord.Embed(
            title="Central de Ajuda",
            description="Selecione uma categoria abaixo para ver os comandos.\n\n"
                        "**Categorias disponiveis:**\n"
                        "\U0001F3A4 Voz | \U0001F4AC Chat | \U0001F4B0 Economia | \U0001F4CA Rankings\n"
                        "\U0001F6E1\uFE0F Admin | \U0001F527 Utilidade | 💍 Relacionamento | \U0001F6E1\uFE0F Seguranca | \U0001F4BE Dono | 🔐 Restrito",
            color=0x5865f2)
        e.set_footer(text="Prefixo para comandos: !")
        view = HelpView(interaction.user.id)
        await interaction.response.send_message(embed=e, view=view)

    # ============================================================
    # !reset_horas - Reseta horas do leaderboard (ADM + authorized)
    # ============================================================
    @commands.command(name='reset_horas', description='Reseta horas do leaderboard (ADM)')
    @commands.has_permissions(administrator=True)
    async def reset_horas(self, ctx):
        print(f"[DEBUG] reset_horas called by {ctx.author} (id={ctx.author.id})")
        if not is_admin(ctx.author.id):
            print(f"[DEBUG] unauthorized!")
            return await ctx.send("Voce nao tem permissao para usar este comando.")

        guild = ctx.guild
        print(f"[DEBUG] guild={guild}")
        all_users = get_all_user_ids_voice(guild.id)
        print(f"[DEBUG] all_users count={len(all_users)}")

        import asyncio
        dm_sent = 0
        dm_failed = 0

        # Fetch all members from API first
        try:
            await guild.chunk()
            print(f"[DEBUG] after chunk: {len(guild.members)} members cached")
        except Exception as e:
            print(f"[DEBUG] chunk failed: {e}")

        # First, collect voice data and send DMs BEFORE reset
        for (uid,) in all_users:
            member = guild.get_member(uid)
            print(f"[DEBUG] uid={uid}, member={member}")
            if not member:
                continue
            try:
                voice_data = get_voice(guild.id, uid)
                if not voice_data:
                    continue
                total_seconds = voice_data[2]  # total_seconds

                embed = discord.Embed(
                    title="\U0001F389 Nova Temporada!",
                    description=f"Parabens! Voce conquistou **{fmt_time(total_seconds)}** de tempo em call!",
                    color=0xfbbf24)

                await member.send(embed=embed)
                dm_sent += 1
            except discord.Forbidden:
                dm_failed += 1
            except Exception as e:
                print(f"DM falhou uid {uid}: {e}")
                dm_failed += 1

            if dm_sent % 10 == 0:
                await asyncio.sleep(1)

        # Now reset voice hours AFTER DMs are sent
        reset_all_voice(guild.id)

        e = discord.Embed(
            title="\u2705 Horas Resetadas",
            description=f"Horas do leaderboard foram resetadas!\n"
                        f"DMs enviadas: **{dm_sent}** | Falharam: **{dm_failed}**",
            color=0x22c55e)
        await ctx.send(embed=e)

    # ============================================================
    # !reset_chats - Reseta chats do leaderboard (ADM + authorized)
    # ============================================================
    @commands.command(name='reset_chats', description='Reseta chats do leaderboard (ADM)')
    @commands.has_permissions(administrator=True)
    async def reset_chats(self, ctx):
        if not is_admin(ctx.author.id):
            return await ctx.send("Voce nao tem permissao para usar este comando.")

        guild = ctx.guild
        all_users = get_all_user_ids_chat(guild.id)
        dm_sent = 0
        dm_failed = 0
        dm_skipped = 0

        import asyncio

        # Fetch all guild members from API
        try:
            await guild.chunk()
            print(f"[reset_chats] guild={guild.name}, users_db={len(all_users)}, cached={len(guild.members)}")
        except Exception as e:
            print(f"[reset_chats] chunk failed: {e}")

        for i, (uid,) in enumerate(all_users):
            member = guild.get_member(uid)
            if not member:
                dm_skipped += 1
                continue
            try:
                chat_data = get_chat(guild.id, uid)
                total_msgs = chat_data[2] if chat_data else 0

                embed = discord.Embed(
                    title="\U0001F389 Nova Temporada!",
                    description="Parabens nesta temporada!",
                    color=0xa855f7)
                embed.add_field(
                    name="\U0001F4AC Mensagens totais",
                    value=f"**{total_msgs}** mensagens enviadas",
                    inline=False)

                await member.send(embed=embed)
                dm_sent += 1
            except discord.Forbidden:
                dm_failed += 1
            except Exception as e:
                print(f"DM falhou uid {uid}: {e}")
                dm_failed += 1

            if i % 10 == 9:
                await asyncio.sleep(1)

        # Reset chat stats
        reset_all_chat(guild.id)

        e = discord.Embed(
            title="\u2705 Chats Resetados",
            description=f"Chats do leaderboard foram resetados!\n"
                        f"DMs enviadas: **{dm_sent}** | Falharam: **{dm_failed}** | Pularadas: **{dm_skipped}**",
            color=0x22c55e)
        await ctx.send(embed=e)

    # ============================================================
    # /backup_server - Backup de cargos e canais (OWNER only, SLASH)
    # ============================================================
    @app_commands.command(name='backup_server', description='Backup completo de cargos e canais (dono)')
    async def backup_server(self, interaction: discord.Interaction):
        if not is_owner(interaction.user.id):
            return await interaction.response.send_message("Apenas o dono do bot pode usar este comando.", ephemeral=True)

        await interaction.response.defer()

        guild = interaction.guild
        backup = {
            "backup_id": f"{guild.id}_{now_brazil().strftime('%Y%m%d_%H%M%S')}",
            "guild_name": guild.name,
            "guild_id": guild.id,
            "created_at": now_brazil().isoformat(),
            "roles": [],
            "channels": {
                "categories": [],
                "text_channels": [],
                "voice_channels": []
            }
        }

        roles_sorted = sorted(guild.roles, key=lambda r: r.position)
        for role in roles_sorted:
            if role.is_default():
                backup["roles"].append({
                    "name": "@everyone",
                    "permissions": dict(role.permissions),
                    "mentionable": role.mentionable,
                    "hoist": role.hoist,
                    "color": str(role.color)
                })
            else:
                backup["roles"].append({
                    "name": role.name,
                    "permissions": dict(role.permissions),
                    "mentionable": role.mentionable,
                    "hoist": role.hoist,
                    "color": str(role.color),
                    "position": role.position
                })

        for cat in guild.categories:
            backup["channels"]["categories"].append({
                "name": cat.name,
                "position": cat.position,
                "overwrites": {str(m.id if isinstance(m, discord.Member) else m.id):
                              {p: v for p, v in ov} for m, ov in cat.overwrites.items()}
            })

        for ch in guild.text_channels:
            backup["channels"]["text_channels"].append({
                "name": ch.name,
                "category": ch.category.name if ch.category else None,
                "position": ch.position,
                "topic": ch.topic,
                "nsfw": ch.is_nsfw(),
                "slowmode": ch.slowmode_delay,
                "overwrites": {str(m.id if isinstance(m, discord.Member) else m.id):
                              {p: v for p, v in ov} for m, ov in ch.overwrites.items()}
            })

        for ch in guild.voice_channels:
            backup["channels"]["voice_channels"].append({
                "name": ch.name,
                "category": ch.category.name if ch.category else None,
                "position": ch.position,
                "bitrate": ch.bitrate,
                "user_limit": ch.user_limit,
                "overwrites": {str(m.id if isinstance(m, discord.Member) else m.id):
                              {p: v for p, v in ov} for m, ov in ch.overwrites.items()}
            })

        self._backup_data[backup["backup_id"]] = backup
        self._latest_backup_id = backup["backup_id"]
        backup_json = json.dumps(backup, indent=2, ensure_ascii=False)

        backup_path = f"backup_{backup['backup_id']}.json"
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(backup_json)

        e = discord.Embed(
            title="\U0001F4BE Backup Realizado",
            description=f"Backup completo de **{guild.name}** criado!\n"
                        f"- **{len(backup['roles'])}** cargos\n"
                        f"- **{len(backup['channels']['categories'])}** categorias\n"
                        f"- **{len(backup['channels']['text_channels'])}** canais de texto\n"
                        f"- **{len(backup['channels']['voice_channels'])}** canais de voz\n\n"
                        f"Backup ID: `{backup['backup_id']}`\n"
                        f"Arquivo salvo: `{backup_path}`\n"
                        f"Use `/restore_server backup_id:{backup['backup_id']}` para restaurar em qualquer servidor.\n\n"
                        f"**ATENCAO:** O restore DELETA todos os cargos/canais antes de recriar!",
            color=0x22c55e)
        e.set_footer(text="Backup salvo localmente. Para copiar, use o arquivo gerado.")
        await interaction.followup.send(embed=e)
        await interaction.followup.send(file=discord.File(backup_path, filename=backup_path))

    # ============================================================
    # /restore_server - Restaura backup deletando e recriando (OWNER only, SLASH)
    # ============================================================
    @app_commands.command(name='restore_server', description='Restaura backup deletando e recriando tudo (dono)')
    @app_commands.describe(backup_id="ID do backup (opcional; vazio = ultimo backup criado)")
    async def restore_server(self, interaction: discord.Interaction, backup_id: str = None):
        if not is_owner(interaction.user.id):
            return await interaction.response.send_message("Apenas o dono do bot pode usar este comando.", ephemeral=True)

        guild = interaction.guild
        chosen_backup_id = backup_id or self._latest_backup_id
        backup = self._backup_data.get(chosen_backup_id) if chosen_backup_id else None

        if not backup:
            return await interaction.response.send_message(
                "Nenhum backup encontrado para esse ID. Use `/backup_server` primeiro e informe `backup_id`.",
                ephemeral=True
            )

        e = discord.Embed(
            title="\u26A0\uFE0F Confirmar Restauracao",
            description="Isso vai **DELETAR** todos os cargos e canais atuais e recriar do backup.\n"
                        "Esta acao e irreversivel!\n\n"
                        f"Backup: `{backup.get('backup_id', 'sem-id')}`\n"
                        f"Origem: **{backup.get('guild_name', 'desconhecido')}**",
            color=0xef4444)
        view = ConfirmRestoreView()
        await interaction.response.send_message(embed=e, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            try:
                return await interaction.edit_original_response(content="Restauracao cancelada.", embed=None, view=None)
            except discord.NotFound:
                return

        try:
            await interaction.edit_original_response(content="Restaurando backup...", embed=None, view=None)
        except discord.NotFound:
            pass

        roles_to_delete = [r for r in guild.roles if not r.is_default()]
        roles_to_delete.sort(key=lambda r: r.position, reverse=True)
        deleted_roles = 0
        for role in roles_to_delete:
            try:
                await role.delete()
                deleted_roles += 1
            except Exception:
                pass

        deleted_channels = 0
        for ch in guild.channels:
            try:
                await ch.delete()
                deleted_channels += 1
            except Exception:
                pass

        categories_map = {}
        for cat_data in backup["channels"]["categories"]:
            try:
                cat = await guild.create_category(cat_data["name"])
                categories_map[cat_data["name"]] = cat
            except Exception:
                pass

        created_text = 0
        for ch_data in backup["channels"]["text_channels"]:
            try:
                cat = categories_map.get(ch_data["category"]) if ch_data["category"] else None
                overwrites = {}
                for uid_str, perms in ch_data.get("overwrites", {}).items():
                    uid = int(uid_str)
                    member = guild.get_member(uid)
                    if member:
                        overwrites[member] = discord.Permissions(**perms)
                    else:
                        role = guild.get_role(uid)
                        if role:
                            overwrites[role] = discord.Permissions(**perms)

                await guild.create_text_channel(
                    ch_data["name"],
                    category=cat,
                    position=ch_data["position"],
                    topic=ch_data.get("topic"),
                    nsfw=ch_data.get("nsfw", False),
                    slowmode_delay=ch_data.get("slowmode", 0),
                    overwrites=overwrites
                )
                created_text += 1
            except Exception:
                pass

        created_voice = 0
        for ch_data in backup["channels"]["voice_channels"]:
            try:
                cat = categories_map.get(ch_data["category"]) if ch_data["category"] else None
                overwrites = {}
                for uid_str, perms in ch_data.get("overwrites", {}).items():
                    uid = int(uid_str)
                    member = guild.get_member(uid)
                    if member:
                        overwrites[member] = discord.Permissions(**perms)
                    else:
                        role = guild.get_role(uid)
                        if role:
                            overwrites[role] = discord.Permissions(**perms)

                await guild.create_voice_channel(
                    ch_data["name"],
                    category=cat,
                    position=ch_data["position"],
                    bitrate=ch_data.get("bitrate", 64000),
                    user_limit=ch_data.get("user_limit", 0),
                    overwrites=overwrites
                )
                created_voice += 1
            except Exception:
                pass

        role_data_list = sorted(
            [r for r in backup["roles"] if r["name"] != "@everyone"],
            key=lambda r: r.get("position", 0),
            reverse=True
        )
        created_roles = 0
        created_role_objs = []
        for role_data in role_data_list:
            try:
                perms = discord.Permissions(**role_data["permissions"])
                color = int(role_data["color"].replace("#", ""), 16) if role_data.get("color") else 0

                new_role = await guild.create_role(
                    name=role_data["name"],
                    permissions=perms,
                    mentionable=role_data.get("mentionable", False),
                    hoist=role_data.get("hoist", False),
                    color=discord.Color(color)
                )
                created_role_objs.append((new_role, role_data.get("position", 0)))
                created_roles += 1
            except Exception:
                pass

        # Reapply role hierarchy order from backup (bottom -> top).
        # Without this pass, Discord may create roles in a reversed visual order.
        reordered_roles = 0
        if created_role_objs:
            try:
                # Reorder by original backup position preserving top roles at higher positions.
                created_role_objs.sort(key=lambda x: x[1], reverse=True)
                role_positions = {}
                next_position = max(1, guild.me.top_role.position - 1)
                for role, _ in created_role_objs:
                    role_positions[role] = next_position
                    next_position = max(1, next_position - 1)
                await guild.edit_role_positions(role_positions)
                reordered_roles = len(role_positions)
            except Exception:
                pass

        e = discord.Embed(
            title="\u2705 Backup Restaurado",
            description=f"Restauracao completa!\n"
                        f"- Backup usado: `{backup.get('backup_id', 'sem-id')}` ({backup.get('guild_name', 'desconhecido')})\n"
                        f"- Deletados: **{deleted_roles}** cargos, **{deleted_channels}** canais\n"
                        f"- Criados: **{created_roles}** cargos, **{created_text}** texto, **{created_voice}** voz, **{len(categories_map)}** categorias\n"
                        f"- Hierarquia de cargos reordenada: **{reordered_roles}**",
            color=0x22c55e)
        try:
            await interaction.edit_original_response(content=None, embed=e, view=None)
        except discord.NotFound:
            try:
                await interaction.followup.send(embed=e, ephemeral=True)
            except Exception:
                pass


class ConfirmRestoreView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.confirmed = False

    @discord.ui.button(label="Confirmar Restauracao", style=discord.ButtonStyle.danger)
    async def confirm(self, ix: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        await ix.response.defer()
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, ix: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        await ix.response.defer()
        self.stop()


async def setup(bot):
    await bot.add_cog(NewCommandsCog(bot))
