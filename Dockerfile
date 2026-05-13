# syntax=docker/dockerfile:1

FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="pina-transcribe"
LABEL org.opencontainers.image.description="YouTube/Twitch -> faster-whisper (CPU)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/root/.cache/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY transcribe.py launcher.py web_server.py docker_entrypoint.py ./
COPY utils/ utils/

RUN mkdir -p /app/logs /app/temp /app/outputs

EXPOSE 15000

VOLUME ["/app/outputs", "/app/logs"]

ENTRYPOINT ["python", "/app/docker_entrypoint.py"]
CMD []
