from discord import app_commands
from discord.ext import commands

class AgentAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _gate(self):
        return self.bot.get_cog("AgentGate")

    @app_commands.command(name="agent-model", description="Agent modell módja: auto | mini | heavy")
    @app_commands.describe(mode="auto | mini | heavy")
    async def agent_model(self, interaction, mode: str):
        gate = self._gate()
        if not gate:
            await interaction.response.send_message("AgentGate cog nincs betöltve.", ephemeral=True)
            return
        mode = mode.lower().strip()
        if mode not in {"auto", "mini", "heavy"}:
            await interaction.response.send_message("Érvénytelen mód. Használd: auto | mini | heavy", ephemeral=True)
            return
        gate.set_model_mode(mode)
        await interaction.response.send_message(f"Oké. Modell mód: **{mode}**.")

    @app_commands.command(name="agent-status", description="Agent státusz (modell, tokenek)")
    async def agent_status(self, interaction):
        gate = self._gate()
        if not gate:
            await interaction.response.send_message("AgentGate cog nincs betöltve.", ephemeral=True)
            return
        await interaction.response.send_message(gate.get_status(), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AgentAdmin(bot))
