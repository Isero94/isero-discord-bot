try:
    import regex as re
except Exception:
    import re
import asyncio
from discord.ext import commands
from loguru import logger
from cogs.utils import context as ctx_flags
from utils import policy, text as textutil

# region ISERO PATCH profanity_sep_and_variants
# Toleráns elválasztó: szóköz, NBSP, \W, szám, aláhúzás – max 3 jel
SEP = r"(?:[\s\N{NO-BREAK SPACE}\W\d_]{0,3})"

WORDLIST = textutil.load_profanity_words()
logger.info(f"Loaded profanity YAML ({len(WORDLIST)} words)")
USE_WEBHOOK = policy.getbool("USE_WEBHOOK_MIMIC", default=True)
MODE = policy.getenv("PROFANITY_MODE", "echo_star")

VAR = {"a":"[aá4@]","e":"[eé3]","i":"[ií1l]","o":"[oó0]","u":"[uúűü]","c":"c(?:h)?","sz":"s(?:z)?"}
def build_token(tok:str)->str:
    tok=tok.lower()
    parts=[]
    i=0
    while i<len(tok):
        if tok[i:i+2]=="sz":
            parts.append(VAR["sz"]+"+")
            i+=2
            continue
        ch=tok[i]
        parts.append(VAR.get(ch, re.escape(ch))+"+")
        i+=1
    return SEP.join(parts)
TOKENS={w:re.compile(build_token(w), re.IGNORECASE|re.UNICODE) for w in WORDLIST}
TOKENS["bazd"+SEP+"meg"]=re.compile("bazd"+SEP+"meg", re.IGNORECASE|re.UNICODE)
# endregion ISERO PATCH profanity_sep_and_variants

def build_tolerant_pattern(words):
    parts=[f"(?:{build_token(w)})" for w in words]
    return re.compile("|".join(parts), re.IGNORECASE|re.UNICODE)

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
        spans=[]
        words=[]
        for pat in TOKENS.values():
            for m in pat.finditer(txt):
                spans.append((m.start(),m.end()))
                words.append(m.group(0))
        if not spans:
            return
        ctx_flags.mark_moderated(message)
        ctx_flags.mark_hidden(message)
        try:
            await message.delete()
        except Exception:
            pass
        starred = textutil.star_mask_all(txt, match_words=words)
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
