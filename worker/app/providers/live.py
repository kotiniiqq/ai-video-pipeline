"""Real providers, used when MODE=live and the matching keys are set in .env.

OpenRouter (LLM), ElevenLabs (voice), fal.ai (images and image-to-video), Openverse (openly licensed
stills, no key), Telegram (notifications). A missing key fails only the call that needs it.
"""
import base64
import json
import mimetypes
import os
import re
import tempfile
import time
from typing import Callable

import httpx

from .. import media, render
from .base import TASKS, AudioResult, ClipResult, ImageResult, LlmResult, ProviderError
from .http import Http

PROMPTS = {
    "script": (
        "You write narration for short documentary videos. Return only a JSON object: "
        '{"sources": [{"id": 1, "title": "...", "url": "..."}], '
        '"paragraphs": [{"role": "intro"|"body"|"outro", "text": "...", "source_ids": [1]}]}. '
        "Rules: 6 to 10 paragraphs; the first is the intro, the last is the outro, all others are body; "
        "every body paragraph cites at least one source id from your list and states only facts that source "
        "supports; plain spoken English, no lists, no headings; 250 to 1400 words in total. "
        "If you are unsure of a fact, leave it out."
    ),
    "storyboard": (
        "You plan the visuals of a narrated video. Input: paragraphs with their spoken duration in seconds. "
        'Return only a JSON object: {"shots": [{"paragraph": <idx>, "kind": "ai"|"still", "duration_s": <s>, '
        '"prompt": "...", "query": "..."}]}. Rules: every paragraph gets 1 to 4 shots whose durations add up '
        "to the paragraph's duration; each shot lasts 1.5 to 12 seconds; 'ai' shots (generated video) may "
        "take at most ai_share_max of the total time, the rest are 'still' (real photos found with `query`, "
        "2 to 4 plain words); `prompt` describes the image to generate, concrete and visual."
    ),
    "packaging": (
        "You write titles and a description for a documentary video. Return only a JSON object: "
        '{"titles": [{"text": "...", "quote": "..."}], "description": "..."}. Give 3 titles under 70 '
        "characters; each `quote` is an exact phrase copied from the script that the title is based on. "
        "The description is 2 to 4 sentences, no hashtags, no claims beyond the script."
    ),
}
OPENVERSE_LICENSES = {"pdm": "Public Domain Mark", "cc0": "CC0", "by": "CC BY", "by-sa": "CC BY-SA"}


def first_json_object(text: str) -> dict | None:
    """The first JSON object in a model reply, tolerating code fences and prose around it."""
    decoder = json.JSONDecoder()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1) + "\n" + text
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)  # the JSON parser handles strings and escapes
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    return None


