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

if [[ -z "${SUPABASE_DB_URL:-}" ]]; then
  echo "SUPABASE_DB_URL is required. Set it in .env before running this script." >&2
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required but was not found in PATH." >&2
  exit 1
fi

echo "Applying supabase/schema.sql"
psql "${SUPABASE_DB_URL}" -v ON_ERROR_STOP=1 -f "${PROJECT_ROOT}/supabase/schema.sql"

echo "Applying supabase/functions.sql"
psql "${SUPABASE_DB_URL}" -v ON_ERROR_STOP=1 -f "${PROJECT_ROOT}/supabase/functions.sql"

echo "Applying supabase/seed.sql"
psql "${SUPABASE_DB_URL}" -v ON_ERROR_STOP=1 -f "${PROJECT_ROOT}/supabase/seed.sql"

if [[ "${SKIP_SKILL_SEED:-0}" == "1" ]]; then
  echo "Skipping skill seed because SKIP_SKILL_SEED=1"
  exit 0
fi

echo "Seeding skills into ai_skills"
"${PROJECT_ROOT}/.venv/bin/python" "${PROJECT_ROOT}/scripts/seed_skills.py"

echo "Supabase bootstrap completed."
