#!/usr/bin/env bash
set -euo pipefail

# Local development runner (auto-reload). For production use Docker / gunicorn.
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -r requirements.txt --quiet
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
