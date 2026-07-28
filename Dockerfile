FROM python:3.12-slim AS base

# ffmpeg is required by yt-dlp for merging separate video/audio streams
# and for audio-only extraction.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY templates ./templates
COPY gunicorn_conf.py .

RUN useradd -m appuser \
    && mkdir -p /srv/app/downloads_tmp \
    && chown -R appuser:appuser /srv/app
USER appuser

ENV PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["gunicorn", "-c", "gunicorn_conf.py", "app.main:app"]
