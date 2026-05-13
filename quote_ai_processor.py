from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
import requests
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from quote_fetcher import fetch_all_raw_quotes
from quote_filter import filter_quotes


MODEL_NAME = "gemma-4-31b-it"

ALLOWED_MUSIC_TAGS = {
    "chill", "healing", "motivation", "love", "wisdom",
    "sad", "hopeful", "light-humor",
    # Newer tags understood by music_selector.py V3.
    "reflective", "gentle", "warm", "emotional",
    "joyful", "playful", "upbeat", "funny-light", "cute",
}

LANE_TO_HASHTAG = {
    "motivation": "#motivation",
    "healing": "#healing",
    "love": "#lovequotes",
    "wisdom": "#wisdom",
    "reflection": "#reflection",
    "self-growth": "#growth",
    "self-worth": "#selfworth",
    "discipline": "#discipline",
    "relationships": "#lovequotes",
    "life-lessons": "#wisdom",
    "other": "#wisdom",
}

DEFAULT_PROHIBITED_VISUALS = [
    # Hard rejects for sample-style quote meme videos.
    "large text in gif that contradicts or distracts from the quote",
    "subtitle or caption inside media that contradicts or distracts from the quote",
    "watermark or logo",
    "celebrity interview",
    "talking head",
    "news clip",
    "political clip",
    "vulgar or explicit media",
    "high visual noise",
    "irrelevant cold stock footage",
    "surreal abstract stock footage that does not match the quote",
]

DEFAULT_PREFERRED_VISUAL_TRAITS = [
    "cartoon or sticker style",
    "cute meme energy",
    "simple readable action",
    "small-to-medium subject",
    "clear motion loop",
    "low visual noise",
    "text inside gif is acceptable only when it supports the quote",
    "fits pastel background",
    "strong semantic fit with the quote",
]

ALLOWED_VISUAL_FAMILIES = {
    "cartoon_sticker",
    "cute_animal",
    "light_reaction",
    "simple_meme",
    "real_people_meme",
}

def safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def stable_quote_hash(text: str, author: str = "", source_url: str = "") -> str:
    raw = f"{text.strip().lower()}|{author.strip().lower()}|{source_url.strip().lower()}"
    return "q_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def normalize_author_display(author: Any) -> str:
    text = safe_str(author)
    if not text:
        return "Khuyết danh"
    if text.lower() in {"unknown", "anonymous", "none", "n/a", "không rõ", "khuyết danh"}:
        return "Khuyết danh"
    return text


def normalize_author_confidence(value: Any) -> str:
    text = safe_str(value).lower()
    return text if text in {"high", "medium", "low"} else "medium"


def normalize_lane(raw_lane: str) -> str:
    text = (raw_lane or "").strip().lower()

    if any(k in text for k in ["self-worth", "self worth", "giá trị bản thân"]):
        return "self-worth"
    if any(k in text for k in ["self-growth", "self growth", "growth", "phát triển bản thân", "trưởng thành"]):
        return "self-growth"
    if any(k in text for k in ["discipline", "kỷ luật"]):
        return "discipline"
    if any(k in text for k in ["motivation", "động lực", "success", "thành công"]):
        return "motivation"
    if any(k in text for k in ["healing", "chữa lành", "cô đơn", "loneliness", "hopeful", "hope"]):
        return "healing"
    if any(k in text for k in ["love", "romance", "heartbreak", "tình yêu"]):
        return "love"
    if any(k in text for k in ["relationship", "relationships", "mối quan hệ"]):
        return "relationships"
    if any(k in text for k in ["life lesson", "life-lessons", "bài học cuộc sống"]):
        return "life-lessons"
    if any(k in text for k in ["reflection", "reflective", "suy ngẫm", "chiêm nghiệm"]):
        return "reflection"
    if any(k in text for k in ["wisdom", "triết", "triết lý", "philosophy"]):
        return "wisdom"

    return "wisdom"


def normalize_mood(raw_mood: str) -> str:
    text = safe_str(raw_mood).lower().replace("_", "-")
    if text in {
        "chill", "healing", "wisdom", "motivation", "love", "sad",
        "light-humor", "hopeful", "reflective", "gentle", "warm",
        "emotional", "joyful", "playful", "upbeat", "funny-light", "cute",
    }:
        return text

    if any(k in text for k in ["joy", "happy", "dance", "freeing", "vui", "khiêu vũ"]):
        return "joyful"
    if any(k in text for k in ["playful", "cute", "wholesome"]):
        return "playful"
    if any(k in text for k in ["humor", "funny", "comedy", "meme", "hài", "bựa"]):
        return "funny-light"
    if any(k in text for k in ["reflect", "suy ngẫm", "chiêm nghiệm", "thoughtful"]):
        return "reflective"
    if "hope" in text:
        return "hopeful"
    if "sad" in text or "melanchol" in text:
        return "sad"
    if "love" in text:
        return "love"
    if any(k in text for k in ["heal", "soft", "gentle", "warm", "calm"]):
        return "healing"
    if "motiv" in text or "power" in text or "discipline" in text:
        return "motivation"
    if "wisdom" in text or "philosophy" in text:
        return "wisdom"

    return "reflective"


def normalize_music_mood_tag(raw_tag: str) -> str:
    text = safe_str(raw_tag).lower().replace("_", "-")

    # Let music_selector.py V3 resolve these newer mood tags instead of forcing everything into old folders.
    if any(k in text for k in ["joy", "happy", "dance", "freeing", "vui", "khiêu vũ"]):
        return "joyful"
    if any(k in text for k in ["playful", "cute", "wholesome"]):
        return "playful"
    if any(k in text for k in ["humor", "funny", "light-humor", "comedy", "meme", "hài", "bựa"]):
        return "funny-light"
    if any(k in text for k in ["reflective", "reflection", "thoughtful", "chiêm nghiệm", "suy ngẫm"]):
        return "reflective"
    if any(k in text for k in ["emotional", "touching", "bittersweet"]):
        return "emotional"
    if any(k in text for k in ["warm", "gentle", "soft"]):
        return "gentle"
    if any(k in text for k in ["motivation", "power", "uplift", "strong", "determined", "discipline"]):
        return "motivation"
    if any(k in text for k in ["healing", "heal"]):
        return "healing"
    if any(k in text for k in ["love", "romantic", "romance"]):
        return "love"
    if any(k in text for k in ["sad", "melancholy", "melancholic", "lonely"]):
        return "sad"
    if any(k in text for k in ["hope", "hopeful", "sunrise"]):
        return "hopeful"
    if any(k in text for k in ["wisdom", "philosophy"]):
        return "wisdom"
    if any(k in text for k in ["lo-fi", "lofi", "calm", "chill", "ambient", "piano"]):
        return "chill"

    return "chill"


def adjust_music_mood_by_context(
    music_mood_tag: str,
    *,
    text_original: str,
    vi_short: str,
    motif_main: str,
    scene_plan: list[dict[str, Any]] | None = None,
) -> str:
    """
    Deterministic music guard.

    Some quotes are emotionally soft/warm, but the model may label them as sad/healing.
    This guard keeps friendship/reassurance videos from sounding too mournful.
    """
    scene_plan = scene_plan or []

    chunks = [
        safe_str(text_original).lower(),
        safe_str(vi_short).lower(),
        safe_str(motif_main).lower(),
    ]

    for scene in scene_plan:
        if not isinstance(scene, dict):
            continue
        for key in [
            "meaning",
            "visual_goal",
            "semantic_goal",
            "visual_intent",
            "emotion_target",
        ]:
            chunks.append(safe_str(scene.get(key)).lower())

        for key in [
            "must_have_elements",
            "must_show",
            "nice_to_have",
            "queries_giphy",
            "queries_fallback",
            "continuity_tags",
        ]:
            value = scene.get(key)
            if isinstance(value, list):
                chunks.append(" ".join(safe_str(x).lower() for x in value if safe_str(x)))

    text = " ".join(chunks)

    warm_friendship_terms = [
        "friend", "friends", "friendship", "pooh", "piglet",
        "beside", "together", "hug", "comfort", "support",
        "reassurance", "still there", "connection", "warm",
        "gentle", "kindness", "care", "caring",
        "bạn", "tình bạn", "bên cạnh", "đồng hành", "ôm",
        "an tâm", "vỗ về", "ấm áp", "dịu dàng", "kết nối",
    ]

    if any(term in text for term in warm_friendship_terms):
        if music_mood_tag in {"sad", "emotional", "healing", "reflective", "chill"}:
            return "warm"

    learning_growth_terms = [
        "book", "books", "reading", "read", "study", "studying",
        "mind", "brain", "growth", "sharpening", "sharpen", "whetstone",
        "sword", "edge", "lightbulb", "eureka", "smart", "learning",
        "knowledge", "curious", "idea", "realization",
        "sách", "đọc sách", "đọc", "học", "học hỏi", "tâm trí",
        "trí óc", "kiến thức", "mài sắc", "thanh kiếm", "đá mài",
        "ý tưởng", "lóe sáng", "khai sáng",
    ]

    sad_context_terms = [
        "sad", "cry", "crying", "tears", "heartbreak", "lonely",
        "grief", "loss", "melancholy",
        "buồn", "khóc", "nước mắt", "cô đơn", "mất mát", "đau lòng",
    ]

    if any(term in text for term in learning_growth_terms):
        if not any(term in text for term in sad_context_terms):
            if music_mood_tag in {"sad", "emotional", "healing", "reflective", "chill", "wisdom"}:
                return "playful"

    return music_mood_tag

