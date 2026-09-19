from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

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


def _all_reading_views():
    """合并孤儿 readings.json + 各 collection 的所有章节，输出统一的 reading 视图。"""
    views = []
    # 孤儿（readings.json 里的）
    for r in reading.list_readings():
        views.append({
            "id": r["id"],
            "title": r["title"],
            "title_zh": r.get("title_zh") or "",
            "topics": _topics_of(r),
            "topic_labels": _topic_labels(_topics_of(r)),
            "target_level": r.get("target_level"),
            "word_count": 0,  # 列表页不计算，省 CPU
            "new_word_rate": 0,
        })
    # collection 章节
    for coll in collections.list_collections():
        full = collections.get_collection(coll["id"])
        if not full:
            continue
        for ch in full.get("chapters") or []:
            views.append({
                "id": ch["id"],
                "title": ch.get("title") or ch["id"],
                "title_zh": ch.get("title_zh") or "",
                "topics": [],
                "topic_labels": [],
                "target_level": ch.get("target_level"),
                "word_count": 0,
                "new_word_rate": 0,
                # collection 元数据（前端面包屑用）
                "collection_id": coll["id"],
                "chapter_index": ch.get("index"),
                "collection_title": coll.get("title"),
                "collection_title_zh": coll.get("title_zh"),
                "collection_total_chapters": coll.get("total_chapters") or len(full.get("chapters") or []),
                "collection_cover_url": coll.get("cover_url"),
            })
    return views


@router.get("")
def list_readings(
    level: int | None = Query(None, ge=0),
    topic: str | None = None,
    user_id: str | None = Header(None, alias="X-User-Id")):
    # 未显式指定 level 时，用该用户的评测词汇量，否则回退默认
    level = level if level is not None else (users.get_vocab_size(user_id) or reading.DEFAULT_LEVEL)
    items = []
    for v in _all_reading_views():
        if topic and topic not in v["topics"]:
            continue
        # 列表页不重算统计（懒加载）；调用方按需 GET /readings/{id}
        items.append(v)
    return {"items": items}


@router.get("/{reading_id}")
def get_reading(
    reading_id: str,
    level: int | None = Query(None, ge=0),
    user_id: str | None = Header(None, alias="X-User-Id")):
    level = level if level is not None else (users.get_vocab_size(user_id) or reading.DEFAULT_LEVEL)
    # 先查 collection 章节
    coll_match = collections.get_chapter_for_reading(reading_id)
    if coll_match is not None:
        coll, chapter = coll_match
        rview = collections.flatten_chapter_to_reading(coll, chapter)
        # 合并 collection.glossary（同名优先 chapter 本地）
        merged_glosses = {**(coll.get("glossary") or {}), **(chapter.get("glosses") or {})}
        # 同样合并 collection_glossary 字段
        # 计算统计
        ann = reading.annotate(
            chapter["body"], level,
            chapter.get("glosses") or {},
            {}, {},  # full_glosses / headwords（章节里没存）
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
    user_id: str | None = Header(None, alias="X-User-Id")):
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