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

import re
import threading
import time
import uuid
from pathlib import Path

from . import chapter_ai
from .storage import atomic_write_json, load_json_or
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
        raw = load_json_or(idx_path, None)
        if isinstance(raw, list):
            d = Path(settings.collections_dir)
            live = [e for e in raw if (d / f"{e.get('id', '')}.json").exists()]
            if len(live) != len(raw):
                with _lock:
                    _write_index_atomic(live)
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
        data = load_json_or(p, None)
        if not isinstance(data, dict):
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
    data = load_json_or(p, None)
    return data if isinstance(data, dict) else None


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
        coll = load_json_or(p, None)
        if not isinstance(coll, dict):
            continue
        for ch in coll.get("chapters") or []:
            if ch.get("id") == reading_id:
                return coll, ch
    return None


# ---------- 写入 ----------

def _write_index_atomic(items: list[dict]) -> None:
    """原子写入 _index.json（调用方需已持有 _lock）。"""
    atomic_write_json(settings.collections_index, items)


def _persist(collection: dict) -> None:
    """单文件落盘 + 原子更新 _index.json（持锁版本，外部调用入口）。"""
    with _lock:
        _persist_locked(collection)


def _persist_locked(collection: dict) -> None:
    """_persist 的无锁版本：调用方必须已持有 _lock。

    用于「读最新 → 改 → 落盘」需要原子的场景（analyze_chapter 并发写回）：
    只锁写不锁读的话，并发线程会用旧快照覆盖别人刚写的状态。
    """
    d = Path(settings.collections_dir)
    d.mkdir(parents=True, exist_ok=True)
    cid = collection["id"]
    atomic_write_json(_collection_path(cid), collection)
    _write_index_atomic(_scan_list())


def create_collection(data: dict) -> dict:
    """新建 collection。data 需含 id, title；其他字段可选。"""
    cid = (data.get("id") or "").strip()
    if not cid:
        raise ValueError("collection id 不能为空")
    # 默认自动生成短 id
    if cid == "_auto":
        cid = "c-" + uuid.uuid4().hex[:8]
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
    # 查重 + 落盘放同一锁段：否则两个并发 create 同 id 都能通过检查
    with _lock:
        if get_collection(cid) is not None:
            raise ValueError(f"collection 已存在: {cid}")
        _persist_locked(collection)
    return collection


def update_collection(id: str, data: dict) -> dict | None:
    """改字段（metadata + glossary + polysemy + chapters）。"""
    # 读 → 改 → 落盘整个放锁内：并发 update 不互相覆盖
    with _lock:
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
        _persist_locked(cur)
        return cur


def delete_collection(id: str) -> bool:
    p = _collection_path(id)
    with _lock:
        if not p.exists():
            return False
        p.unlink()
        _write_index_atomic(_scan_list())
    return True


# ---------- 古腾堡导入 ----------
# 实现已拆到 services/gutenberg_import.py（拆 collections 大文件的第一步）；
# 此处保留入口，调用路径（routers/collections.py）保持不变。
def import_from_gutenberg(book_id: int) -> dict:
    from .gutenberg_import import import_from_gutenberg as _do_import

    return _do_import(book_id)


# ---------- 章节编辑 ----------

def update_chapter(collection_id: str, chapter_index: int, data: dict) -> dict | None:
    """编辑单章：title / title_zh / body / target_level（只更新传入的字段）。

    body 实际变更时把 ai_status 重置为 pending（glosses 已过期，提示重跑 AI；
    词条保留，重跑 force=True 会覆盖）。返回更新后的 chapter；不存在返 None。
    读改写全程持锁，与并发 AI 写回互不覆盖。
    """

    def _find(coll: dict) -> dict | None:
        return next(
            (c for c in coll.get("chapters") or [] if c.get("index") == chapter_index),
            None,
        )

    with _lock:
        cur = get_collection(collection_id)
        if cur is None:
            return None
        ch = _find(cur)
        if ch is None:
            return None
        body_changed = False
        if "title" in data and data["title"] is not None:
            ch["title"] = str(data["title"]).strip()
        if "title_zh" in data and data["title_zh"] is not None:
            ch["title_zh"] = str(data["title_zh"]).strip()
        if "body" in data and data["body"] is not None:
            new_body = str(data["body"])
            body_changed = new_body != ch.get("body")
            ch["body"] = new_body
        if "target_level" in data and data["target_level"] is not None:
            ch["target_level"] = int(data["target_level"])
        # 词汇 / 短语：整体替换（编辑器全量提交）；只动词条不重置 ai_status
        #（手工校正属于收尾，不代表词条过期）
        if "glosses" in data and data["glosses"] is not None:
            ch["glosses"] = {
                str(k).strip(): str(v).strip()
                for k, v in data["glosses"].items() if str(k).strip()
            }
        if "terms" in data and data["terms"] is not None:
            ch["terms"] = {
                str(k).strip(): str(v).strip()
                for k, v in data["terms"].items() if str(k).strip()
            }
        if body_changed:
            ch["ai_status"] = "pending"
            ch["ai_reason"] = "正文已编辑，词条可能过期，建议重跑 AI"
        _persist_locked(cur)
        return ch


# ---------- 全本 AI 批量调度 ----------

