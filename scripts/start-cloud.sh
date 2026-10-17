#!/usr/bin/env bash
set -euo pipefail
cd /workspace/Forex-boot
export DATA_SOURCE=synthetic
export ENABLE_DEMO_EXECUTION=0
mkdir -p runtime
if [[ ! -s runtime/api-token ]]; then
  (umask 077; .venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))' > runtime/api-token)
fi
export API_TOKEN="$(cat runtime/api-token)"
exec .venv/bin/python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000 --workers 1
