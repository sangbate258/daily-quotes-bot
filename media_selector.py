from __future__ import annotations

from typing import Any
import itertools
import os
import re
import json
import time
from urllib.parse import urlparse

from dotenv import load_dotenv
from google import genai
from google.genai import types

from db import get_connection
from giphy_client import search_giphy, GiphyRateLimitError
from pexels_client import search_pexels_videos
from media_previewer import ensure_preview_sheet

MEDIA_REPEAT_WINDOW_DAYS = 30

STOPWORDS = {
    "a",
    "an",
    "the",
    "of",
    "in",
    "on",
    "to",
    "for",
    "with",
    "and",
    "or",
    "one",
    "person",
    "people",
    "someone",
    "somebody",
    "man",
    "woman",
    "very",
    "really",
    "just",
    "that",
    "this",
    "those",
    "these",
    "slow",
    "motion",
    "close",
    "shot",
    "wide",
    "cinematic",
    "aesthetic",
}

# These are not always bad in the whole world, but for your quote-video style
# they often produce random reaction GIFs / celebrity clips / subtitle clips.
HARD_BAD_TERMS = {
    # Keep only strong metadata risks here.
    # Do NOT hard-ban meme/reaction/cartoon/funny because the target style may use them.
    "interview",
    "talkshow",
    "talk show",
    "late night",
    "podcast",
    "news",
    "cnn",
    "fox",
    "bbc",
    "msnbc",
    "celebrity",
    "red carpet",
    "award",
    "oscars",
    "grammy",
    "tiktok",
    "youtube",
    "shorts",
    "reels",
}

# Domain/source hints that often mean the GIF is from pop-culture footage.
SOURCE_BAD_HINTS = {
    "giphy.com/clips",
    "reactiongifs",
    "tenor",
}

# Words that tend to be visually clean and match your intended vibe.
GOOD_VIBE_TERMS = {
    "nature",
    "sunrise",
    "sunset",
    "walking",
    "road",
    "mirror",
    "rain",
    "window",
    "alone",
    "quiet",
    "calm",
    "hands",
    "plant",
    "sprout",
    "mountain",
    "ocean",
    "forest",
    "city",
    "crowd",
    "shadow",
    "light",
    "smile",
    "hug",
    "books",
    "library",
    "work",
    "desk",
    "thinking",
    "home",
    "room",
    "shelf",
    "bookshelf",
    "reflection",
    "friend",
    "friends",
    "comfort",
    "hugging",
    "reading",
}


# Role-aware scoring:
# The selector should ask whether a GIF performs the scene's logic role,
# not only whether it matches the surface mood or a few query tokens.
SCENE_ROLE_INTENTS = {
    "external_negation": {
        "wanted": {
            "no",
            "stop",
            "cannot",
            "cant",
            "can't",
            "dont",
            "don't",
            "forbidden",
            "warning",
            "warn",
            "reject",
            "refuse",
            "limit",
            "limitation",
            "restriction",
            "teacher",
            "pointing",
            "talking",
            "lecture",
            "scolding",
            "argue",
            "argument",
            "deny",
            "denial",
        },
        "avoid": {
            "dance",
            "dancing",
            "celebration",
            "celebrate",
            "party",
            "victory",
            "sleep",
            "sleepy",
            "relax",
        },
    },
    "negative_escalation": {
        "wanted": {
            "worse",
            "bad",
            "problem",
            "problems",
            "wrong",
            "fail",
            "failure",
            "disaster",
            "pile",
            "chain",
            "reaction",
            "escalation",
            "escalating",
            "collapse",
            "crash",
            "break",
            "broken",
            "chaos",
            "mess",
            "trouble",
            "unlucky",
            "badluck",
            "accident",
            "oh",
            "no",
        },
        "avoid": {
            "dance",
            "dancing",
            "celebration",
            "celebrate",
            "party",
            "victory",
            "success",
            "rocket",
            "launch",
            "happy",
            "joy",
            "relax",
            "sleep",
        },
    },
    "positive_escalation": {
        "wanted": {
            "better",
            "good",
            "great",
            "wonderful",
            "possible",
            "possibility",
            "breakthrough",
            "success",
            "achieve",
            "achievement",
            "rocket",
            "launch",
            "flying",
            "fly",
            "wow",
            "invention",
            "invent",
            "discovery",
            "dream",
            "real",
            "reality",
            "miracle",
            "victory",
            "celebration",
            "surprise",
            "news",
            "upgrade",
            "level",
            "up",
            "freedom",
            "free",
        },
        "avoid": {
            "sad",
            "crying",
            "stuck",
            "restriction",
            "forbidden",
            "stop",
            "no",
            "bad",
            "worse",
            "wrong",
            "fail",
            "failure",
            "disaster",
            "sleep",
        },
    },
    "reflection": {
        "wanted": {
            "thinking",
            "think",
            "listen",
            "listening",
            "hear",
            "hearing",
            "confused",
            "wondering",
            "processing",
            "ponder",
            "idea",
            "mind",
            "brain",
            "realize",
            "realization",
            "question",
            "attentive",
            "contemplate",
            "contemplating",
        },
        "avoid": {
            "party",
            "chaos",
            "fighting",
            "fight",
            "explosion",
            "celebration",
            "jackhammer",
        },
    },
    "breakthrough": {
        "wanted": {
            "possible",
            "possibility",
            "breakthrough",
            "success",
            "achieve",
            "achievement",
            "rocket",
            "launch",
            "flying",
            "fly",
            "wow",
            "invention",
            "invent",
            "discovery",
            "dream",
            "real",
            "reality",
            "miracle",
            "victory",
            "celebration",
            "freedom",
            "free",
        },
        "avoid": {
            "sad",
            "crying",
            "stuck",
            "restriction",
            "forbidden",
            "stop",
            "no",
            "sleep",
            "sleepy",
            "failure",
        },
    },
    "connection": {
        "wanted": {
            "friend",
            "friends",
            "hug",
            "together",
            "walking",
            "side",
            "beside",
            "comfort",
            "help",
            "support",
            "high",
            "five",
        },
        "avoid": {
            "alone",
            "fight",
            "fighting",
            "reject",
            "ignore",
        },
    },
}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


VISION_DISABLED_MODELS: set[str] = set()
VISION_MODEL_ERROR_COUNTS: dict[str, int] = {}


def env_model_list(name: str) -> list[str]:
    value = os.getenv(name, "").strip()
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def is_quota_error(error: Exception) -> bool:
    text = str(error).lower()
    return (
        "429" in text
        or "resource_exhausted" in text
        or "quota exceeded" in text
        or "generate_content_free_tier_requests" in text
    )


def is_model_unstable_error(error: Exception) -> bool:
    text = str(error).lower()
    return (
        "500 internal" in text
        or "503 unavailable" in text
        or "404 not_found" in text
        or "requested entity was not found" in text
    )


def should_disable_unstable_model(model_name: str, error: Exception) -> bool:
    text = str(error).lower()

    if "404 not_found" in text or "requested entity was not found" in text:
        return True

    if not is_model_unstable_error(error):
        return False

    VISION_MODEL_ERROR_COUNTS[model_name] = (
        VISION_MODEL_ERROR_COUNTS.get(model_name, 0) + 1
    )

    threshold = env_int("GOOGLE_VISION_DISABLE_AFTER_ERRORS", 3)
    return VISION_MODEL_ERROR_COUNTS[model_name] >= threshold


def get_vision_model_candidates() -> list[str]:
    primary = (
        os.getenv("GOOGLE_VISION_MODEL_NAME", "").strip()
        or os.getenv("GOOGLE_MODEL_NAME", "").strip()
        or "gemma-4-31b-it"
    )

    fallback_models = env_model_list("GOOGLE_VISION_FALLBACK_MODEL_NAME")

    models: list[str] = []
    for model_name in [primary, *fallback_models]:
        if model_name and model_name not in models:
            models.append(model_name)

    return models

def has_available_vision_model() -> bool:
    return any(
        model_name not in VISION_DISABLED_MODELS
        for model_name in get_vision_model_candidates()
    )
def tokenize(text: str) -> set[str]:
    text = (text or "").lower()
    tokens = re.findall(r"[a-zA-Z]+", text)
    return {t for t in tokens if t not in STOPWORDS and len(t) >= 3}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def contains_bad_term(text: str) -> bool:
    hay = normalize_text(text)
    if not hay:
        return False

    for term in HARD_BAD_TERMS:
        if term in hay:
            return True
    return False


def looks_like_pop_culture_or_text_overlay(item: dict[str, Any]) -> tuple[bool, str]:
    title = item.get("title", "") or ""
    page_url = item.get("page_url", "") or ""
    combined = f"{title} {page_url}"

    if contains_bad_term(combined):
        return True, "bad_term_in_title_or_url"

    parsed = urlparse(page_url)
    url_bits = f"{parsed.netloc} {parsed.path}".lower()
    for hint in SOURCE_BAD_HINTS:
        if hint in url_bits:
            return True, "bad_source_hint"

    return False, ""