def normalize_dynamic_hashtag(lane: str) -> str:
    return LANE_TO_HASHTAG.get(lane, "#wisdom")


def normalize_scene_priority(raw: Any) -> str:
    text = safe_str(raw).lower()
    if "literal_or_symbolic" in text or ("literal" in text and "symbolic" in text):
        return "literal_or_symbolic"
    if "symbolic" in text:
        return "symbolic"
    return "literal"


def normalize_scene_role(raw: Any, index: int, total: int) -> str:
    text = safe_str(raw).lower()
    if text in {"setup", "contrast", "payoff", "reflection"}:
        return text
    if total == 1:
        return "reflection"
    if index == 0:
        return "setup"
    if index == total - 1:
        return "payoff"
    return "contrast"


def normalize_visual_family(raw: Any, fallback: str = "cartoon_sticker") -> str:
    text = safe_str(raw).lower().replace("-", "_").replace(" ", "_")
    if text in ALLOWED_VISUAL_FAMILIES:
        return text

    if any(k in text for k in ["animal", "pet", "cat", "dog", "duck", "cute"]):
        return "cute_animal"
    if any(k in text for k in ["reaction", "face", "confused", "surprised"]):
        return "light_reaction"
    if any(k in text for k in ["meme", "funny", "humor"]):
        return "simple_meme"
    if any(k in text for k in ["real", "person", "people"]):
        return "real_people_meme"

    return fallback if fallback in ALLOWED_VISUAL_FAMILIES else "cartoon_sticker"


def normalize_query_list(value: Any, fallback_query: str = "") -> list[str]:
    result: list[str] = []
    for item in safe_list(value):
        q = safe_str(item).lower()
        q = re.sub(r"\s+", " ", q).strip()
        if q and q not in result:
            result.append(q)

    if not result and fallback_query:
        result.append(fallback_query)

    # Do not let model search for text overlays. But meme/reaction are allowed now
    # because the reference videos use light meme/cartoon/sticker energy.
    banned = ["quote", "motivation quote", "text", "caption", "subtitle", "lyrics"]
    cleaned = []
    for q in result:
        if not any(b in q for b in banned):
            # Remove cinematic/stock words that caused the old wrong style.
            q = q.replace("cinematic", "").replace("slow motion", "").replace("stock footage", "")
            q = re.sub(r"\s+", " ", q).strip()
            if q:
                cleaned.append(q)

    return (cleaned or result)[:6]


def convert_scene_plan_to_old_scenes(scene_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old_scenes: list[dict[str, Any]] = []

    for index, scene in enumerate(scene_plan, start=1):
        queries = normalize_query_list(scene.get("queries_giphy"))
        old_scenes.append(
            {
                "scene_number": int(scene.get("scene_id") or index),
                "beat_text": safe_str(scene.get("meaning") or scene.get("visual_goal") or ""),
                "visual_mode": normalize_scene_priority(scene.get("priority", "literal")),
                "search_query_en": queries[0] if queries else "",
            }
        )

    return old_scenes



def _scene(
    *,
    scene_id: int,
    scene_role: str,
    meaning: str,
    visual_goal: str,
    visual_family: str,
    priority: str,
    must_have_elements: list[str],
    avoid_elements: list[str],
    queries_giphy: list[str],
    queries_fallback: list[str] | None = None,
    continuity_tags: list[str] | None = None,
    semantic_goal: str | None = None,
    visual_intent: str | None = None,
    must_show: list[str] | None = None,
    nice_to_have: list[str] | None = None,
    emotion_target: str | None = None,
) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "scene_role": scene_role,
        "meaning": meaning,
        "visual_goal": visual_goal,
        "semantic_goal": semantic_goal or meaning,
        "visual_intent": visual_intent or visual_goal,
        "visual_family": normalize_visual_family(visual_family),
        "priority": normalize_scene_priority(priority),
        "must_have_elements": must_have_elements,
        "must_show": must_show or must_have_elements,
        "nice_to_have": nice_to_have or [],
        "avoid_elements": avoid_elements or list(DEFAULT_PROHIBITED_VISUALS),
        "emotion_target": emotion_target or "",
        "queries_giphy": normalize_query_list(queries_giphy),
        "queries_fallback": normalize_query_list(queries_fallback or queries_giphy[:2]),
        "continuity_tags": continuity_tags or [],
    }


