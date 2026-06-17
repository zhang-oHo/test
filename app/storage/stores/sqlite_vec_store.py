"""sqlite-vec store — 教學零依賴實作，跑得起來不需任何雲端帳號。

對應 spec-24 / task-24 步驟 3。

限制：
- 純向量檢索（不支援 tsvector hybrid）；keyword_score 永遠 0
- category filter 在 client 端二次過濾（vec0 表不支援 metadata where）
- 維度固定在表建立時，預設 1536（OpenAI text-embedding-3-small）
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import sqlite_vec

from app.rag.schemas import KnowledgeChunk
from app.storage.knowledge_store import (
    KnowledgeChunkInsert,
    SearchFilters,
)


class SqliteVecStore:
    name = "sqlite_vec"

    def __init__(self, *, path: str, dim: int = 1536) -> None:
        self._path = path
        self._dim = dim
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            f"""
            create virtual table if not exists private_knowledge using vec0(
              id text primary key,
              embedding float[{self._dim}]
            );
            create table if not exists private_knowledge_meta (
              id text primary key,
              title text,
              content text not null,
              category text not null,
              tags text default '[]',
              metadata text default '{{}}',
              source_id text,
              source_type text default 'markdown',
              content_hash text not null
            );
            create index if not exists idx_meta_category
              on private_knowledge_meta(category);
            create index if not exists idx_meta_source
              on private_knowledge_meta(source_id);
            """
        )
        self._conn.commit()

    async def search(
        self,
        *,
        query_embedding: list[float],
        query_text: str | None = None,
        filters: SearchFilters | None = None,
        top_k: int = 8,
    ) -> list[KnowledgeChunk]:
        # 取較多候選，client 端 filter 後再切 top_k
        fetch_k = max(top_k * 3, top_k + 10)
        cur = self._conn.execute(
            """
            select pk.id, m.title, m.content, m.category, m.tags, m.metadata, distance
            from private_knowledge pk
            left join private_knowledge_meta m on m.id = pk.id
            where pk.embedding match ?
              and k = ?
            order by distance
            """,
            (sqlite_vec.serialize_float32(query_embedding), fetch_k),
        )
        rows = cur.fetchall()

        out: list[KnowledgeChunk] = []
        cats = filters.categories if filters and filters.categories else None
        for r in rows:
            chunk_id, title, content, category, tags_json, meta_json, distance = r
            if cats and category not in cats:
                continue
            # cosine distance ∈ [0, 2]；轉 score ∈ [0, 1]
            score = max(0.0, 1.0 - (distance / 2.0))
            out.append(
                KnowledgeChunk(
                    id=chunk_id,
                    title=title,
                    content=content or "",
                    category=category or "",
                    tags=json.loads(tags_json or "[]"),
                    metadata=json.loads(meta_json or "{}"),
                    vector_score=score,
                    keyword_score=0.0,
                    combined_score=score,
                )
            )
            if len(out) >= top_k:
                break
        return out

    async def upsert(self, chunks: list[KnowledgeChunkInsert]) -> int:
        for c in chunks:
            # sqlite-vec virtual table 不支援 INSERT OR REPLACE：先刪後加
            self._conn.execute(
                "delete from private_knowledge where id = ?", (c.id,)
            )
            self._conn.execute(
                "insert into private_knowledge(id, embedding) values (?, ?)",
                (c.id, sqlite_vec.serialize_float32(c.embedding)),
            )
            self._conn.execute(
                """insert or replace into private_knowledge_meta
                   (id, title, content, category, tags, metadata,
                    source_id, source_type, content_hash)
                   values (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    c.id, c.title, c.content, c.category,
                    json.dumps(c.tags, ensure_ascii=False),
                    json.dumps(c.metadata, ensure_ascii=False),
                    c.source_id, c.source_type, c.content_hash,
                ),
            )
        self._conn.commit()
        return len(chunks)

    async def delete_by_source(self, source_id: str) -> int:
        cur = self._conn.execute(
            "select id from private_knowledge_meta where source_id = ?",
            (source_id,),
        )
        ids = [r[0] for r in cur.fetchall()]
        for chunk_id in ids:
            self._conn.execute(
                "delete from private_knowledge where id = ?", (chunk_id,)
            )
            self._conn.execute(
                "delete from private_knowledge_meta where id = ?", (chunk_id,)
            )
        self._conn.commit()
        return len(ids)

    async def source_hash(self, source_id: str) -> str | None:
        cur = self._conn.execute(
            "select content_hash from private_knowledge_meta where source_id = ? limit 1",
            (source_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None

    async def health_check(self) -> bool:
        try:
            self._conn.execute("select 1").fetchone()
            return True
        except Exception:
            return False
