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
