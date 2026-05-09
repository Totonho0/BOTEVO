import discord
from discord.ext import commands
from discord import app_commands
from typing import List

from database import (
    is_coleira_authorized,
    set_coleira_authorized,
    remove_coleira_authorized,
    add_coleira,
    remove_coleira,
    get_coleiras_by_owner,
    get_coleira_by_target,
    get_coleiras_where_owner,
    get_all_coleiras,
)


def _has_manage_guild(member: discord.Member) -> bool:
    return member.guild_permissions.manage_guild or member.guild_permissions.administrator


class ColeiraConfigView(discord.ui.View):
    def __init__(self, cog: "ColeiraCog", guild_id: int, admin_id: int, target_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.admin_id = admin_id
        self.target_id = target_id

    async def _toggle_auth(self, ix: discord.Interaction, action: str):
        if ix.user.id != self.admin_id:
            return await ix.response.send_message(
                "Somente quem abriu o painel pode usar estes botoes.",
                ephemeral=True,
            )
        target = ix.guild.get_member(self.target_id)
        if not target:
            return await ix.response.send_message("Usuario nao encontrado.", ephemeral=True)
        if action == "grant":
            set_coleira_authorized(self.guild_id, target.id, ix.user.id)
            return await ix.response.send_message(
                f"{target.mention} foi autorizado a usar `/coleira`.",
                ephemeral=True,
            )
        remove_coleira_authorized(self.guild_id, target.id)
        return await ix.response.send_message(
            f"A autorizacao de {target.mention} para `/coleira` foi removida.",
            ephemeral=True,
        )

    @discord.ui.button(label="Autorizar-me", style=discord.ButtonStyle.success)
    async def grant(self, ix: discord.Interaction, button: discord.ui.Button):
        await self._toggle_auth(ix, "grant")

    @discord.ui.button(label="Revogar-me", style=discord.ButtonStyle.danger)
    async def revoke(self, ix: discord.Interaction, button: discord.ui.Button):
        await self._toggle_auth(ix, "revoke")


class ColeiraRemoveSelect(discord.ui.Select):
    def __init__(self, cog: "ColeiraCog", owner_id: int, options: List[discord.SelectOption]):
        super().__init__(
            placeholder="Selecione quem remover da coleira...",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.cog = cog
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "Apenas quem abriu o menu pode remover coleiras.",
                ephemeral=True,
            )
        target_id = int(self.values[0])
        removed = remove_coleira(interaction.guild.id, self.owner_id, target_id)
        if not removed:
            return await interaction.response.send_message(
                "Esta coleira ja foi removida.",
                ephemeral=True,
            )
        target = interaction.guild.get_member(target_id)
        target_name = target.mention if target else f"`{target_id}`"
        await interaction.response.send_message(
            f"Coleira removida de {target_name}.",
            ephemeral=True,
        )


class ColeiraRemoveView(discord.ui.View):
    def __init__(self, cog: "ColeiraCog", owner_id: int, options: List[discord.SelectOption]):
        super().__init__(timeout=300)
        self.add_item(ColeiraRemoveSelect(cog, owner_id, options))


class ColeiraCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _can_use_coleira(self, member: discord.Member) -> bool:
        if _has_manage_guild(member):
            return True
        return is_coleira_authorized(member.guild.id, member.id)

    async def _pull_target(self, guild: discord.Guild, owner_id: int, target_id: int):
        owner = guild.get_member(owner_id)
        target = guild.get_member(target_id)
        if not owner or not target:
            return
        if not owner.voice or not owner.voice.channel:
            return
        if target.voice and target.voice.channel and target.voice.channel.id == owner.voice.channel.id:
            return
        if not target.voice or not target.voice.channel:
            return
        try:
            await target.move_to(owner.voice.channel, reason=f"Coleira aplicada por {owner} ({owner.id})")
        except (discord.Forbidden, discord.HTTPException):
            return

    @app_commands.command(name="configc", description="Configura autorizacao para uso do comando /coleira")
    @app_commands.describe(usuario="Pessoa para autorizar/revogar no /coleira (padrao: voce)")
    async def configc(self, interaction: discord.Interaction, usuario: discord.Member = None):
        member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        if not member or not _has_manage_guild(member):
            return await interaction.response.send_message(
                "Voce precisa de `Gerenciar Servidor` para usar este comando.",
                ephemeral=True,
            )
        alvo = usuario or member
        embed = discord.Embed(
            title="Configuracao de Coleira",
            description=(
                f"Alvo selecionado: {alvo.mention}\n\n"
                "Use os botoes abaixo para **autorizar** ou **revogar** o uso de `/coleira`.\n"
                "Somente usuarios autorizados (ou staff com permissao de gerenciar servidor) podem usar."
            ),
            color=0x3B82F6,
        )
        embed.set_footer(text="Painel expira em 5 minutos.")
        await interaction.response.send_message(
            embed=embed,
            view=ColeiraConfigView(self, interaction.guild.id, interaction.user.id, alvo.id),
            ephemeral=True,
        )

    @app_commands.command(name="coleira", description="Aplica coleira em alguem para puxar para sua call")
    @app_commands.describe(usuario="Pessoa que sera puxada automaticamente para sua call")
    async def coleira(self, interaction: discord.Interaction, usuario: discord.Member):
        actor = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        if not actor:
            return await interaction.response.send_message("Usuario invalido.", ephemeral=True)
        if not self._can_use_coleira(actor):
            return await interaction.response.send_message(
                "Voce nao esta autorizado a usar `/coleira`. Use `/configc` com staff.",
                ephemeral=True,
            )
        if usuario.bot:
            return await interaction.response.send_message("Nao pode aplicar coleira em bot.", ephemeral=True)
        if usuario.id == actor.id:
            return await interaction.response.send_message("Voce nao pode colocar coleira em si mesmo.", ephemeral=True)
        if not actor.voice or not actor.voice.channel:
            return await interaction.response.send_message(
                "Voce precisa estar em uma call para usar `/coleira`.",
                ephemeral=True,
            )

        existing = get_coleira_by_target(interaction.guild.id, usuario.id)
        if existing and int(existing[0]) != actor.id:
            owner = interaction.guild.get_member(int(existing[0]))
            owner_txt = owner.mention if owner else f"`{existing[0]}`"
            return await interaction.response.send_message(
                f"Esse usuario ja esta com coleira de {owner_txt}. Ninguem mais pode colocar ate ser removida.",
                ephemeral=True,
            )

        ok, other_owner = add_coleira(interaction.guild.id, actor.id, usuario.id)
        if not ok:
            owner = interaction.guild.get_member(int(other_owner))
            owner_txt = owner.mention if owner else f"`{other_owner}`"
            return await interaction.response.send_message(
                f"Esse usuario ja esta com coleira de {owner_txt}. Ninguem mais pode colocar ate ser removida.",
                ephemeral=True,
            )
        await self._pull_target(interaction.guild, actor.id, usuario.id)
        await interaction.response.send_message(
            f"{usuario.mention} recebeu sua coleira. Enquanto ativa, sera puxado para sua call automaticamente.",
            ephemeral=True,
        )

    @app_commands.command(name="coleiras", description="Lista e remove as coleiras que voce aplicou")
    async def coleiras(self, interaction: discord.Interaction):
        actor = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        if not actor:
            return await interaction.response.send_message("Usuario invalido.", ephemeral=True)
        all_rows = get_all_coleiras(interaction.guild.id)
        rows = get_coleiras_by_owner(interaction.guild.id, actor.id)
        if not all_rows:
            return await interaction.response.send_message("Nao ha coleiras ativas no servidor.")

        options = []
        public_lines = []
        for owner_id, target_id, _created_at in all_rows[:25]:
            public_lines.append(f"- <@{owner_id}> -> <@{target_id}>")
        for target_id, _created_at in rows[:25]:
            target = interaction.guild.get_member(int(target_id))
            label = target.display_name if target else f"Usuario {target_id}"
            options.append(discord.SelectOption(label=label[:100], value=str(target_id)))

        embed = discord.Embed(
            title="Coleiras ativas do servidor",
            description="\n".join(public_lines),
            color=0xF59E0B,
        )
        if options:
            embed.set_footer(text="Voce pode remover apenas as coleiras que voce aplicou.")
            return await interaction.response.send_message(
                embed=embed,
                view=ColeiraRemoveView(self, actor.id, options),
            )
        embed.set_footer(text="Voce nao aplicou nenhuma coleira para remover.")
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        if before.channel == after.channel:
            return

        # Quando o dono muda de call, puxa todos os alvos dele.
        owner_rows = get_coleiras_where_owner(member.guild.id, member.id)
        for _owner_id, target_id in owner_rows:
            await self._pull_target(member.guild, int(member.id), int(target_id))

        # Quando o alvo muda de call, puxa ele de volta para a call do dono.
        row = get_coleira_by_target(member.guild.id, member.id)
        if row:
            await self._pull_target(member.guild, int(row[0]), int(row[1]))


async def setup(bot):
    await bot.add_cog(ColeiraCog(bot))
