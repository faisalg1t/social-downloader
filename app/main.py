import asyncio
import contextlib
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.background import BackgroundTask

from app.config import settings
from app.downloader import (
    ExtractionError,
    UnsafeURLError,
    cleanup_task,
    fetch_info,
    get_task,
    start_download,
    sweep_expired_tasks,
    task_status,
)
from app.models import DownloadRequest, MediaInfoOut, TaskStatusOut, URLIn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("omnigrab")

limiter = Limiter(key_func=get_remote_address)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async def cleanup_loop():
        while True:
            await asyncio.sleep(settings.CLEANUP_INTERVAL_SECONDS)
            try:
                sweep_expired_tasks()
            except Exception:  # noqa: BLE001
                logger.exception("Cleanup sweep failed")

    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(settings.BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(settings.BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "app_name": settings.APP_NAME})


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/api/info", response_model=MediaInfoOut)
@limiter.limit(settings.RATE_LIMIT)
async def api_info(request: Request, payload: URLIn):
    if not payload.url:
        raise HTTPException(400, "A URL is required.")
    try:
        info = await asyncio.to_thread(fetch_info, payload.url)
    except UnsafeURLError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ExtractionError as exc:
        raise HTTPException(422, str(exc)) from exc
    return info


@app.post("/api/download")
@limiter.limit(settings.RATE_LIMIT)
async def api_download(request: Request, payload: DownloadRequest):
    if not payload.url or not payload.format_id:
        raise HTTPException(400, "url and format_id are required.")
    try:
        task_id = await asyncio.to_thread(
            start_download, payload.url, payload.format_id, payload.audio_only
        )
    except UnsafeURLError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"task_id": task_id}


@app.get("/api/status/{task_id}", response_model=TaskStatusOut)
async def api_status(task_id: str):
    return task_status(task_id)


@app.get("/api/file/{task_id}")
async def api_file(task_id: str):
    t = get_task(task_id)
    if not t or t.get("status") != "finished" or not t.get("filepath"):
        raise HTTPException(404, "File is not ready or has already been collected.")
    filepath = t["filepath"]
    filename = t.get("filename", "download")
    return FileResponse(
        filepath,
        filename=filename,
        media_type="application/octet-stream",
        background=BackgroundTask(cleanup_task, task_id),
    )
