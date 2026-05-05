"""Utility commands — /enquete, /sortear, /anuncio, /roleinfo, /calculadora, /limpar"""
import discord
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks
import random
import re
import asyncio
import ast
import operator as op

_SAFE_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}


def _safe_eval_expr(expr: str):
    node = ast.parse(expr, mode="eval")

    def _eval(n):
        if isinstance(n, ast.Expression):
            return _eval(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _SAFE_OPS:
            return _SAFE_OPS[type(n.op)](_eval(n.left), _eval(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _SAFE_OPS:
            return _SAFE_OPS[type(n.op)](_eval(n.operand))
        raise ValueError("Expressao invalida")

    return _eval(node)


class UtilCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ============================================================
    # /enquete — Criar enquete com reacoes
    # ============================================================
    @commands.command(name="enquete", description="Crie uma enquete com reacoes")
    async def enquete(self, ctx, pergunta: str, opcao1: str, opcao2: str,
                      opcao3: str = None, opcao4: str = None):
        options = [opcao1, opcao2]
        if opcao3:
            options.append(opcao3)
        if opcao4:
            options.append(opcao4)

        emojis = ["1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3", "4\ufe0f\u20e3"]

        desc = "\n".join(f"{emojis[i]} {opt}" for i, opt in enumerate(options))
        e = discord.Embed(
            title=f"\U0001F4CA {pergunta}",
            description=desc,
            color=0x5865f2)
        e.set_footer(text=f"Enquete por {ctx.author.display_name}")

        msg = await ctx.channel.send(embed=e)
        for i in range(len(options)):
            await msg.add_reaction(emojis[i])

        await ctx.send("Enquete criada!")

    # ============================================================
    # /sortear — Sortear membro
    # ============================================================
    @app_commands.command(name="sortear", description="Sorteie membros do servidor")
    @app_commands.describe(
        cargo="Cargo para filtrar membros",
        remover_bots="Remover bots do sorteio (padrao: True)",
        quantidade="Numero de vencedores (padrao: 1)")
    async def sortear(self, interaction: discord.Interaction, cargo: discord.Role = None,
                      remover_bots: bool = True, quantidade: int = 1):
        quantidade = max(1, min(quantidade, 10))

        members = list(interaction.guild.members)
        if remover_bots:
            members = [m for m in members if not m.bot]
        if cargo:
            members = [m for m in members if cargo in m.roles]

        if not members:
            return await interaction.response.send_message("Nenhum membro encontrado para sortear!")

        if quantidade > len(members):
            quantidade = len(members)

        winners = random.sample(members, quantidade)

        if quantidade == 1:
            e = discord.Embed(
                title="\U0001F389 Sorteio!",
                description=f"Vencedor: **{winners[0].mention}**",
                color=0x22c55e)
        else:
            desc = "\n".join(f"\U0001F3C6 {m.mention}" for m in winners)
            e = discord.Embed(
                title="\U0001F389 Sorteio!",
                description=f"**{quantidade} vencedores:**\n{desc}",
                color=0x22c55e)

        e.set_footer(text=f"Sorteado entre {len(members)} membros")
        await interaction.response.send_message(embed=e)

    # ============================================================
    # !anuncio — Enviar anuncio bonito (KEEP AS SLASH)
    # ============================================================
    @app_commands.command(name="anuncio", description="Envia um anuncio formatado no canal")
    @app_commands.describe(
        titulo="Titulo do anuncio",
        mensagem="Conteudo do anuncio",
        canal="Canal para enviar (padrao: canal atual)",
        cor="Cor do embed (hex sem #)")
    @app_commands.default_permissions(manage_messages=True)
    async def anuncio(self, interaction: discord.Interaction, titulo: str, mensagem: str,
                      canal: discord.TextChannel = None, cor: str = "5865f2"):
        canal = canal or interaction.channel

        try:
            color = int(cor.replace("#", ""), 16)
        except ValueError:
            color = 0x5865f2

        e = discord.Embed(
            title=f"\U0001F4E2 {titulo}",
            description=mensagem,
            color=color)
        e.set_footer(text=f"Anuncio por {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        e.timestamp = discord.utils.utcnow()

        msg = await canal.send(embed=e)
        await interaction.response.send_message(f"Anuncio enviado em {canal.mention}! {msg.jump_url}", ephemeral=True)

    # ============================================================
    # !roleinfo — Info de um cargo
    # ============================================================
    @commands.command(name="roleinfo", description="Ve informacoes de um cargo")
    async def roleinfo(self, ctx, *, cargo: discord.Role):
        e = discord.Embed(
            title=f"\U0001F3F7\uFE0F {cargo.name}",
            color=cargo.color or 0x5865f2)

        members_with_role = [m for m in ctx.guild.members if cargo in m.roles]

        e.add_field(name="ID", value=f"`{cargo.id}`", inline=True)
        e.add_field(name="Cor", value=f"`#{cargo.color.value:06X}`" if cargo.color else "Padrao", inline=True)
        e.add_field(name="Posicao", value=f"#{cargo.position}", inline=True)
        e.add_field(name="Membros", value=str(len(members_with_role)), inline=True)
        e.add_field(name="Menciona", value="Sim" if cargo.mentionable else "Nao", inline=True)
        e.add_field(name="Separado", value="Sim" if cargo.hoist else "Nao", inline=True)

        perms = []
        for name, value in cargo.permissions:
            if value:
                perms.append(name.replace("_", " ").title())
        perms_str = ", ".join(perms[:5]) if perms else "Nenhuma"
        if len(perms) > 5:
            perms_str += f" (+{len(perms) - 5})"
        e.add_field(name="Permissoes", value=perms_str, inline=False)

        if members_with_role:
            names = ", ".join(m.mention for m in members_with_role[:10])
            if len(members_with_role) > 10:
                names += f" ...+{len(members_with_role) - 10}"
            e.add_field(name="Membros com o cargo", value=names, inline=False)

        await ctx.send(embed=e)

    # ============================================================
    # !calculadora — Calculadora simples
    # ============================================================
    @commands.command(name="calculadora", description="Calculadora simples")
    async def calculadora(self, ctx, *, expressao: str):
        cleaned = re.sub(r'\s+', '', expressao)
        if not cleaned or re.search(r'[^0-9+\-*/().%]', cleaned):
            return await ctx.send("Use apenas numeros e operadores: `+`, `-`, `*`, `/`, `()`, `%`")

        try:
            result = _safe_eval_expr(cleaned)
            if isinstance(result, float) and result == int(result):
                result = int(result)
            e = discord.Embed(
                title="\U0001F9EE Calculadora",
                description=f"`{expressao}` = **{result}**",
                color=0x3b82f6)
            await ctx.send(embed=e)
        except ZeroDivisionError:
            await ctx.send("\U0001F4A5 Divisao por zero!")
        except Exception:
            await ctx.send("Expressao invalida.")

    # ============================================================
    # /limpar — Limpar mensagens do canal
    # ============================================================
    @app_commands.command(name="limpar", description="Limpe mensagens do canal")
    @app_commands.describe(quantidade="Numero de mensagens para remover (1-100)")
    async def limpar(self, interaction: discord.Interaction, quantidade: int):
        quantidade = max(1, min(quantidade, 100))

        await interaction.response.defer()
        deleted = await interaction.channel.purge(limit=quantidade)
        e = discord.Embed(
            title="\U0001F9F9 Limpeza",
            description=f"{len(deleted)} mensagens removidas por {interaction.user.mention}",
            color=0x22c55e)
        msg = await interaction.followup.send(embed=e)
        await asyncio.sleep(5)
        try:
            await msg.delete()
        except Exception:
            pass

    # ============================================================
    # !baninfo — Info de um ban
    # ============================================================
    @commands.command(name="baninfo", description="Ve banimentos recentes")
    async def baninfo(self, ctx):
        bans = []
        async for entry in ctx.guild.bans(limit=10):
            bans.append(entry)

        if not bans:
            return await ctx.send("Ninguem banido no servidor.")

        desc = ""
        for i, ban in enumerate(bans[:10], 1):
            reason = ban.reason or "Sem motivo"
            desc += f"**{i}.** {ban.user.mention} — *{reason[:50]}*\n"

        e = discord.Embed(
            title="\U0001F528 Banes Recentes",
            description=desc,
            color=0xef4444)
        await ctx.send(embed=e)

    # ============================================================
    # /slowmode — Definir slowmode no canal (KEEP AS SLASH)
    # ============================================================
    @app_commands.command(name="slowmode", description="Define slowmode no canal")
    @app_commands.describe(segundos="Segundos entre mensagens (0-21600)")
    @app_commands.default_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, segundos: int):
        segundos = max(0, min(segundos, 21600))

        await interaction.channel.edit(slowmode_delay=segundos)

        if segundos == 0:
            desc = "Slowmode **desativado**!"
        else:
            desc = f"Slowmode definido para **{segundos} segundos**"

        e = discord.Embed(
            title="\U0001F40C Slowmode",
            description=f"{desc} em {interaction.channel.mention}",
            color=0x3b82f6)
        await interaction.response.send_message(embed=e)

    # ============================================================
    # /nick — Mudar nickname de alguem (KEEP AS SLASH)
    # ============================================================
    @app_commands.command(name="nick", description="Muda o nickname de um membro")
    @app_commands.describe(membro="Membro para mudar", novo_nick="Novo nickname")
    @app_commands.default_permissions(manage_nicknames=True)
    async def nick(self, interaction: discord.Interaction, membro: discord.Member, novo_nick: str):
        if len(novo_nick) > 32:
            return await interaction.response.send_message("Nick muito longo (max 32 caracteres).", ephemeral=True)

        try:
            old = membro.display_name
            await membro.edit(nick=novo_nick)
            e = discord.Embed(
                title="\U0001F3F7\uFE0F Nick Alterado",
                description=f"**{old}** -> **{novo_nick}**",
                color=0x3b82f6)
            e.set_footer(text=f"Por {interaction.user.display_name}")
            await interaction.response.send_message(embed=e)
        except discord.Forbidden:
            await interaction.response.send_message("Nao tenho permissao para mudar o nick desse membro.", ephemeral=True)

    # ============================================================
    # !status — Status do bot
    # ============================================================
    @commands.command(name="status", description="Ve o status do bot")
    async def status(self, ctx):
        bot_user = self.bot.user
        uptime = "Desconhecido"
        if self.bot.start_time:
            from datetime import datetime
            diff = datetime.now() - self.bot.start_time
            hours = int(diff.total_seconds() // 3600)
            mins = int((diff.total_seconds() % 3600) // 60)
            uptime = f"{hours}h {mins}m"

        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        total_channels = sum(len(g.channels) for g in self.bot.guilds)

        e = discord.Embed(
            title=f"\U0001F916 {bot_user.display_name}",
            description="Bot Primal System",
            color=0x5865f2)
        if bot_user.avatar:
            e.set_thumbnail(url=bot_user.avatar.url)

        e.add_field(name="\U0001F4E1 Status", value=f"Online | Latencia: **{round(self.bot.latency * 1000)}ms**", inline=True)
        e.add_field(name="\u23F1\uFE0F Uptime", value=uptime, inline=True)
        e.add_field(name="\U0001F3F0 Servidores", value=str(len(self.bot.guilds)), inline=True)
        e.add_field(name="\U0001F465 Membros", value=str(total_members), inline=True)
        e.add_field(name="\U0001F4AC Canais", value=str(total_channels), inline=True)
        e.add_field(name="\U0001F4E2 Prefixo", value="`!` (comandos legacy)", inline=True)
        e.add_field(name="\U0001F9F0 Cog Loaded", value=str(len(self.bot.cogs)), inline=True)
        e.add_field(name="\U0001F4DD Comandos", value=str(len(self.bot.commands)), inline=True)

        e.set_footer(text="Desenvolvido para o servidor Primal")
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(UtilCog(bot))
