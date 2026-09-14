"""把 data/readings/raw/articles/*.md 批量导入素材库（readings.json + mwe.json）。

流程：解析每篇 .md（标题/副标题/正文/题目）→ 清洗正文（去图片噪声 + 重组被图拆断的句子）
→ 题目机械转换（三选一补「None of the above」成四选一；判断题转四选一）→ 复用
app.services.admin.analyze / create_article 自动定级 + 生词注释 + 术语/短语识别 → 写库。

运行：uv run --directory apps/api python data/readings/raw/import_gemini.py [--dry-run]

幂等：按标题去重，已导入的标题跳过，可安全重跑。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps" / "api"))

from app.services import admin, reading  # noqa: E402

RAW_DIR = Path(__file__).resolve().parent
ARTICLES = RAW_DIR / "articles"

# ---------- 正文清洗 ----------

BOX_CHARS = set("─│┌┐└┘┬┴┼├┤═║╔╗╚╝╠╣╦╩╬")
# 图片来源 / 图片说明等噪声（小写匹配）
NOISE_EXACT = {
    "collider", "fandango", "scinexic", "getty images", "wikimedia", "wikipedia",
    "britannica", "fandom", "james d. mccaffrey - wordpress.com", "+ 1", "+1",
}
NOISE_SUBSTR = [
    "opens in a new window", "how it works:", "pros & cons:", "pros and cons:",
    "plot:", "estimated author:", "main content:", "attributed to", "attribution:",
    "source: getty", "image source", "schematic of", "diagram of",
]

_NO_LETTER = re.compile(r"[A-Za-zͰ-Ͽἀ-῿]")  # 拉丁 + 希腊（π 等数学常量）
_CJK = re.compile(r"[一-鿿]")


def _is_noise(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if _CJK.search(s):  # 含中文 → 内容（解析等），非噪声
        return False
    if any(ch in BOX_CHARS for ch in s):
        return True
    low = s.lower()
    if low in NOISE_EXACT:
        return True
    for sub in NOISE_SUBSTR:
        if sub in low:
            return True
    if not _NO_LETTER.search(s):  # 无字母（纯标点/数字/符号）
        return True
    return False


def _clean_block(raw_block: str) -> str:
    """一个空行分隔的块内：去噪声行、用空格接回（被图拆断的词重新拼回句子）。"""
    parts = [ln.strip() for ln in raw_block.split("\n") if ln.strip() and not _is_noise(ln)]
    return " ".join(parts)


def _fix_spacing(text: str) -> str:
    """修标点前后空格：去掉 `. , ; : ! ? )` 前的空格、`(` `[` 后的空格。"""
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_body(raw: str) -> str:
    """正文去噪 + 重组句子 + 保留段落。

    空行分隔的块：若上一段未以句末标点结尾，则视作被图拆断的续句，接回上一段；
    否则另起一段（保留正文段落结构）。
    """
    paragraphs: list[str] = []
    for raw_block in re.split(r"\n\s*\n", raw):
        block = _clean_block(raw_block)
        if not block:
            continue
        if paragraphs and not paragraphs[-1].endswith((".", "?", "!")):
            paragraphs[-1] = paragraphs[-1] + " " + block
        else:
            paragraphs.append(block)
    return _fix_spacing("\n\n".join(paragraphs))


# ---------- 题目解析与转换 ----------

def _join_section(raw: str) -> str:
    """把一节（题目/答案）里被图拆断的行重新接成一段干净文本。"""
    parts = [ln.strip() for ln in raw.split("\n") if ln.strip() and not _is_noise(ln)]
    return _fix_spacing(" ".join(parts))


def _join_quiz(raw: str) -> str:
    """同 _join_section，但保留孤立「?」（题干结尾）与纯数字（选项文本 0/1/3.0 等）。"""
    parts = []
    for ln in raw.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if s in ("?", "？"):
            parts.append(s)
        elif re.search(r"[0-9]", s):  # 数字选项（0 / 1 / 3.0 / 7.9 / 11.2 …）
            parts.append(s)
        elif not _is_noise(ln):
            parts.append(s)
    return _fix_spacing(" ".join(parts))


def parse_mcqs(section: str) -> list[dict]:
    """解析单项选择题（每篇固定 2 题）。

    先把整段接回干净文本（图片拆断的选项文本、题干「?」都被拼回），再按
    「题干? A. … B. … C. …」的选项循环正则抽取。选项 C 的文本以「下一题题干」
    （疑问词开头的句子）为界，避免吞掉下一题。
    """
    text = _join_quiz(section)
    # 截断到判断题区之前
    m = re.search(r"(?:二、|II\.|判断正误|True\s*or\s*False)", text, re.I)
    if m:
        text = text[: m.start()]
    # 去掉小节头（一、单项选择题 / I. Multiple Choice 及其英文括号注释）
    text = re.sub(r"^.*?(?:单项选择题|Multiple\s*Choice)", "", text, flags=re.I)
    text = re.sub(r"^\s*(?:[一I]+、\s*|\([^)]*\)|[:：])\s*", "", text)

    qstart = (
        r"(?:Which|Who|Whose|Whom|How|What|Why|Where|When|"
        r"According|In|Have|Has|Is|Are|Was|Were|Do|Does|Did|"
        r"Can|Could|Would|Should|May|Might|Must)\b"
    )
    pat = re.compile(
        r"([^?]+)\?\s*"            # 题干（以 ? 结尾）
        r"A\.\s*(.*?)\s*"          # 选项 A
        r"B\.\s*(.*?)\s*"          # 选项 B
        r"C\.\s*(.*?)"             # 选项 C
        rf"(?=\s+{qstart}|\s*$)",  # 止于下一题题干或文本末尾
        re.S,
    )
    mcqs: list[dict] = []
    for m in pat.finditer(text):
        q = m.group(1).strip()
        opts = [
            ("A", m.group(2).strip()),
            ("B", m.group(3).strip()),
            ("C", m.group(4).strip()),
        ]
        if q and all(t for _, t in opts):
            mcqs.append({"q": q, "opts": opts})
    return mcqs[:2]  # 每篇固定 2 题（图片拆断偶发幻觉题，只保留前 2 题）


def parse_tf(section: str) -> str:
    """解析判断题陈述：取「判断正误 / True or False」之后、「T / F」之前的文本。"""
    text = _join_section(section)
    m = re.search(r"(?:判断正误|True\s*or\s*False)\s*[:：]?\s*(.*)", text, re.I | re.S)
    if m:
        text = m.group(1)
    m2 = re.search(r"T\s*/\s*F", text)
    if m2:
        text = text[: m2.start()]
    return text.strip().rstrip("(").strip()


def parse_answers(section: str) -> list[tuple[str, str]]:
    """解析答案区：answer 字母 + 其后的解析文本。"""
    answers: list[tuple[str, str]] = []
    cur_letter = None
    cur_text: list[str] = []
    for line in section.split("\n"):
        s = line.strip()
        if not s or _is_noise(line):
            continue
        if s in ("A", "B", "C", "D", "E", "F", "T"):
            if cur_letter is not None:
                answers.append((cur_letter, _fix_spacing(" ".join(cur_text))))
            cur_letter = s
            cur_text = []
        elif cur_letter is not None:
            cur_text.append(s)
    if cur_letter is not None:
        answers.append((cur_letter, _fix_spacing(" ".join(cur_text))))
    return answers


def _cn_explanation(raw: str) -> tuple[str, str]:
    """中文解析「（解析：文中提到了 "英文"，中文）」→ (中文解释, 英文引用)。"""
    raw = raw.strip().strip("（）()")
    raw = re.sub(r"^解析\s*[:：]\s*", "", raw)
    en = ""
    m = re.search(r'["“]([^"”]{10,})["”]', raw)
    if m:
        en = m.group(1).strip()
    zh = re.sub(r'["“][^"”]{10,}["”]', "", raw)
    zh = re.sub(r"^文中提到(了)?\s*[:：]?\s*", "", zh)
    zh = zh.strip(" ，,、;；")
    return zh, en


def _en_explanation(raw: str) -> tuple[str, str]:
    """英文解析（含 Explanation: 或裸括号）→ (中文空, 英文)。"""
    raw = raw.strip().strip("（）()")
    raw = re.sub(r"^Explanation\s*[:：]\s*", "", raw, flags=re.I)
    raw = raw.strip()
    return "", raw


def convert_quizzes(mcqs, mcq_answers, tf_statement, tf_letter, explain, tf_answer=None) -> list[dict]:
    quizzes: list[dict] = []
    for i, mcq in enumerate(mcqs):
        letter = mcq_answers[i][0] if i < len(mcq_answers) else ""
        options = []
        for l, text in mcq["opts"]:
            options.append({"text": text, "correct": l == letter})
        if len(options) == 3:
            options.append({"text": "None of the above", "correct": False})
        zh, en = explain(mcq_answers[i][1]) if i < len(mcq_answers) else ("", "")
        if not en and options:
            en = next((o["text"] for o in options if o["correct"]), "")
        quizzes.append({
            "type": "choice",
            "question": mcq["q"],
            "options": options,
            "explanation_zh": zh,
            "explanation_en": en,
        })
    # 判断题 → 四选一（True / False / Partly true / Cannot tell）
    is_true = tf_letter == "T"
    zh, en = explain(tf_answer) if tf_answer else ("", "")
    if not en and tf_statement:
        en = tf_statement
    quizzes.append({
        "type": "choice",
        "question": f"Is the following statement true? {tf_statement}",
        "options": [
            {"text": "True", "correct": is_true},
            {"text": "False", "correct": not is_true},
            {"text": "Partly true", "correct": False},
            {"text": "Cannot tell", "correct": False},
        ],
        "explanation_zh": zh,
        "explanation_en": en,
    })
    return quizzes


# ---------- 主题映射 ----------

def assign_topic(title: str, subtitle: str) -> str:
    """按标题/副标题关键词映射到主题；未知默认 science。"""
    blob = f"{title} {subtitle}".lower()
    rules = [
        (["olympic", "奥运会"], "sports"),
        (["sherlock", "福尔摩斯", "verne", "凡尔纳", "wuxia", "武侠", "悬疑"], "adventure"),
        (["xu xiake", "徐霞客", "xuanzang", "玄奘", "jianzhen", "鉴真", "luther king",
          "american revolutionary", "french revolution", "rosetta", "louvre", "卢浮宫",
          "panth", "先贤祠", "month", "weekday", "qi jiguang", "戚继光", "yue fei", "岳飞",
          "yu qian", "于谦", "firearm", "枪械", "novel", "名著", "roman", "古罗马"], "history"),
    ]
    for keys, topic in rules:
        for k in keys:
            if k in blob:
                return topic
    return "science"


# ---------- 逐篇解析 ----------

_SECTION_RE = re.compile(
    r"^(生词表|Vocabulary|Glossary|随堂小测验|单项选择题|Multiple Choice|I\.|一、"
    r"|参考答案|Answer Key|Explore)",
    re.I,
)


def parse_article(path: Path) -> dict:
    """解析一篇 .md → {title, subtitle, body, quizzes, topics}。"""
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    # 头部：标题 / 副标题 / 注释
    title = ""
    subtitle = ""
    body_start = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("# "):
            title = s[2:].strip()
        elif s.startswith("> "):
            subtitle = s[2:].strip()
        elif s.startswith("<!--"):
            body_start = i + 1
            break
    # 找到正文之后的第一个分节标记
    body_end = len(lines)
    for i in range(body_start, len(lines)):
        if _SECTION_RE.match(lines[i].strip()):
            body_end = i
            break
    raw_body = "\n".join(lines[body_start:body_end])
    body = clean_body(raw_body)

    # 分节内容（用于解析题目）
    section = {"quiz": "", "answers": ""}
    cur = None
    for i in range(body_end, len(lines)):
        s = lines[i].strip()
        if re.search(r"^(随堂小测验|Multiple Choice|I\.\s*Multiple|单项选择题)", s, re.I):
            cur = "quiz"
            continue
        if re.search(r"^(参考答案|Answer Key|Answers)", s, re.I):
            cur = "answers"
            continue
        if re.search(r"^(生词表|Vocabulary|Glossary|Explore)", s, re.I):
            cur = None
            continue
        if cur in ("quiz", "answers"):
            section[cur] += s + "\n"

    quizzes = []
    if section["quiz"] and section["answers"]:
        mcqs = parse_mcqs(section["quiz"])
        tf_statement = parse_tf(section["quiz"])
        answers = parse_answers(section["answers"])
        mcq_answers = [a for a in answers if a[0] in "ABCDE"]
        tf_answers = [a for a in answers if a[0] in "TF"]
        tf_letter = tf_answers[-1][0] if tf_answers else ("T" if tf_statement else "F")
        explain = _cn_explanation if "解析" in section["answers"] else _en_explanation
        tf_answer = tf_answers[-1][1] if tf_answers else None
        quizzes = convert_quizzes(mcqs, mcq_answers, tf_statement, tf_letter, explain, tf_answer)

    if not title or title == "（无标题）":
        # 无标题稿（如 036）：从正文首句派生标题
        first = body.strip().split("\n", 1)[0].strip()
        if len(first) > 60:
            first = first[:60].rsplit(" ", 1)[0] + "…"
        title = first or "（无标题）"

    return {
        "title": title,
        "subtitle": subtitle,
        "body": body,
        "quizzes": quizzes,
        "topics": [assign_topic(title, subtitle)],
    }


# ---------- 主流程 ----------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只解析打印，不写库")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 篇（0=全部）")
    args = ap.parse_args()

    files = sorted(ARTICLES.glob("*.md"))
    if args.limit:
        files = files[: args.limit]

    existing_titles = {r.get("title", "").strip().lower() for r in reading.list_readings()}

    imported = []
    skipped = []
    failed = []
    for f in files:
        try:
            art = parse_article(f)
        except Exception as e:  # noqa: BLE001
            failed.append((f.name, f"parse: {e}"))
            continue
        if art["title"].strip().lower() in existing_titles:
            skipped.append((f.name, "已存在"))
            continue
        if not art["body"]:
            failed.append((f.name, "正文为空"))
            continue
        if args.dry_run:
            imported.append((f.name, art["title"], len(art["body"]), len(art["quizzes"])))
            continue
        try:
            analysis = admin.analyze(art["body"])
            payload = {
                "title": art["title"],
                "subtitle": art["subtitle"],
                "body": art["body"],
                "topics": art["topics"],
                "target_level": analysis["level"],
                "glosses": analysis["glosses"],
                "full_glosses": {},
                "headwords": {},
                "multiword": analysis["multiword"],
                "quizzes": art["quizzes"],
            }
            created = admin.create_article(payload)
            imported.append((created["id"], art["title"], analysis["word_count"],
                             analysis["level"], len(art["quizzes"])))
        except Exception as e:  # noqa: BLE001
            failed.append((f.name, f"import: {e}"))
            continue

    print(f"共 {len(files)} 篇：导入 {len(imported)}，跳过 {len(skipped)}，失败 {len(failed)}")
    if args.dry_run:
        for name, title, blen, nq in imported:
            print(f"  [dry] {name} | {title[:50]} | 正文 {blen} 字 | 题 {nq}")
    else:
        for rid, title, wc, lvl, nq in imported:
            print(f"  {rid} | {title[:50]} | {wc} 词 | level {lvl} | 题 {nq}")
    for name, why in skipped:
        print(f"  [skip] {name} | {why}")
    for name, why in failed:
        print(f"  [FAIL] {name} | {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
