from __future__ import annotations

from typing import Any
import os
import json
import requests

from dotenv import load_dotenv


BASE_URL = "https://api.pexels.com/videos/search"


def _require_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Thiếu PEXELS_API_KEY trong file .env")
    return api_key


def search_pexels_videos(query: str, limit: int = 10) -> list[dict[str, Any]]:
    api_key = _require_api_key()

    headers = {
        "Authorization": api_key
    }

    params = {
        "query": query,
        "per_page": limit,
    }

    resp = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
    resp.raise_for_status()

    payload = resp.json()
    results: list[dict[str, Any]] = []

    for item in payload.get("videos", []):
        video_files = item.get("video_files", [])
        best_file = None

        # ưu tiên file mp4 gần 720x1280 hoặc portrait hơn
        def score(vf: dict[str, Any]) -> tuple[int, int]:
            w = vf.get("width", 99999)
            h = vf.get("height", 99999)
            portrait_penalty = 0 if h >= w else 1
            size_penalty = abs(w - 720) + abs(h - 1280)
            return (portrait_penalty, size_penalty)

        mp4_files = [vf for vf in video_files if vf.get("file_type") == "video/mp4"]
        if mp4_files:
            best_file = sorted(mp4_files, key=score)[0]

        if not best_file:
            continue

        results.append(
            {
                "source": "pexels",
                "media_id": item.get("id"),
                "title": item.get("url", "").strip(),
                "page_url": item.get("url", "").strip(),
                "mp4_url": best_file.get("link", "").strip(),
                "gif_url": "",
                "width": best_file.get("width"),
                "height": best_file.get("height"),
            }
        )

    return results


if __name__ == "__main__":
    sample_query = "sunrise ocean"
    items = search_pexels_videos(sample_query, limit=5)

    print(f"Found {len(items)} items for query: {sample_query}\n")
    print(json.dumps(items, ensure_ascii=False, indent=2))