def media_used_recently(media_key: str, days: int = MEDIA_REPEAT_WINDOW_DAYS) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM media_usage
            WHERE media_key = ?
              AND used_at >= datetime('now', ?)
            LIMIT 1
            """,
            (media_key, f"-{days} days"),
        ).fetchone()

    return row is not None


def normalize_candidate(item: dict[str, Any]) -> dict[str, Any]:
    source = item["source"]
    media_id = item["media_id"]
    media_key = f"{source}:{media_id}"

    media_url = item.get("mp4_url") or item.get("gif_url") or ""

    return {
        "candidate_id": media_key,
        "media_key": media_key,
        "source": source,
        "media_id": media_id,
        "title": item.get("title", ""),
        "page_url": item.get("page_url", ""),
        "media_url": media_url,
        "mp4_url": item.get("mp4_url", ""),
        "gif_url": item.get("gif_url", ""),
        "width": item.get("width"),
        "height": item.get("height"),
        "duration_sec": item.get("duration_sec"),
        "search_query_used": item.get("search_query_used", ""),
        "query_round": item.get("query_round", 1),
    }


def safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def dimension_score(width: Any, height: Any, *, source: str) -> float:
    w = safe_int(width)
    h = safe_int(height)
    if not w or not h:
        return 0.0

    score = 0.0
    aspect = w / h

    # For 9:16 videos, portrait/square media is safer. Horizontal media often
    # gets cropped into a random face/body part when forced full-screen.
    if h > w:
        score += 3.0
    elif 0.85 <= aspect <= 1.20:
        score += 2.0
    elif 1.20 < aspect <= 1.55:
        score -= 0.5
    else:
        score -= 2.0

    # Very tiny GIFs often look low quality after scaling to 1080x1920.
    if max(w, h) >= 720:
        score += 1.5
    elif max(w, h) >= 480:
        score += 0.5
    else:
        score -= 1.0

    # GIPHY is often lower-res/pop-culture, so be stricter with bad aspect.
    if source == "giphy" and aspect > 1.55:
        score -= 1.5

    return score


def score_candidate(
    query: str, item: dict[str, Any], *, source: str
) -> tuple[float, list[str]]:
    """
    Old compact scorer kept for backward compatibility with select_media_for_scene().
    """
    reasons: list[str] = []
    normalized = normalize_candidate(item)

    score = 0.0
    query_tokens = tokenize(query)

    title = item.get("title", "")
    page_url = item.get("page_url", "")
    haystack = f"{title} {page_url}"
    hay_tokens = tokenize(haystack)

    overlap = query_tokens & hay_tokens
    score += len(overlap) * 1.5
    if overlap:
        reasons.append(f"overlap={','.join(sorted(overlap))}")

    good_overlap = hay_tokens & GOOD_VIBE_TERMS
    if good_overlap:
        score += min(2.0, len(good_overlap) * 0.5)
        reasons.append(f"good_vibe={','.join(sorted(good_overlap))}")

    bad, bad_reason = looks_like_pop_culture_or_text_overlay(item)
    if bad:
        score -= 8.0
        reasons.append(bad_reason)

    ds = dimension_score(
        normalized.get("width"), normalized.get("height"), source=source
    )
    score += ds
    reasons.append(f"dimension_score={ds:.1f}")

    if not normalized.get("mp4_url") and not normalized.get("gif_url"):
        score -= 100.0
        reasons.append("no_media_url")

    # Source policy:
    # - GIPHY is preferred only when it is clearly decent.
    # - Pexels is allowed to win because it is often cleaner for quote videos.
    if source == "giphy":
        score -= 0.5
        # If title/url has almost no relationship to the query, reject more often.
        # This prevents celebrity/interview GIFs from winning just because GIPHY returned them.
        if not overlap and not good_overlap:
            score -= 2.0
            reasons.append("weak_metadata_match")
    elif source == "pexels":
        score += 1.0
        reasons.append("pexels_clean_source_bonus")

    return score, reasons


def pick_ranked_candidate(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    source: str,
    exclude_media_keys: set[str] | None = None,
    min_score: float = 0.0,
) -> dict[str, Any] | None:
    exclude_media_keys = exclude_media_keys or set()
    ranked: list[tuple[float, dict[str, Any]]] = []

    for item in candidates:
        normalized = normalize_candidate(item)

        if normalized["media_key"] in exclude_media_keys:
            continue

        if media_used_recently(normalized["media_key"]):
            continue

        score, reasons = score_candidate(query, item, source=source)

        normalized["quality_score"] = round(score, 2)
        normalized["quality_reasons"] = reasons

        if score >= min_score:
            ranked.append((score, normalized))

    ranked.sort(key=lambda x: x[0], reverse=True)

    if not ranked:
        return None

    return ranked[0][1]


def build_query_variants(search_query_en: str) -> list[str]:
    base = normalize_text(search_query_en)
    if not base:
        return []

    # Keep small. Too many queries burns API quota and causes noisy results.
    variants = [base]

    # These variants bias search toward cleaner, less meme-like visuals.
    if not any(w in base for w in ["cinematic", "aesthetic"]):
        variants.append(f"cinematic {base}")

    # If the query is too literal and GIPHY fails, a simpler motif query may work better.
    tokens = [
        t for t in re.findall(r"[a-zA-Z]+", base) if t not in STOPWORDS and len(t) >= 3
    ]
    if 2 <= len(tokens) <= 6:
        variants.append(" ".join(tokens[:4]))

    # de-duplicate while preserving order
    seen = set()
    result = []
    for q in variants:
        if q and q not in seen:
            seen.add(q)
            result.append(q)

    return result


def select_media_for_scene(
    search_query_en: str,
    exclude_media_keys: set[str] | None = None,
) -> dict[str, Any] | None:
    """
    Old single-scene selector kept for backward compatibility.

    Current practical policy:
    1. Try GIPHY first, but only accept if the candidate passes a stricter quality score.
    2. If GIPHY looks like random meme/celebrity/talking-head footage, fallback to Pexels.
    3. Avoid media used in the last 30 days and avoid duplicates within the same video.
    """
    exclude_media_keys = exclude_media_keys or set()

    giphy_limit = env_int("GIPHY_CANDIDATE_LIMIT", 25)
    pexels_limit = env_int("PEXELS_CANDIDATE_LIMIT", 15)

    # Raise this if GIPHY keeps picking bad reaction/celebrity GIFs.
    giphy_min_score = env_float("GIPHY_MIN_QUALITY_SCORE", 4.0)
    pexels_min_score = env_float("PEXELS_MIN_QUALITY_SCORE", 1.0)

    query_variants = build_query_variants(search_query_en)
    if not query_variants:
        return None

    # 1) GIPHY first, but with stricter quality gate.
    for query in query_variants[:2]:
        giphy_results = search_giphy(query, limit=giphy_limit)
        picked = pick_ranked_candidate(
            query,
            giphy_results,
            source="giphy",
            exclude_media_keys=exclude_media_keys,
            min_score=giphy_min_score,
        )
        if picked:
            picked["picked_from"] = "giphy_first_quality_filtered"
            picked["search_query_used"] = query
            return picked

    # 2) Pexels fallback: cleaner video source.
    for query in query_variants:
        pexels_results = search_pexels_videos(query, limit=pexels_limit)
        picked = pick_ranked_candidate(
            query,
            pexels_results,
            source="pexels",
            exclude_media_keys=exclude_media_keys,
            min_score=pexels_min_score,
        )
        if picked:
            picked["picked_from"] = "pexels_fallback_cleaner"
            picked["search_query_used"] = query
            return picked

    # 3) Last-resort Pexels: allow first unused if strict scoring is too harsh.
    # This is still usually cleaner than a random GIPHY reaction.
    for query in query_variants:
        pexels_results = search_pexels_videos(query, limit=pexels_limit)
        picked = pick_ranked_candidate(
            query,
            pexels_results,
            source="pexels",
            exclude_media_keys=exclude_media_keys,
            min_score=-2.0,
        )
        if picked:
            picked["picked_from"] = "pexels_last_resort"
            picked["search_query_used"] = query
            return picked

    return None


# ---------------------------------------------------------------------------
# Phase 3: Bundle selector
# ---------------------------------------------------------------------------


def safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def get_policy(media_input: dict[str, Any]) -> dict[str, Any]:
    load_dotenv()
    policy = media_input.get("selection_policy")
    if not isinstance(policy, dict):
        policy = {}

    env_query_rounds = env_int("QUERY_ROUNDS_BEFORE_FALLBACK", 2)
    env_candidate_limit = env_int("GIPHY_CANDIDATE_LIMIT", 6)

    return {
        "source_priority": policy.get("source_priority", ["giphy", "pexels"]),
        "giphy_first": bool(policy.get("giphy_first", True)),
        "max_scenes": int(policy.get("max_scenes", 3)),
        "candidate_limit_per_query": min(
            int(policy.get("candidate_limit_per_query", env_candidate_limit)),
            env_candidate_limit,
        ),
        "query_rounds_before_fallback": min(
            int(policy.get("query_rounds_before_fallback", env_query_rounds)),
            env_query_rounds,
        ),
        "avoid_recent_media_days": int(
            policy.get("avoid_recent_media_days", MEDIA_REPEAT_WINDOW_DAYS)
        ),
        # Keep this lower than final ideal because current scorer is metadata-only.
        # Once OCR/vision is added, 70 is more meaningful.
        "min_acceptable_score": float(
            policy.get("min_acceptable_score", env_float("MEDIA_BUNDLE_MIN_SCORE", 38))
        ),
        "require_text_free_media": bool(policy.get("require_text_free_media", True)),
        "require_visual_consistency": bool(
            policy.get("require_visual_consistency", True)
        ),
        "shortlist_size_per_scene": int(
            policy.get(
                "shortlist_size_per_scene", env_int("SHORTLIST_SIZE_PER_SCENE", 5)
            )
        ),
        "use_vision_rerank": bool(
            policy.get("use_vision_rerank", env_int("USE_VISION_RERANK", 1) == 1)
        ),
        "vision_rerank_top_k": int(
            policy.get("vision_rerank_top_k", env_int("VISION_RERANK_TOP_K", 3))
        ),
        "vision_weight": float(
            policy.get("vision_weight", env_float("VISION_WEIGHT", 0.55))
        ),
        "metadata_weight": float(
            policy.get("metadata_weight", env_float("METADATA_WEIGHT", 0.45))
        ),
        "min_final_scene_score": float(
            policy.get("min_final_scene_score", env_float("MIN_FINAL_SCENE_SCORE", 55))
        ),
        "min_vision_scene_score": float(
            policy.get(
                "min_vision_scene_score", env_float("MIN_VISION_SCENE_SCORE", 45)
            )
        ),
        "min_scene_role_match_score": float(
            policy.get(
                "min_scene_role_match_score", env_float("MIN_SCENE_ROLE_MATCH_SCORE", 4)
            )
        ),
        "min_metadata_scene_score": float(
            policy.get(
                "min_metadata_scene_score", env_float("MIN_METADATA_SCENE_SCORE", 38)
            )
        ),
        "allow_best_available_below_threshold": bool(
            policy.get(
                "allow_best_available_below_threshold",
                env_int("ALLOW_BEST_AVAILABLE", 0) == 1,
            )
        ),
        "use_scene_retry": bool(
            policy.get("use_scene_retry", env_int("USE_SCENE_RETRY", 1) == 1)
        ),
        "scene_retry_query_rounds": min(
            int(
                policy.get(
                    "scene_retry_query_rounds", env_int("SCENE_RETRY_QUERY_ROUNDS", 1)
                )
            ),
            env_int("SCENE_RETRY_QUERY_ROUNDS", 1),
        ),
        "allow_unvisioned_candidates": bool(
            policy.get(
                "allow_unvisioned_candidates",
                env_int("ALLOW_UNVISIONED_CANDIDATES", 0) == 1,
            )
        ),
        "allow_relaxed_vision_candidates": bool(
            policy.get(
                "allow_relaxed_vision_candidates",
                env_int("ALLOW_RELAXED_VISION_CANDIDATES", 1) == 1,
            )
        ),
        "relaxed_min_vision_score": float(
            policy.get(
                "relaxed_min_vision_score", env_float("RELAXED_MIN_VISION_SCORE", 70)
            )
        ),
        "relaxed_min_final_score": float(
            policy.get(
                "relaxed_min_final_score", env_float("RELAXED_MIN_FINAL_SCORE", 50)
            )
        ),
        "relaxed_min_role_score": float(
            policy.get("relaxed_min_role_score", env_float("RELAXED_MIN_ROLE_SCORE", 4))
        ),
        "allow_scene_drop_fallback": bool(
            policy.get(
                "allow_scene_drop_fallback",
                env_int("ALLOW_SCENE_DROP_FALLBACK", 1) == 1,
            )
        ),
        "min_scenes_after_drop": int(
            policy.get("min_scenes_after_drop", env_int("MIN_SCENES_AFTER_DROP", 2))
        ),
        "max_dropped_scenes": int(
            policy.get("max_dropped_scenes", env_int("MAX_DROPPED_SCENES", 1))
        ),
    }


def infer_retry_family(scene_request: dict[str, Any]) -> str:
    """
    Infer a semantic family for retry queries.

    This is intentionally separate from infer_scene_role_intent(). Scene role scoring
    can be broad, but retry search must stay in the same meaning family so it does
    not drift from love -> thinking, books -> generic confused, etc.
    """
    parts = [
        str(scene_request.get("scene_role", "")),
        str(scene_request.get("meaning", "")),
        str(scene_request.get("visual_goal", "")),
        str(scene_request.get("semantic_goal", "")),
        str(scene_request.get("visual_intent", "")),
        str(scene_request.get("emotion_target", "")),
        " ".join(map(str, safe_list(scene_request.get("must_have_elements")))),
        " ".join(map(str, safe_list(scene_request.get("must_show")))),
        " ".join(map(str, safe_list(scene_request.get("nice_to_have")))),
        " ".join(map(str, safe_list(scene_request.get("queries_giphy")))),
        " ".join(map(str, safe_list(scene_request.get("queries_fallback")))),
    ]
    text = normalize_text(" ".join(parts))
    # High-priority concrete action/emotion families.
    # Put these before love/books/teaching so retry does not drift.
    if any(
        k in text
        for k in [
            "planning",
            "plan",
            "writing list",
            "to do list",
            "todo list",
            "checklist",
            "schedule",
            "calendar",
            "typing fast",
            "write down",
            "taking notes",
            "note taking",
            "ghi chú",
            "lên kế hoạch",
            "danh sách",
            "lịch trình",
            "kế hoạch",
        ]
    ):
        return "planning_writing"

    if any(
        k in text
        for k in [
            "sad",
            "gloomy",
            "sigh",
            "sighing",
            "cry",
            "crying",
            "tears",
            "lonely",
            "melancholy",
            "heart broken",
            "heartbroken",
            "upset",
            "feeling down",
            "buồn",
            "u sầu",
            "thở dài",
            "khóc",
            "cô đơn",
            "tan vỡ",
            "đau lòng",
        ]
    ):
        return "sad_gloomy"
    if any(
        k in text
        for k in [
            "friend",
            "friends",
            "friendship",
            "bond",
            "connection",
            "connect",
            "together",
            "best friend",
            "high five",
            "hug",
            "companionship",
            "comfort",
            "support",
            "walking together",
            "bạn",
            "tình bạn",
            "đồng hành",
            "ôm",
            "an ủi",
        ]
    ):
        return "friendship_connection"

    if any(
        k in text
        for k in [
            "chocolate",
            "sweets",
            "sweet",
            "candy",
            "dessert",
            "cake",
            "cookie",
            "ice cream",
            "snack",
            "eating chocolate",
            "eating sweets",
            "đồ ngọt",
            "kẹo",
            "sô-cô-la",
            "socola",
            "bánh",
            "tráng miệng",
            "ăn kẹo",
            "ăn đồ ngọt",
        ]
    ):
        return "sweets_food"
    if any(
        k in text
        for k in [
            "happy dance",
            "happy jump",
            "joyful",
            "joy",
            "celebrate",
            "celebration",
            "proud",
            "excited",
            "cheer",
            "cheering",
            "smiling happily",
            "vui",
            "vui vẻ",
            "nhảy vui",
            "ăn mừng",
            "tự hào",
            "hân hoan",
        ]
    ):
        return "joy_celebration"

    if any(
        k in text
        for k in [
            "dizzy",
            "spinning",
            "spin",
            "overwhelmed",
            "stressed",
            "chaos",
            "chaotic",
            "everything is fine",
            "fire meme",
            "panic",
            "panicking",
            "quay cuồng",
            "choáng",
            "bối rối",
            "hoảng",
            "rối tung",
        ]
    ):
        return "dizzy_chaos"

    if any(
        k in text
        for k in [
            "silence",
            "silent",
            "shh",
            "regret",
            "regret speaking",
            "facepalm",
            "awkward",
            "awkward smile",
            "said too much",
            "lỡ lời",
            "im lặng",
            "hối hận",
            "ngượng",
            "quê",
            "nói lỡ",
        ]
    ):
        return "silence_regret"

    if any(
        k in text
        for k in [
            "relieved",
            "relief",
            "deep breath",
            "breathing",
            "breathe",
            "letting go",
            "let go",
            "calm down",
            "lightness",
            "peaceful smiling",
            "nhẹ nhõm",
            "thở ra",
            "buông bỏ",
            "bình tâm",
            "dịu lại",
        ]
    ):
        return "relief_breath"

    if any(
        k in text
        for k in [
            "heart/feeling",
            "heart feeling",
            "feeling",
            "feelings",
            "emotion",
            "emotional warmth",
            "warm heart",
            "heartwarming",
            "heart beat",
            "heartbeat",
            "heart sparkle",
            "soft heart",
            "trái tim",
            "cảm xúc",
            "ấm lòng",
            "rung động",
            "dịu dàng",
        ]
    ):
        return "heart_feeling"

    # Specific visual content families first. These must outrank generic thinking/reflection.
    love_terms = [
        "love",
        "romance",
        "romantic",
        "heart eyes",
        "attachment",
        "clingy",
        "mesmerized",
        "admire",
        "adore",
        "obsessed",
        "crush",
        "affection",
        "floating hearts",
        "say mê",
        "mê mẩn",
    ]
    if any(k in text for k in love_terms) or re.search(r"\bhearts?\b", text):
        return "love_attachment"

    if any(
        k in text
        for k in [
            "book",
            "books",
            "library",
            "reading",
            "bookshelf",
            "book nook",
            "sách",
            "đọc sách",
            "thư viện",
            "kệ sách",
        ]
    ):
        return "books_reading"

    if any(
        k in text
        for k in [
            "fail",
            "failure",
            "fall",
            "falling",
            "trip",
            "tripping",
            "clumsy",
            "mistake",
            "oops",
            "slip",
            "crash",
            "funny fail",
            "vấp",
            "té",
            "ngã",
        ]
    ):
        return "funny_failure"
    if any(
        k in text
        for k in [
            "worse",
            "bad luck",
            "negative escalation",
            "things going wrong",
            "problem gets worse",
            "chain reaction",
            "pile up",
            "disaster",
            "failure",
            "fail",
            "clumsy",
            "tệ hơn",
            "xui",
            "rắc rối",
        ]
    ):
        return "negative_escalation"

    if any(
        k in text
        for k in [
            "better",
            "positive escalation",
            "breakthrough",
            "achievement",
            "success",
            "impossible becomes possible",
            "good news gets better",
            "surprisingly possible",
            "rocket",
            "launch",
            "invention",
            "eureka",
            "tốt hơn",
            "thành công",
            "bứt phá",
            "phát minh",
            "hiện thực",
        ]
    ):
        return "positive_escalation"

    if any(
        k in text
        for k in [
            "freedom",
            "free",
            "release",
            "liberation",
            "breaking free",
            "escape",
            "unlock",
            "unleash",
            "constraint to liberation",
            "tự do",
            "thoát",
            "giải phóng",
        ]
    ):
        return "freedom_release"
    if any(
        k in text
        for k in [
            "work",
            "working",
            "working hard",
            "effort",
            "try",
            "trying",
            "determined",
            "typing",
            "building",
            "drawing",
            "painting",
            "creating",
            "making",
            "bee working",
            "chăm chỉ",
            "nỗ lực",
            "cố gắng",
            "làm việc",
            "xây",
            "vẽ",
        ]
    ):
        return "effort_working"
    if any(
        k in text
        for k in [
            "teach",
            "teaching",
            "explain",
            "explaining",
            "lesson",
            "warning",
            "tell",
            "telling",
            "advice",
            "listen",
            "guidance",
            "instruction",
            "teacher",
            "scolding",
            "no",
            "stop",
            "dạy",
            "khuyên",
            "cảnh báo",
        ]
    ):
        return "teaching_warning"

    if any(
        k in text
        for k in [
            "be yourself",
            "being yourself",
            "self acceptance",
            "self-acceptance",
            "self expression",
            "self-expression",
            "authentic",
            "authenticity",
            "different from crowd",
            "stand out",
            "uniqueness",
            "khác biệt",
            "là chính mình",
        ]
    ):
        return "self_being_yourself"

    if any(
        k in text
        for k in [
            "kindness",
            "gentle",
            "gentleness",
            "warmth",
            "kind",
            "baffled",
            "what just happened",
            "tử tế",
            "ấm áp",
            "dịu dàng",
        ]
    ):
        return "kindness_vs_confusion"

    if any(
        k in text
        for k in [
            "shrug",
            "peaceful",
            "relax",
            "relaxed",
            "acceptance",
            "accept",
            "okay",
            "calm",
            "chill",
            "smile",
            "lightly",
            "gentle",
            "bình yên",
            "thư giãn",
            "chấp nhận",
            "nhún vai",
        ]
    ):
        return "peaceful_acceptance"

    if any(
        k in text
        for k in [
            "search",
            "searching",
            "looking for",
            "find",
            "finding",
            "magnifying",
            "explore",
            "curious",
            "tìm kiếm",
            "tìm",
        ]
    ):
        return "searching"
    if any(
        k in text
        for k in [
            "think",
            "thinking",
            "reflection",
            "reflect",
            "realization",
            "ponder",
            "pondering",
            "confused",
            "confusion",
            "wonder",
            "question",
            "questioning",
            "deep thought",
            "suy nghĩ",
            "ngẫm",
        ]
    ):
        return "thinking_reflection"

    return "general_reflection"


def build_semantic_retry_queries(
    scene_request: dict[str, Any], family: str
) -> list[str]:
    templates: dict[str, list[str]] = {
        "teaching_warning": [
            "cartoon teacher explaining",
            "cartoon giving advice",
            "funny cartoon warning",
            "cute character teaching lesson",
            "cartoon talking and pointing",
            "listener reaction cartoon",
        ],
        "sweets_food": [
            "cute animal eating chocolate",
            "cute animal eating candy",
            "happy cartoon eating sweets",
            "cute character eating dessert",
            "cartoon chocolate happy",
            "cute animal with cake",
        ],
        "heart_feeling": [
            "cute heart sparkle",
            "heartwarming cute sticker",
            "cartoon heart feeling",
            "cute animal soft heart",
            "warm heart cartoon",
            "cute heart hug",
        ],
        "funny_failure": [
            "cute animal fail",
            "clumsy cartoon fall",
            "funny penguin trip",
            "cartoon slip fall",
            "cute character oops",
            "funny cartoon mistake",
        ],
        "planning_writing": [
            "cartoon writing list",
            "funny cartoon planning",
            "cute animal typing fast",
            "checklist cartoon",
            "cartoon taking notes",
            "cute character writing",
        ],
        "sad_gloomy": [
            "sad cute animal",
            "sad cartoon sigh",
            "gloomy cute sticker",
            "crying cute animal",
            "cute cat sad",
            "heartbroken cartoon sticker",
        ],
        "joy_celebration": [
            "cute animal happy dance",
            "happy cartoon jump",
            "sticker joyful",
            "cute character celebrating",
            "happy animal celebrate",
            "proud cartoon dance",
        ],
        "dizzy_chaos": [
            "confused cartoon spinning",
            "cartoon dizzy",
            "stressed cat meme",
            "overwhelmed cartoon",
            "everything is fine cute",
            "panic cartoon sticker",
        ],
        "silence_regret": [
            "cartoon character shh",
            "funny facepalm cartoon",
            "awkward smile meme",
            "cat regret speaking",
            "cute animal silent",
            "oops regret cartoon",
        ],
        "relief_breath": [
            "relieved cute animal",
            "cartoon deep breath",
            "letting go sticker",
            "peaceful smiling sticker",
            "calm cute animal",
            "relaxed cartoon sigh",
        ],
        "effort_working": [
            "funny cartoon working hard",
            "cute animal typing",
            "bee working sticker",
            "cartoon building something",
            "cute animal painting",
            "determined cute character",
        ],
        "peaceful_acceptance": [
            "cute animal shrug",
            "peaceful cartoon smile",
            "relaxed cute sticker",
            "calm cartoon reaction",
            "cute character okay",
            "chill animal cartoon",
        ],
        "searching": [
            "confused cartoon searching",
            "cute cat magnifying glass",
            "cartoon looking for something",
            "curious animal searching",
            "cute character searching",
            "searching cartoon sticker",
        ],
        "thinking_reflection": [
            "cartoon thinking hard",
            "cute character realization",
            "funny cartoon pondering",
            "confused cartoon thinking",
            "deep thought cartoon",
            "realization meme cartoon",
        ],
        "love_attachment": [
            "cute animal heart eyes",
            "cartoon in love reaction",
            "cute clingy character",
            "mesmerized cartoon face",
            "adoring cute animal",
            "obsessed in love cartoon",
        ],
        "friendship_connection": [
            "cute friends hug",
            "best friends cartoon",
            "two buddies high five",
            "cute animal friendship",
            "cartoon friends walking together",
            "wholesome friendship cartoon",
        ],
        "negative_escalation": [
            "cartoon bad luck chain reaction",
            "everything going wrong cartoon",
            "cute character disaster pile up",
            "problem gets worse cartoon",
            "oh no everything is going wrong",
            "cartoon fail chain reaction",
        ],
        "positive_escalation": [
            "rocket launch celebration cartoon",
            "breakthrough success cartoon",
            "surprise good news cartoon",
            "things get even better cartoon",
            "impossible becomes possible cartoon",
            "cute character amazed celebration",
        ],
        "freedom_release": [
            "cartoon breaking free",
            "cute character escape happy",
            "freedom celebration cartoon",
            "release and dance cartoon",
            "unlock freedom cartoon",
            "happy liberation cartoon",
        ],
        "self_being_yourself": [
            "different from crowd cartoon",
            "cute character standing out",
            "be yourself cartoon",
            "proud unique cartoon",
            "one colorful character in crowd",
            "authentic self cartoon",
        ],
        "kindness_vs_confusion": [
            "cute character smiling kindly",
            "warm cartoon kindness",
            "confused reaction cartoon",
            "baffled cute animal",
            "kind gesture cartoon",
            "funny confused reaction",
        ],
        "general_reflection": [
            "cute character thinking",
            "cartoon reflective moment",
            "soft reaction cartoon",
            "whimsical thoughtful cartoon",
            "cute animal pondering",
            "gentle realization cartoon",
        ],
    }

    base_queries = templates.get(family, templates["general_reflection"])

    existing = [
        normalize_text(str(q))
        for q in safe_list(scene_request.get("queries_giphy"))
        if normalize_text(str(q))
    ]

    # Chỉ thêm retry semantic nếu chưa có sẵn.
    result: list[str] = []
    seen: set[str] = set()

    for q in existing + base_queries:
        qn = normalize_text(q)
        if qn and qn not in seen:
            seen.add(qn)
            result.append(qn)

    return result


def extend_scene_queries_with_semantic_retry(
    scene_request: dict[str, Any],
) -> dict[str, Any]:
    family = infer_retry_family(scene_request)
    extended_queries = build_semantic_retry_queries(scene_request, family)

    updated = dict(scene_request)
    updated["retry_family"] = family
    updated["semantic_retry_queries"] = extended_queries

    # GIPHY-first: ưu tiên mở rộng queries_giphy.
    updated["queries_giphy"] = extended_queries

    # Nếu queries_fallback trống thì mirror nhẹ từ semantic retry.
    fallback_queries = [
        normalize_text(str(q))
        for q in safe_list(updated.get("queries_fallback"))
        if normalize_text(str(q))
    ]
    if not fallback_queries:
        updated["queries_fallback"] = extended_queries[:4]

    return updated


def normalize_scene_request(scene: dict[str, Any], index: int) -> dict[str, Any]:
    queries_giphy = [
        normalize_text(str(q))
        for q in safe_list(scene.get("queries_giphy"))
        if normalize_text(str(q))
    ]
    queries_fallback = [
        normalize_text(str(q))
        for q in safe_list(scene.get("queries_fallback"))
        if normalize_text(str(q))
    ]

    # Compatibility with older fields.
    old_query = normalize_text(str(scene.get("search_query_en", "")))
    if old_query and old_query not in queries_giphy:
        queries_giphy.append(old_query)

    # Dedupe while keeping order.
    def dedupe(items: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    return {
        "scene_id": scene.get("scene_id", index),
        "scene_role": scene.get("scene_role", "reflection"),
        "meaning": scene.get("meaning", ""),
        "visual_goal": scene.get("visual_goal", ""),
        "semantic_goal": scene.get("semantic_goal") or scene.get("meaning", ""),
        "visual_intent": scene.get("visual_intent") or scene.get("visual_goal", ""),
        "priority": scene.get("priority", "symbolic"),
        "must_have_elements": [
            str(x).lower()
            for x in safe_list(scene.get("must_have_elements"))
            if str(x).strip()
        ],
        "must_show": [
            str(x).lower()
            for x in safe_list(
                scene.get("must_show") or scene.get("must_have_elements")
            )
            if str(x).strip()
        ],
        "nice_to_have": [
            str(x).lower()
            for x in safe_list(scene.get("nice_to_have"))
            if str(x).strip()
        ],
        "avoid_elements": [
            str(x).lower()
            for x in safe_list(scene.get("avoid_elements") or scene.get("avoid"))
            if str(x).strip()
        ],
        "emotion_target": str(scene.get("emotion_target", "") or "").lower(),
        "queries_giphy": dedupe(queries_giphy)[:8],
        "queries_fallback": dedupe(queries_fallback)[:6],
        "continuity_tags": [
            str(x).lower()
            for x in safe_list(scene.get("continuity_tags"))
            if str(x).strip()
        ],
    }


def collect_candidates_for_scene(
    scene_request: dict[str, Any],
    policy: dict[str, Any],
    *,
    source: str,
    query_round_offset: int = 0,
) -> list[dict[str, Any]]:
    """
    Collect candidates for a scene from one source without selecting immediately.
    """
    limit = int(policy["candidate_limit_per_query"])
    candidates: list[dict[str, Any]] = []

    if source == "giphy":
        queries = scene_request.get("queries_giphy", [])
        search_fn = search_giphy
    elif source == "pexels":
        queries = scene_request.get("queries_fallback", []) or scene_request.get(
            "queries_giphy", []
        )
        search_fn = search_pexels_videos
    else:
        return []

    max_rounds = int(policy["query_rounds_before_fallback"])
    queries = queries[:max_rounds]

    for query_round, query in enumerate(queries, start=1 + query_round_offset):
        if not query:
            continue

        try:
            results = search_fn(query, limit=limit)
        except GiphyRateLimitError:
            raise
        except Exception as e:
            print(f"[WARN] {source} search failed: {query} -> {e}")
            continue

        for item in results:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["search_query_used"] = query
            item["query_round"] = query_round
            candidates.append(item)

    return candidates


def hard_reject_candidate(
    candidate: dict[str, Any],
    video_context: dict[str, Any],
    scene_request: dict[str, Any],
    *,
    avoid_recent_media_days: int = MEDIA_REPEAT_WINDOW_DAYS,
    exclude_media_keys: set[str] | None = None,
) -> dict[str, Any]:
    """
    Metadata-based hard reject.

    Important limitation: this does NOT see actual frames yet. It cannot reliably
    detect text inside GIF frames. Phase 6 should add OCR/vision.
    """
    exclude_media_keys = exclude_media_keys or set()

    normalized = normalize_candidate(candidate)
    reasons: list[str] = []

    media_key = normalized["media_key"]

    if media_key in exclude_media_keys:
        reasons.append("duplicate_within_video")

    if media_used_recently(media_key, days=avoid_recent_media_days):
        reasons.append("recent_duplicate")

    if not normalized.get("mp4_url") and not normalized.get("gif_url"):
        reasons.append("no_media_url")

    title_url = f"{normalized.get('title', '')} {normalized.get('page_url', '')}"

    # Do not hard-reject by meme/reaction/pop-culture-ish metadata here.
    # Some reference-style GIFs are meme/cartoon/reaction. Let the scorer penalize
    # risky metadata, but keep technically usable candidates in the shortlist.
    # Avoid elements from planner.
    avoid_elements = " ".join(scene_request.get("avoid_elements", []))
    prohibited_visuals = " ".join(safe_list(video_context.get("prohibited_visuals")))
    combined_rules = f"{avoid_elements} {prohibited_visuals}".lower()
    candidate_text = title_url.lower()

    for danger in ["interview", "talking head", "watermark", "celebrity", "news"]:
        if danger in combined_rules and danger in candidate_text:
            reasons.append(f"prohibited_visual:{danger}")

    w = safe_int(normalized.get("width"))
    h = safe_int(normalized.get("height"))
    if w and h:
        aspect = w / h
        # Very wide GIFs often crop badly in 9:16.
        if aspect > 1.8:
            reasons.append("bad_aspect_for_vertical_crop")
        if max(w, h) < 240:
            reasons.append("too_low_resolution")

    return {
        "rejected": bool(reasons),
        "reasons": reasons,
    }


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def infer_scene_role_intent(scene_request: dict[str, Any]) -> str:
    parts = [
        str(scene_request.get("scene_role", "")),
        str(scene_request.get("meaning", "")),
        str(scene_request.get("visual_goal", "")),
        str(scene_request.get("semantic_goal", "")),
        str(scene_request.get("visual_intent", "")),
        str(scene_request.get("emotion_target", "")),
        " ".join(map(str, scene_request.get("must_have_elements", []))),
        " ".join(map(str, scene_request.get("must_show", []))),
        " ".join(map(str, scene_request.get("queries_giphy", []))),
        " ".join(map(str, scene_request.get("queries_fallback", []))),
    ]
    text = normalize_text(" ".join(parts))

    if any(
        k in text
        for k in [
            "worse",
            "worse than expected",
            "bad luck",
            "things going wrong",
            "everything going wrong",
            "problem gets worse",
            "small problem",
            "bigger problem",
            "chain reaction",
            "pile up",
            "disaster",
            "fail chain",
            "negative escalation",
            "gets worse",
            "going wrong",
            "tệ hơn",
            "tệ nhất",
            "xấu hơn",
            "mọi chuyện tệ",
            "rắc rối",
            "xui xẻo",
        ]
    ):
        return "negative_escalation"

    if any(
        k in text
        for k in [
            "better",
            "better than expected",
            "things get even better",
            "good news",
            "breakthrough",
            "impossible becomes possible",
            "rocket",
            "rocket launch",
            "invention",
            "achievement",
            "success",
            "positive escalation",
            "surprisingly possible",
            "becomes possible",
            "tốt hơn",
            "tuyệt vời hơn",
            "có thể",
            "hiện thực",
            "bứt phá",
            "thành công",
            "phát minh",
            "tên lửa",
        ]
    ):
        return "positive_escalation"

    if any(
        k in text
        for k in [
            "do not",
            "don't",
            "dont",
            "cannot",
            "can't",
            "cant",
            "never",
            "mustn't",
            "mustnt",
            "forbidden",
            "warning",
            "warn",
            "saying no",
            "say no",
            "says no",
            "reject",
            "rejection",
            "limit",
            "limitation",
            "restriction",
            "teacher",
            "pointing",
            "scolding",
            "không thể",
            "đừng",
            "không được",
            "không nên",
            "không bao giờ",
            "cấm",
            "phủ định",
            "ngăn cản",
        ]
    ):
        return "external_negation"

    if any(
        k in text
        for k in [
            "listen",
            "listening",
            "hear",
            "hearing",
            "think",
            "thinking",
            "reflect",
            "reflection",
            "processing",
            "consider",
            "wonder",
            "wondering",
            "confused",
            "idea",
            "mind",
            "brain",
            "lắng nghe",
            "suy nghĩ",
            "ngẫm",
            "cân nhắc",
            "bối rối",
        ]
    ):
        return "reflection"

    if any(
        k in text
        for k in [
            "possible",
            "possibility",
            "happen",
            "anything",
            "everything",
            "real",
            "reality",
            "dream",
            "come true",
            "breakthrough",
            "rocket",
            "launch",
            "flying",
            "fly",
            "invention",
            "success",
            "achievement",
            "victory",
            "freedom",
            "free",
            "có thể",
            "xảy ra",
            "hiện thực",
            "thành hiện thực",
            "bứt phá",
            "tên lửa",
            "bay",
            "phát minh",
        ]
    ):
        return "breakthrough"

    if any(
        k in text
        for k in [
            "friend",
            "friends",
            "friendship",
            "together",
            "beside",
            "side by side",
            "hug",
            "comfort",
            "support",
            "help",
            "bạn",
            "tình bạn",
            "bên cạnh",
            "đồng hành",
            "ôm",
            "giúp",
        ]
    ):
        return "connection"

    role = str(scene_request.get("scene_role", "reflection")).lower().strip()
    if role in SCENE_ROLE_INTENTS:
        return role
    return "reflection"


def role_intent_score_from_tokens(
    *,
    role_intent: str,
    evidence_tokens: set[str],
) -> tuple[float, list[str], list[str]]:
    policy = SCENE_ROLE_INTENTS.get(role_intent)
    if not policy:
        return 0.0, [], []

    wanted = policy.get("wanted", set())
    avoid = policy.get("avoid", set())

    wanted_hits = sorted(evidence_tokens & wanted)
    avoid_hits = sorted(evidence_tokens & avoid)

    score = min(20.0, len(wanted_hits) * 6.0)
    if role_intent in {"breakthrough", "external_negation"} and wanted_hits:
        score += 3.0

    score -= min(20.0, len(avoid_hits) * 8.0)
    return clamp(score, 0.0, 20.0), wanted_hits, avoid_hits


def score_candidate_for_scene(
    candidate: dict[str, Any],
    video_context: dict[str, Any],
    scene_request: dict[str, Any],
) -> dict[str, Any]:
    """
    Balanced semantic scorer for quote-video media selection.

    Important:
    - Candidate metadata should NOT include search_query_used, otherwise score is fake-high.
    - But the search query itself is still useful evidence because the candidate came from that query.
    - So we score:
      1) candidate metadata fit
      2) query-to-scene alignment
      3) technical/readability/loop quality
    """

    normalized = normalize_candidate(candidate)

    title = str(normalized.get("title", ""))
    page_url = str(normalized.get("page_url", ""))
    search_query_used = str(normalized.get("search_query_used", ""))

    # Candidate evidence only. Do not include search_query_used here.
    candidate_haystack = f"{title} {page_url}"

    candidate_tokens = tokenize(candidate_haystack)
    query_tokens = tokenize(search_query_used)

    motif_tokens = tokenize(str(video_context.get("motif_main", "")))
    visual_world_tokens = tokenize(str(video_context.get("visual_world", "")))

    scene_meaning_tokens = tokenize(str(scene_request.get("meaning", "")))
    visual_goal_tokens = tokenize(str(scene_request.get("visual_goal", "")))

    must_have_tokens = set()
    for x in safe_list(scene_request.get("must_have_elements")):
        must_have_tokens |= tokenize(str(x))

    avoid_tokens = set()
    for x in safe_list(scene_request.get("avoid_elements")):
        avoid_tokens |= tokenize(str(x))

    continuity_tokens = set()
    for x in safe_list(scene_request.get("continuity_tags")):
        continuity_tokens |= tokenize(str(x))

    role_tokens = tokenize(str(scene_request.get("scene_role", "")))
    semantic_goal_tokens = tokenize(str(scene_request.get("semantic_goal", "")))
    visual_intent_tokens = tokenize(str(scene_request.get("visual_intent", "")))
    emotion_target_tokens = tokenize(str(scene_request.get("emotion_target", "")))

    must_show_tokens = set()
    for x in safe_list(scene_request.get("must_show")):
        must_show_tokens |= tokenize(str(x))

    nice_to_have_tokens = set()
    for x in safe_list(scene_request.get("nice_to_have")):
        nice_to_have_tokens |= tokenize(str(x))

    scene_intent_tokens = (
        scene_meaning_tokens
        | visual_goal_tokens
        | must_have_tokens
        | motif_tokens
        | continuity_tokens
        | role_tokens
        | semantic_goal_tokens
        | visual_intent_tokens
        | emotion_target_tokens
        | must_show_tokens
        | nice_to_have_tokens
    )

    # Candidate metadata evidence.
    query_overlap = len(query_tokens & candidate_tokens)
    motif_overlap = len(motif_tokens & candidate_tokens)
    meaning_overlap = len(scene_meaning_tokens & candidate_tokens)
    goal_overlap = len(visual_goal_tokens & candidate_tokens)
    must_have_overlap = len(must_have_tokens & candidate_tokens)
    continuity_overlap = len(continuity_tokens & candidate_tokens)
    world_overlap = len(visual_world_tokens & candidate_tokens)
    good_vibe_overlap = len(candidate_tokens & GOOD_VIBE_TERMS)
    avoid_hits = len(avoid_tokens & candidate_tokens)

    # Search-query evidence. This avoids total failure when GIPHY metadata is sparse.
    query_scene_alignment = len(query_tokens & scene_intent_tokens)
    query_must_alignment = len(query_tokens & (must_have_tokens | must_show_tokens))

    role_intent = infer_scene_role_intent(scene_request)
    role_evidence_tokens = candidate_tokens | query_tokens
    role_fit, role_wanted_hits, role_avoid_hits = role_intent_score_from_tokens(
        role_intent=role_intent,
        evidence_tokens=role_evidence_tokens,
    )

    semantic_fit = (
        8
        + meaning_overlap * 6
        + goal_overlap * 5
        + must_have_overlap * 8
        + len(must_show_tokens & candidate_tokens) * 7
        + len(semantic_goal_tokens & candidate_tokens) * 4
        + len(visual_intent_tokens & candidate_tokens) * 4
        + query_overlap * 3
        + motif_overlap * 3
        + continuity_overlap * 2
        + query_scene_alignment * 3
        + query_must_alignment * 4
    )
    semantic_fit = clamp(semantic_fit, 0, 35)

    mood_fit = 5 + world_overlap * 3 + good_vibe_overlap * 1.5
    mood_fit = clamp(mood_fit, 0, 15)

    cleanliness = 15.0
    metadata_text = candidate_haystack.lower()
    if contains_bad_term(metadata_text):
        cleanliness -= 5
    bad, _ = looks_like_pop_culture_or_text_overlay(candidate)
    if bad:
        cleanliness -= 4
    cleanliness = clamp(cleanliness, 0, 15)

    ds = dimension_score(
        normalized.get("width"), normalized.get("height"), source=normalized["source"]
    )
    readability = clamp(5 + ds, 0, 10)

    duration = safe_float(normalized.get("duration_sec"))
    if duration is None:
        loop_quality = 3.0
    elif 2.0 <= duration <= 7.0:
        loop_quality = 5.0
    elif 1.0 <= duration < 2.0 or 7.0 < duration <= 10.0:
        loop_quality = 3.5
    else:
        loop_quality = 2.0

    source_bonus = 2.0 if normalized["source"] == "giphy" else 0.5

    penalty = 0.0

    # Penalize generic cute GIFs only when both candidate metadata and query intent are weak.
    if semantic_fit < 15 and good_vibe_overlap > 0 and query_scene_alignment == 0:
        penalty += 6.0

    if avoid_hits > 0:
        penalty += min(10.0, avoid_hits * 4.0)

    if role_avoid_hits:
        penalty += min(18.0, len(role_avoid_hits) * 8.0)

    # Penalize generic mood-only matches for roles that need a clear logic beat.
    if (
        role_intent
        in {
            "external_negation",
            "negative_escalation",
            "positive_escalation",
            "breakthrough",
        }
        and role_fit < 4
    ):
        penalty += 12.0

    query_round = safe_int(normalized.get("query_round")) or 1
    if query_round >= 2:
        penalty += min(3.0, (query_round - 1) * 1.0)

    # Hard low-evidence penalty only if both metadata and query alignment are absent.
    if (
        meaning_overlap
        + goal_overlap
        + must_have_overlap
        + query_overlap
        + motif_overlap
        + query_scene_alignment
    ) == 0:
        penalty += 8.0

    total = (
        semantic_fit
        + role_fit
        + mood_fit
        + cleanliness
        + readability
        + loop_quality
        + source_bonus
        - penalty
    )
    total = clamp(total, 0, 100)

    breakdown = {
        "semantic_fit": round(semantic_fit, 2),
        "role_fit": round(role_fit, 2),
        "inferred_scene_role": role_intent,
        "role_wanted_hits": role_wanted_hits,
        "role_avoid_hits": role_avoid_hits,
        "mood_fit": round(mood_fit, 2),
        "cleanliness": round(cleanliness, 2),
        "text_readability": round(readability, 2),
        "loop_quality": round(loop_quality, 2),
        "source_bonus": round(source_bonus, 2),
        "penalty": round(penalty, 2),
        "query_scene_alignment": query_scene_alignment,
        "query_must_alignment": query_must_alignment,
        "metadata_query_overlap": query_overlap,
        "total_score": round(total, 2),
    }

    why_it_fits = []
    if must_have_overlap:
        why_it_fits.append(f"metadata matches must-have elements ({must_have_overlap})")
    if meaning_overlap:
        why_it_fits.append(f"metadata matches scene meaning ({meaning_overlap})")
    if goal_overlap:
        why_it_fits.append(f"metadata matches visual goal ({goal_overlap})")
    if query_overlap:
        why_it_fits.append(f"metadata matches query tokens ({query_overlap})")
    if query_scene_alignment:
        why_it_fits.append(
            f"search query aligns with scene intent ({query_scene_alignment})"
        )
    if query_must_alignment:
        why_it_fits.append(
            f"search query aligns with must-have elements ({query_must_alignment})"
        )
    if role_wanted_hits:
        why_it_fits.append(
            f"role {role_intent} evidence: {','.join(role_wanted_hits[:5])}"
        )

    why_it_might_fail = []
    if avoid_hits:
        why_it_might_fail.append(f"hits avoid elements ({avoid_hits})")
    if role_avoid_hits:
        why_it_might_fail.append(
            f"role {role_intent} conflict: {','.join(role_avoid_hits[:5])}"
        )
    if (
        role_intent
        in {
            "external_negation",
            "negative_escalation",
            "positive_escalation",
            "breakthrough",
        }
        and role_fit < 4
    ):
        why_it_might_fail.append(f"weak narrative role fit for {role_intent}")
    if semantic_fit < 16:
        why_it_might_fail.append("semantic fit still weak")
    if query_round >= 2:
        why_it_might_fail.append("picked from fallback/later query")
    if contains_bad_term(metadata_text):
        why_it_might_fail.append("metadata contains risky terms")

    return {
        "score_breakdown": breakdown,
        "judge_summary": {
            "why_it_fits": "; ".join(why_it_fits)
            or "partial query/metadata evidence of semantic fit",
            "why_it_might_fail": "; ".join(why_it_might_fail)
            or "no strong metadata risk found",
            "decision": (
                "accept" if total >= 65 else ("shortlist" if total >= 38 else "reject")
            ),
        },
    }


def extract_json_object_safe(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None

    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def score_0_10(value: Any, default: float = 0.0) -> float:
    try:
        return clamp(float(value), 0.0, 10.0)
    except Exception:
        return default


def build_vision_judge_prompt(
    *,
    video_context: dict[str, Any],
    scene_request: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    return f"""
