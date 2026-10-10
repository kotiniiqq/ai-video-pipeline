"""Starting a shot (picture -> image QC -> render job), its fallback, and joining narration parts.

Retry and fallback decisions are not made here: n8n owns the shot state machine. These endpoints
do one step each and report what happened.
"""
import os
import tempfile

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import jobs, media, qc, render, routes_providers
from .providers import get_providers
from .providers.base import ProviderError

router = APIRouter()
MOVES = ["zoom_in", "pan_right", "zoom_out", "pan_left"]


class StartReq(BaseModel):
    kind: str = Field(pattern="^(ai|still)$")
    idx: int
    prompt: str
    query: str
    duration_s: float = Field(gt=0, le=15)
    out_dir: str
    attempt: int = 0


class FallbackReq(BaseModel):
    image_path: str
    idx: int
    duration_s: float = Field(gt=0, le=15)
    out_dir: str
    context: dict | None = Field(None, description="returned as is, so the caller can continue without a lookup")


class ConcatReq(BaseModel):
    paths: list[str] = Field(min_length=1)
    out: str
    gap_s: float = 0.35


@router.post("/shots/start")
def start(req: StartReq):
    providers = get_providers()
    stem = os.path.join(req.out_dir, f"shot{req.idx:03d}_a{req.attempt}")
    cost = 0.0
    try:
        picture = None
        if req.kind == "still":
            found = providers.stills(req.query, stem + "_stills", 1)
            picture = found[0] if found else None
        if picture is None:  # ai shots, or no openly licensed photo for the query
            picture = providers.image(req.prompt, stem + ".png")
        cost += picture.usd
    except ProviderError as e:
        if e.status >= 500:
            raise HTTPException(e.status, str(e))
        return {"ok": False, "reason": str(e), "permanent": True, "cost_usd": cost}

    check = qc.image_qc(qc.ImageQC(path=picture.path))
    if check["status"] != "PASS":
        return {"ok": False, "reason": "; ".join(check["reasons"]), "image_path": picture.path,
                "qc": check, "permanent": False, "cost_usd": cost}

    if req.kind == "ai":
        job = jobs.submit("clip", routes_providers._clip_job, image_path=picture.path, prompt=req.prompt,
                          duration_s=req.duration_s, out=stem + ".mp4")
    else:
        job = jobs.submit("kenburns", render.kenburns, image_path=picture.path, out=stem + ".mp4",
                          duration_s=req.duration_s, move=MOVES[req.idx % len(MOVES)])
    return {"ok": True, "image_path": picture.path, "job_id": job["job_id"], "qc": check,
            "source": picture.source, "cost_usd": cost}


@router.post("/shots/fallback")
def fallback(req: FallbackReq):
    media.inside_shared(req.image_path)
    out = os.path.join(req.out_dir, f"shot{req.idx:03d}_fallback.mp4")
    media.output_path(out)
    job = jobs.submit("kenburns", render.kenburns, image_path=req.image_path, out=out,
                      duration_s=req.duration_s, move=MOVES[req.idx % len(MOVES)])
    return {**job, "context": req.context}


@router.post("/audio/concat")
def concat(req: ConcatReq):
    """Narration parts in order with a short pause between them; returns where each part sits."""
    srcs = [media.inside_shared(p) for p in req.paths]
    dst = media.output_path(req.out)
    parts, t = [], 0.0
    with tempfile.TemporaryDirectory(dir=os.path.dirname(dst)) as tmp:
        silence = os.path.join(tmp, "gap.wav")
        media.run_ffmpeg("-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono", "-t", f"{req.gap_s:.3f}", silence)
        listing, norm = [], []
        for i, src in enumerate(srcs):
            n = os.path.join(tmp, f"p{i}.wav")
            media.run_ffmpeg("-i", src, "-ar", "48000", "-ac", "1", n)
            d = media.duration(n)
            parts.append({"start_s": round(t, 3), "duration_s": round(d, 3)})
            t += d
            listing.append(n)
            if i < len(srcs) - 1:
                listing.append(silence)
                t += req.gap_s
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{p}'\n" for p in listing)
        media.run_ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c:a", "pcm_s16le", dst)
    return {"path": dst, "duration_s": round(media.duration(dst), 3), "parts": parts}
