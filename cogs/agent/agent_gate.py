from discord.ext import commands

FEATURE_NAME = "staff_assistant"

async def setup(bot):
    await bot.add_cog(AgentGate(bot))

class AgentGate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ask")
    async def ask(self, ctx: commands.Context, *, prompt: str):
        # Minimal placeholder: echoes the prompt (clamped in Ticket cog for pre-chat)
        text = prompt.strip()
        await ctx.send(f"[staff-agent] {text[:300]}")
