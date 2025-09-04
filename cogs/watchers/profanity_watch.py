try:
    import regex as re
except Exception:
    import re
import asyncio
from discord.ext import commands
from loguru import logger
from cogs.utils import context as ctx_flags
from utils import policy, throttling

SEP = r"[\s\N{NO-BREAK SPACE}\W\d_]{0,3}"
RAW_WORDS = policy.getenv("PROFANITY_WORDS", "")
WORDLIST = [w.strip() for w in RAW_WORDS.split(",") if w.strip()] or ["geci","kurva","bazdmeg","seggfej","anyad"]
EXEMPT_IDS = {int(s) for s in policy.getenv("PROFANITY_EXEMPT_USER_IDS","" ).replace(" ","").split(",") if s.isdigit()}
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
        self.throttle=throttling.PerUserChannelTTL(policy.getint("PROFANITY_ECHO_TTL_S",30))
        logger.info("Profanity Watcher v2 loaded (echo-star)")
    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot: return
        if ctx_flags.is_flagged(self.bot, message): return
        txt=message.content or ""
        if not txt.strip(): return
        spans=[]
        for pat in TOKENS.values():
            for m in pat.finditer(txt): spans.append((m.start(),m.end()))
        if not spans: return
        ctx_flags.mark_moderated(self.bot, message)
        ctx_flags.mark_hidden(self.bot, message)
        censored=star_mask(txt, spans)
        try: await message.delete()
        except Exception as e: logger.debug(f"delete failed: {e}")
        if policy.is_nsfw(message.channel):
            return
        if MODE=="echo_star" and self.throttle.allow(message.author.id, message.channel.id):
            await echo_censored(message, censored)
        if message.author.id in EXEMPT_IDS: return
        # scoring hook left here if throttling helper exists
        # from utils.throttling import add_profanity_strike
        # await add_profanity_strike(self.bot, message.author, message.channel)
async def setup(bot): await bot.add_cog(ProfanityWatcher(bot))

# backwards compat
ProfanityGuard = ProfanityWatcher
