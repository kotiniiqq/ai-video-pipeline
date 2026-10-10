"""Media for tests is generated here with ffmpeg's lavfi sources; no media files live in the repo."""
import os
import subprocess

import pytest
from fastapi.testclient import TestClient


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True, timeout=120)


@pytest.fixture
def shared(tmp_path, monkeypatch):
    root = tmp_path / "shared"
    root.mkdir()
    from app import config
    monkeypatch.setattr(config, "SHARED_DIR", os.path.realpath(root))
    return str(root)


@pytest.fixture
def client(shared):
    from app.main import app
    return TestClient(app)


@pytest.fixture
def make_clip(shared):
    def make(name, duration=2.0, kind="testsrc", size="1280x720", fps=30):
        out = os.path.join(shared, name)
        src = {
            "testsrc": f"testsrc2=size={size}:rate={fps}",
            "black": f"color=c=black:size={size}:rate={fps}",
            "still": f"color=c=0x336699:size={size}:rate={fps}",
        }[kind]
        _ffmpeg("-f", "lavfi", "-i", src, "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p", out)
        return out
    return make


@pytest.fixture
def make_tone(shared):
    def make(name, duration=3.0, freq=440, volume=0.3):
        out = os.path.join(shared, name)
        _ffmpeg("-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=44100:duration={duration}",
                "-af", f"volume={volume}", out)
        return out
    return make


@pytest.fixture
def make_image(shared):
    def make(name, w=1280, h=720):
        out = os.path.join(shared, name)
        _ffmpeg("-f", "lavfi", "-i", f"testsrc2=size={w}x{h}", "-frames:v", "1", out)
        return out
    return make


@pytest.fixture
def wait_job(client):
    import time

    def wait(job_id, timeout=120):
        until = time.time() + timeout
        while time.time() < until:
            job = client.get(f"/jobs/{job_id}").json()
            if job["status"] in ("done", "failed"):
                return job
            time.sleep(0.1)
        raise AssertionError(f"job {job_id} still running after {timeout}s")
    return wait


@pytest.fixture
def make_av(shared):
    """A moving clip with a tone; `lufs` normalises the audio to that integrated loudness."""
    def make(name, duration=4.0, lufs=None, volume=0.05):
        out = os.path.join(shared, name)
        af = f"loudnorm=I={lufs}:TP=-1:LRA=11" if lufs is not None else f"volume={volume}"
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi",
                "-i", f"sine=frequency=330:sample_rate=48000:duration={duration}",
                "-t", str(duration), "-af", af, "-ar", "48000", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", out)
        return out
    return make


class FakeFaces:
    """Stands in for the YuNet/SFace backend: a fixed number of faces and a fixed similarity."""

    def __init__(self, count=1, similarity=0.9):
        self.count, self.sim = count, similarity

    def detect(self, img):
        from app.faces import Face
        return [Face(100.0 * i, 100.0, 200.0, 200.0, 0.99, None) for i in range(self.count)]

    def similarity(self, img_a, face_a, img_b, face_b):
        return self.sim


@pytest.fixture
def fake_faces():
    from app import faces

    def use(count=1, similarity=0.9):
        faces.set_backend(FakeFaces(count, similarity))
    yield use
    faces.set_backend(None)
