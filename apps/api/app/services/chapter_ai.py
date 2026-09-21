"""章节级 AI 释义：候选生词提取 + 语境释义 + 短语挑选 + 词条校准。

从 services/collections.py 拆出（后者负责存储 / CRUD / 全本批量调度）。
analyze_chapter 写回章节时必须与 collections 的 CRUD 共用同一把 _lock，
因此锁 / 落盘原语在函数体内从 collections 延迟导入（同时规避循环导入）。
AI 调用不持锁——耗时长，不能阻塞其他章节的写回。
"""
from __future__ import annotations

import re

from . import ai

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def extract_chapter_vocab(body: str, level: int) -> list[dict]:
    """提取章节候选生词（按 level 过滤 + 每词首次出现句）。

    返回 [{"lemma": str, "context": str, "dict_gloss": str}, ...]
    """
    from . import reading  # 避免循环导入

    r = reading.annotate(body, level=level)
    # 收集每词首次出现的句子（用纯文本，去 markup）
    first_sent: dict[str, str] = {}
    for line in r["lines"]:
        text = _HTML_TAG_RE.sub("", line["html"]).strip()
        if not text:
            continue
        for w in line["words"]:
            lemma = w.get("lemma")
            if lemma and lemma not in first_sent:
                first_sent[lemma] = text

    items: list[dict] = []
    seen: set[str] = set()
    for v in r["vocabulary"]:
        if v.get("phrase"):
            continue  # 短语走 terms，不进单词清单（glosses 不收带空格的键）
        lemma = v["lemma"]
        if lemma in seen or not lemma:
            continue
        seen.add(lemma)
        items.append({
            "lemma": lemma,
            "context": first_sent.get(lemma, ""),
            "dict_gloss": v.get("gloss") or "",
        })
    return items


def ai_json_map(prompt: str, *, temperature: float = 0.2) -> dict:
    """调 AI 并把响应解析为 {键: 值} JSON 对象；失败不抛异常。

    返回 {"map": dict, "ai_used": bool, "reason": str | None, "raw": str}。
    """
    ai_map: dict = {}
    ai_used = False
    reason: str | None = None
    raw = ""
    try:
        content = ai.chat([{"role": "user", "content": prompt}], temperature=temperature)
    except RuntimeError as e:
        content = ""
        reason = f"AI 调用失败：{e}"
    raw = content[:200]
    if content:
        snippet = content[:120].replace("\n", " ")
        parsed = ai.parse_json_object(content)
        if parsed:
            ai_map = parsed
            ai_used = True
        else:
            reason = f"AI 响应无法解析为 JSON（开头: {snippet!r}）"
    elif reason is None:
        reason = "AI 返回空内容"
    return {"map": ai_map, "ai_used": ai_used, "reason": reason, "raw": raw}


def ai_gloss_vocab(items: list[dict]) -> dict:
    """调用默认 AI 为生词列表生成语境义。

    输入: [{"lemma", "context", "dict_gloss"}, ...]
    返回: {"glosses": {lemma: gloss}, "ai_used", "reason", "raw"}
    """
    if not items:
        return {"glosses": {}, "ai_used": False, "reason": "无生词", "raw": ""}

    lines = [
        f"- {it['lemma']}（参考义：{it['dict_gloss'] or '无'}）\n  首次出现句：{it['context']}"
        for it in items
    ]
    prompt = (
        "你是英语分级阅读的编辑，为初中英语学习者做生词的中文释义。\n"
        "下面是某书某一章里的生词清单（附词典义 + 首次出现的句子），"
        "请结合上下文语境，为每个词给出 1~6 个字的中文释义，"
        "只取该句里最贴切的含义（多义词务必按句意取舍，不要列出全部义项）。\n\n"
        "【生词清单】\n" + "\n".join(lines) + "\n\n"
        "只输出一个 JSON 对象，键为词条文本，值为中文释义。"
        "不要输出 JSON 以外的任何内容（不要 markdown 围栏）。"
    )
    res = ai_json_map(prompt)
    glosses: dict[str, str] = {}
    for it in items:
        lemma = it["lemma"]
        ai_g = str(res["map"].get(lemma) or "").strip()
        if ai_g:
            glosses[lemma] = ai_g
        elif it["dict_gloss"]:
            glosses[lemma] = it["dict_gloss"]  # AI 没给则词典义兜底
    return {"glosses": glosses, "ai_used": res["ai_used"], "reason": res["reason"], "raw": res["raw"]}


