from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import shutil
import traceback
import unicodedata
from dataclasses import asdict
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from telegram import Bot

from config import AppConfig, load_config
from db import get_connection, init_db
from quote_fetcher import fetch_all_raw_quotes
from quote_filter import CandidateQuote, filter_quotes
from quote_ai_processor import process_one_quote
from media_selector import select_media_bundle
from media_downloader import download_selected_media
from music_selector import select_music_track
from timeline_builder import build_timeline
from video_renderer import render_final_video

APP_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
AUTHOR_REPEAT_WINDOW_DAYS = 7
MAX_QUOTES_TO_TRY_PER_VIDEO = 6
UNKNOWN_AUTHORS = {
    "",
    "unknown",
    "anonymous",
    "khuyết danh",
    "khuyet danh",
    "không rõ tác giả",
    "khong ro tac gia",
}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def now_local() -> datetime:
    return datetime.now(APP_TZ)


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def inside_run_window(config: AppConfig) -> bool:
    current = now_local().time()
    return parse_hhmm(config.run_start) <= current <= parse_hhmm(config.run_deadline)


def normalize_author(author: str | None) -> str:
    value = (author or "").strip().strip("—-").strip()
    value_key = remove_vietnamese_accents(value).lower()
    if value_key in UNKNOWN_AUTHORS:
        return "Khuyết danh"
    return value or "Khuyết danh"


def get_author_display(
    ai_data: dict[str, Any], fallback_author: str | None = None
) -> str:
    quote_source = (
        ai_data.get("quote_source")
        if isinstance(ai_data.get("quote_source"), dict)
        else {}
    )
    author = (
        quote_source.get("author_display") or ai_data.get("_author") or fallback_author
    )
    return normalize_author(str(author or ""))


def remove_vietnamese_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def slugify(text: str, max_len: int = 48) -> str:
    text = remove_vietnamese_accents(text).lower()
    allowed = []
    last_underscore = False
    for ch in text:
        if ch.isalnum():
            allowed.append(ch)
            last_underscore = False
        elif not last_underscore:
            allowed.append("_")
            last_underscore = True
    slug = "".join(allowed).strip("_")
    return slug[:max_len].strip("_") or "quote_video"


