#!/usr/bin/env bash
# One-command start: creates the venv, installs deps, builds data+model if
# missing, and serves the portal on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi
if [ ! -f models/risk_model.json ]; then
  .venv/bin/python -m risklens.pipeline
fi
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"
