FEATURE_NAME = "ticket_hub"

import discord
import asyncio
from typing import Optional, List, Dict

from discord.ext import commands
from loguru import logger

from bot.config import (
    CATEGORIES, PRECHAT_TURNS, PRECHAT_MSG_CHAR_LIMIT,
    TICKET_TEXT_MAXLEN, TICKET_IMG_MAX, NSFW_AGEGATE_REQUIRED,
    TICKET_HUB_CHANNEL_ID, ARCHIVES_CHANNEL_ID
)
from cogs.utils.ai import short_reply

# ---- Ticket state ----
class TicketState:
    def __init__(self, thread: discord.Thread, user: discord.Member, cat_key: str):
        self.thread = thread
        self.user = user
        self.cat_key = cat_key  # 'mebinu' | 'commission' | 'nsfw' | 'general'
        self.closed = False
        # Pre-chat counters
        self.user_turns = 0
        self.agent_turns = 0
        # Final data
        self.final_text: Optional[str] = None
        self.attachments: List[str] = []
        # NSFW flag
        self.age_ok: bool = (cat_key != "nsfw")

    def touch(self):
        pass

# In-memory state:
