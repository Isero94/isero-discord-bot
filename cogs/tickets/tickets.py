import re
import os
import datetime as dt
import logging
import discord
from discord.ext import commands

class Tickets(commands.Cog):
    """Minimal ticket intake: welcome and auto-log first message."""

    def __init__(self, bot):
        self.bot = bot
        self.log = logging.getLogger("ISERO.Tickets")
        self.default_sla_days = int(os.getenv("TICKET_DEFAULT_SLA_DAYS", "3") or "3")
        self.notify_channel_id = int(os.getenv("TICKET_NOTIFY_CHANNEL_ID", "0") or "0")
        self.auto_submit = os.getenv("TICKET_AUTO_SUBMIT_ON_FIRST_MSG", "true").lower() == "true"
        self.min_chars = int(os.getenv("TICKET_MIN_CHARS", "20") or "20")
        self.ping_owner = os.getenv("TICKET_PING_OWNER_ON_NEW", "true").lower() == "true"
        self.owner_id = int(os.getenv("OWNER_ID", "0") or "0")
        self.logged_once: set[int] = set()

    async def ensure_ticket_perms(self, channel: discord.TextChannel, opener: discord.Member):
        try:
            await channel.set_permissions(opener, view_channel=True, send_messages=True, attach_files=True, embed_links=True)
        except Exception:
            pass

    async def post_welcome_and_sla(self, channel: discord.TextChannel, kind: str, opener: discord.Member):
        await self.ensure_ticket_perms(channel, opener)
        due = dt.datetime.utcnow() + dt.timedelta(days=self.default_sla_days)
        desc = (
            f"Szia {opener.mention}! Ez egy privát ticket csatorna.\n\n"
            f"**Céldátum (≈ puha határidő):** {due.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        embed = discord.Embed(title=f"Welcome — {kind.capitalize()}", description=desc, color=discord.Color.green())
        embed.set_footer(text=f"SLA ≈ {self.default_sla_days} nap • ISERO")
        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    def _kind_from_topic(self, topic: str | None) -> str:
        if not topic:
            return "general"
        m = re.search(r"type=([a-z0-9_-]+)", topic)
        return m.group(1) if m else "general"

    async def _log_message(self, message: discord.Message):
        kind = self._kind_from_topic(getattr(message.channel, "topic", ""))
        excerpt = (message.content or "")[:300]
        embed = discord.Embed(
            title="Ticket message",
            description=excerpt or "[nincs szöveg]",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Típus", value=kind, inline=True)
        embed.add_field(name="Csatorna", value=message.channel.mention, inline=True)
        embed.add_field(name="Felhasználó", value=message.author.mention, inline=True)
        if message.attachments:
            urls = "\n".join(a.url for a in message.attachments)
            embed.add_field(name="Csatolmányok", value=urls, inline=False)
            embed.add_field(name="Darab", value=str(len(message.attachments)), inline=True)
        notify = self.bot.get_channel(self.notify_channel_id)
        content = f"<@{self.owner_id}>" if self.ping_owner and self.owner_id else None
        if notify:
            try:
                await notify.send(content=content, embed=embed)
            except Exception:
                pass
        try:
            await message.channel.send("Köszi, rögzítettem.")
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        ch = message.channel
        topic = getattr(ch, "topic", "") or ""
        if "type=" not in topic:
            return
        if self.auto_submit and ch.id not in self.logged_once:
            if (message.content and len(message.content) >= self.min_chars) or message.attachments:
                await self._log_message(message)
                self.logged_once.add(ch.id)

    @commands.hybrid_command(name="submit", description="Kézi logolás a ticketből.")
    async def submit(self, ctx: commands.Context):
        ch = ctx.channel
        async for m in ch.history(limit=20, oldest_first=False):
            if not m.author.bot:
                await self._log_message(m)
                return
        await ctx.reply("Nincs logolható üzenet.")
