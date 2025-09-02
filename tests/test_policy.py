from utils.policy import ResponderPolicy, DecideResult
from cogs.utils.context import MessageContext
from bot.config import settings


def _ctx(**kwargs):
    base = dict(
        guild_id=1,
        channel_id=0,
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
    )
    base.update(kwargs)
    return MessageContext(**base)


def test_general_chat_requires_trigger():
    settings.CHANNEL_GENERAL_CHAT = 1
    ctx = _ctx(channel_id=1)
    res = ResponderPolicy.decide(ctx)
    assert not res.should_reply
    ctx2 = _ctx(channel_id=settings.CHANNEL_GENERAL_CHAT, was_mentioned=True)
    res2 = ResponderPolicy.decide(ctx2)
    assert res2.mode == "short" and res2.should_reply


def test_ticket_hub_free_text_silent():
    settings.CHANNEL_TICKET_HUB = 2
    ctx = _ctx(channel_id=2, trigger="free_text")
    res = ResponderPolicy.decide(ctx)
    assert not res.should_reply


def test_announcements_redirect():
    settings.CHANNEL_ANNOUNCEMENTS = 3
    ctx = _ctx(channel_id=3)
    res = ResponderPolicy.decide(ctx)
    assert res.mode == "redirect"


def test_ticket_guided():
    ctx = _ctx(is_ticket=True, ticket_type="mebinu")
    res = ResponderPolicy.decide(ctx)
    assert res.mode == "guided"


def test_nsfw_redirect_if_not_allowed():
    settings.CATEGORY_NSFW = 99
    ctx = _ctx(is_ticket=True, ticket_type="nsfw", category_id=0)
    res = ResponderPolicy.decide(ctx)
    assert res.mode == "redirect"
