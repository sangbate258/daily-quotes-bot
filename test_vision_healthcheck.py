import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise RuntimeError("Missing GOOGLE_API_KEY")

client = genai.Client(api_key=api_key)

image_url = "https://media.giphy.com/media/h8sQ2si8AOmVnN8ufU/giphy.gif"
image_path = Path("vision_test.gif")

if not image_path.exists():
    response = requests.get(image_url, timeout=30)
    response.raise_for_status()
    image_path.write_bytes(response.content)

models = [
    os.getenv("GOOGLE_MODEL_NAME", "gemma-4-31b-it"),
    os.getenv("GOOGLE_VISION_TEST_ALT_MODEL", "gemini-2.5-flash"),
]

prompt = """
Return only valid JSON:
{
  "contains_book": true/false,
  "contains_cartoon_or_sticker": true/false,
  "short_description": "..."
}
"""

for model_name in models:
    print(f"\n[VISION HEALTHCHECK] model={model_name}")
    try:
        uploaded = client.files.upload(file=str(image_path))
        result = client.models.generate_content(
            model=model_name,
            contents=[uploaded, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            ),
        )
        print(result.text)
    except Exception as exc:
        print(f"[VISION HEALTHCHECK FAIL] {exc}")