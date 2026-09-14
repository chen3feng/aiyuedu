"""后台管理编排：文章定级预览 / 主题校验 / 文章 CRUD / AI 语境义。

只做「编排 + 校验」，底层落库与词频/注释逻辑复用 services/reading.py 与 topics.py，
AI 调用复用 services/ai.py。
"""
import json

from ..services import ai, ecdict, mwe, reading, topics


def analyze(body: str, level: int | None = None) -> dict:
    """自动定级 + 提取生词注释 + 识别多词表达式，返回给后台预览。

    多词表达式（multiword）分流：短语（并入全局 mwe）与术语（文章级注释）；
    已全局短语不再列出。返回 {level, word_count, new_word_count, new_word_rate,
    glosses, vocabulary, multiword}。
    """
    global_phrases = mwe.texts()
    multiword = []
    for m in ecdict.scan_multiword(body):
        if m["text"] in global_phrases:
            continue  # 已全局短语，无需再列
        g = reading.short_gloss(m["translation"])
        if not g:
            continue  # 词典中无干净释义：不翻译也不列入
        multiword.append({
            "text": m["text"],
            "gloss": g,
            "kind": m["kind"],
            "tag": m["tag"],
        })
    terms = {m["text"]: m["gloss"] for m in multiword if m["kind"] == "term" and m["gloss"]}
    if level is None:
        level = reading.suggest_level(body, terms=terms)["level"]
    ann = reading.annotate(body, level, terms=terms)
    return {
        "level": level,
        "word_count": ann["word_count"],
        "new_word_count": ann["new_word_count"],
        "new_word_rate": ann["new_word_rate"],
        "glosses": reading.build_glosses(body, level, terms=terms),  # 词族头 -> 自动词典义
        "vocabulary": ann["vocabulary"],  # 逐词 {word,lemma,phonetic,gloss,full_gloss}
        "multiword": multiword,  # 多词表达式预览 [{text, gloss, kind, tag}]
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


def _build(data: dict, reading_id: str) -> tuple[dict, list]:
    """组装文章 dict 与待并入全局的短语列表：level 缺省按词频自动定级。

    多词表达式按 kind 分流：phrase → 待并入全局 mwe；term → 存文章 terms。
    """
    terms: dict[str, str] = {}
    phrases: list[dict] = []
    for m in data.get("multiword") or []:
        text = (m.get("text") or "").strip().lower()
        gloss = (m.get("gloss") or "").strip()
        if not text or not gloss:
            continue
        if m.get("kind") == "phrase":
            phrases.append({"text": text, "gloss": gloss})
        else:
            terms[text] = gloss
    level = data.get("target_level")
    if level is None:
        level = reading.suggest_level(data["body"], terms=terms)["level"]
    article = {
        "id": reading_id,
        "title": (data.get("title") or "").strip(),
        "subtitle": (data.get("subtitle") or "").strip(),
        "topics": data.get("topics") or [],
        "target_level": level,
        "glosses": data.get("glosses") or {},
        "full_glosses": data.get("full_glosses") or {},
        "headwords": data.get("headwords") or {},
        "terms": terms,
        "skip": data.get("skip") or [],
        "body": (data.get("body") or "").strip(),
        "quizzes": data.get("quizzes") or [],
    }
    return article, phrases


def create_article(data: dict) -> dict:
    _validate(data)
    article, phrases = _build(data, reading.next_reading_id())
    reading.add_reading(article)
    mwe.add_phrases(phrases)
    return article


def update_article(reading_id: str, data: dict) -> dict | None:
    _validate(data)
    article, phrases = _build(data, reading_id)
    updated = reading.update_reading(reading_id, article)
    if updated is not None:
        mwe.add_phrases(phrases)
    return updated


def delete_article(reading_id: str) -> bool:
    return reading.delete_reading(reading_id)


def get_article(reading_id: str) -> dict | None:
    return reading.get_reading(reading_id)


def list_articles() -> list[dict]:
    """文章列表（含主题中文名与字数）。"""
    items = []
    for r in reading.list_readings():
        rtopics = r.get("topics") or []
        st = reading.stats(r["body"], r.get("target_level") or reading.DEFAULT_LEVEL, skip=r.get("skip"))
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


def _parse_json(text: str) -> dict:
    """从 AI 回复文本中提取 JSON 对象；失败返回空 dict。"""
    if not text:
        return {}
    text = text.strip()
    # 剥掉 ```json ... ``` 围栏
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
        text = text.removeprefix("json").lstrip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def ai_glosses(body: str, level: int | None = None) -> dict:
    """调用默认 AI 为本文生词/短语生成语境义（仅行内 ruby 用），词典义兜底。

    返回 {"glosses": {lemma: 义}, "multiword_glosses": {text: 义}}；AI 漏项/空义时保留词典义。
    """
    r = analyze(body, level)
    glosses: dict[str, str] = dict(r["glosses"])  # lemma -> 词典 inline 义（兜底）
    multiword = r["multiword"]  # [{text, gloss, kind, tag}]

    items = [f"- {lemma}（词典义：{gloss}）" for lemma, gloss in glosses.items() if gloss]
    items += [f"- {m['text']}（词典义：{m['gloss']}）" for m in multiword if m.get("gloss")]
    if not items:
        return {"glosses": glosses, "multiword_glosses": {}}

    prompt = (
        "你是英语分级阅读的编辑，为英语学习者（中国初中生）做行内中文注音。\n"
        "下面是一篇文章的正文，以及需要注音的词/短语清单（附词典义作参考）。\n"
        "请结合本文语境，为每一项给出最准确、最简短的中文释义（用于行内 ruby 注音，"
        "通常 2~8 个字；多义词务必取本文含义，词典义已贴合时可沿用，避免冗长）。\n\n"
        "【正文】\n" + body + "\n\n"
        "【待注音项】\n" + "\n".join(items) + "\n\n"
        "只输出一个 JSON 对象，键为上面的原词，值为中文释义。不要输出 JSON 以外的任何内容。"
    )

    content = ai.chat([{"role": "user", "content": prompt}], temperature=0.3)
    ai_map = _parse_json(content)

    def _pick(key: str) -> str:
        if key in ai_map:
            return str(ai_map[key] or "").strip()
        lk = key.lower()
        for k, v in ai_map.items():
            if isinstance(k, str) and k.lower() == lk and v:
                return str(v).strip()
        return ""

    for lemma in list(glosses):
        g = _pick(lemma)
        if g:
            glosses[lemma] = g

    multiword_glosses: dict[str, str] = {}
    for m in multiword:
        g = _pick(m["text"])
        if g:
            m["gloss"] = g
            multiword_glosses[m["text"]] = g

    return {"glosses": glosses, "multiword_glosses": multiword_glosses}
