from __future__ import annotations

from pathlib import Path
import json
from typing import Any


OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def choose_total_duration(vi_short: str) -> float:
    """Choose 12-15s based on quote length."""
    length = len((vi_short or "").strip())
    if length <= 45:
        return 12.0
    if length <= 70:
        return 13.0
    if length <= 95:
        return 14.0
    return 15.0


def _safe_scene_value(scene: dict[str, Any], key: str, default: Any = "") -> Any:
    value = scene.get(key, default)
    return default if value is None else value


def build_timeline(
    ai_data: dict[str, Any],
    selected_scenes: list[dict[str, Any]],
    music_data: dict[str, Any],
    author_display: str,
) -> dict[str, Any]:
    """
    Build timeline in the exact shape expected by the current video_renderer.py.

    Important:
    - main.py calls: build_timeline(ai_data, selected_media, music_data, author_display)
    - video_renderer.py expects:
      timeline["quote"]["vi_short"]
      timeline["timeline"]["scenes"][i]["start/end/media/local_path"]
      timeline["music"]["local_path"]
    """
    vi_short = (ai_data.get("vi_short") or ai_data.get("vi_full") or "").strip()
    if not vi_short:
        raise RuntimeError("AI output thiếu vi_short/vi_full để build timeline")

    if not selected_scenes:
        raise RuntimeError("Không có selected_scenes/media để build timeline")

    if not music_data or not music_data.get("local_path"):
        raise RuntimeError("Không có music_data.local_path để build timeline")

    total_duration = choose_total_duration(vi_short)

    # Keep enough time for author + channel at the end.
    ending_block = 2.2
    content_duration = max(total_duration - ending_block, 8.0)

    raw_scenes = ai_data.get("scenes") or []
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raw_scenes = [
            {
                "scene_number": 1,
                "beat_text": vi_short,
                "visual_mode": "symbolic",
                "search_query_en": "",
            }
        ]

    # Limit to the amount of media we actually have and max 3 scenes.
    scene_count = min(len(raw_scenes), len(selected_scenes), 3)
    if scene_count <= 0:
        raise RuntimeError("Không đủ scene/media để build timeline")

    raw_scenes = raw_scenes[:scene_count]
    selected_scenes = selected_scenes[:scene_count]

    scene_duration = round(content_duration / scene_count, 2)
    timeline_scenes: list[dict[str, Any]] = []
    cursor = 0.0

    for idx, scene in enumerate(raw_scenes):
        media = selected_scenes[idx]
        if not media or not media.get("local_path"):
            raise RuntimeError(f"Scene {idx + 1} thiếu media.local_path")

        start = round(cursor, 2)

        # Last scene ends exactly at content_duration to avoid accumulating rounding error.
        if idx == scene_count - 1:
            end = round(content_duration, 2)
        else:
            end = round(start + scene_duration, 2)

        timeline_scenes.append(
            {
                "scene_number": int(_safe_scene_value(scene, "scene_number", idx + 1)),
                "start": start,
                "end": end,
                "beat_text": _safe_scene_value(scene, "beat_text", ""),
                "visual_mode": _safe_scene_value(scene, "visual_mode", "symbolic"),
                "search_query_en": _safe_scene_value(scene, "search_query_en", ""),
                "media": media,
            }
        )
        cursor = end

    timeline = {
        "video_style": {
            "format": "9:16",
            "text_reveal_mode": "char_fade_soft_planned_not_yet_renderer",
            "text_position": "center",
            "text_background": "soft_dark_patch",
            "author_appears": "end_only",
            "channel_name_appears": "after_author_short_delay",
            "scene_transition": "soft_fade_planned_not_yet_renderer",
            "mute_source_audio": True,
        },
        "quote": {
            "vi_full": ai_data.get("vi_full", vi_short),
            "vi_short": vi_short,
            "author": author_display or "Khuyết danh",
            "caption": ai_data.get("caption", ""),
            "lane": ai_data.get("lane", "wisdom"),
            "mood": ai_data.get("mood", "chill"),
            "dynamic_hashtag": ai_data.get("dynamic_hashtag", "#wisdom"),
            "music_mood_tag": ai_data.get("music_mood_tag", "chill"),
        },
        "music": music_data,
        "timeline": {
            "total_duration": total_duration,
            "content_duration": round(content_duration, 2),
            "ending_block_duration": ending_block,
            "scenes": timeline_scenes,
            "ending": {
                "author_start": round(content_duration, 2),
                "author_end": round(content_duration + 1.2, 2),
                "channel_name_start": round(content_duration + 1.4, 2),
                "channel_name_end": round(total_duration, 2),
            },
        },
    }

    return timeline


if __name__ == "__main__":
    # Smoke test only. Must not run during import.
    sample_ai_data = {
        "vi_full": "Hãy là chính mình, vì người khác đã là họ rồi.",
        "vi_short": "Hãy là chính mình, vì người khác đã là họ rồi.",
        "caption": "Có những ngày ta mệt chỉ vì cố sống giống một ai đó.",
        "lane": "self-worth",
        "mood": "reflective",
        "dynamic_hashtag": "#selfworth",
        "music_mood_tag": "chill",
        "scenes": [
            {
                "scene_number": 1,
                "beat_text": "Hãy là chính mình",
                "visual_mode": "symbolic",
                "search_query_en": "person looking in mirror",
            }
        ],
    }
    sample_media = [
        {
            "media_key": "sample:1",
            "source": "sample",
            "local_path": "temp_media/sample.mp4",
            "media_url": "",
        }
    ]
    sample_music = {
        "local_path": "music/chill/sample.mp3",
        "resolved_mood_tag": "chill",
    }
    print(json.dumps(
        build_timeline(sample_ai_data, sample_media, sample_music, "Khuyết danh"),
        ensure_ascii=False,
        indent=2,
    ))
