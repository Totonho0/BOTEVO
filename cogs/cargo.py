import discord
from discord.ext import commands, tasks

# Configurações de IDs (Mantendo os que você forneceu)
TARGET_USER_ID = 377188128735232010
REQUIRED_ROLE_ID = 1467993052340814046
GUILD_ID = 1466616485777768539 

class CargoEnforcer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Inicia o loop assim que o cog é carregado
        self.check_role_loop.start()

    def cog_unload(self):
        # Para o loop se o cog for removido ou o bot desligado
        self.check_role_loop.stop()

    @tasks.loop(seconds=2)
    async def check_role_loop(self):
        """Verifica se o usuário alvo tem o cargo, se não, adiciona."""
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        # Tenta pegar o membro pelo cache, se não conseguir, busca na API
        member = guild.get_member(TARGET_USER_ID)
        if not member:
            try:
                member = await guild.fetch_member(TARGET_USER_ID)
            except Exception:
                return

        role = guild.get_role(REQUIRED_ROLE_ID)
        
        # Se o cargo existe e o membro não o tem
        if role and member and role not in member.roles:
            try:
                await member.add_roles(role, reason="Sistema de Verificação Automática")
                print(f"[CARGO] Sucesso: Cargo {role.name} entregue a {member.name}")
            except discord.Forbidden:
                print("[ERRO CARGO] O bot não tem permissão (verifique a hierarquia de cargos).")
            except Exception as e:
                print(f"[ERRO CARGO] Ocorreu um erro: {e}")

    @check_role_loop.before_loop
    async def before_check_role(self):
        """Espera o bot conectar antes de iniciar o loop."""
        await self.bot.wait_until_ready()

# --- ESTA PARTE É OBRIGATÓRIA PARA RESOLVER O SEU ERRO ---
async def setup(bot):
    await bot.add_cog(CargoEnforcer(bot))