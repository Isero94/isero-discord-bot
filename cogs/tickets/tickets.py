import os
import typing as t
import discord
from discord import app_commands
from discord.ext import commands

FEATURE_NAME = "ticket_hub"  # marker a bot saját üzeneteinek azonosítására

# --- Konstansok (testreszabható) ------------------------------------------------

HUB_TITLE = "Üdv a(z) #️⃣ | ticket-hub!-ban!"
HUB_DESC = (
    "Válassz kategóriát a gombokkal. A rendszer külön privát threadet nyit neked.\n\n"
    "**Mebinu** — Gyűjthető figura kérések, variánsok, kódok, ritkaság.\n"
    "**Commission** — Fizetős, egyedi art megbízás (scope, budget, határidő).\n"
    "**NSFW 18+** — Csak 18+; szigorúbb szabályzat & review.\n"
    "**General Help** — Gyors kérdés–válasz, útmutatás."
)

# Gombok stílusa (discord.ButtonStyle): primary=blurple, secondary=szürke, success=zöld, danger=piros
BTN_STYLE = {
    "Mebinu": discord.ButtonStyle.primary,
    "Commission": discord.ButtonStyle.success,   # kérésedre külön (zöld) szín
    "NSFW 18+": discord.ButtonStyle.danger,
    "General Help": discord.ButtonStyle.secondary,
}

# Thread név minta
def thread_name(label: str, user: discord.abc.User) -> str:
    return f"{label.upper()} | {user.display_name}"


# --- View + gombok --------------------------------------------------------------

class TicketHubView(discord.ui.View):
    """Perzisztens view: restart után is élnek a gombok."""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

        self.add_item(HubButton(label="Mebinu", custom_id="isero:ticket:mebinu",
                                style=BTN_STYLE["Mebinu"]))
        self.add_item(HubButton(label="Commission", custom_id="isero:ticket:commission",
                                style=BTN_STYLE["Commission"]))
        self.add_item(HubButton(label="NSFW 18+", custom_id="isero:ticket:nsfw",
                                style=BTN_STYLE["NSFW 18+"]))
        self.add_item(HubButton(label="General Help", custom_id="isero:ticket:general",
                                style=BTN_STYLE["General Help"]))


class HubButton(discord.ui.Button):
    async def callback(self, interaction: discord.Interaction):
        assert interaction.user is not None
        label = self.label or "Ticket"
        channel = interaction.channel

        # Csak szövegcsatornákban működjön
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "Ezt a gombot szövegcsatornában tudod használni.", ephemeral=True
            )
            return

        parent_channel = channel.parent if isinstance(channel, discord.Thread) else channel

        # Privát thread nyitása
        try:
            tthread = await parent_channel.create_thread(
                name=thread_name(label, interaction.user),
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason=f"{FEATURE_NAME}: {interaction.user} kérte a(z) {label} threadet."
            )
            # Hozzáadjuk a felhasználót a privát threadhez
            await tthread.add_user(interaction.user)

            # Nyitó üzenet a threadben (nem árulunk el belső limit infót)
            open_msg = (
                f"Opened pre-chat for **{label}**.\n"
                "Írj pár mondatot a kérésedről / problémádról, és csatolj képet, ha kell. "
                "A staff hamarosan beköszön. "
                "Kérlek maradj a témánál ebben a threadben."
            )
            await tthread.send(open_msg, allowed_mentions=discord.AllowedMentions.none())

            await interaction.response.send_message(
                f"Thread opened: {tthread.mention}", ephemeral=True
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "Nincs jogosultságom privát threadet nyitni itt. Kérj meg egy admint, hogy engedélyezze.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Hiba történt a thread nyitásakor: `{type(e).__name__}: {e}`",
                ephemeral=True,
            )


# --- Cog ------------------------------------------------------------------------

class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Perzisztens view regisztráció – hogy reboot után is éljenek a gombok
        self.bot.add_view(TicketHubView(bot))

    # Segéd: ellenőrizd, hogy ticket-hubban fut-e a parancs
    def _ensure_in_hub(self, interaction: discord.Interaction) -> t.Optional[discord.TextChannel]:
        ch = interaction.channel
        if isinstance(ch, discord.TextChannel) and ch.name == "ticket-hub":
            return ch
        return None

    @app_commands.command(name="ticket_hub_setup", description="TicketHub beállítása / újraposztolása ebben a csatornában.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        hub_ch = self._ensure_in_hub(interaction)
        if hub_ch is None:
            await interaction.response.send_message(
                "Ezt a parancsot a **#ticket-hub** csatornában futtasd.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=HUB_TITLE,
            description=HUB_DESC,
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"feature={FEATURE_NAME}")

        view = TicketHubView(self.bot)

        # Posztoljuk a hub üzenetet
        await hub_ch.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())

        await interaction.response.send_message(
            f"Hub frissítve. Csatorna: {hub_ch.mention}",
            ephemeral=True
        )

    @app_commands.command(name="ticket_hub_cleanup", description="Korábbi TicketHub üzenetek törlése (a bot üzenetei).")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def ticket_hub_cleanup(self, interaction: discord.Interaction):
        hub_ch = self._ensure_in_hub(interaction)
        if hub_ch is None:
            await interaction.response.send_message(
                "Ezt a parancsot a **#ticket-hub** csatornában futtasd.",
                ephemeral=True
            )
            return

        deleted = 0
        # Csak a bot által küldött, ticket_hub feature-rel jelölt üziket töröljük
        async for msg in hub_ch.history(limit=200):
            if msg.author.id != self.bot.user.id:
                continue
            marker = False
            if msg.embeds:
                for emb in msg.embeds:
                    if (emb.footer and emb.footer.text and f"feature={FEATURE_NAME}" in emb.footer.text):
                        marker = True
                        break
            if msg.components:
                # Ha vannak gombok, az is erős jel, hogy a hub üzenet
                marker = True

            if marker:
                try:
                    await msg.delete()
                    deleted += 1
                except Exception:
                    pass

        await interaction.response.send_message(
            f"Hub takarítva. Törölve: **{deleted}** üzenet. Csatorna: {hub_ch.mention}",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
