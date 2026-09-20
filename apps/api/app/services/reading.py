"""分级阅读：生词判定 + 逐行对照注释。

按 Nation BNC/COCA 词族 rank（1~25000）判定生词：给定读者词汇量 level，
rank <= level 判「已知」，否则「生词」；不在词表、又无法还原到词族头的词也判「生词」。
生词率 = 生词 token 数 / 词 token 总数（数字与标点不计入）。

词形还原（surface -> 词族头）用 data/wordlists/surface_lemma.json，
由 data/wordlists/build_surface_lemma.py 从 raw 词族表 + 词形还原表生成，见 data/wordlists/README.md。

P1 简化：生词是「已知/未知」二值（设计 §7.1 概率模型的近似）；已做多词短语识别
（services.mwe，连续 trie + 可分离短语）；LLM 语境化消歧与术语层注释留 P2；
专有名词（句中大写）按已知处理、不注释义。
"""
import csv
import html as _html
import json
import re
import time
from functools import lru_cache
from pathlib import Path

from ..config import settings
from . import ecdict, mwe

# 领域标签（[医][计] 等）对少儿不友好，full_gloss 里剥掉
_BRACKET = re.compile(r"\[[^\]]*\]")
# 全角领域标签（ECDICT 的【物理学】【化】等），同样剥掉
_FULL_BRACKET = re.compile(r"【[^】]*】")
# 半角尖括号语体/地区标签（ECDICT 的 <非正> <英> <美> 等），剥掉
_ANGLE = re.compile(r"<[^<>]*>")
# 半角/全角圆括号里的括注（ECDICT 的语法说明，如「( fossil fuel的名词复数 )」、
# 「（god的复数）」「(不污染大气的)」等），short_gloss 里剥掉，只留核心义
_PAREN = re.compile(r"[（(][^（）()]*[）)]")
# 词性前缀（n./vt./adj./na. 等），short_gloss 里剥掉，只留中文义
_POS_RE = re.compile(r"^\s*(?:[A-Za-z]+\.\s*)+")


def full_gloss(translation: str) -> str:
    """完整意思：保留全部义项与词性，仅去掉 [医][计] 等领域标签，不截断。

    与 short_gloss（行内 ruby 单义项、去词性前缀）的区别：short_gloss 只取第一个义项；
    本文要求「文章结尾列出所有生词的完整意思」，故此处给全量义项。

    同时兼容两种来源的释义格式：词表用「；」分隔义项，ECDICT 用「\\n」分行（每行一个
    词性/义项）且常见「[法][计][经]」半角领域标签与「【物理学】」全角领域标签。
    「[网络] ...」行是机器抓取的网络释义（常为噪声，如 greenhouse effect 的
    「快乐工人/植物生长剂」），连同该行内「；」子义项整行丢弃；跨行重复义项去重
    （如 ECDICT 的「天体\\n[法] 天体」只留「天体」）。
    """
    if not translation:
        return ""
    groups: list[str] = []
    seen: set[str] = set()
    for line in translation.split("\n"):
        if line.strip().startswith("[网络]"):
            continue
        for g in line.split("；"):
            g = _ANGLE.sub("", _FULL_BRACKET.sub("", g))
            g = g.strip(" ,，;；\n\t")
            if not g:
                continue
            if "[" in g or "]" in g:
                continue  # 半角领域义项（如 [医]、[计]）跳过
            if g not in seen:
                seen.add(g)
                groups.append(g)
    if not groups:
        for line in translation.split("\n"):
            seg = _ANGLE.sub("", _FULL_BRACKET.sub("", _BRACKET.sub("", line))).strip(" ,，;；\n\t")
            if seg:
                groups = [seg]
                break
    return "；".join(groups)


def _short_line(s: str) -> str:
    """从单行释义取第一条短义（剥领域标签/括注/词性后取首个逗号义项）；无则空串。"""
    for seg in re.split(r"[；;]", s):
        seg = _ANGLE.sub("", _PAREN.sub("", _FULL_BRACKET.sub("", _BRACKET.sub("", seg))))
        seg = _POS_RE.sub("", seg).strip(" ,，;；\n\t")
        if not seg:
            continue
        parts = [p.strip() for p in re.split(r"[，,]", seg) if p.strip()]
        out = parts[0] if parts else seg
        if len(out) > 16:
            out = out[:16].rstrip(" ,，;；") + "…"
        return out
    return ""


