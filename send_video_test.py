from dotenv import load_dotenv
import os
import asyncio
from pathlib import Path
from telegram import Bot

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

VIDEO_PATH = Path("output/sample_overlay.mp4")

CAPTION = """Mọi thứ lúc đầu đều khó, rồi sẽ dễ dần khi bạn quen với nó.

— Johann Wolfgang von Goethe

#trichdanmoingay #wisdom"""

async def main():
    if not VIDEO_PATH.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {VIDEO_PATH}")

    bot = Bot(token=TOKEN)

    with open(VIDEO_PATH, "rb") as f:
        await bot.send_video(
            chat_id=CHAT_ID,
            video=f,
            caption=CAPTION
        )

asyncio.run(main())