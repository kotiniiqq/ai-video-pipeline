"""Subtitles from the narration timeline, and the thumbnail."""
import re

from fastapi import APIRouter
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from . import config, media

LINE = 42
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
router = APIRouter()


def _lines(text: str) -> list[str]:
    """Greedy wrap to LINE characters; a word longer than a line is cut."""
    words = []
    for w in text.split():
        words += [w[i:i + LINE] for i in range(0, len(w), LINE)]
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > LINE:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def cues(paragraphs: list[dict]) -> list[dict]:
    """Two-line cues; each paragraph's time is spread over its text by length."""
    out = []
    for p in paragraphs:
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", p["text"].strip()) if s]
        chunks = []
        for s in sentences:
            lines = _lines(s)
            chunks += ["\n".join(lines[i:i + 2]) for i in range(0, len(lines), 2)]
        if not chunks:
            continue
        weights = [len(c) for c in chunks]
        t, start, dur = p["start_s"], p["start_s"], p["duration_s"]
        for i, (chunk, w) in enumerate(zip(chunks, weights)):
            end = start + dur if i == len(chunks) - 1 else t + dur * w / sum(weights)
            out.append({"start": round(t, 3), "end": round(end, 3), "text": chunk})
            t = end
    return out


def _ts(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(paragraphs: list[dict], out: str) -> dict:
    dst = media.output_path(out)
    items = cues(paragraphs)
    with open(dst, "w", encoding="utf-8") as f:
        for i, c in enumerate(items, 1):
            f.write(f"{i}\n{_ts(c['start'])} --> {_ts(c['end'])}\n{c['text']}\n\n")
    return {"path": dst, "cues": len(items)}


def _wrap_px(draw, text: str, font, width: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        trial = f"{cur} {w}".strip()
        if cur and draw.textlength(trial, font=font) > width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def thumbnail(image_path: str, text: str, out: str) -> dict:
    """Cover-crop to 1280x720, darken the left side, set the title there in up to three lines."""
    w, h = config.RENDER_W, config.RENDER_H
    img = Image.open(media.inside_shared(image_path)).convert("RGB")
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    img = img.crop((left, top, left + w, top + h))

    shade = Image.new("L", (w, h))
    sd = ImageDraw.Draw(shade)
    for x in range(w):
        sd.line([(x, 0), (x, h)], fill=int(215 * max(0.0, 1 - x / (w * 0.65))))
    img = Image.composite(Image.new("RGB", (w, h)), img, shade)

    draw = ImageDraw.Draw(img)
    box_w = int(w * 0.55)
    text = " ".join(text.split()).upper()
    for size in range(96, 35, -4):
        font = ImageFont.truetype(FONT, size)
        lines = _wrap_px(draw, text, font, box_w)
        if len(lines) <= 3:
            break
    if len(lines) > 3:  # still too long at the smallest size: keep three lines and mark the cut
        lines = lines[:3]
        while lines[2] and draw.textlength(lines[2] + "…", font=font) > box_w:
            lines[2] = lines[2].rsplit(" ", 1)[0] if " " in lines[2] else lines[2][:-1]
        lines[2] += "…"
    line_h = int(font.size * 1.15)
    y = (h - line_h * len(lines)) // 2
    for line in lines:
        draw.text((64, y), line, font=font, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
        y += line_h

    dst = media.output_path(out)
    img.save(dst, "JPEG", quality=90)
    return {"path": dst, "width": w, "height": h, "lines": len(lines), "font_size": font.size}


class Paragraph(BaseModel):
    text: str
    start_s: float
    duration_s: float


class SubtitlesReq(BaseModel):
    paragraphs: list[Paragraph]
    out: str


class ThumbnailReq(BaseModel):
    image_path: str
    text: str
    out: str


@router.post("/subtitles")
def subtitles_route(req: SubtitlesReq):
    return write_srt([p.model_dump() for p in req.paragraphs], req.out)


@router.post("/thumbnail")
def thumbnail_route(req: ThumbnailReq):
    return thumbnail(req.image_path, req.text, req.out)
