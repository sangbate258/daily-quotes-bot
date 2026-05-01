from __future__ import annotations

from pathlib import Path
import json
import math
import re
import shutil
import subprocess
import unicodedata
from typing import Any

from PIL import Image, ImageDraw, ImageFont


# Renderer V5.1:
# - Native vertical 9:16 for Shorts/Reels/TikTok.
# - Sample-style: pastel background, black bold quote, small faint watermark,
#   GIF/meme below text, quote reveals in first 3-5 seconds then stays.
# - Author appears shortly after quote completes and stays to the end.
# - Text reveal is time-based, independent from media scenes.
# - Media transition is very short/subtle, not cinematic.
WIDTH = 1080
HEIGHT = 1920
FPS = 24

BASE_DIR = Path(".")
OUTPUT_DIR = BASE_DIR / "output"
TEMP_RENDER_DIR = BASE_DIR / "temp_render"
TEMP_RENDER_DIR.mkdir(exist_ok=True)

FINAL_FRAMES_DIR = TEMP_RENDER_DIR / "final_frames_v51"
MEDIA_FRAMES_DIR = TEMP_RENDER_DIR / "media_frames_v51"

TEXT_AREA_MAX_WIDTH = 850
TEXT_AREA_MAX_HEIGHT = 660

# Sample-like layout zones.
TEXT_TOP_DEFAULT = 250
MEDIA_MAX_W = 760
MEDIA_MAX_H = 560
MEDIA_MIN_Y = 930
MEDIA_MAX_Y = 1160

WATERMARK_TEXT = "trichdanmoingay"
WATERMARK_ALPHA = 55

REVEAL_START_T = 0.35
AUTHOR_FADE_DURATION = 0.55
MEDIA_XFADE_DURATION = 0.20

PASTEL_PALETTES = {
    "healing": ["#F7E3E6", "#E7F1EA", "#F8EFD8", "#EDE7F6"],
    "hopeful": ["#FFF0C9", "#E8F4F8", "#F7E5EE", "#E8F3DA"],
    "wisdom": ["#F2E8D8", "#E7EEF8", "#EFE7F8", "#F8EAD8"],
    "motivation": ["#FFE1C7", "#FFF1B8", "#E4F2DD", "#E7EEF8"],
    "love": ["#F8DDE8", "#F7E6E6", "#FFE8D6", "#F1E5FF"],
    "sad": ["#E5E8EF", "#EDE7F2", "#E2EDF0", "#F1EDE8"],
    "light-humor": ["#FFF2A8", "#DFF4CE", "#FFD9C9", "#DCEBFF"],
    "chill": ["#E9F2F2", "#EFE8DC", "#E7ECF7", "#F3E8EF"],
    "reflective": ["#F1E9DD", "#E8ECF1", "#EEE4F0", "#E7F0E7"],
    # Newer mood tags can map to sample-like bright palettes.
    "joyful": ["#FFF2A8", "#FFD9C9", "#DFF4CE", "#DCEBFF"],
    "playful": ["#FFF2A8", "#FFD9C9", "#E7F5D8", "#E7ECFF"],
    "upbeat": ["#FFE1C7", "#FFF1B8", "#DFF4CE", "#DCEBFF"],
    "funny-light": ["#FFF2A8", "#FFD9C9", "#DFF4CE", "#EADFFF"],
    "cute": ["#F8DDE8", "#FFF0C9", "#DFF4CE", "#DCEBFF"],
}

DEFAULT_PALETTE = ["#F4E6D8", "#E8F0E8", "#EFE6F4", "#FFF0C9"]

