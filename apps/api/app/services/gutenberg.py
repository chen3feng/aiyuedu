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


def _hard_split(text: str) -> list[Chapter]:
    """按章节标题行硬切。

    形式1：标题独占一行（"CHAPTER I." / "Sara" / "第1章"）
    形式2：编号 + 章节名两行（"1" / "Sara"）—— 把两行合并成章节标题 "1 Sara"
           允许中间夹空行。
    """
    lines = text.split("\n")
    chapters: list[list[str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _is_chapter_heading(line):
            title = line.strip()
            # 形式2：当前行是裸数字，找下一行非空内容作为章节名
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