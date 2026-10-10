"""Offline providers: no keys, no network. Piper speaks, Pillow paints, FFmpeg animates."""
import hashlib
import logging
import os
import random
import tempfile
import wave

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import config, media, render
from . import demo_text
from .base import TASKS, AudioResult, ClipResult, ImageResult, LlmResult

log = logging.getLogger("providers.demo")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _rng(text: str) -> random.Random:
    return random.Random(hashlib.sha256(text.encode()).hexdigest())


class DemoProviders:
    name = "demo"

    def __init__(self):
        self._voice = None

    # -- text ---------------------------------------------------------------------------------
    def llm(self, task: str, payload: dict, repair: dict | None = None) -> LlmResult:
        if task not in TASKS:
            raise media.InputError(f"unknown task {task!r}; expected one of {', '.join(TASKS)}")
        if task == "script":
            output = demo_text.script(payload["topic"])
        elif task == "storyboard":
            output = demo_text.storyboard(payload["paragraphs"], float(payload.get("ai_share_max", 0.3)))
        else:
            output = demo_text.packaging(payload["topic"], payload["script_text"])
        return LlmResult(output=output, model=f"demo-{task}", usd=0.0)

    # -- voice --------------------------------------------------------------------------------
    def _piper(self):
        model = os.path.join(config.MODELS_DIR, "piper", "voice.onnx")
        if self._voice is None and os.path.isfile(model):
            from piper import PiperVoice
            self._voice = PiperVoice.load(model)
        return self._voice

    def tts(self, text: str, out: str) -> AudioResult:
        dst = media.output_path(out)
        voice = self._piper()
        if voice is not None:
            with wave.open(dst, "wb") as wav:
                voice.synthesize_wav(text, wav)
        else:  # no voice model (unit tests outside the image): a tone as long as speech would be
            seconds = max(1.0, len(text) / 15)
            media.run_ffmpeg("-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=22050:duration={seconds:.2f}",
                             "-af", "volume=0.3", dst)
        return AudioResult(path=dst, duration_s=round(media.duration(dst), 3))

    # -- pictures -----------------------------------------------------------------------------
    def image(self, prompt: str, out: str, width: int = 1280, height: int = 720) -> ImageResult:
        """A synthetic frame: two-colour gradient, soft shapes, and the prompt as a caption."""
        rng = _rng(prompt)
        a = [rng.randint(20, 120) for _ in range(3)]
        b = [rng.randint(120, 235) for _ in range(3)]
        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)
        for y in range(height):
            t = y / max(height - 1, 1)
            draw.line([(0, y), (width, y)], fill=tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3)))
        layer = Image.new("RGBA", (width, height))
        ld = ImageDraw.Draw(layer)
        for _ in range(9):
            x, y, r = rng.randint(0, width), rng.randint(0, height), rng.randint(height // 10, height // 3)
            colour = tuple(rng.randint(0, 255) for _ in range(3)) + (rng.randint(50, 120),)
            (ld.ellipse if rng.random() < 0.6 else ld.rectangle)([x - r, y - r, x + r, y + r], fill=colour)
        img = Image.alpha_composite(img.convert("RGBA"), layer.filter(ImageFilter.GaussianBlur(6))).convert("RGB")
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(FONT, max(18, height // 30))
        draw.text((32, height - height // 12), f"demo frame: {prompt[:90]}", font=font, fill=(255, 255, 255),
                  stroke_width=2, stroke_fill=(0, 0, 0))
        dst = media.output_path(out)
        img.save(dst)
        return ImageResult(path=dst, source={"license": "generated", "author": "demo provider", "url": None})

    def clip(self, image_path: str, prompt: str, duration_s: float, out: str) -> ClipResult:
        """Stands in for image-to-video: a camera move plus film grain, so QC sees real motion."""
        dst = media.output_path(out)
        move = _rng(prompt + image_path).choice(["zoom_in", "zoom_out", "pan_left", "pan_right"])
        with tempfile.TemporaryDirectory(dir=os.path.dirname(dst)) as tmp:
            raw = render.kenburns(image_path, os.path.join(tmp, "raw.mp4"), duration_s, move=move)["path"]
            media.run_ffmpeg("-i", raw, "-vf", "noise=alls=10:allf=t+u", *render.VIDEO_OUT, "-an", dst)
        return ClipResult(path=dst, duration_s=round(media.duration(dst), 3))

    def stills(self, query: str, out_dir: str, limit: int = 3) -> list[ImageResult]:
        results = []
        for i in range(limit):
            res = self.image(f"{query} #{i + 1}", os.path.join(out_dir, f"still_{i + 1}.png"))
            res.source = {"license": "CC0", "author": "demo provider (generated)", "url": None}
            results.append(res)
        return results

    def notify(self, text: str) -> bool:
        log.info("notify (demo, not sent): %s", text)
        return False
