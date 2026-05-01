from __future__ import annotations

from pathlib import Path
import json
import random
import subprocess
from typing import Any

from config import load_config


AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}

KNOWN_MOOD_TAGS = {
    "chill", "healing", "motivation", "love", "wisdom", "sad", "hopeful",
    "light-humor", "reflective", "deep_reflective", "gentle", "warm",
    "emotional", "joyful", "playful", "upbeat", "funny-light", "cute",
    "meme", "discipline", "action", "life-lessons",
}

MOOD_ALIASES = {
    "reflection": "reflective",
    "reflective-light": "reflective",
    "thoughtful": "reflective",
    "philosophy": "wisdom",
    "life lesson": "life-lessons",
    "life-lessons": "life-lessons",
    "deep": "deep_reflective",
    "deep-reflective": "deep_reflective",
    "soft": "gentle",
    "calm": "gentle",
    "gentle": "gentle",
    "warm": "warm",
    "emotional": "emotional",
    "joy": "joyful",
    "happy": "joyful",
    "joyful": "joyful",
    "playful": "playful",
    "funny": "funny-light",
    "funny-light": "funny-light",
    "light humor": "light-humor",
    "light-humor": "light-humor",
    "cute": "cute",
    "uplifting": "hopeful",
    "hope": "hopeful",
    "hopeful": "hopeful",
    "upbeat": "upbeat",
    "dance": "joyful",
    "freeing": "joyful",
    "motivation": "motivation",
    "motivational": "motivation",
    "discipline": "discipline",
    "action": "action",
    "sad": "sad",
    "melancholy": "sad",
    "melancholic": "sad",
    "lonely": "sad",
    "loneliness": "sad",
    "love": "love",
    "romantic": "love",
}

# Hard guard: do not let generic chill tracks leak into deep quote moods.
STRICT_ALLOWED_FAMILIES = {
    "wisdom": {"wisdom", "reflective", "deep_reflective", "healing", "gentle", "warm", "emotional", "love", "sad"},
    "reflective": {"wisdom", "reflective", "deep_reflective", "healing", "gentle", "warm", "emotional", "love", "sad"},
    "deep_reflective": {"wisdom", "reflective", "deep_reflective", "healing", "gentle", "warm", "emotional", "love", "sad"},
    "emotional": {"wisdom", "reflective", "healing", "gentle", "warm", "emotional", "love", "sad"},
    "healing": {"healing", "gentle", "warm", "emotional", "reflective", "love", "sad", "wisdom"},
    "sad": {"sad", "emotional", "healing", "gentle", "reflective"},
}

