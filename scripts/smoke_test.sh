#!/usr/bin/env bash
#
# Pre-deploy smoke test — 對應 docs/Lesson_5_Production/ch10 §Step 6。
#
# 跑完 8 步全綠才允許 deploy。任何一步失敗會 exit 1。
#
# 用法：
#     bash scripts/smoke_test.sh
#
# 預設讀 .env；可設 SKIP_GRAPH=true 跳過耗時的 graph 跑通測試。

set -euo pipefail

# 載入 .env（若有）
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . .env
    set +a
fi

step() {
    echo ""
    echo "=== $1 ==="
}

fail() {
    echo "❌ $1" >&2
    exit 1
}

# ─────────────────────────────────────────
step "1. 必要環境變數"
for var in SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY SUPABASE_DB_URL; do
    if [ -z "${!var:-}" ]; then
        fail "$var 未設定"
    else
        echo "✅ $var set"
    fi
done

# AI provider 至少一組
ai_provider="${AI_PROVIDER:-openai}"
case "$ai_provider" in
    openai)        ai_key_var="OPENAI_API_KEY" ;;
    claude)        ai_key_var="ANTHROPIC_API_KEY" ;;
    gemini)        ai_key_var="GEMINI_API_KEY" ;;
    github_copilot) ai_key_var="GITHUB_COPILOT_TOKEN" ;;
    *)             fail "AI_PROVIDER=${ai_provider} 不認識" ;;
esac
if [ -z "${!ai_key_var:-}" ]; then
    fail "$ai_key_var 未設定（AI_PROVIDER=$ai_provider）"
else
    echo "✅ $ai_key_var set"
fi

# LINE 是 optional（HTTP / stub channel 可以無它）
for var in LINE_CHANNEL_SECRET LINE_CHANNEL_ACCESS_TOKEN; do
    if [ -z "${!var:-}" ]; then
        echo "⚠️  $var 未設（LINE channel 不可用，HTTP/stub 仍可跑）"
    else
        echo "✅ $var set"
    fi
done

# ─────────────────────────────────────────
step "2. Supabase 連線"
psql "$SUPABASE_DB_URL" -c "select 1" >/dev/null 2>&1 \
    && echo "✅ DB connect" \
    || fail "Supabase DB 連不上"

# ─────────────────────────────────────────
step "3. Schema 完整性"
for t in ai_skills private_knowledge line_messages retrieval_logs prompt_cache; do
    if psql "$SUPABASE_DB_URL" -c "\\d $t" >/dev/null 2>&1; then
        echo "✅ table $t"
    else
        fail "table $t 不存在；跑 psql -f supabase/schema.sql 套用"
    fi
done

# ─────────────────────────────────────────
step "4. match_private_knowledge RPC"
if psql "$SUPABASE_DB_URL" -c '\df match_private_knowledge' 2>/dev/null \
        | grep -q match_private_knowledge; then
    echo "✅ RPC exists"
else
    fail "match_private_knowledge RPC 不存在；跑 psql -f supabase/functions.sql 套用"
fi

# ─────────────────────────────────────────
step "5. 至少一筆 enabled skill"
count=$(psql "$SUPABASE_DB_URL" -t -c \
    "select count(*) from ai_skills where enabled = true;" | xargs)
if [ "${count:-0}" -gt 0 ]; then
    echo "✅ $count skills enabled"
else
    fail "ai_skills 表沒有 enabled=true 的列；跑 psql -f supabase/seed.sql 或 scripts/seed_skills.py"
fi

# ─────────────────────────────────────────
step "6. 知識庫狀態（warning，不擋部署）"
count=$(psql "$SUPABASE_DB_URL" -t -c \
    "select count(*) from private_knowledge;" | xargs)
if [ "${count:-0}" -gt 0 ]; then
    echo "✅ $count chunks ingested"
else
    echo "⚠️  private_knowledge 為空；RAG query 會走 fallback。先跑 scripts/ingest_markdown.py"
fi

# ─────────────────────────────────────────
step "7. LLM 通"
poetry run python - <<'PYEOF'
import asyncio
import sys
from app.config import get_settings
from app.ai.factory import build_llm

async def main():
    try:
        llm = build_llm(get_settings(), role="router")
        out = await llm.complete("Reply with exactly: OK")
        print(f"✅ LLM responded: {out[:80]!r}")
    except Exception as e:
        print(f"❌ LLM call failed: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

asyncio.run(main())
PYEOF

# ─────────────────────────────────────────
if [ "${SKIP_GRAPH:-false}" = "true" ]; then
    echo ""
    echo "⏭  跳過 graph 跑通測試（SKIP_GRAPH=true）"
else
    step "8. graph 跑通（stub channel）"
    poetry run python - <<'PYEOF'
import asyncio
import sys
from app.dependencies import get_runtime_services
from app.channels.base import ChannelInput
from app.line.webhook import process_channel_input

async def main():
    services = get_runtime_services()
    inp = ChannelInput(
        channel="stub",
        external_user_id="U_demo_smoke",
        external_message_id="smoke_test",
        raw_text="你好",
    )
    try:
        await process_channel_input(inp, services)
    except Exception as e:
        print(f"❌ process_channel_input failed: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    stub = services.channels.get("stub")
    if stub is None or not stub.pushed:
        print("❌ stub channel 沒收到 push", file=sys.stderr)
        sys.exit(1)

    first_msg = stub.pushed[0][1][0] if stub.pushed and stub.pushed[0][1] else ""
    print(f"✅ graph pushed: {first_msg[:80]!r}")

asyncio.run(main())
PYEOF
fi

echo ""
echo "🎉 All smoke tests passed!"
