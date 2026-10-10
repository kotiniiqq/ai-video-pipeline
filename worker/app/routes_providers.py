"""HTTP routes for the provider gateway. n8n never calls model providers directly; it calls these."""
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import jobs, media
from .providers import get_providers
from .providers.base import ProviderError

router = APIRouter()


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ProviderError as e:
        raise HTTPException(e.status, str(e))


class LlmReq(BaseModel):
    task: str
    input: dict
    repair: dict | None = Field(None, description="{previous: <bad output>, errors: [..]} to ask for a corrected answer")


class TtsReq(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    out: str


class ImageReq(BaseModel):
    prompt: str
    out: str
    width: int = 1280
    height: int = 720


class ClipReq(BaseModel):
    image_path: str
    prompt: str
    duration_s: float = Field(gt=0, le=15)
    out: str


class StillsReq(BaseModel):
    query: str
    out_dir: str
    limit: int = Field(3, ge=1, le=10)


class NotifyReq(BaseModel):
    text: str


@router.post("/llm")
def llm(req: LlmReq):
    res = _call(get_providers().llm, req.task, req.input, req.repair)
    return {"output": res.output, "model": res.model, "cost_usd": res.usd}


@router.post("/tts")
def tts(req: TtsReq):
    res = _call(get_providers().tts, req.text, req.out)
    return {"path": res.path, "duration_s": res.duration_s, "cost_usd": res.usd}


@router.post("/image")
def image(req: ImageReq):
    media.output_path(req.out)
    res = _call(get_providers().image, req.prompt, req.out, req.width, req.height)
    return {"path": res.path, "cost_usd": res.usd, "source": res.source}


def _clip_job(image_path: str, prompt: str, duration_s: float, out: str) -> dict:
    try:
        res = get_providers().clip(image_path, prompt, duration_s, out)
    except ProviderError as e:
        if e.status < 500:
            raise media.InputError(str(e))  # permanent: the job is marked so and the shot falls back
        raise
    return {"path": res.path, "duration_s": res.duration_s, "cost_usd": res.usd}


@router.post("/clip")
def clip(req: ClipReq):
    media.inside_shared(req.image_path)
    media.output_path(req.out)
    return jobs.submit("clip", _clip_job, image_path=req.image_path, prompt=req.prompt,
                       duration_s=req.duration_s, out=req.out)


@router.post("/search-stills")
def search_stills(req: StillsReq):
    media.output_path(os.path.join(req.out_dir, "x"))
    items = _call(get_providers().stills, req.query, req.out_dir, req.limit)
    return {"items": [{"path": i.path, "source": i.source} for i in items], "cost_usd": sum(i.usd for i in items)}


@router.post("/notify")
def notify(req: NotifyReq):
    return {"sent": _call(get_providers().notify, req.text)}
