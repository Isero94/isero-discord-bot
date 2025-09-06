import os
import types
import discord
import asyncio
from discord.ext import commands

from cogs.tickets.tickets import Tickets

class DummyChannel:
    def __init__(self, id=123, topic="type=general"):
        self.id = id
        self.topic = topic
        self.sent = []
        self._history = []
        self.guild = types.SimpleNamespace(get_channel=lambda _id: None)
    @property
    def mention(self):
        return f"<#${self.id}>".replace("$", "")
    async def send(self, content=None, embed=None, **kwargs):
        self.sent.append((content, embed))
    def history(self, limit=100, oldest_first=False):
        async def gen():
            msgs = self._history if oldest_first else list(reversed(self._history))
            count = 0
            for m in msgs:
                if count >= limit:
                    break
                count += 1
                yield m
        return gen()

class DummyAuthor:
    id = 42
    bot = False
    mention = "@user"
    display_name = "user"
    roles = []

class DummyAttachment:
    def __init__(self, url):
        self.url = url

async def setup_bot():
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    tickets = Tickets(bot)
    await bot.add_cog(tickets)
    return bot, tickets

def test_ticket_auto_submit_first_msg(monkeypatch):
    os.environ["TICKET_AUTO_SUBMIT_ON_FIRST_MSG"] = "true"
    os.environ["TICKET_MIN_CHARS"] = "5"
    os.environ["TICKET_NOTIFY_CHANNEL_ID"] = "999"
    os.environ["TICKET_PING_OWNER_ON_NEW"] = "false"

    bot, tickets = asyncio.run(setup_bot())
    notify = DummyChannel(id=999, topic="")
    bot.get_channel = lambda _id: notify if _id == 999 else None
    ch = DummyChannel()
    msg = types.SimpleNamespace(author=DummyAuthor(), channel=ch, content="hello world", attachments=[])
    ch._history.append(msg)
    asyncio.run(tickets.on_message(msg))
    assert any("Rögzítettem" in (c or "") for c, _ in ch.sent)
    assert len(notify.sent) == 1

def test_no_agent_no_legacy(monkeypatch):
    os.environ["TICKET_AUTO_SUBMIT_ON_FIRST_MSG"] = "true"
    os.environ["TICKET_MIN_CHARS"] = "5"
    os.environ["TICKET_NOTIFY_CHANNEL_ID"] = "999"
    os.environ["TICKET_PING_OWNER_ON_NEW"] = "false"

    bot, tickets = asyncio.run(setup_bot())
    notify = DummyChannel(id=999, topic="")
    bot.get_channel = lambda _id: notify if _id == 999 else None
    ch = DummyChannel()
    msg = types.SimpleNamespace(author=DummyAuthor(), channel=ch, content="hello world", attachments=[])
    ch._history.append(msg)
    asyncio.run(tickets.on_message(msg))
    sent_texts = " ".join((c or "") for c, _ in ch.sent)
    assert "ISERO" not in sent_texts
    assert "Melyik termék" not in sent_texts

def test_submit_cmd(monkeypatch):
    os.environ["TICKET_AUTO_SUBMIT_ON_FIRST_MSG"] = "false"
    os.environ["TICKET_NOTIFY_CHANNEL_ID"] = "999"
    os.environ["TICKET_PING_OWNER_ON_NEW"] = "false"

    bot, tickets = asyncio.run(setup_bot())
    notify = DummyChannel(id=999, topic="")
    bot.get_channel = lambda _id: notify if _id == 999 else None
    ch = DummyChannel()
    msg = types.SimpleNamespace(author=DummyAuthor(), channel=ch, content="manual content", attachments=[DummyAttachment("u1")])
    ch._history.append(msg)
    asyncio.run(tickets.on_message(msg))  # should not auto log
    assert len(notify.sent) == 0

    async def reply(content, **kwargs):
        await ch.send(content)
    ctx = types.SimpleNamespace(channel=ch, reply=reply)
    asyncio.run(tickets.submit(ctx))
    assert len(notify.sent) == 1
    assert any("Rögzítettem" in (c or "") for c, _ in ch.sent)
