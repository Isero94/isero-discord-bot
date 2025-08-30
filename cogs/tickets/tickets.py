# cogs/tickets/tickets.py
from __future__ import annotations
import os, re, time, logging, asyncio
from typing import Optional, Literal

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# -------- utilok --------
def _to_int(env: str, default: int = 0) -> int:
    try:
        v = (os.getenv(env) or "").strip()
        return int(v) if v else default
    except Exception:
        return default

def _slugify(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-_.]", "", s).strip("-._")
    return s or "user"

# -------- a cog --------
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
        # Perzisztens view a régi Hub gombokra is
        if not self._views_added:
            self.bot.add_view(HubView(self))
            self._views_added = True
        log.info("[ISERO] Tickets cog loaded (persistent view ready)")

    # ---- helpers ----
    async def get_hub_channel(self, guild: discord.Guild | None) -> Optional[discord.TextChannel]:
        if not guild: return None
        ch = guild.get_channel(self.hub_channel_id)
        return ch if isinstance(ch, discord.TextChannel) else None

    def get_ticket_category(self, guild: discord.Guild | None) -> Optional[discord.CategoryChannel]:
        if not guild: return None
        cat = guild.get_channel(self.ticket_category_id)
        return cat if isinstance(cat, discord.CategoryChannel) else None

    def get_archive_category(self, guild: discord.Guild | None) -> Optional[discord.CategoryChannel]:
        if not guild or not self.archive_category_id: return None
        cat = guild.get_channel(self.archive_category_id)
        return cat if isinstance(cat, discord.CategoryChannel) else None

    async def post_hub(self, channel: discord.TextChannel):
        embed = (discord.Embed(
            title="Ticket Hub",
            description="Nyomd meg az **Open Ticket** gombot. A következő lépésben kategóriát választasz.",
            color=discord.Color.blurple(),
        ).set_footer(text="A kategóriaválasztás ezután jön (ephemeral)."))
        await channel.send(embed=embed, view=HubView(self))

    async def _cleanup_and_repost(self, channel: discord.TextChannel, deep: bool) -> int:
        deleted = 0
        async for m in channel.history(limit=None, oldest_first=False):
            if m.author == self.bot.user:
                try:
                    await m.delete()
                    deleted += 1
                except discord.HTTPException:
                    pass
            elif deep:
                # csak a bot üzeneteit töröljük biztosan; a deep itt most ugyanaz, csak hely a további finomításhoz
                pass
        await self.post_hub(channel)
        return deleted

    async def find_open_ticket_channel(self, guild: discord.Guild, user_id: int) -> Optional[discord.TextChannel]:
        cat = self.get_ticket_category(guild)
        if not cat: return None
        for ch in cat.channels:
            if isinstance(ch, discord.TextChannel) and (ch.topic or "").find(f"owner:{user_id}") != -1:
                if not ch.name.startswith("arch-"):
                    return ch
        return None

    async def has_open_ticket(self, guild: discord.Guild, user_id: int) -> bool:
        return (await self.find_open_ticket_channel(guild, user_id)) is not None

    def _category_embed(self) -> discord.Embed:
        return discord.Embed(
            title="Válassz kategóriát:",
            description=(
                "• **Mebinu** — gyűjthető figurák\n"
                "• **Commission** — fizetős egyedi munka\n"
                "• **NSFW 18+** — felnőtt tartalom (megerősítés szükséges)\n"
                "• **General Help** — gyors Q&A és útmutatás"
            ),
            color=discord.Color.dark_theme()
        )

    async def create_ticket_channel(
        self, interaction: discord.Interaction, category_key: Literal["mebinu","commission","nsfw","help"]
    ) -> discord.TextChannel:
        guild = interaction.guild; assert guild
        cat = self.get_ticket_category(guild)
        if not cat:
            raise RuntimeError("TICKETS_CATEGORY_ID nincs jól beállítva.")

        uname = _slugify(interaction.user.name)
        base = f"{category_key}-{uname}"
        i = 1
        while True:
            name = base if i == 1 else f"{base}-{i}"
            if not discord.utils.get(cat.channels, name=name):
                break
            i += 1

        topic = f"owner:{interaction.user.id} | opened:{discord.utils.utcnow().isoformat()}"
        overwrites = None  # ide tehetsz egyedi jogosultságokat ha szükséges
        ch = await guild.create_text_channel(name=name, category=cat, topic=topic, overwrites=overwrites)

        greet = (discord.Embed(
            title="Üdv a ticketedben!",
            description="Írd le, miben segíthetünk. Lezárás: **/close** (vagy staff zárja).",
            color=discord.Color.green()
        ).set_footer(text=f"Kategória: {category_key.upper()} • Tulaj: {interaction.user.name}"))

        await ch.send(content=interaction.user.mention, embed=greet)
        return ch

    # ---- BUTTON & SELECT HANDLERS ----
    async def on_open_ticket_clicked(self, interaction: discord.Interaction):
        # gyors válasz, hogy ne timeoutoljon: defer + későbbi followup
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            return await interaction.followup.send("Csak szerveren használható.", ephemeral=True)

        # már van nyitott?
        existing = await self.find_open_ticket_channel(guild, interaction.user.id)
        if existing:
            return await interaction.followup.send(
                f"Már van nyitott ticketed: {existing.mention}\n"
                "Kérjük, azt zárd le, mielőtt újat nyitsz.", ephemeral=True
            )

        # cooldown
        now = time.time()
        last = self.cooldowns.get(interaction.user.id, 0.0)
        left = int(self.cooldown_secs - (now - last))
        if left > 0:
            return await interaction.followup.send(
                f"Kérlek, várj még **{left}** másodpercet, mielőtt új ticketet nyitsz.", ephemeral=True
            )

        # mutatjuk a kategória választót (ephemeral)
        await interaction.followup.send(embed=self._category_embed(), view=CategoryView(self), ephemeral=True)

    async def on_category_chosen(self, i: discord.Interaction, key: Literal["mebinu","commission","nsfw","help"]):
        await i.response.defer(ephemeral=True)
        guild = i.guild; assert guild

        existing = await self.find_open_ticket_channel(guild, i.user.id)
        if existing:
            return await i.followup.send(
                f"Már van nyitott ticketed: {existing.mention}\nZárd le azt, mielőtt újat nyitsz.", ephemeral=True
            )

        if key == "nsfw":
            # plusz megerősítés
            return await i.followup.send("Elmúltál 18 éves?", view=NSFWConfirmView(self), ephemeral=True)

        # létrehozás
        ch = await self.create_ticket_channel(i, key)
        self.cooldowns[i.user.id] = time.time()
        await i.followup.send(f"Kész! A ticketed: {ch.mention}", ephemeral=True)

    async def on_nsfw_confirm(self, i: discord.Interaction, yes: bool):
        if not yes:
            return await i.response.send_message("Megszakítva. Nem nyitottunk NSFW ticketet.", ephemeral=True)

        await i.response.defer(ephemeral=True)
        guild = i.guild; assert guild

        existing = await self.find_open_ticket_channel(guild, i.user.id)
        if existing:
            return await i.followup.send(
                f"Már van nyitott ticketed: {existing.mention}\nZárd le azt, mielőtt újat nyitsz.", ephemeral=True
            )

        ch = await self.create_ticket_channel(i, "nsfw")
        self.cooldowns[i.user.id] = time.time()
        await i.followup.send(f"Kész! A ticketed: {ch.mention}", ephemeral=True)

    # ---- SLASH parancsok ----
    @app_commands.command(name="ticket_hub_setup", description="Hub panel kihelyezése (opciósan takarítással).")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_hub_setup(self, interaction: discord.Interaction, cleanup: Optional[bool] = False):
        await interaction.response.defer(ephemeral=True)
        hub = await self.get_hub_channel(interaction.guild)
        if not hub:
            return await interaction.followup.send("TICKET_HUB_CHANNEL_ID nincs jól beállítva.", ephemeral=True)

        deleted = 0
        if cleanup:
            deleted = await self._cleanup_and_repost(hub, deep=False)
        else:
            await self.post_hub(hub)

        await interaction.followup.send(f"Hub kész. Törölt üzenetek: **{deleted}**", ephemeral=True)

    @app_commands.command(name="ticket_hub_cleanup", description="Takarítás + hub visszarakás.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, deep: Optional[bool] = False):
        await interaction.response.defer(ephemeral=True)
        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel):
            return await interaction.followup.send("Nem szövegcsatorna.", ephemeral=True)

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
        if m and int(m.group(1)) == interaction.user.id:
            is_owner = True

        if not (is_staff or is_owner):
            return await interaction.response.send_message("Nincs jogod lezárni ezt a ticketet.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild; assert guild
        new_name = ch.name if ch.name.startswith("arch-") else f"arch-{ch.name}"
        new_cat = self.get_archive_category(guild) or ch.category
        try:
            await ch.edit(name=new_name, category=new_cat)
        except discord.HTTPException as e:
            log.warning("Archive edit failed: %r", e)

        await interaction.followup.send("Ticket archiválva. Köszönjük!", ephemeral=True)

    # ---- Fallback: szöveges „/parancsok” staffnak ----
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        content = message.content.strip().lower()
        if not (content.startswith("/ticket_hub_setup") or content.startswith("/ticket_hub_cleanup")):
            return

        perms = message.author.guild_permissions
        if not (perms.manage_messages or perms.manage_channels or perms.administrator):
            return  # csak staff használhatja

        ch = message.channel
        if not isinstance(ch, discord.TextChannel):
            return

        try:
            if content.startswith("/ticket_hub_setup"):
                cleanup = "cleanup:true" in content or "clean:true" in content
                if cleanup:
                    deleted = await self._cleanup_and_repost(ch, deep=False)
                    await ch.send("✅ Hub kész (takarítva).", delete_after=8)
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

# -------- UI osztályok --------
class HubView(discord.ui.View):
    def __init__(self, cog: Tickets):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, _):
        await self.cog.on_open_ticket_clicked(interaction)

class CategoryView(discord.ui.View):
    def __init__(self, cog: Tickets):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.secondary)
    async def mebinu(self, i: discord.Interaction, _):
        await self.cog.on_category_chosen(i, "mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary)
    async def commission(self, i: discord.Interaction, _):
        await self.cog.on_category_chosen(i, "commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger)
    async def nsfw(self, i: discord.Interaction, _):
        await self.cog.on_category_chosen(i, "nsfw")

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success)
    async def help(self, i: discord.Interaction, _):
        await self.cog.on_category_chosen(i, "help")

class NSFWConfirmView(discord.ui.View):
    def __init__(self, cog: Tickets):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes(self, i: discord.Interaction, _):
        await self.cog.on_nsfw_confirm(i, True)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, i: discord.Interaction, _):
        await self.cog.on_nsfw_confirm(i, False)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
