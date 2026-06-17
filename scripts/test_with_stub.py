"""不打 LINE 也能跑完整 graph：用 stub channel 灌訊息進去看回應。

對應 docs/Lesson_5_Production/ch03 §Step 5。

用法：
    python scripts/test_with_stub.py
    python scripts/test_with_stub.py --message "Supabase HNSW 怎麼設？"
    python scripts/test_with_stub.py --user U_dev_001 --message "你好" --no-dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.channels.base import ChannelInput  # noqa: E402
from app.dependencies import get_runtime_services  # noqa: E402
from app.line.webhook import process_channel_input  # noqa: E402


async def main(args: argparse.Namespace) -> None:
    services = get_runtime_services()

    if "stub" not in services.channels:
        print("!! services.channels 沒有 'stub' adapter，無法跑此 script", file=sys.stderr)
        sys.exit(1)

    # 預設用 U_demo_* 觸發 dry_run（不寫真實 message log）
    user_id = args.user or "U_demo_stub_001"
    if args.no_dry_run and user_id.startswith(("U_demo", "U_eval")):
        print(
            f"!! user_id={user_id} 仍會觸發 dry_run（前綴是 U_demo/U_eval），"
            "請改用其他前綴或拿掉 --no-dry-run",
            file=sys.stderr,
        )

    inp = ChannelInput(
        channel="stub",
        external_user_id=user_id,
        external_message_id=args.message_id,
        raw_text=args.message,
    )

    print(f"→ Sending to graph (variant={services.settings.graph_variant})")
    print(f"  user_id        = {user_id}")
    print(f"  message_id     = {args.message_id}")
    print(f"  raw_text       = {args.message!r}")
    print()

    await process_channel_input(inp, services)

    stub = services.channels["stub"]
    if not stub.pushed:
        print("(graph 沒推任何訊息——可能被 input_guard 擋下，或落到 HITL pending)")
        return

    print(f"=== Pushed messages ({len(stub.pushed)} batch) ===")
    for i, (recipient_id, messages) in enumerate(stub.pushed, 1):
        print(f"\n[batch {i}] recipient={recipient_id}")
        for j, m in enumerate(messages, 1):
            print(f"  --- msg {j} ---")
            print(m)

    # 若有 trace，提示位置
    trace_path = PROJECT_ROOT / ".traces" / f"stub-{user_id}-{args.message_id}.json"
    if trace_path.exists():
        try:
            data = json.loads(trace_path.read_text())
            cost = data.get("total_cost_usd")
            dur = data.get("total_duration_ms")
            print(f"\n=== trace ===")
            print(f"  file:     {trace_path}")
            print(f"  cost:     ${cost:.6f}" if cost is not None else "")
            print(f"  duration: {dur}ms" if dur is not None else "")
        except Exception:
            pass


def cli() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--message", default="你好，介紹一下你自己")
    p.add_argument("--user", default=None, help="external_user_id；空則用 U_demo_stub_001")
    p.add_argument("--message-id", default="stub_msg_001")
    p.add_argument(
        "--no-dry-run",
        action="store_true",
        help="預設 U_demo_* 前綴會觸發 dry_run；本旗標警告但不阻擋",
    )
    args = p.parse_args()
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
