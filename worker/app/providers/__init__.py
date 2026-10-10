"""Provider gateway: the one place where demo and live differ. Selected by MODE at call time."""
from .. import config
from .base import Providers

_cache: dict[str, Providers] = {}


def get_providers() -> Providers:
    mode = config.MODE
    if mode not in _cache:
        if mode == "live":
            from .live import LiveProviders
            _cache[mode] = LiveProviders()
        else:
            from .demo import DemoProviders
            _cache[mode] = DemoProviders()
    return _cache[mode]
