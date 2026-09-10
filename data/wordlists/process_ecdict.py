# /// script
# requires-python = ">=3.9"
# ///
"""把 ECDICT 全量 CSV + Paul Nation BNC/COCA 25000 词族表 生成项目词表（词族标度）。

输出字段：lemma, phonetic, pos, translation, collins, oxford, tag, bnc, frq, rank, freq_band

关键：rank = Nation BNC/COCA 词族排名（1 = 最常见词族，1~25000）。词汇量评测与阅读分级都以
rank 为准，与 qsbdc / 欧路等主流「词族」口径完全一致。

为什么用 Nation 25000 词族而不是 lemma.en.txt：
- lemma.en.txt 是「词形还原表」，把 able / ability / unable / inability 拆成 4 个独立词族
  （共 62072 族）；Nation 把它们归为 ABLE 一族。透明派生词（environmentalism）与透明复合词
  （wildfire、bloodline）在 lemma.en.txt 里都被当成独立词族，导致高分用户被系统性高估
  （实测 23280 vs 真实 12000）。
- Nation 的 25×1000=25000 基础词族（basewrd1~25.txt）+ 4 个附加表（basewrd31 专有名词 /
  basewrd32 边缘词 / basewrd33 透明复合词 / basewrd34 缩写），是 qsbdc、欧路等标准口径。
  本项目只用前 25000 基础词族作 rank；附加表不参与排名。

词族聚合：Nation basewrd1~25 每个文件 1000 词族，headword 无缩进、成员词 tab 缩进；
把每个 ECDICT 词形（小写 + 去音符）还原到 Nation 词族头，rank = 词族头在 25000 中的序号。
每个词族选一个「代表词形」（词族头本身；若 ECDICT 无则取 frq 最小者）作为展示与释义载体。

数据来源：https://www.wgtn.ac.nz/lals/resources/paul-nations-resources/vocabulary-analysis-programs/range/BNC_COCA_25000.zip
（Paul Nation, CC BY-SA 4.0）
"""
import csv
import re
import sys
import unicodedata
from collections import Counter, defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SRC = "data/wordlists/raw/ecdict.csv"
OUT = "data/wordlists/wordlist.csv"
NATION = "data/wordlists/raw/basewrd{}.txt"  # 1..25，每个 1000 词族

FIELDS = ["lemma", "phonetic", "pos", "translation",
          "collins", "oxford", "tag", "bnc", "frq", "rank", "freq_band"]

# 代表词形过滤：小写实词（排除全大写缩写与首字母大写的专有名词）
WORD_OK = re.compile(r"^[a-z][a-z'\-]+$")

# 明确无词汇价值的释义标记：人名姓氏 / 纯地名 / 缩写 / 屈折变形（词族头是别的词的变形）
_JUNK = ("姓氏", "（地名", "（人名", "人名）", "旧称", "= ",
         "abbr.", "复数", "过去分词", "现在分词", "男子名", "女子名", "女性名")


def norm(w: str) -> str:
    """小写 + 去音符（NFD 拆解后去掉组合符），把 CAFÉ→cafe、FÜHRER→fuhrer。"""
    w = w.strip().lower()
    w = unicodedata.normalize("NFD", w)
    return "".join(c for c in w if not unicodedata.combining(c))


def clean(s: str) -> str:
    if not s:
        return ""
    # ECDICT 字段内用字面 \n / \r 表示换行，替换为分号
    return (s.replace("\\r\\n", "；").replace("\\n", "；")
             .replace("\\r", "；").strip())


def band(rank: int) -> str:
    if rank <= 0:
        return ""
    if rank <= 1000:
        return "1k"
    if rank <= 2000:
        return "2k"
    if rank <= 3000:
        return "3k"
    if rank <= 5000:
        return "5k"
    if rank <= 10000:
        return "10k"
    if rank <= 15000:
        return "15k"
    if rank <= 20000:
        return "20k"
    return "25k"


def to_int(s: str) -> int:
    try:
        return int((s or "").strip())
    except ValueError:
        return 0


# —— 1. 解析 Nation basewrd1~25：词族头 -> rank，成员词 -> 词族头 ——
head_rank: dict[str, int] = {}
member_head: dict[str, str] = {}
rank = 0
for i in range(1, 26):
    cur_head = None
    with open(NATION.format(i), encoding="utf-8-sig") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line.strip():
                continue
            w = norm(line.lstrip("\t").split()[0])
            if not w:
                continue
            if line.startswith("\t"):
                member_head.setdefault(w, cur_head)  # 首个（rank 最小）词族优先
            else:
                cur_head = w
                rank += 1
                head_rank[w] = rank

# —— 2. 读 ECDICT，把词形归入 Nation 词族 ——
# 词族 -> [(frq, bnc, word, 原始行)]
family: dict[str, list] = defaultdict(list)
with open(SRC, encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        word = (row.get("word") or "").strip()
        if not word:
            continue
        nw = norm(word)
        if nw in head_rank:
            head = nw
        else:
            head = member_head.get(nw)
        if head is None:
            continue  # 不在 Nation 25000 基础词族内
        frq = to_int(row.get("frq"))
        bnc = to_int(row.get("bnc"))
        family[head].append((frq, bnc, word, row))

# —— 3. 每个词族选代表词形，输出一行 ——
rows_out = []
band_counter: Counter = Counter()
skipped_junk = 0

for head in sorted(head_rank, key=head_rank.get):
    members = family.get(head)
    if not members:
        continue
    # 代表词形：优先词族头（最标准原型）；否则 frq>0 中 frq 最小（最常用）；否则 bnc 最小
    h = next((m for m in members if norm(m[2]) == head), None)
    with_frq = [m for m in members if m[0] > 0]
    with_bnc = [m for m in members if m[1] > 0]
    if h is not None:
        pick = h
    elif with_frq:
        pick = min(with_frq, key=lambda m: m[0])
    elif with_bnc:
        pick = min(with_bnc, key=lambda m: m[1])
    else:
        pick = members[0]
    frq, bnc, word, row = pick

    if not WORD_OK.match(word):
        continue
    translation = clean(row.get("translation"))
    if not translation:
        continue
    if any(j in translation for j in _JUNK):
        skipped_junk += 1
        continue

    b = band(head_rank[head])
    band_counter[b] += 1
    rows_out.append({
        "lemma": word,
        "phonetic": clean(row.get("phonetic")),
        "pos": clean(row.get("pos")),
        "translation": translation,
        "collins": (row.get("collins") or "").strip(),
        "oxford": (row.get("oxford") or "").strip(),
        "tag": (row.get("tag") or "").strip(),
        "bnc": str(bnc) if bnc else "",
        "frq": str(frq) if frq else "",
        "rank": str(head_rank[head]),
        "freq_band": b,
    })

rows_out.sort(key=lambda r: int(r["rank"]))

with open(OUT, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows_out)

print(f"kept: {len(rows_out)} words -> {OUT}  (skipped junk: {skipped_junk})")
print("band distribution (by Nation 词族 rank):")
for b in ["1k", "2k", "3k", "5k", "10k", "15k", "20k", "25k"]:
    print(f"  {b:>5}: {band_counter[b]:>6}")
