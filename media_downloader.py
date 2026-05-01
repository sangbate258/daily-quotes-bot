from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
import json
import requests
import subprocess

from media_selector import select_media_for_scene


TEMP_MEDIA_DIR = Path("temp_media")
TEMP_MEDIA_DIR.mkdir(exist_ok=True)

PREVIEW_DIR = TEMP_MEDIA_DIR / "previews"
PREVIEW_DIR.mkdir(exist_ok=True)


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


def build_filename(media: dict) -> str:
    media_key = media["media_key"].replace(":", "_")
    ext = guess_extension(media)
    return f"{media_key}{ext}"


def build_preview_filename(media: dict) -> str:
    media_key = media["media_key"].replace(":", "_")
    return f"{media_key}_sheet.jpg"


def download_file(url: str, out_path: Path) -> None:
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)


def create_preview_sheet(local_path: Path, preview_path: Path) -> bool:
    """
    Create a compact visual sheet for later GIF understanding/judging.

    This is intentionally non-fatal: if FFmpeg fails, the video pipeline should
    still continue. The preview is a debugging/AI-judge helper, not required
    for rendering.
    """
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
        return result.returncode == 0 and preview_path.exists()
    except Exception:
        return False


def attach_preview_sheet(media: dict, local_path: Path) -> dict:
    preview_path = PREVIEW_DIR / build_preview_filename(media)
    generated = create_preview_sheet(local_path, preview_path)

    if preview_path.exists():
        media["preview_sheet"] = str(preview_path)
        media["preview_generated"] = generated
    else:
        media["preview_sheet"] = None
        media["preview_generated"] = False

    return media


def download_selected_media(media: dict) -> dict:
    filename = build_filename(media)
    out_path = TEMP_MEDIA_DIR / filename

    if out_path.exists():
        media["local_path"] = str(out_path)
        media["downloaded"] = False
        return attach_preview_sheet(media, out_path)

    url = media.get("media_url") or media.get("mp4_url") or media.get("gif_url")
    if not url:
        raise RuntimeError("Media không có URL để tải")

    download_file(url, out_path)

    media["local_path"] = str(out_path)
    media["downloaded"] = True
    return attach_preview_sheet(media, out_path)


if __name__ == "__main__":
    sample_queries = [
        "one colorful person in a crowd of grey people",
        "confident person looking in mirror smiling",
    ]

    results = []

    for query in sample_queries:
        picked = select_media_for_scene(query)
        if not picked:
            results.append({
                "query": query,
                "picked": None,
            })
            continue

        downloaded = download_selected_media(dict(picked))
        results.append({
            "query": query,
            "picked": downloaded,
        })

    print(json.dumps(results, ensure_ascii=False, indent=2))
