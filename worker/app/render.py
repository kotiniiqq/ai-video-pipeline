"""Rendering with FFmpeg: Ken Burns over stills, fitting clips to a length, and the final master.

Everything renders to 1280x720, 30 fps, H.264 yuv420p. The master keeps picture and narration in
sync: a crossfade borrows its time from an extended clip, so transitions never shorten the timeline.
"""
import json
import os
import re
import tempfile
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from . import config, jobs, media

W, H, FPS = config.RENDER_W, config.RENDER_H, config.RENDER_FPS
VIDEO_OUT = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]
COVER = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"

router = APIRouter(prefix="/render")


def kenburns(image_path: str, out: str, duration_s: float, move: str = "zoom_in", zoom: float = 1.15) -> dict:
    """A slow zoom or pan over a still image."""
    src, dst = media.inside_shared(image_path), media.output_path(out)
    frames = max(1, round(duration_s * FPS))
    p = f"on/{frames}"
    z, x, y = {
        "zoom_in": (f"1+{zoom - 1}*{p}", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"),
        "zoom_out": (f"{zoom}-{zoom - 1}*{p}", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"),
        "pan_left": (str(zoom), f"(iw-iw/zoom)*(1-{p})", "ih/2-ih/zoom/2"),
        "pan_right": (str(zoom), f"(iw-iw/zoom)*{p}", "ih/2-ih/zoom/2"),
    }[move]
    # Upscale first: zoompan rounds to whole pixels, and on a 2x canvas the motion stays smooth
    vf = (f"scale={2 * W}:{2 * H}:force_original_aspect_ratio=increase,crop={2 * W}:{2 * H},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},setsar=1")
    media.run_ffmpeg("-i", src, "-vf", vf, "-frames:v", str(frames), *VIDEO_OUT, "-an", dst)
    return {"path": dst, "duration_s": round(media.duration(dst), 3)}


def fit(video_path: str, out: str, duration_s: float, max_stretch: float = 1.25) -> dict:
    """Trim a clip to a length, or slow it down (up to max_stretch) and then hold the last frame."""
    src, dst = media.inside_shared(video_path), media.output_path(out)
    have = media.duration(src)
    filters = [COVER, f"fps={FPS}"]
    if have < duration_s:
        stretch = min(duration_s / have, max_stretch) if have > 0 else 1.0
        filters.insert(0, f"setpts={stretch:.4f}*PTS")
        hold = duration_s - have * stretch
        if hold > 0.01:
            filters.append(f"tpad=stop_mode=clone:stop_duration={hold + 0.1:.3f}")
    media.run_ffmpeg("-i", src, "-vf", ",".join(filters), "-t", f"{duration_s:.3f}", *VIDEO_OUT, "-an", dst)
    return {"path": dst, "duration_s": round(media.duration(dst), 3)}


def music_bed(duration_s: float, out: str) -> dict:
    """A quiet generated pad, so demo videos have something to duck under the voice."""
    dst = media.output_path(out)
    d = f"{duration_s:.3f}"
    tones = "+".join(f"0.18*sin(2*PI*{f}*t)" for f in (110, 164.8, 220.5, 329.6))
    fade_out = max(duration_s - 2.0, 0.0)
    media.run_ffmpeg("-f", "lavfi", "-i", f"aevalsrc='{tones}':s=48000:d={d}",
                     "-af", f"lowpass=f=900,tremolo=f=0.2:d=0.3,afade=t=in:d=2,afade=t=out:st={fade_out:.3f}:d=2",
                     "-t", d, "-c:a", "aac", "-b:a", "128k", dst)
    return {"path": dst, "duration_s": round(media.duration(dst), 3)}


TRUE_PEAK = -1.5


def _measure(src: str, target: float) -> dict:
    log = media.run_ffmpeg("-i", src, "-af", f"loudnorm=I={target}:TP={TRUE_PEAK}:LRA=11:print_format=json",
                           "-f", "null", "-").stderr
    return json.loads(re.findall(r"\{[^{}]*\}", log)[-1])


def _loudnorm_two_pass(src: str, dst: str, target: float) -> None:
    """Measure, then normalise with one linear gain (no pumping).

    Speech has peaks far above its average level; when the gain needed to reach the target would push
    those peaks over the true-peak ceiling, loudnorm cannot stay linear and lands short of the target.
    So the peaks are limited first, exactly to where the gain will put them at the ceiling.
    """
    m = _measure(src, target)
    gain = target - float(m["input_i"])
    ceiling = TRUE_PEAK - gain - 0.3  # headroom for the limiter's own overshoot
    if float(m["input_tp"]) > ceiling:
        limited = dst + ".limited.wav"
        media.run_ffmpeg("-i", src, "-af", f"alimiter=limit={10 ** (ceiling / 20):.5f}:level=false:attack=1:release=50",
                         "-ar", "48000", limited)
        src, m = limited, _measure(limited, target)
    media.run_ffmpeg("-i", src, "-af",
                     f"loudnorm=I={target}:TP={TRUE_PEAK}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                     f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
                     f"linear=true", "-ar", "48000", dst)


def master(segments: list[dict], voice_path: str, out: str, music_path: str | None = None,
           music_volume: float = 0.18, xfade: float = 0.5) -> dict:
    """Join shot clips with transitions, put the narration and ducked music under them, -14 LUFS."""
    voice = media.inside_shared(voice_path)
    dst = media.output_path(out)
    total = media.duration(voice)
    with tempfile.TemporaryDirectory(dir=os.path.dirname(dst)) as tmp:
        clips, lengths = [], []
        for i, seg in enumerate(segments):
            fades_out = seg.get("transition", "fade") == "fade" and i < len(segments) - 1
            length = float(seg["duration_s"]) + (xfade if fades_out else 0.0)
            clip = os.path.join(tmp, f"seg{i:03d}.mp4")
            fit(seg["path"], clip, length)
            clips.append(clip)
            lengths.append(length)

        # Video: chain of xfade (fade) or concat (cut); a fade starts xfade seconds before the boundary
        # xfade needs constant-rate inputs on one timebase; concat loses the rate, so every input and
        # every concat result is put back on FPS and 1/FPS
        tb = f"settb=1/{FPS},fps={FPS}"  # fps last: it is what gives the link a constant rate
        graph = [f"[{i}:v]{tb}[s{i}]" for i in range(len(clips))]
        label, run = "[s0]", lengths[0]
        for i in range(1, len(clips)):
            nxt = f"[v{i}]"
            if segments[i - 1].get("transition", "fade") == "fade":
                graph.append(f"{label}[s{i}]xfade=transition=fade:duration={xfade}:offset={run - xfade:.3f}{nxt}")
                run += lengths[i] - xfade
            else:
                graph.append(f"{label}[s{i}]concat=n=2:v=1:a=0,{tb}{nxt}")
                run += lengths[i]
            label = nxt
        video_only = os.path.join(tmp, "video.mp4")
        inputs = [a for c in clips for a in ("-i", c)]
        media.run_ffmpeg(*inputs, "-filter_complex", ";".join(graph), "-map", label, *VIDEO_OUT, video_only)

        # Audio: music ducked under the voice (sidechain), then normalised as a whole
        mixed = os.path.join(tmp, "mix.wav")
        if music_path:
            music = media.inside_shared(music_path)
            media.run_ffmpeg("-i", voice, "-stream_loop", "-1", "-i", music, "-filter_complex",
                             f"[1:a]volume={music_volume},aresample=48000[m];[0:a]aresample=48000,asplit=2[v][key];"
                             "[m][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
                             "[v][duck]amix=inputs=2:duration=first:normalize=0[a]",
                             "-map", "[a]", "-t", f"{total:.3f}", mixed)
        else:
            media.run_ffmpeg("-i", voice, "-ar", "48000", mixed)
        normed = os.path.join(tmp, "norm.wav")
        _loudnorm_two_pass(mixed, normed, config.TARGET_LUFS)

        media.run_ffmpeg("-i", video_only, "-i", normed, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                         "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", dst)
    return {"path": dst, "duration_s": round(media.duration(dst), 3), "lufs": round(media.loudness(dst), 2)}


# ---- routes -------------------------------------------------------------------------------------

class KenBurnsReq(BaseModel):
    image_path: str
    out: str
    duration_s: float
    move: Literal["zoom_in", "zoom_out", "pan_left", "pan_right"] = "zoom_in"


class FitReq(BaseModel):
    video_path: str
    out: str
    duration_s: float


class Segment(BaseModel):
    path: str
    duration_s: float
    transition: Literal["fade", "cut"] = "fade"


class MasterReq(BaseModel):
    segments: list[Segment]
    voice_path: str
    out: str
    music_path: str | None = None


class BedReq(BaseModel):
    duration_s: float
    out: str


def _check_paths(*inputs: str, out: str) -> None:
    """Validate before queueing, so a bad path is a 422 now instead of a failed job later."""
    for p in inputs:
        media.inside_shared(p)
    media.output_path(out)


@router.post("/kenburns")
def kenburns_route(req: KenBurnsReq):
    _check_paths(req.image_path, out=req.out)
    return jobs.submit("kenburns", kenburns, image_path=req.image_path, out=req.out,
                       duration_s=req.duration_s, move=req.move)


@router.post("/fit")
def fit_route(req: FitReq):
    _check_paths(req.video_path, out=req.out)
    return jobs.submit("fit", fit, video_path=req.video_path, out=req.out, duration_s=req.duration_s)


@router.post("/master")
def master_route(req: MasterReq):
    _check_paths(req.voice_path, *[s.path for s in req.segments], *([req.music_path] if req.music_path else []), out=req.out)
    return jobs.submit("master", master, segments=[s.model_dump() for s in req.segments],
                       voice_path=req.voice_path, out=req.out, music_path=req.music_path)


@router.post("/music-bed")
def music_bed_route(req: BedReq):
    return music_bed(req.duration_s, req.out)
