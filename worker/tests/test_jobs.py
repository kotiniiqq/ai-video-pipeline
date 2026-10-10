import json
import os
import time

from app import jobs


def double(x):
    return {"y": x * 2}


def boom():
    raise RuntimeError("boom")


def test_job_runs_to_done(client, wait_job):
    started = jobs.submit("test", double, x=21)
    assert started["status"] == "queued"
    job = wait_job(started["job_id"])
    assert job["status"] == "done" and job["result"] == {"y": 42}


def test_job_error_is_reported(client, wait_job):
    job = wait_job(jobs.submit("test", boom)["job_id"])
    assert job["status"] == "failed" and "boom" in job["error"]
    assert "trace" not in job


def test_running_job_with_stale_heartbeat_is_failed(client, shared):
    job_id = "a" * 32
    path = os.path.join(shared, ".jobs", job_id + ".json")
    os.makedirs(os.path.dirname(path))
    with open(path, "w") as f:
        json.dump({"id": job_id, "kind": "render", "status": "running"}, f)
    old = time.time() - 300
    os.utime(path, (old, old))
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "failed" and "restarted" in job["error"]


def test_malformed_and_unknown_ids_are_404(client):
    assert client.get("/jobs/..%2F..%2Fetc").status_code == 404
    assert client.get("/jobs/" + "b" * 32).status_code == 404
