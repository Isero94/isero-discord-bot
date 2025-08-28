import os
GUILD_ID=int(os.getenv('GUILD_ID','0'))
OWNER_ID=int(os.getenv('OWNER_ID','0'))
CHANNELS={'mod_logs':int(os.getenv('CHANNEL_MOD_LOGS','1409966648378785842')),'logs':int(os.getenv('CHANNEL_GENERAL_LOGS','1410503173231349780')),'mod_queue':int(os.getenv('CHANNEL_MOD_QUEUE','1409966496578535527')),'ticket_hub':int(os.getenv('CHANNEL_TICKET_HUB','1410509056988151809'))}
CATEGORIES={'tickets':int(os.getenv('CATEGORY_TICKETS','1410508478514073670'))}
STAFF_CHAT=int(os.getenv('STAFF_CHAT','1409944966024663101'))
NSFW_CHANNELS={int(x) for x in os.getenv('NSFW_CHANNELS','').split(',') if x.strip().isdigit()}
MAX_SWEARS_FREE_PER_MESSAGE=2
HITS_STAGE0_TO_TIMEOUT=4
TIMEOUT_STAGE0_MINUTES=40
TIMEOUT_STAGE1_HOURS=8
TIMEOUT_STAGE2_DAYS=28
LANGUAGE_REMINDER_EVERY=5
DEFAULT_SWEARWORDS={'fasz','geci','picsa','kurva','bazd','bazmeg','basz','szar','csicska','buzi','fuck','shit','bitch','asshole','bastard','dick','cunt','motherfucker'}
INTENT_KEYWORDS={'commission','price','order','buy','how much','mebinu','adoptable','adopt','nsfw','custom','pay','paypal','offer','deal','purchase'}
