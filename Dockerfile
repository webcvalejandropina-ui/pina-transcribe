# syntax=docker/dockerfile:1

FROM denoland/deno:bin-2.6.3 AS deno

FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="pina-transcribe"
LABEL org.opencontainers.image.description="YouTube/Twitch -> faster-whisper (CPU)"
LABEL org.opencontainers.image.version="2.1.0"
LABEL org.opencontainers.image.created="2026-09-16"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/app/.cache/huggingface \
    XDG_CACHE_HOME=/home/app/.cache

COPY --from=deno /deno /usr/local/bin/deno

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip "setuptools>=83.0.0" \
    && pip install -r requirements.txt

COPY transcribe.py launcher.py web_server.py docker_entrypoint.py app_metadata.py ./
COPY utils/ utils/

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
    && mkdir -p /app/logs /app/temp /app/outputs "$HF_HOME" \
    && chown -R app:app /app /home/app

USER app

EXPOSE 15000

VOLUME ["/app/outputs", "/app/logs"]

ENTRYPOINT ["python", "/app/docker_entrypoint.py"]
CMD []
