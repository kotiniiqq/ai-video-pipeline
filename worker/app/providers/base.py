"""What the pipeline needs from model providers. Demo and live implementations both satisfy this."""
from dataclasses import dataclass, field
from typing import Protocol

TASKS = ("script", "storyboard", "packaging")


class ProviderError(Exception):
    """A provider call failed. status 400 = caller must fix something (permanent); 502 = retry later."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class LlmResult:
    output: dict
    model: str
    usd: float = 0.0


@dataclass
class AudioResult:
    path: str
    duration_s: float
    usd: float = 0.0


@dataclass
class ImageResult:
    path: str
    usd: float = 0.0
    source: dict = field(default_factory=dict)  # license, author, url: shown in the video description


@dataclass
class ClipResult:
    path: str
    duration_s: float
    usd: float = 0.0


class Providers(Protocol):
    name: str

    def llm(self, task: str, payload: dict, repair: dict | None = None) -> LlmResult: ...

    def tts(self, text: str, out: str) -> AudioResult: ...

    def image(self, prompt: str, out: str, width: int = 1280, height: int = 720) -> ImageResult: ...

    def clip(self, image_path: str, prompt: str, duration_s: float, out: str) -> ClipResult: ...

    def stills(self, query: str, out_dir: str, limit: int = 3) -> list[ImageResult]: ...

    def notify(self, text: str) -> bool: ...
