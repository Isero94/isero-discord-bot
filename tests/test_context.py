import asyncio
import discord

from cogs.utils.context import resolve


class DummyInteraction(discord.Interaction):
    def __init__(self):  # type: ignore[no-untyped-def]
        self.channel = type(
            "Chan",
            (),
            {
                "id": 123,
                "name": "chan",
                "category": type("Cat", (), {"id": 456, "name": "cat"})(),
                "guild": type("G", (), {"id": 1})(),
            },
        )()
        self.user = type("User", (), {"id": 1, "display_name": "U", "roles": [], "locale": "en"})()
        
    @property
    def channel_id(self):  # type: ignore[override]
        return 123
        self.user = type("User", (), {"id": 1, "display_name": "U", "roles": [], "locale": "en"})()
        self.locale = "en"
        self.guild = type("Guild", (), {"id": 1, "preferred_locale": "en"})()
        self.client = type("Client", (), {"fetch_channel": lambda self, cid: self})()


class DummyMessage(discord.Message):
    def __init__(self):  # type: ignore[no-untyped-def]
        self.channel = type(
            "Chan",
            (),
            {
                "id": 321,
                "name": "mchan",
                "category": type("Cat", (), {"id": 654, "name": "mcat"})(),
                "guild": type("G", (), {"id": 1})(),
            },
        )()
        self.content = "hi"
        self.author = type("User", (), {"id": 2, "display_name": "M", "roles": [], "locale": "en"})()
        self.mentions = []
        self.role_mentions = []
        self.attachments = []
        self.guild = self.channel.guild

def test_resolve_interaction():
    ctx = asyncio.run(resolve(DummyInteraction()))
    assert ctx.channel_id == 123
    assert ctx.category_id == 456
    assert ctx.char_limit > 0


def test_resolve_message():
    ctx = asyncio.run(resolve(DummyMessage()))
    assert ctx.channel_id == 321
    assert ctx.msg_chars == 2
    assert ctx.category_id == 654