def author_used_recently(
    author_display: str, days: int = AUTHOR_REPEAT_WINDOW_DAYS
) -> bool:
    # Không khóa quá chặt với tác giả không rõ, vì nhiều quote unknown có thể dùng được.
    if remove_vietnamese_accents(author_display).lower() in UNKNOWN_AUTHORS:
        return False

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM used_quotes
            WHERE lower(author_display) = lower(?)
              AND used_at >= datetime('now', ?)
            LIMIT 1
            """,
            (author_display, f"-{days} days"),
        ).fetchone()
    return row is not None


def choose_candidate_quote(candidates: list[CandidateQuote]) -> CandidateQuote:
    shuffled = list(candidates)
    random.shuffle(shuffled)

    # Ưu tiên tác giả chưa xuất hiện gần đây.
    for candidate in shuffled:
        author_display = normalize_author(candidate.author)
        if not author_used_recently(author_display):
            return candidate

    # Nếu tất cả đều trùng tác giả gần đây thì vẫn lấy một cái để không chết pipeline.
    return shuffled[0]


def validate_ai_data(ai_data: dict[str, Any]) -> None:
    required = [
        "vi_full",
        "vi_short",
        "caption",
        "lane",
        "mood",
        "music_mood_tag",
        "scenes",
    ]
    missing = [key for key in required if not ai_data.get(key)]
    if missing:
        raise RuntimeError(f"AI output thiếu trường bắt buộc: {', '.join(missing)}")

    if not isinstance(ai_data["scenes"], list) or not ai_data["scenes"]:
        raise RuntimeError("AI output không có scenes hợp lệ")

    # MVP: tối đa 3 scene để giữ video gọn.
    ai_data["scenes"] = ai_data["scenes"][:3]

    # Phase 2: nếu có schema mới, cũng giới hạn scene_plan để đồng bộ.
    if isinstance(ai_data.get("scene_plan"), list):
        ai_data["scene_plan"] = ai_data["scene_plan"][:3]


EASY_VISUAL_TERMS = {
    "cat",
    "dog",
    "animal",
    "cute",
    "friend",
    "friends",
    "hug",
    "help",
    "support",
    "book",
    "books",
    "reading",
    "library",
    "thinking",
    "confused",
    "searching",
    "magnifying",
    "walking",
    "dance",
    "celebrate",
    "success",
    "rocket",
    "work",
    "typing",
    "building",
    "drawing",
    "painting",
    "smile",
    "calm",
    "relaxed",
    "shrug",
    "heart",
    "love",
    "flower",
    "garden",
    "fall",
    "trip",
    "fail",
    "chó",
    "mèo",
    "sách",
    "đọc",
    "bạn",
    "ôm",
    "giúp",
    "cười",
    "bình yên",
    "nhảy",
    "thành công",
    "làm việc",
    "vẽ",
    "xây",
    "té",
    "ngã",
}

HARD_ABSTRACT_TERMS = {
    "fake persona",
    "persona",
    "mask",
    "identity",
    "self-deception",
    "perspective shift",
    "perspective",
    "painful clarity",
    "clarity",
    "illusion",
    "truth",
    "existential",
    "ego",
    "soul",
    "metaphor",
    "inside a dog's belly",
    "dog's belly",
    "belly",
    "mimic perspective",
    "the mask",
    "the mirror",
    "bản ngã",
    "danh tính",
    "mặt nạ",
    "ảo tưởng",
    "sự thật",
    "góc nhìn",
    "ẩn dụ",
    "linh hồn",
}


def _join_ai_scene_text(ai_data: dict[str, Any]) -> str:
    chunks: list[str] = []

    for key in [
        "vi_full",
        "vi_short",
        "caption",
        "lane",
        "mood",
        "music_mood_tag",
        "dynamic_hashtag",
    ]:
        value = ai_data.get(key)
        if value:
            chunks.append(str(value))

    for key in ["visual_plan", "text_output"]:
        value = ai_data.get(key)
        if isinstance(value, dict):
            chunks.append(" ".join(str(v) for v in value.values() if v))

    scenes = ai_data.get("scene_plan") or ai_data.get("scenes") or []
    if isinstance(scenes, list):
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            for key in [
                "scene_role",
                "meaning",
                "visual_goal",
                "semantic_goal",
                "visual_intent",
                "emotion_target",
            ]:
                value = scene.get(key)
                if value:
                    chunks.append(str(value))

            for key in [
                "must_have_elements",
                "must_show",
                "nice_to_have",
                "avoid_elements",
                "queries_giphy",
                "queries_fallback",
            ]:
                value = scene.get(key)
                if isinstance(value, list):
                    chunks.append(" ".join(str(x) for x in value if x))

    return " ".join(chunks).lower()


def assess_quote_visual_complexity(ai_data: dict[str, Any]) -> dict[str, Any]:
    text = _join_ai_scene_text(ai_data)

    scenes = ai_data.get("scene_plan") or ai_data.get("scenes") or []
    scene_count = len(scenes) if isinstance(scenes, list) else 0

    hard_hits = sorted(term for term in HARD_ABSTRACT_TERMS if term in text)
    easy_hits = sorted(term for term in EASY_VISUAL_TERMS if term in text)

    scene_without_easy_visual = 0
    if isinstance(scenes, list):
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            scene_text = " ".join(
                str(scene.get(key, ""))
                for key in [
                    "meaning",
                    "visual_goal",
                    "semantic_goal",
                    "visual_intent",
                    "emotion_target",
                ]
            ).lower()
            scene_text += " "
            scene_text += " ".join(
                str(x)
                for key in [
                    "must_have_elements",
                    "must_show",
                    "queries_giphy",
                    "queries_fallback",
                ]
                for x in (scene.get(key) if isinstance(scene.get(key), list) else [])
            ).lower()

            if not any(term in scene_text for term in EASY_VISUAL_TERMS):
                scene_without_easy_visual += 1

    reasons: list[str] = []

    if scene_count > 3:
        reasons.append(f"too_many_scenes:{scene_count}")

    if hard_hits:
        reasons.append(f"hard_abstract_terms:{', '.join(hard_hits[:5])}")

    if scene_without_easy_visual >= 2:
        reasons.append(
            f"too_many_scenes_without_easy_visual:{scene_without_easy_visual}"
        )

    if len(easy_hits) < 2:
        reasons.append("not_enough_easy_visual_terms")

    accepted = not reasons

    return {
        "accepted": accepted,
        "scene_count": scene_count,
        "easy_hits": easy_hits[:12],
        "hard_hits": hard_hits[:12],
        "scene_without_easy_visual": scene_without_easy_visual,
        "reasons": reasons,
    }


def reject_if_quote_too_complex(ai_data: dict[str, Any]) -> None:
    result = assess_quote_visual_complexity(ai_data)
    ai_data["quote_complexity_gate"] = result

    if not result.get("accepted"):
        has_easy_visual_plan = (
            result.get("scene_count", 0) >= 2
            and result.get("scene_without_easy_visual", 999) == 0
            and len(result.get("easy_hits", [])) >= 3
        )

        only_abstract_reason = all(
            str(reason).startswith("hard_abstract_terms:")
            for reason in result.get("reasons", [])
        )

        if has_easy_visual_plan and only_abstract_reason:
            result["accepted"] = True
            result.setdefault("reasons", []).append("override_easy_visual_plan")
            print("[COMPLEXITY OVERRIDE]", result)
        else:
            print("[COMPLEXITY SKIP]", result)
            raise RuntimeError(f"Quote Complexity Gate rejected: {result}")
        


def build_media_selector_input(ai_data: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 2/4 adapter.

    Tạo input chuẩn cho media selector theo schema mới.
    Từ Phase 4, main.py sẽ truyền object này vào select_media_bundle() thật.
    """
    quote_source = (
        ai_data.get("quote_source")
        if isinstance(ai_data.get("quote_source"), dict)
        else {}
    )
    classification = (
        ai_data.get("classification")
        if isinstance(ai_data.get("classification"), dict)
        else {}
    )
    visual_plan = (
        ai_data.get("visual_plan")
        if isinstance(ai_data.get("visual_plan"), dict)
        else {}
    )

    scene_requests = get_scene_requests(ai_data)

    return {
        "schema_version": "media_selector_input_v1",
        "video_context": {
            "quote_id_hash": quote_source.get("quote_id_hash", ""),
            "lane": classification.get("lane") or ai_data.get("lane", "wisdom"),
            "mood": classification.get("mood") or ai_data.get("mood", "reflective"),
            "motif_main": visual_plan.get("motif_main", ""),
            "visual_world": visual_plan.get("visual_world", ""),
            "consistency_tags": visual_plan.get("consistency_tags", []),
            "prohibited_visuals": visual_plan.get("prohibited_visuals", []),
        },
        "selection_policy": {
            "source_priority": ["giphy", "pexels"],
            "giphy_first": True,
            "max_scenes": min(len(scene_requests), 3),
            "avoid_recent_media_days": 30,
            "require_text_free_media": True,
            "require_visual_consistency": True,
        },
        "scene_requests": scene_requests,
    }


