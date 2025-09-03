import types
import time
import types
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from cogs.agent.agent_gate import AgentGate
from cogs.utils.context import MessageContext
import discord
from discord.ext import commands
from bot.config import settings


class DummyMsg:
    def __init__(self, content, author_id=1, channel_id=1):
        self.content = content
        self.author = types.SimpleNamespace(id=author_id)
        self.channel = types.SimpleNamespace(id=channel_id)


def _ctx(**kw):
    base = dict(
        guild_id=1,
        channel_id=1,
        channel_name="chan",
        category_id=None,
        category_name=None,
        is_thread=False,
        is_ticket=False,
        ticket_type=None,
        is_nsfw=False,
        is_owner=False,
        is_staff=False,
        locale="en",
        user_display="user",
        content="",
    )
    base.update(kw)
    return MessageContext(**base)


def test_ai_gate_owner_override():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    ag = AgentGate(bot)
    ctx = _ctx(channel_id=2, is_owner=True)
    msg = DummyMsg("hello", author_id=1, channel_id=2)
    assert ag._ai_gate(msg, ctx)


def test_ai_gate_limit():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    ag = AgentGate(bot)
    settings.FEATURES_AI_GATE_V1 = True
    settings.AI_MAX_CALLS_PER_USER_HOUR = 2
    settings.AI_DEBOUNCE_MS = 0
    ctx = _ctx(content="help?", channel_id=1)
    msg = DummyMsg("help?", author_id=5, channel_id=1)
    assert ag._ai_gate(msg, ctx)
    assert ag._ai_gate(msg, ctx)
    assert not ag._ai_gate(msg, ctx)
