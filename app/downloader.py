"""
Wraps yt-dlp: metadata extraction, format normalization, background download
jobs with progress tracking, and safe cleanup of temporary files.
"""
from __future__ import annotations

import ipaddress
import re
import shutil
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yt_dlp

from app.config import settings
from app.models import FormatOut, MediaInfoOut, TaskStatusOut

_executor = ThreadPoolExecutor(max_workers=settings.MAX_CONCURRENT_DOWNLOADS)
_download_semaphore = threading.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)

_TASKS: dict[str, dict[str, Any]] = {}
_TASKS_LOCK = threading.Lock()


class UnsafeURLError(ValueError):
    pass


class ExtractionError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Security: block requests aimed at internal/private infrastructure (SSRF)
# --------------------------------------------------------------------------
def assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http/https URLs are supported.")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("Could not determine the host of that URL.")
    if host.lower() in ("localhost",):
        raise UnsafeURLError("That host is not allowed.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Let yt-dlp attempt/raise its own clearer error rather than block here.
        return
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
        ):
            raise UnsafeURLError("Requests to internal/private addresses are not allowed.")


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": settings.SOCKET_TIMEOUT,
        "nocheckcertificate": False,
        "extractor_retries": 2,
    }
    if settings.COOKIES_FILE:
        opts["cookiefile"] = settings.COOKIES_FILE
    return opts


def _classify(fmt: dict) -> str:
    has_v = fmt.get("vcodec") not in (None, "none")
    has_a = fmt.get("acodec") not in (None, "none")
    if has_v and has_a:
        return "video"
    if has_v and not has_a:
        return "video_only"
    return "audio"


def fetch_info(url: str) -> MediaInfoOut:
    assert_public_url(url)
    opts = _base_opts()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise ExtractionError(str(exc)) from exc

    if info is None:
        raise ExtractionError("No information could be extracted for that URL.")

    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        if not entries:
            raise ExtractionError("That playlist appears to be empty.")
        info = entries[0]

    duration = info.get("duration")
    if duration and duration > settings.MAX_VIDEO_DURATION_SECONDS:
        raise ExtractionError("This media exceeds the maximum allowed duration.")

    raw_formats = info.get("formats") or []
    formats: list[FormatOut] = []
    seen = set()
    for f in raw_formats:
        if f.get("format_id") is None:
            continue
        kind = _classify(f)
        if kind == "video_only" and not f.get("height"):
            continue
        resolution = None
        if f.get("height"):
            resolution = f"{f.get('width') or '?'}x{f.get('height')}"
        elif kind == "audio":
            resolution = "audio only"
        key = (f["format_id"], resolution, kind)
        if key in seen:
            continue
        seen.add(key)
        formats.append(
            FormatOut(
                format_id=f["format_id"],
                ext=f.get("ext", "mp4"),
                resolution=resolution,
                fps=f.get("fps"),
                vcodec=f.get("vcodec"),
                acodec=f.get("acodec"),
                filesize=f.get("filesize") or f.get("filesize_approx"),
                tbr=f.get("tbr"),
                note=f.get("format_note"),
                kind=kind,
            )
        )

    def sort_key(fo: FormatOut):
        order = {"video": 0, "video_only": 1, "audio": 2}
        height = 0
        if fo.resolution and "x" in fo.resolution:
            try:
                height = int(fo.resolution.split("x")[1])
            except ValueError:
                height = 0
        return (order.get(fo.kind, 3), -height, -(fo.tbr or 0))

    formats.sort(key=sort_key)

    return MediaInfoOut(
        title=info.get("title", "Untitled"),
        thumbnail=info.get("thumbnail"),
        duration=duration,
        uploader=info.get("uploader"),
        extractor=info.get("extractor_key", "generic"),
        webpage_url=info.get("webpage_url", url),
        formats=formats,
    )


def _set_task(task_id: str, **kwargs) -> None:
    with _TASKS_LOCK:
        _TASKS.setdefault(task_id, {})
        _TASKS[task_id].update(kwargs)
        _TASKS[task_id]["updated_at"] = time.time()


