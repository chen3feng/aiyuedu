"""分级阅读：生词判定 + 逐行对照注释。

按 Nation BNC/COCA 词族 rank（1~25000）判定生词：给定读者词汇量 level，
rank <= level 判「已知」，否则「生词」；不在词表、又无法还原到词族头的词也判「生词」。
生词率 = 生词 token 数 / 词 token 总数（数字与标点不计入）。

词形还原（surface -> 词族头）用 data/wordlists/surface_lemma.json，
由 data/wordlists/build_surface_lemma.py 从 raw 词族表 + 词形还原表生成，见 data/wordlists/README.md。

P1 简化：生词是「已知/未知」二值（设计 §7.1 概率模型的近似）；不做短语识别与
LLM 语境化消歧（留 P2）；专有名词（句中大写）按已知处理、不注释义。
"""
import csv
import html as _html
import json
import re
import time
from functools import lru_cache
from pathlib import Path

from ..config import settings
from .vocab import gloss

# 领域标签（[医][计] 等）对少儿不友好，full_gloss 里剥掉
_BRACKET = re.compile(r"\[[^\]]*\]")


def full_gloss(translation: str) -> str:
    """完整意思：保留全部义项与词性，仅去掉 [医][计] 等领域标签，不截断。

    与 vocab.gloss 的区别：gloss 只取前 2 组 × 前 3 义项、限 32 字（用于行内/选项）；
    本文要求「文章结尾列出所有生词的完整意思」，故此处给全量义项。
    """
    if not translation:
        return ""
    groups = []
    for g in translation.split("；"):
        if "[" in g or "]" in g:
            continue  # 领域义项（如 [医]、[计]）跳过
        g = g.strip(" ,，;；")
        if g:
            groups.append(g)
    if not groups:
        seg = _BRACKET.sub("", translation).strip(" ,，;；")
        groups = [seg] if seg else []
    return "；".join(groups)

# 目标学生估算词汇量（design §2.1：初一男生 ~3600），可用 ?level= 覆盖
DEFAULT_LEVEL = 3600

