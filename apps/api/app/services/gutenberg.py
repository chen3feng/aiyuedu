"""古腾堡导入：拉取 + 拆章节。

数据源：
- 元数据：https://gutendex.com/books/{book_id}（公开 API，免 key，OAS 见 gutendex.com）
- 正文：formats['text/plain; charset=utf-8'] 的纯文本 URL

不支持 HTML（爬虫成本 + boilerplate 多），只取纯文本。

章节拆分三层启发式（与 issue #2 对齐）：
1. 硬切：识别标题行作为章节边界（CHAPTER I. / Chapter 1 / 罗马数字 / 中文 第X章）
2. 过长拆分：单章 > 3500 词 → 在空行（≥2 个连续 \\n）处按 ~2000 词切
3. 过短合并：单章 < 800 词 → 与下一章合并（直到 ≥ 1200 词或已是最后一章）

目标区间：800-3500 词 / 章，中位数 2000。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

GUTENDEX_API = "https://gutendex.com/books/{book_id}"
USER_AGENT = "aiyuedu/1.0 (+https://github.com/chen3feng/aiyuedu)"

# 标题行匹配（多行模式 ^/$）
_CHAPTER_PATTERNS = [
    # 英文：CHAPTER I. / CHAPTER 1. / CHAPTER ONE（可带尾部 ] 容纳 "Chapter I.]" 这类目录标记）
    re.compile(r"(?im)^chapter\s+([ivxlcdm]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b\.?\s*\]?\s*$"),
    # 英文：Chapter 1 / Chapter One（同样允许尾部 ]）
    re.compile(r"(?im)^chapter\s+\d+\s*\]?\s*$"),
    re.compile(r"(?im)^chapter\s+(one|two|three|four|five|six|seven|eight|nine|ten)\b\.?\s*\]?\s*$"),
    # 数字编号（Project Gutenberg 常见）：  1. Sara /  2. A French Lesson
    re.compile(r"(?m)^\s*\d{1,3}\.\s+\S"),
    # 裸数字 + 下一行是标题（1 / Sara）
    re.compile(r"(?m)^\s*\d{1,3}\s*$"),
    # 中文：第X章 / 第X回 / 卷X
    re.compile(r"(?m)^第[一二三四五六七八九十百千零0-9]+[章回]\s*$"),
    re.compile(r"(?m)^卷[一二三四五六七八九十百千零0-9]+\s*$"),
    # 罗马数字独立行（兜底；CHAPTER ONE 之类）
    re.compile(r"(?m)^\s*[IVXLCDM]{2,}\s*$"),
]


@dataclass
class SplitConfig:
    """章节粒度控制"""
    min_words: int = 800       # 单章 < 此值时与下一章合并
    target_words: int = 2000   # 过长拆分的目标长度
    max_words: int = 5000      # 单章 > 此值时强制拆分；多数英语书单章 ≤ 4000 词


@dataclass
class Chapter:
    """拆分后的章节"""
    index: int
    title: str          # 第一行作为标题（去掉尾随空白）
    body: str           # 标题行之后到下一标题或正文结束
    word_count: int


# ---------- 拉取 ----------

def fetch_book(book_id: int) -> dict:
    """拉元数据 + 纯文本。返回 {title, author, summary, text, cover_url, source, language}。

    失败抛 RuntimeError（网络 / 解析 / 不可用文本格式）。
    """
    # 1) gutendex 元数据
    try:
        r = httpx.get(
            GUTENDEX_API.format(book_id=book_id),
            timeout=60.0,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
    except httpx.HTTPError as e:
        raise RuntimeError(f"拉取古腾堡元数据失败：{e}") from e
    if r.status_code == 404:
        raise RuntimeError(f"古腾堡 book_id={book_id} 不存在")
    if r.status_code != 200:
        raise RuntimeError(f"古腾堡元数据返回 {r.status_code}")
    try:
        meta = r.json()
    except Exception as e:
        raise RuntimeError(f"古腾堡元数据 JSON 解析失败：{e}") from e

    # 2) 选纯文本 URL（优先 UTF-8）
    formats = meta.get("formats") or {}
    text_url = formats.get("text/plain; charset=utf-8") or formats.get("text/plain; charset=us-ascii")
    if not text_url:
        raise RuntimeError(f"book {book_id} 无可用的纯文本格式")

    # 3) 拉正文
    try:
        tr = httpx.get(text_url, timeout=180.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    except httpx.HTTPError as e:
        raise RuntimeError(f"拉取正文失败：{e}") from e
    if tr.status_code != 200:
        raise RuntimeError(f"正文返回 {tr.status_code}")
    text = tr.text

    text = strip_gutenberg_boilerplate(text)

    cover_url = formats.get("image/jpeg")

    authors = meta.get("authors") or []
    author_name = ", ".join(a.get("name", "") for a in authors if a.get("name"))
    summaries = meta.get("summaries") or [""]

    return {
        "title": meta.get("title", ""),
        "author": author_name,
        "summary": summaries[0] if summaries else "",
        "text": text,
        "cover_url": cover_url,
        "source": f"gutenberg://{book_id}",
        "language": (meta.get("languages") or ["en"])[0],
    }


def strip_gutenberg_boilerplate(text: str) -> str:
    """剥 *** START OF ... / *** END OF ... 之间的正文"""
    start_marker = text.find("*** START OF")
    end_marker = text.find("*** END OF")
    if start_marker >= 0:
        # 跳过 START marker 那一行
        nl = text.find("\n", start_marker)
        start = nl + 1 if nl >= 0 else start_marker
    else:
        start = 0
    if end_marker >= 0:
        # 保留到 *** END OF 之前那一行
        last_nl = text.rfind("\n", 0, end_marker)
        end = last_nl if last_nl >= 0 else end_marker
    else:
        end = len(text)
    body = text[start:end].strip()
    # 末尾的 "Produced by ..." 之类也常见，保留——不去除
    return body


# ---------- 拆章节 ----------

# 古腾堡纯文本斜体：_text_（首个字符非空白，天然跳过 "____" 分隔线与 "_ _"）
_UNDERSCORE_EM_RE = re.compile(r"_([^_\s][^_]*?)_")


def underscores_to_em(text: str) -> str:
    """古腾堡斜体标记 _text_ → <em>text</em>（阅读端渲染斜体强调）。

    - 内容允许内部换行（软回车折行截断的斜体），但不允许跨段落（含空行
      则保持原样：斜体不该跨段，宁可漏转也不错转）
    - 词首非空白约束让 "______" 分隔线、"_ _ _" 之类装饰线天然不匹配
    """
    def _conv(m: re.Match) -> str:
        inner = m.group(1)
        if re.search(r"\n\s*\n", inner):
            return m.group(0)
        return f"<em>{inner}</em>"

    return _UNDERSCORE_EM_RE.sub(_conv, text)


# 插图注记起点：[Illustration] / [Illustration: caption]
_ILLUS_START_RE = re.compile(r"\[[Ii]llustration\b")
# 块结尾后紧跟的整段空行（删块时一并吞掉，避免留下 3+ 连续空行）
_TRAILING_BLANKS_RE = re.compile(r"[ \t]*\r?\n(?:[ \t]*\r?\n)*")


def strip_illustrations(text: str) -> str:
    """删掉 [Illustration...] 插图注记块（含 caption）。

    纯文本里没有对应图片，注记只是噪音；caption 常是相邻正文的引文
    （如 1894 插图版傲慢与偏见的 “He came down to see the place”），
    保留会与正文重复。块内可嵌套 [...]（如 "[_Copyright 1894 ..._]]"），
    用括号深度扫描找闭合 ]，正则做不到。

    删块后把块所在段的空行一并吞掉：插图本来就在段落之间，删后留下
    一个干净的段落分隔即可。两类例外：
    - 闭合 ] 挂在章节标题行尾（扉页样式）→ 标题幸存，只吞 ]
    - 畸形未闭合块跳过不动（宁留勿删）
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while True:
        m = _ILLUS_START_RE.search(text, i)
        if m is None:
            out.append(text[i:])
            break
        out.append(text[i : m.start()])
        # 从 [ 起做括号深度扫描找闭合 ]
        depth = 0
        end = -1
        for j in range(m.start(), n):
            c = text[j]
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end < 0:
            # 未闭合：跳过这个 [ 继续扫后面的块
            out.append(text[m.start() : m.start() + 1])
            i = m.start() + 1
            continue
        # 闭合 ] 所在行若有非空白前缀：caption 本该在前面结束，这一行是「恰好
        # 带着闭合括号的正文」。只有章节标题才幸存（傲慢与偏见扉页即
        # "[Illustration: ·PRIDE AND PREJUDICE· …\nChapter I.]"，闭合 ] 挂在
        # 第一章标题行尾）；其余（如 [_Copyright …._]] 的版权注行）仍是 caption。
        j = end - 1  # text[j] == ']'
        line_start = text.rfind("\n", m.start(), j) + 1
        prefix = text[line_start:j]
        if line_start > m.start() and prefix.strip() and _is_chapter_heading(prefix):
            out.append(prefix)
            i = j + 1  # 只吞掉 ]，标题行之后的空行留给段落分隔
            continue
        # 吞掉块后的空行（要求至少一个换行，避免把行中空格也吞掉）
        tail = _TRAILING_BLANKS_RE.match(text, end)
        i = tail.end() if tail else end
    return "".join(out)


