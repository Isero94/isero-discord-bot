import asyncio

# Call the async main() that lives in /bot/bot.py
from bot.bot import main

if __name__ == "__main__":
    asyncio.run(main())