# 句子切分：句末标点 + 空白（"9.58" 里的点后无空白，不会被误切）
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
# 词 token：数字（可含小数点）或字母词（内部可含撇号，如 can't / don't）；其余为标点
_TOKEN_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?|[A-Za-z]+(?:'[A-Za-z]+)*)|([^A-Za-z0-9]+)")

# 功能词停用表：极高频虚词，即便词表生成时被过滤（如 a / an），也永不当生词。
STOPWORDS = frozenset(
    """
    a an the i me my mine we us our ours you your yours he him his she her hers it its
    they them their theirs this that these those who whom whose which what
    am is are was were be been being have has had having do does did done doing
    will would shall should can could may might must
    of in to for on at by with from about into over after before under between through
    during without against among around upon until till up down out off
    and but or nor so yet if because while though although than as when where how why
    whether since unless not no yes also very too just only even then now here there
    again always never ever once more most less least some any all both each every
    other another such many much few little
    """.split()
)

# 词表生成时被过滤、但阅读中高频出现的常用词（Nation 词族头未入库）。值形如词表行。
# rank 为近似词族序（够用来判定「已知」即可），translation 供 gloss() 提取释义。
_EXTRA_COMMON = {
    "run": {"rank": 400, "phonetic": "rʌn", "translation": "跑；运行；经营"},
    "ran": {"rank": 400, "phonetic": "", "translation": "跑（run 的过去式）"},
    "runs": {"rank": 400, "phonetic": "", "translation": "跑（run 的第三人称）"},
    "running": {"rank": 400, "phonetic": "", "translation": "跑（run 的进行时）"},
    "past": {"rank": 900, "phonetic": "", "translation": "过去；经过；晚于"},
}


@lru_cache(maxsize=1)
def _load_readings() -> list:
    with open(settings.readings_path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_surface_lemma() -> dict:
    with open(settings.surface_lemma_path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_heads() -> dict:
    """词族头 -> {rank, phonetic, translation}。"""
    heads: dict = {}
    with open(settings.wordlist_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            lemma = (row.get("lemma") or "").strip().lower()
            try:
                rank = int(row.get("rank") or row.get("frq") or 0)
            except (TypeError, ValueError):
                rank = 0
            if lemma and rank > 0:
                heads[lemma] = {
                    "rank": rank,
                    "phonetic": (row.get("phonetic") or "").strip(),
                    "translation": row.get("translation") or "",
                }
    return heads


def list_readings() -> list:
    return _load_readings()


def get_reading(reading_id: str) -> dict | None:
    for r in _load_readings():
        if r["id"] == reading_id:
            return r
    return None


def _head_of(lower: str) -> str:
    """词形（小写）-> 词族头；查不到返回自身。附带撇号所有格（dog's -> dog）处理。"""
    sl = _load_surface_lemma()
    if lower in sl:
        return sl[lower]
    if lower.endswith("'s"):
        stripped = lower[:-2]
        if stripped in sl:
            return sl[stripped]
    return lower


def _sentences(body: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(body.strip()) if s.strip()]


def _tokenize(sentence: str) -> list[dict]:
    """把一句拆成 token 序列：[{text, kind}]，kind ∈ {word, punct}。"""
    tokens = []
    for m in _TOKEN_RE.finditer(sentence):
        if m.group(1):
            tokens.append({"text": m.group(1), "kind": "word"})
        else:
            tokens.append({"text": m.group(2), "kind": "punct"})
    return tokens


def _classify(text: str, level: int) -> dict:
    """给一个词 token 判「已知/生词」，生词附词族头 + 释义 + rank（音标仅当原词即词族头）。"""
    if text[0].isdigit():
        return {"w": text, "known": True, "num": True}
    lower = text.lower()
    if lower in STOPWORDS:
        return {"w": text, "known": True, "stop": True}
    head = _head_of(lower)
    info = _load_heads().get(head) or _EXTRA_COMMON.get(head)
    if info:
        if info["rank"] <= level:
            return {"w": text, "known": True, "lemma": head}
        entry: dict = {
            "w": text, "known": False, "lemma": head, "rank": info["rank"],
            "gloss": gloss(info["translation"]),
            "full_gloss": full_gloss(info["translation"]),
        }
        if info["phonetic"]:
            entry["phonetic"] = info["phonetic"]
        return entry
    # 不在词表/补充表：大写词当专有名词（人名/地名），小写词当未知生词（无释义）
    if text[0].isupper():
        return {"w": text, "known": True, "proper": True}
    return {"w": text, "known": False, "lemma": lower, "gloss": ""}


def _count(body: str, level: int) -> tuple[int, int]:
    """返回 (词 token 数, 生词 token 数)，数字与标点不计入。"""
    word_count = new_count = 0
    for sentence in _sentences(body):
        for tok in _tokenize(sentence):
            if tok["kind"] == "punct":
                continue
            entry = _classify(tok["text"], level)
            if entry.get("num"):
                continue
            word_count += 1
            if not entry["known"]:
                new_count += 1
    return word_count, new_count


def stats(body: str, level: int) -> dict:
    """轻量统计（列表用，不生成逐词结构）。"""
    word_count, new_count = _count(body, level)
    return {
        "word_count": word_count,
        "new_word_count": new_count,
        "new_word_rate": round(new_count / word_count, 4) if word_count else 0.0,
    }


def annotate(
    body: str,
    level: int,
    glosses: dict | None = None,
    full_glosses: dict | None = None,
    headwords: dict | None = None,
) -> dict:
    """逐句切分并逐词标注：每行附 ruby 标注 HTML + 词级 token；文末生词表（完整意思）。

    每个生词只在**首次出现**时加 `<ruby>` 中文注释，之后复现不再注释（鼓励回忆，
    避免满篇注音）。生词表按首次出现顺序去重列出，`word` 为展示用原型。

    - `glosses`：词族头 -> 本文最贴切的语境义（行内 `<ruby>` 只标这一义）。
    - `full_glosses`：词族头 -> 完整意思覆盖（派生词「词面义 ≠ 词族头义」时用，如
      propeller->propel；缺省用词族头的 full_gloss）。
    - `headwords`：词族头 -> 展示词形覆盖 `{word, phonetic}`（派生词是独立词条、词族头
      并非其原型时用，如 propeller->propel 应展示「propeller」；缺省展示词族头）。
    """
    glosses = glosses or {}
    full_glosses = full_glosses or {}
    headwords = headwords or {}
    lines = []
    vocab: dict[str, dict] = {}  # 词族头 -> 生词表条目（按首次出现顺序）
    word_count = new_count = 0
    for sentence in _sentences(body):
        words = []
        html_parts: list[str] = []
        for tok in _tokenize(sentence):
            if tok["kind"] == "punct":
                words.append({"w": tok["text"], "punct": True})
                html_parts.append(_html.escape(tok["text"], quote=False))
                continue
            entry = _classify(tok["text"], level)
            words.append(entry)
            if entry.get("num"):
                html_parts.append(_html.escape(tok["text"], quote=False))
                continue
            word_count += 1
            if entry["known"]:
                html_parts.append(_html.escape(tok["text"], quote=False))
                continue
            new_count += 1
            head = entry.get("lemma") or tok["text"].lower()
            ctx = glosses.get(head) or entry.get("gloss") or ""
            if head not in vocab:
                # 首次出现：加 ruby 中文注释，并录入生词表（展示用原型）
                wf = headwords.get(head) or {}
                vocab[head] = {
                    "word": wf.get("word") or head,
                    "lemma": head,
                    "phonetic": wf.get("phonetic") or entry.get("phonetic", ""),
                    "gloss": ctx,
                    "full_gloss": full_glosses.get(head) or entry.get("full_gloss") or "",
                }
                html_parts.append(
                    f"<ruby>{_html.escape(tok['text'], quote=False)}"
                    f"<rt>{_html.escape(ctx, quote=False)}</rt></ruby>"
                )
            else:
                # 复现：不再注释中文
                html_parts.append(_html.escape(tok["text"], quote=False))
        lines.append({"words": words, "html": "".join(html_parts)})
    return {
        "lines": lines,
        "vocabulary": [vocab[h] for h in vocab],
        "word_count": word_count,
        "new_word_count": new_count,
        "new_word_rate": round(new_count / word_count, 4) if word_count else 0.0,
    }


def record_reading(
    reading_id: str,
    level: int,
    completed_ratio: float,
    seconds: int,
    new_word_clicks: list,
    user_id: str | None = None,
) -> None:
    """追加一条阅读记录（JSONL），供后续「已知词概率模型」离线分析。失败不影响接口。"""
    try:
        path = Path(settings.reading_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": round(time.time(), 3),
            "user_id": user_id,
            "reading_id": reading_id,
            "level": level,
            "completed_ratio": completed_ratio,
            "seconds": seconds,
            "new_word_clicks": new_word_clicks,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
