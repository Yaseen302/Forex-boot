#!/usr/bin/env bash
set -euo pipefail
cd /workspace/Forex-boot
python -m venv .venv
.venv/bin/python -m pip install --cache-dir /workspace/.pip-cache -r requirements-dev.txt
cd frontend
npm ci --cache /workspace/.npm-cache --no-audit --no-fund
npm run build
cd ..
.venv/bin/python -m pytest -q
