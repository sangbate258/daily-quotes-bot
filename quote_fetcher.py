from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Tuple
import json
import os
import random
import re
import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

GOODREADS_URL = "https://www.goodreads.com/quotes"

# Fetcher V2:
# - Goodreads multi-page instead of only the first 20 quotes.
# - Randomized page order for testing/variety.
# - Still requests + BeautifulSoup only; no MCP/Playwright needed yet.
DEFAULT_GOODREADS_MAX_PAGES = int(os.getenv("GOODREADS_MAX_PAGES", "8"))
DEFAULT_RAW_QUOTES_LIMIT = int(os.getenv("RAW_QUOTES_LIMIT", "120"))
GOODREADS_SLEEP_SECONDS = float(os.getenv("GOODREADS_SLEEP_SECONDS", "0.6"))


@dataclass
class RawQuote:
    text: str
    author: str
    source_name: str
    source_url: str


def _get_html(url: str) -> str:
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def _clean_spaces(text: str) -> str:
    return " ".join(text.split()).strip()


def _clean_quote_text(text: str) -> str:
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\\", "")
    text = _clean_spaces(text)

    # bỏ quote mở/đóng nếu còn sót
    text = text.strip().strip('"').strip()

    # bỏ ký tự em dash ở cuối nếu còn sót
    text = re.sub(r"\s*―\s*$", "", text).strip()

    # bỏ quote đóng còn sót ở cuối
    text = re.sub(r'["“”]\s*$', "", text).strip()

    return text


def _goodreads_page_url(page: int) -> str:
    if page <= 1:
        return GOODREADS_URL
    return f"{GOODREADS_URL}?{urlencode({'page': page})}"


def _parse_goodreads_quotes_from_html(html: str, source_url: str) -> List[RawQuote]:
    soup = BeautifulSoup(html, "lxml")

    results: List[RawQuote] = []
    seen: set[Tuple[str, str]] = set()

    quote_blocks = soup.select("div.quoteText")

    for block in quote_blocks:
        # parse trên bản copy để thoải mái xóa tag
        block_copy = BeautifulSoup(str(block), "lxml")
        quote_div = block_copy.select_one("div.quoteText")
        if not quote_div:
            continue

        author_tag = quote_div.select_one("span.authorOrTitle")
        author = author_tag.get_text(" ", strip=True).strip(",") if author_tag else "Khuyết danh"

        # xóa những tag phụ để phần text còn lại sạch hơn
        for tag in quote_div.select("span.authorOrTitle, a.authorOrTitle, span.greyText.smallText"):
            tag.extract()

        raw_text = quote_div.get_text(" ", strip=True)
        quote_text = _clean_quote_text(raw_text)
        author = _clean_spaces(author)

        if not quote_text:
            continue

        key = (quote_text.lower(), author.lower())
        if key in seen:
            continue
        seen.add(key)

        results.append(
            RawQuote(
                text=quote_text,
                author=author if author else "Khuyết danh",
                source_name="goodreads",
                source_url=source_url,
            )
        )

    return results


def fetch_goodreads_quotes(
    limit: int = DEFAULT_RAW_QUOTES_LIMIT,
    *,
    max_pages: int = DEFAULT_GOODREADS_MAX_PAGES,
    randomize_pages: bool = True,
) -> List[RawQuote]:
    """
    Fetch multiple Goodreads quote pages.

    Why:
    The old fetcher only pulled https://www.goodreads.com/quotes and usually got
    the same first 20 quotes. After those were saved in used_quotes, filtering
    produced 0 candidates. This function scans several pages so the pipeline can
    keep finding fresh quotes.
    """
    page_numbers = list(range(1, max(1, max_pages) + 1))
    if randomize_pages:
        random.shuffle(page_numbers)

    results: List[RawQuote] = []
    seen: set[Tuple[str, str]] = set()

    for page in page_numbers:
        if len(results) >= limit:
            break

        url = _goodreads_page_url(page)

        try:
            html = _get_html(url)
            page_quotes = _parse_goodreads_quotes_from_html(html, source_url=url)
        except Exception as e:
            print(f"[WARN] goodreads page {page} failed: {e}")
            continue

        added = 0
        for q in page_quotes:
            key = (q.text.lower(), q.author.lower())
            if key in seen:
                continue
            seen.add(key)
            results.append(q)
            added += 1

            if len(results) >= limit:
                break

        print(f"[OK] goodreads page {page}: {added}/{len(page_quotes)} new quotes")

        # Be polite to the site; also reduces chance of transient blocking.
        if GOODREADS_SLEEP_SECONDS > 0:
            time.sleep(GOODREADS_SLEEP_SECONDS)

    return results


def fetch_all_raw_quotes() -> List[RawQuote]:
    quotes = fetch_goodreads_quotes(
        limit=DEFAULT_RAW_QUOTES_LIMIT,
        max_pages=DEFAULT_GOODREADS_MAX_PAGES,
        randomize_pages=True,
    )
    print(f"[OK] goodreads total: {len(quotes)} quotes")
    return quotes


if __name__ == "__main__":
    quotes = fetch_all_raw_quotes()
    print(f"\nTotal quotes fetched: {len(quotes)}\n")

    preview = [asdict(q) for q in quotes[:10]]
    print(json.dumps(preview, ensure_ascii=False, indent=2))
