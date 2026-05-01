from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
TEMP_MEDIA_DIR = BASE_DIR / "temp_media"
MUSIC_DIR = BASE_DIR / "music"
STATE_DIR = BASE_DIR / "state"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = STATE_DIR / "app.db"


@dataclass(frozen=True)
class AppConfig:
    base_dir: Path
    output_dir: Path
    temp_media_dir: Path
    music_dir: Path
    state_dir: Path
    logs_dir: Path
    db_path: Path

    telegram_bot_token: str
    telegram_chat_id: str
    pexels_api_key: str
    google_api_key: str

    channel_name: str
    fixed_hashtag: str
    run_start: str
    run_deadline: str

    videos_per_day: int
    temp_media_retention_days: int
    media_repeat_window_days: int


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Thiếu biến môi trường bắt buộc: {name}")
    return value


def ensure_directories() -> None:
    for path in [OUTPUT_DIR, TEMP_MEDIA_DIR, MUSIC_DIR, STATE_DIR, LOGS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    load_dotenv()
    ensure_directories()

    return AppConfig(
        base_dir=BASE_DIR,
        output_dir=OUTPUT_DIR,
        temp_media_dir=TEMP_MEDIA_DIR,
        music_dir=MUSIC_DIR,
        state_dir=STATE_DIR,
        logs_dir=LOGS_DIR,
        db_path=DB_PATH,

        telegram_bot_token=_required_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_required_env("TELEGRAM_CHAT_ID"),
        pexels_api_key=_required_env("PEXELS_API_KEY"),
        google_api_key=_required_env("GOOGLE_API_KEY"),

        channel_name=os.getenv("CHANNEL_NAME", "Trích dẫn mỗi ngày").strip(),
        fixed_hashtag=os.getenv("FIXED_HASHTAG", "#trichdanmoingay").strip(),
        run_start=os.getenv("RUN_START", "15:30").strip(),
        run_deadline=os.getenv("RUN_DEADLINE", "16:00").strip(),

        videos_per_day=2,
        temp_media_retention_days=3,
        media_repeat_window_days=30,
    )


if __name__ == "__main__":
    config = load_config()
    print("Config OK")
    print(f"BASE_DIR: {config.base_dir}")
    print(f"DB_PATH: {config.db_path}")
    print(f"OUTPUT_DIR: {config.output_dir}")
    print(f"TEMP_MEDIA_DIR: {config.temp_media_dir}")
    print(f"MUSIC_DIR: {config.music_dir}")
    print(f"CHANNEL_NAME: {config.channel_name}")
    print(f"FIXED_HASHTAG: {config.fixed_hashtag}")
    print(f"RUN_WINDOW: {config.run_start} -> {config.run_deadline}")