def get_scene_requests(ai_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Ưu tiên scene_plan mới. Nếu thiếu thì chuyển từ scenes cũ sang request tối thiểu.
    """
    scene_plan = ai_data.get("scene_plan")
    if isinstance(scene_plan, list) and scene_plan:
        return [scene for scene in scene_plan[:3] if isinstance(scene, dict)]

    result: list[dict[str, Any]] = []
    for index, scene in enumerate(ai_data.get("scenes", [])[:3], start=1):
        query = (scene.get("search_query_en") or "").strip()
        result.append(
            {
                "scene_id": index,
                "scene_role": "reflection",
                "meaning": scene.get("beat_text", ""),
                "visual_goal": scene.get("beat_text", ""),
                "priority": scene.get("visual_mode", "symbolic"),
                "must_have_elements": [],
                "avoid_elements": [],
                "queries_giphy": [query] if query else [],
                "queries_fallback": [query] if query else [],
                "continuity_tags": [],
            }
        )
    return result


def select_and_download_scene_media(
    media_selector_input: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Phase 4: dùng select_media_bundle() thật.

    - main.py không còn tự duyệt từng query rồi nhận candidate đầu tiên.
    - media_selector.py sẽ chấm điểm, shortlist và chọn theo cả bundle scene.
    - Sau khi bundle được chọn xong mới download media cho từng scene.
    """
    media_result = select_media_bundle(media_selector_input)
    if not isinstance(media_result, dict):
        raise RuntimeError("media selector không trả về dict hợp lệ")

    summary = media_result.get("video_selection_summary")
    selected_scene_results = media_result.get("selected_scenes")
    if not isinstance(selected_scene_results, list) or not selected_scene_results:
        raise RuntimeError(
            f"Media bundle selection failed. Summary: {summary}. "
            f"Rejected count: {len(media_result.get('rejected_candidates_log', []))}"
        )

    selected_media: list[dict[str, Any]] = []
    for scene_index, scene_result in enumerate(selected_scene_results, start=1):
        if not isinstance(scene_result, dict):
            raise RuntimeError(f"selected_scenes[{scene_index}] không hợp lệ")

        raw_media = scene_result.get("selected_media")
        if not isinstance(raw_media, dict) or not raw_media:
            raise RuntimeError(f"Scene {scene_index} không có selected_media hợp lệ")

        picked = dict(raw_media)
        picked["_scene_id"] = scene_result.get("scene_id", scene_index)
        picked["_scene_role"] = scene_result.get("scene_role", "")
        picked["_visual_goal"] = scene_result.get("visual_goal", "")
        picked["_selection_score"] = (
            scene_result.get("score_breakdown", {})
            if isinstance(scene_result.get("score_breakdown"), dict)
            else {}
        ).get("total_score")
        picked["_score_breakdown"] = scene_result.get("score_breakdown", {})
        picked["_judge_summary"] = scene_result.get("judge_summary", {})
        picked["_shortlist"] = scene_result.get("shortlist", [])

        picked = download_selected_media(picked)
        selected_media.append(picked)

    return selected_media, media_result


def build_video_slug(slot_index: int, quote_text: str) -> str:
    stamp = now_local().strftime("%Y%m%d_%H%M%S")
    short_quote = slugify(quote_text, max_len=42)
    return f"{stamp}_v{slot_index}_{short_quote}"


def make_social_caption(config: AppConfig, ai_data: dict[str, Any]) -> str:
    text_output = (
        ai_data.get("text_output")
        if isinstance(ai_data.get("text_output"), dict)
        else {}
    )

    dynamic = (
        text_output.get("dynamic_hashtag")
        or ai_data.get("dynamic_hashtag")
        or "#wisdom"
    ).strip()
    if not dynamic.startswith("#"):
        dynamic = f"#{dynamic}"

    caption = (text_output.get("caption") or ai_data["caption"]).strip()
    return f"{caption}\n\n{config.fixed_hashtag} {dynamic}"


def write_metadata(config: AppConfig, slug: str, metadata: dict[str, Any]) -> Path:
    out_path = config.output_dir / f"{slug}.json"
    out_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_path


def register_success_in_db(
    *,
    quote: CandidateQuote,
    ai_data: dict[str, Any],
    selected_media: list[dict[str, Any]],
    slug: str,
    video_path: Path,
    metadata_path: Path,
    social_caption: str,
    telegram_message_id: str | None = None,
) -> None:
    author_display = get_author_display(ai_data, quote.author)
    hashtags = ["#trichdanmoingay", ai_data.get("dynamic_hashtag", "#wisdom")]

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO used_quotes (
                quote_hash, source_name, source_url, original_quote,
                author_name, author_display, vi_full, vi_short, lane, mood
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                quote.quote_hash,
                quote.source_name,
                quote.source_url,
                quote.text,
                quote.author,
                author_display,
                ai_data["vi_full"],
                ai_data["vi_short"],
                ai_data.get("lane"),
                ai_data.get("mood"),
            ),
        )

        for media in selected_media:
            media_key = media.get("media_key")
            if not media_key:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO media_usage (
                    media_key, media_source, media_url, media_type, used_in_video_slug
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    media_key,
                    media.get("source", "unknown"),
                    media.get("media_url")
                    or media.get("mp4_url")
                    or media.get("gif_url")
                    or "",
                    "video" if media.get("mp4_url") else "gif",
                    slug,
                ),
            )

        conn.execute(
            """
            INSERT OR REPLACE INTO videos (
                video_slug, video_path, metadata_path, source_name, source_url,
                quote_hash, author_display, lane, mood, caption_text,
                hashtags_json, status, sent_to_telegram_at, telegram_message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                str(video_path),
                str(metadata_path),
                quote.source_name,
                quote.source_url,
                quote.quote_hash,
                author_display,
                ai_data.get("lane"),
                ai_data.get("mood"),
                social_caption,
                json.dumps(hashtags, ensure_ascii=False),
                "sent_to_telegram" if telegram_message_id else "created",
                (
                    now_local().isoformat(timespec="seconds")
                    if telegram_message_id
                    else None
                ),
                telegram_message_id,
            ),
        )
        conn.commit()


def create_run_row(run_date: str, attempt_number: int) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO runs (run_date, attempt_number, status)
            VALUES (?, ?, 'running')
            """,
            (run_date, attempt_number),
        )
        conn.commit()
        return int(cur.lastrowid)


