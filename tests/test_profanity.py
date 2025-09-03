import types
from cogs.watchers.profanity_watch import (
    ProfanityGuard,
    build_tolerant_pattern,
    soft_censor_text,
)
from discord.ext import commands
import discord


def test_variants_kurva():
    pat = build_tolerant_pattern(["kurva"])
    variants = [
        "kurva",
        "k u r v a",
        "k.u.r.v.a",
        "ku4v@",
        "k\nu\nrva",
        "kuuurva",
    ]
    for v in variants:
        _, cnt = soft_censor_text(v, pat)
        assert cnt == 1


def test_variants_geci():
    pat = build_tolerant_pattern(["geci"])
    variants = ["g3ci", "g e c i", "ge.ci", "gechi", "g\ne\nc\ni"]
    for v in variants:
        _, cnt = soft_censor_text(v, pat)
        assert cnt == 1


import asyncio


def test_nsfw_behavior():
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    guard = ProfanityGuard(bot)

    class Chan:
        id = 1
        mention = "#nsfw"

        def is_nsfw(self):
            return True

        async def send(self, *a, **kw):
            raise AssertionError("should not send in nsfw")

    class Guild:
        id = 1
        def __init__(self):
            self.me = types.SimpleNamespace(guild_permissions=types.SimpleNamespace(manage_messages=True))
        def get_channel(self, _):
            return None

    class Author:
        id = 2
        bot = False
        display_name = "x"
        mention = "@x"
        display_avatar = types.SimpleNamespace(url="")

    msg = types.SimpleNamespace(
        guild=Guild(),
        author=Author(),
        channel=Chan(),
        content="kurva",
        attachments=[],
        jump_url="url",
    )
    called = {}

    async def fake_log(guild, text, embed=None):
        called["logged"] = text

    guard.log = fake_log  # type: ignore
    asyncio.run(guard.on_message(msg))
    assert "kurva" in called.get("logged", "")


def test_echo_throttle():
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    guard = ProfanityGuard(bot)
    sent: list[str] = []

    class Chan:
        id = 2
        mention = "#gen"
        def is_nsfw(self):
            return False
        async def send(self, content, **kw):
            sent.append(content)

    class Guild:
        id = 1
        def __init__(self):
            self.me = types.SimpleNamespace(guild_permissions=types.SimpleNamespace(manage_messages=True))
        def get_channel(self, _):
            return None

    class Author:
        id = 3
        bot = False
        display_name = "y"
        mention = "@y"
        display_avatar = types.SimpleNamespace(url="")
        guild_permissions = types.SimpleNamespace(manage_guild=False)
        top_role = types.SimpleNamespace(permissions=types.SimpleNamespace(manage_guild=False))

    async def fake_delete():
        pass

    msg = types.SimpleNamespace(
        guild=Guild(),
        author=Author(),
        channel=Chan(),
        content="kurva",
        attachments=[],
        jump_url="u",
        delete=fake_delete,
    )

    asyncio.run(guard.on_message(msg))
    asyncio.run(guard.on_message(msg))
    assert len(sent) == 2  # first call echo + warning
