"""Live providers against a mock transport: request shapes, parsing and error mapping. No network."""
import json
import os
import subprocess

import httpx
import pytest

from app import media
from app.providers.base import ProviderError
from app.providers.live import LiveProviders

ENV = {"OPENROUTER_API_KEY": "or-test", "ELEVENLABS_API_KEY": "el-test", "ELEVENLABS_VOICE_ID": "voice123",
       "FAL_KEY": "fal-test", "TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42"}


def media_bytes(shared, args, name):
    path = os.path.join(shared, name)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args, path], check=True)
    return open(path, "rb").read()


def providers(handler, env=ENV):
    calls = []

    def record(request):
        calls.append(request)
        return handler(request, len(calls))
    p = LiveProviders(client=httpx.Client(transport=httpx.MockTransport(record)), env=env, sleep=lambda s: None)
    return p, calls


def chat(content, cost=0.0123):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"cost": cost}})


def test_llm_request_shape_and_fenced_json():
    p, calls = providers(lambda r, n: chat('Sure!\n```json\n{"sources": [], "paragraphs": []}\n```'))
    res = p.llm("script", {"topic": "Lighthouses"})
    req = calls[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer or-test"
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system" and "Lighthouses" in body["messages"][1]["content"]
    assert res.output == {"sources": [], "paragraphs": []} and res.usd == 0.0123


def test_llm_repair_sends_previous_output_and_errors():
    p, calls = providers(lambda r, n: chat('{"shots": []}'))
    p.llm("storyboard", {"paragraphs": []}, repair={"previous": {"shots": [1]}, "errors": ["shot 1 too long"]})
    last = json.loads(calls[0].content)["messages"][-1]["content"]
    assert "shot 1 too long" in last and '"shots"' in last


def test_llm_prose_without_json_is_retryable_error():
    p, _ = providers(lambda r, n: chat("I cannot help with that request today."))
    with pytest.raises(ProviderError) as e:
        p.llm("script", {"topic": "x"})
    assert e.value.status == 502 and "cannot help" in str(e.value)


def test_rate_limit_is_retried():
    p, calls = providers(lambda r, n: httpx.Response(429) if n == 1 else chat('{"titles": [], "description": "d"}'))
    assert p.llm("packaging", {"topic": "x", "script_text": "y"}).output["description"] == "d"
    assert len(calls) == 2


def test_server_errors_give_up_after_retries():
    p, calls = providers(lambda r, n: httpx.Response(503))
    with pytest.raises(ProviderError) as e:
        p.llm("script", {"topic": "x"})
    assert e.value.status == 502 and len(calls) == 3


def test_bad_key_is_permanent():
    p, _ = providers(lambda r, n: httpx.Response(401, json={"error": "invalid key"}))
    with pytest.raises(ProviderError) as e:
        p.llm("script", {"topic": "x"})
    assert e.value.status == 400


def test_missing_key_is_a_clear_permanent_error():
    p, calls = providers(lambda r, n: chat("{}"), env={})
    with pytest.raises(ProviderError) as e:
        p.llm("script", {"topic": "x"})
    assert e.value.status == 400 and "OPENROUTER_API_KEY" in str(e.value) and not calls


def test_tts_elevenlabs(shared):
    audio = media_bytes(shared, ["-f", "lavfi", "-i", "sine=duration=1.5"], "src.mp3")
    p, calls = providers(lambda r, n: httpx.Response(200, content=audio))
    res = p.tts("Hello there.", os.path.join(shared, "out", "p0.mp3"))
    assert str(calls[0].url).startswith("https://api.elevenlabs.io/v1/text-to-speech/voice123")
    assert calls[0].headers["xi-api-key"] == "el-test"
    assert abs(res.duration_s - 1.5) < 0.1


def test_image_fal(shared):
    png = media_bytes(shared, ["-f", "lavfi", "-i", "testsrc2=size=1280x720", "-frames:v", "1"], "src.png")

    def handler(r, n):
        if r.url.host == "fal.run":
            return httpx.Response(200, json={"images": [{"url": "https://cdn.example/img.png"}]})
        return httpx.Response(200, content=png)
    p, calls = providers(handler)
    res = p.image("a harbour", os.path.join(shared, "i.png"))
    assert calls[0].headers["authorization"] == "Key fal-test"
    assert json.loads(calls[0].content)["prompt"] == "a harbour"
    assert os.path.getsize(res.path) == len(png) and res.source["license"] == "generated"


def test_clip_fal_queue_polls_until_done(shared, make_image):
    mp4 = media_bytes(shared, ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-t", "5",
                               "-pix_fmt", "yuv420p"], "src.mp4")

    def handler(r, n):
        url = str(r.url)
        if r.method == "POST":
            return httpx.Response(200, json={"request_id": "q1", "status_url": "https://queue.fal.run/s/q1",
                                             "response_url": "https://queue.fal.run/r/q1"})
        if url.endswith("/s/q1"):
            return httpx.Response(200, json={"status": "IN_PROGRESS" if n < 4 else "COMPLETED"})
        if url.endswith("/r/q1"):
            return httpx.Response(200, json={"video": {"url": "https://cdn.example/v.mp4"}})
        return httpx.Response(200, content=mp4)
    p, calls = providers(handler)
    res = p.clip(make_image("f.png"), "slow push in", 3.0, os.path.join(shared, "c.mp4"))
    body = json.loads(calls[0].content)
    assert body["image_url"].startswith("data:image/png;base64,") and body["prompt"] == "slow push in"
    assert abs(media.duration(res.path) - 3.0) < 0.1


