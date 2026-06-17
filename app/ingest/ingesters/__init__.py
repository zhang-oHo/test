"""Concrete ingesters. 對應 spec-25 / task-25 步驟 4-7。"""

from app.ingest.ingesters.csv_rows import CsvIngester, CsvIngesterConfig
from app.ingest.ingesters.markdown_files import MarkdownIngester
from app.ingest.ingesters.pdf import PdfIngester
from app.ingest.ingesters.supabase_articles import SupabaseArticleIngester
from app.ingest.ingesters.web import WebIngester

__all__ = [
    "CsvIngester",
    "CsvIngesterConfig",
    "MarkdownIngester",
    "PdfIngester",
    "SupabaseArticleIngester",
    "WebIngester",
]
