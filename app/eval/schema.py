"""Golden case schema for evaluation framework.

對應 spec-20 / task-20。實作上把 schema 放在 app/eval/（task 原稿放 tests/）：
避免 app → tests 的反向依賴，wheel 包仍可用 EvalRunner 跑自帶 case set。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class GoldenCase(BaseModel):
    id: str
    query: str
    category: str | None = None
    expected_chunks: list[str] = Field(default_factory=list, description="chunk_id 應命中清單")
    must_cite_sources: list[str] = Field(
        default_factory=list, description="回覆必須引用的 source 子字串"
    )
    forbidden_phrases: list[str] = Field(
        default_factory=list, description="回覆禁止出現的字串"
    )
    expect_clarification: bool = False
    notes: str = ""


class GoldenCaseSet(BaseModel):
    cases: list[GoldenCase]

    @classmethod
    def load(cls, path: Path) -> "GoldenCaseSet":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, list):
            data = {"cases": data}
        return cls(**data)
