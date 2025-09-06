import os
import types
import asyncio
import discord
from discord.ext import commands

from cogs.agent.agent_gate import AgentGate
from cogs.tickets.mebinu_flow import MebinuFlow

class DummyChannel:
    def __init__(self):
        self.id = 123
        self.topic = "type=mebinu"
        self.name = "ticket"
        self.category = None
        self.guild = None
        self.sent = []
    async def send(self, content=None, **kwargs):
        self.sent.append(content)
    def history(self, **kwargs):
        async def gen():
            return
            yield
        return gen()

class DummyAuthor:
    id = 55
    bot = False
    mention = "@u"
    display_name = "user"
    roles = []

def test_mebinu_autostart(monkeypatch):
    os.environ["AGENT_AUTO_START_ON_FIRST_MSG"] = "true"
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    ag = AgentGate(bot)
    mf = MebinuFlow(bot)
    asyncio.run(bot.add_cog(ag))
    asyncio.run(bot.add_cog(mf))
    ch = DummyChannel()
    msg = types.SimpleNamespace(author=DummyAuthor(), channel=ch, content="hello", guild=object())
    asyncio.run(mf.on_message(msg))
    assert ag.is_active(ch.id)
    assert not any("Melyik termék" in (m or "") for m in ch.sent)


def test_startagent_command():
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    ag = AgentGate(bot)
    asyncio.run(bot.add_cog(ag))
    ch = DummyChannel()
    async def reply(content, **kwargs):
        await ch.send(content)
    ctx = types.SimpleNamespace(channel=ch, author=DummyAuthor(), reply=reply)
    asyncio.run(ag.startagent(ctx))
    assert ag.is_active(ch.id)
