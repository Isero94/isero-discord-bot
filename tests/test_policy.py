from utils.policy import ResponderPolicy, DecideResult
from cogs.utils.context import MessageContext
from bot.config import settings
from utils.policy import ResponderPolicy


def _ctx(**kwargs):
    base = dict(
        guild_id=1,
        channel_id=0,
        channel_name="chan",
        content="",
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


def test_reply_limit_default():
    ctx = _ctx()
    assert ResponderPolicy.get_reply_limit(ctx) == 300


def test_owner_override_and_question():
    settings.CHANNEL_GENERAL_CHAT = 10
    settings.CHANNEL_BOT_COMMANDS = 11
    settings.CHANNEL_SUGGESTIONS = 12
    settings.OWNER_ID = 42
    ctx_owner = _ctx(channel_id=10, is_owner=True)
    res_owner = ResponderPolicy.decide(ctx_owner)
    assert res_owner.reason == "owner_override" and res_owner.should_reply

    ctx_q = _ctx(channel_id=11, content="help?", is_owner=False)
    res_q = ResponderPolicy.decide(ctx_q)
    assert res_q.reason == "question_in_general" and res_q.should_reply

    ctx_silent = _ctx(channel_id=11, content="hello", is_owner=False)
    res_silent = ResponderPolicy.decide(ctx_silent)
    assert not res_silent.should_reply


def test_owner_override_in_talk_category():
    settings.CATEGORY_SOCIAL = 50
    ctx = _ctx(channel_id=123, category_id=50, is_owner=True)
    res = ResponderPolicy.decide(ctx)
    assert res.reason == "owner_override" and res.should_reply


def test_quiet_unquiet():
    ctx = _ctx(channel_id=5)
    ResponderPolicy.quiet_channel(5, ttl=60)
    res = ResponderPolicy.decide(ctx)
    assert not res.should_reply and res.reason == "channel_quiet"
    ResponderPolicy.unquiet_channel(5)
    res2 = ResponderPolicy.decide(ctx)
    assert res2.should_reply
