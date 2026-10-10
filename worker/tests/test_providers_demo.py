import os

import pytest
from PIL import Image

from app import media
from app.providers.demo import DemoProviders

TOPIC = "The first transatlantic telegraph cable"


@pytest.fixture
def demo():
    return DemoProviders()


def script(demo, topic=TOPIC):
    return demo.llm("script", {"topic": topic}).output


def test_script_is_deterministic_per_topic(demo):
    assert script(demo) == script(demo)
    assert script(demo) != script(demo, "How lighthouses learned to blink")


def test_script_follows_the_rules_the_workflow_checks(demo):
    s = script(demo)
    paras, ids = s["paragraphs"], {src["id"] for src in s["sources"]}
    assert 6 <= len(paras) <= 10
    assert paras[0]["role"] == "intro" and paras[-1]["role"] == "outro"
    for p in paras[1:-1]:
        assert p["role"] == "body" and p["source_ids"] and set(p["source_ids"]) <= ids
    words = sum(len(p["text"].split()) for p in paras)
    assert 250 <= words <= 1400
    assert TOPIC.lower() in paras[0]["text"].lower()


def test_storyboard_covers_every_paragraph_with_matching_time(demo):
    paras = [{"idx": i, "text": f"Paragraph {i}.", "duration_s": d} for i, d in enumerate([6.0, 11.5, 8.25])]
    shots = demo.llm("storyboard", {"paragraphs": paras, "ai_share_max": 0.3}).output["shots"]
    for p in paras:
        mine = [s for s in shots if s["paragraph"] == p["idx"]]
        assert mine and abs(sum(s["duration_s"] for s in mine) - p["duration_s"]) < 0.01
    ai = sum(s["duration_s"] for s in shots if s["kind"] == "ai")
    assert ai <= 0.3 * sum(p["duration_s"] for p in paras) + 1e-6
    assert all(s["prompt"] and s["query"] for s in shots)


def test_packaging_quotes_come_from_the_script(demo):
    s = script(demo)
    text = " ".join(p["text"] for p in s["paragraphs"])
    out = demo.llm("packaging", {"topic": TOPIC, "script_text": text}).output
    assert len(out["titles"]) == 3 and out["description"]
    for t in out["titles"]:
        assert t["quote"].lower() in text.lower()


def test_demo_costs_nothing(demo):
    assert demo.llm("script", {"topic": TOPIC}).usd == 0


def test_unknown_task_is_422(client):
    assert client.post("/llm", json={"task": "poem", "input": {}}).status_code == 422


def test_llm_route(client):
    body = client.post("/llm", json={"task": "script", "input": {"topic": TOPIC}}).json()
    assert body["model"].startswith("demo") and body["cost_usd"] == 0 and body["output"]["paragraphs"]


def test_tts_duration_matches_the_file(client, shared):
    out = os.path.join(shared, "v", "p0.wav")
    body = client.post("/tts", json={"text": "A short sentence for the narrator.", "out": out}).json()
    assert os.path.isfile(body["path"]) and abs(media.duration(body["path"]) - body["duration_s"]) < 0.05
    assert body["duration_s"] > 0.5


def test_image_is_full_size(client, shared):
    out = os.path.join(shared, "i.png")
    body = client.post("/image", json={"prompt": "a ship laying cable at sea", "out": out}).json()
    assert Image.open(body["path"]).size == (1280, 720)
    assert body["source"]["license"] == "generated"


def test_demo_clip_passes_clip_qc(client, shared, wait_job):
    img = client.post("/image", json={"prompt": "harbour at dawn", "out": os.path.join(shared, "c.png")}).json()["path"]
    job = client.post("/clip", json={"image_path": img, "prompt": "slow push in", "duration_s": 3.0,
                                     "out": os.path.join(shared, "c.mp4")}).json()
    done = wait_job(job["job_id"])
    assert done["status"] == "done", done
    qc = client.post("/qc/clip", json={"path": done["result"]["path"], "expected_duration": 3.0}).json()
    assert qc["status"] == "PASS", qc["reasons"]


def test_stills_are_licensed_and_full_size(client, shared):
    body = client.post("/search-stills", json={"query": "telegraph", "out_dir": os.path.join(shared, "st"), "limit": 2}).json()
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert Image.open(item["path"]).size == (1280, 720) and item["source"]["license"]


def test_notify_without_telegram_is_a_no_op(client):
    assert client.post("/notify", json={"text": "hello"}).json() == {"sent": False}
