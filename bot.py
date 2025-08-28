import os, asyncio, discord
from discord.ext import commands
from dotenv import load_dotenv
load_dotenv()
intents=discord.Intents.default(); intents.message_content=True; intents.members=True; intents.guilds=True
bot=commands.Bot(command_prefix=commands.when_mentioned_or('!'), intents=intents, help_command=None)
INITIAL_EXTENSIONS=['cogs.profiles','cogs.logging','cogs.moderation','cogs.agent_gate']
@bot.event
async def on_ready():
    print(f'✅ ISERO v2 online as {bot.user} ({bot.user.id})')
    from cogs.agent_gate import TicketHubView
    bot.add_view(TicketHubView())
async def load_cogs():
    for ext in INITIAL_EXTENSIONS:
        try:
            await bot.load_extension(ext)
            print(f'Loaded {ext}')
        except Exception as e:
            print(f'Failed to load {ext}: {e}')
async def main():
    async with bot:
        await load_cogs()
        await bot.start(os.getenv('DISCORD_TOKEN'))
if __name__=='__main__': asyncio.run(main())
