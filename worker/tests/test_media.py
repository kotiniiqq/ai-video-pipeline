import os

import pytest

from app import media
from app.media import InputError


def test_paths_outside_shared_are_rejected(shared):
    with pytest.raises(InputError):
        media.inside_shared("/etc/passwd")
    with pytest.raises(InputError):
        media.inside_shared(os.path.join(shared, "..", "escape.txt"))


def test_missing_file_is_rejected(shared):
    with pytest.raises(InputError):
        media.inside_shared(os.path.join(shared, "nope.mp4"))


def test_output_path_creates_parent_and_stays_inside(shared):
    out = media.output_path(os.path.join(shared, "videos", "1", "a.mp4"))
    assert os.path.isdir(os.path.dirname(out))
    with pytest.raises(InputError):
        media.output_path("/tmp/elsewhere.mp4")


def test_duration_of_generated_clip(make_clip):
    assert abs(media.duration(make_clip("a.mp4", 2.0)) - 2.0) < 0.1


def test_black_clip_is_detected(make_clip):
    black, _ = media.black_and_freeze(make_clip("b.mp4", 2.0, kind="black"))
    assert black and black[0]["duration"] >= 1.5


def test_still_clip_is_frozen(make_clip):
    _, freeze = media.black_and_freeze(make_clip("s.mp4", 3.0, kind="still"))
    assert freeze


def test_moving_clip_is_clean(make_clip):
    assert media.black_and_freeze(make_clip("m.mp4", 2.0)) == ([], [])


def test_grab_frame(make_clip):
    frame = media.grab_frame(make_clip("g.mp4", 2.0), 1.0)
    assert frame is not None and frame.shape[:2] == (720, 1280)


def test_loudness_tracks_volume(make_tone):
    loud = media.loudness(make_tone("loud.wav", 3.0, volume=1.0))
    quiet = media.loudness(make_tone("quiet.wav", 3.0, volume=0.316))  # -10 dB
    assert -60 < quiet < loud < 0
    assert abs((loud - quiet) - 10) < 0.5


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["mode"] in ("demo", "live")


def test_input_error_maps_to_422(client):
    assert client.post("/probe", json={"path": "/etc/passwd"}).status_code == 422


def test_probe_endpoint(client, make_clip):
    body = client.post("/probe", json={"path": make_clip("p.mp4", 2.0)}).json()
    assert body["width"] == 1280 and body["height"] == 720 and abs(body["duration"] - 2.0) < 0.1
    assert body["has_audio"] is False
