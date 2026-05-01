from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import os
from db import get_connection
from quote_fetcher import RawQuote, fetch_all_raw_quotes


MAX_RAW_QUOTE_CHARS = 250


@dataclass
class CandidateQuote:
    quote_hash: str
    text: str
    author: str
    source_name: str
    source_url: str


def normalize_quote_text(text: str) -> str:
    return " ".join(text.strip().split())


def make_quote_hash(text: str) -> str:
    normalized = normalize_quote_text(text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def quote_exists_in_db(quote_hash: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM used_quotes
            WHERE quote_hash = ?
            LIMIT 1
            """,
            (quote_hash,),
        ).fetchone()
    return row is not None


def filter_quotes(raw_quotes: list[RawQuote]) -> list[CandidateQuote]:
    results: list[CandidateQuote] = []
    seen_in_batch: set[str] = set()

    for q in raw_quotes:
        text = normalize_quote_text(q.text)
        if not text:
            continue

        if len(text) > MAX_RAW_QUOTE_CHARS:
            continue

        quote_hash = make_quote_hash(text)

        if quote_hash in seen_in_batch:
            continue

        if os.getenv("IGNORE_USED_QUOTES_FOR_TEST", "0").strip() != "1":
            if quote_exists_in_db(quote_hash):
                continue

        seen_in_batch.add(quote_hash)

        results.append(
            CandidateQuote(
                quote_hash=quote_hash,
                text=text,
                author=q.author.strip() if q.author.strip() else "Khuyết danh",
                source_name=q.source_name,
                source_url=q.source_url,
            )
        )

    return results


if __name__ == "__main__":
    raw_quotes = fetch_all_raw_quotes()
    filtered = filter_quotes(raw_quotes)

    print(f"Raw quotes: {len(raw_quotes)}")
    print(f"Filtered quotes: {len(filtered)}\n")

    preview = [asdict(q) for q in filtered[:10]]
    print(json.dumps(preview, ensure_ascii=False, indent=2))