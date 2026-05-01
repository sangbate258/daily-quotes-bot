from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

W, H = 1080, 1920
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

QUOTE = "Mọi thứ lúc đầu đều khó, rồi sẽ dễ dần khi bạn quen với nó."
AUTHOR = "Johann Wolfgang von Goethe"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]

def load_font(size: int):
    for path in FONT_CANDIDATES:
        p = Path(path)
        if p.exists():
            return ImageFont.truetype(str(p), size=size)
    return ImageFont.load_default()

quote_font = load_font(68)
author_font = load_font(42)

img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

max_text_width = 760

def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current = []

    for word in words:
        test_line = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]

    if current:
        lines.append(" ".join(current))

    return lines

quote_lines = wrap_text(QUOTE, quote_font, max_text_width)
author_line = f"— {AUTHOR}"

quote_line_gap = 18
author_gap = 70

quote_line_heights = []
for line in quote_lines:
    bbox = draw.textbbox((0, 0), line, font=quote_font)
    quote_line_heights.append(bbox[3] - bbox[1])

author_bbox = draw.textbbox((0, 0), author_line, font=author_font)
author_h = author_bbox[3] - author_bbox[1]

quote_block_h = sum(quote_line_heights) + quote_line_gap * (len(quote_lines) - 1)
total_block_h = quote_block_h + author_gap + author_h

start_y = (H - total_block_h) // 2

def draw_centered_text(text, y, font, fill=(255, 255, 255, 255), shadow=True):
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    x = (W - text_w) // 2

    if shadow:
        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 140))
    draw.text((x, y), text, font=font, fill=fill)

y = start_y
for i, line in enumerate(quote_lines):
    draw_centered_text(line, y, quote_font, fill=(255, 255, 255, 255))
    y += quote_line_heights[i] + quote_line_gap

y += author_gap
draw_centered_text(author_line, y, author_font, fill=(230, 230, 230, 255))

# save transparent overlay
png_path = OUTPUT_DIR / "quote_card_test.png"
img.save(png_path)

# save preview on black background so you can inspect easily
preview = Image.new("RGB", (W, H), (0, 0, 0))
preview.paste(img, (0, 0), img)
jpg_path = OUTPUT_DIR / "quote_card_test_preview.jpg"
preview.save(jpg_path, quality=95)

print("Saved:")
print(png_path)
print(jpg_path)