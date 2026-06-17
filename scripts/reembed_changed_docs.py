from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ingest_markdown import ingest_path


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--category", default="notes")
    args = parser.parse_args()

    total = 0
    for raw_path in args.paths:
        total += await ingest_path(Path(raw_path), category=args.category)
    print(f"Re-embedded {total} chunks.")


if __name__ == "__main__":
    asyncio.run(main())