You are judging whether a GIF/video preview fits a short quote video scene.

The preview sheet contains frames from the same GIF/video. Judge the visual content, not just the title.

VIDEO / QUOTE CONTEXT:
- core meaning: {video_context.get("core_meaning", "")}
- motif: {video_context.get("motif_main", "")}
- visual world: {video_context.get("visual_world", "")}
- preferred traits: {safe_list(video_context.get("preferred_visual_traits"))}
- prohibited visuals: {safe_list(video_context.get("prohibited_visuals"))}

SCENE:
- role: {scene_request.get("scene_role", "")}
- inferred logic role: {infer_scene_role_intent(scene_request)}
- meaning: {scene_request.get("meaning", "")}
- semantic goal: {scene_request.get("semantic_goal", "")}
- visual goal: {scene_request.get("visual_goal", "")}
- visual intent: {scene_request.get("visual_intent", "")}
- must have: {scene_request.get("must_have_elements", [])}
- must show: {scene_request.get("must_show", [])}
- emotion target: {scene_request.get("emotion_target", "")}
- avoid: {scene_request.get("avoid_elements", [])}

CANDIDATE:
- title: {candidate.get("title", "")}
- search query used: {candidate.get("search_query_used", "")}
- source: {candidate.get("source", "")}

Return only valid JSON with this schema:
{{
  "subjects": ["short subject list"],
  "action": "what happens visually",
  "emotion": "dominant emotion",
  "humor_style": "none | cute | absurd | sarcastic | deadpan | slapstick | wholesome | other",
  "visual_style": "cartoon_sticker | anime | cute_animation | realistic_human | realistic_animal | cinematic_stock | abstract_symbol | mixed | unknown",
  "visual_clarity_score": 0,
  "semantic_match_score": 0,
  "scene_role_match_score": 0,
  "role_mismatch_reason": "",
  "mood_match_score": 0,
  "text_safety_score": 0,
  "loop_quality_guess": 0,
  "risk_flags": ["mostly_blank | unclear_subject | chaotic | too_much_text | contradicting_text | celebrity | political | watermark | none"],
  "fit_decision": "strong_fit | usable | weak_fit | reject",
  "fit_reason": "one concise reason"
}}

