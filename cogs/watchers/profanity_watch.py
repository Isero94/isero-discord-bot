import asyncio
from discord.ext import commands
from loguru import logger
from cogs.utils import context as ctx_flags
from utils import policy, text as textutil
import re
from ..utils.profanity_patterns import build_patterns_with_sepmax, find_matches, mask_spans

WORDLIST = textutil.load_profanity_words()
logger.info(f"Loaded profanity wordlist ({len(WORDLIST)} entries)")
SEP_MAX = int(policy.getenv("PROFANITY_SEP_MAX", "4") or "4")
REPEAT_MAX = int(policy.getenv("PROFANITY_REPEAT_MAX", "6") or "6")
PATTERNS = build_patterns_with_sepmax(WORDLIST, sepmax=SEP_MAX, repeatmax=REPEAT_MAX)
USE_WEBHOOK = policy.getbool("USE_WEBHOOK_MIMIC", default=True)
MODE = policy.getenv("PROFANITY_MODE", "echo_star")

def build_tolerant_pattern(words):
    pats = build_patterns_with_sepmax(words, sepmax=SEP_MAX, repeatmax=REPEAT_MAX)
    return re.compile("|".join(p.pattern for p in pats), re.IGNORECASE | re.UNICODE)

def soft_censor_text(text, pattern):
    spans=[m.span() for m in pattern.finditer(text)]
    return star_mask(text, spans), len(spans)

def star_mask(text, spans):
    if not spans: return text
    cs=list(text)
    for a,b in spans:
        for k in range(a,b):
            if k not in (a,b-1) and not cs[k].isspace():
                cs[k]="*"
    return "".join(cs)

async def echo_censored(msg, txt):
    if USE_WEBHOOK:
        try:
            hooks=await msg.channel.webhooks()
            hook=next((h for h in hooks if h.name=="ISERO Echo"), None)
            if hook is None:
                hook=await msg.channel.create_webhook(name="ISERO Echo", reason="Profanity echo")
            await hook.send(txt, username=msg.author.display_name,
                            avatar_url=getattr(msg.author.display_avatar,"url",None),
                            allowed_mentions=None, wait=False)
            return
        except Exception as e:
            logger.warning(f"Webhook echo fallback: {e}")
    await msg.channel.send(txt, allowed_mentions=None)

class ProfanityWatcher(commands.Cog):
    def __init__(self, bot):
        self.bot=bot
        logger.info("Profanity Watcher v2 loaded (echo-star)")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        if ctx_flags.is_flagged(message):
            return
        txt = message.content or ""
        if not txt.strip():
            return
        spans = find_matches(PATTERNS, txt)
        if not spans:
            return
        ctx_flags.mark_moderated(message)
        ctx_flags.mark_hidden(message)
        try:
            await message.delete()
        except Exception:
            pass
        starred = mask_spans(txt, spans)
        await textutil.send_audit(self.bot, policy.getint("CHANNEL_MOD_LOGS",0), message, reason="profanity", original=txt, redacted=starred)
        if policy.is_nsfw(message.channel):
            return
        await textutil.echo_masked(self.bot, message, starred, ttl_s=policy.getint("PROFANITY_ECHO_TTL_S",30))
        if policy.is_exempt_user(message.author):
            return
        # scoring hook placeholder

async def setup(bot):
    await bot.add_cog(ProfanityWatcher(bot))

# backwards compat
ProfanityGuard = ProfanityWatcher
