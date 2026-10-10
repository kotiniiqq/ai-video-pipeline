import json
import os
import subprocess

from app import media, render


def stream_durations(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", path],
                         capture_output=True, text=True, check=True)
    return {s["codec_type"]: float(s["duration"]) for s in json.loads(out.stdout)["streams"]}


def test_kenburns_makes_a_moving_clip_of_the_requested_length(shared, make_image):
    out = os.path.join(shared, "kb.mp4")
    res = render.kenburns(make_image("p.png", 1600, 900), out, 3.0, move="zoom_in")
    info = media.summary(out)
    assert res["path"] == out and abs(info["duration"] - 3.0) < 0.1
    assert (info["width"], info["height"]) == (1280, 720)
    _, freeze = media.black_and_freeze(out)
    assert freeze == []


def test_kenburns_handles_portrait_images(shared, make_image):
    out = os.path.join(shared, "kb2.mp4")
    render.kenburns(make_image("tall.png", 600, 1000), out, 2.0, move="pan_left")
    assert (media.summary(out)["width"], media.summary(out)["height"]) == (1280, 720)


def test_fit_slows_down_short_clips(shared, make_clip):
    out = os.path.join(shared, "slow.mp4")
    render.fit(make_clip("short.mp4", 2.0), out, 3.0)
    assert abs(media.duration(out) - 3.0) < 0.1


def test_fit_trims_long_clips(shared, make_clip):
    out = os.path.join(shared, "trim.mp4")
    render.fit(make_clip("long.mp4", 4.0), out, 2.0)
    assert abs(media.duration(out) - 2.0) < 0.1


def test_music_bed_has_the_requested_length(shared):
    out = os.path.join(shared, "bed.m4a")
    render.music_bed(8.0, out)
    assert abs(media.duration(out) - 8.0) < 0.15


def test_master_keeps_picture_and_sound_in_sync(shared, make_clip, make_tone):
    segs = [{"path": make_clip("a.mp4", 2.0), "duration_s": 2.0, "transition": "fade"},
            {"path": make_clip("b.mp4", 2.0), "duration_s": 2.0, "transition": "fade"},
            {"path": make_clip("c.mp4", 1.5), "duration_s": 1.5, "transition": "cut"}]
    voice = make_tone("voice.wav", 5.5, volume=0.4)
    bed = os.path.join(shared, "bed.m4a")
    render.music_bed(5.5, bed)
    out = os.path.join(shared, "final.mp4")
    res = render.master(segs, voice, out, music_path=bed)
    streams = stream_durations(out)
    assert abs(streams["video"] - 5.5) < 0.15, streams
    assert abs(streams["video"] - streams["audio"]) < 0.1, streams
    assert abs(res["lufs"] - (-14)) <= 1.0
    black, _ = media.black_and_freeze(out)
    assert black == []


def test_render_routes_return_jobs(client, wait_job, shared, make_image):
    out = os.path.join(shared, "videos", "1", "kb.mp4")
    r = client.post("/render/kenburns", json={"image_path": make_image("q.png"), "out": out, "duration_s": 2.0})
    assert r.status_code == 200
    job = wait_job(r.json()["job_id"])
    assert job["status"] == "done" and abs(job["result"]["duration_s"] - 2.0) < 0.1


def test_render_rejects_output_outside_shared(client, make_image):
    r = client.post("/render/kenburns", json={"image_path": make_image("q.png"), "out": "/tmp/x.mp4", "duration_s": 2.0})
    assert r.status_code == 422


def test_master_with_cuts_before_fades(shared, make_clip, make_tone):
    """A cut (concat) followed by a fade (xfade): both inputs of xfade must share a timebase."""
    segs = [{"path": make_clip(f"s{i}.mp4", 2.0), "duration_s": 2.0, "transition": t}
            for i, t in enumerate(["cut", "cut", "fade", "cut", "cut"])]
    voice = make_tone("v.wav", 10.0, volume=0.4)
    out = os.path.join(shared, "mixed.mp4")
    render.master(segs, voice, out)
    streams = stream_durations(out)
    assert abs(streams["video"] - 10.0) < 0.15, streams


def test_master_reaches_target_loudness_even_with_sharp_peaks(shared, make_clip):
    """Speech has peaks far above its average level; linear gain alone cannot reach -14 LUFS then."""
    voice = os.path.join(shared, "peaky.wav")
    expr = "0.05*sin(2*PI*220*t)+if(lt(mod(t\,1)\,0.01)\,0.95*sin(2*PI*1000*t)\,0)"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d=6", voice], check=True)
    segs = [{"path": make_clip("p.mp4", 6.0), "duration_s": 6.0, "transition": "cut"}]
    res = render.master(segs, voice, os.path.join(shared, "peaky.mp4"))
    assert abs(res["lufs"] - (-14)) <= 1.0, res