def _is_chapter_heading(line: str) -> bool:
    """一行是否是章节标题（去前后空白后精确匹配）。"""
    s = line.strip()
    if not s or len(s) > 80:
        return False
    return any(p.match(s) for p in _CHAPTER_PATTERNS)


def _word_count(text: str) -> int:
    """粗略词数（按空白拆；英文 / 中文都适用）。"""
    return len(text.split())


def split_chapters(text: str, config: SplitConfig | None = None) -> list[Chapter]:
    """主入口：把整本书文本拆成 N 个章节。

    算法：
      0. 剥目录（如果开头有 TOC）
      1. 按章节标题行硬切
      2. 过长（> max_words）按空行再切
      3. 过短（< min_words）与下一章合并
    """
    cfg = config or SplitConfig()
    text = _strip_table_of_contents(text)
    text = strip_illustrations(text)
    raw = _hard_split(text)
    raw = _split_long_chapters(raw, cfg)
    raw = _merge_short_chapters(raw, cfg)
    return _finalize(raw)


def _strip_table_of_contents(text: str) -> str:
    """剥掉开头的目录页（如果存在）。

    Project Gutenberg 很多书开头有目录：编号 + 标题连续多行。

    启发式：扫描开头 200 行，找**最长连续**的 `\\d{1,3}\\. \\S` 块；如果 ≥ 5 行
    就视为目录，整段从该块的结束位置截掉。空行 / 标题行 / 普通段不打断扫描。
    """
    lines = text.split("\n")
    scan_until = min(200, len(lines))
    # 找所有 TOC run（连续匹配 `\d{1,3}\. \S` 的行块；空行延续）
    runs: list[list[int]] = []
    cur: list[int] = []
    for i in range(scan_until):
        line = lines[i]
        if re.match(r"^\s*\d{1,3}\.\s+\S", line):
            cur.append(i)
        elif line.strip() == "":
            # 空行延续当前 run
            if cur:
                cur.append(i)
        else:
            # 非空非 TOC：当前 run 结束；下一行起重新开始扫描
            if cur:
                runs.append(cur)
                cur = []
    if cur:
        runs.append(cur)
    if not runs:
        return text
    # 选 TOC 行数最多的 run（排除空行）
    best = max(runs, key=lambda r: sum(1 for i in r if re.match(r"^\s*\d{1,3}\.\s+\S", lines[i])))
    toc_lines = [i for i in best if re.match(r"^\s*\d{1,3}\.\s+\S", lines[i])]
    if len(toc_lines) < 5:
        return text
    cut_at = best[-1] + 1
    # 跳过 cut_at 之后的连续空行
    while cut_at < len(lines) and lines[cut_at].strip() == "":
        cut_at += 1
    return "\n".join(lines[cut_at:])


