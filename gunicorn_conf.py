import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
worker_class = "uvicorn.workers.UvicornWorker"

# IMPORTANT: task/progress state lives in each worker's process memory
# (see app/downloader.py _TASKS). Concurrency for the actual downloads is
# already handled internally via a ThreadPoolExecutor + semaphore, so a
# single worker can serve many simultaneous jobs (this is an I/O-bound
# workload, not CPU-bound). If you need > 1 gunicorn worker for higher HTTP
# throughput, you MUST either (a) enable sticky sessions on your load
# balancer/reverse proxy so a client's /api/status and /api/file calls hit
# the same worker that started its download, or (b) swap the in-memory
# _TASKS dict for a shared store such as Redis. Absent one of those, keep
# WEB_CONCURRENCY=1.
workers = int(os.environ.get("WEB_CONCURRENCY", 1))

timeout = 300          # downloads can take a while; don't kill workers mid-job
graceful_timeout = 30
keepalive = 5

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