MOOD_INTENTS = {
    "wisdom": {
        "wanted": {"wisdom", "reflective", "deep_reflective", "gentle", "warm", "emotional"},
        "avoid": {"chill", "neutral", "joyful", "dance", "upbeat", "light-humor", "playful", "funny-light"},
        "energy": {"low"},
    },
    "reflective": {
        "wanted": {"reflective", "wisdom", "gentle", "warm", "emotional"},
        "avoid": {"chill", "neutral", "joyful", "dance", "upbeat", "light-humor", "playful", "funny-light"},
        "energy": {"low"},
    },
    "deep_reflective": {
        "wanted": {"deep_reflective", "reflective", "wisdom", "gentle", "emotional"},
        "avoid": {"chill", "neutral", "joyful", "dance", "upbeat", "light-humor", "playful", "funny-light"},
        "energy": {"low"},
    },
    "healing": {
        "wanted": {"healing", "gentle", "warm", "emotional", "reflective"},
        "avoid": {"chill", "neutral", "dance", "upbeat", "high_energy", "light-humor"},
        "energy": {"low"},
    },
    "gentle": {
        "wanted": {"gentle", "warm", "healing", "reflective"},
        "avoid": {"dance", "upbeat", "high_energy", "light-humor"},
        "energy": {"low"},
    },
    "warm": {
        "wanted": {"warm", "gentle", "healing", "love", "reflective", "emotional"},
        "avoid": {"dance", "upbeat", "high_energy"},
        "energy": {"low"},
    },
    "emotional": {
        "wanted": {"emotional", "warm", "healing", "sad", "reflective"},
        "avoid": {"chill", "neutral", "joyful", "dance", "upbeat", "light-humor", "funny-light"},
        "energy": {"low"},
    },
    "sad": {
        "wanted": {"sad", "emotional", "healing", "gentle"},
        "avoid": {"joyful", "dance", "upbeat", "light-humor", "playful"},
        "energy": {"low"},
    },
    "love": {
        "wanted": {"love", "warm", "gentle", "emotional", "healing"},
        "avoid": {"dance", "upbeat", "light-humor"},
        "energy": {"low", "medium"},
    },
    "hopeful": {
        "wanted": {"hopeful", "motivation", "warm", "upbeat"},
        "avoid": {"sad", "grief", "heavy_emotion"},
        "energy": {"medium", "high"},
    },
    "motivation": {
        "wanted": {"motivation", "discipline", "action", "hopeful", "upbeat"},
        "avoid": {"sad", "grief", "deep_reflective"},
        "energy": {"medium", "high"},
    },
    "joyful": {
        "wanted": {"joyful", "playful", "upbeat", "funny-light", "light-humor"},
        "avoid": {"sad", "deep_reflective", "grief", "heavy_emotion"},
        "energy": {"medium", "high"},
    },
    "playful": {
        "wanted": {"playful", "joyful", "funny-light", "light-humor", "cute"},
        "avoid": {"sad", "deep_reflective", "grief", "heavy_emotion"},
        "energy": {"medium", "high"},
    },
    "upbeat": {
        "wanted": {"upbeat", "joyful", "playful", "motivation", "hopeful"},
        "avoid": {"sad", "deep_reflective", "grief", "heavy_emotion"},
        "energy": {"medium", "high"},
    },
    "light-humor": {
        "wanted": {"light-humor", "funny-light", "playful", "cute", "meme"},
        "avoid": {"sad", "deep_reflective", "grief", "heavy_emotion"},
        "energy": {"medium"},
    },
    "funny-light": {
        "wanted": {"funny-light", "light-humor", "playful", "cute", "meme"},
        "avoid": {"sad", "deep_reflective", "grief", "heavy_emotion"},
        "energy": {"medium"},
    },
    "cute": {
        "wanted": {"cute", "playful", "light-humor", "funny-light", "warm"},
        "avoid": {"sad", "deep_reflective", "grief", "heavy_emotion"},
        "energy": {"low", "medium"},
    },
    "chill": {
        "wanted": {"chill", "neutral", "gentle", "warm"},
        "avoid": set(),
        "energy": {"low", "medium"},
    },
}


def normalize_mood_tag(raw_tag: str) -> str:
    text = (raw_tag or "").strip().lower().replace("_", "-")
    text = " ".join(text.split())

    if text in MOOD_ALIASES:
        return MOOD_ALIASES[text]
    if text in KNOWN_MOOD_TAGS:
        return text

    if any(k in text for k in ["dance", "free", "joy", "happy", "vui", "khiêu vũ"]):
        return "joyful"
    if any(k in text for k in ["funny", "humor", "meme", "hài", "bựa"]):
        return "funny-light"
    if any(k in text for k in ["reflect", "thought", "wisdom", "triết", "suy ngẫm"]):
        return "reflective"
    if any(k in text for k in ["heal", "gentle", "soft", "ấm", "dịu"]):
        return "healing"
    if any(k in text for k in ["sad", "melanch", "buồn", "cô đơn"]):
        return "sad"
    if any(k in text for k in ["love", "romance", "yêu"]):
        return "love"
    if any(k in text for k in ["motivat", "discipline", "action", "động lực", "kỷ luật"]):
        return "motivation"

    return "chill"


def list_audio_files(folder: Path) -> list[Path]:
    if not folder.exists() or not folder.is_dir():
        return []

    files = []
    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            files.append(path)

    files.sort()
    return files


def load_music_manifest(config) -> list[dict[str, Any]]:
    manifest_path = config.music_dir / "music_manifest.json"
    if not manifest_path.exists():
        return []

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print("[WARN] Cannot read music_manifest.json:", e)
        return []

    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        return []

    result = []
    for item in tracks:
        if not isinstance(item, dict):
            continue

        rel_file = item.get("file", "")
        project_root_path = config.music_dir.parent / rel_file

        if not project_root_path.exists():
            continue

        item = dict(item)
        item["_local_path"] = project_root_path
        result.append(item)

    return result


