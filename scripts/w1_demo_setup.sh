#!/usr/bin/env bash
# W1 demo 錄影前的環境準備（不收錄到影片裡）。
# 對應 docs/ai-agent/examples/w1-demo-script.md。
#
# 用法：
#     bash scripts/w1_demo_setup.sh
#
# 完成後攝影師依 w1-demo-script.md 逐幕拍攝。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

DEMO_DIR=/tmp/w1_demo

# 找出能跑的 python：優先 venv，再 fall back 到 python3 / python
if [[ -x ".venv/bin/python" ]]; then
    PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
else
    echo "❌ 找不到 python（venv 也不存在）。先建 venv：python3 -m venv .venv"
    exit 1
fi
echo "使用 Python: $PY"

echo "==> 1/4 安裝依賴（含 crawler extra）"
$PY -m pip install -e ".[dev,crawler]" --quiet

echo "==> 2/4 確認 chromium 已就緒"
$PY -m playwright install chromium >/dev/null

echo "==> 3/4 清空 demo 暫存"
rm -rf "$DEMO_DIR"
mkdir -p "$DEMO_DIR/crawled"

cat > "$DEMO_DIR/urls.txt" << 'EOF'
https://nextjs.org/docs/app/building-your-application/rendering/server-components
https://nextjs.org/docs/app/building-your-application/rendering/client-components
EOF

echo "==> 4/4 確認 .env 與 OpenAI key"
if [[ ! -f .env ]]; then
    echo "❌ .env not found. Copy .env.example and fill OPENAI_API_KEY first."
    exit 1
fi
if ! grep -q "^OPENAI_API_KEY=sk-" .env; then
    echo "⚠️  OPENAI_API_KEY 看起來沒設或非 sk- 開頭；檢查 .env"
fi

# 確認 demo runner 存在於穩定路徑
if [[ ! -f scripts/w1_demo_run.py ]]; then
    echo "⚠️  scripts/w1_demo_run.py 不存在；該檔提供 W1 e2e demo 入口"
fi

echo
echo "✅ 環境就緒。下一步："
echo "   1. 開螢幕錄製（OBS / QuickTime / asciinema）"
echo "   2. 字級調 14–16 pt"
echo "   3. cd $PROJECT_ROOT && clear"
echo "   4. 依 docs/ai-agent/examples/w1-demo-script.md 逐幕拍"
echo
echo "暫存：$DEMO_DIR"
echo "URL list：$DEMO_DIR/urls.txt"
