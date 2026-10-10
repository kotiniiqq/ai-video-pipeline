"""Background jobs for long work (renders, provider clips).

Job state is a JSON file under SHARED_DIR/.jobs, so every uvicorn process and a restarted
container see the same jobs. A running job touches its file every few seconds; a running job
whose file went stale lost its process and is reported as failed, so callers re-submit instead
of waiting forever.
"""
import json
import os
import re
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from fastapi import APIRouter, HTTPException

from . import config, media

HEARTBEAT_S = 5
STALE_S = 120
QUEUED_MAX_S = 3 * 3600
KEEP_S = 7 * 86400
_ID = re.compile(r"^[0-9a-f]{32}$")

_pool = ThreadPoolExecutor(max_workers=int(os.getenv("JOB_PARALLEL", "2")), thread_name_prefix="job")
router = APIRouter()


def _dir() -> str:
    return os.path.join(config.SHARED_DIR, ".jobs")


def _path(job_id: str) -> str:
    if not _ID.match(job_id):
        raise HTTPException(404, "unknown job")
    return os.path.join(_dir(), job_id + ".json")


def _write(job: dict) -> None:
    os.makedirs(_dir(), exist_ok=True)
    tmp = _path(job["id"]) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(job, f)
    os.replace(tmp, _path(job["id"]))


def _run(job: dict, fn: Callable[..., dict], kwargs: dict) -> None:
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(HEARTBEAT_S):
            try:
                os.utime(_path(job["id"]))
            except OSError:
                pass

    job.update(status="running", started_at=time.time())
    _write(job)
    threading.Thread(target=heartbeat, daemon=True).start()
    try:
        job.update(status="done", result=fn(**kwargs))
    except media.InputError as e:
        job.update(status="failed", error=str(e), permanent=True)
    except Exception as e:  # noqa: BLE001 - everything goes back to the caller
        job.update(status="failed", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
    finally:
        stop.set()
        job["finished_at"] = time.time()
        _write(job)


def submit(kind: str, fn: Callable[..., dict], **kwargs) -> dict:
    job = {"id": uuid.uuid4().hex, "kind": kind, "status": "queued", "created_at": time.time()}
    _write(job)
    _pool.submit(_run, job, fn, kwargs)
    _prune()
    return {"job_id": job["id"], "status": "queued"}


def _prune() -> None:
    now = time.time()
    try:
        for name in os.listdir(_dir()):
            p = os.path.join(_dir(), name)
            if now - os.path.getmtime(p) > KEEP_S:
                os.unlink(p)
    except OSError:
        pass


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    path = _path(job_id)
    try:
        with open(path) as f:
            job = json.load(f)
        age = time.time() - os.path.getmtime(path)
    except FileNotFoundError:
        raise HTTPException(404, "unknown job")
    if (job["status"] == "running" and age > STALE_S) or (job["status"] == "queued" and age > QUEUED_MAX_S):
        job.update(status="failed", error="the job's process died (worker restarted?)")
        _write(job)
    job.pop("trace", None)
    return job