class LiveProviders:
    name = "live"

    def __init__(self, client: httpx.Client | None = None, env: dict | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.env = os.environ if env is None else env
        self.http = Http(client, sleep)
        self.sleep = sleep

    def _key(self, name: str, what: str) -> str:
        value = self.env.get(name, "").strip()
        if not value:
            raise ProviderError(400, f"{what} needs {name} in .env (or run with MODE=demo)")
        return value

    # -- text ---------------------------------------------------------------------------------
    def llm(self, task: str, payload: dict, repair: dict | None = None) -> LlmResult:
        if task not in TASKS:
            raise media.InputError(f"unknown task {task!r}; expected one of {', '.join(TASKS)}")
        key = self._key("OPENROUTER_API_KEY", "the LLM")
        model = self.env.get("LLM_MODEL", "anthropic/claude-sonnet-4.5")
        messages = [{"role": "system", "content": PROMPTS[task]},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        if repair:
            messages.append({"role": "user", "content": (
                "Your previous answer did not pass validation.\nPrevious answer:\n"
                f"{json.dumps(repair.get('previous'), ensure_ascii=False)}\nProblems:\n- "
                + "\n- ".join(map(str, repair.get("errors", []))) + "\nReturn the corrected JSON object only.")})
        r = self.http.request("POST", "https://openrouter.ai/api/v1/chat/completions", "OpenRouter",
                              headers={"Authorization": f"Bearer {key}"},
                              json={"model": model, "messages": messages, "temperature": 0.4,
                                    "response_format": {"type": "json_object"}})
        data = r.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        output = first_json_object(content)
        if output is None:
            raise ProviderError(502, f"the model returned no JSON object: …{content[-300:]}")
        return LlmResult(output=output, model=model, usd=float((data.get("usage") or {}).get("cost") or 0.0))

    # -- voice --------------------------------------------------------------------------------
    def tts(self, text: str, out: str) -> AudioResult:
        key = self._key("ELEVENLABS_API_KEY", "the voice")
        voice = self._key("ELEVENLABS_VOICE_ID", "the voice")
        dst = media.output_path(out)
        r = self.http.request("POST", f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
                              "ElevenLabs", headers={"xi-api-key": key},
                              json={"text": text, "model_id": self.env.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")})
        with open(dst, "wb") as f:
            f.write(r.content)
        return AudioResult(path=dst, duration_s=round(media.duration(dst), 3), usd=len(text) * 0.0001)

    # -- pictures -----------------------------------------------------------------------------
    def image(self, prompt: str, out: str, width: int = 1280, height: int = 720) -> ImageResult:
        key = self._key("FAL_KEY", "image generation")
        dst = media.output_path(out)
        r = self.http.request("POST", "https://fal.run/fal-ai/flux/schnell", "fal.ai",
                              headers={"Authorization": f"Key {key}"},
                              json={"prompt": prompt, "image_size": {"width": width, "height": height}, "num_images": 1})
        self.http.download(r.json()["images"][0]["url"], dst, "fal.ai image download")
        return ImageResult(path=dst, usd=0.003, source={"license": "generated", "author": "fal-ai/flux/schnell", "url": None})

    def clip(self, image_path: str, prompt: str, duration_s: float, out: str) -> ClipResult:
        key = self._key("FAL_KEY", "video generation")
        src = media.inside_shared(image_path)
        dst = media.output_path(out)
        mime = mimetypes.guess_type(src)[0] or "image/png"
        data_uri = f"data:{mime};base64,{base64.b64encode(open(src, 'rb').read()).decode()}"
        headers = {"Authorization": f"Key {key}"}
        model = self.env.get("FAL_VIDEO_MODEL", "fal-ai/kling-video/v2.1/standard/image-to-video")
        sub = self.http.request("POST", f"https://queue.fal.run/{model}", "fal.ai queue", headers=headers,
                                json={"prompt": prompt, "image_url": data_uri, "duration": "5" if duration_s <= 5 else "10"}).json()
        deadline = time.monotonic() + 600
        while True:
            status = self.http.request("GET", sub["status_url"], "fal.ai status", headers=headers).json().get("status")
            if status == "COMPLETED":
                break
            if status not in ("IN_QUEUE", "IN_PROGRESS"):
                raise ProviderError(502, f"fal.ai job {sub.get('request_id')} ended with status {status}")
            if time.monotonic() > deadline:
                raise ProviderError(502, f"fal.ai job {sub.get('request_id')} took longer than 10 minutes")
            self.sleep(5)
        url = self.http.request("GET", sub["response_url"], "fal.ai result", headers=headers).json()["video"]["url"]
        with tempfile.TemporaryDirectory(dir=os.path.dirname(dst)) as tmp:
            raw = self.http.download(url, os.path.join(tmp, "raw.mp4"), "fal.ai video download")
            render.fit(raw, dst, duration_s)
        return ClipResult(path=dst, duration_s=round(media.duration(dst), 3), usd=0.25 if duration_s <= 5 else 0.5)

    def stills(self, query: str, out_dir: str, limit: int = 3) -> list[ImageResult]:
        r = self.http.request("GET", "https://api.openverse.org/v1/images/", "Openverse",
                              params={"q": query, "license": ",".join(OPENVERSE_LICENSES), "aspect_ratio": "wide",
                                      "page_size": 20, "mature": "false"},
                              headers={"User-Agent": "ai-video-pipeline (demo project)"})
        items = []
        for hit in r.json().get("results", []):
            lic = (hit.get("license") or "").lower()
            if lic not in OPENVERSE_LICENSES or (hit.get("width") or 0) < 1024:
                continue  # double check: the query filters licenses, but the result decides
            ext = os.path.splitext(hit["url"].split("?")[0])[1] or ".jpg"
            dst = media.output_path(os.path.join(out_dir, f"still_{len(items) + 1}{ext}"))
            try:
                self.http.download(hit["url"], dst, "Openverse image download")
            except ProviderError:
                continue
            items.append(ImageResult(path=dst, source={"license": OPENVERSE_LICENSES[lic],
                                                       "author": hit.get("creator") or "unknown",
                                                       "url": hit.get("foreign_landing_url") or hit["url"]}))
            if len(items) >= limit:
                break
        return items

    def notify(self, text: str) -> bool:
        token, chat = self.env.get("TELEGRAM_BOT_TOKEN", "").strip(), self.env.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat:
            return False
        self.http.request("POST", f"https://api.telegram.org/bot{token}/sendMessage", "Telegram",
                          json={"chat_id": chat, "text": text[:4000]})
        return True