def short_gloss(translation: str) -> str:
    """单条简短释义（行内 ruby 用）：只取第一个干净义项，去掉词性前缀与领域标签。

    与 full_gloss（全量、供生词本完整解释）相对，这里要「短而贴切」，避免
    「n. 土地，战场，场地；a. 土地的，地面上的」这类满行注释。半角/全角分号、逗号
    均按义项分隔；[网络]/【网络】噪声行整行丢弃；领域标签剥除后不再单独成义。
    现代技术词（hardcoding/refactoring/datacenters 等）常仅 [网络] 一行，此时退而
    取该行核心义，与 full_gloss 的兜底一致，避免「生词本有义、行内 ruby 空」。
    """
    if not translation:
        return ""
    for line in translation.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("[网络]") or s.startswith("【网络】"):
            continue
        out = _short_line(s)
        if out:
            return out
    # 全是 [网络]/【网络】行：退而取核心义兜底（现代技术词常仅网络释义）
    for line in translation.split("\n"):
        out = _short_line(line.strip())
        if out:
            return out
    return ""


def _network_only(translation: str) -> bool:
    """释义是否仅由 [网络]/【网络】噪声行构成（无任何干净行）。"""
    for line in (translation or "").split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("[网络]") or s.startswith("【网络】"):
            continue
        return False  # 存在干净行
    return True


# 目标学生估算词汇量（design §2.1：初一男生 ~3600），可用 ?level= 覆盖
DEFAULT_LEVEL = 3600

# 材料生成基准词汇量：后台生成词表时按此统一基准判定「生词」（rank > GLOSS_LEVEL），
# 覆盖各文章自动难度不一的问题；阅读端仍按用户自己的词汇量现筛现显。
GLOSS_LEVEL = 2000