PROTECTED_PHRASES = [
    ("chấp", "nhận"), ("tồi", "tệ"), ("khờ", "khạo"), ("con", "người"),
    ("tình", "yêu"), ("bóng", "tối"), ("ánh", "sáng"), ("chính", "mình"),
    ("bản", "thân"), ("cuộc", "sống"), ("vũ", "trụ"), ("trái", "tim"),
    ("thành", "công"), ("thất", "bại"), ("cô", "đơn"), ("hy", "vọng"),
    ("tha", "thứ"), ("bao", "dung"), ("thấu", "hiểu"), ("mạnh", "mẽ"),
    ("yếu", "đuối"), ("hạnh", "phúc"), ("đau", "khổ"), ("tự", "do"),
    ("tự", "tin"), ("tự", "trọng"), ("tự", "yêu"), ("trưởng", "thành"),
    ("kiên", "nhẫn"), ("kỷ", "luật"), ("giá", "trị"), ("thiên", "đường"),
    ("khiêu", "vũ"), ("nhìn", "thấy"), ("lắng", "nghe"),
]

UNSAFE_ENDINGS = {
    "và", "hoặc", "nhưng", "mà", "vì", "nếu", "khi", "thì", "là", "của",
    "sự", "niềm", "nỗi", "một", "những", "các", "rất", "quá", "đã", "đang",
    "sẽ", "không", "chỉ", "tình", "ánh", "bóng", "con", "cuộc", "tự", "giá",
}


def run_ffmpeg(cmd: list[str]) -> None:
    print("\n[FFMPEG CMD]")
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


def load_timeline() -> dict:
    timeline_path = OUTPUT_DIR / "timeline_test.json"
    if not timeline_path.exists():
        raise RuntimeError("Không tìm thấy output/timeline_test.json")
    return json.loads(timeline_path.read_text(encoding="utf-8"))


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def remove_vietnamese_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def norm_word(word: str) -> str:
    word = word.lower().strip()
    word = re.sub(r"^[^\wÀ-ỹ]+|[^\wÀ-ỹ]+$", "", word, flags=re.UNICODE)
    return remove_vietnamese_accents(word)


def hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    hex_color = hex_color.strip().lstrip("#")
    if len(hex_color) != 6:
        return (244, 230, 216, alpha)
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
        alpha,
    )


def load_font(size: int, *, bold: bool = False):
    candidates: list[str] = []
    if bold:
        candidates.extend([
            r"C:\Windows\Fonts\seguisb.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
        ])

    candidates.extend([
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ])

    for path in candidates:
        p = Path(path)
        if p.exists():
            return ImageFont.truetype(str(p), size=size)

    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\n", " ").split()).strip()


def tokenize_words_with_punctuation(text: str) -> list[str]:
    return normalize_text(text).split()


def build_protected_units(text: str) -> list[str]:
    words = tokenize_words_with_punctuation(text)
    units: list[str] = []
    protected = {(norm_word(a), norm_word(b)) for a, b in PROTECTED_PHRASES}

    i = 0
    while i < len(words):
        if i + 1 < len(words):
            pair = (norm_word(words[i]), norm_word(words[i + 1]))
            if pair in protected:
                units.append(f"{words[i]} {words[i + 1]}")
                i += 2
                continue
        units.append(words[i])
        i += 1

    fixed: list[str] = []
    i = 0
    while i < len(units):
        unit = units[i]
        while i + 1 < len(units) and norm_word(unit.split()[-1]) in UNSAFE_ENDINGS:
            i += 1
            unit = f"{unit} {units[i]}"
        fixed.append(unit)
        i += 1

    return fixed


def choose_palette(mood: str) -> list[str]:
    key = (mood or "").strip().lower()
    return PASTEL_PALETTES.get(key, DEFAULT_PALETTE)


def layout_units_into_lines(draw: ImageDraw.ImageDraw, units: list[str], font, max_width: int) -> list[list[str]]:
    lines: list[list[str]] = []
    current: list[str] = []

    for unit in units:
        test = " ".join(current + [unit])
        w, _ = text_size(draw, test, font)

        if w <= max_width or not current:
            current.append(unit)
        else:
            lines.append(current)
            current = [unit]

    if current:
        lines.append(current)

    return lines