def apply_quote_specific_scene_templates(
    *,
    text_original: str,
    vi_short: str,
    motif_main: str,
    visual_world: str,
    scene_plan: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Deterministic planner guard.

    The LLM sometimes produces broadly cute GIF queries that are usable but not
    sharp enough. These templates make abstract quotes produce concrete GIPHY
    beats: tension -> choice/action -> payoff.
    """
    raw = safe_str(text_original).lower()
    vi = safe_str(vi_short).lower()
    combined = f"{raw} {vi}"

    def common_tags(*extra: str) -> list[str]:
        return [tag for tag in [motif_main, visual_world, *extra] if tag]
    # Reading / novel / joy of books:
    # Example:
    # "A person, be it gentleman or lady, who has not pleasure in a good novel,
    #  must be intolerably stupid."
    #
    # Visual logic:
    # 1) establish the good novel / book
    # 2) contrast with someone who does not get it: confused / loading / blank brain
    # 3) clarify the pleasure: cute character happily reading
    if (
        (
            any(k in raw for k in ["novel", "book", "books", "reading", "read"])
            and any(k in raw for k in ["pleasure", "joy", "enjoy", "delight", "happy", "stupid", "fool"])
        )
        or (
            any(k in vi for k in ["tiểu thuyết", "cuốn sách", "đọc sách", "đọc"])
            and any(k in vi for k in ["niềm vui", "vui", "thích thú", "ngốc"])
        )
    ):
        return [
            _scene(
                scene_id=1,
                scene_role="setup",
                meaning="A good novel or book appears as something inviting and interesting.",
                semantic_goal="Establish the object of joy: a good novel or book.",
                visual_goal="A magical or cozy book opening, or a cute book-focused visual.",
                visual_intent="good novel, book, reading invitation, cozy reading mood",
                visual_family="cartoon_sticker",
                priority="literal",
                must_have_elements=["book", "novel", "reading"],
                must_show=["a book or novel is clearly visible"],
                nice_to_have=["magical book", "cozy reading vibe", "book opening"],
                emotion_target="curious, inviting, warm",
                avoid_elements=[
                    "blank book with no clear reading meaning",
                    "dark horror book",
                    "random library with no book focus",
                    "unrelated dancing",
                    "romance unrelated to reading",
                ],
                queries_giphy=[
                    "cute cat reading book",
                    "cartoon reading book happy",
                    "sticker reading book",
                    "magical book opening cartoon",
                    "cute animal reading books",
                    "cozy library cartoon",
                ],
                queries_fallback=[
                    "cute animal reading book",
                    "cartoon reading book",
                    "open book cartoon",
                ],
                continuity_tags=common_tags("reading", "novel", "book", "setup"),
            ),
            _scene(
                scene_id=2,
                scene_role="contrast",
                meaning="Someone who cannot enjoy the good novel looks clueless or mentally blank.",
                semantic_goal="Show the contrast: not understanding or not appreciating the joy of reading.",
                visual_goal="A cute confused character, loading brain, blank stare, or clueless reaction.",
                visual_intent="confusion, blank brain, loading, not understanding",
                visual_family="light_reaction",
                priority="literal_or_symbolic",
                must_have_elements=["confused", "blank brain", "loading"],
                must_show=["clear confused or clueless reaction"],
                nice_to_have=["loading icon", "blank stare", "funny confused cat"],
                emotion_target="confused, clueless, funny",
                avoid_elements=[
                    "happy reading",
                    "smart studying success",
                    "angry argument",
                    "sad heavy drama",
                    "unrelated romance",
                ],
                queries_giphy=[
                    "confused cat meme",
                    "blank stare cartoon",
                    "funny confused face sticker",
                    "brain loading cartoon",
                    "loading cat gif",
                    "confused cartoon thinking",
                ],
                queries_fallback=[
                    "confused reaction",
                    "blank stare",
                    "loading brain",
                ],
                continuity_tags=common_tags("reading", "contrast", "confused", "blank brain"),
            ),
            _scene(
                scene_id=3,
                scene_role="payoff",
                meaning="The joy of a good novel is made clear through a character happily reading.",
                semantic_goal="Clarify the missing beat: reading a good novel should feel joyful.",
                visual_goal="A cute character or animal happily reading, hugging a book, or enjoying a book.",
                visual_intent="happy reading, enjoying book, joy of novel",
                visual_family="cute_animal",
                priority="literal",
                must_have_elements=["happy", "reading", "book"],
                must_show=["character happily reading or enjoying a book"],
                nice_to_have=["hugging book", "smiling while reading", "cozy book joy"],
                emotion_target="happy, delighted, cozy",
                avoid_elements=[
                    "confused face",
                    "sad reading",
                    "angry reading",
                    "book only with no character",
                    "unrelated dancing",
                ],
                queries_giphy=[
                    "cute animal reading book happy",
                    "happy cat reading book",
                    "cute character reading book",
                    "cartoon happy reading",
                    "cute animal hugging book",
                    "cozy reading sticker",
                ],
                queries_fallback=[
                    "happy reading book cartoon",
                    "cute animal reading",
                    "person happy reading book",
                ],
                continuity_tags=common_tags("reading", "payoff", "happy reading", "book joy"),
            ),
        ]
    # Worse / better escalation:
    # Quote pattern:
    # "Just when you think it can't get any worse, it can.
    #  And just when you think it can't get any better, it can."
    # The visual logic must be contrast, not generic shock/happy reaction.
    if (
        (
            ("worse" in raw or "bad" in raw)
            and ("better" in raw or "wonderful" in raw or "great" in raw)
            and ("think" in raw or "can't" in raw or "cannot" in raw or "can" in raw)
        )
        or (
            ("tệ hơn" in vi or "tệ" in vi or "xấu hơn" in vi)
            and ("tuyệt vời hơn" in vi or "tốt hơn" in vi or "đẹp hơn" in vi)
        )
    ):
        return [
            _scene(
                scene_id=1,
                scene_role="contrast",
                meaning="A situation looks bad, then unexpectedly gets even worse.",
                semantic_goal="Show worse-than-expected escalation: a small problem turns into a bigger problem.",
                visual_goal="A clear chain reaction of bad luck or a cute character facing a pile-up of problems.",
                visual_intent="bad luck escalation, things going wrong, one problem becoming worse",
                visual_family="simple_meme",
                priority="literal_or_symbolic",
                must_have_elements=["bad luck", "worse", "problem", "escalation"],
                must_show=["problem gets worse", "clear negative escalation", "chain reaction or pile up"],
                nice_to_have=["cartoon disaster", "cute character reacting to escalating trouble"],
                emotion_target="surprised, overwhelmed, oh no",
                avoid_elements=[
                    "generic shocked face only",
                    "happy dance",
                    "random cute animal with no problem",
                    "celebration",
                    "romance",
                ],
                queries_giphy=[
                    "cartoon bad luck chain reaction",
                    "everything going wrong cartoon",
                    "cute character disaster pile up",
                    "problem gets worse cartoon",
                    "oh no everything is going wrong",
                    "cartoon fail chain reaction",
                ],
                queries_fallback=[
                    "bad luck chain reaction",
                    "things going wrong",
                    "disaster pile up cartoon",
                ],
                continuity_tags=common_tags("contrast", "worse", "bad luck", "escalation"),
            ),
            _scene(
                scene_id=2,
                scene_role="payoff",
                meaning="A situation looks already good, then unexpectedly gets even better.",
                semantic_goal="Show better-than-expected escalation: something good becomes even better or surprisingly possible.",
                visual_goal="A clear positive upgrade, breakthrough, surprise good news, rocket launch, invention, or celebration of something becoming possible.",
                visual_intent="positive escalation, breakthrough, impossible becomes possible, good news gets better",
                visual_family="cartoon_sticker",
                priority="literal_or_symbolic",
                must_have_elements=["better", "breakthrough", "surprise", "possible"],
                must_show=["positive escalation", "clear achievement or breakthrough", "things become even better"],
                nice_to_have=["rocket launch", "invention", "surprise celebration", "wow moment"],
                emotion_target="wonder, delighted surprise, uplifting",
                avoid_elements=[
                    "generic happy dance only",
                    "random cute animal with no achievement",
                    "sadness",
                    "stuck",
                    "bad luck",
                ],
                queries_giphy=[
                    "rocket launch celebration cartoon",
                    "breakthrough success cartoon",
                    "surprise good news cartoon",
                    "things get even better cartoon",
                    "impossible becomes possible cartoon",
                    "cute character amazed celebration",
                    "invention success cartoon",
                ],
                queries_fallback=[
                    "rocket launch",
                    "breakthrough success",
                    "surprise good news",
                ],
                continuity_tags=common_tags("contrast", "better", "breakthrough", "possible"),
            ),
        ]

    # Mark Twain-ish: truth / lie / memory.
    if (
        ("truth" in raw and ("remember" in raw or "anything" in raw))
        or ("nói thật" in vi and ("nhớ" in vi or "ghi nhớ" in vi))
        or ("lie" in raw and "remember" in raw)
    ):
        return [
            _scene(
                scene_id=1,
                scene_role="setup",
                meaning="Lying or not being honest creates mental load: you have to remember what you said.",
                visual_goal="A confused character or animal trying hard to remember something.",
                visual_family="light_reaction",
                priority="literal_or_symbolic",
                must_have_elements=["confused", "remember", "thinking"],
                avoid_elements=["random dancing", "unrelated celebration", "romance"],
                queries_giphy=[
                    "confused monkey trying to remember",
                    "brain loading cartoon",
                    "stressed cat thinking",
                    "confused cartoon thinking",
                ],
                queries_fallback=["confused person thinking", "person trying to remember"],
                continuity_tags=common_tags("confused", "memory", "thinking"),
            ),
            _scene(
                scene_id=2,
                scene_role="contrast",
                meaning="Telling the truth is simple and clean.",
                visual_goal="A character honestly speaking or showing truth in a simple funny way.",
                visual_family="simple_meme",
                priority="literal_or_symbolic",
                must_have_elements=["truth", "honest", "speaking"],
                avoid_elements=["lying celebration", "random dance", "unrelated love"],
                queries_giphy=[
                    "honest cartoon speaking truth",
                    "cartoon telling truth",
                    "pinocchio nose funny truth",
                    "truth bomb cartoon",
                ],
                queries_fallback=["person telling truth", "honest speaking"],
                continuity_tags=common_tags("truth", "honest", "speaking"),
            ),
            _scene(
                scene_id=3,
                scene_role="payoff",
                meaning="Because the truth is simple, you feel relieved and do not need to remember anything.",
                visual_goal="A relieved or carefree character after pressure is gone.",
                visual_family="cartoon_sticker",
                priority="symbolic",
                must_have_elements=["relieved", "free", "carefree"],
                avoid_elements=["sadness", "anger", "stress"],
                queries_giphy=[
                    "relieved cartoon character",
                    "happy free dance cartoon",
                    "cute animal relaxed relief",
                    "stress gone cartoon",
                ],
                queries_fallback=["relieved person", "carefree happy"],
                continuity_tags=common_tags("relief", "carefree", "free"),
            ),
        ]

    # Robert Frost-ish: life goes on.
    if (
        ("life" in raw and "goes on" in raw)
        or ("đời" in vi and ("tiếp diễn" in vi or "vẫn cứ" in vi))
        or ("cuộc đời" in vi and "tiếp diễn" in vi)
    ):
        return [
            _scene(
                scene_id=1,
                scene_role="setup",
                meaning="A person or character is stuck, surprised, or dealing with a hard moment.",
                visual_goal="A cute character briefly stuck or confused.",
                visual_family="light_reaction",
                priority="symbolic",
                must_have_elements=["stuck", "confused", "moment"],
                avoid_elements=["random motivation", "unrelated dance"],
                queries_giphy=[
                    "confused cartoon pause",
                    "cute animal stuck",
                    "cartoon surprised face",
                ],
                queries_fallback=["person paused thinking", "confused person"],
                continuity_tags=common_tags("pause", "life", "moment"),
            ),
            _scene(
                scene_id=2,
                scene_role="contrast",
                meaning="Life continues moving forward.",
                visual_goal="A simple visual of flow or time passing.",
                visual_family="cartoon_sticker",
                priority="literal_or_symbolic",
                must_have_elements=["moving", "flow", "time"],
                avoid_elements=["intense motivation", "workout", "party"],
                queries_giphy=[
                    "leaf floating on water cartoon",
                    "river flowing cartoon",
                    "clouds passing cartoon",
                    "clock ticking cartoon",
                ],
                queries_fallback=["river flowing", "clouds passing"],
                continuity_tags=common_tags("flow", "time", "continue"),
            ),
            _scene(
                scene_id=3,
                scene_role="payoff",
                meaning="Acceptance: life still goes on, calmly.",
                visual_goal="A calm cute character accepting and moving on.",
                visual_family="cute_animal",
                priority="symbolic",
                must_have_elements=["calm", "acceptance", "moving on"],
                avoid_elements=["panic", "chaos", "angry"],
                queries_giphy=[
                    "calm cute animal floating",
                    "cartoon character moving on",
                    "peaceful cartoon smiling",
                    "cute animal relaxing",
                ],
                queries_fallback=["calm person walking", "peaceful smile"],
                continuity_tags=common_tags("calm", "acceptance", "moving on"),
            ),
        ]

    # Be yourself / self-expression / don't mind critics.
    if (
        "be who you are" in raw
        or "be yourself" in raw
        or ("chính mình" in vi and ("bận tâm" in vi or "cảm thấy" in vi))
        or ("nói ra" in vi and "cảm thấy" in vi)
    ):
        return [
            _scene(
                scene_id=1,
                scene_role="setup",
                meaning="Trying to fit in or worrying about judgment feels awkward.",
                visual_goal="A cute awkward character trying to fit in or looking unsure.",
                visual_family="simple_meme",
                priority="symbolic",
                must_have_elements=["awkward", "fit in", "unsure"],
                avoid_elements=["sad heavy drama", "romance"],
                queries_giphy=[
                    "awkward penguin walk",
                    "cat trying to fit in box",
                    "confused cartoon face",
                    "nervous cute animal",
                ],
                queries_fallback=["awkward person", "trying to fit in"],
                continuity_tags=common_tags("awkward", "fit in", "judgment"),
            ),
            _scene(
                scene_id=2,
                scene_role="contrast",
                meaning="Being yourself means expressing what you feel freely.",
                visual_goal="A character confidently expressing itself or dancing freely.",
                visual_family="cartoon_sticker",
                priority="symbolic",
                must_have_elements=["self expression", "happy movement", "confidence"],
                avoid_elements=["crowd pressure", "sadness"],
                queries_giphy=[
                    "cute animal dancing",
                    "happy cat groove",
                    "proud cartoon dance",
                    "cute sticker confidence",
                ],
                queries_fallback=["person dancing freely", "confident smile"],
                continuity_tags=common_tags("self expression", "confidence", "happy"),
            ),
            _scene(
                scene_id=3,
                scene_role="payoff",
                meaning="The right people accept you; the wrong opinions do not matter.",
                visual_goal="A carefree shrug or warm acceptance from friends.",
                visual_family="light_reaction",
                priority="literal_or_symbolic",
                must_have_elements=["shrug", "acceptance", "carefree"],
                avoid_elements=["fighting", "angry crowd"],
                queries_giphy=[
                    "cute animal shrug",
                    "funny shrug meme",
                    "friends hug cartoon",
                    "accepted by friends cartoon",
                ],
                queries_fallback=["shrug reaction", "friends accepting"],
                continuity_tags=common_tags("acceptance", "carefree", "friends"),
            ),
        ]

    # Friendship / walking beside me.
    if (
        ("friend" in raw and ("walk" in raw or "beside" in raw))
        or ("bạn" in vi and ("bên cạnh" in vi or "đồng hành" in vi))
    ):
        return [
            _scene(
                scene_id=1,
                scene_role="setup",
                meaning="True friendship is not about leading or following.",
                visual_goal="Two characters not ahead/behind, preparing to walk together.",
                visual_family="cartoon_sticker",
                priority="literal_or_symbolic",
                must_have_elements=["two friends", "side by side", "together"],
                avoid_elements=["lonely walking", "competition"],
                queries_giphy=[
                    "two buddies walking side by side",
                    "cartoon friends walking together",
                    "cute animal friends walking",
                ],
                queries_fallback=["friends walking together", "two people walking"],
                continuity_tags=common_tags("friends", "side by side", "together"),
            ),
            _scene(
                scene_id=2,
                scene_role="payoff",
                meaning="A friend stays beside you.",
                visual_goal="A warm friendship gesture: hug, high five, or walking together.",
                visual_family="cute_animal",
                priority="literal_or_symbolic",
                must_have_elements=["friendship", "hug", "together"],
                avoid_elements=["romance", "sad goodbye"],
                queries_giphy=[
                    "cute animal friends hug",
                    "two cats high five",
                    "friends hug cartoon",
                    "best friends cartoon dance",
                ],
                queries_fallback=["friends hugging", "high five friends"],
                continuity_tags=common_tags("friendship", "hug", "together"),
            ),
        ]

    # Kindness / treatment of weaker people.
    if (
        ("kind" in raw and ("weak" in raw or "weaker" in raw or "treat" in raw))
        or ("tử tế" in vi and ("yếu thế" in vi or "đối xử" in vi))
    ):
        return [
            _scene(
                scene_id=1,
                scene_role="setup",
                meaning="A small or weaker character needs kindness.",
                visual_goal="A small cute character needing help or comfort.",
                visual_family="cute_animal",
                priority="literal_or_symbolic",
                must_have_elements=["small", "help", "kindness"],
                avoid_elements=["mocking", "bullying"],
                queries_giphy=[
                    "small animal needs help",
                    "cute animal comfort friend",
                    "cartoon helping friend",
                ],
                queries_fallback=["helping someone", "comforting friend"],
                continuity_tags=common_tags("kindness", "help", "comfort"),
            ),
            _scene(
                scene_id=2,
                scene_role="payoff",
                meaning="The real character of a person shows in how they treat others.",
                visual_goal="A warm moment of helping, hugging, or caring.",
                visual_family="cartoon_sticker",
                priority="literal_or_symbolic",
                must_have_elements=["helping", "hug", "care"],
                avoid_elements=["cruel", "angry"],
                queries_giphy=[
                    "cartoon helping friend",
                    "cute friends hug",
                    "cat comfort friend",
                    "wholesome helping cartoon",
                ],
                queries_fallback=["people helping", "kindness hug"],
                continuity_tags=common_tags("kindness", "care", "warm"),
            ),
        ]

    return scene_plan


def build_default_scene_plan(
    vi_short: str,
    motif_main: str,
    visual_world: str,
    old_scenes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    old_scenes = old_scenes or [
        {
            "scene_number": 1,
            "beat_text": vi_short,
            "visual_mode": "symbolic",
            "search_query_en": "cute cartoon thinking sticker",
        },
        {
            "scene_number": 2,
            "beat_text": vi_short,
            "visual_mode": "symbolic",
            "search_query_en": "cute cartoon friendship sticker",
        },
    ]

    total = min(max(len(old_scenes), 1), 3)
    scene_plan: list[dict[str, Any]] = []

    for i, old in enumerate(old_scenes[:total]):
        query = safe_str(old.get("search_query_en") or "cute cartoon thinking sticker")
        scene_plan.append(
            {
                "scene_id": int(old.get("scene_number") or i + 1),
                "scene_role": normalize_scene_role("", i, total),
                "meaning": safe_str(old.get("beat_text") or vi_short),
                "visual_goal": safe_str(old.get("beat_text") or f"Visualize: {motif_main}"),
                "priority": normalize_scene_priority(old.get("visual_mode", "symbolic")),
                "must_have_elements": [motif_main] if motif_main else [],
                "avoid_elements": list(DEFAULT_PROHIBITED_VISUALS),
                "queries_giphy": normalize_query_list([query], fallback_query=query),
                "queries_fallback": normalize_query_list([query], fallback_query=query),
                "visual_family": "cartoon_sticker",
                "continuity_tags": [tag for tag in [motif_main, visual_world, "cartoon_sticker"] if tag],
            }
        )

    return scene_plan


def normalize_quote_plan(data: dict[str, Any], *, original_quote: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Normalize AI output into quote_plan_v1 and keep old flat fields for compatibility.

    Accepts either:
    - new nested schema quote_plan_v1, or
    - old flat schema from the earlier prompt.
    """
    original_quote = original_quote or {}

    quote_source = data.get("quote_source") if isinstance(data.get("quote_source"), dict) else {}

    text_original = safe_str(
        quote_source.get("text_original")
        or original_quote.get("text")
        or data.get("text_original")
        or ""
    )
    author_raw = safe_str(
        quote_source.get("author_raw")
        or original_quote.get("author")
        or data.get("author")
        or data.get("_author")
        or ""
    )
    author_display = normalize_author_display(quote_source.get("author_display") or author_raw)
    source_name = safe_str(quote_source.get("source_name") or original_quote.get("source_name") or data.get("source_name") or "Unknown")
    source_url = safe_str(quote_source.get("source_url") or original_quote.get("source_url") or data.get("source_url") or "")
    quote_id_hash = safe_str(quote_source.get("quote_id_hash") or data.get("quote_id_hash") or stable_quote_hash(text_original, author_display, source_url))

    text_output = data.get("text_output") if isinstance(data.get("text_output"), dict) else {}
    vi_full = safe_str(text_output.get("vi_full") or data.get("vi_full") or text_original)
    vi_short = safe_str(text_output.get("vi_short") or data.get("vi_short") or vi_full)

    # Guard against over-compression:
    # For this project, the video quote should stay close to the original meaning.
    # If vi_short is much shorter than vi_full while vi_full is still displayable,
    # use vi_full instead. This prevents outputs like:
    # "Đời đơn giản là: cứ thế trôi." for
    # "In three words I can sum up everything I've learned about life: it goes on."
    if vi_full and vi_short:
        full_len = len(vi_full)
        short_len = len(vi_short)
        if full_len <= 170 and short_len < full_len * 0.72:
            vi_short = vi_full

    caption = safe_str(text_output.get("caption") or data.get("caption") or "")

    classification = data.get("classification") if isinstance(data.get("classification"), dict) else {}
    lane = normalize_lane(classification.get("lane") or data.get("lane") or "")
    mood = normalize_mood(classification.get("mood") or data.get("mood") or "")
    music_mood_tag = normalize_music_mood_tag(classification.get("music_mood_tag") or data.get("music_mood_tag") or mood)
    literal_possible = bool(classification.get("literal_possible", data.get("literal_possible", True)))

    dynamic_hashtag = safe_str(text_output.get("dynamic_hashtag") or data.get("dynamic_hashtag") or normalize_dynamic_hashtag(lane))
    if not dynamic_hashtag.startswith("#"):
        dynamic_hashtag = "#" + dynamic_hashtag

    visual_plan = data.get("visual_plan") if isinstance(data.get("visual_plan"), dict) else {}
    core_meaning = safe_str(visual_plan.get("core_meaning") or data.get("core_meaning") or vi_short)
    motif_main = safe_str(visual_plan.get("motif_main") or data.get("motif_main") or "main visual motif of the quote")
    visual_world = safe_str(visual_plan.get("visual_world") or data.get("visual_world") or "pastel cartoon sticker meme visual world")
    narrative_shape = safe_str(visual_plan.get("narrative_shape") or data.get("narrative_shape") or "reflection")
    if narrative_shape not in {"contrast", "build", "reveal", "reflection"}:
        narrative_shape = "reflection"

    visual_family = normalize_visual_family(
        visual_plan.get("visual_family") or data.get("visual_family") or "cartoon_sticker"
    )

    preferred_visual_traits = [
        safe_str(x) for x in safe_list(visual_plan.get("preferred_visual_traits")) if safe_str(x)
    ] or list(DEFAULT_PREFERRED_VISUAL_TRAITS)

    prohibited_visuals = [
        safe_str(x) for x in safe_list(visual_plan.get("prohibited_visuals")) if safe_str(x)
    ] or list(DEFAULT_PROHIBITED_VISUALS)

    consistency_tags = [
        safe_str(x) for x in safe_list(visual_plan.get("consistency_tags")) if safe_str(x)
    ] or [tag for tag in [lane, music_mood_tag, motif_main] if tag][:5]

    raw_scene_plan = data.get("scene_plan") if isinstance(data.get("scene_plan"), list) else None
    old_scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else []
    scene_source = raw_scene_plan or build_default_scene_plan(vi_short, motif_main, visual_world, old_scenes)

    scene_count = min(max(len(scene_source), 1), 3)
    scene_plan: list[dict[str, Any]] = []

    for i, scene_raw in enumerate(scene_source[:scene_count]):
        if not isinstance(scene_raw, dict):
            scene_raw = {}

        old_query = ""
        if i < len(old_scenes) and isinstance(old_scenes[i], dict):
            old_query = safe_str(old_scenes[i].get("search_query_en"))

        queries_giphy = normalize_query_list(
            scene_raw.get("queries_giphy"),
            fallback_query=old_query or safe_str(scene_raw.get("search_query_en")),
        )
        if not queries_giphy:
            queries_giphy = normalize_query_list([f"{motif_main} {visual_world}"], "quiet cinematic emotional scene")

        scene_plan.append(
            {
                "scene_id": int(scene_raw.get("scene_id") or scene_raw.get("scene_number") or i + 1),
                "scene_role": normalize_scene_role(scene_raw.get("scene_role", ""), i, scene_count),
                "meaning": safe_str(scene_raw.get("meaning") or scene_raw.get("beat_text") or vi_short),
                "visual_goal": safe_str(scene_raw.get("visual_goal") or scene_raw.get("meaning") or f"Visualize: {motif_main}"),
                "semantic_goal": safe_str(scene_raw.get("semantic_goal") or scene_raw.get("meaning") or scene_raw.get("beat_text") or vi_short),
                "visual_intent": safe_str(scene_raw.get("visual_intent") or scene_raw.get("visual_goal") or scene_raw.get("meaning") or f"Visualize: {motif_main}"),
                "priority": normalize_scene_priority(scene_raw.get("priority") or scene_raw.get("visual_mode") or "literal"),
                "must_have_elements": [safe_str(x) for x in safe_list(scene_raw.get("must_have_elements")) if safe_str(x)],
                "must_show": [
                    safe_str(x)
                    for x in safe_list(scene_raw.get("must_show") or scene_raw.get("must_have_elements"))
                    if safe_str(x)
                ],
                "nice_to_have": [safe_str(x) for x in safe_list(scene_raw.get("nice_to_have")) if safe_str(x)],
                "avoid_elements": [safe_str(x) for x in safe_list(scene_raw.get("avoid_elements") or scene_raw.get("avoid")) if safe_str(x)] or list(DEFAULT_PROHIBITED_VISUALS),
                "emotion_target": safe_str(scene_raw.get("emotion_target") or ""),
                "queries_giphy": queries_giphy,
                "queries_fallback": normalize_query_list(scene_raw.get("queries_fallback"), fallback_query=queries_giphy[0]),
                "visual_family": normalize_visual_family(scene_raw.get("visual_family"), visual_family),
                "continuity_tags": [safe_str(x) for x in safe_list(scene_raw.get("continuity_tags")) if safe_str(x)] or (consistency_tags + [visual_family])[:4],
            }
        )

    scene_plan = apply_quote_specific_scene_templates(
        text_original=text_original,
        vi_short=vi_short,
        motif_main=motif_main,
        visual_world=visual_world,
        scene_plan=scene_plan,
    )

    music_mood_tag = adjust_music_mood_by_context(
        music_mood_tag,
        text_original=text_original,
        vi_short=vi_short,
        motif_main=motif_main,
        scene_plan=scene_plan,
    )

    mood = normalize_mood(music_mood_tag)

    normalized = {
        "schema_version": "quote_plan_v1",
        "quote_source": {
            "quote_id_hash": quote_id_hash,
            "text_original": text_original,
            "author_raw": author_raw,
            "author_display": author_display,
            "source_name": source_name,
            "source_url": source_url,
            "author_confidence": normalize_author_confidence(quote_source.get("author_confidence")),
        },
        "text_output": {
            "vi_full": vi_full,
            "vi_short": vi_short,
            "caption": caption,
            "fixed_hashtag": "#trichdanmoingay",
            "dynamic_hashtag": dynamic_hashtag,
        },
        "classification": {
            "lane": lane,
            "mood": mood,
            "music_mood_tag": music_mood_tag,
            "literal_possible": literal_possible,
        },
        "visual_plan": {
            "core_meaning": core_meaning,
            "motif_main": motif_main,
            "visual_world": visual_world,
            "visual_family": visual_family,
            "narrative_shape": narrative_shape,
            "scene_count": len(scene_plan),
            "prohibited_visuals": prohibited_visuals,
            "preferred_visual_traits": preferred_visual_traits,
            "consistency_tags": consistency_tags,
        },
        "scene_plan": scene_plan,

        # Backward-compatible flat fields used by current main/timeline/media code.
        "vi_full": vi_full,
        "vi_short": vi_short,
        "caption": caption,
        "lane": lane,
        "mood": mood,
        "dynamic_hashtag": dynamic_hashtag,
        "music_mood_tag": music_mood_tag,
        "scenes": convert_scene_plan_to_old_scenes(scene_plan),
        "_author": author_display,
    }

    return normalized


def normalize_output(data: dict[str, Any], original_quote: dict[str, str] | None = None) -> dict[str, Any]:
    return normalize_quote_plan(data, original_quote=original_quote)


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise RuntimeError("Không tìm thấy JSON hợp lệ trong output của model")

    return json.loads(match.group(0))


def build_prompt(quote_text: str, author: str, source_name: str, source_url: str) -> str:
    return f"""
Bạn là biên tập viên nội dung kiêm đạo diễn GIF cho kênh video ngắn "Trích dẫn mỗi ngày".

INPUT:
- text: {quote_text}
- author: {author}
- source_name: {source_name}
- source_url: {source_url}

MỤC TIÊU THẬT:
Tạo plan cho video quote meme 9:16, khoảng 14 giây, giống các clip mẫu:
- nền pastel trơn
- quote tiếng Việt chữ đen đậm, hiện dần trong 3–5 giây đầu rồi giữ nguyên
- tác giả nằm dưới quote
- GIF/meme/sticker nhỏ-vừa nằm dưới text
- đổi GIF vài lần để giữ nhịp
- vibe tối giản, cute, meme nhẹ, dễ xem, không cinematic stock footage

ĐÂY KHÔNG PHẢI:
- video điện ảnh
- quote trên nền stock footage
- visual story nghiêm túc
- cảnh người đi bộ slow motion cinematic
- ảnh siêu thực / vũ trụ / city stock nếu quote không cần

RULE VIỆT HÓA — RẤT QUAN TRỌNG:
- Ưu tiên trung thành với ý gốc hơn là rút ngắn cho đẹp.
- Không được biến quote thành slogan mới nếu làm mất cấu trúc/tinh thần câu gốc.
- Không được bỏ các mệnh đề quan trọng của quote gốc.
- Việt hóa tự nhiên, nhưng vẫn phải đọc ra được câu gốc đang nói gì.
- vi_full = bản dịch đầy đủ, gần nghĩa gốc, tự nhiên bằng tiếng Việt.
- vi_short = mặc định nên gần giống vi_full; chỉ rút gọn nhẹ nếu vi_full quá dài để lên video.
- Nếu quote gốc ngắn/vừa, vi_short được phép bằng vi_full.
- Nếu phải rút gọn, chỉ bỏ phần phụ ít quan trọng; không được đổi ý chính.
- caption là một câu riêng, hoàn chỉnh, không lặp lại quote.
- dynamic_hashtag chỉ được đúng 1 hashtag.

VÍ DỤ DỊCH ĐÚNG HƯỚNG:
Original:
"In three words I can sum up everything I've learned about life: it goes on."
Dịch tốt:
"Tất cả những gì tôi học được về cuộc đời có thể gói lại trong ba chữ: đời vẫn tiếp diễn."
Dịch quá rút gọn / lệch sắc thái:
"Đời đơn giản là: cứ thế trôi."
Vì câu này làm mất cấu trúc "everything I've learned about life" và làm lệch "it goes on" thành cảm giác buông trôi.

RULE MOOD & MUSIC:
- Nếu quote chiêm nghiệm/sâu/hoài niệm: mood/music_mood_tag = reflective, wisdom, gentle, emotional hoặc healing.
- Nếu quote vui/giải phóng/khiêu vũ/sống hết mình: mood/music_mood_tag = joyful, playful hoặc upbeat.
- Nếu quote hài nhẹ/châm biếm: mood/music_mood_tag = funny-light hoặc light-humor.
- Không gán music_mood_tag quá chung chung nếu quote có cảm xúc rõ.

RULE SCENE PLANNING — CỰC KỲ QUAN TRỌNG:

Mục tiêu không phải là tìm GIF cute nhất.
Mục tiêu là chọn GIF diễn đúng beat ý nghĩa của quote.

Mỗi scene phải là một VISUAL BEAT nhìn thấy được:
- scene 1 = tình huống / tension / vấn đề
- scene 2 = lựa chọn / chuyển biến / đối lập
- scene 3 = payoff / nhẹ nhõm / kết luận cảm xúc

Nguyên tắc ưu tiên:
1. Đúng hành động / beat chính
2. Đúng cảm xúc
3. Đúng arc giữa các scene
4. Đúng style cute/cartoon/pastel
5. Đúng con vật/đạo cụ cụ thể

KHÔNG ĐƯỢC khóa scene quá cụ thể nếu không cần thiết.
Ví dụ không nên bắt buộc:
- đúng mèo và chó cùng nhìn nhau
- đúng cây mọc từ trang sách
- đúng nhân vật đứng trước núi và cúp vàng
- đúng thought bubble với chi tiết cụ thể
- đúng một object quá hiếm trên GIPHY

Nếu quote không bắt buộc con vật/đạo cụ đó, hãy để con vật/đạo cụ là nice_to_have, không phải must_have.

must_have_elements / must_show chỉ nên chứa:
- hành động chính
- cảm xúc chính
- beat ý nghĩa bắt buộc

nice_to_have mới chứa:
- cat, dog, bunny, bear
- pastel
- specific object
- exact setting

Ví dụ:
Sai:
must_have = ["cat", "dog", "pastel", "sitting together", "thinking about happiness"]

Đúng:
must_have = ["two characters", "friendship", "warm connection"]
nice_to_have = ["cat", "dog", "pastel", "sitting together"]

Với quote trừu tượng, hãy đổi thành hành vi cụ thể dễ tìm trên GIPHY:
- truth / secret / honesty → shh, keeping mouth closed, suspicious face, refusing to speak
- growth / change → small step forward, trying hard, watering plant, improving
- past / yesterday → looking back, calendar, walking away, moving forward
- friendship / support → hug, walking together, helping friend, sitting together
- learning / books → reading book, confused about book, happy reading, lightbulb idea
- effort / success → trying hard, working, tired effort, small celebration
- fear / doubt → nervous face, hiding, hesitant step, then step forward
- regret / awkwardness → facepalm, awkward smile, freezing, embarrassed reaction
- kindness → helping friend, sharing, comforting, gentle hug

Query GIPHY phải là hành động dễ search:
Tốt:
- "cartoon friends thinking"
- "cute friends sitting together"
- "cartoon character shh"
- "confused cat thinking"
- "cute animal facepalm"
- "small character walking forward"
- "friends hug cartoon"
- "cute animal trying hard"

Tệ:
- "deep wisdom"
- "happiness meaning"
- "magic sparkles"
- "beautiful soul"
- "truth energy"
- "cat and dog thinking about each other's happiness in pastel background"

Luật quan trọng:
- GIF phải giúp người xem hiểu quote hơn, kể cả khi chưa đọc hết chữ.
- Được dùng GIF có chữ nếu chữ hỗ trợ đúng beat.
- Chỉ tránh chữ trong GIF nếu nó mâu thuẫn quote, gây nhiễu nghĩa, watermark/logo, hoặc làm người xem hiểu sai.
- Đừng reject ý tưởng chỉ vì không đúng con vật. Reject nếu sai hành động hoặc sai cảm xúc.
- Quote sâu → scene đơn giản, rõ hành động.
- Mood chỉ là phụ; story beat mới là chính.
RULE CENTRAL IMAGE — RẤT QUAN TRỌNG:

Mỗi quote phải có central_tension và central_symbol.

central_tension = xung đột/chuyển động chính của quote.
central_symbol = hình ảnh đơn giản giúp người xem nhận ra chủ đề quote.

queries_giphy không được chỉ là mood/action chung.
Mỗi query tốt nên có:
[subject đơn giản] + [visible action] + [central symbol nếu có]

Ví dụ:
- greatness / greatness fear / greatness achieved
  central_tension: small/afraid → brave/proud
  central_symbol: stage, crown, trophy, medal, spotlight, big dream
  query tốt: "small character big dream", "cartoon character scared stage", "cute animal trophy proud", "cartoon crown proud"

- truth / secret / honesty
  central_tension: muốn nói → giữ lại / chọn im lặng
  central_symbol: shh, mouth closed, secret, suspicious face
  query tốt: "cartoon shh secret", "cute animal mouth closed", "suspicious cartoon face"

- growth / change
  central_tension: nhỏ/yếu → lớn/mạnh hơn
  central_symbol: plant, steps, ladder, progress, small win
  query tốt: "watering plant cartoon", "small character step forward", "cute animal trying hard"

- friendship / support
  central_tension: một mình → có người bên cạnh
  central_symbol: hug, side by side, helping hand, umbrella
  query tốt: "friends hug cartoon", "cartoon friends walking together", "cute animal helping friend"

- learning / books
  central_tension: chưa hiểu → hiểu ra / thích thú
  central_symbol: book, lightbulb, reading, library
  query tốt: "cute cat reading book", "cartoon lightbulb idea", "confused character reading book"

Tránh query quá chung nếu thiếu central symbol:
- "cute animal thinking"
- "cartoon nervous"
- "cute animal proud"
- "cartoon celebrate"

Các query trên chỉ được dùng làm fallback, không phải query chính.
Không được yêu cầu GIF phải có chữ/label cụ thể như "Truth", "Lie", "Success", "Greatness".
Text trong GIF được phép nếu tự nhiên và hỗ trợ beat, nhưng không được biến text thành must-have.
central_symbol phải là vật/hành động dễ thấy, không phải chữ viết bắt buộc.

Ví dụ sai:
- lightbulb labeled "Truth"
- pillow saying "Lie"
- trophy with text "Success"

Ví dụ đúng:
- cartoon character squinting at bright light
- cartoon shh secret
- pinocchio nose funny
- character hiding mouth
- cute animal holding trophy
- cartoon crown proud
RULE VISUAL THEO CLIP MẪU:
- Ưu tiên GIPHY kiểu: cartoon, sticker, cute animal, light reaction, simple meme.
- GIF chỉ minh họa phụ, không phải full-screen background.
- Visual phải hợp ý quote là ưu tiên số 1. Visual_family chỉ là gợi ý style, không phải luật cứng.
- Được mix người thật / cartoon / sticker nếu việc mix đó làm quote dễ hiểu, vui hơn hoặc cảm xúc hơn; không mix chỉ vì keyword trùng.
- Tránh visual lạnh/stock/surreal/cinematic nếu nó không phục vụ ý quote; nhưng người thật/cảnh thật vẫn được dùng nếu hợp ý và không bị stock vô hồn.
- Chấp nhận meme/reaction nhẹ nếu nó giúp câu quote dễ hiểu và dễ viral hơn.
- Không tự động loại GIF có chữ lớn. GIF có chữ được dùng nếu chữ đó hỗ trợ đúng ý quote; tránh nếu chữ lệch ý, gây nhiễu, phản nghĩa, watermark rõ, interview/talking head/news/political/vulgar.
- Query phải cụ thể, nhìn thấy được trong GIF.
- Query GIPHY nên ngắn như người thật search GIPHY.

VISUAL_FAMILY HỢP LỆ:
- cartoon_sticker
- cute_animal
- light_reaction
- simple_meme
- real_people_meme

CÁCH DÙNG VISUAL_FAMILY:
- visual_family chỉ giúp định hướng style, không phải luật ép buộc.
- Quote về bạn bè/đồng hành: có thể dùng cartoon_sticker, cute_animal, hoặc người thật nếu thể hiện rõ "đi cùng nhau / bên cạnh nhau".
- Quote vui/hài/châm biếm: simple_meme, light_reaction, cartoon, hoặc người thật hài đều được nếu tự nhiên.
- Quote self-growth/động lực: cartoon/sticker/meme nhẹ hoặc cảnh thật năng động đều được nếu hợp ý.
- Quote buồn/sâu: ưu tiên visual dịu, cảm xúc, nhưng không chọn stock lạnh/vô hồn.
- Được mix visual family giữa các scene nếu mỗi scene minh họa đúng một phần ý quote và chuyển cảnh không bị vô nghĩa.

VÍ DỤ QUERY TỐT:
- "cartoon friends walking together"
- "cute animal friends hug"
- "duck walking with friend cartoon"
- "confused cartoon thinking"
- "cute sticker happy dance"
- "funny cartoon working hard"
- "cat comfort friend"
- "two buddies walking gif"

VÍ DỤ QUERY TỆ:
- "quiet cinematic reflection"
- "person walking alone road cinematic"
- "deep wisdom quote"
- "motivational text"
- "surreal astronaut"
- "city slow motion"
- "stock footage emotional"

TRẢ JSON ĐÚNG SCHEMA:
{{
  "schema_version": "quote_plan_v1",
  "quote_source": {{
    "quote_id_hash": "",
    "text_original": "string",
    "author_raw": "string",
    "author_display": "string",
    "source_name": "Goodreads | BrainyQuote | Unknown",
    "source_url": "string",
    "author_confidence": "high | medium | low"
  }},
  "text_output": {{
    "vi_full": "string",
    "vi_short": "string",
    "caption": "string",
    "fixed_hashtag": "#trichdanmoingay",
    "dynamic_hashtag": "#string"
  }},
  "classification": {{
    "lane": "motivation | healing | love | wisdom | reflection | self-worth | self-growth | discipline | relationships | life-lessons | other",
    "mood": "chill | healing | wisdom | motivation | love | sad | light-humor | hopeful | reflective | gentle | warm | emotional | joyful | playful | upbeat | funny-light | cute",
    "music_mood_tag": "chill | healing | motivation | love | wisdom | sad | hopeful | light-humor | reflective | gentle | warm | emotional | joyful | playful | upbeat | funny-light | cute",
    "literal_possible": true
  }},
  "visual_plan": {{
    "core_meaning": "string",
    "motif_main": "string",
    "visual_world": "pastel meme quote style",
    "visual_family": "cartoon_sticker | cute_animal | light_reaction | simple_meme | real_people_meme",
    "narrative_shape": "contrast | build | reveal | reflection",
    "scene_count": 2,
    "prohibited_visuals": [
      "large text in gif that contradicts or distracts from the quote",
      "subtitle or caption inside media that contradicts or distracts from the quote",
      "watermark or logo",
      "celebrity interview",
      "talking head",
      "news clip",
      "political clip",
      "vulgar or explicit media",
      "irrelevant cold stock footage",
      "surreal abstract stock footage that does not match the quote"
    ],
    "preferred_visual_traits": [
      "cartoon or sticker style",
      "cute meme energy",
      "simple readable action",
      "clear motion loop",
      "text inside gif is acceptable only when it supports the quote",
      "fits pastel background"
    ],
    "consistency_tags": ["string"]
  }},
  "scene_plan": [
    {{
      "scene_id": 1,
      "scene_role": "setup | contrast | payoff | reflection",
      "meaning": "string",
      "visual_goal": "string",
      "visual_family": "cartoon_sticker | cute_animal | light_reaction | simple_meme | real_people_meme",
      "priority": "literal | literal_or_symbolic | symbolic",
      "must_have_elements": ["string"],
      "avoid_elements": ["string"],
      "queries_giphy": ["string", "string", "string"],
      "queries_fallback": ["string", "string"],
      "continuity_tags": ["string"]
    }},
    {{
      "scene_id": 2,
      "scene_role": "setup | contrast | payoff | reflection",
      "meaning": "string",
      "visual_goal": "string",
      "visual_family": "cartoon_sticker | cute_animal | light_reaction | simple_meme | real_people_meme",
      "priority": "literal | literal_or_symbolic | symbolic",
      "must_have_elements": ["string"],
      "avoid_elements": ["string"],
      "queries_giphy": ["string", "string", "string"],
      "queries_fallback": ["string", "string"],
      "continuity_tags": ["string"]
    }}
  ]
}}

CHẤT LƯỢNG:
- 2 scene là mặc định cho quote rất đơn giản; dùng 3 scene nếu quote có tension/problem → action/choice → payoff/result.
- Hai scene không bắt buộc cùng visual_family; chỉ cần cùng phục vụ ý quote và không chắp vá vô nghĩa.
- queries_giphy ưu tiên cartoon/sticker/meme/cute/reaction nhẹ, nhưng người thật hoặc cảnh thật vẫn được nếu hợp ý quote hơn.
- Không query cinematic/stock/surreal theo thói quen; chỉ dùng khi nó thật sự là cách minh họa tốt nhất.
- Nếu quote nói về tình bạn/đồng hành, visual nên là hai nhân vật/động vật đi cạnh nhau, ôm nhau, giúp nhau.
- Nếu quote nói về hành động/làm việc, visual nên là cartoon working, animal working, funny effort sticker.
- Nếu quote nói về trì trệ/lười, visual nên là lazy cartoon, sleepy animal, procrastination meme nhẹ.
- Nếu quote nói về cảm xúc để lại, visual nên là cute comfort, hug, touched reaction, friend smiling.
- vi_short không được ngắn hơn vi_full quá nhiều nếu điều đó làm mất ý gốc.
- Chỉ trả JSON.
""".strip()
def build_compact_prompt(quote_text: str, author: str, source_name: str, source_url: str) -> str:
    return f"""
Bạn là biên tập viên cho video quote ngắn 9:16 của kênh "Trích dẫn mỗi ngày".

INPUT:
- text: {quote_text}
- author: {author}
- source_name: {source_name}
- source_url: {source_url}

YÊU CẦU:
- Dịch quote sang tiếng Việt sát ý gốc, tự nhiên, không rút gọn quá tay.
- Tạo caption riêng, không lặp lại quote.
- Tạo 2 scene visual đơn giản, dễ tìm GIF trên GIPHY.
- Style visual: pastel, cute, wholesome, cartoon/sticker/meme nhẹ.
- Scene phải searchable trên GIPHY.
- Ưu tiên visible action và emotional beat hơn là đúng chính xác con vật hay đạo cụ.
- Nếu quote không bắt buộc đúng con vật/đạo cụ, hãy xem chúng là nice_to_have, không phải must-have.
- Visual_goal phải đơn giản, dễ tìm; không tạo cảnh quá hiếm hoặc quá thơ như cây mọc từ trang sách, linh hồn/ánh sáng trừu tượng, mèo và chó cùng suy tư về hạnh phúc.
- Query GIPHY phải ngắn, cụ thể, có visible action + central symbol của quote nếu có.
- Không dùng query chỉ có mood/action chung như "cute animal thinking", "cartoon nervous", "cute animal proud", "cartoon celebrate" làm query chính.
- Query tốt: "cartoon character scared stage", "cute animal trophy proud", "cartoon shh secret", "watering plant cartoon", "friends hug cartoon", "cute cat reading book".
- Với mỗi quote, tự xác định central_tension và central_symbol trước khi viết scene.
- central_symbol nên là vật/hành động dễ tìm trên GIPHY: stage, crown, trophy, medal, spotlight, shh, plant, steps, hug, book, lightbulb.
- Không được yêu cầu GIF phải có chữ/label cụ thể như "Truth", "Lie", "Success", "Greatness".
- Text trong GIF được phép nếu tự nhiên và hỗ trợ beat, nhưng không được biến text thành must-have.
- central_symbol phải là vật/hành động dễ thấy, không phải chữ viết bắt buộc.
- Ví dụ sai: lightbulb labeled "Truth", pillow saying "Lie", trophy with text "Success".
- Ví dụ đúng: cartoon shh secret, character hiding mouth, cartoon character squinting at bright light, cute animal holding trophy, cartoon crown proud.
- Không dùng query quá trừu tượng như: "deep wisdom", "beautiful soul", "truth energy", "happiness meaning".
- Không dùng cinematic, stock footage, surreal, city, abstract nếu không thật sự cần.
- GIF có chữ vẫn được nếu chữ hỗ trợ đúng beat; chỉ tránh nếu chữ gây hiểu sai, gây nhiễu, watermark/logo.
- Chỉ trả JSON hợp lệ. Không markdown. Không giải thích.

TRẢ JSON THEO FORM NÀY:
{{
  "schema_version": "quote_plan_v1",
  "quote_source": {{
    "text_original": "{quote_text}",
    "author_raw": "{author}",
    "author_display": "{author}",
    "source_name": "{source_name}",
    "source_url": "{source_url}",
    "author_confidence": "medium"
  }},
  "text_output": {{
    "vi_full": "bản dịch tiếng Việt sát nghĩa",
    "vi_short": "bản dùng trên video, gần giống vi_full nếu quote không quá dài",
    "caption": "một câu caption riêng, mở rộng ý nghĩa quote",
    "fixed_hashtag": "#trichdanmoingay",
    "dynamic_hashtag": "#wisdom"
  }},
  "classification": {{
    "lane": "wisdom",
    "mood": "reflective",
    "music_mood_tag": "reflective",
    "literal_possible": true
  }},
  "visual_plan": {{
    "core_meaning": "ý chính của quote",
    "motif_main": "motif visual chính",
    "visual_world": "pastel meme quote style",
    "visual_family": "cartoon_sticker",
    "narrative_shape": "reflection",
    "scene_count": 2,
    "consistency_tags": ["pastel", "cute", "cartoon"]
  }},
  "scene_plan": [
    {{
      "scene_id": 1,
      "scene_role": "setup",
      "meaning": "beat đầu tiên của quote",
      "visual_goal": "mô tả visual cụ thể",
      "visual_family": "cartoon_sticker",
      "priority": "literal_or_symbolic",
    "must_have_elements": ["thinking", "confused"],
    "nice_to_have": ["cat", "dog", "pastel", "cute"],
    "avoid_elements": ["watermark", "news", "political", "vulgar", "random stock footage"],
    "queries_giphy": ["cartoon character facing challenge", "small character big dream"],
    "queries_fallback": ["cute animal thinking"],
      "continuity_tags": ["pastel", "cute"]
    }},
    {{
      "scene_id": 2,
      "scene_role": "payoff",
      "meaning": "beat kết của quote",
      "visual_goal": "mô tả visual cụ thể",
      "visual_family": "cartoon_sticker",
      "priority": "literal_or_symbolic",
        "must_have_elements": ["warm connection", "relief"],
        "nice_to_have": ["cat", "dog", "pastel", "hug"],
        "avoid_elements": ["watermark", "news", "political", "vulgar", "random stock footage"],
        "queries_giphy": ["cute animal trophy proud", "cartoon crown proud"],
        "queries_fallback": ["cartoon happy relief"],
      "continuity_tags": ["pastel", "cute"]
    }}
  ]
}}
""".strip()

def _call_model_once(client: Any, model_name: str, prompt: str, *, use_thinking: bool) -> str:
    if use_thinking:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_level="high")
                ),
            )
            return response.text or ""
        except TypeError:
            pass

    response = client.models.generate_content(model=model_name, contents=prompt)
    return response.text or ""
