"""Site-specific 內容抽取規則 — 對應 spec-18 / task-18 步驟 1。

學生轉題目時把自己領域目標站加進來。

每條規則：
- main_selector: 用 CSS selector 抽主內容（None → readability 自動推）
- remove_selectors: 從抽出的主內容裡額外移除（nav / sidebar / TOC）
- wait_selector: page.goto 後等這個 selector 出現才視為載完
"""

from __future__ import annotations

from urllib.parse import urlparse


DEFAULT_RULE: dict = {
    "main_selector": None,
    "remove_selectors": [],
    "wait_selector": None,
}


SITE_RULES: dict[str, dict] = {
    "nextjs.org": {
        "main_selector": "main article",
        "remove_selectors": ["nav", ".sidebar", "[class*='Toc']"],
        "wait_selector": "main article",
    },
    "react.dev": {
        "main_selector": "article",
        "remove_selectors": ["nav", "[class*='Toc']"],
        "wait_selector": "article",
    },
    # 範例：學生新增自己的站
    # "your-domain.com": {...},
}


def rule_for(url: str) -> dict:
    host = urlparse(url).netloc.replace("www.", "")
    return {**DEFAULT_RULE, **SITE_RULES.get(host, {})}
