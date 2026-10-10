"""Media worker: QC, rendering, packaging and the single gateway to model providers."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import config, jobs, media, packaging, qc, render

app = FastAPI(title="ai-video-pipeline worker")
app.include_router(jobs.router)
app.include_router(qc.router)
app.include_router(render.router)
app.include_router(packaging.router)


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
