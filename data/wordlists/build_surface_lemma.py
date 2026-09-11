"""生成分级阅读用的词形还原映射产物 surface_lemma.json。

把「词形/派生形式 → Nation 词族头」的映射从两份 raw 数据合并、过滤后落盘：

- raw/basewrd1..25.txt —— Paul Nation BNC/COCA 词族表（无缩进头 + 缩进成员），
  覆盖派生（beautiful→beauty、environmentalism→environment）；
- raw/lemma.en.txt —— ECDICT 词形还原表（`base/freq -> 屈折形式`，84k 组），
  覆盖屈折 + 不规则（went→go、children→child、better→good）。

只保留「词族头出现在 wordlist.csv 中」的条目（约 23611 词族），
否则运行时会把映射到一个无 rank 的头，无法判定已知/生词。

产出：data/wordlists/surface_lemma.json（{surface: 词族头}，已提交）。
运行：uv run data/wordlists/build_surface_lemma.py
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
WORDLIST = HERE / "wordlist.csv"
OUT = HERE / "surface_lemma.json"

# 常见缩写/缩略词（' 连接的短词）——lemma.en.txt 只收录了 's / n't 等片段，
# 全文缩略如 can't / it's 无法直接还原，这里显式映射到高频词族头。
CONTRACTIONS = {
    "i'm": "i", "im": "i", "you're": "you", "we're": "we", "they're": "they",
    "he's": "he", "she's": "she", "it's": "it", "that's": "that",
    "what's": "what", "who's": "who", "there's": "there", "here's": "here",
    "let's": "let", "i'll": "i", "you'll": "you", "we'll": "we",
    "they'll": "they", "he'll": "he", "she'll": "she", "it'll": "it",
    "i've": "i", "you've": "you", "we've": "we", "they've": "they",
    "i'd": "i", "you'd": "you", "we'd": "we", "they'd": "they",
    "can't": "can", "don't": "do", "doesn't": "do", "didn't": "do",
    "won't": "will", "isn't": "be", "aren't": "be", "wasn't": "be",
    "weren't": "be", "haven't": "have", "hasn't": "have", "hadn't": "have",
    "couldn't": "can", "shouldn't": "shall", "wouldn't": "will",
    "mustn't": "must", "shan't": "shall",
}


def load_heads() -> set[str]:
    """wordlist.csv 的词族头集合（小写）。"""
    heads = set()
    with open(WORDLIST, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            lemma = (row.get("lemma") or "").strip().lower()
            if lemma:
                heads.add(lemma)
    return heads


def add_family_members(mapping: dict[str, str], heads: set[str]) -> None:
    """basewrd1..25：无缩进行=词族头，缩进行=成员，映射成员→头（仅头在词表中）。"""
    for i in range(1, 26):
        path = RAW / f"basewrd{i}.txt"
        current_head: str | None = None
        with open(path, encoding="utf-8") as f:
            for line in f:
                raw_line = line.rstrip("\n")
                if not raw_line.strip():
                    continue
                word = raw_line.split()[0].lower() if raw_line.split() else ""
                if raw_line.startswith("\t"):
                    # 成员 → 当前头
                    if current_head and current_head in heads and word:
                        mapping[word] = current_head
                else:
                    current_head = word
        if current_head and current_head in heads:
            mapping[current_head] = current_head


def add_inflections(mapping: dict[str, str], heads: set[str]) -> None:
    """lemma.en.txt：`base/freq -> 屈折形式`，仅当 base 在词表中才收录。"""
    path = RAW / "lemma.en.txt"
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";") or "->" not in line:
                continue
            left, _, right = line.partition("->")
            base = left.split("/")[0].strip().lower()
            if base not in heads:
                continue
            mapping[base] = base
            for token in right.split(","):
                token = token.strip().lower()
                if token:
                    mapping[token] = base


def main() -> None:
    heads = load_heads()
    mapping: dict[str, str] = {}
    # 派生（词族成员）优先，再补屈折；缩略词最后显式覆盖
    add_family_members(mapping, heads)
    add_inflections(mapping, heads)
    for surface, head in CONTRACTIONS.items():
        if head in heads:
            mapping[surface] = head

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"heads={len(heads)}  surface_lemma entries={len(mapping)}  size={size_mb:.2f}MB")
    # 自检
    checks = {
        "jumped": "jump", "went": "go", "children": "child", "better": "good",
        "beautiful": "beauty", "environmentalism": "environment", "can't": "can",
        "dogs": "dog",
    }
    for s, want in checks.items():
        got = mapping.get(s)
        mark = "ok" if got == want else f"MISMATCH want={want}"
        print(f"  {s!r:20} -> {got!r:20} {mark}")


if __name__ == "__main__":
    main()
