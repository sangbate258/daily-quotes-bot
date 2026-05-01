from __future__ import annotations

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GIPHY_API_KEY")
if not API_KEY:
    raise RuntimeError("Thiếu GIPHY_API_KEY trong file .env")

QUERY = "be yourself crowd identity"

url = "https://api.giphy.com/v1/gifs/search"
params = {
    "api_key": API_KEY,
    "q": QUERY,
    "limit": 5,
    "rating": "g",
    "lang": "en",
}

resp = requests.get(url, params=params, timeout=30)
resp.raise_for_status()

data = resp.json()

print("Status OK")
print(f"Found: {len(data.get('data', []))} results\n")

preview = []
for item in data.get("data", [])[:5]:
    preview.append({
        "id": item.get("id"),
        "title": item.get("title"),
        "url": item.get("url"),
    })

print(json.dumps(preview, ensure_ascii=False, indent=2))