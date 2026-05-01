from dotenv import load_dotenv
import os
from telegram import Bot
import asyncio

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def main():
    bot = Bot(token=TOKEN)
    await bot.send_message(
        chat_id=CHAT_ID,
        text="Test OK. Bot đã gửi được tin nhắn vào Telegram."
    )

asyncio.run(main())