def energy_score(track_energy: str, allowed_energy: set[str]) -> float:
    energy = (track_energy or "").strip().lower()
    if not allowed_energy:
        return 0.0
    if energy in allowed_energy:
        return 3.0
    return -4.0


def is_hard_blocked(track: dict[str, Any], mood: str) -> tuple[bool, str | None]:
    mood_tags = set(str(x).strip().lower() for x in track.get("mood_tags", []) if str(x).strip())
    good_for = set(str(x).strip().lower() for x in track.get("good_for", []) if str(x).strip())
    avoid_for = set(str(x).strip().lower() for x in track.get("avoid_for", []) if str(x).strip())
    energy = str(track.get("energy", "")).strip().lower()

    if mood in avoid_for:
        return True, f"track_explicitly_avoids_{mood}"

    if mood in STRICT_ALLOWED_FAMILIES:
        allowed = STRICT_ALLOWED_FAMILIES[mood]
        if not ((mood_tags | good_for) & allowed):
            return True, f"not_in_strict_allowed_family_for_{mood}"
        if energy != "low":
            return True, f"energy_{energy}_not_allowed_for_{mood}"

    return False, None


def score_track(track: dict[str, Any], mood: str) -> tuple[float, list[str]]:
    blocked, block_reason = is_hard_blocked(track, mood)
    if blocked:
        return -999.0, [block_reason or "hard_blocked"]

    intent = MOOD_INTENTS.get(mood, MOOD_INTENTS["chill"])
    wanted = set(intent.get("wanted", set()))
    avoid = set(intent.get("avoid", set()))
    allowed_energy = set(intent.get("energy", set()))

    mood_tags = set(str(x).strip().lower() for x in track.get("mood_tags", []) if str(x).strip())
    good_for = set(str(x).strip().lower() for x in track.get("good_for", []) if str(x).strip())
    avoid_for = set(str(x).strip().lower() for x in track.get("avoid_for", []) if str(x).strip())

    score = 0.0
    reasons: list[str] = []

    if mood in mood_tags:
        score += 6.0
        reasons.append(f"direct_mood_match={mood}")

    if mood in good_for:
        score += 4.0
        reasons.append(f"direct_good_for={mood}")

    wanted_hits = (mood_tags | good_for) & wanted
    if wanted_hits:
        score += 2.0 * len(wanted_hits)
        reasons.append(f"wanted_hits={','.join(sorted(wanted_hits))}")

    forbidden_hits = (mood_tags | good_for) & avoid
    if forbidden_hits:
        score -= 5.0 * len(forbidden_hits)
        reasons.append(f"avoid_hits={','.join(sorted(forbidden_hits))}")

    es = energy_score(str(track.get("energy", "")), allowed_energy)
    score += es
    reasons.append(f"energy_score={es}")

    weight = float(track.get("weight", 1.0) or 1.0)
    score *= max(0.1, weight)

    return round(score, 3), reasons