def get_task(task_id: str) -> dict | None:
    with _TASKS_LOCK:
        t = _TASKS.get(task_id)
        return dict(t) if t else None


def _progress_hook(task_id: str):
    def hook(d: dict):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            percent = round((done / total) * 100, 1) if total else 0.0
            _set_task(
                task_id,
                status="downloading",
                percent=percent,
                speed=_human_rate(d.get("speed")),
                eta=_human_eta(d.get("eta")),
            )
        elif d["status"] == "finished":
            _set_task(task_id, status="processing", percent=99.0)
    return hook


def _human_rate(v) -> str | None:
    if not v:
        return None
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if v < 1024:
            return f"{v:.1f}{unit}"
        v /= 1024
    return f"{v:.1f}TB/s"


def _human_eta(v) -> str | None:
    if v is None:
        return None
    m, s = divmod(int(v), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9 ._-]+")


def _safe_filename(name: str, fallback: str) -> str:
    name = _SAFE_NAME_RE.sub("", name).strip() or fallback
    return name[:120]


def _run_download(task_id: str, url: str, format_id: str, audio_only: bool):
    job_dir = settings.TEMP_DIR / task_id
    job_dir.mkdir(parents=True, exist_ok=True)

    fmt_selector = f"{format_id}+bestaudio/best" if not audio_only else format_id

    ydl_opts = {
        **_base_opts(),
        "format": fmt_selector,
        "outtmpl": str(job_dir / "%(title).100s.%(ext)s"),
        "progress_hooks": [_progress_hook(task_id)],
        "merge_output_format": "mp4",
    }
    if audio_only:
        ydl_opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]

    with _download_semaphore:
        try:
            _set_task(task_id, status="downloading", percent=0.0)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            produced = sorted(job_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            produced = [p for p in produced if p.is_file()]
            if not produced:
                raise ExtractionError("Download finished but no output file was found.")
            final_file = produced[0]
            _set_task(
                task_id,
                status="finished",
                percent=100.0,
                filename=final_file.name,
                filepath=str(final_file),
            )
        except yt_dlp.utils.DownloadError as exc:
            _set_task(task_id, status="error", error=str(exc))
            shutil.rmtree(job_dir, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the client
            _set_task(task_id, status="error", error=str(exc))
            shutil.rmtree(job_dir, ignore_errors=True)


def start_download(url: str, format_id: str, audio_only: bool) -> str:
    assert_public_url(url)
    task_id = uuid.uuid4().hex
    _set_task(task_id, status="queued", percent=0.0, created_at=time.time())
    _executor.submit(_run_download, task_id, url, format_id, audio_only)
    return task_id


def task_status(task_id: str) -> TaskStatusOut:
    t = get_task(task_id)
    if not t:
        return TaskStatusOut(task_id=task_id, status="error", error="Unknown task.")
    return TaskStatusOut(
        task_id=task_id,
        status=t.get("status", "queued"),
        percent=t.get("percent", 0.0),
        speed=t.get("speed"),
        eta=t.get("eta"),
        filename=t.get("filename"),
        error=t.get("error"),
    )


def cleanup_task(task_id: str) -> None:
    """Remove a task's temp files immediately (called after the file is served)."""
    job_dir = settings.TEMP_DIR / task_id
    shutil.rmtree(job_dir, ignore_errors=True)
    with _TASKS_LOCK:
        _TASKS.pop(task_id, None)


def sweep_expired_tasks() -> None:
    """Periodic housekeeping: remove stale tasks/files that were never collected."""
    now = time.time()
    with _TASKS_LOCK:
        stale = [
            tid for tid, t in _TASKS.items()
            if now - t.get("updated_at", now) > settings.TASK_TTL_SECONDS
        ]
    for tid in stale:
        cleanup_task(tid)

    # Also sweep orphan directories with no matching task entry.
    if settings.TEMP_DIR.exists():
        with _TASKS_LOCK:
            active_ids = set(_TASKS.keys())
        for child in settings.TEMP_DIR.iterdir():
            if child.is_dir() and child.name not in active_ids:
                if now - child.stat().st_mtime > settings.TASK_TTL_SECONDS:
                    shutil.rmtree(child, ignore_errors=True)