def _call_openrouter_once(prompt: str) -> tuple[str, str]:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY")

    model_name = (
        os.getenv("OPENROUTER_QUOTE_FALLBACK_MODEL", "").strip()
        or "nvidia/nemotron-3-super-120b-a12b:free"
    )

    use_nemotron_thinking = os.getenv("OPENROUTER_NEMOTRON_THINKING", "1").strip() == "1"
    low_effort = os.getenv("OPENROUTER_NEMOTRON_LOW_EFFORT", "0").strip() == "1"
    reasoning_max_tokens = int(os.getenv("OPENROUTER_NEMOTRON_REASONING_MAX_TOKENS", "4096"))

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return only valid JSON in message.content. "
                    "No markdown. No explanation outside JSON."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": float(os.getenv("OPENROUTER_QUOTE_FALLBACK_TEMPERATURE", "1.0")),
        "top_p": float(os.getenv("OPENROUTER_QUOTE_FALLBACK_TOP_P", "0.95")),
        "max_tokens": int(os.getenv("OPENROUTER_QUOTE_FALLBACK_MAX_TOKENS", "6000")),
    }

    if use_nemotron_thinking:
        payload["reasoning"] = {
            "enabled": True,
            "max_tokens": reasoning_max_tokens,
            "exclude": True,
        }
        payload["chat_template_kwargs"] = {
            "enable_thinking": True,
            "low_effort": low_effort,
        }

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/sangbate258/daily-quotes-bot",
            "X-Title": "daily-quotes-bot",
        },
        json=payload,
        timeout=int(os.getenv("OPENROUTER_QUOTE_FALLBACK_TIMEOUT_SEC", "120")),
    )

    # Some OpenRouter providers may reject provider-specific fields.
    # Retry once without thinking controls instead of killing the fallback.
    if response.status_code in {400, 422} and use_nemotron_thinking:
        payload.pop("reasoning", None)
        payload.pop("chat_template_kwargs", None)
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/sangbate258/daily-quotes-bot",
                "X-Title": "daily-quotes-bot",
            },
            json=payload,
            timeout=int(os.getenv("OPENROUTER_QUOTE_FALLBACK_TIMEOUT_SEC", "120")),
        )

    response.raise_for_status()
    payload = response.json()

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"OpenRouter returned no choices: {payload}")

    message = choices[0].get("message") or {}
    content = (message.get("content") or "").strip()
    if not content:
        raise RuntimeError(f"OpenRouter returned empty content: {payload}")

    resolved_model = str(payload.get("model") or model_name)
    return content, resolved_model
