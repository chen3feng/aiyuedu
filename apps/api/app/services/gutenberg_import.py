"""古腾堡导入：拉取书籍 → 拆章节 → 创建 collection 文件。

从 services/collections.py 拆出（后者负责 collection 的存储 / CRUD / AI 分析，
导入流程是独立入口，依赖方向是本模块 → collections）。
为避免与 collections 形成循环导入，所需的 collections 函数在函数体内延迟导入。
"""
from __future__ import annotations

import re
import time


def slug_from_title(title: str, fallback: str) -> str:
    """从英文书名生成 collection id（限长 + 去前缀噪音）。"""
    # 去掉常见前缀（The / A / An）
    s = re.sub(r"^(the|a|an)\s+", "", (title or "").lower(), flags=re.IGNORECASE)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    # 限长 40 字符，按词边界截断
    if len(s) > 40:
        s = "-".join(s.split("-")[:5])
    return s or fallback


def import_from_gutenberg(book_id: int) -> dict:
    """从古腾堡拉取 + 拆章节 → 创建 collection 文件。

    不做 AI 标注（词汇分析留给后台「重跑 AI 分析」按钮）。

    返回完整 collection dict。失败抛 RuntimeError。
    """
    # analyze_collection 是全本批量任务，已拆到 collection_jobs
    # 且两模块存在双向引用，模块加载期不能互相 import
    from . import gutenberg
    from .collections import _persist, get_collection
    from .collection_jobs import analyze_collection

    data = gutenberg.fetch_book(book_id)
    chapters = gutenberg.split_chapters(data["text"])

    cid = slug_from_title(data["title"], f"gutenberg-{book_id}")
    # 已存在则加后缀
    if get_collection(cid) is not None:
        cid = f"{cid}-{book_id}"

    chapter_dicts = []
    for ch in chapters:
        cid_ch = f"r-{cid}-{ch.index}"
        chapter_dicts.append({
            "index": ch.index,
            "id": cid_ch,
            "title": ch.title,
            "title_zh": "",  # 待后台 AI 补
            "body": ch.body,
            "target_level": 3000,  # 默认初中级
            "glosses": {},
            "terms": {},
            "skip": [],
            "quizzes": [],
        })

    collection = {
        "id": cid,
        "title": data["title"],
        "title_zh": "",  # 待后台 AI 补
        "author": data["author"],
        "source": data["source"],
        "total_chapters": len(chapter_dicts),
        "cover_url": data.get("cover_url") or "",
        "intro_zh": "",  # 待后台 AI 补
        "intro_en": data.get("summary") or "",
        "created_at": round(time.time(), 3),
        "glossary": {},
        "polysemy": {},
        "ai_status": "pending",  # pending / analyzing / done / error
        "ai_reason": "",
        "chapters": chapter_dicts,
    }
    # 自动启动全本 AI 释义（后台线程）：导入即可用，学生打开章节能看到生词
    _persist(collection)
    analyze_collection(cid)
    return collection
