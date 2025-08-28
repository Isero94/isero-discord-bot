import asyncio, time, os
from typing import Optional
import discord
from discord.ext import commands, tasks
from openai import OpenAI
from config import CHANNELS, CATEGORIES, INTENT_KEYWORDS, STAFF_CHAT, OWNER_ID, NSFW_CHANNELS
from .profiles import Profiles
OPENAI_KEY=os.getenv('OPENAI_API_KEY',''); client=OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None
ISERO_SYSTEM=('You are Isero: sharp, stylish, human-sounding strategist. Be succinct, friendly, mysterious. No hard-sell. Public short; owner gets long technical. If NSFW but allowed: stay tasteful, avoid explicit sexual content; redirect to commission/ticket if needed.')
class TicketForm(discord.ui.Modal, title='ISERO – Ticket form'):
    def __init__(self):
        super().__init__(timeout=None)
        self.req=discord.ui.TextInput(label='Kérelem (max 800 karakter)',style=discord.TextStyle.paragraph,max_length=800,required=True)
        self.refs=discord.ui.TextInput(label='Referenciák (max 4 URL, vesszővel)',style=discord.TextStyle.short,max_length=400,required=False)
        self.deadline=discord.ui.TextInput(label='Határidő (opcionális)',style=discord.TextStyle.short,max_length=100,placeholder="YYYY-MM-DD vagy 'nincs'")
        self.add_item(self.req); self.add_item(self.refs); self.add_item(self.deadline)
    async def on_submit(self,interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True,thinking=False)
        ch=interaction.channel
        if not ch: return
        emb=discord.Embed(title='Ticket – Beküldött űrlap',description=(f"**Felhasználó:** {interaction.user.mention}\n**Kérelem:**\n{self.req.value}\n\n**Referenciák:** {self.refs.value or '—'}\n**Határidő:** {self.deadline.value or '—'}\n\n*Megjegyzés:* A legtöbb megrendelés **3 napon** belül készül el. Ha több idő kell, a boss jelezni fogja."),color=0x00B894)
        await ch.send(embed=emb)
class TicketHubView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label='Commission',style=discord.ButtonStyle.primary,custom_id='isero:ticket:commission')
    async def btn_comm(self,interaction,button): await self._open_ticket(interaction,'commission')
    @discord.ui.button(label='Mebinu',style=discord.ButtonStyle.secondary,custom_id='isero:ticket:mebinu')
    async def btn_meb(self,interaction,button): await self._open_ticket(interaction,'mebinu')
    @discord.ui.button(label='General Support',style=discord.ButtonStyle.success,custom_id='isero:ticket:general')
    async def btn_gen(self,interaction,button): await self._open_ticket(interaction,'general')
    async def _open_ticket(self,interaction,category:str):
        await interaction.response.defer(ephemeral=True,thinking=False)
        g=interaction.guild; u=interaction.user
        cat_id=CATEGORIES.get('tickets'); cat=g.get_channel(cat_id) if cat_id else None
        overw={g.default_role:discord.PermissionOverwrite(read_messages=False),u:discord.PermissionOverwrite(read_messages=True,send_messages=True),g.me:discord.PermissionOverwrite(read_messages=True,send_messages=True)}
        name=f"ticket-{u.name[:20].lower()}-{int(time.time())%10000:04d}"
        ch=await g.create_text_channel(name=name,category=cat,overwrites=over,topic=f'Ticket for {u.id} [{category}]')
        await ch.send(f"{u.mention} Üdv! Röviden írd le a helyzetet. **Max 300 karakter/üzenet**, összesen **10 üzenet**. 10 perc inaktivitás után jön az űrlap.")
        from .profiles import DB_PATH; import aiosqlite
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR REPLACE INTO tickets (guild_id,channel_id,user_id,opened_ts,last_user_msg_ts,user_msg_count,status,category) VALUES (?,?,?,?,?,?,?,?)',(g.id,ch.id,u.id,time.time(),None,0,'open',category)); await db.commit()
        await ch.send(view=FormPromptView())
class FormPromptView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label='Megnyitom az űrlapot',style=discord.ButtonStyle.primary,custom_id='isero:ticket:openform')
    async def open_form(self,interaction,button): await interaction.response.send_modal(TicketForm())
async def ai_quick_response(prompt:str)->Optional[str]:
    if not client: return None
    try:
        resp=client.responses.create(model='gpt-4o-mini',input=ISERO_SYSTEM+'\nUser: '+prompt+'\nIsero:')
        return (resp.output_text or '').strip()[:1800]
    except: return None