# 正文短于这么多词就不挑短语（太短的章节没有值得提取的搭配，省一次 AI 调用）
TERMS_MIN_WORDS = 200


def ai_gloss_terms(body: str, level: int, limit: int = 12) -> dict:
    """AI 挑选本章最值得注释的短语/习语/搭配并给中文释义（写入 chapter.terms）。

    返回 {"terms": {text: gloss}, "ai_used", "reason", "raw"}；失败不抛异常、terms 为空。
    正文太短（< TERMS_MIN_WORDS 词）时直接跳过：ai_used=False、reason=None（不算失败）。
    """
    from . import reading

    word_count = reading.stats(body, level)["word_count"]
    if word_count < TERMS_MIN_WORDS:
        return {"terms": {}, "ai_used": False, "reason": None, "raw": ""}
    prompt = (
        "你是英语分级阅读的编辑，为初中英语学习者挑选短语。\n"
        f"下面是一章英文正文（学习者词汇量约 {level} 词）。请挑出其中对学习者"
        "最有学习价值的多词表达——习语、固定搭配、动词短语"
        "（如 in want of、made up his mind、take possession of），"
        "并给每个短语 1~8 字的中文释义（按本章语境取义）。\n"
        "要求：\n"
        "- 只挑 2~5 词的多词表达；短语原文照抄正文拼写（保留空格）\n"
        "- 不挑人名/地名等专有名词组合；不挑字面直译就能懂的搭配\n"
        f"- 最多 {limit} 个，按学习价值从高到低；没有值得挑的就输出空对象 {{}}\n\n"
        "【正文】\n" + body + "\n\n"
        "只输出一个 JSON 对象，键为短语原文，值为中文释义。"
        "不要输出 JSON 以外的任何内容（不要 markdown 围栏）。"
    )
    res = ai_json_map(prompt)
    terms: dict[str, str] = {}
    for k, v in res["map"].items():
        text = str(k).strip().lower()
        gloss = str(v).strip()
        # 只收多词短语（防 AI 把单词混进 terms），键统一小写便于行内匹配
        if text and " " in text and gloss:
            terms[text] = gloss
    return {"terms": terms, "ai_used": res["ai_used"], "reason": res["reason"], "raw": res["raw"]}


def analyze_chapter(
    collection_id: str,
    chapter_index: int,
    *,
    force: bool = False,
) -> dict | None:
    """对单章跑 AI 释义：提取生词 + 挑短语 → 调 AI → 写回 glosses / terms + ai_status。

    返回 {"collection", "chapter", "items_count", "ai_used", "reason", "raw",
    "terms_count", "terms_ai_used", "terms_reason"}；collection / 章节不存在返回 None。
    force=True 时即使 ai_status=done 也重跑（用于「重跑 AI 释义」按钮），glosses / terms
    整体替换；非 force 合并保留已有词条（含手工加的）。短语提取失败不改变 ai_status
    （单词释义已可用），只在 ai_reason 里留备注。

    并发安全：标记 analyzing 与写回结果两段都持 collections._lock 做「读最新 → 改 → 落盘」。
    若只锁写不锁读，多章并发时后落盘的线程会拿旧快照把别人刚写的状态
    覆盖回去（表现为章节 ai_status 卡在 pending / analyzing）。
    AI 调用不持锁——耗时长，不能阻塞其他章节的写回。
    """
    # 延迟导入：锁必须与 collections CRUD 是同一把，且规避两模块循环导入
    from .collections import _lock, _persist_locked, get_collection

    def _find(coll: dict) -> dict | None:
        return next(
            (c for c in coll.get("chapters") or [] if c.get("index") == chapter_index),
            None,
        )

    # 第一段：标记 analyzing（原子读改写）
    with _lock:
        coll = get_collection(collection_id)
        if coll is None:
            return None
        chapter = _find(coll)
        if chapter is None:
            return None
        level = chapter.get("target_level") or 3000
        body = chapter.get("body") or ""
        chapter["ai_status"] = "analyzing"
        chapter["ai_reason"] = ""
        _persist_locked(coll)

    items = extract_chapter_vocab(body, level)
    result = ai_gloss_vocab(items)
    terms_result = ai_gloss_terms(body, level)

    # 第二段：写回结果（重新读最新快照再合并，同样原子）
    with _lock:
        cur = get_collection(collection_id)
        if cur is None:
            return None
        ch = _find(cur)
        if ch is None:
            return None

        if force:
            ch["glosses"] = dict(result["glosses"])
            ch["terms"] = dict(terms_result["terms"])
        else:
            merged = dict(ch.get("glosses") or {})
            merged.update(result["glosses"])
            ch["glosses"] = merged
            merged_terms = dict(ch.get("terms") or {})
            merged_terms.update(terms_result["terms"])
            ch["terms"] = merged_terms
        if result["ai_used"] or not items:
            # AI 成功，或本章没有生词（不算失败，避免「无生词」标红）
            ch["ai_status"] = "done"
            ch["ai_reason"] = "" if result["ai_used"] else (result["reason"] or "")
        else:
            ch["ai_status"] = "error"
            ch["ai_reason"] = result["reason"] or "未知错误"
        if not terms_result["ai_used"] and terms_result["reason"]:
            # 短语提取失败不阻塞章节（单词释义已可用），但留一条可见备注
            note = f"短语提取未更新：{terms_result['reason']}"
            ch["ai_reason"] = f"{ch['ai_reason']}；{note}" if ch["ai_reason"] else note
        _persist_locked(cur)
        return {
            "collection": cur,
            "chapter": ch,
            "items_count": len(items),
            "ai_used": result["ai_used"],
            "reason": result["reason"],
            "raw": result["raw"],
            "terms_count": len(terms_result["terms"]),
            "terms_ai_used": terms_result["ai_used"],
            "terms_reason": terms_result["reason"],
        }


