"""GraphTracer + ContextVar dispatch + @traced decorator。

對應 spec-22 / task-22 步驟 3-4。

設計重點：
1. ContextVar 而非 service-injected：讓 LLM provider 內部呼叫 record_llm_call_if_traced
   時不需要每次傳 services 進去——provider 介面 `complete(prompt)` 維持單參數
2. 沒進 tracer context（測試 / eval）就 no-op，無 import error
3. node 用 @traced("name") 裝飾即可，不污染 node 主邏輯
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from app.observability.pricing import estimate_cost_usd

logger = logging.getLogger("observability")

_current_tracer: ContextVar["GraphTracer | None"] = ContextVar(
    "current_tracer", default=None
)


def get_current_tracer() -> "GraphTracer | None":
    return _current_tracer.get()


def set_current_tracer(tracer: "GraphTracer | None"):
    """回傳 token；caller 用 reset_current_tracer 還原。"""
    return _current_tracer.set(tracer)


def reset_current_tracer(token) -> None:
    _current_tracer.reset(token)


@dataclass
class _Span:
    node: str
    started_at: float
    ended_at: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        end = self.ended_at or time.time()
        return int((end - self.started_at) * 1000)


@dataclass
class GraphTracer:
    thread_id: str
    variant: str
    started_at: float = field(default_factory=time.time)
    events: list[dict] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    finished_at: float | None = None

    @contextmanager
    def span(self, *, node: str, **extra) -> Iterator[_Span]:
        s = _Span(node=node, started_at=time.time(), extra=dict(extra))
        self.events.append({
            "phase": "node_enter",
            "node": node,
            "ts": s.started_at,
            **extra,
        })
        try:
            yield s
        finally:
            s.ended_at = time.time()
            self.events.append({
                "phase": "node_exit",
                "node": node,
                "duration_ms": s.duration_ms,
                "ts": s.ended_at,
                **extra,
            })

    def record_llm_call(
        self,
        *,
        node: str | None = None,
        model: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        duration_ms: int,
    ) -> None:
        cost = estimate_cost_usd(
            model=model, input_tokens=input_tokens, output_tokens=output_tokens
        )
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += cost
        self.events.append({
            "phase": "llm_call",
            "node": node or "(unknown)",
            "model": model,
            "provider": provider,
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "cached": cached_tokens,
            },
            "duration_ms": duration_ms,
            "estimated_cost_usd": cost,
            "ts": time.time(),
        })

    def finalize(self) -> dict:
        if self.finished_at is None:
            self.finished_at = time.time()
        node_timings: list[dict] = []
        in_progress: dict[str, float] = {}
        for ev in self.events:
            if ev["phase"] == "node_enter":
                in_progress[ev["node"]] = ev["ts"]
            elif ev["phase"] == "node_exit":
                in_progress.pop(ev["node"], None)
                node_timings.append({
                    "node": ev["node"],
                    "duration_ms": ev["duration_ms"],
                })
        return {
            "thread_id": self.thread_id,
            "variant": self.variant,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_duration_ms": int((self.finished_at - self.started_at) * 1000),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "node_timings": node_timings,
            "events": self.events,
        }


@dataclass
class TracerRegistry:
    """每個 graph invocation 建一個 tracer，跑完寫 trace JSON。

    `persist=True` 時同時把 finalize 的 payload 透過 traces_repo 寫進 Supabase
    `graph_traces` 表（spec-22 §Supabase Schema）；traces_repo=None 時退化為
    只寫本機檔案，並在第一次 persist 嘗試時 log 一筆 warning。
    """

    trace_dir: Path
    persist: bool = False
    traces_repo: Any = None  # app.storage.traces_repo.TracesRepository | None

    def __post_init__(self):
        self.trace_dir = Path(self.trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self._persist_warned = False

    def start(self, *, thread_id: str, variant: str) -> GraphTracer:
        return GraphTracer(thread_id=thread_id, variant=variant)

    def write_trace(self, tracer: GraphTracer) -> Path:
        """同步寫檔（供 scripts / eval 等非 async 呼叫端使用）。

        sync 路徑無法 await traces_repo（async）；persist 開啟時 caller 應走
        async_write_trace 才能同步落 Supabase。本路徑只警告一次。
        """
        payload = tracer.finalize()
        path = self._write_local(payload, tracer.thread_id)
        if self.persist and not self._persist_warned:
            logger.warning(
                "TracerRegistry.write_trace called sync but persist=True; "
                "Supabase write skipped — use async_write_trace from async contexts."
            )
            self._persist_warned = True
        return path

    async def async_write_trace(self, tracer: GraphTracer) -> Path:
        """非同步：本機 .traces JSON + （opt-in）Supabase graph_traces 一起寫。"""
        payload = tracer.finalize()
        path = await asyncio.to_thread(self._write_local, payload, tracer.thread_id)
        if self.persist:
            if self.traces_repo is None:
                if not self._persist_warned:
                    logger.warning(
                        "OBSERVABILITY_PERSIST=true but traces_repo is None; "
                        "skipping Supabase write. Wire TracesRepository in dependencies."
                    )
                    self._persist_warned = True
            else:
                try:
                    await self.traces_repo.insert(payload)
                except Exception:
                    logger.exception("traces_repo.insert failed (non-fatal)")
        return path

    def _write_local(self, payload: dict, thread_id: str) -> Path:
        # 檔名 sanitize：thread_id 可能含 "/" 等
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in thread_id)
        path = self.trace_dir / f"{safe}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path


_current_node_name: ContextVar[str | None] = ContextVar("current_node_name", default=None)


def record_llm_call_if_traced(
    *, model: str, provider: str, input_tokens: int, output_tokens: int,
    cached_tokens: int = 0, duration_ms: int,
) -> None:
    """LLM provider 內呼叫；無 tracer context 時 no-op。

    `node` 由 ContextVar 自動取得（@traced 裝飾的 node 進入時會把 node name 推上 stack）。
    """
    tracer = get_current_tracer()
    if tracer is None:
        return
    tracer.record_llm_call(
        node=_current_node_name.get(),
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        duration_ms=duration_ms,
    )


def traced(node_name: str):
    """Decorator：包裝 graph node，自動產生 span 並把 node_name 推進 ContextVar。

    無 tracer context 時走 fast path：只設 node_name（給 LLM provider 標記用），
    不做 span。
    """

    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(state, services):
            tracer = get_current_tracer()
            node_token = _current_node_name.set(node_name)
            try:
                if tracer is None:
                    return await fn(state, services)
                with tracer.span(
                    node=node_name,
                    retry=state.get("reflection_retry", 0),
                ):
                    return await fn(state, services)
            finally:
                _current_node_name.reset(node_token)

        return wrapper

    return deco