Scoring guide:
- semantic_match_score: how well the visual meaning matches the scene meaning and visual goal.
- scene_role_match_score: how well the GIF performs the inferred logic role in the quote's argument. Do not give a high role score for mood-only matches.
  For negative_escalation, the GIF must show a problem getting worse, bad luck, failure, disaster, or chain reaction.
  For positive_escalation, the GIF must show breakthrough, success, rocket/launch, invention, good news, surprise upgrade, or something becoming possible.
- mood_match_score: how well the emotion/vibe matches.
- visual_clarity_score: whether a viewer can instantly understand the GIF.
- text_safety_score: high if no distracting/contradicting text is visible.
- loop_quality_guess: estimate from the preview; penalize mostly blank, static, or chaotic previews.
- visual_style:
  cartoon_sticker = flat/cartoon/sticker/GIF animation style.
  anime = anime-like animated style.
  cute_animation = soft/cute animation, not realistic footage.
  realistic_human = real people/live action.
  realistic_animal = real animal footage.
  cinematic_stock = cinematic or stock-video looking real footage.
  abstract_symbol = symbolic/poetic object shot, flower/reflection/light/etc.
  mixed = multiple styles in the same GIF or unclear mixed source.
  unknown = cannot determine.
""".strip()


def vision_score_from_analysis(analysis: dict[str, Any]) -> float:
    semantic = score_0_10(analysis.get("semantic_match_score"))
    mood = score_0_10(analysis.get("mood_match_score"))
    role_match = score_0_10(analysis.get("scene_role_match_score"), default=5.0)
    clarity = score_0_10(analysis.get("visual_clarity_score"))
    text_safety = score_0_10(analysis.get("text_safety_score"), default=7.0)
    loop_guess = score_0_10(analysis.get("loop_quality_guess"), default=5.0)

    score = (
        semantic * 3.5
        + mood * 2.0
        + role_match * 2.5
        + clarity * 2.0
        + text_safety * 1.5
        + loop_guess * 1.0
    )

    decision = str(analysis.get("fit_decision", "")).strip().lower()
    risk_flags = {
        str(x).strip().lower()
        for x in safe_list(analysis.get("risk_flags"))
        if str(x).strip()
    }

    if role_match <= 3:
        score -= 25

    if decision == "reject":
        score -= 40
    elif decision == "weak_fit":
        score -= 15
    elif decision == "strong_fit":
        score += 8

    if "mostly_blank" in risk_flags:
        score -= 30
    if "unclear_subject" in risk_flags:
        score -= 20
    if "contradicting_text" in risk_flags:
        score -= 30
    if "too_much_text" in risk_flags:
        score -= 15
    if "celebrity" in risk_flags or "political" in risk_flags:
        score -= 25
    if "watermark" in risk_flags:
        score -= 12

    return round(clamp(score, 0, 100), 2)


def analyze_candidate_with_vision(
    *,
    candidate: dict[str, Any],
    scene_request: dict[str, Any],
    video_context: dict[str, Any],
) -> dict[str, Any] | None:
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        print("[VISION WARN] GOOGLE_API_KEY missing; skip vision rerank")
        return None

    previewed = ensure_preview_sheet(candidate)
    preview_sheet = previewed.get("preview_sheet")
    if not preview_sheet:
        return None

    try:
        image_bytes = open(preview_sheet, "rb").read()
    except Exception as e:
        print(f"[VISION WARN] cannot read preview sheet: {preview_sheet} -> {e}")
        return None

    prompt = build_vision_judge_prompt(
        video_context=video_context,
        scene_request=scene_request,
        candidate=previewed,
    )

    client = genai.Client(api_key=api_key)
    model_candidates = get_vision_model_candidates()

    if not model_candidates:
        print("[VISION WARN] no vision model configured")
        return None
    if not has_available_vision_model():
        raise RuntimeError("No available vision model left for this run")
    last_error: Exception | None = None

    for model_name in model_candidates:
        if model_name in VISION_DISABLED_MODELS:
            continue

        print(f"[VISION MODEL] {model_name} candidate={candidate.get('media_key')}")

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                ],
            )
            raw_text = response.text or ""

        except Exception as e:
            last_error = e

            if is_quota_error(e):
                VISION_DISABLED_MODELS.add(model_name)
                print(
                    f"[VISION QUOTA STOP] model={model_name} "
                    f"candidate={candidate.get('media_key')}: {e}"
                )
                continue

            if is_model_unstable_error(e):
                if should_disable_unstable_model(model_name, e):
                    VISION_DISABLED_MODELS.add(model_name)
                    print(
                        f"[VISION MODEL DISABLED] model={model_name} "
                        f"errors={VISION_MODEL_ERROR_COUNTS.get(model_name, 0)} "
                        f"candidate={candidate.get('media_key')}: {e}"
                    )
                else:
                    print(
                        f"[VISION MODEL WARN] model={model_name} "
                        f"errors={VISION_MODEL_ERROR_COUNTS.get(model_name, 0)} "
                        f"candidate={candidate.get('media_key')}: {e}"
                    )
                continue

            print(
                f"[VISION WARN] model failed for {candidate.get('media_key')} "
                f"model={model_name}: {e}"
            )
            continue

        data = extract_json_object_safe(raw_text)
        if not data:
            print(
                f"[VISION WARN] invalid vision JSON for {candidate.get('media_key')} "
                f"model={model_name}: {raw_text[:160]}"
            )
            continue

        data["_model_name"] = model_name
        data["_preview_sheet"] = preview_sheet
        data["_raw_text"] = raw_text[:800]
        VISION_MODEL_ERROR_COUNTS[model_name] = 0
        return data

    if last_error:
        print(
            f"[VISION WARN] all vision models failed for "
            f"{candidate.get('media_key')}: {last_error}"
        )
    else:
        print(f"[VISION WARN] all vision models disabled for {candidate.get('media_key')}")
    if not has_available_vision_model():
        raise RuntimeError("No available vision model left for this run")
    return None
def rerank_scene_shortlist_with_vision(
    *,
    scene_request: dict[str, Any],
    shortlist: list[dict[str, Any]],
    video_context: dict[str, Any],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    if not shortlist:
        return shortlist

    top_k = max(0, int(policy.get("vision_rerank_top_k", 3)))
    metadata_weight = float(policy.get("metadata_weight", 0.45))
    vision_weight = float(policy.get("vision_weight", 0.55))

    reranked: list[dict[str, Any]] = []
    top_candidates = shortlist[:top_k]
    rest = shortlist[top_k:]

    for candidate in top_candidates:
        candidate = dict(candidate)
        metadata_score = float(candidate["score_breakdown"]["total_score"])

        analysis = analyze_candidate_with_vision(
            candidate=candidate,
            scene_request=scene_request,
            video_context=video_context,
        )

        if analysis:
            v_score = vision_score_from_analysis(analysis)
            final_score = metadata_score * metadata_weight + v_score * vision_weight
            candidate["vision_analysis"] = analysis
            candidate["vision_score"] = round(v_score, 2)
            candidate["final_score"] = round(final_score, 2)
            print(
                "[VISION]",
                f"scene={scene_request.get('scene_id')}",
                f"candidate={candidate.get('media_key')}",
                f"decision={analysis.get('fit_decision')}",
                f"style={analysis.get('visual_style')}",
                f"vision_score={candidate['vision_score']}",
                f"final_score={candidate['final_score']}",
                f"reason={analysis.get('fit_reason', '')[:100]}",
                
            )
        else:
            candidate["vision_analysis"] = None
            candidate["vision_score"] = None
            candidate["final_score"] = metadata_score

        reranked.append(candidate)

    for candidate in rest:
        candidate = dict(candidate)
        candidate["vision_analysis"] = None
        candidate["vision_score"] = None
        candidate["final_score"] = float(candidate["score_breakdown"]["total_score"])
        reranked.append(candidate)

    reranked.sort(
        key=lambda x: x.get("final_score", x["score_breakdown"]["total_score"]),
        reverse=True,
    )
    return reranked


def candidate_is_eligible(
    item: dict[str, Any], policy: dict[str, Any]
) -> tuple[bool, str]:
    """
    Hard gate for final render eligibility.

    Vision reject means the candidate must not be rendered. This prevents the
    pipeline from choosing media that the vision judge already marked as bad.
    """
    final_score = float(item.get("final_score", item["score_breakdown"]["total_score"]))
    metadata_score = float(item["score_breakdown"]["total_score"])

    min_final = float(policy.get("min_final_scene_score", 55))
    min_vision = float(policy.get("min_vision_scene_score", 45))
    min_role = float(policy.get("min_scene_role_match_score", 4))
    min_metadata = float(policy.get("min_metadata_scene_score", 38))

    analysis = item.get("vision_analysis")

    if bool(policy.get("use_vision_rerank", False)) and not isinstance(analysis, dict):
        if not bool(policy.get("allow_unvisioned_candidates", False)):
            return False, "vision_missing_or_failed"

    if isinstance(analysis, dict):
        decision = str(analysis.get("fit_decision", "")).strip().lower()
        vision_score = item.get("vision_score")
        role_score = score_0_10(analysis.get("scene_role_match_score"), default=5)

        if decision == "reject":
            return False, "vision_reject"

        if role_score < min_role:
            return False, f"scene_role_match_too_low:{role_score}"

        if vision_score is not None and float(vision_score) < min_vision:
            return False, f"vision_score_too_low:{vision_score}"

        if bool(policy.get("allow_relaxed_vision_candidates", True)):
            relaxed_min_vision = float(policy.get("relaxed_min_vision_score", 70))
            relaxed_min_final = float(policy.get("relaxed_min_final_score", 50))
            relaxed_min_role = float(policy.get("relaxed_min_role_score", 4))

            if (
                decision in {"strong_fit", "usable", "weak_fit"}
                and vision_score is not None
                and float(vision_score) >= relaxed_min_vision
                and final_score >= relaxed_min_final
                and role_score >= relaxed_min_role
            ):
                return True, f"eligible_relaxed_vision:{decision}"

    if final_score < min_final:
        return False, f"final_score_too_low:{round(final_score, 2)}"

    if metadata_score < min_metadata:
        return False, f"metadata_score_too_low:{round(metadata_score, 2)}"

    return True, "eligible"


def apply_hard_gate_to_shortlist(
    *,
    scene_request: dict[str, Any],
    shortlist: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not shortlist:
        return shortlist, rejected

    eligible: list[dict[str, Any]] = []

    for item in shortlist:
        ok, reason = candidate_is_eligible(item, policy)
        item["eligible"] = ok
        item["ineligible_reason"] = reason

        if ok:
            eligible.append(item)
            continue

        rejected.append(
            {
                "candidate_id": item.get("candidate_id"),
                "source": item.get("source"),
                "search_query_used": item.get("search_query_used", ""),
                "scene_id": scene_request.get("scene_id"),
                "reject_stage": "hard_gate",
                "reasons": [reason],
                "vision_decision": (
                    item.get("vision_analysis", {}).get("fit_decision")
                    if isinstance(item.get("vision_analysis"), dict)
                    else None
                ),
                "vision_score": item.get("vision_score"),
                "final_score": item.get("final_score"),
                "metadata_score": item.get("score_breakdown", {}).get("total_score"),
            }
        )

    if eligible:
        return eligible, rejected

    if bool(policy.get("allow_best_available_below_threshold", False)):
        best = dict(shortlist[0])
        best["eligible"] = True
        best["ineligible_reason"] = "allowed_best_available_below_threshold"
        best["judge_summary"] = {
            **best.get("judge_summary", {}),
            "decision": "best_available_below_threshold",
            "why_it_might_fail": (
                str(best.get("judge_summary", {}).get("why_it_might_fail", ""))
                + "; hard gate bypassed by ALLOW_BEST_AVAILABLE=1"
            ).strip("; "),
        }
        print(
            "[MEDIA WARN] Hard gate found no eligible candidate; using best available because ALLOW_BEST_AVAILABLE=1:",
            scene_request.get("scene_id"),
            best.get("media_key"),
            best.get("ineligible_reason"),
        )
        return [best], rejected

    print(
        "[MEDIA FAIL] No eligible candidate after hard gate:",
        f"scene={scene_request.get('scene_id')}",
        f"role={scene_request.get('scene_role')}",
        f"goal={scene_request.get('visual_goal')}",
    )
    return [], rejected


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        value = normalize_text(str(item))
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def build_scene_retry_queries(scene_request: dict[str, Any]) -> list[str]:
    """
    Build same-family retry queries when the first candidate pool fails.

    Important: retry must not drift semantic family. For example, a love/heart
    scene must not retry with generic thinking/confused queries.
    """
    family = infer_retry_family(scene_request)
    all_semantic = build_semantic_retry_queries(scene_request, family)

    existing = dedupe_keep_order(
        [str(x) for x in safe_list(scene_request.get("queries_giphy"))]
        + [str(x) for x in safe_list(scene_request.get("queries_fallback"))]
    )
    existing_set = {normalize_text(q) for q in existing}

    # Start with new same-family semantic variants. Existing queries already failed,
    # so they go later as backup rather than first.
    fresh_semantic = [q for q in all_semantic if normalize_text(q) not in existing_set]
    queries: list[str] = fresh_semantic + existing

    text = normalize_text(
        " ".join(
            [
                str(scene_request.get("meaning", "")),
                str(scene_request.get("visual_goal", "")),
                str(scene_request.get("semantic_goal", "")),
                str(scene_request.get("visual_intent", "")),
                str(scene_request.get("emotion_target", "")),
                " ".join(map(str, safe_list(scene_request.get("must_have_elements")))),
                " ".join(map(str, safe_list(scene_request.get("must_show")))),
                " ".join(map(str, safe_list(scene_request.get("nice_to_have")))),
            ]
        )
    )

    # Content-specific boosters stay in the same family and should be placed near the front.
    boosters: list[str] = []
    if family == "books_reading":
        boosters += [
            "cozy library cartoon",
            "cute animal reading books",
            "book pile cartoon",
            "reading room cozy cartoon",
            "cute cat reading book",
            "bookshelf cartoon cozy",
        ]
    if family == "love_attachment":
        boosters += [
            "cute animal heart eyes",
            "cartoon in love reaction",
            "cute cat floating hearts",
            "puppy love hearts",
            "heart pop cartoon",
            "cute animal love sticker",
        ]

    if family == "negative_escalation" or any(
        k in text
        for k in [
            "pile",
            "piling",
            "clutter",
            "objects",
            "stuff",
            "messy",
            "đống",
            "bừa bộn",
        ]
    ):
        boosters += [
            "pile of stuff cartoon",
            "messy room cartoon",
            "clutter cartoon",
            "overwhelmed by things cartoon",
            "cartoon stuff piling up",
        ]

    if any(k in text for k in ["flower", "flowers", "garden", "hoa", "vườn"]):
        boosters += [
            "cute animal flowers",
            "cartoon garden flowers",
            "bunny flower field",
            "cat walking garden",
        ]

    if family == "friendship_connection" or any(
        k in text
        for k in [
            "comfort",
            "companionship",
            "hug",
            "support",
            "an ủi",
            "ôm",
            "đồng hành",
        ]
    ):
        boosters += [
            "comforting hug cartoon",
            "cute friends hug",
            "two animals hugging",
            "cute animal comfort",
            "friends support sticker",
        ]

    return dedupe_keep_order(boosters + queries)[:12]


def collect_scene_retry_candidates(
    scene_request: dict[str, Any],
    policy: dict[str, Any],
    *,
    source: str,
    query_round_offset: int,
) -> list[dict[str, Any]]:
    retry_queries = build_scene_retry_queries(scene_request)
    if not retry_queries:
        return []

    retry_scene = dict(scene_request)
    retry_scene["queries_giphy"] = retry_queries
    retry_scene["queries_fallback"] = retry_queries

    retry_policy = dict(policy)
    retry_policy["query_rounds_before_fallback"] = max(
        1,
        min(len(retry_queries), int(policy.get("scene_retry_query_rounds", 4))),
    )

    retry_family = infer_retry_family(scene_request)
    print(
        "[MEDIA RETRY]",
        f"scene={scene_request.get('scene_id')}",
        f"source={source}",
        f"family={retry_family}",
        f"queries={retry_queries[: int(retry_policy['query_rounds_before_fallback'])]}",
    )

    return collect_candidates_for_scene(
        retry_scene,
        retry_policy,
        source=source,
        query_round_offset=query_round_offset,
    )


def build_scene_shortlist(
    scene_request: dict[str, Any],
    candidates: list[dict[str, Any]],
    video_context: dict[str, Any],
    policy: dict[str, Any],
    *,
    exclude_media_keys: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    shortlist: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_media_keys: set[str] = set()
    exclude_media_keys = exclude_media_keys or set()

    for raw in candidates:
        candidate = normalize_candidate(raw)
        media_key = candidate["media_key"]

        if media_key in seen_media_keys:
            continue
        seen_media_keys.add(media_key)

        hard = hard_reject_candidate(
            candidate,
            video_context,
            scene_request,
            avoid_recent_media_days=int(policy["avoid_recent_media_days"]),
            exclude_media_keys=exclude_media_keys,
        )

        if hard["rejected"]:
            rejected.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "source": candidate["source"],
                    "search_query_used": candidate.get("search_query_used", ""),
                    "reject_stage": "hard_reject",
                    "reasons": hard["reasons"],
                }
            )
            continue

        scored = score_candidate_for_scene(candidate, video_context, scene_request)
        total = scored["score_breakdown"]["total_score"]

        item = {
            **candidate,
            "score_breakdown": scored["score_breakdown"],
            "judge_summary": scored["judge_summary"],
        }

        if total >= float(policy["min_acceptable_score"]):
            shortlist.append(item)
        else:
            rejected.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "source": candidate["source"],
                    "search_query_used": candidate.get("search_query_used", ""),
                    "reject_stage": "scoring",
                    "reasons": [f"score_below_threshold:{total}"],
                }
            )

    shortlist.sort(key=lambda x: x["score_breakdown"]["total_score"], reverse=True)

    # Strict default:
    # Do not use best-available media unless explicitly enabled. A bad/mismatched
    # GIF is worse than failing this quote and letting main.py try another quote.
    if not shortlist and bool(
        policy.get("allow_best_available_below_threshold", False)
    ):
        scored_fallback = []

        for raw in candidates:
            candidate = normalize_candidate(raw)

            # Still skip unusable media.
            if not candidate.get("mp4_url") and not candidate.get("gif_url"):
                continue

            scored = score_candidate_for_scene(candidate, video_context, scene_request)

            item = {
                **candidate,
                "score_breakdown": scored["score_breakdown"],
                "judge_summary": {
                    **scored["judge_summary"],
                    "decision": "best_available_below_threshold",
                },
            }
            scored_fallback.append(item)

        scored_fallback.sort(
            key=lambda x: x["score_breakdown"]["total_score"], reverse=True
        )

        if scored_fallback:
            print(
                "[MEDIA WARN] No candidate passed threshold; using best available because ALLOW_BEST_AVAILABLE=1:",
                scored_fallback[0].get("search_query_used", ""),
                scored_fallback[0]["score_breakdown"],
            )
            shortlist = scored_fallback[: int(policy["shortlist_size_per_scene"])]

    if shortlist:
        if bool(policy.get("use_vision_rerank", False)):
            shortlist = rerank_scene_shortlist_with_vision(
                scene_request=scene_request,
                shortlist=shortlist,
                video_context=video_context,
                policy=policy,
            )
        else:
            for item in shortlist:
                item["vision_analysis"] = None
                item["vision_score"] = None
                item["final_score"] = item["score_breakdown"]["total_score"]

        shortlist, rejected = apply_hard_gate_to_shortlist(
            scene_request=scene_request,
            shortlist=shortlist,
            rejected=rejected,
            policy=policy,
        )

    return shortlist[: int(policy["shortlist_size_per_scene"])], rejected


def pair_consistency_score(
    bundle: list[dict[str, Any]], video_context: dict[str, Any]
) -> float:
    """
    Lightweight bundle consistency score.

    Without vision, we use query/title/source/tag metadata. This is only a proxy.
    """
    if not bundle:
        return 0.0
    if len(bundle) == 1:
        return 70.0

    source_set = {item["selected_media"]["source"] for item in bundle}
    query_tokens_list = [
        tokenize(
            " ".join(
                [
                    str(item["selected_media"].get("search_query_used", "")),
                    str(item["selected_media"].get("title", "")),
                    str(item.get("judge_summary", {}).get("why_it_fits", "")),
                ]
            )
        )
        for item in bundle
    ]

    common_tokens = set.intersection(*query_tokens_list) if query_tokens_list else set()
    union_tokens = set.union(*query_tokens_list) if query_tokens_list else set()

    jaccard = len(common_tokens) / len(union_tokens) if union_tokens else 0.0

    consistency_tags = set()
    for tag in safe_list(video_context.get("consistency_tags")):
        consistency_tags |= tokenize(str(tag))

    tag_hits = 0
    for tokens in query_tokens_list:
        if tokens & consistency_tags:
            tag_hits += 1

    score = 50.0
    score += 25.0 * jaccard
    score += 10.0 * (tag_hits / max(len(bundle), 1))

    if len(source_set) == 1:
        score += 10.0
    else:
        score -= 5.0

    return round(clamp(score, 0, 100), 2)


def select_best_scene_bundle(
    scene_shortlists: list[list[dict[str, Any]]],
    video_context: dict[str, Any],
) -> tuple[list[dict[str, Any]], float]:
    """
    Select the best combination of scene candidates.

    This avoids choosing scenes completely independently.
    """
    if not scene_shortlists or any(not s for s in scene_shortlists):
        return [], 0.0

    best_bundle: list[dict[str, Any]] = []
    best_score = -1.0

    for combo in itertools.product(*scene_shortlists):
        media_keys = [item["media_key"] for item in combo]
        if len(media_keys) != len(set(media_keys)):
            continue

        bundle_items = []
        for item in combo:
            bundle_items.append(
                {
                    "selected_media": {
                        key: item.get(key)
                        for key in [
                            "candidate_id",
                            "media_key",
                            "source",
                            "media_id",
                            "title",
                            "page_url",
                            "media_url",
                            "mp4_url",
                            "gif_url",
                            "width",
                            "height",
                            "duration_sec",
                            "search_query_used",
                            "query_round",
                        ]
                    },
                    "score_breakdown": item["score_breakdown"],
                    "judge_summary": item["judge_summary"],
                    "vision_analysis": item.get("vision_analysis"),
                    "vision_score": item.get("vision_score"),
                    "final_score": item.get(
                        "final_score", item["score_breakdown"]["total_score"]
                    ),
                }
            )

        style_conflict = find_visual_style_conflict(video_context, bundle_items)
        if style_conflict.get("has_conflict"):
            continue

        consistency = pair_consistency_score(bundle_items, video_context)
        avg_score = sum(
            item.get("final_score", item["score_breakdown"]["total_score"])
            for item in combo
        ) / len(combo)

        total = avg_score * 0.75 + consistency * 0.25

        if total > best_score:
            best_score = total
            best_bundle = bundle_items

    return best_bundle, round(best_score, 2)

def normalize_visual_style(value: Any) -> str:
    style = (
    normalize_text(str(value or ""))
    .replace("/", "_")
    .replace(" ", "_")
    .replace("-", "_")
)

    aliases = {
        "cartoon": "cartoon_sticker",
        "sticker": "cartoon_sticker",
        "cartoon_sticker": "cartoon_sticker",
        "animation": "cute_animation",
        "animated": "cute_animation",
        "cute_animation": "cute_animation",
        "anime": "anime",
        "realistic": "realistic_human",
        "real_person": "realistic_human",
        "real_people": "realistic_human",
        "live_action": "realistic_human",
        "realistic_human": "realistic_human",
        "real_animal": "realistic_animal",
        "realistic_animal": "realistic_animal",
        "stock": "cinematic_stock",
        "stock_footage": "cinematic_stock",
        "cinematic": "cinematic_stock",
        "cinematic_stock": "cinematic_stock",
        "abstract": "abstract_symbol",
        "symbolic": "abstract_symbol",
        "abstract_symbol": "abstract_symbol",
        "mixed": "mixed",
        "unknown": "unknown",
    }

    return aliases.get(style, "unknown")


def target_prefers_cartoon_style(video_context: dict[str, Any]) -> bool:
    parts = [
        str(video_context.get("visual_world", "")),
        str(video_context.get("visual_family", "")),
        " ".join(map(str, safe_list(video_context.get("preferred_visual_traits")))),
        " ".join(map(str, safe_list(video_context.get("consistency_tags")))),
    ]
    text = normalize_text(" ".join(parts))

    return any(
        key in text
        for key in [
            "pastel",
            "meme",
            "cartoon",
            "sticker",
            "cute",
            "wholesome",
        ]
    )


def get_bundle_visual_styles(selected_bundle: list[dict[str, Any]]) -> list[str]:
    styles: list[str] = []

    for item in selected_bundle:
        analysis = item.get("vision_analysis")
        if isinstance(analysis, dict):
            styles.append(normalize_visual_style(analysis.get("visual_style")))
        else:
            styles.append("unknown")

    return styles


def find_visual_style_conflict(
    video_context: dict[str, Any],
    selected_bundle: list[dict[str, Any]],
) -> dict[str, Any]:
    styles = get_bundle_visual_styles(selected_bundle)

    animation_styles = {"cartoon_sticker", "anime", "cute_animation"}
    incompatible_with_cartoon = {
        "realistic_human",
        "cinematic_stock",
        "abstract_symbol",
    }

    known_styles = [style for style in styles if style != "unknown"]

    if not known_styles:
        return {
            "has_conflict": False,
            "styles": styles,
            "reason": "visual_style_unknown",
        }

    if target_prefers_cartoon_style(video_context):
        has_animation = any(style in animation_styles for style in known_styles)
        has_incompatible = any(
            style in incompatible_with_cartoon for style in known_styles
        )

        if has_animation and has_incompatible:
            return {
                "has_conflict": True,
                "styles": styles,
                "reason": (
                    "mixed_cartoon_with_realistic_or_abstract_style_for_pastel_meme_video"
                ),
            }

    return {
        "has_conflict": False,
        "styles": styles,
        "reason": "style_consistent_enough",
    }
def _extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise RuntimeError("Arc validator: không tìm thấy JSON hợp lệ")

    return json.loads(match.group(0))


def build_arc_validation_prompt(
    video_context: dict[str, Any],
    scene_requests: list[dict[str, Any]],
    selected_bundle: list[dict[str, Any]],
) -> str:
    quote_en = (video_context.get("original_quote") or "").strip()
    quote_vi = (video_context.get("vi_full") or "").strip()
    motif_main = (video_context.get("motif_main") or "").strip()
    lane = (video_context.get("lane") or "").strip()
    mood = (video_context.get("mood") or "").strip()

    scene_plan_lines = []
    for i, req in enumerate(scene_requests, start=1):
        scene_plan_lines.append(
            "\n".join(
                [
                    f"SCENE REQUEST {i}:",
                    f"- scene_role: {req.get('scene_role', '')}",
                    f"- meaning: {req.get('meaning', '')}",
                    f"- semantic_goal: {req.get('semantic_goal', '')}",
                    f"- visual_intent: {req.get('visual_intent', '')}",
                    f"- must_show: {req.get('must_show', [])}",
                ]
            )
        )

    selected_lines = []
    for i, item in enumerate(selected_bundle, start=1):
        media = item.get("selected_media") or {}
        vision = item.get("vision_analysis") or {}
        selected_lines.append(
            "\n".join(
                [
                    f"SELECTED SCENE {i}:",
                    f"- media_key: {media.get('media_key', '')}",
                    f"- search_query_used: {media.get('search_query_used', '')}",
                    f"- title: {media.get('title', '')}",
                    f"- source: {media.get('source', '')}",
                    f"- score_breakdown: {item.get('score_breakdown', {})}",
                    f"- judge_summary: {item.get('judge_summary', {})}",
                    f"- vision_score: {item.get('vision_score')}",
                    f"- final_score: {item.get('final_score')}",
                    f"- subjects: {vision.get('subjects', [])}",
                    f"- action: {vision.get('action', '')}",
                    f"- emotion: {vision.get('emotion', '')}",
                    f"- humor_style: {vision.get('humor_style', '')}",
                    f"- fit_decision: {vision.get('fit_decision', '')}",
                    f"- fit_reason: {vision.get('fit_reason', '')}",
                    f"- risk_flags: {vision.get('risk_flags', [])}",
                ]
            )
        )

    return f"""