def finish_run_row(
    run_id: int,
    status: str,
    error_step: str | None = None,
    error_message: str | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE runs
            SET status = ?, error_step = ?, error_message = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, error_step, error_message, run_id),
        )
        conn.commit()


async def send_telegram_video(
    config: AppConfig,
    video_path: Path,
    *,
    slot_index: int,
    quote: CandidateQuote,
    ai_data: dict[str, Any],
    social_caption: str,
) -> str | None:
    bot = Bot(token=config.telegram_bot_token)
    author_display = get_author_display(ai_data, quote.author)
    review_caption = (
        f"✅ Video {slot_index} đã render xong\n\n"
        f"CAPTION ĐĂNG:\n{social_caption}\n\n"
        f"QUOTE GỐC (EN):\n{quote.text}\n"
        f"— {author_display}\n\n"
        f"QUOTE VIỆT:\n{ai_data['vi_short']}\n"
        f"— {author_display}\n\n"
        f"Lane: {ai_data.get('lane')} | Mood: {ai_data.get('mood')}"
    )
    with open(video_path, "rb") as f:
        msg = await bot.send_video(
            chat_id=config.telegram_chat_id,
            video=f,
            caption=review_caption[:1000],
            supports_streaming=True,
            # Keep Telegram from hanging too long during manual tests.
            connect_timeout=20,
            read_timeout=60,
            write_timeout=90,
            pool_timeout=20,
        )
    return str(getattr(msg, "message_id", "")) if msg else None


