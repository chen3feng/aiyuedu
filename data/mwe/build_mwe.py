"""从中文维基教科书两页生成多词短语（MWE）种子库 mwe.json。

来源：
  - 英语/高中英语动词短语汇编（按动词分组，~700 条，带中文释义）
  - 英语/英语介词短语动词短语汇编（编号列表，~114 条）

处理：
  - 英文短语与中文释义按「首个 CJK 字符」切分；
  - 剥离 vt./vi./n. 等词性标签、`~~`/`sb.`/`sth`/`one's`/斜杠/括号等占位与歧义模式；
  - 含 `…`/`...` 的动词短语记为可分离（separable，verb=首词 particle=末词）；
  - 按 canonical 文本去重。

仅保留「可直接对正文匹配」的干净条目；带 sb./sth/one's 的习语型条目留待后续
更复杂的模式语言（gap/占位）再处理，本脚本跳过并统计。

运行：python data/mwe/build_mwe.py
"""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://zh.wikibooks.org/w/api.php"
TITLES = [
    "英语/高中英语动词短语汇编",
    "英语/英语介词短语动词短语汇编",
]
OUT = Path(__file__).resolve().parent / "mwe.json"

CJK = re.compile(r"[一-鿿]")
# 词性标签（英文侧，须 \b 定界，避免误删 down 里的 n / move 里的 v）
POS_EN = re.compile(r"\b(?:vt|vi|v|n|adj|adv|prep|conj|pron|num|art|int)\.?\b", re.I)
# 词性标签（中文释义侧，与汉字相邻无 \b，只匹配多字母标签，避免误删）
POS_ZH = re.compile(r"(?:vt|vi|adj|adv|prep|conj|pron|int|num|art)\.?", re.I)
# 需要跳过（占位符 / 歧义模式）：sb. sth one's 波浪线 斜杠 反斜杠 括号
SKIP = re.compile(r"sb\.?|sth\.?|one'?s|~~|~|[/\\]|\(|\)", re.I)
# 释义里的占位符（~~ / ～ / ---）统一替换成「…」
GLOSS_PH = re.compile(r"[~～]+|-{2,}")

# 手工补充：维基教科书缺失的高频动词短语（源自 PHaVE/PHRASE 高频项），带中文释义。
# 第三项为是否可分离（take it apart / point it out）。
SUPPLEMENT = [
    ("find out", "查明，发现", True),
    ("point out", "指出", True),
    ("figure out", "弄明白，想出", True),
    ("take apart", "拆开", True),
    ("take up", "开始从事；占用", True),
    ("trade in", "以旧换新", True),
    ("show off", "炫耀", True),
    ("hand in", "上交，提交", True),
    ("hand out", "分发", True),
    ("let down", "使失望", True),
    ("let in", "让…进来", True),
    ("pay back", "偿还；回报", True),
    ("pay off", "还清；得到回报", True),
    ("shut down", "关闭，停业", True),
    ("switch on", "打开（开关）", True),
    ("switch off", "关掉（开关）", True),
    ("wake up", "醒来；叫醒", True),
    ("work out", "解决；算出；锻炼", True),
    ("write down", "写下，记下", True),
    ("slow down", "放慢，减速", True),
    ("speed up", "加速", True),
    ("pull over", "靠边停车", True),
    ("hang out", "闲逛，泡在一起", False),
    ("come up with", "想出，提出", False),
    ("run out of", "用完，耗尽", False),
    ("deal with", "处理，应对", False),
    ("talk about", "谈论", False),
    ("wait for", "等待", False),
    ("turn up", "出现；调大（音量）", False),
    ("run away", "逃跑", False),
    ("hold on", "等一下；坚持", False),
    ("stand up", "起立，站立", False),
    ("stay up", "熬夜", False),
]
# 可分离标记（"build … into" / "take ... apart"）
ELLIPSIS = re.compile(r"…|\.\.\.")
# 连续词面（用于匹配）：只保留字母/空格/撇号/连字符
WORD_OK = re.compile(r"^[a-z][a-z'\- ]+$")