def test_stills_openverse_keeps_only_reusable_large_images(shared):
    png = media_bytes(shared, ["-f", "lavfi", "-i", "testsrc2=size=1600x900", "-frames:v", "1"], "s.png")
    results = [
        {"url": "https://img/1.png", "width": 1600, "height": 900, "license": "by", "creator": "Ann",
         "foreign_landing_url": "https://src/1"},
        {"url": "https://img/2.png", "width": 1600, "height": 900, "license": "by-nc", "creator": "Bob",
         "foreign_landing_url": "https://src/2"},
        {"url": "https://img/3.png", "width": 500, "height": 300, "license": "cc0", "creator": "Cy",
         "foreign_landing_url": "https://src/3"},
    ]

    def handler(r, n):
        if r.url.host == "api.openverse.org":
            return httpx.Response(200, json={"results": results})
        return httpx.Response(200, content=png)
    p, calls = providers(handler)
    items = p.stills("telegraph", os.path.join(shared, "st"), 3)
    assert "license=pdm%2Ccc0%2Cby%2Cby-sa" in str(calls[0].url) or "license=pdm,cc0,by,by-sa" in str(calls[0].url)
    assert [i.source["author"] for i in items] == ["Ann"]
    assert items[0].source == {"license": "CC BY", "author": "Ann", "url": "https://src/1"}


def test_notify_telegram():
    p, calls = providers(lambda r, n: httpx.Response(200, json={"ok": True}))
    assert p.notify("video 7 is ready") is True
    assert str(calls[0].url) == "https://api.telegram.org/bot123:abc/sendMessage"
    assert json.loads(calls[0].content) == {"chat_id": "42", "text": "video 7 is ready"}


def test_notify_without_telegram_settings():
    p, calls = providers(lambda r, n: httpx.Response(200), env={})
    assert p.notify("x") is False and not calls


def test_json_with_escaped_quotes_and_braces_in_strings_is_parsed():
    from app.providers.live import first_json_object
    text = 'Here you go: {"text": "a \\"{\\" b", "n": 1} and {"other": 2}'
    assert first_json_object(text) == {"text": 'a "{" b', "n": 1}
