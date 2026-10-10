"""File access inside the shared directory, plus ffprobe/ffmpeg helpers used by QC and rendering."""
import json
import os
import re
import subprocess

import cv2
import numpy as np

from . import config


class InputError(ValueError):
    """Bad input from the caller: maps to HTTP 422 and is never retried."""


def _inside(path: str) -> str:
    root = config.SHARED_DIR
    real = os.path.realpath(path)
    if real != root and not real.startswith(root + os.sep):
        raise InputError(f"path must be inside {root}: {path}")
    return real


def inside_shared(path: str) -> str:
    """An existing file inside SHARED_DIR, as a real path."""
    real = _inside(path)
    if not os.path.isfile(real):
        raise InputError(f"file not found: {path}")
    return real


def output_path(path: str) -> str:
    """A file path inside SHARED_DIR to write to; its directory is created."""
    real = _inside(path)
    os.makedirs(os.path.dirname(real), exist_ok=True)
    return real


def run_ffmpeg(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-y", *args],
                         capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {out.stderr.strip()[-600:]}")
    return out


def probe(path: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise InputError(f"not a media file: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def duration(path: str) -> float:
    return float(probe(path)["format"].get("duration") or 0.0)


def summary(path: str) -> dict:
    info = probe(path)
    video = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    return {
        "duration": round(float(info["format"].get("duration") or 0.0), 3),
        "width": video.get("width") if video else None,
        "height": video.get("height") if video else None,
        "has_video": video is not None,
        "has_audio": any(s.get("codec_type") == "audio" for s in info["streams"]),
    }


def black_and_freeze(path: str, freeze_min: float = 1.0) -> tuple[list[dict], list[dict]]:
    """Black segments and frozen stretches, found in one ffmpeg pass."""
    log = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vf",
         f"blackdetect=d=0.3:pix_th=0.10,freezedetect=n=0.003:d={freeze_min}", "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300).stderr
    black = [{"start": float(s), "end": float(e), "duration": float(d)}
             for s, e, d in re.findall(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)", log)]
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
    durations = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", log)]
    freeze = [{"start": s, "duration": d} for s, d in zip(starts, durations)]
    if len(starts) > len(durations):  # a freeze lasting to the end has no duration line
        freeze.append({"start": starts[-1], "duration": None})
    return black, freeze


def grab_frame(path: str, t: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(path)
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(t, 0.0) * 1000)
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def loudness(path: str) -> float:
    """Integrated loudness (LUFS, EBU R128) of the file's audio."""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True, timeout=300).stderr
    found = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    if not found:
        raise InputError("no audio to measure")
    return float(found[-1])


def load_image(path: str) -> np.ndarray:
    img = cv2.imread(inside_shared(path), cv2.IMREAD_COLOR)
    if img is None:
        raise InputError(f"not a decodable image: {path}")
    return img
