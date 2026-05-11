import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise RuntimeError("Missing OPENROUTER_API_KEY")

model_name = os.getenv("OPENROUTER_QUOTE_FALLBACK_MODEL", "tencent/hy3-preview:free")

prompt = """
Return only valid JSON. No markdown.

Analyze this quote for a short Vietnamese vertical quote video.

Quote: "Never tell the truth to people who are not worthy of it."
Author: Mark Twain

Return this JSON shape:
{
  "vi_short": "...",
  "caption": "...",
  "mood": "...",
  "music_mood_tag": "...",
  "scene_plan": [
    {
      "scene_id": 1,
      "scene_role": "setup",
      "visual_goal": "...",
      "queries_giphy": ["...", "..."]
    },
    {
      "scene_id": 2,
      "scene_role": "payoff",
      "visual_goal": "...",
      "queries_giphy": ["...", "..."]
    }
  ]
}
""".strip()

response = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/sangbate258/daily-quotes-bot",
        "X-Title": "daily-quotes-bot",
    },
    json={
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 1800,
    },
    timeout=90,
)

print("status:", response.status_code)
print(response.text)

response.raise_for_status()
content = response.json()["choices"][0]["message"]["content"]
parsed = json.loads(content)
print("\nparsed ok:")
print(json.dumps(parsed, ensure_ascii=False, indent=2))