# 「CHAPTER I.」/「Chapter 1」式的裸编号标题（后面可能另起一行跟副标题）
_NUMBERED_ONLY_RE = re.compile(
    r"^(?:chapter|chap\.?|cap\.?)\s+(?:[ivxlcdm]+|\d{1,3})[.\]]?$", re.IGNORECASE
)


def _looks_like_subtitle(line: str) -> bool:
    """启发式判断一行是否为章节副标题（而非正文首句）。

    规则：≤10 词；首词大写；所有 ≥5 字母的词都首字母大写（书名式大小写，
    允许 the/from/a/and/in 这类短虚词小写）；大写词占比 ≥ 一半；不含逗号/分号。
    如 "Down the Rabbit-Hole"、"Advice from a Caterpillar"、"Who Stole the Tarts?"。
    """
    s = line.strip()
    words = re.findall(r"[A-Za-z’'-]+", s)
    if not 1 <= len(words) <= 10:
        return False
    if not words[0][0].isupper():
        return False
    if any(c in s for c in (",", ";", "—", "--")):
        return False
    if s.endswith("."):  # 副标题不以句号结尾（正文首句才是；问号允许：Who Stole the Tarts?）
        return False
    caps = sum(1 for w in words if w[0].isupper())
    long_lower = any(len(w) >= 5 and not w[0].isupper() for w in words)
    return not long_lower and caps / len(words) >= 0.5


