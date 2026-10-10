"""Runtime settings from the environment. Read through this module so tests can patch them."""
import os

SHARED_DIR = os.path.realpath(os.getenv("SHARED_DIR", "/data/shared"))
MODE = os.getenv("MODE", "demo").strip().lower()
MODELS_DIR = os.getenv("MODELS_DIR", "/models")

RENDER_W, RENDER_H = 1280, 720
RENDER_FPS = 30
TARGET_LUFS = -14.0

if MODE not in ("demo", "live"):
    raise RuntimeError(f"MODE must be 'demo' or 'live', got {MODE!r}")
