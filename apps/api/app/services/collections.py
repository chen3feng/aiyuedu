"""作品集 / 书籍服务：每个 collection 一个 JSON 文件（含 metadata + glossary + chapters）。

存储：
- data/collections/<id>.json — 单本书完整数据
- data/collections/_index.json — 轻量列表（首页用）
- chapters 数组嵌在 collection 文件里，不外置到 readings.json
  （这样一本 = 一个文件，git diff 自包含、导出/共享 = 单文件）

API 不暴露 chapter 子概念，统一以 reading 视图呈现
（前端看到的 reading 实体带 collection_id / chapter_index / chapter_title）。
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from ..config import settings

_lock = threading.Lock()


def _collection_path(id: str) -> Path:
    """单本 collection 文件路径：data/collections/<id>.json"""
    # 防路径穿越：只允许字母数字 + 短横线
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", id):
        raise ValueError(f"collection id 非法（仅小写字母数字 + 短横线）: {id}")
    return Path(settings.collections_dir) / f"{id}.json"


# ---------- 列表 / 单本 ----------

def list_collections() -> list[dict]:
    """所有 collection 的轻量列表（基于 _index.json；缺则现扫）。

    索引里的条目若对应文件已删，自动剔除并重写索引，避免指向死文件。
    """
    idx_path = Path(settings.collections_index)
    if idx_path.exists():
        try:
            raw = json.loads(idx_path.read_text(encoding="utf-8")) or []
        except (json.JSONDecodeError, OSError):
            raw = None
        if raw is not None:
            d = Path(settings.collections_dir)
            live = [e for e in raw if (d / f"{e.get('id', '')}.json").exists()]
            if len(live) != len(raw):
                _rebuild_index()
            return live
    # 兜底：扫目录
    return _scan_list()


def _scan_list() -> list[dict]:
    """扫 data/collections/*.json 重建轻量列表（不读 chapters 内容，只读元数据）。"""
    items: list[dict] = []
    d = Path(settings.collections_dir)
    if not d.exists():
        return items
    for p in sorted(d.glob("*.json")):
        if p.name == "_index.json":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        items.append({
            "id": data.get("id", p.stem),
            "title": data.get("title", ""),
            "title_zh": data.get("title_zh", ""),
            "author": data.get("author", ""),
            "cover_url": data.get("cover_url", ""),
            "total_chapters": len(data.get("chapters") or []),
            "source": data.get("source", ""),
            "glossary_size": len(data.get("glossary") or {}),
            "created_at": data.get("created_at", 0),
        })
    return items


def get_collection(id: str) -> dict | None:
    """读完整 collection（含 chapters + glossary + polysemy）；不存在返 None。"""
    p = _collection_path(id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def get_chapter(collection_id: str, chapter_index: int) -> tuple[dict, dict] | None:
    """返回 (collection, chapter) 或 None。index 从 1 开始。"""
    coll = get_collection(collection_id)
    if coll is None:
        return None
    for ch in coll.get("chapters") or []:
        if ch.get("index") == chapter_index:
            return coll, ch
    return None


def get_chapter_for_reading(reading_id: str) -> tuple[dict, dict] | None:
    """按 reading_id 找章节（扫所有 collection）。找到返回 (collection, chapter)。"""
    d = Path(settings.collections_dir)
    if not d.exists():
        return None
    for p in sorted(d.glob("*.json")):
        if p.name == "_index.json":
            continue
        try:
            coll = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for ch in coll.get("chapters") or []:
            if ch.get("id") == reading_id:
                return coll, ch
    return None


# ---------- 写入 ----------

def _persist(collection: dict) -> None:
    """单文件落盘；同时更新 _index.json。"""
    d = Path(settings.collections_dir)
    d.mkdir(parents=True, exist_ok=True)
    cid = collection["id"]
    path = _collection_path(cid)
    with _lock:
        path.write_text(
            json.dumps(collection, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    # 重建索引
    _rebuild_index()


def _rebuild_index() -> None:
    items = _scan_list()
    idx = Path(settings.collections_index)
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def create_collection(data: dict) -> dict:
    """新建 collection。data 需含 id, title；其他字段可选。"""
    cid = (data.get("id") or "").strip()
    if not cid:
        raise ValueError("collection id 不能为空")
    # 默认自动生成短 id
    if cid == "_auto":
        cid = "c-" + uuid.uuid4().hex[:8]
    if get_collection(cid) is not None:
        raise ValueError(f"collection 已存在: {cid}")
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("title 不能为空")
    collection = {
        "id": cid,
        "title": title,
        "title_zh": (data.get("title_zh") or "").strip(),
        "author": (data.get("author") or "").strip(),
        "source": (data.get("source") or "").strip(),
        "total_chapters": len(data.get("chapters") or []),
        "cover_url": (data.get("cover_url") or "").strip(),
        "intro_zh": (data.get("intro_zh") or "").strip(),
        "intro_en": (data.get("intro_en") or "").strip(),
        "created_at": round(time.time(), 3),
        "glossary": dict(data.get("glossary") or {}),
        "polysemy": dict(data.get("polysemy") or {}),
        "chapters": list(data.get("chapters") or []),
    }
    _persist(collection)
    return collection


def update_collection(id: str, data: dict) -> dict | None:
    """改字段（metadata + glossary + polysemy + chapters）。"""
    cur = get_collection(id)
    if cur is None:
        return None
    for k in ("title", "title_zh", "author", "source", "cover_url", "intro_zh", "intro_en"):
        if k in data:
            cur[k] = (data.get(k) or "").strip()
    for k in ("glossary", "polysemy"):
        if k in data and data[k] is not None:
            cur[k] = dict(data[k])
    if "chapters" in data and data["chapters"] is not None:
        cur["chapters"] = list(data["chapters"])
        cur["total_chapters"] = len(cur["chapters"])
    _persist(cur)
    return cur


def delete_collection(id: str) -> bool:
    p = _collection_path(id)
    if not p.exists():
        return False
    with _lock:
        p.unlink()
    _rebuild_index()
    return True


# ---------- 古腾堡导入 ----------

def _slug_from_title(title: str, fallback: str) -> str:
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
    # 避免循环引用
    from . import gutenberg

    data = gutenberg.fetch_book(book_id)
    chapters = gutenberg.split_chapters(data["text"])

    cid = _slug_from_title(data["title"], f"gutenberg-{book_id}")
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
        "chapters": chapter_dicts,
    }
    _persist(collection)
    return collection


# ---------- reading 视图适配 ----------

def flatten_chapter_to_reading(coll: dict, chapter: dict) -> dict:
    """把嵌在 collection 里的 chapter 转成 reading 视图（带 collection 元数据）。"""
    return {
        "id": chapter["id"],
        "collection_id": coll["id"],
        "chapter_index": chapter.get("index"),
        "chapter_title": chapter.get("title"),
        "title": chapter.get("title") or chapter["id"],
        "title_zh": chapter.get("title_zh") or "",
        "subtitle": "",
        "topics": [],
        "target_level": chapter.get("target_level"),
        "glosses": chapter.get("glosses") or {},
        # collection.glossary 合并展示：chapter 优先
        "collection_glossary": coll.get("glossary") or {},
        "full_glosses": {},
        "headwords": {},
        "terms": chapter.get("terms") or {},
        "skip": chapter.get("skip") or [],
        "body": chapter.get("body") or "",
        "quizzes": chapter.get("quizzes") or [],
        "collection": {
            "id": coll["id"],
            "title": coll.get("title", ""),
            "title_zh": coll.get("title_zh", ""),
            "author": coll.get("author", ""),
            "cover_url": coll.get("cover_url", ""),
            "total_chapters": len(coll.get("chapters") or []),
        },
    }