import os
import re

from PIL import Image

from app import packaging

PARAS = [
    {"text": "The cable was laid in 1858. It worked for three weeks, then failed.", "start_s": 0.0, "duration_s": 6.0},
    {"text": "A second attempt, eight years later, used a far better design and a much larger ship, "
             "which carried the whole length in one piece across the ocean.", "start_s": 6.0, "duration_s": 9.0},
]


def test_cues_cover_the_narration_in_order():
    cues = packaging.cues(PARAS)
    assert cues[0]["start"] == 0.0
    assert abs(cues[-1]["end"] - 15.0) < 0.01
    for a, b in zip(cues, cues[1:]):
        assert a["end"] <= b["start"] + 1e-6 and a["start"] < a["end"]


def test_cue_lines_are_short():
    for cue in packaging.cues(PARAS):
        lines = cue["text"].split("\n")
        assert len(lines) <= 2 and all(len(line) <= 42 for line in lines), cue


def test_srt_format(shared):
    out = os.path.join(shared, "s.srt")
    res = packaging.write_srt(PARAS, out)
    text = open(out, encoding="utf-8").read()
    assert res["cues"] >= 4
    assert re.match(r"1\n00:00:00,000 --> 00:00:\d\d,\d{3}\n", text)
    assert "00:00:15,000" in text


def test_thumbnail_is_1280x720_from_a_portrait_image(shared, make_image):
    out = os.path.join(shared, "t.jpg")
    res = packaging.thumbnail(make_image("portrait.png", 800, 1200), "The cable that crossed an ocean", out)
    assert (res["width"], res["height"]) == (1280, 720)
    assert Image.open(out).size == (1280, 720)


def test_thumbnail_survives_very_long_text(shared, make_image):
    out = os.path.join(shared, "t2.jpg")
    res = packaging.thumbnail(make_image("p.png"), "word " * 60, out)
    assert res["lines"] <= 3


def test_routes(client, shared, make_image):
    srt = client.post("/subtitles", json={"paragraphs": PARAS, "out": os.path.join(shared, "x.srt")})
    assert srt.status_code == 200 and srt.json()["cues"] >= 4
    th = client.post("/thumbnail", json={"image_path": make_image("i.png"), "text": "Hi", "out": os.path.join(shared, "x.jpg")})
    assert th.status_code == 200 and th.json()["width"] == 1280
