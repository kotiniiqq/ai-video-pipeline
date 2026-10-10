"""Media worker: QC, rendering, packaging and the single gateway to model providers."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import config, media

app = FastAPI(title="ai-video-pipeline worker")


@app.exception_handler(media.InputError)
def _input_error(_: Request, exc: media.InputError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health")
def health():
    return {"status": "ok", "mode": config.MODE}


class ProbeRequest(BaseModel):
    path: str


@app.post("/probe")
def probe(req: ProbeRequest):
    return media.summary(media.inside_shared(req.path))
