from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
import requests
import subprocess


TEMP_MEDIA_DIR = Path("temp_media")
VISION_CANDIDATE_DIR = TEMP_MEDIA_DIR / "vision_candidates"
PREVIEW_DIR = TEMP_MEDIA_DIR / "previews"

for folder in [TEMP_MEDIA_DIR, VISION_CANDIDATE_DIR, PREVIEW_DIR]:
    folder.mkdir(exist_ok=True)


def guess_extension(media: dict) -> str:
    if media.get("mp4_url"):
        return ".mp4"
    if media.get("gif_url"):
        return ".gif"

    url = media.get("media_url", "")
    path = urlparse(url).path.lower()
    if path.endswith(".mp4"):
        return ".mp4"
    if path.endswith(".gif"):
        return ".gif"

    return ".bin"


def build_media_filename(media: dict) -> str:
    media_key = str(media.get("media_key") or media.get("candidate_id") or "unknown_media")
    safe_key = media_key.replace(":", "_").replace("/", "_").replace("\\", "_")
    return f"{safe_key}{guess_extension(media)}"


def build_preview_filename(media: dict) -> str:
    media_key = str(media.get("media_key") or media.get("candidate_id") or "unknown_media")
    safe_key = media_key.replace(":", "_").replace("/", "_").replace("\\", "_")
    return f"{safe_key}_sheet.jpg"


def download_file(url: str, out_path: Path) -> bool:
    if out_path.exists():
        return False

    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    return True


def ensure_candidate_local_file(media: dict) -> Path | None:
    url = media.get("media_url") or media.get("mp4_url") or media.get("gif_url")
    if not url:
        return None

    out_path = VISION_CANDIDATE_DIR / build_media_filename(media)

    try:
        download_file(url, out_path)
    except Exception as e:
        print(f"[VISION WARN] candidate download failed: {media.get('media_key')} -> {e}")
        return None

    return out_path if out_path.exists() else None


def create_preview_sheet(local_path: Path, preview_path: Path) -> bool:
    if preview_path.exists():
        return False

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(local_path),
        "-vf",
        "fps=1,scale=240:240:force_original_aspect_ratio=decrease,"
        "pad=240:240:(ow-iw)/2:(oh-ih)/2,tile=5x1",
        "-frames:v",
        "1",
        str(preview_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"[VISION WARN] preview ffmpeg failed for {local_path.name}: {result.stderr[-300:]}")
            return False
        return preview_path.exists()
    except Exception as e:
        print(f"[VISION WARN] preview generation failed: {local_path} -> {e}")
        return False


def ensure_preview_sheet(media: dict) -> dict:
    """
    Ensure a candidate has a local file and a preview sheet.

    This is non-fatal. If download/ffmpeg fails, it returns the media dict with:
    - vision_local_path = None
    - preview_sheet = None
    - preview_generated = False
    """
    media = dict(media)

    existing_preview = media.get("preview_sheet")
    if existing_preview and Path(existing_preview).exists():
        media["preview_generated"] = False
        return media

    local_path = None
    if media.get("local_path") and Path(media["local_path"]).exists():
        local_path = Path(media["local_path"])
    else:
        local_path = ensure_candidate_local_file(media)

    if not local_path:
        media["vision_local_path"] = None
        media["preview_sheet"] = None
        media["preview_generated"] = False
        return media

    preview_path = PREVIEW_DIR / build_preview_filename(media)
    generated = create_preview_sheet(local_path, preview_path)

    media["vision_local_path"] = str(local_path)
    media["preview_sheet"] = str(preview_path) if preview_path.exists() else None
    media["preview_generated"] = generated

    return media