Bạn là HUMAN-STYLE GIF DIRECTOR cho video quote ngắn.

NHIỆM VỤ:
Đánh giá bundle GIF như một người thật đang chọn GIF cho quote video ngắn.
Không chỉ kiểm tra logic. Hãy kiểm tra cảm giác xem thật:
- GIF có làm quote dễ hiểu hơn không?
- GIF có làm quote thấm hơn không?
- Scene nào chỉ đúng logic nhưng khô, thừa, hoặc giải thích quá rõ?
- Với quote đối lập đơn giản A vs B, 2 scene có mạnh hơn 3 scene không?
- Nếu bỏ quote text đi, người xem còn cảm được 50-70% ý chính không?

THÔNG TIN QUOTE:
- original_quote_en: {quote_en}
- vi_full: {quote_vi}
- motif_main: {motif_main}
- lane: {lane}
- mood: {mood}

SCENE PLAN MONG MUỐN:
{chr(10).join(scene_plan_lines)}

BUNDLE ĐÃ CHỌN:
{chr(10).join(selected_lines)}

QUY TẮC ĐÁNH GIÁ:
1. ARC phải bám vào ý toàn quote, không chỉ đúng mood chung chung.
2. Nếu từng scene riêng lẻ có vẻ hợp nhưng ghép lại không tạo thành diễn tiến đúng ý quote, thì phải fail.
3. Nếu bundle chỉ tạo cảm giác "cute / funny / sad / happy" chung chung mà không thể hiện logic chính của quote, đánh dấu generic_mood_only = true.
4. Nếu quote mang cấu trúc chuyển biến / tương phản / escalation / payoff mà bundle không thể hiện được điều đó, phải fail.
5. Nếu scene chỉ là biểu tượng giải thích khô như "lightbulb / thinking / rethink / idea" mà không làm quote thấm hơn, hãy đánh dấu scene đó là redundant hoặc hurts.
6. Không ép 3 scene. Ít nhất 2 scene là đủ.
7. Với quote có đối lập đơn giản A vs B, ưu tiên 2 scene mạnh: A rồi B.
8. Chỉ giữ scene thứ 3 nếu nó thêm một beat cảm xúc mới, không phải chỉ là cầu nối logic.
9. Nếu drop một scene mà bundle còn ít nhất 2 scene và cảm xúc mạnh hơn, hãy đề xuất drop scene đó.
10. GIF tốt là GIF làm người xem hiểu/cảm quote nhanh hơn, không chỉ match keyword.

