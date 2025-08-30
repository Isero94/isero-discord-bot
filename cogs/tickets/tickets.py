# cogs/tickets/tickets.py
# Teljes, önállóan bemásolható verzió (slash + szöveg-parancs fallback)

from __future__ import annotations
import os, re, logging, asyncio, time
from typing import Optional, Literal

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

def _to_int(env: str, default: int = 0) -> int:
    try: return int((os.getenv(env) or "").strip() or default)
    except: return default

def _slugify(s: str) -> str:
    s = re.sub(r"\s+", "-", (s or "").lower().strip())
    s = re.sub(r"[^a-z0-9\-_.]", "", s).strip("-._")
    return s or "user"

class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.hub_channel_id = _to_int("TICKET_HUB_CHANNEL_ID")
        self.ticket_category_id = _to_int("TICKETS_CATEGORY_ID")
        self.archive_category_id = _to_int("ARCHIVE_CATEGORY_ID") or None
        self.cooldown_secs = _to_int("TICKET_COOLDOWN_SECONDS", 20)
        self.cooldowns: dict[int, float] = {}
        self._views_added = False

    async def cog_load(self):
        if not self._views_added:
            self.bot.add_view(HubView(self))  # persistent
            self._views_added = True
        log.info("[ISERO] Tickets cog loaded (persistent view ready)")

    # ---------- helpers ----------
    async def get_hub_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        ch = guild.get_channel(self.hub_channel_id)
        return ch if isinstance(ch, discord.TextChannel) else None

    def get_ticket_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        cat = guild.get_channel(self.ticket_category_id)
        return cat if isinstance(cat, discord.CategoryChannel) else None

    def get_archive_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        if not self.archive_category_id: return None
        cat = guild.get_channel(self.archive_category_id)
        return cat if isinstance(cat, discord.CategoryChannel) else None

    async def post_hub(self, channel: discord.TextChannel):
        embed = discord.Embed(
            title="Ticket Hub",
            description="Nyomd meg az **Open Ticket** gombot. A következő lépésben kategóriát választasz.",
            color=discord.Color.blurple(),
        ).set_footer(text="A kategóriaválasztás ezután jön (ephemeral).")
        await channel.send(embed=embed, view=HubView(self))

    async def has_open_ticket(self, guild: discord.Guild, user_id: int) -> bool:
        cat = self.get_ticket_category(guild)
        if not cat: return False
        for ch in cat.channels:
            if isinstance(ch, discord.TextChannel) and ch.topic:
                if f"owner:{user_id}" in ch.topic and not ch.name.startswith("arch-"):
                    return True
        return False

    def _category_embed(self) -> discord.Embed:
        return discord.Embed(
            title="Válassz kategóriát:",
            description=("• **Mebinu** — gyűjthető figurák\n"
                         "• **Commission** — fizetős munka\n"
                         "• **NSFW 18+** — felnőtt tartalom\n"
                         "• **General Help** — gyors segítség"),
            color=discord.Color.dark_theme()
        )

    async def _cleanup_and_repost(self, channel: discord.TextChannel, deep: bool) -> int:
        deleted = 0
        async for m in channel.history(limit=None, oldest_first=False):
            if m.author == self.bot.user:
                try:
                    await m.delete()
                    deleted += 1
                except discord.HTTPException:
                    pass
        await self.post_hub(channel)
        return deleted

    async def create_ticket_channel(self, interaction: discord.Interaction,
                                    category_key: Literal["mebinu","commission","nsfw","help"]) -> discord.TextChannel:
        guild = interaction.guild; assert guild
        cat = self.get_ticket_category(guild)
        if not cat: raise RuntimeError("TICKETS_CATEGORY_ID nincs jól beállítva.")
        uname = _slugify(interaction.user.name)
        base, name = f"{category_key}-{uname}", None
        i = 1
        while True:
            cand = base if i == 1 else f"{base}-{i}"
            if not discord.utils.get(cat.channels, name=cand):
                name = cand; break
            i += 1
        topic = f"owner:{interaction.user.id} | opened:{discord.utils.utcnow().isoformat()}"
        ch = await guild.create_text_channel(name=name, category=cat, topic=topic)
        greet = discord.Embed(
            title="Üdv a ticketedben!",
            description="Írd le, miben segíthetünk. Lezárás: **/close**",
            color=discord.Color.green()
        ).set_footer(text=f"Kategória: {category_key.upper()} • Tulaj: {interaction.user.name}")
        await ch.send(content=interaction.user.mention, embed=greet)
        return ch

    # ---------- slash parancsok ----------
    @app_commands.command(name="ticket_hub_setup", description="Hub panel kihelyezése (opcionális takarítással).")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_hub_setup(self, interaction: discord.Interaction, cleanup: Optional[bool] = False):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild;  hub = await self.get_hub_channel(guild) if guild else None
        if not hub: return await interaction.followup.send("TICKET_HUB_CHANNEL_ID nincs jól beállítva.", ephemeral=True)
        deleted = await self._cleanup_and_repost(hub, deep=False) if cleanup else 0 or await self.post_hub(hub)
        await interaction.followup.send(f"Hub kész. Törölt üzenetek: **{deleted or 0}**", ephemeral=True)

    @app_commands.command(name="ticket_hub_cleanup", description="Takarítás + hub visszarakás.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, deep: Optional[bool] = False):
        await interaction.response.defer(ephemeral=True)
        ch = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
        if not ch: return await interaction.followup.send("Nem szövegcsatorna.", ephemeral=True)
        deleted = await self._cleanup_and_repost(ch, bool(deep))
        await interaction.followup.send(f"Cleanup kész. Törölve: **{deleted}**", ephemeral=True)

    @app_commands.command(name="close", description="Aktuális ticket lezárása/archiválása.")
    async def close_ticket(self, interaction: discord.Interaction, reason: Optional[str] = None):
        ch = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
        if not ch or not (ch.topic and "owner:" in ch.topic):
            return await interaction.response.send_message("Ez nem ticket csatorna.", ephemeral=True)

        is_staff = interaction.user.guild_permissions.manage_channels
        is_owner = False
        m = re.search(r"owner:(\d+)", ch.topic or "")
        if m and int(m.group(1)) == interaction.user.id: is_owner = True
        if not (is_staff or is_owner):
            return await interaction.response.send_message("Nincs jogod lezárni ezt a ticketet.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild;  assert guild
        new_name = ch.name if ch.name.startswith("arch-") else f"arch-{ch.name}"
        new_cat = self.get_archive_category(guild) or ch.category
        try: await ch.edit(name=new_name, category=new_cat)
        except discord.HTTPException as e: log.warning("Archive edit failed: %r", e)
        await interaction.followup.send("Ticket archiválva. Köszönjük!", ephemeral=True)

    # ---------- Fallback: sima üzenetes „/parancsok” ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        content = message.content.strip().lower()

        if not (content.startswith("/ticket_hub_setup") or content.startswith("/ticket_hub_cleanup")):
            return

        perms = message.author.guild_permissions
        if not (perms.manage_messages or perms.manage_channels or perms.administrator):
            return  # csak staff

        ch = message.channel
        if not isinstance(ch, discord.TextChannel): return

        try:
            if content.startswith("/ticket_hub_setup"):
                # ha a sorban szerepel 'cleanup:true' akkor takarítunk is
                cleanup = "cleanup:true" in content or "clean:true" in content
                if cleanup:
                    deleted = await self._cleanup_and_repost(ch, deep=False)
                    await ch.send(f"✅ Hub kész. Törölve: **{deleted}**", delete_after=8)
                else:
                    await self.post_hub(ch)
                    await ch.send("✅ Hub kihelyezve.", delete_after=8)

            elif content.startswith("/ticket_hub_cleanup"):
                deep = "deep:true" in content
                deleted = await self._cleanup_and_repost(ch, deep=deep)
                await ch.send(f"🧹 Cleanup kész. Törölve: **{deleted}**", delete_after=8)
        except Exception as e:
            log.exception("Text fallback error: %r", e)
            await ch.send("❌ Hiba történt a művelet közben.", delete_after=8)

class HubView(discord.ui.View):
    def __init__(self, cog: Tickets):
        super().__init__(timeout=None); self.cog = cog

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, _):
        await self.cog.on_open_ticket_clicked(interaction)

class CategoryView(discord.ui.View):
    def __init__(self, cog: Tickets):
        super().__init__(timeout=180); self.cog = cog

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.secondary)
    async def mebinu(self, i: discord.Interaction, _): await self.cog.on_category_chosen(i, "mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary)
    async def commission(self, i: discord.Interaction, _): await self.cog.on_category_chosen(i, "commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger)
    async def nsfw(self, i: discord.Interaction, _): await self.cog.on_category_chosen(i, "nsfw")

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success)
    async def help(self, i: discord.Interaction, _): await self.cog.on_category_chosen(i, "help")

class NSFWConfirmView(discord.ui.View):
    def __init__(self, cog: Tickets):
        super().__init__(timeout=60); self.cog = cog

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes(self, i: discord.Interaction, _): await self.cog.on_nsfw_confirm(i, True)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, i: discord.Interaction, _): await self.cog.on_nsfw_confirm(i, False)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