def _fallback_ai_data_for_dev_only(quote: dict[str, str]) -> dict[str, Any]:
    text = safe_str(quote.get("text"))
    author = normalize_author_display(quote.get("author"))

    shortened = text
    # Development fallback should preserve meaning, not compress aggressively.
    if len(shortened) > 170:
        shortened = shortened[:167].rstrip() + "..."

    data = {
        "schema_version": "quote_plan_v1",
        "quote_source": {
            "quote_id_hash": stable_quote_hash(text, author, quote.get("source_url", "")),
            "text_original": text,
            "author_raw": quote.get("author", ""),
            "author_display": author,
            "source_name": quote.get("source_name", "Unknown"),
            "source_url": quote.get("source_url", ""),
            "author_confidence": "low",
        },
        "text_output": {
            "vi_full": shortened,
            "vi_short": shortened,
            "caption": "Có những điều chỉ thật sự rõ ra khi ta dừng lại và nhìn kỹ hơn.",
            "fixed_hashtag": "#trichdanmoingay",
            "dynamic_hashtag": "#wisdom",
        },
        "classification": {
            "lane": "wisdom",
            "mood": "reflective",
            "music_mood_tag": "reflective",
            "literal_possible": False,
        },
        "visual_plan": {
            "core_meaning": shortened,
            "motif_main": "cute cartoon thinking sticker",
            "visual_world": "pastel cartoon sticker meme style",
            "narrative_shape": "reflection",
            "scene_count": 2,
            "prohibited_visuals": list(DEFAULT_PROHIBITED_VISUALS),
            "preferred_visual_traits": ["clean background", "soft light", "low visual noise", "text only if it supports the quote"],
            "consistency_tags": ["cartoon_sticker", "friends", "pastel"],
        },
        "scene_plan": [
            {
                "scene_id": 1,
                "scene_role": "setup",
                "meaning": shortened[:60],
                "visual_goal": "A cute cartoon character thinking quietly",
                "priority": "symbolic",
                "must_have_elements": ["cartoon", "thinking", "cute"],
                "avoid_elements": list(DEFAULT_PROHIBITED_VISUALS),
                "queries_giphy": ["cute cartoon thinking", "confused cartoon thinking", "cute thinking sticker"],
                "queries_fallback": ["person thinking window", "quiet cinematic window"],
                "continuity_tags": ["cartoon_sticker", "thinking", "pastel"],
            },
            {
                "scene_id": 2,
                "scene_role": "payoff",
                "meaning": shortened[60:120] or shortened[:60],
                "visual_goal": "A cute cartoon character walking with a friend",
                "priority": "symbolic",
                "must_have_elements": ["cartoon", "friends", "walking"],
                "avoid_elements": list(DEFAULT_PROHIBITED_VISUALS),
                "queries_giphy": ["cartoon friends walking together", "cute animal friends walking", "two buddies walking gif"],
                "queries_fallback": ["person walking alone", "calm cinematic walk"],
                "continuity_tags": ["cartoon_sticker", "friends", "pastel"],
            },
        ],
        "_fallback_warning": "LOCAL FALLBACK ONLY - NOT FINAL QUALITY",
    }
    return normalize_output(data, original_quote=quote)


