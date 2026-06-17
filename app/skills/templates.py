SKILL_TEMPLATE = """---
skill_id: example_skill
name: 範例技能
category: general
version: 0.1.0
description: 描述這個 skill 的使用情境。
use_when:
  - 什麼時候使用
avoid_when:
  - 什麼時候不要使用
default_temperature: 0.4
rag_categories:
  - general
---

在這裡放 skill 的 system prompt 與操作規則。
"""
