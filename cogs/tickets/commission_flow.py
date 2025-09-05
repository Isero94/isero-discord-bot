from discord.ext import commands
import discord, os, datetime as dt
from ..utils.prompt import compose_commission_prompt
from ..utils.sales import calc_images, calc_videos

# region ISERO PATCH commission-flow
class CommissionFlow(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start_flow(self, channel: discord.TextChannel, opener: discord.Member):
        tickets = getattr(self.bot, "get_cog", lambda _n: None)("Tickets")
        if tickets:
            if hasattr(tickets, "ensure_ticket_perms"):
                await tickets.ensure_ticket_perms(channel, opener)
            if hasattr(tickets, "post_welcome_and_sla"):
                await tickets.post_welcome_and_sla(channel, "commission", opener)
        use_agent = (os.getenv("COMMISSION_USE_AGENT", "true").lower() == "true")
        if not use_agent:
            return
        agent = getattr(self.bot, "get_cog", lambda _n: None)("AgentGate")
        if not agent:
            return
        kb = (getattr(self.bot.get_cog("Tickets"), "kb", {}) if self.bot.get_cog("Tickets") else {}) or {}
        sys = compose_commission_prompt(self.bot, channel, opener, kb)
        try:
            await agent.start_session(
                channel=channel,
                system_prompt=sys,
                prefer_heavy=True,
                ttl_seconds=int(os.getenv("AGENT_DEDUP_TTL_SECONDS","120") or "120"),
            )
            await channel.send("ISERO bekapcsolt. Képeket vagy videókat szeretnél első körben?")
        except Exception:
            pass

    @commands.hybrid_command(name="quoteimg", description="Képajánlat (db × ár, 4+ kedvezmény).")
    async def quoteimg(self, ctx: commands.Context, qty: int):
        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.reply("Csak csatornában használható.")
        unit = float(os.getenv("IMG_BASE_PRICE_USD", "6") or "6")
        bulk_min = int(os.getenv("IMG_BULK_MIN_QTY", "4") or "4")
        off = float(os.getenv("IMG_BULK_OFF_USD", "1") or "1")
        sub, disc, total = calc_images(unit, qty, bulk_min, off)
        txt = (f"Kép ajánlat: **{qty}× ${unit:.2f}** = ${sub:.2f}"
               + (f" • Kedvezmény: −${disc:.2f}" if disc>0 else "")
               + f" → **Végösszeg: ${total:.2f}**  ( {bulk_min}+ képnél −${off:.0f}/kép )")
        try: await ctx.reply(txt)
        except Exception: await ctx.send(txt)

    @commands.hybrid_command(name="quotevid", description="Videó ajánlat (mp és darabszám alapján).")
    async def quotevid(self, ctx: commands.Context, seconds_per_video: int, qty: int = 1):
        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.reply("Csak csatornában használható.")
        per5 = float(os.getenv("VID_PRICE_PER_5S_USD", "20") or "20")
        bulk_min = int(os.getenv("VID_BULK_MIN_QTY", "4") or "4")
        off = float(os.getenv("VID_BULK_OFF_USD", "5") or "5")
        per_video, sub, disc, total = calc_videos(per5, seconds_per_video, qty, bulk_min, off)
        txt = (f"Videó ajánlat: **{qty}× {seconds_per_video}s** (blokkonként ${per5:.0f}/5s) "
               f"→ **${per_video:.2f}/videó**, összesen ${sub:.2f}"
               + (f" • Kedvezmény: −${disc:.2f}" if disc>0 else "")
               + f" → **Végösszeg: ${total:.2f}**  ( {bulk_min}+ videónál −${off:.0f}/videó )")
        try: await ctx.reply(txt)
        except Exception: await ctx.send(txt)

    # region ISERO PATCH commission-checkout
    @commands.hybrid_command(name="checkoutimg", description="Képes rendelés lezárása és logolása.")
    async def checkoutimg(self, ctx: commands.Context, qty: int):
        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.reply("Csak csatornában használható.")
        unit = float(os.getenv("IMG_BASE_PRICE_USD", "6") or "6")
        bulk_min = int(os.getenv("IMG_BULK_MIN_QTY", "4") or "4")
        off = float(os.getenv("IMG_BULK_OFF_USD", "1") or "1")
        sub, disc, total = calc_images(unit, qty, bulk_min, off)
        items = f"{qty} × Kép @ ${unit:.2f}  =  ${sub:.2f}"
        if disc > 0:
            items += f"\nKedvezmény (≥{bulk_min}): −${disc:.2f}"
        due = dt.datetime.utcnow() + dt.timedelta(days=int(os.getenv("TICKET_DEFAULT_SLA_DAYS","3") or "3"))
        tickets = getattr(self.bot, "get_cog", lambda _n: None)("Tickets")
        if not tickets:
            return await ctx.reply("Ticket rendszer nem elérhető.")
        emb = tickets.build_order_embed(kind="commission-image", opener=ctx.author, items_text=items, total_usd=total, due_utc=due)
        await tickets.post_order_log(channel=ctx.channel, embed=emb)
        try:
            await ctx.reply("Rendelés rögzítve (képek). ✅")
        except Exception:
            pass

    @commands.hybrid_command(name="checkoutvid", description="Videós rendelés lezárása és logolása.")
    async def checkoutvid(self, ctx: commands.Context, seconds_per_video: int, qty: int = 1):
        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.reply("Csak csatornában használható.")
        per5 = float(os.getenv("VID_PRICE_PER_5S_USD", "20") or "20")
        bulk_min = int(os.getenv("VID_BULK_MIN_QTY", "4") or "4")
        off = float(os.getenv("VID_BULK_OFF_USD", "5") or "5")
        per_video, sub, disc, total = calc_videos(per5, seconds_per_video, qty, bulk_min, off)
        items = f"{qty} × Videó @ ${per5:.0f}/5s  (videónként ~${per_video:.2f})  =  ${sub:.2f}"
        if disc > 0:
            items += f"\nKedvezmény (≥{bulk_min}): −${disc:.2f}"
        due = dt.datetime.utcnow() + dt.timedelta(days=int(os.getenv("TICKET_DEFAULT_SLA_DAYS","3") or "3"))
        tickets = getattr(self.bot, "get_cog", lambda _n: None)("Tickets")
        if not tickets:
            return await ctx.reply("Ticket rendszer nem elérhető.")
        emb = tickets.build_order_embed(kind="commission-video", opener=ctx.author, items_text=items, total_usd=total, due_utc=due)
        await tickets.post_order_log(channel=ctx.channel, embed=emb)
        try:
            await ctx.reply("Rendelés rögzítve (videók). ✅")
        except Exception:
            pass
    # endregion ISERO PATCH commission-checkout
# endregion ISERO PATCH commission-flow
