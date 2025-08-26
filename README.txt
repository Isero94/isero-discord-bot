ISERO Discord Bot – Starter Pack

Mappaszerkezet:
isero-discord-bot/
├─ isero_bot.py
├─ requirements.txt
└─ cogs/
   ├─ __init__.py
   ├─ utility.py
   ├─ moderation.py
   └─ fun.py

Render beállítások:
- Build command:  pip install -r requirements.txt
- Start command:  python isero_bot.py
- Environment:    DISCORD_TOKEN = (a bot tokened)
- Opcionális:     GUILD_ID = (szerver ID – gyors slash sync)

Discord Dev Portal → OAuth2 URL Generator:
- Scopes: bot, applications.commands
- Permissions: legalább Send Messages, Read Message History (moderációhoz Manage Messages)

Parancsok:
- Prefix: !ping, !clear 10
- Slash:  /ping, /server_info, /clear, /roll