def first_context(body: str, phrase: str, window: int = 100) -> str:
    """短语 / 手工词条在正文首次出现处的上下文窗口（提示词里当语境用）。"""
    m = re.search(re.escape(phrase), body, re.IGNORECASE)
    if m is None:
        return ""
    s = max(0, m.start() - window)
    e = min(len(body), m.end() + window)
    return re.sub(r"\s+", " ", body[s:e]).strip()


def ai_calibrate_vocab(
    body: str,
    level: int,
    glosses: dict | None,
    terms: dict | None,
) -> dict:
    """AI 校准一份章节词条清单（无状态，不落盘）—— 编辑器「AI 校准」按钮。

    输入编辑器当前的词汇 + 短语（可含手工加的），结合正文语境重新给义：
    - 每条以「当前义 + 首次出现语境」喂给 AI，AI 给出语境义则覆盖；
      AI 没覆盖的条目保持原值（合并结果保证不丢词条）
    - 只重给义、不添新词：提取发现但不在清单里的词不进结果
      （新增词条归「重跑 AI」；校准不该悄悄改清单）
    - AI 失败（网络 / 无法解析）→ 原样返回 + reason 诊断，ai_used=False
    返回 {"glosses", "terms", "ai_used", "reason", "raw"}。
    """
    input_glosses: dict[str, str] = {str(k): str(v) for k, v in (glosses or {}).items()}
    input_terms: dict[str, str] = {str(k): str(v) for k, v in (terms or {}).items()}

    items: list[dict] = []
    # 提取的生词带真实语境；当前义优先于词典义作参考（校准的就是它）
    for it in extract_chapter_vocab(body, level):
        it["dict_gloss"] = input_glosses.get(it["lemma"]) or it["dict_gloss"]
        items.append(it)
    # 手工词条（提取不覆盖：常见词手动加的 / 词形不同）+ 短语
    for lemma, g in input_glosses.items():
        if not any(it["lemma"] == lemma for it in items):
            items.append({"lemma": lemma, "context": first_context(body, lemma), "dict_gloss": g})
    for text, g in input_terms.items():
        items.append({"lemma": text, "context": first_context(body, text), "dict_gloss": g})

    result = ai_gloss_vocab(items)

    # 合并：输入清单为起点，AI 结果只作用于清单内的 key（条目不丢、不添）
    out_glosses: dict[str, str] = dict(input_glosses)
    out_terms: dict[str, str] = dict(input_terms)
    for k, v in result["glosses"].items():
        if k in out_terms:
            out_terms[k] = v
        elif k in out_glosses:
            out_glosses[k] = v
    return {
        "glosses": out_glosses,
        "terms": out_terms,
        "ai_used": result["ai_used"],
        "reason": result["reason"],
        "raw": result["raw"],
    }
