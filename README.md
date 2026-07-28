# OmniGrab — Universal Media Downloader

A self-hosted, mobile-friendly web app for fetching video/audio from YouTube,
Instagram, TikTok, X/Twitter, Facebook, Reddit, Vimeo, SoundCloud and hundreds
of other sites, powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) and
FastAPI.

## ⚖️ Before you deploy this

This tool can fetch copyrighted media. Running a public instance that lets
strangers redistribute other people's copyrighted content may violate the
law in your jurisdiction and almost certainly violates the source
platforms' Terms of Service. You are responsible for how you operate and
use this software. Sensible defaults for a personal/internal deployment:

- Put it behind auth (see "Adding authentication" below) rather than exposing
  it publicly.
- Keep it for content you own, that's Creative Commons/public domain, or
  that you otherwise have clear rights to save.
- Don't remove the in-app disclaimer.

## Features

- Paste any supported URL → fetch title, thumbnail, duration, uploader, and
  every available format (progressive video, video-only, and audio-only).
- One-tap download with a live progress bar (percent, speed, ETA).
- Fully responsive, dark/light theme, keyboard accessible, reduced-motion
  aware.
- Files are streamed to the browser and deleted from the server immediately
  after — nothing is hosted or retained.
- SSRF guard (blocks requests to private/internal IP ranges), per-IP rate
  limiting, request size caps, and a background sweep that purges any
  orphaned temp files.
- Docker + gunicorn/uvicorn config, nginx reverse-proxy example, ready for a
  VPS, Fly.io, Render, Railway, or any container host.

## Architecture

```
Browser  ──POST /api/info──────▶  FastAPI  ──▶ yt-dlp (metadata only)
         ◀── formats/thumbnail ──┘

Browser  ──POST /api/download──▶  FastAPI ──▶ background thread ──▶ yt-dlp (+ffmpeg)
         ◀── {task_id} ──────────┘                 │
Browser  ──GET /api/status/:id──▶  in-memory task table  ◀──── progress hooks
Browser  ──GET /api/file/:id────▶  streams file, then deletes temp dir
```

Downloads run in a `ThreadPoolExecutor` (yt-dlp/ffmpeg are I/O + subprocess
bound, so threads are sufficient — no need for a separate task queue at
small-to-medium scale). A `Semaphore` caps how many downloads run at once
(`MAX_CONCURRENT_DOWNLOADS`), so one server can't be overwhelmed.

## Quick start (local)

```bash
git clone <this-repo>
cd social-downloader
cp .env.example .env
./run.sh
# open http://localhost:8000
```

You'll need `ffmpeg` installed locally (`apt install ffmpeg` / `brew install
ffmpeg`) for format merging and audio extraction to work outside Docker.

## Quick start (Docker — recommended for production)

```bash
docker compose up --build -d
# open http://localhost
```

This runs the FastAPI app behind an nginx reverse proxy configured for large
file transfers and long-running requests. Edit `nginx.conf` and set your
domain + TLS certs before exposing it to the internet.

## Configuration

All settings are environment variables (see `.env.example`):

| Variable                     | Purpose                                             |
|-------------------------------|------------------------------------------------------|
| `ALLOWED_ORIGINS`              | JSON array of allowed CORS origins                   |
| `MAX_CONCURRENT_DOWNLOADS`     | Global cap on simultaneous yt-dlp jobs                |
| `TASK_TTL_SECONDS`             | How long a finished-but-uncollected file is kept      |
| `CLEANUP_INTERVAL_SECONDS`     | How often the housekeeping sweep runs                 |
| `MAX_VIDEO_DURATION_SECONDS`   | Safety cap to reject extremely long media              |
| `RATE_LIMIT`                   | Per-IP rate limit for `/api/info` and `/api/download` |
| `COOKIES_FILE`                 | Optional path to a `cookies.txt` for gated content    |

## Scaling beyond one process

Task/progress state is kept in each worker's process memory. A single
gunicorn/uvicorn worker already handles many concurrent downloads (this is
an I/O-bound workload), so **the default is `WEB_CONCURRENCY=1`**. If you
need more than one process:

- enable sticky sessions on your load balancer so a client's `/api/status`
  and `/api/file` calls land on the same worker that started the job, **or**
- replace the in-memory task dict in `app/downloader.py` with a shared store
  (Redis is the natural fit) and move the download job to a real task queue
  (Celery/RQ/Arq).

## Adding authentication

This project ships without auth so it's easy to adapt to whatever you
already use. The simplest options:

- Put nginx in front with HTTP Basic Auth (`auth_basic` directive).
- Add a reverse proxy like Authelia/Tailscale in front of the whole stack.
- Or add a FastAPI dependency (e.g. an API key header check) to the routes
  in `app/main.py`.

## Project layout

```
app/
  main.py        FastAPI routes
  downloader.py  yt-dlp wrapper, task manager, SSRF guard, cleanup
  models.py      Pydantic request/response schemas
  config.py      Environment-driven settings
static/          CSS + JS for the UI
templates/       Jinja2 HTML template
Dockerfile, docker-compose.yml, nginx.conf, gunicorn_conf.py
```

## Updating yt-dlp

Sites change frequently and yt-dlp ships fixes often. Pin a recent version
in `requirements.txt` and update it regularly:

```bash
pip install -U yt-dlp
pip freeze | grep yt-dlp   # copy the new pin into requirements.txt
```

## License

Use this however you like for your own projects. It has no affiliation with
any of the platforms it can fetch from.
