from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from ..services import reading, users

router = APIRouter(prefix="/readings", tags=["reading"])

# 四大兴趣主题（design §11.2 确认的种子分类）
TOPICS = {
    "science": "科普/科技",
    "sports": "体育/游戏/汽车",
    "history": "历史/名人",
    "adventure": "冒险/科幻/悬疑",
}


class RecordIn(BaseModel):
    level: int = reading.DEFAULT_LEVEL
    completed_ratio: float = 1.0
    seconds: int = 0
    new_word_clicks: list[str] = []


@router.get("")
def list_readings(
    level: int | None = Query(None, ge=0),
    topic: str | None = None,
    user_id: str | None = Header(None, alias="X-User-Id"),
):
    # 未显式指定 level 时，用该用户的评测词汇量，否则回退默认
    level = level if level is not None else (users.get_vocab_size(user_id) or reading.DEFAULT_LEVEL)
    items = []
    for r in reading.list_readings():
        if topic and r.get("topic") != topic:
            continue
        st = reading.stats(r["body"], level)
        items.append(
            {
                "id": r["id"],
                "title": r["title"],
                "topic": r["topic"],
                "topic_label": TOPICS.get(r.get("topic", ""), r["topic"]),
                "target_level": r.get("target_level"),
                "word_count": st["word_count"],
                "new_word_rate": st["new_word_rate"],
            }
        )
    return {"items": items}


@router.get("/{reading_id}")
def get_reading(
    reading_id: str,
    level: int | None = Query(None, ge=0),
    user_id: str | None = Header(None, alias="X-User-Id"),
):
    level = level if level is not None else (users.get_vocab_size(user_id) or reading.DEFAULT_LEVEL)
    r = reading.get_reading(reading_id)
    if r is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    ann = reading.annotate(
        r["body"], level, r.get("glosses"), r.get("full_glosses"), r.get("headwords")
    )
    return {
        "id": r["id"],
        "title": r["title"],
        "topic": r["topic"],
        "topic_label": TOPICS.get(r.get("topic", ""), r["topic"]),
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
    user_id: str | None = Header(None, alias="X-User-Id"),
):
    if reading.get_reading(reading_id) is None:
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
