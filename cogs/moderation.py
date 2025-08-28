import re, datetime
import discord
from discord.ext import commands
from langdetect import detect
from config import DEFAULT_SWEARWORDS, MAX_SWEARS_FREE_PER_MESSAGE, HITS_STAGE0_TO_TIMEOUT, TIMEOUT_STAGE0_MINUTES, TIMEOUT_STAGE1_HOURS, TIMEOUT_STAGE2_DAYS, CHANNELS, LANGUAGE_REMINDER_EVERY
from .profiles import Profiles
WORD_RE=re.compile(r"[\w\-']+",re.UNICODE)
def count_swears(text,swearset):
    tokens=WORD_RE.findall(text.lower()); return sum(1 for t in tokens for s in swearset if s in t)
class Moderation(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.swearset=set(DEFAULT_SWEARWORDS)
    async def timeout_member(self,member,minutes,reason):
        try: await member.timeout(datetime.timedelta(minutes=minutes),reason=reason); return True
        except: return False
    async def stage_action(self,message,swears,prof):
        g=message.guild; m=message.author; stage=prof['stage']
        if stage==0 and swears>=(MAX_SWEARS_FREE_PER_MESSAGE+1):
            nh=prof['swear_hits']+1; await Profiles.update_profile(g.id,m.id,swear_hits=nh)
            if nh>=HITS_STAGE0_TO_TIMEOUT:
                await self.timeout_member(m,TIMEOUT_STAGE0_MINUTES,'Stage0 limit');
                await Profiles.update_profile(g.id,m.id,stage=1,swear_hits=0,timeouts=prof['timeouts']+1)
                await self._log(f'Stage 0 -> 1 | {m} 40p timeout')
                try: await message.reply('4 találat összegyűlt (≥3 csúnya szó/üzenet). 40 perc némítás, Stage 1.')
                except: pass
            else:
                try: await message.reply(f'Figyi: {nh}/4 találat a Stage 0-ban. 2-ig szabad, 3-tól számolunk.')
                except: pass
            return
        if stage==1 and swears>=2:
            await self.timeout_member(m,TIMEOUT_STAGE1_HOURS*60,'Stage1 limit');
            await Profiles.update_profile(g.id,m.id,stage=2,timeouts=prof['timeouts']+1)
            await self._log(f'Stage 1 -> 2 | {m} 8h timeout')
            try: await message.reply('Stage 1 megszegve (≥2 csúnya szó). 8 óra némítás, Stage 2.')
            except: pass
            return
        if stage==2 and swears>=1:
            await self.timeout_member(m,TIMEOUT_STAGE2_DAYS*24*60,'Stage2 limit');
            await Profiles.update_profile(g.id,m.id,perma_flag=1,timeouts=prof['timeouts']+1)
            await self._log(f'Stage 2 near-permanent | {m} 28 nap timeout')
            try: await message.reply('Stage 2: egyetlen csúnya szó is tiltott. 28 nap némítás. 24 óra múlva fellebbezhetsz ticketen.')
            except: pass
    async def _log(self,text):
        ch=self.bot.get_channel(CHANNELS.get('mod_logs'))
        if ch: await ch.send(embed=discord.Embed(description=text,color=0xED4245))
    @commands.Cog.listener()
    async def on_message(self,message:discord.Message):
        if message.author.bot or not message.guild: return
        prof=await Profiles.get_profile(message.guild.id,message.author.id)
        nt=prof['msg_total']+1; ns=prof['msg_since_lang']+1
        # language reminder only if not EN/HU
        try:
            if ns>=LANGUAGE_REMINDER_EVERY:
                lang=detect(message.content[:200])
                if lang not in ('en','hu'):
                    try: await message.author.send('Preferált a **English** (vagy Hungarian is ok). Ha kell, használj fordítót. 🤝')
                    except: pass
                    ns=0
        except: pass
        await Profiles.update_profile(message.guild.id,message.author.id,msg_total=nt,msg_since_lang=ns,last_msg_ts=message.created_at.timestamp())
        swears=count_swears(message.content,self.swearset)
        if swears<=MAX_SWEARS_FREE_PER_MESSAGE: return
        await self.stage_action(message,swears,prof)
    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def addswear(self,ctx,*,word:str): self.swearset.add(word.lower()); await ctx.reply(f'Felvéve: **{word}**')
    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def rmswear(self,ctx,*,word:str): self.swearset.discard(word.lower()); await ctx.reply(f'Törölve: **{word}**')
async def setup(bot): await bot.add_cog(Moderation(bot))
