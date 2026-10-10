def qc(client, path, body):
    r = client.post(path, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_small_image_fails(client, make_image):
    res = qc(client, "/qc/image", {"path": make_image("small.png", 640, 360)})
    assert res["status"] == "FAIL" and any("resolution" in r for r in res["reasons"])


def test_good_image_passes_without_face_check(client, make_image):
    res = qc(client, "/qc/image", {"path": make_image("ok.png")})
    assert res["status"] == "PASS" and res["faces"] is None


def test_expected_face_count(client, make_image, fake_faces):
    path = make_image("f.png")
    for count, status in ((0, "FAIL"), (2, "FAIL"), (1, "PASS")):
        fake_faces(count=count)
        res = qc(client, "/qc/image", {"path": path, "expect_face": True})
        assert (res["status"], res["faces"]) == (status, count)


def test_black_clip_fails(client, make_clip):
    res = qc(client, "/qc/clip", {"path": make_clip("b.mp4", 2.0, kind="black")})
    assert res["status"] == "FAIL" and any("black" in r for r in res["reasons"])


def test_static_clip_fails(client, make_clip):
    res = qc(client, "/qc/clip", {"path": make_clip("s.mp4", 3.0, kind="still")})
    assert res["status"] == "FAIL" and any("static" in r for r in res["reasons"])


def test_moving_clip_of_right_length_passes(client, make_clip):
    res = qc(client, "/qc/clip", {"path": make_clip("m.mp4", 3.0), "expected_duration": 3.0})
    assert res["status"] == "PASS", res["reasons"]


def test_wrong_duration_fails(client, make_clip):
    res = qc(client, "/qc/clip", {"path": make_clip("m.mp4", 2.0), "expected_duration": 4.0})
    assert res["status"] == "FAIL" and any("duration" in r for r in res["reasons"])


def test_face_drift_is_questionable(client, make_clip, fake_faces):
    fake_faces(count=1, similarity=0.2)
    res = qc(client, "/qc/clip", {"path": make_clip("d.mp4", 2.0), "expect_face": True})
    assert res["status"] == "QUESTIONABLE" and any("drift" in r for r in res["reasons"])


def test_final_at_target_loudness_passes(client, make_av):
    res = qc(client, "/qc/final", {"path": make_av("f.mp4", 6.0, lufs=-14), "expected_duration": 6.0})
    assert res["status"] == "PASS", res
    assert abs(res["lufs"] + 14) <= 1.0


def test_quiet_final_fails_on_loudness(client, make_av):
    res = qc(client, "/qc/final", {"path": make_av("q.mp4", 6.0, volume=0.02), "expected_duration": 6.0})
    assert res["status"] == "FAIL" and any("loudness" in r for r in res["reasons"])


def test_non_media_file_is_422(client, shared):
    import os
    p = os.path.join(shared, "x.mp4")
    open(p, "w").write("not a video")
    assert client.post("/qc/clip", json={"path": p}).status_code == 422
