from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from cogs.utils.context import resolve
from config import GUILD_ID
from bot.config import settings

if GUILD_ID:
    _guilds = app_commands.guilds(discord.Object(id=GUILD_ID))
else:
    def _guilds(func):
        return func


class Health(commands.Cog):
    """Minimal diagnostic utilities."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check if the bot is alive")
    @_guilds
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Pong!")

    @app_commands.command(name="diag", description="Show basic diagnostic info")
    @_guilds
    async def diag(self, interaction: discord.Interaction) -> None:
        ag = self.bot.get_cog("AgentGate")
        pg = self.bot.get_cog("ProfanityGuard")
        reason = "none"
        if ag and hasattr(ag, "channel_trigger_reason"):
            try:
                reason = ag.channel_trigger_reason(interaction.channel)  # type: ignore[arg-type]
            except Exception:
                reason = "none"
        env = getattr(ag, "env_status", {}) if ag else {}
        prof_module = pg.__module__ if pg else "none"
        prof_source = getattr(pg, "source", "unknown")
        free_words = getattr(pg, "free_per_msg", 0)
        prof_diag = format_profanity_diag(self.bot)
        ctx = await resolve(interaction)
        msg = (
            f"trigger_reason={reason}\n"
            f"context channel={ctx.channel_name}/{ctx.channel_id} "
            f"category={ctx.category_name}/{ctx.category_id} "
            f"is_ticket={ctx.is_ticket} ticket_type={ctx.ticket_type} "
            f"is_nsfw={ctx.is_nsfw} owner={ctx.is_owner} staff={ctx.is_staff} "
            f"locale={ctx.locale} char_limit={ctx.char_limit} "
            f"brief_limits={ctx.brief_char_limit}/{ctx.brief_image_limit}\n"
            f"{prof_diag} "
            f"prof_cog={prof_module} prof_src={prof_source} free_words={free_words} "
            f"features profanity_v2={settings.FEATURES_PROFANITY_V2} mebinu_dialog_v1={settings.FEATURES_MEBINU_DIALOG_V1}\n"
            f"env bot_commands={env.get('bot_commands', 'unset')} "
            f"suggestions={env.get('suggestions', 'unset')} "
            f"tickets_category={env.get('tickets_category', 'unset')} "
            f"wake_words_count={env.get('wake_words_count', 0)} "
            f"deprecated_keys_detected={env.get('deprecated_keys_detected', False)}"
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="whereami", description="Show current channel context")
    @_guilds
    async def whereami(self, interaction: discord.Interaction) -> None:
        ctx = await resolve(interaction)
        msg = (
            f"channel={ctx.channel_name}/{ctx.channel_id} "
            f"category={ctx.category_name}/{ctx.category_id} "
            f"is_ticket={ctx.is_ticket} ticket_type={ctx.ticket_type} "
            f"char_limit={ctx.char_limit} "
            f"brief_limits={ctx.brief_char_limit}/{ctx.brief_image_limit}"
        )
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Health(bot))
