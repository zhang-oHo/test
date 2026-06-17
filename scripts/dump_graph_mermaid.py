"""產生三 variant 的 mermaid 拓撲圖到 docs/ai-agent/examples/。

用法：
    python scripts/dump_graph_mermaid.py

不需要外部服務（用 stub 即可 build graph）；產出檔案可貼到 mermaid.live 預覽。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 用 conftest 的 stub services 不需要 .env / Supabase
from tests.conftest import (  # type: ignore[import-not-found]
    _StubResponder,
    _StubRetriever,
    _StubRouter,
    _make_services,
)
from app.graph.variants import VARIANT_BUILDERS


def main() -> None:
    services = _make_services(
        router=_StubRouter(is_rag_required=True),
        retriever=_StubRetriever(),
        responder=_StubResponder(),
    )
    out_dir = PROJECT_ROOT / "docs" / "ai-agent" / "examples"
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, builder in VARIANT_BUILDERS.items():
        graph = builder(services)
        mermaid = graph.get_graph().draw_mermaid()
        out_path = out_dir / f"graph-{name}.mermaid"
        out_path.write_text(mermaid, encoding="utf-8")
        print(f"wrote {out_path.relative_to(PROJECT_ROOT)} ({len(mermaid)} chars)")


if __name__ == "__main__":
    main()
