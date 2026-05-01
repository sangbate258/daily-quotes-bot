from dotenv import load_dotenv
import os
from google import genai

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise RuntimeError("Thiếu GOOGLE_API_KEY trong file .env")

client = genai.Client(api_key=api_key)

prompt = """
Hãy dịch câu quote sau sang tiếng Việt thật tự nhiên, ngắn gọn, thấm và hợp làm video:
Everything is hard before it is easy.
Chỉ trả về đúng 1 câu tiếng Việt, không giải thích.
"""

response = client.models.generate_content(
    model="gemma-4-31b-it",
    contents=prompt,
)

print(response.text)