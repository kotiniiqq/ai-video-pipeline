"""Face detection and identity similarity behind a small interface.

The default backend is OpenCV's YuNet detector with the SFace recognizer (models from OpenCV Zoo,
Apache-2.0). QC code only talks to `get_backend()`, so the backend can be swapped (tests use a fake).
"""
import os
import threading
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

from . import config


@dataclass
class Face:
    x: float
    y: float
    w: float
    h: float
    score: float
    raw: np.ndarray | None  # backend-specific row (landmarks for alignment)


class Backend(Protocol):
    def detect(self, img: np.ndarray) -> list[Face]: ...

    def similarity(self, img_a: np.ndarray, face_a: Face, img_b: np.ndarray, face_b: Face) -> float: ...


class OpenCvBackend:
    DET_SCORE = 0.8
    MIN_FACE_FRAC = 0.08  # ignore faces smaller than this share of the short side (background people)
    DET_MAX_SIDE = 640  # YuNet misses big faces on big inputs; detect on a downscaled copy

    def __init__(self, models_dir: str):
        self.models_dir = models_dir
        self._local = threading.local()  # cv2 DNN objects are not thread-safe

    def _models(self):
        if not hasattr(self._local, "det"):
            self._local.det = cv2.FaceDetectorYN.create(
                os.path.join(self.models_dir, "yunet.onnx"), "", (320, 320), self.DET_SCORE, 0.3, 5000)
            self._local.rec = cv2.FaceRecognizerSF.create(os.path.join(self.models_dir, "sface.onnx"), "")
        return self._local.det, self._local.rec

    def detect(self, img: np.ndarray) -> list[Face]:
        det, _ = self._models()
        h, w = img.shape[:2]
        scale = min(1.0, self.DET_MAX_SIDE / max(h, w))
        small = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else img
        det.setInputSize((small.shape[1], small.shape[0]))
        _, rows = det.detect(small)
        if rows is None:
            return []
        rows[:, :14] /= scale
        min_side = self.MIN_FACE_FRAC * min(h, w)
        return [Face(float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[14]), r)
                for r in rows if r[2] >= min_side and r[3] >= min_side]

    def similarity(self, img_a, face_a, img_b, face_b) -> float:
        _, rec = self._models()
        a = rec.feature(rec.alignCrop(img_a, face_a.raw))
        b = rec.feature(rec.alignCrop(img_b, face_b.raw))
        return float(rec.match(a, b, cv2.FaceRecognizerSF_FR_COSINE))


_override: Backend | None = None
_default: Backend | None = None


def set_backend(backend: Backend | None) -> None:
    global _override
    _override = backend


def get_backend() -> Backend:
    global _default
    if _override is not None:
        return _override
    if _default is None:
        _default = OpenCvBackend(config.MODELS_DIR)
    return _default
