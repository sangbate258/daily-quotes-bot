import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")
model_name = os.getenv("GOOGLE_MODEL_NAME", "gemma-4-31b-it")

if not api_key:
    raise RuntimeError("Missing GOOGLE_API_KEY")

client = genai.Client(api_key=api_key)

prompt = "Reply with only this JSON: {\"ok\": true}"

print(f"[AI HEALTHCHECK] model={model_name}")

response = client.models.generate_content(
    model=model_name,
    contents=prompt,
)

print(response.text)