async def send_telegram_error(config: AppConfig, text: str) -> None:
    bot = Bot(token=config.telegram_bot_token)
    await bot.send_message(
        chat_id=config.telegram_chat_id,
        text=text[:3500],
        connect_timeout=20,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=20,
    )


def render_to_slugged_output(
    config: AppConfig, timeline: dict[str, Any], slug: str
) -> Path:
    rendered_path = render_final_video(timeline)
    if not rendered_path.exists():
        raise RuntimeError(f"Renderer không tạo ra file: {rendered_path}")

    final_path = config.output_dir / f"{slug}.mp4"
    shutil.copy2(rendered_path, final_path)
    return final_path


async def generate_one_video(
    config: AppConfig, slot_index: int, attempt_number: int
) -> Path:
    run_date = now_local().strftime("%Y-%m-%d")
    run_id = create_run_row(run_date, attempt_number)

    try:
        raw_quotes = fetch_all_raw_quotes()
        candidates = filter_quotes(raw_quotes)
        if not candidates:
            raise RuntimeError("Không còn quote hợp lệ sau khi lọc trùng/dài")

        last_error: Exception | None = None
        max_quotes_to_try = max(
            1, env_int("MAX_QUOTES_TO_TRY_PER_VIDEO", MAX_QUOTES_TO_TRY_PER_VIDEO)
        )
        print(f"[QUOTE TRY LIMIT] {max_quotes_to_try}")
        for _ in range(min(max_quotes_to_try, len(candidates))):
            quote = choose_candidate_quote(candidates)
            candidates.remove(quote)

            try:
                author_display = normalize_author(quote.author)
                ai_data = process_one_quote(
                    {
                        "text": quote.text,
                        "author": author_display,
                        "source_name": quote.source_name,
                        "source_url": quote.source_url,
                    }
                )
                validate_ai_data(ai_data)
                reject_if_quote_too_complex(ai_data)
                # Phase 4: build schema input và dùng bundle selector thật.
                media_selector_input = build_media_selector_input(ai_data)
                selected_media, media_result = select_and_download_scene_media(
                    media_selector_input
                )
                print(
                    "[MEDIA] selection summary:",
                    json.dumps(
                        media_result.get("video_selection_summary", {}),
                        ensure_ascii=False,
                    ),
                )
                music_data = select_music_track(ai_data["music_mood_tag"])
                timeline = build_timeline(
                    ai_data,
                    selected_media,
                    music_data,
                    get_author_display(ai_data, quote.author),
                )

                slug = build_video_slug(slot_index, ai_data["vi_short"])
                social_caption = make_social_caption(config, ai_data)

                metadata = {
                    "video_slug": slug,
                    "created_at": now_local().isoformat(timespec="seconds"),
                    "slot_index": slot_index,
                    "attempt_number": attempt_number,
                    "source": {
                        "name": quote.source_name,
                        "url": quote.source_url,
                    },
                    "quote": {
                        "quote_hash": quote.quote_hash,
                        "original_quote": quote.text,
                        "author_raw": quote.author,
                        "author_display": get_author_display(ai_data, quote.author),
                    },
                    "ai": ai_data,
                    "visual_plan": ai_data.get("visual_plan"),
                    "scene_plan": ai_data.get("scene_plan"),
                    "media_selector_input": media_selector_input,
                    "media_result": media_result,
                    "social_caption": social_caption,
                    "selected_media": selected_media,
                    "music": music_data,
                    "timeline": timeline,
                }

                # Lưu timeline/debug trước render để dễ xem lỗi nếu FFmpeg fail.
                timeline_debug_path = config.output_dir / f"{slug}_timeline.json"
                timeline_debug_path.write_text(
                    json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
                )

                video_path = render_to_slugged_output(config, timeline, slug)
                metadata["video_path"] = str(video_path)

                # IMPORTANT FIX:
                # From this point onward, the video already exists. Telegram failure
                # must NOT make the bot throw away this video and render another quote.
                telegram_message_id: str | None = None
                telegram_error: str | None = None

                try:
                    telegram_message_id = await send_telegram_video(
                        config,
                        video_path,
                        slot_index=slot_index,
                        quote=quote,
                        ai_data=ai_data,
                        social_caption=social_caption,
                    )
                except Exception as telegram_exc:
                    telegram_error = str(telegram_exc)
                    print(
                        "[WARN] Telegram send failed, but rendered video is kept:",
                        telegram_error,
                    )

                if telegram_error:
                    metadata["telegram_error"] = telegram_error

                metadata_path = write_metadata(config, slug, metadata)

                register_success_in_db(
                    quote=quote,
                    ai_data=ai_data,
                    selected_media=selected_media,
                    slug=slug,
                    video_path=video_path,
                    metadata_path=metadata_path,
                    social_caption=social_caption,
                    telegram_message_id=telegram_message_id,
                )

                finish_run_row(run_id, "success")
                print(f"[OK] Video created: {video_path}")
                if telegram_error:
                    print(
                        "[WARN] Video was NOT sent to Telegram. Check metadata for telegram_error."
                    )
                return video_path

            except Exception as quote_error:
                last_error = quote_error
                print("[WARN] Quote candidate failed:", quote_error)
                continue

        raise RuntimeError(
            f"Thử nhiều quote nhưng không tạo được video. Lỗi cuối: {last_error}"
        )

    except Exception as e:
        finish_run_row(
            run_id, "failed", error_step="generate_one_video", error_message=str(e)
        )
        raise


