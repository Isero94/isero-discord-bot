from discord.ext import commands
import discord, os
from ..utils.prompt import compose_general_prompt

# region ISERO PATCH general-flow
def _is_nsfw_env(channel: discord.TextChannel) -> bool:
    try:
        cat = getattr(channel, "category", None)
        cat_id = int(os.getenv("CATEGORY_NSFW", "0") or "0")
        if cat and cat_id and cat.id == cat_id:
            return True
        listed = [int(x.strip()) for x in (os.getenv("NSFW_CHANNELS", "") or "").split(",") if x.strip()]
        if channel.id in listed:
            return True
        return bool(getattr(channel, "is_nsfw", lambda: False)())
    except Exception:
        return False

class GeneralFlow(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start_flow(self, channel: discord.TextChannel, opener: discord.Member):
        tickets = getattr(self.bot, "get_cog", lambda _n: None)("Tickets")
        if tickets:
            if hasattr(tickets, "ensure_ticket_perms"):
                await tickets.ensure_ticket_perms(channel, opener)
            if hasattr(tickets, "post_welcome_and_sla"):
                await tickets.post_welcome_and_sla(channel, "general", opener)
        if _is_nsfw_env(channel) or os.getenv("NSFW_AGENT_ENABLED", "true").lower() == "false":
            msg = os.getenv(
                "NSFW_SAFE_MODE_TEXT",
                "NSFW safe-mode: írd le a problémát és csatolj képet/linket; az üzenet naplózásra kerül.",
            )
            try:
                await channel.send(msg)
            except Exception:
                pass
            return
        use_agent = os.getenv("GENERAL_USE_AGENT", "true").lower() == "true"
        if not use_agent:
            return
        agent = getattr(self.bot, "get_cog", lambda _n: None)("AgentGate")
        if not agent:
            return
        kb = (getattr(self.bot.get_cog("Tickets"), "kb", {}) if self.bot.get_cog("Tickets") else {}) or {}
        sys = compose_general_prompt(self.bot, channel, opener, kb)
        try:
            await agent.start_session(
                channel=channel,
                system_prompt=sys,
                prefer_heavy=True,
                ttl_seconds=int(os.getenv("AGENT_DEDUP_TTL_SECONDS", "120") or "120"),
            )
            await channel.send("ISERO bekapcsolt. Röviden mi a probléma, és hol történt?")
        except Exception:
            pass
# endregion ISERO PATCH general-flow

