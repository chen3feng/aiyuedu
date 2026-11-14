"""扫描低频「纯音译」释义，辅助维护 transliteration_blacklist.json。

释义与英文发音高度对应的词（人名/地名/乐器名/药名/单位等）在四选一里可以
按音直接猜中，属于送分题。本脚本用中文拼音声母与英文音标做粗略对齐，列出
候选供人工复核；确认后把 lemma 加入
``data/wordlists/transliteration_blacklist.json``。

pypinyin 不是运行时依赖，需要临时安装：

    uv run --with pypinyin --directory apps/api python scripts/scan_transliterations.py

注意：自动匹配有误报（例如 insomnia/失眠、offal/废料），一定要人工复核后再
入黑名单，不要直接把脚本输出当结果。
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

# 让 `python scripts/scan_transliterations.py` 能导入 app 包。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import vocab  # noqa: E402

# 粗略的 IPA → 拉丁字母映射，只用于声母/整体相似度比较。
_IPA_MAP = {
    "æ": "a", "ɑ": "a", "ʌ": "a", "ɒ": "o", "ɔ": "o", "ə": "e", "ɜ": "e",
    "ɛ": "e", "ɪ": "i", "ʊ": "u", "ʃ": "sh", "ʒ": "zh", "tʃ": "ch",
    "dʒ": "j", "θ": "th", "ð": "d", "ŋ": "ng", "ɡ": "g", "j": "y",
    "ː": "", "ˈ": "", "ˌ": "", ".": "", "'": "",
}
_CONS = re.compile(r"[aeiouy]")
_POS_HEAD = re.compile(r"^(?:\s*[a-z]+\s*\.\s*(?:[&/]\s*)?)+", re.I)
_SENSE = re.compile(r"[,，]")


def _norm_ipa(text: str) -> str:
    return "".join(_IPA_MAP.get(ch, ch if "a" <= ch <= "z" else "") for ch in text.lower())


def _consonants(text: str) -> str:
    return _CONS.sub("", text)


def _pinyin(text: str) -> str:
    from pypinyin import lazy_pinyin

    return "".join(lazy_pinyin(text))


def score(word: str, phonetic: str, sense: str) -> float:
    """音近分数 0–1：拼音声母序列与英文音标声母序列的相似度。"""
    han = "".join(re.findall(r"[一-鿿]+", sense))
    if len(han) < 2:
        return 0.0
    py = _pinyin(han)
    en = _norm_ipa(phonetic) if phonetic else word.lower()
    a, b = _consonants(py), _consonants(en)
    if len(a) < 2 or len(b) < 2:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    length = min(len(a), len(b)) / max(len(a), len(b))
    return ratio * 0.7 + length * 0.3


def _senses(gloss: str) -> list[str]:
    body = _POS_HEAD.sub("", gloss)
    return [s.strip() for s in _SENSE.split(body) if s.strip()]


def _blacklisted() -> set[str]:
    try:
        path = Path(vocab.settings.transliteration_blacklist_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("lemmas", []))
    except (OSError, json.JSONDecodeError):
        return set()


def scan(min_rank: int, threshold: float, include_blacklisted: bool) -> list[dict]:
    rows = {r["lemma"]: r for r in vocab._load_rows()}
    blacklisted = set() if include_blacklisted else _blacklisted()
    out: list[dict] = []
    for rank, lemma, gloss in vocab._candidates():
        if rank < min_rank or lemma in blacklisted:
            continue
        phonetic = rows.get(lemma, {}).get("phonetic", "")
        best = max((score(lemma, phonetic, s) for s in _senses(gloss)), default=0.0)
        if best >= threshold:
            out.append({
                "score": round(best, 2),
                "rank": rank,
                "lemma": lemma,
                "phonetic": phonetic,
                "gloss": gloss,
            })
    out.sort(key=lambda it: it["rank"])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-rank", type=int, default=8000,
                        help="只看该 rank 之后的低频词（默认 8000）")
    parser.add_argument("--threshold", type=float, default=0.75,
                        help="音近分数阈值（默认 0.75）")
    parser.add_argument("--include-blacklisted", action="store_true",
                        help="也列出已在黑名单里的词")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    items = scan(args.min_rank, args.threshold, args.include_blacklisted)
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    print(f"# {len(items)} 个候选（rank >= {args.min_rank}, score >= {args.threshold}）")
    for it in items:
        print(
            f"{it['score']:.2f}\t{it['rank']}\t{it['lemma']}\t"
            f"{it['phonetic']}\t{it['gloss']}"
        )


if __name__ == "__main__":
    main()