def get_audio_duration_sec(path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return None
        return float(result.stdout.strip())
    except Exception:
        return None


def infer_pixabay_track_metadata(path: Path) -> dict[str, Any]:
    """
    Infer minimal mood metadata from curated Pixabay file names.

    Expected prefixes:
    reflective_, warm_, humor_, motivation_, sad_, cute_
    """
    name = path.stem.lower()
    duration_sec = get_audio_duration_sec(path)

    mood_tags: list[str] = ["pixabay"]
    good_for: list[str] = []
    avoid_for: list[str] = []
    energy = "medium"
    tempo_feel = "medium"

    if name.startswith("reflective_"):
        mood_tags += ["reflective", "wisdom", "emotional", "gentle"]
        good_for += ["reflective", "wisdom", "deep_reflective", "emotional"]
        avoid_for += ["joyful", "upbeat", "light-humor"]
        energy = "low"
        tempo_feel = "slow"
    elif name.startswith("warm_"):
        mood_tags += ["warm", "gentle", "healing", "emotional", "love"]
        good_for += ["warm", "healing", "love", "friendship", "emotional"]
        avoid_for += ["sad", "dark", "high_energy"]
        energy = "low"
        tempo_feel = "medium"
    elif name.startswith("humor_"):
        mood_tags += ["light-humor", "funny-light", "playful", "meme"]
        good_for += ["light-humor", "funny-light", "playful", "sarcasm", "deadpan"]
        avoid_for += ["sad", "deep_reflective", "grief"]
        energy = "medium"
        tempo_feel = "medium"
    elif name.startswith("motivation_"):
        mood_tags += ["motivation", "hopeful", "upbeat", "discipline", "action"]
        good_for += ["motivation", "hopeful", "discipline", "self-growth"]
        avoid_for += ["sad", "grief", "deep_reflective"]
        energy = "medium"
        tempo_feel = "upbeat"
    elif name.startswith("sad_"):
        mood_tags += ["sad", "healing", "emotional", "gentle", "reflective"]
        good_for += ["sad", "healing", "emotional", "loneliness"]
        avoid_for += ["joyful", "upbeat", "light-humor", "meme"]
        energy = "low"
        tempo_feel = "slow"
    elif name.startswith("cute_"):
        mood_tags += ["cute", "playful", "joyful", "light-humor", "warm"]
        good_for += ["cute", "playful", "joyful", "light-humor"]
        avoid_for += ["sad", "deep_reflective", "grief"]
        energy = "medium"
        tempo_feel = "medium"
    else:
        mood_tags += ["chill", "gentle"]
        good_for += ["chill", "gentle"]
        energy = "low"
        tempo_feel = "medium"

    return {
        "file": str(path),
        "_local_path": path,
        "source": "pixabay_local",
        "mood_tags": mood_tags,
        "energy": energy,
        "tempo_feel": tempo_feel,
        "good_for": good_for,
        "avoid_for": avoid_for,
        "duration_sec": duration_sec,
        "weight": 1.0,
    }


def load_pixabay_local_library(config) -> list[dict[str, Any]]:
    pixabay_dir = config.music_dir / "pixabay"
    if not pixabay_dir.exists() or not pixabay_dir.is_dir():
        return []

    tracks: list[dict[str, Any]] = []
    for path in list_audio_files(pixabay_dir):
        tracks.append(infer_pixabay_track_metadata(path))

    return tracks


def select_from_pixabay_local(config, mood: str) -> dict[str, Any] | None:
    tracks = load_pixabay_local_library(config)
    if not tracks:
        return None

    ranked: list[tuple[float, dict[str, Any], list[str]]] = []
    blocked_log: list[str] = []

    for track in tracks:
        local_path: Path = track["_local_path"]
        duration_sec = track.get("duration_sec")

        if duration_sec is not None and duration_sec < 18:
            blocked_log.append(f"{local_path.name}:duration_too_short={duration_sec:.1f}s")
            continue

        score, reasons = score_track(track, mood)
        if duration_sec is not None:
            if duration_sec >= 30:
                score += 1.0
                reasons.append("duration_ok>=30s")
            elif duration_sec >= 18:
                score += 0.3
                reasons.append("duration_acceptable>=18s")

        if score > 0:
            ranked.append((score, track, reasons))
        elif score <= -999:
            blocked_log.append(f"{local_path.name}:{reasons[0] if reasons else 'blocked'}")

    if not ranked:
        print("[WARN] No positive-scored Pixabay local music candidate. Blocked:", blocked_log[:8])
        return None

    ranked.sort(key=lambda x: x[0], reverse=True)

    top_score = ranked[0][0]
    top = [item for item in ranked if item[0] >= top_score - 0.5]
    score, track, reasons = random.choice(top)
    local_path: Path = track["_local_path"]

    return {
        "requested_mood_tag": mood,
        "resolved_mood_tag": mood,
        "picked_from": "pixabay_local_v1",
        "source": "pixabay_local",
        "file_name": local_path.name,
        "local_path": str(local_path),
        "duration_sec": track.get("duration_sec"),
        "selection_score": round(score, 3),
        "selection_reason": reasons,
        "blocked_candidates_sample": blocked_log[:10],
        "license_note": "Manually downloaded from Pixabay Music; keep original source/license info if available.",
        "track_manifest": {
            "mood_tags": track.get("mood_tags", []),
            "energy": track.get("energy"),
            "tempo_feel": track.get("tempo_feel"),
            "good_for": track.get("good_for", []),
            "avoid_for": track.get("avoid_for", []),
        },
    }



def select_from_manifest(config, mood: str) -> dict[str, Any] | None:
    tracks = load_music_manifest(config)
    if not tracks:
        return None

    ranked: list[tuple[float, dict[str, Any], list[str]]] = []
    blocked_log: list[str] = []

    for track in tracks:
        score, reasons = score_track(track, mood)
        if score > 0:
            ranked.append((score, track, reasons))
        elif score <= -999:
            blocked_log.append(f"{Path(track.get('file','')).name}:{reasons[0] if reasons else 'blocked'}")

    if not ranked:
        print("[WARN] No positive-scored music candidate. Blocked:", blocked_log[:8])
        return None

    ranked.sort(key=lambda x: x[0], reverse=True)

    # Choose from very top only. This prevents low-score generic chill from sneaking in.
    top_score = ranked[0][0]
    top = [item for item in ranked if item[0] >= top_score - 0.5]

    score, track, reasons = random.choice(top)
    local_path: Path = track["_local_path"]

    return {
        "requested_mood_tag": mood,
        "resolved_mood_tag": mood,
        "picked_from": "music_manifest_v3_hard_guard",
        "file_name": local_path.name,
        "local_path": str(local_path),
        "selection_score": score,
        "selection_reason": reasons,
        "blocked_candidates_sample": blocked_log[:10],
        "track_manifest": {
            "mood_tags": track.get("mood_tags", []),
            "energy": track.get("energy"),
            "tempo_feel": track.get("tempo_feel"),
            "good_for": track.get("good_for", []),
            "avoid_for": track.get("avoid_for", []),
        },
    }


def pick_random_track(folder: Path) -> Path | None:
    tracks = list_audio_files(folder)
    if not tracks:
        return None
    return random.choice(tracks)


def safe_folder_fallback_moods(mood: str) -> list[str]:
    if mood in {"wisdom", "reflective", "deep_reflective", "emotional"}:
        return ["wisdom", "healing", "love", "sad"]
    if mood in {"healing", "gentle", "warm"}:
        return ["healing", "love", "wisdom", "sad"]
    if mood in {"joyful", "playful", "upbeat", "funny-light", "light-humor", "cute"}:
        return ["light-humor", "motivation", "chill"]
    if mood in {"motivation", "discipline", "action", "hopeful"}:
        return ["motivation", "light-humor", "chill"]
    if mood == "sad":
        return ["sad", "healing", "wisdom"]
    if mood == "love":
        return ["love", "healing", "wisdom"]
    return ["chill", "healing", "wisdom"]


def select_music_track(music_mood_tag: str) -> dict:
    config = load_config()

    requested = music_mood_tag
    mood = normalize_mood_tag(music_mood_tag)

    # Prefer the user's curated Pixabay Music library.
    picked = select_from_pixabay_local(config, mood)
    if picked:
        picked["requested_mood_tag"] = requested
        return picked

    picked = select_from_manifest(config, mood)
    if picked:
        picked["requested_mood_tag"] = requested
        return picked

    # Safer fallback than old random folder.
    for folder_mood in safe_folder_fallback_moods(mood):
        folder = config.music_dir / folder_mood
        chosen = pick_random_track(folder)
        if chosen:
            return {
                "requested_mood_tag": requested,
                "resolved_mood_tag": mood,
                "picked_from": f"safe_folder_fallback:{folder_mood}",
                "file_name": chosen.name,
                "local_path": str(chosen),
                "selection_reason": [
                    "music_manifest missing or no positive candidate; used safe fallback mood list"
                ],
            }

    raise RuntimeError(f"Không tìm thấy file nhạc hợp lệ cho mood '{mood}'")


if __name__ == "__main__":
    test_tags = [
        "chill", "wisdom", "reflective", "deep_reflective", "healing",
        "emotional", "motivation", "joyful", "playful", "light-humor",
        "sad", "love",
    ]

    results = []
    for tag in test_tags:
        try:
            results.append(select_music_track(tag))
        except Exception as e:
            results.append({
                "requested_mood_tag": tag,
                "error": str(e),
            })

    print(json.dumps(results, ensure_ascii=False, indent=2))
