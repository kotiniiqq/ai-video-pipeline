"""Quality checks: a generated image, a shot clip, and the final video.

Statuses: PASS; QUESTIONABLE (usable, but a person or a vision model should look);
FAIL (regenerate). Reasons are plain sentences so they can go straight into a notification.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from . import config, faces, media

router = APIRouter(prefix="/qc")


class ImageQC(BaseModel):
    path: str
    min_width: int = 1024
    min_height: int = 576
    expect_face: bool = False


class ClipQC(BaseModel):
    path: str
    expected_duration: float | None = None
    tolerance: float = 0.25
    expect_face: bool = False
    drift_threshold: float = 0.45
    freeze_min: float = 1.0


class FinalQC(BaseModel):
    path: str
    expected_duration: float
    tolerance: float = 1.0
    target_lufs: float = config.TARGET_LUFS
    lufs_tolerance: float = 1.0


@router.post("/image")
def image_qc(req: ImageQC):
    img = media.load_image(req.path)
    h, w = img.shape[:2]
    reasons, count = [], None
    if w < req.min_width or h < req.min_height:
        reasons.append(f"resolution {w}x{h} is below {req.min_width}x{req.min_height}")
    if req.expect_face:
        count = len(faces.get_backend().detect(img))
        if count != 1:
            reasons.append(f"expected exactly one face, found {count}")
    return {"status": "FAIL" if reasons else "PASS", "reasons": reasons, "width": w, "height": h, "faces": count}


@router.post("/clip")
def clip_qc(req: ClipQC):
    path = media.inside_shared(req.path)
    info = media.summary(path)
    if not info["has_video"]:
        return {"status": "FAIL", "reasons": ["no video stream"], "duration": info["duration"]}
    fail, questionable = [], []
    dur = info["duration"]
    if req.expected_duration is not None and abs(dur - req.expected_duration) > req.tolerance:
        fail.append(f"duration {dur:.2f}s, expected {req.expected_duration:.2f}s")

    black, freeze = media.black_and_freeze(path, req.freeze_min)
    if black:
        fail.append(f"black frames in {len(black)} segment(s)")
    frozen = sum(f["duration"] if f["duration"] is not None else dur - f["start"] for f in freeze)
    if dur and frozen / dur >= 0.5:
        fail.append(f"static for {frozen:.1f}s of {dur:.1f}s")
    elif freeze:
        questionable.append(f"frozen for {frozen:.1f}s")

    face_report = None
    if req.expect_face:
        face_report = _face_consistency(path, dur, req.drift_threshold)
        questionable += face_report.pop("issues")

    status = "FAIL" if fail else "QUESTIONABLE" if questionable else "PASS"
    return {"status": status, "reasons": fail + questionable, "duration": dur,
            "black": black, "freeze": freeze, "face": face_report}


def _face_consistency(path: str, dur: float, threshold: float) -> dict:
    """One face at the start and at the end of the clip, and the same person in both."""
    backend = faces.get_backend()
    issues, points, found = [], [], {}
    for label, t in (("start", 0.0), ("end", max(dur - 0.1, 0.0))):
        frame = media.grab_frame(path, t)
        detected = backend.detect(frame) if frame is not None else []
        points.append({"at": label, "faces": len(detected)})
        if len(detected) != 1:
            issues.append(f"{label}: expected one face, found {len(detected)}")
        else:
            found[label] = (frame, detected[0])
    sim = None
    if len(found) == 2:
        sim = backend.similarity(*found["start"], *found["end"])
        if sim < threshold:
            issues.append(f"face drift: start/end similarity {sim:.2f} < {threshold}")
    return {"points": points, "start_end_similarity": sim, "issues": issues}


@router.post("/final")
def final_qc(req: FinalQC):
    path = media.inside_shared(req.path)
    info = media.summary(path)
    reasons = []
    if abs(info["duration"] - req.expected_duration) > req.tolerance:
        reasons.append(f"duration {info['duration']:.2f}s, expected {req.expected_duration:.2f}s")
    lufs = media.loudness(path) if info["has_audio"] else None
    if lufs is None:
        reasons.append("no audio")
    elif abs(lufs - req.target_lufs) > req.lufs_tolerance:
        reasons.append(f"loudness {lufs:.1f} LUFS, target {req.target_lufs:.1f}")
    black, _ = media.black_and_freeze(path, 5.0)
    if black:
        reasons.append(f"black frames in {len(black)} segment(s)")
    return {"status": "FAIL" if reasons else "PASS", "reasons": reasons, "duration": info["duration"],
            "lufs": lufs, "black": black, "width": info["width"], "height": info["height"]}