def analyze_collection(collection_id: str) -> dict | None:
    """对全本所有未 done 的章节并发跑 AI（在后台线程里调用）。

    返回启动摘要：{"scheduled": [chapter_indices], "threads": [...]}
    collection 不存在返回 None。返回的 threads 列表供调用方 join（测试 / 重启场景）。
    """
    coll = get_collection(collection_id)
    if coll is None:
        return None
    scheduled: list[int] = []
    for ch in coll["chapters"]:
        if ch.get("ai_status") != "done":
            scheduled.append(ch["index"])
    if not scheduled:
        return {"scheduled": [], "collection": coll, "threads": []}

    def _run(idx: int) -> None:
        try:
            chapter_ai.analyze_chapter(collection_id, idx, force=False)
        except Exception:
            # 标记失败，不让线程死循环（同样原子读改写）
            with _lock:
                cur = get_collection(collection_id)
                if cur is None:
                    return
                c = next(
                    (c for c in cur.get("chapters") or [] if c.get("index") == idx),
                    None,
                )
                if c is not None:
                    c["ai_status"] = "error"
                    c["ai_reason"] = "后台线程异常"
                    _persist_locked(cur)

    threads = []
    for idx in scheduled:
        t = threading.Thread(target=_run, args=(idx,), daemon=True)
        t.start()
        threads.append(t)
    return {"scheduled": scheduled, "collection": coll, "threads": threads}


def backfill_terms(collection_id: str, *, only_empty: bool = True) -> dict | None:
    """为已完成章节并发补短语：只写 chapter.terms，不动 glosses / ai_status。

    用于导入时短语功能尚未上线、全本 done 后需要回填的场景（force 重跑会
    覆盖手工 gloss 释义，故另走此路径）。only_empty=True 时只补 terms 为空的章节。
    返回 {"scheduled", "threads"}；collection 不存在返回 None。
    """

    def _find(coll: dict, idx: int) -> dict | None:
        return next(
            (c for c in coll.get("chapters") or [] if c.get("index") == idx),
            None,
        )

    with _lock:
        coll = get_collection(collection_id)
        if coll is None:
            return None
        scheduled = [
            c["index"]
            for c in coll.get("chapters") or []
            if c.get("ai_status") == "done"
            and (not only_empty or not (c.get("terms") or {}))
        ]
    if not scheduled:
        return {"scheduled": [], "threads": []}

    def _run(idx: int) -> None:
        # 读 body（持锁快照）→ AI 不持锁 → 合并写回（原子）
        with _lock:
            cur = get_collection(collection_id)
            if cur is None:
                return
            ch = _find(cur, idx)
            if ch is None:
                return
            body = ch.get("body") or ""
            level = ch.get("target_level") or 3000
        r = chapter_ai.ai_gloss_terms(body, level)
        if not r["terms"]:
            return
        with _lock:
            cur = get_collection(collection_id)
            if cur is None:
                return
            ch = _find(cur, idx)
            if ch is None:
                return
            merged = dict(ch.get("terms") or {})
            merged.update(r["terms"])
            ch["terms"] = merged
            _persist_locked(cur)

    threads = []
    for idx in scheduled:
        t = threading.Thread(target=_run, args=(idx,), daemon=True)
        t.start()
        threads.append(t)
    return {"scheduled": scheduled, "threads": threads}


def reconcile_collection(collection_id: str) -> dict | None:
    """对齐全书词汇表：扫描所有 chapter.glosses，写入 collection.glossary + polysemy。

    规则：
    - 同一词所有章节 gloss 一致 → glossary[lemma] = gloss；polysemy 不收录
    - 同一词不同章节 gloss 不同 → glossary[lemma] = 出现次数最多的 gloss；
      polysemy[lemma][gloss] = [章节 index 列表]
    """
    coll = get_collection(collection_id)
    if coll is None:
        return None

    # lemma → gloss → [chapter_index]
    bucket: dict[str, dict[str, list[int]]] = {}
    for ch in coll["chapters"]:
        for lemma, gloss in (ch.get("glosses") or {}).items():
            if not lemma or not gloss:
                continue
            bucket.setdefault(lemma, {}).setdefault(gloss, []).append(ch["index"])

    glossary: dict[str, str] = {}
    polysemy: dict[str, dict[str, list[int]]] = {}
    for lemma, glosses in bucket.items():
        if len(glosses) == 1:
            glossary[lemma] = next(iter(glosses.keys()))
        else:
            polysemy[lemma] = {g: sorted(chs) for g, chs in glosses.items()}
            # canonical = 出现章节最多的 gloss
            canonical = max(glosses.items(), key=lambda kv: len(kv[1]))[0]
            glossary[lemma] = canonical

    # 写回放锁内：避免与并发 analyze_chapter 互相覆盖
    with _lock:
        cur = get_collection(collection_id)
        if cur is None:
            return None
        cur["glossary"] = glossary
        cur["polysemy"] = polysemy
        _persist_locked(cur)
        return cur


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
        "ai_status": chapter.get("ai_status") or "pending",
        "ai_reason": chapter.get("ai_reason") or "",
        "collection": {
            "id": coll["id"],
            "title": coll.get("title", ""),
            "title_zh": coll.get("title_zh", ""),
            "author": coll.get("author", ""),
            "cover_url": coll.get("cover_url", ""),
            "total_chapters": len(coll.get("chapters") or []),
        },
    }