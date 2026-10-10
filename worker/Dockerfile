FROM python:3.12-slim AS base

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Face models from OpenCV Zoo (Apache-2.0) and a Piper voice trained on LJSpeech (public domain).
# Downloaded at build time; nothing model-related is stored in the repository.
RUN mkdir -p /models/piper \
 && curl -fsSL -o /models/yunet.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
 && curl -fsSL -o /models/sface.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx \
 && curl -fsSL -o /models/piper/voice.onnx https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/ljspeech/medium/en_US-ljspeech-medium.onnx \
 && curl -fsSL -o /models/piper/voice.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/ljspeech/medium/en_US-ljspeech-medium.onnx.json

COPY app ./app

# Same uid as the n8n container; /data/shared is created here so a fresh named volume inherits the owner
RUN useradd -u 1000 -m worker && mkdir -p /data/shared && chown worker /data/shared
USER worker
ENV MODELS_DIR=/models SHARED_DIR=/data/shared

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

FROM base AS test
USER root
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
USER worker
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
