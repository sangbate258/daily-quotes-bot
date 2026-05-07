from __future__ import annotations
import time
from typing import Any
import os
import json
import requests
import re
from dotenv import load_dotenv

BASE_URL = "https://api.giphy.com/v1/gifs/search"
QUERY_STOPWORDS = {
    "a",
    "an",
    "the",
    "of",
    "in",
    "on",
    "to",
    "for",
    "with",
    "one",
    "person",
    "people",
    "someone",
    "somebody",
    "very",
    "really",
    "just",
    "that",
    "this",
    "those",
    "these",
    "fast",
    "moving",
}
_GIPHY_DISABLED_UNTIL = 0.0


class GiphyRateLimitError(RuntimeError):
    pass


def _giphy_cooldown_seconds() -> int:
    value = os.getenv("GIPHY_RATE_LIMIT_COOLDOWN_SEC", "1800").strip()
    try:
        return int(value)
    except ValueError:
        return 1800


def _giphy_is_temporarily_disabled() -> bool:
    return time.time() < _GIPHY_DISABLED_UNTIL


def compact_giphy_query(query: str, max_words: int = 5) -> str:
    tokens = re.findall(r"[a-zA-Z]+", (query or "").lower())
    filtered = [t for t in tokens if t not in QUERY_STOPWORDS and len(t) >= 3]

    if not filtered:
        filtered = tokens[:max_words]

    return " ".join(filtered[:max_words])


def _require_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("GIPHY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Thiếu GIPHY_API_KEY trong file .env")
    return api_key


def _pick_best_media(images: dict[str, Any]) -> dict[str, Any]:
    mp4_candidates = [
        images.get("original", {}),
        images.get("downsized", {}),
        images.get("fixed_height", {}),
        images.get("preview", {}),
    ]

    mp4_url = ""
    width = None
    height = None

    for item in mp4_candidates:
        if item.get("mp4"):
            mp4_url = item["mp4"]
            width = item.get("width")
            height = item.get("height")
            break

    gif_candidates = [
        images.get("original", {}),
        images.get("downsized", {}),
        images.get("fixed_height", {}),
    ]

    gif_url = ""
    for item in gif_candidates:
        if item.get("url"):
            gif_url = item["url"]
            if width is None:
                width = item.get("width")
            if height is None:
                height = item.get("height")
            break

    return {
        "mp4_url": mp4_url,
        "gif_url": gif_url,
        "width": width,
        "height": height,
    }


def search_giphy(
    query: str, limit: int = 10, rating: str = "g"
) -> list[dict[str, Any]]:
    global _GIPHY_DISABLED_UNTIL

    if _giphy_is_temporarily_disabled():
        remaining = int(_GIPHY_DISABLED_UNTIL - time.time())
        print(f"[GIPHY SKIP] rate limit cooldown active for {remaining}s: {query}")
        raise GiphyRateLimitError(f"GIPHY cooldown active. Remaining {remaining}s.")

    api_key = _require_api_key()
    compact_query = compact_giphy_query(query)

    params = {
        "api_key": api_key,
        "q": compact_query,
        "limit": limit,
        "rating": rating,
        "lang": "en",
    }

    print(f"[GIPHY] original query: {query}")
    print(f"[GIPHY] compact query: {compact_query}")

    try:
        resp = requests.get(BASE_URL, params=params, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(
            f"GIPHY request failed for query='{compact_query}': {type(e).__name__}"
        ) from e

    if resp.status_code == 429:
        cooldown = _giphy_cooldown_seconds()
        _GIPHY_DISABLED_UNTIL = time.time() + cooldown
        print(
            f"[GIPHY RATE LIMIT] 429 Too Many Requests. Disable GIPHY for {cooldown}s."
        )
        raise GiphyRateLimitError(f"GIPHY rate limited. Cooldown {cooldown}s.")

    if not resp.ok:
        raise RuntimeError(
            f"GIPHY HTTP {resp.status_code} for query='{compact_query}'. "
            "API key hidden from logs."
        )

    payload = resp.json()
    results: list[dict[str, Any]] = []

    for item in payload.get("data", []):
        media = _pick_best_media(item.get("images", {}))

        results.append(
            {
                "source": "giphy",
                "media_id": item.get("id"),
                "title": item.get("title", "").strip(),
                "page_url": item.get("url", "").strip(),
                "mp4_url": media["mp4_url"],
                "gif_url": media["gif_url"],
                "width": media["width"],
                "height": media["height"],
            }
        )

    return results


if __name__ == "__main__":
    sample_query = "be yourself crowd identity"
    items = search_giphy(sample_query, limit=5)

    print(f"Found {len(items)} items for query: {sample_query}\n")
    print(json.dumps(items, ensure_ascii=False, indent=2))
