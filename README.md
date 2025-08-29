# ISERO Discord Bot — FINAL COGS SKELETON

Generated: 2025-08-29T21:52:39

This is a **production-ready skeleton** using your **/bot + /cogs** structure.
It includes:
- **TicketHub** with 4 fixed categories (Mebinu, Commission, NSFW 18+, General Help)
- **NSFW 18+ age-gate**
- **Pre-chat**: ≤300 chars/message, **max 10 rounds** (user + Isero)
- **Final commission**: ≤800 chars + **≤4 images**
- Strong **logging** (stdout + opt. Discord log mirror)
- Centralized **limits & UI copy** in `bot/config.py`
- Simple **JSON storage** by default (swappable later)

## Quick start
1. `cp .env.example .env` and fill values
2. `pip install -r requirements.txt`
3. `python -m bot.bot`
4. Use `!ticket_hub` in your Ticket Hub channel to post the start button.

## Deploy on Render
- Uses `render.yaml` worker. Auto-deploy should just work.
