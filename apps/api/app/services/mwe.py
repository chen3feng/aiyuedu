"""多词短语（MWE）匹配：连续短语 trie + 可分离动词短语（verb ... particle）。

阅读标注在单词分类**之前**先跑 MWE 匹配：命中的整段合成一个单元、只注一次义，
避免把 throw / up 各注一个无关释义。可分离短语（take it apart）用「动词 + 有界
间隔内的小品词」匹配，间隔上限 SEPARABLE_MAX_GAP；超出间隔则回退为逐词处理。

短语暂无词频，一律按「生词」对待（见 reading._units）；术语层另走文章级注释，
经 match_terms 匹配，不计生词、不进全局词典（见 reading._units）。
"""
import json
from functools import lru_cache

from ..config import settings
from .storage import atomic_write_json, load_json_or

# 可分离短语中「动词」与「小品词」之间允许隔的最大单词数（take the clock apart）
SEPARABLE_MAX_GAP = 4


def build_trie(items: list) -> tuple:
    """把条目列表建两套结构：连续短语 trie + 可分离 verb -> [(particle, entry)]。"""
    trie: dict = {}
    separable: dict = {}
    for it in items:
        text = (it.get("text") or "").strip().lower()
        gloss = (it.get("gloss") or "").strip()
        if not text or not gloss:
            continue
        entry = {"text": text, "gloss": gloss, "type": it.get("type", "phrasal_verb")}
        if it.get("separable"):
            parts = text.split()
            if len(parts) == 2:
                separable.setdefault(parts[0], []).append((parts[1], entry))
            continue
        node = trie
        for w in text.split():
            node = node.setdefault(w, {})
        node["$"] = entry
    return trie, separable


@lru_cache(maxsize=1)
def _load() -> tuple:
    """返回 (trie, separable)。trie 用于连续短语；separable: verb -> [(particle, entry)]。"""
    data = load_json_or(settings.mwe_path, {"items": []})
    if not isinstance(data, dict):
        data = {"items": []}
    return build_trie(data.get("items") or [])


def match_spans(
    words: list[str], trie: dict | None = None, separable: dict | None = None
) -> list[tuple[int, int, dict]]:
    """words: 小写单词序列。返回 [(start, end, entry)]，end 开区间、按 start 升序不重叠。

    优先级：当前位置先试「连续最长匹配」（"take over" 优先于 "take"），无则试
    「可分离短语」（verb 在 start，向后找 particle，取最近的、间隔 ≤ SEPARABLE_MAX_GAP）。
    trie/separable 缺省用全局 mwe.json；传外部 trie 可匹配文章级术语。
    """
    if trie is None:
        trie, separable = _load()
    spans: list[tuple[int, int, dict]] = []
    n = len(words)
    i = 0
    while i < n:
        # 1) 连续最长匹配
        node = trie
        best: tuple[int, int, dict] | None = None
        j = i
        while j < n and words[j] in node:
            node = node[words[j]]
            j += 1
            if "$" in node:
                best = (i, j, node["$"])
        if best:
            spans.append(best)
            i = best[1]
            continue
        # 2) 可分离短语
        w = words[i]
        if w in separable:
            found: tuple[int, int, dict] | None = None
            for particle, entry in separable[w]:
                for j in range(i + 1, min(n, i + 1 + SEPARABLE_MAX_GAP)):
                    if words[j] == particle:
                        if found is None or j < found[1]:
                            found = (i, j + 1, entry)
                        break
            if found:
                spans.append(found)
                i = found[1]
                continue
        i += 1
    return spans


def match_terms(words: list[str], terms: dict) -> list[tuple[int, int, dict]]:
    """文章级术语匹配：terms = {text: gloss}，建成无分离 trie 后复用 match_spans。"""
    items = [{"text": t, "gloss": g, "type": "term"} for t, g in terms.items() if t and g]
    if not items:
        return []
    trie, _ = build_trie(items)
    return match_spans(words, trie, {})


def texts() -> frozenset:
    """全局短语 canonical 文本集合（后台 analyze 里跳过已全局短语）。"""
    try:
        with open(settings.mwe_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return frozenset()
    return frozenset((it.get("text") or "").strip().lower() for it in data.get("items") or [])


def add_phrases(entries: list) -> int:
    """把新短语按 text 排重并入 mwe.json（只增不减），返回新增条数。"""
    try:
        with open(settings.mwe_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {"items": []}
    existing = {(it.get("text") or "").strip().lower() for it in data.get("items") or []}
    added = 0
    for e in entries:
        text = (e.get("text") or "").strip().lower()
        gloss = (e.get("gloss") or "").strip()
        if not text or not gloss or text in existing:
            continue
        data.setdefault("items", []).append({
            "text": text,
            "gloss": gloss,
            "type": "phrasal_verb",
            "separable": False,
        })
        existing.add(text)
        added += 1
    if added:
        atomic_write_json(settings.mwe_path, data)
        _load.cache_clear()
    return added
