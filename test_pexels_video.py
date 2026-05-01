from dotenv import load_dotenv
from pathlib import Path
import os
import requests

load_dotenv()

API_KEY = os.getenv("PEXELS_API_KEY")
if not API_KEY:
    raise RuntimeError("Thiếu PEXELS_API_KEY trong file .env")

OUTPUT_DIR = Path("temp_media")
OUTPUT_DIR.mkdir(exist_ok=True)

SEARCH_QUERY = "sunrise ocean"

headers = {
    "Authorization": API_KEY
}

params = {
    "query": SEARCH_QUERY,
    "per_page": 3
}

print(f"Searching Pexels for: {SEARCH_QUERY}")
resp = requests.get(
    "https://api.pexels.com/videos/search",
    headers=headers,
    params=params,
    timeout=30
)
resp.raise_for_status()

data = resp.json()
videos = data.get("videos", [])
if not videos:
    raise RuntimeError("Pexels không trả về video nào")

video = videos[0]
video_files = video.get("video_files", [])
if not video_files:
    raise RuntimeError("Video đầu tiên không có video_files")

mp4_files = [vf for vf in video_files if vf.get("file_type") == "video/mp4"]
if not mp4_files:
    raise RuntimeError("Không tìm thấy file mp4 nào")

def score(vf):
    w = vf.get("width", 99999)
    h = vf.get("height", 99999)
    portrait_penalty = 0 if h >= w else 1
    size_penalty = abs(w - 720) + abs(h - 1280)
    return (portrait_penalty, size_penalty)

best_file = sorted(mp4_files, key=score)[0]
download_url = best_file["link"]

print("Selected file:")
print(best_file)

out_path = OUTPUT_DIR / "pexels_test.mp4"

with requests.get(download_url, stream=True, timeout=60) as r:
    r.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

print(f"Saved to: {out_path}")