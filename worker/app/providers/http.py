"""HTTP calls to providers: retries on 429/5xx, and errors mapped to permanent (400) or retryable (502)."""
import time
from typing import Callable

import httpx

from .base import ProviderError

RETRYABLE = {429, 500, 502, 503, 504}


class Http:
    def __init__(self, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep,
                 attempts: int = 3):
        self.client = client or httpx.Client(timeout=httpx.Timeout(120, connect=15), follow_redirects=True)
        self.sleep = sleep
        self.attempts = attempts

    def request(self, method: str, url: str, what: str, **kwargs) -> httpx.Response:
        last = ""
        for attempt in range(self.attempts):
            try:
                r = self.client.request(method, url, **kwargs)
            except httpx.TransportError as e:
                last = f"{type(e).__name__}: {e}"
            else:
                if r.status_code < 400:
                    return r
                last = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code not in RETRYABLE:
                    raise ProviderError(400, f"{what} rejected the request ({last})")
            if attempt < self.attempts - 1:
                self.sleep(2 ** attempt)
        raise ProviderError(502, f"{what} failed after {self.attempts} attempts ({last})")

    def download(self, url: str, dst: str, what: str) -> str:
        r = self.request("GET", url, what)
        with open(dst, "wb") as f:
            f.write(r.content)
        return dst