TRẢ VỀ JSON ĐÚNG SCHEMA:
{{
  "arc_fit_score": 0,
  "arc_decision": "pass",
  "human_style_fit_score": 0,
  "recommended_scene_count": 2,
  "recommended_drop_scene_indexes": [],
  "scene_reviews": [
    {{
      "scene_index": 1,
      "necessity": "essential",
      "human_style_fit": 0,
      "keep": true,
      "reason": ""
    }}
  ],
  "story_summary": "",
  "missing_beats": [],
  "generic_mood_only": false,
  "reason": ""
}}

QUY ƯỚC:
- arc_fit_score: 0-100, chấm logic story.
- human_style_fit_score: 0-100, chấm cảm giác giống người thật chọn GIF cho quote video.
- arc_decision: pass | weak_pass | fail
- recommended_scene_count: 2 hoặc 3
- recommended_drop_scene_indexes: list số thứ tự scene trong BUNDLE ĐÃ CHỌN, dùng index bắt đầu từ 1.
- necessity: essential | useful | redundant | hurts
- Nếu không cần drop scene nào, trả [].
- Chỉ trả JSON.
""".strip()


def validate_selected_arc(
    video_context: dict[str, Any],
    scene_requests: list[dict[str, Any]],
    selected_bundle: list[dict[str, Any]],
) -> dict[str, Any]:
    load_dotenv()

    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Arc validator: thiếu GOOGLE_API_KEY")

    model_name = (
        os.getenv("GOOGLE_ARC_MODEL_NAME")
        or os.getenv("GOOGLE_VISION_MODEL_NAME")
        or os.getenv("GOOGLE_MODEL_NAME")
        or "gemma-4-31b-it"
    ).strip()
    max_attempts = env_int("ARC_VALIDATION_RETRIES", 3)
    retry_sleep_sec = env_float("ARC_VALIDATION_RETRY_SLEEP_SEC", 2.0)

    prompt = build_arc_validation_prompt(
        video_context=video_context,
        scene_requests=scene_requests,
        selected_bundle=selected_bundle,
    )

    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )

            raw_text = resp.text or ""
            data = _extract_json_object(raw_text)

            return {
                "arc_fit_score": int(data.get("arc_fit_score", 0) or 0),
                "arc_decision": str(data.get("arc_decision", "fail") or "fail")
                .strip()
                .lower(),
                "human_style_fit_score": int(
                    data.get("human_style_fit_score", data.get("arc_fit_score", 0)) or 0
                ),
                "recommended_scene_count": int(data.get("recommended_scene_count", 0) or 0),
                "recommended_drop_scene_indexes": data.get("recommended_drop_scene_indexes", []) or [],
                "scene_reviews": data.get("scene_reviews", []) or [],
                "story_summary": str(data.get("story_summary", "") or "").strip(),
                "missing_beats": data.get("missing_beats", []) or [],
                "generic_mood_only": bool(data.get("generic_mood_only", False)),
                "reason": str(data.get("reason", "") or "").strip(),
                "_raw_model_text": raw_text,
                "_model_name": model_name,
                "_attempt": attempt,
            }

        except Exception as e:
            last_error = e
            print(f"[ARC WARN] attempt {attempt}/{max_attempts} failed: {e}")

            if is_quota_error(e):
                raise RuntimeError(f"Arc validator quota exhausted: {e}") from e

            if attempt < max_attempts:
                time.sleep(retry_sleep_sec)

    raise RuntimeError(
        f"Arc validator failed after {max_attempts} attempts: {last_error}"
    )


def select_media_bundle(media_selector_input: dict[str, Any]) -> dict[str, Any]:
    """
    New Phase 3 selector.

    It returns a full media selection result but does NOT download media.
    Phase 4 will update main.py to use this function and then call downloader.
    """
    if not isinstance(media_selector_input, dict):
        raise ValueError("media_selector_input must be a dict")

    policy = get_policy(media_selector_input)
    video_context = media_selector_input.get("video_context")
    if not isinstance(video_context, dict):
        video_context = {}

    raw_scene_requests = media_selector_input.get("scene_requests")
    if not isinstance(raw_scene_requests, list) or not raw_scene_requests:
        raise RuntimeError("media_selector_input thiếu scene_requests")

    scene_requests = [
        normalize_scene_request(scene, i)
        for i, scene in enumerate(
            raw_scene_requests[: int(policy["max_scenes"])], start=1
        )
        if isinstance(scene, dict)
    ]

    rejected_candidates_log: list[dict[str, Any]] = []
    scene_shortlists: list[list[dict[str, Any]]] = []

    used_media_keys_in_this_video: set[str] = set()
    used_fallback_source = False

    for scene in scene_requests:
        # GIPHY-first: collect and score GIPHY candidates first.
        giphy_candidates = collect_candidates_for_scene(scene, policy, source="giphy")
        shortlist, rejected = build_scene_shortlist(
            scene,
            giphy_candidates,
            video_context,
            policy,
            exclude_media_keys=used_media_keys_in_this_video,
        )
        rejected_candidates_log.extend(rejected)

        # Only fallback after GIPHY rounds fail to build a shortlist.
        if not shortlist:
            used_fallback_source = True
            pexels_candidates = collect_candidates_for_scene(
                scene, policy, source="pexels"
            )
            shortlist, rejected = build_scene_shortlist(
                scene,
                pexels_candidates,
                video_context,
                policy,
                exclude_media_keys=used_media_keys_in_this_video,
            )
            rejected_candidates_log.extend(rejected)

        # Scene Retry V1:
        # Keep the hard gate strict, but try broader semantic queries before failing the quote.
        if not shortlist and bool(policy.get("use_scene_retry", True)):
            retry_giphy_candidates = collect_scene_retry_candidates(
                scene,
                policy,
                source="giphy",
                query_round_offset=100,
            )
            shortlist, rejected = build_scene_shortlist(
                scene,
                retry_giphy_candidates,
                video_context,
                policy,
                exclude_media_keys=used_media_keys_in_this_video,
            )
            rejected_candidates_log.extend(rejected)

        if not shortlist and bool(policy.get("use_scene_retry", True)):
            used_fallback_source = True
            retry_pexels_candidates = collect_scene_retry_candidates(
                scene,
                policy,
                source="pexels",
                query_round_offset=200,
            )
            shortlist, rejected = build_scene_shortlist(
                scene,
                retry_pexels_candidates,
                video_context,
                policy,
                exclude_media_keys=used_media_keys_in_this_video,
            )
            rejected_candidates_log.extend(rejected)

        scene_shortlists.append(shortlist)

        # We cannot mark final used_media_keys until bundle is selected, but this
        # helps prevent repeated candidates when only one candidate exists.

        failed_scene_ids = [
            scene_requests[i].get("scene_id", i + 1)
            for i, shortlist in enumerate(scene_shortlists)
            if not shortlist
        ]

    dropped_scene_ids: list[Any] = []
    used_scene_drop_fallback = False

    if failed_scene_ids:
        available_pairs = [
            (scene_requests[i], shortlist)
            for i, shortlist in enumerate(scene_shortlists)
            if shortlist
        ]

        can_drop_failed_scenes = (
            bool(policy.get("allow_scene_drop_fallback", True))
            and len(failed_scene_ids) <= int(policy.get("max_dropped_scenes", 1))
            and len(available_pairs) >= int(policy.get("min_scenes_after_drop", 2))
            and len(scene_requests) >= 3
        )

        if can_drop_failed_scenes:
            dropped_scene_ids = list(failed_scene_ids)
            used_scene_drop_fallback = True

            print(
                "[SCENE DROP]",
                f"dropped_scene_ids={dropped_scene_ids}",
                f"remaining_scenes={len(available_pairs)}",
                f"motif={video_context.get('motif_main', '')}",
            )

            scene_requests = [scene for scene, _ in available_pairs]
            scene_shortlists = [shortlist for _, shortlist in available_pairs]
        else:
            return {
                "schema_version": "media_selector_output_v1",
                "video_selection_summary": {
                    "selection_status": "failed",
                    "failure_reason": f"no_eligible_candidate_for_scene_{failed_scene_ids[0]}",
                    "failed_scene_ids": failed_scene_ids,
                    "motif_main": video_context.get("motif_main", ""),
                    "visual_world": video_context.get("visual_world", ""),
                    "consistency_score": 0,
                    "used_fallback_source": used_fallback_source,
                    "used_scene_drop_fallback": False,
                    "notes": "vision_reject_candidates_not_rendered_scene_retry_used",
                },
                "selected_scenes": [],
                "rejected_candidates_log": rejected_candidates_log,
            }

    selected_bundle, bundle_score = select_best_scene_bundle(
        scene_shortlists, video_context
    )

    if not selected_bundle:
        return {
            "schema_version": "media_selector_output_v1",
            "video_selection_summary": {
                "selection_status": "failed",
                "failure_reason": "no_valid_bundle_after_hard_gate",
                "motif_main": video_context.get("motif_main", ""),
                "visual_world": video_context.get("visual_world", ""),
                "consistency_score": 0,
                "used_fallback_source": used_fallback_source,
                "notes": "vision_reject_candidates_not_rendered_scene_retry_used",
            },
            "selected_scenes": [],
            "rejected_candidates_log": rejected_candidates_log,
        }
    style_conflict = find_visual_style_conflict(video_context, selected_bundle)
    if style_conflict.get("has_conflict"):
        print(
            "[STYLE FAIL]",
            f"styles={style_conflict.get('styles')}",
            f"reason={style_conflict.get('reason')}",
            f"motif={video_context.get('motif_main', '')}",
        )

        return {
            "schema_version": "media_selector_output_v1",
            "video_selection_summary": {
                "selection_status": "failed",
                "failure_reason": "visual_style_inconsistent",
                "visual_style_conflict": style_conflict,
                "motif_main": video_context.get("motif_main", ""),
                "visual_world": video_context.get("visual_world", ""),
                "consistency_score": bundle_score,
                "used_fallback_source": used_fallback_source,
                "used_scene_drop_fallback": used_scene_drop_fallback,
                "dropped_scene_ids": dropped_scene_ids,
                "notes": "bundle_rejected_before_arc_due_to_visual_style_mix",
            },
            "selected_scenes": [],
            "rejected_candidates_log": rejected_candidates_log,
        }
    try:
        arc_validation = validate_selected_arc(
            video_context=video_context,
            scene_requests=scene_requests,
            selected_bundle=selected_bundle,
        )

        print(
            "[ARC]",
            f"decision={arc_validation.get('arc_decision')}",
            f"score={arc_validation.get('arc_fit_score')}",
            f"generic_mood_only={arc_validation.get('generic_mood_only')}",
            f"reason={str(arc_validation.get('reason', ''))[:160]}",
        )

    except Exception as e:
        return {
            "schema_version": "media_selector_output_v1",
            "video_selection_summary": {
                "selection_status": "failed",
                "failure_reason": "arc_validator_error",
                "arc_error": str(e),
                "motif_main": video_context.get("motif_main", ""),
                "visual_world": video_context.get("visual_world", ""),
                "consistency_score": bundle_score,
                "used_fallback_source": used_fallback_source,
                "notes": "arc_validation_failed_before_render",
            },
            "selected_scenes": [],
            "rejected_candidates_log": rejected_candidates_log,
        }
    recommended_drop_indexes_raw = arc_validation.get("recommended_drop_scene_indexes") or []
    recommended_drop_indexes: list[int] = []

    for value in recommended_drop_indexes_raw:
        try:
            index_value = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= index_value <= len(selected_bundle):
            recommended_drop_indexes.append(index_value)

    recommended_drop_indexes = sorted(set(recommended_drop_indexes))

    can_director_drop = (
        bool(policy.get("allow_scene_drop_fallback", True))
        and len(recommended_drop_indexes) > 0
        and len(recommended_drop_indexes) <= int(policy.get("max_dropped_scenes", 1))
        and len(selected_bundle) - len(recommended_drop_indexes)
        >= int(policy.get("min_scenes_after_drop", 2))
    )

    if can_director_drop:
        drop_index_set = set(recommended_drop_indexes)
        director_dropped_scene_ids = [
            scene_requests[index - 1].get("scene_id", index)
            for index in recommended_drop_indexes
        ]

        print(
            "[DIRECTOR SCENE DROP]",
            f"drop_indexes={recommended_drop_indexes}",
            f"dropped_scene_ids={director_dropped_scene_ids}",
            f"reason={str(arc_validation.get('reason', ''))[:160]}",
        )

        scene_requests = [
            scene
            for index, scene in enumerate(scene_requests, start=1)
            if index not in drop_index_set
        ]
        scene_shortlists = [
            shortlist
            for index, shortlist in enumerate(scene_shortlists, start=1)
            if index not in drop_index_set
        ]
        selected_bundle = [
            item
            for index, item in enumerate(selected_bundle, start=1)
            if index not in drop_index_set
        ]

        dropped_scene_ids.extend(director_dropped_scene_ids)
        used_scene_drop_fallback = True

        try:
            arc_validation = validate_selected_arc(
                video_context=video_context,
                scene_requests=scene_requests,
                selected_bundle=selected_bundle,
            )

            print(
                "[ARC AFTER DIRECTOR DROP]",
                f"decision={arc_validation.get('arc_decision')}",
                f"score={arc_validation.get('arc_fit_score')}",
                f"human_style={arc_validation.get('human_style_fit_score')}",
                f"generic_mood_only={arc_validation.get('generic_mood_only')}",
                f"reason={str(arc_validation.get('reason', ''))[:160]}",
            )

        except Exception as e:
            return {
                "schema_version": "media_selector_output_v1",
                "video_selection_summary": {
                    "selection_status": "failed",
                    "failure_reason": "arc_validator_error_after_director_drop",
                    "arc_error": str(e),
                    "motif_main": video_context.get("motif_main", ""),
                    "visual_world": video_context.get("visual_world", ""),
                    "consistency_score": bundle_score,
                    "used_fallback_source": used_fallback_source,
                    "used_scene_drop_fallback": used_scene_drop_fallback,
                    "dropped_scene_ids": dropped_scene_ids,
                    "notes": "director_scene_drop_revalidation_failed",
                },
                "selected_scenes": [],
                "rejected_candidates_log": rejected_candidates_log,
            }
    arc_score = int(arc_validation.get("arc_fit_score", 0) or 0)
    human_style_score = int(
        arc_validation.get("human_style_fit_score", arc_score) or arc_score
    )
    arc_decision = (
        str(arc_validation.get("arc_decision", "fail") or "fail").strip().lower()
    )
    generic_mood_only = bool(arc_validation.get("generic_mood_only", False))

    if arc_decision == "fail" or arc_score < 60 or human_style_score < 60 or generic_mood_only:
        return {
            "schema_version": "media_selector_output_v1",
            "video_selection_summary": {
                "selection_status": "failed",
                "failure_reason": "arc_validation_failed",
                "arc_validation": arc_validation,
                "motif_main": video_context.get("motif_main", ""),
                "visual_world": video_context.get("visual_world", ""),
                "consistency_score": bundle_score,
                "used_fallback_source": used_fallback_source,
                "used_scene_drop_fallback": used_scene_drop_fallback,
                "dropped_scene_ids": dropped_scene_ids,
                "notes": "scene_candidates_passed_but_story_arc_failed",
            },
            "selected_scenes": [],
            "rejected_candidates_log": rejected_candidates_log,
        }
    selected_scenes: list[dict[str, Any]] = []
    for index, item in enumerate(selected_bundle, start=1):
        scene_request = scene_requests[index - 1]
        selected_scenes.append(
            {
                "scene_id": scene_request.get("scene_id", index),
                "scene_role": scene_request.get("scene_role", ""),
                "visual_goal": scene_request.get("visual_goal", ""),
                "inferred_scene_role": infer_scene_role_intent(scene_request),
                "selected_media": item["selected_media"],
                "score_breakdown": item["score_breakdown"],
                "judge_summary": item["judge_summary"],
                "vision_analysis": item.get("vision_analysis"),
                "vision_score": item.get("vision_score"),
                "final_score": item.get("final_score"),
                "eligible": item.get("eligible"),
                "ineligible_reason": item.get("ineligible_reason"),
                "shortlist": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "source": candidate["source"],
                        "inferred_scene_role": candidate["score_breakdown"].get(
                            "inferred_scene_role"
                        ),
                        "role_fit": candidate["score_breakdown"].get("role_fit"),
                        "total_score": candidate["score_breakdown"]["total_score"],
                        "final_score": candidate.get("final_score"),
                        "vision_score": candidate.get("vision_score"),
                        "eligible": candidate.get("eligible"),
                        "ineligible_reason": candidate.get("ineligible_reason"),
                        "vision_decision": (
                            candidate.get("vision_analysis", {}).get("fit_decision")
                            if isinstance(candidate.get("vision_analysis"), dict)
                            else None
                        ),
                        "vision_reason": (
                            candidate.get("vision_analysis", {}).get("fit_reason")
                            if isinstance(candidate.get("vision_analysis"), dict)
                            else None
                        ),
                        "search_query_used": candidate.get("search_query_used", ""),
                    }
                    for candidate in scene_shortlists[index - 1]
                ],
            }
        )

    return {
        "schema_version": "media_selector_output_v1",
        "video_selection_summary": {
            "selection_status": "success",
            "motif_main": video_context.get("motif_main", ""),
            "visual_world": video_context.get("visual_world", ""),
            "consistency_score": bundle_score,
            "used_fallback_source": used_fallback_source,
            "used_scene_drop_fallback": used_scene_drop_fallback,
            "dropped_scene_ids": dropped_scene_ids,
            "arc_validation": arc_validation,
            "notes": (
                "metadata_plus_gemma_vision_rerank_with_hard_gate_and_scene_retry"
                if bool(policy.get("use_vision_rerank", False))
                else "metadata_only_judge_with_hard_gate"
            ),
        },
        "selected_scenes": selected_scenes,
        "rejected_candidates_log": rejected_candidates_log,
    }


if __name__ == "__main__":
    sample_queries = [
        "person being kind to a waiter or street cleaner",
        "business people shaking hands smiling",
        "close up hands planting a small sprout in soil",
    ]

    results = []
    for query in sample_queries:
        picked = select_media_for_scene(query)
        results.append(
            {
                "query": query,
                "picked": picked,
            }
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))
