from __future__ import annotations

import sqlite3
from typing import Iterable

from config import load_config


SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS used_quotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quote_hash TEXT NOT NULL UNIQUE,
        source_name TEXT NOT NULL,
        source_url TEXT,
        original_quote TEXT NOT NULL,
        author_name TEXT,
        author_display TEXT NOT NULL,
        vi_full TEXT NOT NULL,
        vi_short TEXT NOT NULL,
        lane TEXT,
        mood TEXT,
        used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_used_quotes_author
    ON used_quotes(author_display);
    """,
    """
    CREATE TABLE IF NOT EXISTS media_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        media_key TEXT NOT NULL UNIQUE,
        media_source TEXT NOT NULL,
        media_url TEXT NOT NULL,
        media_type TEXT NOT NULL,
        used_in_video_slug TEXT,
        used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_media_usage_used_at
    ON media_usage(used_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_slug TEXT NOT NULL UNIQUE,
        video_path TEXT NOT NULL,
        metadata_path TEXT,
        source_name TEXT NOT NULL,
        source_url TEXT,
        quote_hash TEXT,
        author_display TEXT NOT NULL,
        lane TEXT,
        mood TEXT,
        caption_text TEXT,
        hashtags_json TEXT,
        status TEXT NOT NULL DEFAULT 'created',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        sent_to_telegram_at TEXT,
        telegram_message_id TEXT,
        FOREIGN KEY (quote_hash) REFERENCES used_quotes(quote_hash)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_videos_created_at
    ON videos(created_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date TEXT NOT NULL,
        attempt_number INTEGER NOT NULL,
        status TEXT NOT NULL,
        error_step TEXT,
        error_message TEXT,
        started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at TEXT
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_runs_run_date
    ON runs(run_date);
    """,
]


def get_connection() -> sqlite3.Connection:
    config = load_config()
    conn = sqlite3.connect(config.db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.commit()


def list_tables() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
            """
        ).fetchall()
    return [row["name"] for row in rows]


if __name__ == "__main__":
    init_db()
    print("Database OK")
    print("Tables:")
    for table_name in list_tables():
        print(f"- {table_name}")