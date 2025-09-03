from cogs.tickets.mebinu_flow import MebinuSession, QUESTIONS
from cogs.tickets.tickets import TicketsCog
from bot.config import settings
from discord.ext import commands
import discord
import types
import asyncio

def test_flow_happy_path():
    s = MebinuSession()
    assert s.next_question() == QUESTIONS[0]
    s.record("figurát"); s.next_question()
    s.record("piros"); s.next_question()
    s.record("holnap"); s.next_question()
    s.record("1000 HUF"); s.next_question()
    s.record("igen");
    assert s.next_question() is None
    summary = s.summary()
    assert "figurát" in summary and "1000" in summary


def test_prefill_skips_questions():
    s = MebinuSession()
    s.prefill("Mebinu piros fekete")
    assert s.step == 2
    assert s.next_question() == QUESTIONS[2]


def test_old_template_disabled():
    settings.FEATURES_MEBINU_DIALOG_V1 = True
    sent = []

    class FakeResponse:
        async def send_message(self, content, **kw):
            sent.append(content)

    class FakeChannel:
        id = 1
        topic = "owner:1 | type:mebinu"

        def history(self, **kwargs):
            async def gen():
                yield types.SimpleNamespace(author=types.SimpleNamespace(id=1), content="Mebinu piros fekete")
            return gen()

    async def run():
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        cog = TicketsCog(bot)
        interaction = types.SimpleNamespace(
            user=types.SimpleNamespace(id=1, mention="@u"),
            channel=FakeChannel(),
            response=FakeResponse(),
            created_at=None,
        )
        await cog.start_isero_flow(interaction)

    asyncio.run(run())
    assert sent and "alcsomag" not in sent[0]
    assert "[3/5]" in sent[0]


def test_old_template_when_flag_off():
    settings.FEATURES_MEBINU_DIALOG_V1 = False
    sent = []

    class FakeResp:
        async def send_message(self, content, **kw):
            sent.append(content)

    class FakeChannel:
        id = 3
        topic = "owner:3 | type:mebinu"

    async def run():
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        cog = TicketsCog(bot)
        interaction = types.SimpleNamespace(user=types.SimpleNamespace(id=3, mention="@u"), channel=FakeChannel(), response=FakeResp(), created_at=None)
        await cog.start_isero_flow(interaction)

    asyncio.run(run())
    assert sent and "alcsomag" in sent[0]


def test_self_flow_modal_limit():
    sent = []

    class FakeResp:
        async def send_modal(self, modal):
            sent.append(modal)

    class FakeInteraction:
        user = types.SimpleNamespace(id=4)
        channel = types.SimpleNamespace(id=4, topic="owner:4 | type:mebinu")
        response = FakeResp()

    async def run():
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        cog = TicketsCog(bot)
        await cog.start_self_flow(FakeInteraction())

    asyncio.run(run())
    assert sent and getattr(sent[0].desc, "max_length", 0) == 800
