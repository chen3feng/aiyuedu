"""从 vibe-writing 抓取的 Gemini 对话 JSON 中，抽取英文阅读材料为逐篇 .md，供导入素材库。

输入：<raw>/gemini-6bKWnzs2Ol8h.json（由 vibe-writing 抓取）
输出：
  - <raw>/articles/NNN_<slug>.md   每篇英文阅读材料（标题头 + 正文原文）
  - <raw>/index.md                 全部抽取结果清单（含跳过项说明）
  - <raw>/gemini-6bKWnzs2Ol8h.md   完整对话转 Markdown（存档）

用法：
  uv run --directory apps/api python data/readings/raw/extract_articles.py

说明：正文按 Gemini 原始输出逐字保留（含「生词表 / 随堂小测验 / 参考答案」，
以及行内图片造成的文字断裂与图片来源噪声）。清洗与导入（定级、生词标注、题目解析）
在后台导入时进行，本脚本只负责「抽出来、存档、列清单」。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent
SRC = RAW_DIR / "gemini-6bKWnzs2Ol8h.json"
OUT = RAW_DIR / "articles"

# 英文正文判定阈值：足够长，且中文占比足够低（避免把中文稿/空/垃圾当正文）
MIN_LEN = 500
MAX_CJK = 0.2

_CJK = re.compile(r"[一-鿿]")


def cjk_ratio(text: str) -> float:
    text = text.strip()
    if not text:
        return 0.0
    return len(_CJK.findall(text)) / len(text)


def slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug[:60] or "untitled"


def _is_title(line: str) -> bool:
    """标题应是短行且不以句末标点结尾；正文首句（长句 / 以 .?! 结尾）不算标题。"""
    line = line.strip()
    if len(line) > 120:
        return False
    if line.endswith((".", "?", "!", ";", ",")):
        return False
    return True


def _clean_title(line: str) -> str:
    """去掉被行内图片截断而残留的尾部标点/括号（如 “The History of Pi (” → “The History of Pi”）。"""
    return re.sub(r"[\s:—\-（(]+$", "", line).rstrip()


def split_title(lines: list[str]) -> tuple[str, str, list[str]]:
    """从非空行中分离（英文标题, 副标题, 正文行）。

    早期格式：第 1 行中文副标题、第 2 行英文标题；后续格式：第 1 行即英文标题。
    标题 = 第一条不含中文、且像标题的行；它之前的行视为副标题；之后为正文。
    若首条英文行其实是正文首句（无标题文章），则标题为空、整体归入正文。
    """
    subtitle_parts: list[str] = []
    i = 0
    while i < len(lines) and _CJK.search(lines[i]):
        subtitle_parts.append(lines[i])
        i += 1
    subtitle = " ".join(subtitle_parts).strip()
    if i < len(lines) and _is_title(lines[i]):
        return _clean_title(lines[i]), subtitle, lines[i + 1 :]
    # 无标题：所有剩余行都算正文
    return "", subtitle, lines[i:]


def classify(text: str) -> str:
    """把一条 model 回复分类为 english / chinese / garbage / empty。"""
    t = text.strip()
    if len(t) < MIN_LEN:
        return "empty" if not t else "garbage"
    if cjk_ratio(t) > MAX_CJK:
        return "chinese"
    return "english"


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    model_turns = [t for t in data if t.get("role") == "model"]

    OUT.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    skipped: list[dict] = []
    n = 0
    for m in model_turns:
        text = m["text"]
        kind = classify(text)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if kind != "english":
            skipped.append(
                {"kind": kind, "len": len(text), "preview": (lines[0][:60] if lines else "")}
            )
            continue
        n += 1
        title, subtitle, body = split_title(lines)
        slug = slugify(title)
        fname = f"{n:03d}_{slug}.md"
        out_path = OUT / fname
        header = f"# {title or '（无标题）'}\n"
        if subtitle:
            header += f"\n> {subtitle}\n"
        header += (
            "\n<!-- 来源：Gemini 对话（share.gemini.google/6bKWnzs2Ol8h） · "
            f"原文 {len(text)} 字符 · 汉字占比 {cjk_ratio(text):.0%} -->\n"
        )
        out_path.write_text(header + "\n" + "\n\n".join(body) + "\n", encoding="utf-8")
        rows.append(
            {"n": n, "file": fname, "title": title, "subtitle": subtitle, "len": len(text)}
        )

    _write_index(rows, skipped, model_turns)
    _write_markdown_dump(model_turns)

    print(f"抽取英文正文 {len(rows)} 篇 -> {OUT}")
    print(f"跳过 {len(skipped)} 项：")
    for s in skipped:
        print(f"  [{s['kind']:7}] {s['preview']}")
    return 0


def _write_index(rows: list[dict], skipped: list[dict], model_turns: list[dict]) -> None:
    lines = [
        "# Gemini 阅读材料抽取清单",
        "",
        "- 源：`share.gemini.google/6bKWnzs2Ol8h`（共 52 条 model 回复）",
        f"- 抽取英文正文 **{len(rows)}** 篇 → `articles/`",
        f"- 跳过 {len(skipped)} 项（中文重复稿 / 空 / 垃圾）",
        "",
        "## 文章清单",
        "",
        "| # | 文件 | 英文标题 | 中文副标题 | 字符数 |",
        "|---|------|----------|-----------|-------:|",
    ]
    for r in rows:
        title = (r["title"] or "（无标题）").replace("|", "\\|")
        subtitle = r["subtitle"].replace("|", "\\|")
        lines.append(f"| {r['n']} | `{r['file']}` | {title} | {subtitle} | {r['len']} |")

    lines += ["", "## 跳过项", "", "| 类型 | 预览 |", "|------|------|"]
    for s in skipped:
        preview = s["preview"].replace("|", "\\|")
        lines.append(f"| {s['kind']} | {preview} |")

    lines += [
        "",
        "## 数据质量提示",
        "",
        "- 正文为 Gemini 原始输出**逐字保留**：含「生词表 / 随堂小测验 / 参考答案」三节。",
        "- 行内图片导致部分句子被**拆断**，且图片来源（如 Collider / Getty Images / "
        "Fandango / SciNexic 等）作为独立行混入正文与生词表。导入前需人工清洗。",
        "- 跳过的 3 篇中文稿（福尔摩斯 / 计时技术 / 于谦）已有对应英文版（[67] / [73] / "
        "[89]），无需补英文。",
        "- 从约第 56 轮起存在**一轮错位**（回复对应用户上一条请求），但每篇正文自带标题，"
        "故按标题而非请求配对，不影响抽取。",
        "",
    ]
    (RAW_DIR / "index.md").write_text("\n".join(lines), encoding="utf-8")


def _write_markdown_dump(model_turns: list[dict]) -> None:
    """把完整对话转成 Markdown 存档（逐条 role 分节）。"""
    parts: list[str] = ["# Gemini 对话存档（share.gemini.google/6bKWnzs2Ol8h）", ""]
    for i, t in enumerate(model_turns):
        role = t.get("role", "unknown")
        parts.append(f"\n\n---\n\n## {role} #{i}\n")
        parts.append(t["text"])
    (RAW_DIR / "gemini-6bKWnzs2Ol8h.md").write_text("".join(parts), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
