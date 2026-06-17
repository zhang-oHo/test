"""CSV ingester — 適用 FAQ 表 / SKU 規格表 / 結構化資料。

對應 spec-25 / task-25 步驟 7。兩種模式：
- row_per_doc：每列一份 Document（FAQ 表常用）
- table_as_doc：整表一份 Document（小型參考表）

`text_columns` 串接成 section.text；`metadata_columns` 寫進 metadata 不進 embedding。
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Literal

from app.ingest.document import Document, DocumentSection


@dataclass
class CsvIngesterConfig:
    path: str | Path
    mode: Literal["row_per_doc", "table_as_doc"] = "row_per_doc"
    text_columns: list[str] = field(default_factory=list)
    metadata_columns: list[str] = field(default_factory=list)
    title_column: str | None = None        # row_per_doc 用
    title_template: str = "{title}"        # 若 title_column 為空，用此 template
    encoding: str = "utf-8"


class CsvIngester:
    name = "csv"

    def __init__(self, config: CsvIngesterConfig, *, category: str) -> None:
        self._cfg = config
        self._category = category
        self._path = Path(config.path)

    def required_settings(self) -> list[str]:
        return []

    async def yield_documents(self) -> AsyncIterator[Document]:
        with self._path.open(encoding=self._cfg.encoding) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            return

        if self._cfg.mode == "row_per_doc":
            for idx, row in enumerate(rows, start=1):
                doc = self._row_to_doc(row, idx=idx)
                if doc is not None:
                    yield doc
        else:
            doc = self._table_to_doc(rows)
            if doc is not None:
                yield doc

    def _row_text(self, row: dict) -> str:
        cols = self._cfg.text_columns or list(row.keys())
        return "\n".join(f"{col}: {row.get(col, '')}" for col in cols if row.get(col))

    def _row_metadata(self, row: dict) -> dict:
        return {col: row.get(col) for col in self._cfg.metadata_columns if col in row}

    def _row_to_doc(self, row: dict, *, idx: int) -> Document | None:
        text = self._row_text(row)
        if not text.strip():
            return None
        if self._cfg.title_column and row.get(self._cfg.title_column):
            title = str(row[self._cfg.title_column])
        else:
            try:
                title = self._cfg.title_template.format(**row)
            except (KeyError, IndexError):
                title = f"{self._path.stem}#{idx}"

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return Document(
            source_id=f"{self._path}#{idx}",
            source_type="csv",
            source_url=f"file://{self._path.absolute()}",
            title=title[:120],
            sections=[DocumentSection(text=text, metadata=self._row_metadata(row))],
            fetched_at=datetime.now(timezone.utc),
            content_hash=content_hash,
            category=self._category,
            tags=[self._path.stem],
            metadata={"row_index": idx},
        )

    def _table_to_doc(self, rows: list[dict]) -> Document | None:
        text = "\n\n".join(self._row_text(r) for r in rows)
        if not text.strip():
            return None
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return Document(
            source_id=str(self._path),
            source_type="csv",
            source_url=f"file://{self._path.absolute()}",
            title=self._path.stem,
            sections=[DocumentSection(text=text)],
            fetched_at=datetime.now(timezone.utc),
            content_hash=content_hash,
            category=self._category,
            tags=[self._path.stem],
            metadata={"row_count": len(rows)},
        )
