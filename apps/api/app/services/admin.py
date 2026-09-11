"""后台管理编排：文章定级预览 / 主题校验 / 文章 CRUD。

只做「编排 + 校验」，底层落库与词频/注释逻辑复用 services/reading.py 与 topics.py。
"""
from ..services import reading, topics


def analyze(body: str, level: int | None = None) -> dict:
    """自动定级 + 提取生词注释，返回给后台预览（glosses 可再手工改）。

    返回 {level, word_count, new_word_count, new_word_rate, glosses, vocabulary}。
    """
    if level is None:
        level = reading.suggest_level(body)["level"]
    ann = reading.annotate(body, level)
    return {
        "level": level,
        "word_count": ann["word_count"],
        "new_word_count": ann["new_word_count"],
        "new_word_rate": ann["new_word_rate"],
        "glosses": reading.build_glosses(body, level),  # 词族头 -> 自动词典义
        "vocabulary": ann["vocabulary"],  # 逐词 {word,lemma,phonetic,gloss,full_gloss}
    }


def _validate(data: dict) -> None:
    """校验文章字段，不合法抛 ValueError（由路由转 422）。"""
    if not (data.get("title") or "").strip():
        raise ValueError("标题不能为空")
    if not (data.get("body") or "").strip():
        raise ValueError("正文不能为空")
    ts = data.get("topics") or []
    if not ts:
        raise ValueError("至少选择一个主题")
    valid = set(topics.get_topic_keys())
    for t in ts:
        if t not in valid:
            raise ValueError(f"未知主题: {t}")
    for q in data.get("quizzes", []):
        if not (q.get("question") or "").strip():
            raise ValueError("每道题的问题不能为空")
        opts = q.get("options") or []
        if len(opts) < 2:
            raise ValueError("每道题至少要有 2 个选项")
        if not any(o.get("correct") for o in opts):
            raise ValueError("每道题至少要有一个正确选项")
        for o in opts:
            if not (o.get("text") or "").strip():
                raise ValueError("选项内容不能为空")


def _build(data: dict, reading_id: str) -> dict:
    """组装文章 dict：level 缺省按词频自动定级，其余字段规范化。"""
    level = data.get("target_level")
    if level is None:
        level = reading.suggest_level(data["body"])["level"]
    return {
        "id": reading_id,
        "title": (data.get("title") or "").strip(),
        "subtitle": (data.get("subtitle") or "").strip(),
        "topics": data.get("topics") or [],
        "target_level": level,
        "glosses": data.get("glosses") or {},
        "full_glosses": data.get("full_glosses") or {},
        "headwords": data.get("headwords") or {},
        "body": (data.get("body") or "").strip(),
        "quizzes": data.get("quizzes") or [],
    }


def create_article(data: dict) -> dict:
    _validate(data)
    return reading.add_reading(_build(data, reading.next_reading_id()))


def update_article(reading_id: str, data: dict) -> dict | None:
    _validate(data)
    return reading.update_reading(reading_id, _build(data, reading_id))


def delete_article(reading_id: str) -> bool:
    return reading.delete_reading(reading_id)


def get_article(reading_id: str) -> dict | None:
    return reading.get_reading(reading_id)


def list_articles() -> list[dict]:
    """文章列表（含主题中文名与字数）。"""
    items = []
    for r in reading.list_readings():
        rtopics = r.get("topics") or []
        st = reading.stats(r["body"], r.get("target_level") or reading.DEFAULT_LEVEL)
        items.append(
            {
                "id": r["id"],
                "title": r["title"],
                "subtitle": r.get("subtitle", ""),
                "topics": rtopics,
                "topic_labels": [topics.topic_label(k) for k in rtopics],
                "target_level": r.get("target_level"),
                "word_count": st["word_count"],
            }
        )
    return items
