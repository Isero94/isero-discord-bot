FEATURE_NAME = "keyword"

from discord.ext import commands

async def setup(bot):
    # Register this cog with the bot
    await bot.add_cog(KeywordWatch(bot))

class KeywordWatch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # List of keywords and phrases to watch for. Feel free to expand this list with additional triggers.
        self.keywords = {
            "mebinu",
            "commission",
            "rajz",     # Hungarian: drawing/rajz
            "draw",
            "hentai",
            "help",
        }

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listens for messages and updates player state when keywords are detected."""
        # Ignore direct messages and messages from bots
        if message.guild is None or message.author.bot:
            return
        # Normalise message content to lowercase for matching
        content = message.content.lower()
        # Count how many of the defined keywords appear in the message
        matches = sum(1 for kw in self.keywords if kw in content)
        if matches <= 0:
            return
        # Retrieve the AgentGate cog to access the database
        ag = self.bot.get_cog("AgentGate")
        db = getattr(ag, "db", None)
        if db is None:
            return  # no DB available – exit quietly
        # Award tokens based on the number of keyword matches
        await db.add_tokens(message.author.id, matches)
        # Increase marketing score for the user proportionally to keyword matches
        await db.bump_marketing(message.author.id, matches)
        # You could add more actions here if needed (e.g., triggering notifications)
        return