class AgentGate(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.agent_enabled=True; self.inactivity_checker.start()
    def cog_unload(self): self.inactivity_checker.cancel()
    async def ensure_ticket_hub_buttons(self):
        hub=self.bot.get_channel(CHANNELS.get('ticket_hub'))
        if hub:
            try:
                hist=[m async for m in hub.history(limit=10)]
                if not any(m.components for m in hist):
                    await hub.send('Nyiss ticketet az alábbi gombokkal:',view=TicketHubView())
            except: pass
    @commands.Cog.listener()
    async def on_ready(self): await self.ensure_ticket_hub_buttons()
    @tasks.loop(minutes=1)
    async def inactivity_checker(self):
        from .profiles import DB_PATH; import aiosqlite
        now=time.time()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT channel_id,user_id,last_user_msg_ts,user_msg_count FROM tickets WHERE status='open'") as cur:
                rows=await cur.fetchall()
        for ch_id,uid,last_ts,count in rows:
            ch=self.bot.get_channel(ch_id)
            if not ch: continue
            if last_ts is None:
                try:
                    first=[m async for m in ch.history(limit=1,oldest_first=True)]
                    opened_ago=time.time()-first[0].created_at.timestamp() if first else 0
                except: opened_ago=0
                if opened_ago>600:
                    await ch.send('10 perc telt el válasz nélkül. Töltsd ki az űrlapot:',view=FormPromptView())
                continue
            if (now-last_ts)>600:
                await ch.send('10 perc telt el az utolsó válasz óta. Íme az űrlap:',view=FormPromptView())
    @commands.Cog.listener()
    async def on_message(self,message:discord.Message):
        if not message.guild or message.author.bot: return
        if isinstance(message.channel,discord.TextChannel) and message.channel.category_id==CATEGORIES.get('tickets'):
            if message.author==self.bot.user: return
            if len(message.content)>300:
                try: await message.delete()
                except: pass
                await message.channel.send(f'{message.author.mention} Max 300 karakter/üzenet a ticketben. Röviden fogalmazz, kérlek.'); return
            from .profiles import DB_PATH; import aiosqlite
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE tickets SET user_msg_count=user_msg_count+1,last_user_msg_ts=? WHERE channel_id=?',(time.time(),message.channel.id)); await db.commit()
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT user_msg_count FROM tickets WHERE channel_id=?',(message.channel.id,)) as cur:
                    row=await cur.fetchone()
            if row and row[0]>=10:
                await message.channel.send('Elérted a 10 üzenetes limitet. Kérlek töltsd ki az űrlapot:',view=FormPromptView())
            return
        if message.channel.id in NSFW_CHANNELS:
            if client and self.agent_enabled:
                txt=await ai_quick_response(f'NSFW-friendly but tasteful reply to: {message.content[:600]}')
                if txt:
                    try: await message.channel.send(txt)
                    except: pass
            return
        general_ids={1409935279099346985,1409931600489353298}
        if message.channel.id in general_ids and self.agent_enabled and client:
            if 8<=len(message.content)<=220 and ('?' in message.content or any(k in message.content.lower() for k in ['idea','help','tip','advice','price','commission','mebinu'])):
                reply=await ai_quick_response(message.content[:600])
                if reply:
                    try: await message.channel.send(reply[:350])
                    except: pass
    async def _staff_only(self,ctx): return ctx.channel and ctx.channel.id==STAFF_CHAT
    def _is_owner(self,user): return OWNER_ID and user.id==OWNER_ID
    @commands.group(name='agent',invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def agent_group(self,ctx):
        if not await self._staff_only(ctx): return
        await ctx.reply(f'Agent enabled: **{self.agent_enabled}** | OpenAI: **{"ON" if client else "OFF"}**')
    @agent_group.command(name='enable')
    @commands.has_permissions(administrator=True)
    async def agent_enable(self,ctx,flag:bool):
        if not await self._staff_only(ctx): return
        self.agent_enabled=bool(flag); await ctx.reply(f'Agent enabled set to **{self.agent_enabled}**')
    @agent_group.command(name='say')
    @commands.has_permissions(administrator=True)
    async def agent_say(self,ctx,channel:discord.TextChannel,*,text:str):
        if not await self._staff_only(ctx): return
        await channel.send(text[:1900]); await ctx.reply('✅ Sent.')
    @agent_group.command(name='exec')
    @commands.has_permissions(administrator=True)
    async def agent_exec(self,ctx,*,text:str):
        if not await self._staff_only(ctx): return
        if not self._is_owner(ctx.author): return await ctx.reply('Ezt a parancsot csak Alexa használhatja.')
        tl=text.lower()
        if 'reload' in tl and 'cog' in tl:
            try:
                parts=text.split(); target=next((p for p in parts if p.startswith('cogs.')),None)
                if not target: return await ctx.reply('Add meg: cogs.nev')
                await self.bot.reload_extension(target); return await ctx.reply(f'♻️ Újratöltve: {target}')
            except Exception as e: return await ctx.reply(f'Reload hiba: {e}')
        if 'enable agent' in tl: self.agent_enabled=True; return await ctx.reply('Agent **enabled**.')
        if 'disable agent' in tl: self.agent_enabled=False; return await ctx.reply('Agent **disabled**.')
        return await ctx.reply("Oké, jegyeztem. (Tipp: 'reload cog cogs.moderation')")
async def setup(bot): await bot.add_cog(AgentGate(bot)); bot.add_view(TicketHubView())
