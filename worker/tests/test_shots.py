import os

from app import media


def start(client, shared, kind, idx=0, attempt=0):
    body = {"kind": kind, "idx": idx, "prompt": "workshop at night, documentary style", "query": "workshop",
            "duration_s": 2.5, "out_dir": os.path.join(shared, "videos", "1", "shots"), "attempt": attempt}
    r = client.post("/shots/start", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_still_shot_becomes_a_ken_burns_clip(client, shared, wait_job):
    res = start(client, shared, "still")
    assert res["ok"] and os.path.isfile(res["image_path"]) and res["source"]["license"]
    job = wait_job(res["job_id"])
    assert job["status"] == "done" and abs(media.duration(job["result"]["path"]) - 2.5) < 0.1


def test_ai_shot_becomes_a_generated_clip_that_passes_qc(client, shared, wait_job):
    res = start(client, shared, "ai", idx=3)
    assert res["ok"] and res["qc"]["status"] == "PASS"
    job = wait_job(res["job_id"])
    qc = client.post("/qc/clip", json={"path": job["result"]["path"], "expected_duration": 2.5}).json()
    assert qc["status"] == "PASS", qc


def test_each_attempt_writes_its_own_files(client, shared, wait_job):
    a = start(client, shared, "ai", idx=4, attempt=0)
    b = start(client, shared, "ai", idx=4, attempt=1)
    assert a["image_path"] != b["image_path"]
    wait_job(a["job_id"])
    wait_job(b["job_id"])


def test_fallback_renders_ken_burns_over_an_existing_image(client, shared, wait_job, make_image):
    r = client.post("/shots/fallback", json={"image_path": make_image("f.png"), "idx": 2, "duration_s": 3.0,
                                             "out_dir": os.path.join(shared, "videos", "1", "shots"),
                                             "context": {"shot_id": 9, "update": {"status": "generating"}}})
    assert r.json()["context"] == {"shot_id": 9, "update": {"status": "generating"}}
    job = wait_job(r.json()["job_id"])
    assert job["status"] == "done" and abs(job["result"]["duration_s"] - 3.0) < 0.1


def test_audio_concat_reports_where_each_part_starts(client, shared, make_tone):
    a, b = make_tone("a.wav", 1.0), make_tone("b.wav", 2.0)
    out = os.path.join(shared, "voice.wav")
    body = client.post("/audio/concat", json={"paths": [a, b], "out": out, "gap_s": 0.4}).json()
    assert abs(body["duration_s"] - 3.4) < 0.05
    assert [round(p["start_s"], 2) for p in body["parts"]] == [0.0, 1.4]
    assert [round(p["duration_s"], 1) for p in body["parts"]] == [1.0, 2.0]
    assert abs(media.duration(out) - 3.4) < 0.05


def test_injected_faults_exercise_retries_and_fallback(client, shared, wait_job, monkeypatch):
    """DEMO_FAULTS makes demo runs fail on purpose, so the retry and fallback paths get exercised end to end."""
    from app import config
    monkeypatch.setattr(config, "DEMO_FAULTS", True)
    first = start(client, shared, "still", idx=4, attempt=0)
    assert first["ok"] is False and "injected" in first["reason"] and not first["permanent"]
    assert start(client, shared, "still", idx=4, attempt=2)["ok"] is True
    clip = start(client, shared, "ai", idx=10, attempt=0)
    job = wait_job(clip["job_id"])
    assert job["status"] == "failed" and "injected" in job["error"]
    assert start(client, shared, "ai", idx=7, attempt=0)["ok"] is True  # other shots are untouched