def process_one_quote(quote: dict[str, str]) -> dict[str, Any]:
    load_dotenv()

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Thiếu GOOGLE_API_KEY trong file .env")

    model_name = os.getenv("GOOGLE_MODEL_NAME", MODEL_NAME).strip() or MODEL_NAME
    max_attempts = int(os.getenv("AI_MAX_ATTEMPTS", "4"))

    client = genai.Client(api_key=api_key)

    prompt = build_prompt(
        quote_text=quote["text"],
        author=quote["author"],
        source_name=quote["source_name"],
        source_url=quote["source_url"],
    )

    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        use_compact_prompt = attempt > 1 and os.getenv("USE_COMPACT_AI_RETRY", "1").strip() == "1"
        attempt_prompt = (
            build_compact_prompt(
                quote_text=quote["text"],
                author=quote["author"],
                source_name=quote["source_name"],
                source_url=quote["source_url"],
            )
            if use_compact_prompt
            else prompt
        )
        use_thinking = attempt == 1 and not use_compact_prompt

        print(f"[AI PROMPT MODE] {'compact' if use_compact_prompt else 'full'} thinking={int(use_thinking)}")

        try:
            raw_text = _call_model_once(client, model_name, attempt_prompt, use_thinking=use_thinking)

            if not raw_text.strip():
                raise RuntimeError("Model trả output rỗng")

            data = extract_json_object(raw_text)
            data = normalize_output(data, original_quote=quote)
            data["_raw_model_text"] = raw_text
            data["_model_name"] = model_name
            data["_ai_attempt"] = attempt
            return data

        except Exception as e:
            last_error = e
            print(f"[AI WARN] attempt {attempt}/{max_attempts} failed:", e)

            if attempt < max_attempts:
                sleep_s = min(8.0, 1.5 * attempt + random.random())
                time.sleep(sleep_s)

    if os.getenv("USE_OPENROUTER_AI_FALLBACK", "1").strip() == "1":
        try:
            fallback_prompt = build_compact_prompt(
                quote_text=quote["text"],
                author=quote["author"],
                source_name=quote["source_name"],
                source_url=quote["source_url"],
            )

            print("[AI FALLBACK] openrouter starting")
            raw_text, fallback_model_name = _call_openrouter_once(fallback_prompt)

            data = extract_json_object(raw_text)
            data = normalize_output(data, original_quote=quote)
            data["_raw_model_text"] = raw_text
            data["_model_name"] = fallback_model_name
            data["_ai_attempt"] = "openrouter_fallback"
            data["_primary_model_name"] = model_name
            data["_primary_model_error"] = str(last_error)

            print(f"[AI FALLBACK] openrouter model={fallback_model_name}")
            return data

        except Exception as fallback_error:
            print("[AI FALLBACK WARN] openrouter failed:", fallback_error)

    if os.getenv("ALLOW_LOCAL_AI_FALLBACK", "0").strip() == "1":
        print("[AI WARN] Using LOCAL fallback planner. This is for pipeline testing only.")
        return _fallback_ai_data_for_dev_only(quote)

    raise RuntimeError(f"AI failed after {max_attempts} attempts. Last error: {last_error}")

if __name__ == "__main__":
    raw_quotes = fetch_all_raw_quotes()
    filtered_quotes = filter_quotes(raw_quotes)

    if not filtered_quotes:
        raise RuntimeError("Không còn quote nào sau khi filter")

    first_quote = {
        "text": filtered_quotes[0].text,
        "author": filtered_quotes[0].author,
        "source_name": filtered_quotes[0].source_name,
        "source_url": filtered_quotes[0].source_url,
    }

    print("Testing AI processor with quote:")
    print(json.dumps(first_quote, ensure_ascii=False, indent=2))
    print("\n--- MODEL OUTPUT ---\n")

    result = process_one_quote(first_quote)

    raw_model_text = result.pop("_raw_model_text", "")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    print("\n--- RAW MODEL TEXT (first 500 chars) ---\n")
    print(raw_model_text[:500])
