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
    seen: set[str] = set()
    for m in ecdict.scan_multiword(body):
        if m["text"] in global_phrases:
            continue  # 已全局短语，无需再列
        if m["text"] in seen:
            continue  # 同一短语在正文多次出现，只列一次
        g = reading.short_gloss(m["translation"])
        if not g:
            continue  # 词典中无干净释义：不翻译也不列入
        seen.add(m["text"])
        multiword.append({
            "text": m["text"],
            "gloss": g,
            "kind": m["kind"],
            "tag": m["tag"],
        })
    terms = {m["text"]: m["gloss"] for m in multiword if m["kind"] == "term" and m["gloss"]}
    if level is None:
        level = reading.suggest_level(body, terms=terms)["level"]  # 文章难度标签（不改）
    # 词表按统一基准 GLOSS_LEVEL 生成，覆盖所有 rank > GLOSS_LEVEL 的词；
    # 阅读端再按用户词汇量现筛，故此处不必受文章难度影响。
    ann = reading.annotate(body, reading.GLOSS_LEVEL, terms=terms)
    return {
        "level": level,
        "word_count": ann["word_count"],
        "new_word_count": ann["new_word_count"],
        "new_word_rate": ann["new_word_rate"],
        "glosses": reading.build_glosses(body, reading.GLOSS_LEVEL, terms=terms),  # 词族头 -> 自动词典义
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


def get_article_edit(reading_id: str) -> dict | None:
    """取文章供后台编辑：附带按已存 glosses 重建的生词表与统计，打开即显示可手工改。

    生词表逐条取自已存 `glosses` 的键（含单词与多词短语），保证后台「生词中文注释」
    打开即回显；`word`/`phonetic` 优先取 `headwords` 覆盖，`full_gloss` 取 `full_glosses`。
    统计与「自动定级」同口径（terms 不计生词、短语计生词）。
    """
    a = reading.get_reading(reading_id)
    if a is None:
        return None
    level = a.get("target_level") or reading.DEFAULT_LEVEL
    glosses = a.get("glosses") or {}
    full_glosses = a.get("full_glosses") or {}
    headwords = a.get("headwords") or {}
    vocabulary = []
    for lemma, gloss in glosses.items():
        hw = headwords.get(lemma) or {}
        vocabulary.append(
            {
                "word": hw.get("word") or lemma,
                "lemma": lemma,
                "phonetic": hw.get("phonetic") or "",
                "gloss": gloss,
                "full_gloss": full_glosses.get(lemma) or "",
            }
        )
    st = reading.stats(a["body"], level, terms=a.get("terms"), skip=a.get("skip"))
    out = dict(a)
    out["vocabulary"] = vocabulary
    out["word_count"] = st["word_count"]
    out["new_word_count"] = st["new_word_count"]
    out["new_word_rate"] = st["new_word_rate"]
    return out


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


def generate_article(
    outline: str,
    extra_requirements: str = "",
    target_level: int | None = None,
) -> str:
    """调用默认 AI 根据大纲和要求生成分级阅读文章正文。

    返回纯文本（不含标题/markdown），失败抛 RuntimeError。
    """
    level_hint = ""
    if target_level:
        level_hint = (
            f"词汇量控制在英语最常用 {target_level} 个词族范围内，"
            f"超纲词不要超过全文词数的 3%。"
        )
    else:
        level_hint = "词汇量控制在英语最常用 2000~4000 词族范围内，适合中国中小学生。"

    prompt = (
        "你是一位英语分级阅读作家，为中国中小学生撰写英语短文。\n"
        "请根据以下要求，用标准英语撰写一篇分级阅读短文：\n\n"
        f"- 词汇量级别要求：{level_hint}\n"
        f"- 文章大纲：{outline}\n"
        f"{'- 额外要求：' + extra_requirements if extra_requirements else ''}"
        "\n要求：\n"
        "1. 文章长度 150~350 词，适合做分级阅读\n"
        "2. 语言自然流畅、有教育意义\n"
        "3. 只输出英语正文，不要标题、不要 markdown 格式、不要任何额外说明\n"
    )
    return ai.chat([{"role": "user", "content": prompt}], temperature=0.8)


def revise_article(body: str, suggestions: str) -> str:
    """根据修改建议重写已生成的正文，返回修改后的完整正文。"""
    prompt = (
        "你是一位英语分级阅读编辑。下面是一篇已经生成好的英语分级阅读短文。\n"
        "请根据修改建议对文章进行修改，保持原有的分级阅读风格与词汇难度，"
        "输出修改后的完整正文。\n\n"
        "【修改建议】\n" + suggestions + "\n\n"
        "【原文】\n" + body + "\n\n"
        "只输出修改后的完整英语正文，不要标题、不要 markdown 格式、不要任何额外说明。"
    )
    return ai.chat([{"role": "user", "content": prompt}], temperature=0.6)


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