def _hard_split(text: str) -> list[Chapter]:
    """按章节标题行硬切。

    形式1：标题独占一行（"CHAPTER I." / "Sara" / "第1章"）
    形式2：编号 + 章节名两行——把两行合并成章节标题：
           - 裸数字编号（"1" / "Sara"）→ "1 Sara"，允许中间夹空行
           - 编号式标题（"CHAPTER I." / "Down the Rabbit-Hole"）→
             "CHAPTER I. Down the Rabbit-Hole"；副标题须通过 _looks_like_subtitle，
             且与下方正文之间有空行相隔（防止误吞正文首句）
    """
    lines = text.split("\n")
    chapters: list[list[str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _is_chapter_heading(line):
            title = line.strip()
            # 形式2a：当前行是裸数字，找下一行非空内容作为章节名
            if re.match(r"^\s*\d{1,3}\s*$", title):
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and not _is_chapter_heading(lines[j]):
                    nxt = lines[j].strip()
                    title = f"{title} {nxt}"
                    i = j + 1
                    chapters.append([title])
                    continue
            # 形式2b：「CHAPTER I.」式裸编号标题，下一行（允许隔空行）是副标题
            elif _NUMBERED_ONLY_RE.match(title):
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                # 副标题之后须至少有一个空行与正文相隔
                k = j + 1
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if (
                    j < len(lines)
                    and not _is_chapter_heading(lines[j])
                    and _looks_like_subtitle(lines[j])
                    and k > j + 1  # 中间确实夹了空行
                ):
                    nxt = lines[j].strip()
                    title = f"{title} {nxt}"
                    i = j + 1
                    chapters.append([title])
                    continue
            chapters.append([title])
            i += 1
        else:
            if chapters:
                chapters[-1].append(line)
            i += 1
    # 转成 Chapter 列表
    out: list[Chapter] = []
    for lines_in_ch in chapters:
        if not lines_in_ch:
            continue
        title = lines_in_ch[0].strip()
        body = "\n".join(lines_in_ch[1:]).strip()
        if not body:
            continue
        out.append(Chapter(index=0, title=title, body=body, word_count=_word_count(body)))
    return out


def _split_long_chapters(chapters: list[Chapter], cfg: SplitConfig) -> list[Chapter]:
    """过长章节按空行拆。后续 chunk 标题加 "（续 N/M）" 后缀。"""
    out: list[Chapter] = []
    for ch in chapters:
        if ch.word_count <= cfg.max_words:
            out.append(ch)
            continue
        # 按连续 ≥2 空行拆
        blocks = re.split(r"\n\s*\n\s*\n+", ch.body)
        chunks: list[str] = []
        buf = ""
        for blk in blocks:
            blk = blk.strip()
            if not blk:
                continue
            candidate = (buf + "\n\n" + blk).strip() if buf else blk
            if _word_count(candidate) > cfg.max_words and buf:
                chunks.append(buf)
                buf = blk
            else:
                buf = candidate
            if _word_count(buf) >= cfg.target_words:
                chunks.append(buf)
                buf = ""
        if buf:
            chunks.append(buf)
        # 加标题：第一块保留原标题，后续加「（续 2/3）」类后缀
        total = len(chunks)
        for idx, body in enumerate(chunks):
            if idx == 0:
                t = ch.title
            else:
                t = f"{ch.title}（续 {idx + 1}/{total}）"
            out.append(Chapter(
                index=0,
                title=t,
                body=body,
                word_count=_word_count(body),
            ))
    return out


def _merge_short_chapters(chapters: list[Chapter], cfg: SplitConfig) -> list[Chapter]:
    """过短章节与**正好下一个**下一章合并（不级联：A 合 B，合完即停止）。"""
    out: list[Chapter] = []
    skip_next = False
    for i, cur in enumerate(chapters):
        if skip_next:
            skip_next = False
            continue
        if cur.word_count < cfg.min_words and i + 1 < len(chapters):
            nxt = chapters[i + 1]
            merged_body = cur.body + "\n\n" + nxt.body
            out.append(Chapter(
                index=0,
                title=cur.title,
                body=merged_body,
                word_count=_word_count(merged_body),
            ))
            skip_next = True
        else:
            out.append(cur)
    return out


def _finalize(chapters: list[Chapter]) -> list[Chapter]:
    """重编号 index=1..N；body 里的 _text_ 斜体标记转成 <em>（标题不动）。"""
    return [
        Chapter(
            index=i + 1,
            title=c.title,
            body=underscores_to_em(c.body),
            word_count=c.word_count,
        )
        for i, c in enumerate(chapters)
    ]