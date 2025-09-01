FEATURE_NAME = "ranks"
from discord.ext import commands
import os
import discord

async def setup(bot):
    await bot.add_cog(RoleSync(bot))

class RoleSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # parse role mapping from environment variable LEVEL_ROLE_IDS
        # expected format: "threshold:role_id,threshold2:role_id2"
        mapping_str = os.getenv("LEVEL_ROLE_IDS", "")
        self.level_roles = {}
        for part in mapping_str.split(","):
            if ":" in part:
                threshold, role_id = part.split(":", 1)
                try:
                    self.level_roles[int(threshold.strip())] = int(role_id.strip())
                except ValueError:
                    continue

    @commands.command(name="syncroles")
    async def sync_roles(self, ctx, member: discord.Member = None):
        """Synchronize roles for a member based on their level."""
        member = member or ctx.author
        # get AgentGate cog to access the database
        ag = self.bot.get_cog("AgentGate")
        if ag is None:
            await ctx.send("AgentGate is not available.")
            return
        db = ag.db
        try:
            card = await db.get_card(member.id)
        except Exception:
            await db.ensure_player(member.id)
            card = await db.get_card(member.id)
        tokens = getattr(card, "tokens_total", 0)
        tokens_per_rank = 20
        ranks_per_level = 20
        level = tokens // (tokens_per_rank * ranks_per_level)
        # Determine the appropriate role for this level
        target_role_id = None
        for threshold, role_id in sorted(self.level_roles.items()):
            if level >= threshold:
                target_role_id = role_id
        if not target_role_id:
            await ctx.send("No role mapping configured for this level.")
            return
        guild = ctx.guild
        target_role = guild.get_role(target_role_id)
        if target_role is None:
            await ctx.send("Configured role ID not found in guild.")
            return
        # Assign target role and remove other level roles
        roles_to_remove = []
        for rid in self.level_roles.values():
            if rid != target_role_id and member.get_role(rid):
                role = guild.get_role(rid)
                if role:
                    roles_to_remove.append(role)
        await member.add_roles(target_role, reason="Sync roles based on level")
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Sync roles based on level")
        await ctx.send(f"Synchronized roles for {member.display_name} to level {level}.")
