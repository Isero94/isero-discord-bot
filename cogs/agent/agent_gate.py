import os
import re
import asyncio
from typing import Optional, Callable, Awaitable, List

import discord
from discord.ext import commands

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
# Wake-words: első a hivatalos név ("Isero"), de a félregépelést is elfogadjuk.
WAKE_WORDS = [w.strip().lower() for w in os.getenv("WAKE_WORDS", "isero,issero").split(",")]
HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0"))


class AgentGate(commands.Cog):
    """
    Természetes nyelvű OWNER gateway.
    Csak az OWNER_ID-től jövő, wake-wordöt tartalmazó üzenetekre reagál.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------- belső segédek -------------

    def _has_wake(self, content: str) -> bool:
        lc = content.lower()
        return any(w in lc for w in WAKE_WORDS)

    async def _owner_status(self, channel: discord.abc.Messageable) -> None:
        try:
            loaded = sorted(self.bot.cogs.keys())
            ping_ms = int(self.bot.latency * 1000) if self.bot.latency is not None else -1
            guilds = len(self.bot.guilds)
            text = (
                "✅ **Isero státusz**\n"
                f"- Guilds: **{guilds}**\n"
                f"- Ping: **{ping_ms} ms**\n"
                f"- Betöltött cogs: `{', '.join(loaded)}`\n"
            )
            await channel.send(text)
        except Exception as e:
            await channel.send(f"⚠️ Státusz lekérdezés hiba: `{e}`")

    async def _cleanup_hub(self, channel: discord.abc.Messageable) -> None:
        # Döntsük el, hol dolgozzunk
        target_channel: discord.abc.Messageable = channel
        if HUB_CHANNEL_ID:
            ch = self.bot.get_channel(HUB_CHANNEL_ID)
            if ch is None:
                # fallback: fetch_channel, ha nincs cache-ben
                try:
                    ch = await self.bot.fetch_channel(HUB_CHANNEL_ID)
                except Exception as e:
                    await channel.send(f"⚠️ Nem érem el a hub csatornát (`{HUB_CHANNEL_ID}`): `{e}`")
                    return
            target_channel = ch  # type: ignore[assignment]

        # Töröljük a bot régi hub-posztjait (ahol értelmezett a purge, pl. TextChannel)
        deleted = 0
        try:
            if isinstance(target_channel, discord.TextChannel):
                def _is_bot(m: discord.Message) -> bool:
                    return m.author.id == self.bot.user.id if self.bot.user else False
                purged = await target_channel.purge(limit=100, check=_is_bot)
                deleted = len(purged)
            else:
                # Thread vagy DM esetén egyenként megyünk végig
                async for m in target_channel.history(limit=50):  # type: ignore[attr-defined]
                    if self.bot.user and m.author.id == self.bot.user.id:
                        try:
                            await m.delete()
                            deleted += 1
                            await asyncio.sleep(0.2)
                        except Exception:
                            pass
        except discord.Forbidden:
            await channel.send("❌ Nincs jogosultságom törölni a hub csatornában.")
            return
        except Exception as e:
            await channel.send(f"⚠️ Törlés közben hiba történt: `{e}`")
            # nem állunk le, megpróbáljuk kirakni a hubot

        # Hub újrakirakása: megpróbáljuk a Tickets cog publikus metódusait meghívni
        tickets = self.bot.get_cog("Tickets")
        posted = False
        if tickets:
            candidate_methods: List[str] = [
                "post_ticket_hub",
                "post_hub",
                "setup_hub",
                "show_hub",
            ]
            for name in candidate_methods:
                func: Optional[Callable[..., Awaitable]] = getattr(tickets, name, None)  # type: ignore[assignment]
                if callable(func):
                    try:
                        await func(target_channel)  # type: ignore[misc]
                        posted = True
                        break
                    except TypeError:
                        # lehet, hogy nincs paramétere; próbáljuk paraméter nélkül
                        try:
                            await func()  # type: ignore[misc]
                            posted = True
                            break
                        except Exception:
                            continue
                    except Exception:
                        continue

        if not posted:
            # Ha nincs publikus metódus, adjunk instrukciót
            await target_channel.send("ℹ️ Hub üzenet nem posztolható automatikusan. "
                                      "Futtasd a **/ticket_hub_setup** vagy **/ticket_hub_cleanup** parancsot.")

        await channel.send(f"🧹 Kész. Törölve: **{deleted}** üzenet. "
                           f"Csatorna: <#{getattr(target_channel, 'id', 0)}>")

    # ------------- eseménykezelő -------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ne reagáljon a saját és más botok üzenetére
        if message.author.bot:
            return
        # csak az OWNER
        if message.author.id != OWNER_ID:
            return
        # DM-ben és guildben is működjön
        content = message.content.strip()
        if not content:
            return
        if not self._has_wake(content):
            return

        lc = content.lower()

        # egyszerű intentek
        if re.search(r"\bstatus\b|\bstátusz\b", lc):
            await self._owner_status(message.channel)
            return

        if "takarítsd" in lc and "hub" in lc:
            await self._cleanup_hub(message.channel)
            return
        if "cleanup" in lc and "hub" in lc:
            await self._cleanup_hub(message.channel)
            return

        # help
        await message.channel.send(
            "👋 **Isero** itt. Parancsok:\n"
            "• `Isero status` – állapotjelentés\n"
            "• `Isero takarítsd a hubot` – ticket-hub rendberakás"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
