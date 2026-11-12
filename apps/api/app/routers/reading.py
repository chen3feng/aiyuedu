from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..deps import current_user_id
from ..services import collections, reading, topics, users

router = APIRouter(prefix="/readings", tags=["reading"])


def _topics_of(r: dict) -> list[str]:
    """文章主题列表（多值；兼容旧单值 topic 字段）。"""
    return r.get("topics") or ([r["topic"]] if r.get("topic") else [])


def _topic_labels(keys: list[str]) -> list[str]:
    return [topics.topic_label(k) for k in keys]


class RecordIn(BaseModel):
    level: int = reading.DEFAULT_LEVEL
    completed_ratio: float = 1.0
    seconds: int = 0
    new_word_clicks: list[str] = []


def _all_reading_views(topic: str | None = None):
    """合并视图：孤儿 readings（按 topic 过滤）+ 各 collection 摘要（作为整体入口）。

    不再把 collection 的章节作为独立条目列出——它们是 collection 的一部分，
    通过 collection 入口访问。这避免了 list 页章节与其他文章混在一起的问题。
    """
    out: list[dict] = []
    # 孤儿 readings
    for r in reading.list_readings():
        rtopics = _topics_of(r)
        if topic and topic not in rtopics:
            continue
        out.append({
            "id": r["id"],
            "title": r["title"],
            "title_zh": r.get("title_zh") or "",
            "topics": rtopics,
            "topic_labels": _topic_labels(rtopics),
            "target_level": r.get("target_level"),
            "word_count": 0,  # 列表页不计算
            "new_word_rate": 0,
        })
    # collection 摘要：每个 collection 作为一条目，独立入口
    for coll in collections.list_collections():
        full = collections.get_collection(coll["id"])
        if not full:
            continue
        ctopics = full.get("topics") or []
        if topic and topic not in ctopics:
            continue
        out.append({
            "id": coll["id"],
            "title": coll.get("title", ""),
            "title_zh": coll.get("title_zh") or "",
            "topics": ctopics,
            "topic_labels": _topic_labels(ctopics),
            "target_level": None,
            "word_count": 0,
            "new_word_rate": 0,
            "is_collection": True,
            "total_chapters": coll.get("total_chapters") or len(full.get("chapters") or []),
            "author": coll.get("author", ""),
            "cover_url": coll.get("cover_url", ""),
        })
    return out


@router.get("")
def list_readings(
    level: int | None = Query(None, ge=0),
    topic: str | None = None,
    user_id: str = Depends(current_user_id)):
    # 未显式指定 level 时，用该用户的评测词汇量，否则回退默认
    level = level if level is not None else (users.get_vocab_size(user_id) or reading.DEFAULT_LEVEL)
    # 列表页不重算统计（懒加载）；调用方按需 GET /readings/{id}
    return {"items": _all_reading_views(topic)}


@router.get("/progress")
def list_progress(user_id: str = Depends(current_user_id)):
    """当前用户每篇阅读的最新进度（含标题与所属作品集），按时间倒序。"""
    items = []
    for rec in reading.list_progress(user_id):
        rid = rec.get("reading_id", "")
        coll_match = collections.get_chapter_for_reading(rid)
        if coll_match is not None:
            coll, chapter = coll_match
            title = chapter.get("title") or chapter.get("title_zh") or rid
            title_zh = chapter.get("title_zh") or ""
            collection_id = coll["id"]
            collection_title = coll.get("title_zh") or coll.get("title") or ""
            chapter_index = chapter.get("index")
        else:
            r = reading.get_reading(rid) or {}
            title = r.get("title") or rid
            title_zh = r.get("title_zh") or ""
            collection_id = None
            collection_title = None
            chapter_index = None
        items.append({
            "reading_id": rid,
            "title": title,
            "title_zh": title_zh,
            "collection_id": collection_id,
            "collection_title": collection_title,
            "chapter_index": chapter_index,
            "level": rec.get("level"),
            "completed_ratio": rec.get("completed_ratio", 0),
            "seconds": rec.get("seconds", 0),
            "ts": rec.get("ts", 0),
        })
    return {"items": items}