def fetch_wikitext(title: str) -> str:
    params = urllib.parse.urlencode({
        "action": "query", "prop": "revisions", "rvprop": "content",
        "rvslots": "main", "format": "json", "formatversion": "2", "titles": title,
    })
    req = urllib.request.Request(f"{API}?{params}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    for p in data["query"]["pages"]:
        revs = p.get("revisions", [{}])
        if revs:
            return revs[0].get("slots", {}).get("main", {}).get("content", "")
    return ""


def split_en_zh(line: str) -> tuple[str, str]:
    """按首个 CJK 字符切出 (english, chinese)。"""
    m = CJK.search(line)
    if not m:
        return line.strip(), ""
    return line[: m.start()].strip(), line[m.start() :].strip()


def clean_gloss(raw: str) -> str:
    g = raw.strip()
    g = POS_ZH.sub("；", g)  # 词性标签 → 分隔符，把 vt/vi 的义项分开（如「瓦解；出故障」）
    g = GLOSS_PH.sub("…", g)  # ~~ / ～ / --- 占位符 → …
    g = re.sub(r"\s+", " ", g)
    g = re.sub(r"[;；]{2,}", "；", g)
    g = g.strip(" ,，;；。·")
    return g


def normalize(en_raw: str) -> tuple[str, bool]:
    """返回 (canonical 短语文本, 是否可分离)；不合格返回 ('', False)。"""
    e = en_raw.strip()
    e = POS_EN.sub("", e)  # 去词性标签
    e = e.strip(" .…,，;；()")
    if ELLIPSIS.search(e):
        # 可分离："build … into" -> verb=build particle=into
        e = ELLIPSIS.sub(" ", e)
        words = re.findall(r"[a-z']+", e.lower())
        if len(words) == 2:
            return f"{words[0]} {words[1]}", True
        return "", False
    if SKIP.search(e):
        return "", False
    e = e.lower()
    words = re.findall(r"[a-z']+", e)
    if len(words) < 2:
        return "", False
    return " ".join(words), False


def main() -> None:
    items: dict[str, dict] = {}  # canonical -> item
    skipped = 0
    seen_lines = 0
    for title in TITLES:
        text = fetch_wikitext(title)
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            # 页1 组标题「N.以X为中心的词组」/ 页2 编号「123 xxx 释义」
            if re.match(r"^\d+\.以", line):
                continue
            en_raw, zh_raw = split_en_zh(line)
            if not zh_raw:
                continue
            seen_lines += 1
            canon, separable = normalize(en_raw)
            gloss = clean_gloss(zh_raw)
            if not canon or not gloss:
                skipped += 1
                continue
            item = {
                "text": canon,
                "gloss": gloss,
                "type": "phrasal_verb",
                "separable": separable,
            }
            items.setdefault(canon, item)

    # 手工补充高频缺失项（覆盖维基教科书没有的常用短语，如 trade in / point out）
    for text, gloss, separable in SUPPLEMENT:
        items[text] = {
            "text": text,
            "gloss": gloss,
            "type": "phrasal_verb",
            "separable": separable,
        }

    out = {
        "note": "英语多词短语（动词短语/习语）种子库：阅读标注用，可分离短语按 verb...particle 匹配。"
                "来源：中文维基教科书；暂无词频（后续并入 PHaVE/PHRASE List 标频）。",
        "items": sorted(items.values(), key=lambda x: x["text"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sep = sum(1 for i in out["items"] if i["separable"])
    print(f"条目总数: {len(out['items'])}（可分离 {sep}，连续 {len(out['items']) - sep}）")
    print(f"跳过: {skipped}（含占位符/歧义/缺释义），解析行: {seen_lines}")


if __name__ == "__main__":
    main()