async def run_daily(config: AppConfig, videos: int) -> None:
    for slot_index in range(1, videos + 1):
        try:
            await generate_one_video(config, slot_index=slot_index, attempt_number=1)
        except Exception as first_error:
            print(f"[ERROR] Video {slot_index} attempt 1 failed:", first_error)
            if "No available vision model left for this run" in str(first_error):
                error_text = (
                    f"❌ Video {slot_index} lỗi vì vision model/quota không khả dụng.\n\n"
                    f"Lỗi: {first_error}\n\n"
                    f"Không retry vì retry sẽ fail tiếp khi không còn vision model để chấm GIF.\n\n"
                    f"Trace gần nhất:\n{traceback.format_exc()}"
                )
                try:
                    await send_telegram_error(config, error_text)
                except Exception as telegram_error:
                    print(
                        "[WARN] Could not send Telegram error message:", telegram_error
                    )
                continue
            # Retry 1 lần nếu còn trong khung giờ. Khi test bằng --ignore-window, retry luôn.
            try:
                if inside_run_window(config):
                    await generate_one_video(
                        config, slot_index=slot_index, attempt_number=2
                    )
                else:
                    raise RuntimeError("Hết khung giờ retry") from first_error
            except Exception as second_error:
                error_text = (
                    f"❌ Video {slot_index} lỗi sau khi retry.\n\n"
                    f"Lỗi lần 1: {first_error}\n"
                    f"Lỗi retry: {second_error}\n\n"
                    f"Trace gần nhất:\n{traceback.format_exc()}"
                )
                try:
                    await send_telegram_error(config, error_text)
                except Exception as telegram_error:
                    print(
                        "[WARN] Could not send Telegram error message:", telegram_error
                    )
                    print(error_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily quote video bot MVP")
    parser.add_argument(
        "--videos", type=int, default=None, help="Số video cần tạo trong lần chạy này"
    )
    parser.add_argument(
        "--ignore-window",
        action="store_true",
        help="Bỏ qua khung giờ 15:30-16:00 để test thủ công",
    )
    args = parser.parse_args()

    config = load_config()
    init_db()

    if not args.ignore_window and not inside_run_window(config):
        print(
            f"Ngoài khung giờ chạy ({config.run_start}-{config.run_deadline}). Dùng --ignore-window để test."
        )
        return

    videos = args.videos if args.videos is not None else config.videos_per_day
    asyncio.run(run_daily(config, videos=videos))


if __name__ == "__main__":
    main()
