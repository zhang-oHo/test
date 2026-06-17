"""PDF ingester — 用 pdfplumber 抽 text，per-page 切 DocumentSection。

對應 spec-25 / task-25 步驟 5。

策略：
- 用 pdfplumber 抽 layout-aware text（保留段落 / 表格結構）
- 每個 PDF page → 一個 DocumentSection，page_number 流入 metadata
- section_path 從 PDF outline (bookmarks) 對應（簡化版未實作；學生需要時擴充）
- 抽不到文字（掃描 PDF）的 page → 暫跳過；可選 OCR fallback
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from app.ingest.document import Document, DocumentSection

logger = logging.getLogger(__name__)


class PdfIngester:
    name = "pdf"

    def __init__(
        self,
        paths: list[Path | str],
        *,
        category: str,
        use_ocr: bool = False,
    ) -> None:
        self._paths = [Path(p) for p in paths]
        self._category = category
        self._use_ocr = use_ocr

    def required_settings(self) -> list[str]:
        return []

    async def yield_documents(self) -> AsyncIterator[Document]:
        for path in self._paths:
            doc = self._build_document(path)
            if doc is not None:
                yield doc
            else:
                logger.warning("PDF %s yielded no extractable text; skipped", path)

    def _build_document(self, path: Path) -> Document | None:
        import pdfplumber

        sections: list[DocumentSection] = []
        full_text_parts: list[str] = []

        with pdfplumber.open(path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if not text.strip() and self._use_ocr:
                    text = self._ocr_page(page)
                text = text.strip()
                if not text:
                    continue
                sections.append(
                    DocumentSection(text=text, page_number=page_num)
                )
                full_text_parts.append(text)

        if not sections:
            return None

        full_text = "\n".join(full_text_parts)
        content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()[:16]
        return Document(
            source_id=str(path),
            source_type="pdf",
            source_url=f"file://{path.absolute()}",
            title=path.stem,
            sections=sections,
            fetched_at=datetime.now(timezone.utc),
            content_hash=content_hash,
            category=self._category,
            tags=[path.stem],
            metadata={"pages": len(sections)},
        )

    def _ocr_page(self, page) -> str:
        """OCR fallback；需 pip install -e ".[ocr]"。預設關閉。"""
        try:
            import pytesseract
            img = page.to_image().original
            return pytesseract.image_to_string(img) or ""
        except ImportError:
            logger.warning("OCR requested but pytesseract not installed")
            return ""
        except Exception:
            logger.exception("OCR failed for page")
            return ""
