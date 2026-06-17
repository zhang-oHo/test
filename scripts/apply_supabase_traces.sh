#!/usr/bin/env bash
# spec-22 §「介面契約」：套用 graph_traces 表（opt-in）。
# 本機教學 .traces/*.json 已夠用；需要跨 session 累積分析才執行本腳本。
#
# 用法：
#   bash scripts/apply_supabase_traces.sh

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

echo "Applying supabase/observability_schema.sql"
psql "${SUPABASE_DB_URL}" -v ON_ERROR_STOP=1 \
  -f "${PROJECT_ROOT}/supabase/observability_schema.sql"

echo "graph_traces table is ready. Set OBSERVABILITY_PERSIST=true to enable writes."