def fit_layout_for_full_quote(draw: ImageDraw.ImageDraw, units: list[str]):
    for size in [74, 70, 66, 62, 58, 54, 50, 46, 42]:
        font = load_font(size, bold=True)
        line_gap = max(9, int(size * 0.16))
        lines = layout_units_into_lines(draw, units, font, TEXT_AREA_MAX_WIDTH)
        heights = [text_size(draw, " ".join(line), font)[1] for line in lines]
        block_h = sum(heights) + line_gap * max(0, len(lines) - 1)

        if block_h <= TEXT_AREA_MAX_HEIGHT and len(lines) <= 8:
            return font, lines, line_gap, block_h

    font = load_font(40, bold=True)
    line_gap = 8
    lines = layout_units_into_lines(draw, units, font, TEXT_AREA_MAX_WIDTH)
    heights = [text_size(draw, " ".join(line), font)[1] for line in lines]
    block_h = sum(heights) + line_gap * max(0, len(lines) - 1)
    return font, lines, line_gap, block_h


def get_line_height(draw: ImageDraw.ImageDraw, line_units: list[str], font) -> int:
    text = " ".join(line_units) if line_units else " "
    _, h = text_size(draw, text, font)
    return h


def build_unit_char_spans(units: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cur = 0
    for i, unit in enumerate(units):
        start = cur
        cur += len(unit)
        spans.append((start, cur))
        if i < len(units) - 1:
            cur += 1
    return spans


def draw_typewriter_text(
    draw: ImageDraw.ImageDraw,
    *,
    units: list[str],
    lines: list[list[str]],
    font,
    x: int,
    y: int,
    line_gap: int,
    reveal_chars: float,
    fill=(22, 22, 22, 255),
) -> int:
    spans = build_unit_char_spans(units)
    unit_to_span = {idx: span for idx, span in enumerate(spans)}

    unit_index = 0
    current_y = y
    space_w, _ = text_size(draw, " ", font)

    for line_units in lines:
        current_x = x
        line_h = get_line_height(draw, line_units, font)

        for unit in line_units:
            start, _ = unit_to_span[unit_index]
            visible_count = max(0, min(len(unit), int(math.floor(reveal_chars - start))))

            if visible_count > 0:
                visible_text = unit[:visible_count]
                draw.text((current_x, current_y), visible_text, font=font, fill=fill)

            unit_w, _ = text_size(draw, unit, font)
            current_x += unit_w + space_w
            unit_index += 1

        current_y += line_h + line_gap

    return current_y


def draw_watermark(draw: ImageDraw.ImageDraw) -> None:
    font = load_font(26, bold=True)
    w, h = text_size(draw, WATERMARK_TEXT, font)
    x = (WIDTH - w) // 2
    y = 88
    draw.text((x, y), WATERMARK_TEXT, font=font, fill=(22, 22, 22, WATERMARK_ALPHA))


def paste_media_centered(base: Image.Image, media_frame: Image.Image, *, center_x: int, y: int, alpha: float) -> None:
    media = media_frame.convert("RGBA")
    x = int(center_x - media.width / 2)

    if alpha < 1:
        a = media.getchannel("A")
        a = a.point(lambda p: int(p * max(0.0, min(1.0, alpha))))
        media.putalpha(a)

    base.alpha_composite(media, dest=(x, int(y)))


def get_quote_reveal_end(total_duration: float, total_chars: int) -> float:
    """
    Match samples: quote finishes early, usually 3-5 seconds.
    """
    if total_chars <= 70:
        return 3.5
    if total_chars <= 115:
        return 4.3
    return 5.0


def extract_media_frames(scene: dict[str, Any], scene_index: int, duration: float) -> list[Path]:
    media = scene.get("media") or {}
    media_path = media.get("local_path")
    if not media_path:
        raise RuntimeError(f"Scene {scene_index} thiếu media.local_path")

    out_dir = MEDIA_FRAMES_DIR / f"scene_{scene_index:02d}"
    clean_dir(out_dir)

    # Slight slowdown to reduce unpleasant fast loops.
    speed_factor = 1.18

    out_pattern = out_dir / "frame_%05d.png"
    vf = (
        f"setpts={speed_factor}*PTS,"
        f"scale={MEDIA_MAX_W}:{MEDIA_MAX_H}:force_original_aspect_ratio=decrease,"
        f"fps={FPS}"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-stream_loop", "-1",
        "-i", str(media_path),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        str(out_pattern),
    ]
    run_ffmpeg(cmd)

    frames = sorted(out_dir.glob("frame_*.png"))
    if not frames:
        raise RuntimeError(f"Không extract được frame cho scene {scene_index}: {media_path}")

    return frames


def prepare_scene_frame_bank(scenes: list[dict[str, Any]], total_duration: float) -> list[dict[str, Any]]:
    clean_dir(MEDIA_FRAMES_DIR)
    bank: list[dict[str, Any]] = []

    for idx, scene in enumerate(scenes, start=1):
        start = float(scene.get("start", 0))
        end = float(scene.get("end", total_duration))
        duration = max(0.5, end - start + MEDIA_XFADE_DURATION * 2)
        frames = extract_media_frames(scene, idx, duration)

        bank.append(
            {
                "scene": scene,
                "start": start,
                "end": end,
                "frames": frames,
            }
        )

    return bank


def open_frame(frames: list[Path], local_frame_index: int) -> Image.Image:
    if not frames:
        raise RuntimeError("Frame bank rỗng")
    idx = max(0, local_frame_index) % len(frames)
    return Image.open(frames[idx]).convert("RGBA")


def scene_index_for_time(bank: list[dict[str, Any]], t: float) -> int:
    for i, item in enumerate(bank):
        if float(item["start"]) <= t < float(item["end"]):
            return i
    return max(0, len(bank) - 1)


def media_layers_for_time(bank: list[dict[str, Any]], t: float) -> list[tuple[int, float]]:
    if not bank:
        return []

    current = scene_index_for_time(bank, t)
    item = bank[current]
    start = float(item["start"])
    end = float(item["end"])

    if current > 0 and start <= t < start + MEDIA_XFADE_DURATION:
        a = (t - start) / MEDIA_XFADE_DURATION
        return [(current - 1, 1.0 - a), (current, a)]

    if current + 1 < len(bank) and end - MEDIA_XFADE_DURATION <= t < end:
        a = (end - t) / MEDIA_XFADE_DURATION
        return [(current, a), (current + 1, 1.0 - a)]

    return [(current, 1.0)]


def get_media_frame_for_time(bank_item: dict[str, Any], t: float) -> Image.Image:
    start = float(bank_item["start"])
    local_t = max(0.0, t - start)
    local_idx = int(local_t * FPS)
    return open_frame(bank_item["frames"], local_idx)


def render_final_frames(
    *,
    timeline: dict[str, Any],
    units: list[str],
    lines: list[list[str]],
    font,
    line_gap: int,
    block_h: int,
    total_duration: float,
    scene_bank: list[dict[str, Any]],
) -> None:
    clean_dir(FINAL_FRAMES_DIR)

    quote_data = timeline["quote"]
    mood = quote_data.get("mood", "chill")
    author = quote_data.get("author", "")
    palette = choose_palette(mood)

    total_frames = max(1, int(round(total_duration * FPS)))
    total_chars = len(" ".join(units))

    reveal_end_t = min(total_duration - 2.0, get_quote_reveal_end(total_duration, total_chars))
    reveal_end_t = max(2.8, reveal_end_t)
    author_start_t = min(total_duration - 1.8, reveal_end_t + 0.45)

    text_x = (WIDTH - TEXT_AREA_MAX_WIDTH) // 2

    if block_h < 180:
        text_top = 310
    elif block_h < 340:
        text_top = 255
    else:
        text_top = TEXT_TOP_DEFAULT

    author_y = text_top + block_h + 34
    media_y = max(MEDIA_MIN_Y, min(MEDIA_MAX_Y, author_y + 76))

    author_font = load_font(34, bold=False)

    for frame_idx in range(total_frames):
        t = frame_idx / FPS

        # Samples often change background with GIF segments, but stay pastel.
        bg_hex = palette[min(len(palette) - 1, int(t // 3.5) % len(palette))]
        img = Image.new("RGBA", (WIDTH, HEIGHT), hex_to_rgba(bg_hex))
        draw = ImageDraw.Draw(img)

        draw_watermark(draw)

        if t <= REVEAL_START_T:
            reveal_chars = 0
        elif t >= reveal_end_t:
            reveal_chars = total_chars
        else:
            progress = (t - REVEAL_START_T) / max(0.1, reveal_end_t - REVEAL_START_T)
            # Smooth but still typewriter-like.
            reveal_chars = progress * total_chars

        draw_typewriter_text(
            draw,
            units=units,
            lines=lines,
            font=font,
            x=text_x,
            y=text_top,
            line_gap=line_gap,
            reveal_chars=reveal_chars,
            fill=(22, 22, 22, 255),
        )

        # Author appears soon after quote finishes, then stays.
        if author and t >= author_start_t:
            alpha = int(170 * min(1.0, (t - author_start_t) / AUTHOR_FADE_DURATION))
            if alpha > 0:
                draw.text(
                    (text_x, author_y),
                    f"- {author}",
                    font=author_font,
                    fill=(22, 22, 22, alpha),
                )

        for scene_i, alpha in media_layers_for_time(scene_bank, t):
            media_frame = get_media_frame_for_time(scene_bank[scene_i], t)
            paste_media_centered(img, media_frame, center_x=WIDTH // 2, y=media_y, alpha=alpha)

        out_path = FINAL_FRAMES_DIR / f"frame_{frame_idx + 1:05d}.png"
        img.convert("RGB").save(out_path, quality=95)


def encode_frames_with_music(total_duration: float, music_path: str) -> Path:
    final_out = OUTPUT_DIR / "rendered_test.mp4"
    frame_pattern = FINAL_FRAMES_DIR / "frame_%05d.png"

    cmd = [
        "ffmpeg",
        "-y",
        "-framerate", str(FPS),
        "-i", str(frame_pattern),
        "-stream_loop", "-1",
        "-i", str(music_path),
        "-t", f"{total_duration:.3f}",
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        str(final_out),
    ]
    run_ffmpeg(cmd)
    return final_out


def render_final_video(timeline: dict) -> Path:
    quote_data = timeline["quote"]
    time_data = timeline["timeline"]
    scenes = time_data["scenes"]
    music = timeline["music"]

    total_duration = float(time_data.get("total_duration") or 14.0)
    if total_duration <= 0:
        raise RuntimeError("total_duration không hợp lệ")
    if not scenes:
        raise RuntimeError("Timeline không có scene nào")

    quote_text = quote_data.get("vi_short") or quote_data.get("vi_full") or ""
    units = build_protected_units(quote_text)

    probe = Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, 0))
    probe_draw = ImageDraw.Draw(probe)
    font, lines, line_gap, block_h = fit_layout_for_full_quote(probe_draw, units)

    scene_bank = prepare_scene_frame_bank(scenes, total_duration)

    render_final_frames(
        timeline=timeline,
        units=units,
        lines=lines,
        font=font,
        line_gap=line_gap,
        block_h=block_h,
        total_duration=total_duration,
        scene_bank=scene_bank,
    )

    return encode_frames_with_music(total_duration, music["local_path"])


if __name__ == "__main__":
    timeline = load_timeline()
    out_path = render_final_video(timeline)
    print(f"\nRendered video saved to: {out_path}")
