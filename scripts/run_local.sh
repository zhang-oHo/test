#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

PORT="${APP_PORT:-8000}"

cd "${PROJECT_ROOT}"
exec "${PROJECT_ROOT}/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port "${PORT}" --reload