@router.get("/{reading_id}")
def get_reading(
    reading_id: str,
    level: int | None = Query(None, ge=0),
    user_id: str = Depends(current_user_id)):
    level = level if level is not None else (users.get_vocab_size(user_id) or reading.DEFAULT_LEVEL)
    # 先查 collection 章节
    coll_match = collections.get_chapter_for_reading(reading_id)
    if coll_match is not None:
        coll, chapter = coll_match
        rview = collections.flatten_chapter_to_reading(coll, chapter)
        # 合并 collection.glossary（同名优先 chapter 本地）
        merged_glosses = {**(coll.get("glossary") or {}), **(chapter.get("glosses") or {})}
        # 计算统计
        ann = reading.annotate(
            chapter["body"], level,
            merged_glosses,
            # 由孤儿短文迁入的章节保留了 full_glosses / headwords，须透传才不丢
            # 派生词覆盖；古腾堡章节无此字段（{}），行为不变
            chapter.get("full_glosses") or {},
            chapter.get("headwords") or {},
            chapter.get("terms") or {}, chapter.get("skip") or [],
            only_glosses=True,
        )
        return {
            "id": rview["id"],
            "collection_id": coll["id"],
            "chapter_index": chapter.get("index"),
            "chapter_title": chapter.get("title"),
            "title": chapter.get("title") or chapter["id"],
            "title_zh": chapter.get("title_zh") or "",
            "subtitle": "",
            "topics": [],
            "topic_labels": [],
            "target_level": chapter.get("target_level"),
            "body": chapter.get("body") or "",
            "word_count": ann["word_count"],
            "new_word_count": ann["new_word_count"],
            "new_word_rate": ann["new_word_rate"],
            "lines": ann["lines"],
            "vocabulary": ann["vocabulary"],
            "quizzes": chapter.get("quizzes") or [],
            "collection_glossary": coll.get("glossary") or {},
            "collection": {
                "id": coll["id"],
                "title": coll.get("title", ""),
                "title_zh": coll.get("title_zh", ""),
                "author": coll.get("author", ""),
                "cover_url": coll.get("cover_url", ""),
                "total_chapters": len(coll.get("chapters") or []),
            },
            "chapters": [
                {
                    "index": ch.get("index"),
                    "id": ch["id"],
                    "title": ch.get("title"),
                    "title_zh": ch.get("title_zh"),
                } for ch in coll.get("chapters") or []
            ],
        }
    # 孤儿 reading 走老路径
    r = reading.get_reading(reading_id)
    if r is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    ann = reading.annotate(
        r["body"], level, r.get("glosses"), r.get("full_glosses"), r.get("headwords"), r.get("terms"),
        r.get("skip"),
        only_glosses=True,
    )
    rtopics = _topics_of(r)
    return {
        "id": r["id"],
        "title": r["title"],
        "title_zh": r.get("title_zh") or "",
        "subtitle": r.get("subtitle", ""),
        "topics": rtopics,
        "topic_labels": _topic_labels(rtopics),
        "target_level": r.get("target_level"),
        "body": r["body"],
        "word_count": ann["word_count"],
        "new_word_count": ann["new_word_count"],
        "new_word_rate": ann["new_word_rate"],
        "lines": ann["lines"],
        "vocabulary": ann["vocabulary"],
        "quizzes": r.get("quizzes", []),
    }


@router.post("/{reading_id}/record")
def record(
    reading_id: str,
    payload: RecordIn,
    user_id: str = Depends(current_user_id)):
    # 章节或孤儿都能 record
    coll_match = collections.get_chapter_for_reading(reading_id)
    if coll_match is None and reading.get_reading(reading_id) is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    reading.record_reading(
        reading_id,
        payload.level,
        payload.completed_ratio,
        payload.seconds,
        payload.new_word_clicks,
        user_id,
    )
    return {"ok": True, "reading_id": reading_id}