# 句子切分：句末标点 + 空白（"9.58" 里的点后无空白，不会被误切）
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
# 古腾堡等长文本里有三种行尾：\r\n（Windows） / \r（旧 Mac，已罕见） / \n（Unix）。
# 先归一为 \n：1) 单 \n 软回车 → 空格；2) \n\n+ 段落分隔保留。
_CRLF_RE = re.compile(r"\r\n?")
_SOFT_WRAP_RE = re.compile(r"(?<!\n)\n(?!\n)")
# 常见英文缩写：句末 splitter 不能把这些点当句末（"Mr. Bennet" 不能被切成两句）
_ABBREV_RE = re.compile(
    r"\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Gen|Gov|Sgt|Capt|Lt|Cmdr|Hon|Rev|Fr|vs|etc|"
    r"i\.e|e\.g|cf|No|Inc|Co|Corp|Ltd|Fig|approx|dept|Univ|est|vol)\."
)
# 缩写点占位符（用 \x00 防止与正文冲突；最终替换回 .）
_ABBREV_PLACEHOLDER = "\x00"
# 词 token：数字（可含小数点与序数后缀 20th/21st/2nd/3rd，序数整体按数字处理，
# 避免把 "20th" 拆成 "20"+"th"，使 "th" 沦为生词/噪声）或字母词（内部可含撇号，
# 如 can't / don't）；其余为标点
_TOKEN_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?(?:st|nd|rd|th)?|[A-Za-z]+(?:'[A-Za-z]+)*)|([^A-Za-z0-9]+)")

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


_readings_cache: dict = {"mtime": None, "data": None}


def _load_readings() -> list:
    """读 readings.json，带 mtime 缓存：文件变化（含后台跨进程写入）自动重读。"""
    path = Path(settings.readings_path)
    mtime = path.stat().st_mtime
    if _readings_cache["data"] is None or _readings_cache["mtime"] != mtime:
        with open(path, encoding="utf-8") as f:
            _readings_cache["data"] = json.load(f)
        _readings_cache["mtime"] = mtime
    return _readings_cache["data"]


def _save_readings(items: list) -> None:
    """写盘并失效 mtime 缓存（后台增删改文章后即时可见）。"""
    path = Path(settings.readings_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.write("\n")
    _readings_cache["mtime"] = None
    _readings_cache["data"] = None


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
    # 1. 缩写点 → 占位符（防被误切）；2. 行尾归一；3. 软回车折叠；4. 句末切分；5. 还原占位符
    pre = _ABBREV_RE.sub(lambda m: m.group(0)[:-1] + _ABBREV_PLACEHOLDER, body)
    pre = _CRLF_RE.sub("\n", pre)
    pre = _SOFT_WRAP_RE.sub(" ", pre)
    sents = _SENT_SPLIT.split(pre.strip())
    return [s.replace(_ABBREV_PLACEHOLDER, ".").strip() for s in sents if s.strip()]


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
    if len(lower) == 1:
        # 单字母（数学符号/单位，如 r/v/h/e/g/m/s）不可能是生词，硬判噪声（无需词库）。
        # 须在词形还原之前判：surface_lemma 里 m/s 会还原到 be，若先还原会被误判成已知词。
        return {"w": text, "known": True, "noise": True}
    head = _head_of(lower)
    info = _load_heads().get(head) or _EXTRA_COMMON.get(head)
    if info:
        if info["rank"] <= level:
            return {"w": text, "known": True, "lemma": head}
        entry: dict = {
            "w": text, "known": False, "lemma": head, "rank": info["rank"],
            "gloss": short_gloss(info["translation"]),
            "full_gloss": full_gloss(info["translation"]),
        }
        if info["phonetic"]:
            entry["phonetic"] = info["phonetic"]
        return entry
    # 不在词表/补充表：大写词当专有名词（人名/地名），小写词先查 ECDICT 补释义。
    # 用还原头 head 而非表面形 lower 做 lemma：词表外的屈折（rovers/orbiters）已由
    # surface_lemma 还原到原型（rover/orbiter），使二者合并成同一生词条目。
    if text[0].isupper():
        return {"w": text, "known": True, "proper": True}
    ec = ecdict.lookup(lower)
    # 屈折形的释义若仅 [网络] 噪声，而词族头有干净释义（workflows→workflow「工作流程」），
    # 取词族头，避免行内 ruby / 生词本被网络噪声污染。
    if lower != head and ec and _network_only(ec.get("translation")):
        ec_head = ecdict.lookup(head)
        if ec_head and not _network_only(ec_head.get("translation")):
            ec = ec_head
    if ec is None:
        ec = ecdict.lookup(head)
    if ec and (ec.get("translation") or "").strip():
        fg = full_gloss(ec["translation"])
        if fg:
            entry = {
                "w": text, "known": False, "lemma": head,
                "gloss": short_gloss(ec["translation"]), "full_gloss": fg,
            }
            if ec.get("phonetic"):
                entry["phonetic"] = ec["phonetic"]
            return entry
    if ecdict.has_db(settings.ecdict_path):
        # 词库在、却查不到干净释义的碎片（单位/数学符号，如 km、th）视为噪声：
        # 照常显示但不计词、不进生词表，避免空释义污染 glosses。
        return {"w": text, "known": True, "noise": True}
    # 词库缺失（如 CI 无 811MB stardict.db）→ 降级为旧行为：生词、空释义待后台补全。
    return {"w": text, "known": False, "lemma": head, "gloss": "", "full_gloss": ""}


def _units(sentence: str, level: int, terms: dict | None = None) -> list[dict]:
    """把一句切成一列「渲染单元」：punct / num / word / term。

    word 单元是 _classify 的结果（已判已知/生词）；term 单元是文章级术语整体，
    {kind, w, lemma, gloss}，不计生词、不进生词表。多词匹配先于单词分类，命中的
    span 吃掉内部 token、不再逐词注释。

    只匹配文章级术语（terms）；全局短语库（mwe.json）不再驱动阅读端标注，避免作者
    未选定的短语（如 "work well"）被误注。多词匹配不跨非空白标点：逗号/句号等视为
    硬边界，短语只能横跨纯空白（如 "cooking oil" 可跨空格，"rice, noodles" 不会误配
    "rice noodles"）。渲染时整段 span 跳过，避免内部标点被重复输出。
    """
    tokens = _tokenize(sentence)
    word_pos = [k for k, t in enumerate(tokens) if t["kind"] == "word"]
    # 匹配序列：词 -> 小写文本；非空白标点 -> 空串哨兵（trie 无法匹配，天然断词）。
    seg: list[tuple] = []  # (text_or_None, token_start, token_end)
    for idx, k in enumerate(word_pos):
        if idx > 0:
            gap = tokens[word_pos[idx - 1] + 1 : k]
            if any(g["text"].strip() for g in gap):
                seg.append((None, -1, -1))
        seg.append((tokens[k]["text"].lower(), k, k + 1))
    match_words = ["" if s[0] is None else s[0] for s in seg]
    # 只匹配文章级术语；全局短语库不参与阅读端 ruby（见 docstring）。
    spans = mwe.match_terms(match_words, terms) if terms else []
    # span 的 seg 下标 -> 覆盖的 token 区间 [start, end)，渲染时整段跳过、避免内部标点重复
    span_by_start_tok: dict[int, tuple[int, dict]] = {}
    for s, e, en in spans:
        span_by_start_tok[seg[s][1]] = (seg[e - 1][2], en)

    units = []
    ti = 0
    n = len(tokens)
    while ti < n:
        tok = tokens[ti]
        if tok["kind"] == "punct":
            units.append({"kind": "punct", "w": tok["text"]})
            ti += 1
            continue
        if ti in span_by_start_tok:
            et, en = span_by_start_tok[ti]
            # 原文表面 = span 覆盖的全部 token 文本（仅空白间隙，无硬标点）
            surface = "".join(t["text"] for t in tokens[ti:et])
            # 短语/术语的释义可能来自全局短语库或文章 terms 的旧存储（含词性前缀/多义项），
            # 行内 ruby 一律用短义（short_gloss 兜底原义）。
            g = short_gloss(en["gloss"]) or en["gloss"]
            units.append({"kind": "term", "w": surface, "lemma": en["text"], "gloss": g})
            ti = et
            continue
        entry = _classify(tok["text"], level)
        entry["kind"] = "word"
        units.append(entry)
        ti += 1
    return units


def _count(body: str, level: int, terms: dict | None = None, skip: list | None = None) -> tuple[int, int]:
    """返回 (词 token 数, 生词 token 数)，数字与标点不计入；短语/术语各按 1 个单元计。

    术语不计入生词数（纯语境注释，不复习）。skip 是后台手工删掉的生词（词族头），
    按已知处理：计词数、不计生词数。
    """
    skip_set = set(skip) if skip else set()
    word_count = new_count = 0
    for sentence in _sentences(body):
        for u in _units(sentence, level, terms):
            if u["kind"] == "punct" or u.get("num") or u.get("noise"):
                continue
            word_count += 1
            if u["kind"] == "mwe":
                new_count += 1
            elif u["kind"] == "word" and not u.get("known"):
                head = u.get("lemma") or u["w"].lower()
                if head not in skip_set:
                    new_count += 1
    return word_count, new_count


def stats(body: str, level: int, terms: dict | None = None, skip: list | None = None) -> dict:
    """轻量统计（列表用，不生成逐词结构）。"""
    word_count, new_count = _count(body, level, terms, skip)
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
    terms: dict | None = None,
    skip: list | None = None,
    only_glosses: bool = False,
) -> dict:
    """逐句切分并逐词标注：每行附 ruby 标注 HTML + 词级 token；文末生词表（完整意思）。

    每个生词只在**首次出现**时加 `<ruby>` 中文注释，之后复现不再注释（鼓励回忆，
    避免满篇注音）。生词表按首次出现顺序去重列出，`word` 为展示用原型。

    两种注音口径：
    - `only_glosses=False`（后台「自动定级」）：按 level 判生词，`glosses` 提供语境义、
      词典兜底（用于自动生成 glosses 供作者再手工改）。
    - `only_glosses=True`（读者端）：只注 `glosses`/`terms` 中作者**显式选定**的词/短语，
      无词典兜底、不按 level 自动补注（避免非作者选定的词被误注）。

    - `glosses`：词族头 -> 本文最贴切的语境义（行内 `<ruby>` 只标这一义）。
    - `full_glosses`：词族头 -> 完整意思覆盖（派生词「词面义 ≠ 词族头义」时用，如
      propeller->propel；缺省用词族头的 full_gloss）。
    - `headwords`：词族头 -> 展示词形覆盖 `{word, phonetic}`（派生词是独立词条、词族头
      并非其原型时用，如 propeller->propel 应展示「propeller」；缺省展示词族头）。
    - `terms`：术语文本 -> 语境义（文章级多词注释；每次出现都注 ruby，不计生词、不进生词表）。
    - `skip`：后台手工删掉的生词（词族头列表），按已知处理（不注音、不进生词表、不计生词）。
    """
    glosses = glosses or {}
    full_glosses = full_glosses or {}
    headwords = headwords or {}
    skip_set = set(skip) if skip else set()
    lines = []
    vocab: dict[str, dict] = {}  # 词族头 -> 生词表条目（按首次出现顺序）
    word_count = new_count = 0
    for sentence in _sentences(body):
        words = []
        html_parts: list[str] = []
        for u in _units(sentence, level, terms):
            kind = u["kind"]
            if kind == "punct":
                words.append({"w": u["w"], "punct": True})
                html_parts.append(_html.escape(u["w"], quote=False))
                continue
            if u.get("num"):
                words.append(u)
                html_parts.append(_html.escape(u["w"], quote=False))
                continue
            if u.get("noise"):
                # 噪声碎片（单字母/单位/数学符号）：照常显示，但不计词、不进生词表
                words.append(u)
                html_parts.append(_html.escape(u["w"], quote=False))
                continue
            if kind == "term":
                # 术语：行内注释（每次出现都注），不计生词数、不进生词表
                word_count += 1
                words.append({"w": u["w"], "known": True, "term": True, "gloss": u["gloss"]})
                html_parts.append(
                    f"<ruby>{_html.escape(u['w'], quote=False)}"
                    f"<rt>{_html.escape(u['gloss'], quote=False)}</rt></ruby>"
                )
                continue
            # 单词
            words.append(u)
            word_count += 1
            head = u.get("lemma") or u["w"].lower()
            if head in skip_set:
                # 后台手工删掉的生词：按已知处理，不进生词表
                u["known"] = True
                html_parts.append(_html.escape(u["w"], quote=False))
                continue
            # 注音口径：only_glosses（读者端）只注 glosses 已收录的词；否则按 level 判生词。
            if only_glosses and head not in glosses:
                html_parts.append(_html.escape(u["w"], quote=False))
                continue
            if not only_glosses and u["known"]:
                html_parts.append(_html.escape(u["w"], quote=False))
                continue
            new_count += 1
            # 行内 ruby 只显示「文中最贴切的单一义」：对文章 glosses 的旧存冗长释义
            # （含词性前缀/多义项）同样归一为短义，保证展示干净、可人工再改。
            ctx = short_gloss(glosses.get(head)) or short_gloss(u.get("gloss")) or ""
            if head not in vocab:
                # 首次出现：加 ruby 中文注释，并录入生词表（展示用原型）
                wf = headwords.get(head) or {}
                vocab[head] = {
                    "word": wf.get("word") or head,
                    "lemma": head,
                    "phonetic": wf.get("phonetic") or u.get("phonetic", ""),
                    "gloss": ctx,
                    "full_gloss": full_glosses.get(head) or u.get("full_gloss") or "",
                }
                html_parts.append(
                    f"<ruby>{_html.escape(u['w'], quote=False)}"
                    f"<rt>{_html.escape(ctx, quote=False)}</rt></ruby>"
                )
            else:
                # 复现：不再注释中文
                html_parts.append(_html.escape(u["w"], quote=False))
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


# ---------- 后台：自动定级 / 自动注释 / 文章 CRUD ----------


def suggest_level(body: str, target_rate: float = 0.03, terms: dict | None = None) -> dict:
    """按词频自动定级：取生词率最接近 target_rate 的词汇量档位，四舍五入到百位。

    生词率随 level 单调非增，扫描 500→20000（步长 500）取最接近者即可。
    返回 {level, word_count, new_word_count, new_word_rate}。
    """
    best: dict | None = None
    for level in range(500, 20001, 500):
        st = stats(body, level, terms)
        if best is None or abs(st["new_word_rate"] - target_rate) < abs(
            best["new_word_rate"] - target_rate
        ):
            best = {"level": level, **st}
    best["level"] = round(best["level"] / 100) * 100
    return best


def build_glosses(body: str, level: int, terms: dict | None = None) -> dict:
    """自动提取生词语境义：词族头 -> 词典义（后台可再手工改）。

    full_glosses / headwords 是派生词「词面义 ≠ 词族头义」时的人工覆盖，
    自动提取无法推断，故这里只产出 glosses。术语与多词短语不进 glosses
    （短语另走 multiword/terms），避免在 glosses 里混入带空格的多词键。
    """
    ann = annotate(body, level, terms=terms)
    return {v["lemma"]: v["gloss"] for v in ann["vocabulary"] if not v.get("phrase")}


def next_reading_id() -> str:
    """按现有最大编号生成下一个 id（r001、r002…）。"""
    nums = [
        int(r["id"][1:])
        for r in _load_readings()
        if r.get("id", "").startswith("r") and r["id"][1:].isdigit()
    ]
    return f"r{max(nums, default=0) + 1:03d}"


def add_reading(article: dict) -> dict:
    items = _load_readings()
    items.append(article)
    _save_readings(items)
    return article


def update_reading(reading_id: str, article: dict) -> dict | None:
    items = _load_readings()
    for i, r in enumerate(items):
        if r.get("id") == reading_id:
            items[i] = article
            _save_readings(items)
            return article
    return None


def delete_reading(reading_id: str) -> bool:
    items = _load_readings()
    kept = [r for r in items if r.get("id") != reading_id]
    if len(kept) == len(items):
        return False
    _save_readings(kept)
    return True
