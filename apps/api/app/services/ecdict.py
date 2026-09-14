"""ECDICT 增强版 SQLite（stardict.db）只读查询：导入文章时查多词短语/术语。

只做「点查 + n-gram 扫描 + 短语/术语判别」，不 import reading（避免耦合）：
- lookup(word)：单点查（word 列唯一 NOCASE 索引）；
- scan_multiword(body)：扫描正文里的多词表达式，返回 {text, translation, tag, kind, pos_first}，
  由上层（services/admin.py）再算中文释义并分流短语/术语。

db 缺失或连接失败 → 返回空/None，优雅降级，不影响导入流程。
"""
import re
import sqlite3
from functools import lru_cache

from ..config import settings

MAX_NGRAM = 5  # 最多尝试 5 词连读（更长短语罕见，省查询）
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")
_NOISE_TAG = "[地名]"  # 纯地名（专名），阅读端已按专有名词处理，跳过

# 虚词/功能词开头（冠词、介词、连词、代词、限定词、助动词）的多词条不是术语，
# 如 "a chain"、"the last"、"in the sky"、"such as"；跳过（仅跳过该词作起点，
# 后续实义词仍可匹配，如 "the solar system" 跳过 the 后仍能匹配 "solar system"）。
_FUNCTION_FIRST = frozenset(
    """
    a an the this that these those some any each every no other another such all both
    many much few little more most several
    i me my mine we us our ours you your yours he him his she her hers it its
    they them their theirs who whom whose which what
    am is are was were be been being have has had having do does did done doing
    will would shall should can could may might must
    in on at by to for of with from about into onto over under after before between
    through during without against among around upon until till up down out off
    via per within toward towards
    and but or nor so yet if because while though although than as when where how why
    whether since unless not no
    """.split()
)


def _connect() -> sqlite3.Connection | None:
    try:
        return sqlite3.connect(settings.ecdict_path)
    except (OSError, sqlite3.Error):
        return None


@lru_cache(maxsize=8)
def has_db(path: str) -> bool:
    """数据库是否可用（文件存在且 stardict 表可查）。按路径缓存，测试 monkeypatch 不串扰。"""
    try:
        con = sqlite3.connect(path)
        con.execute("SELECT 1 FROM stardict LIMIT 1").fetchone()
        con.close()
        return True
    except (OSError, sqlite3.Error):
        return False


@lru_cache(maxsize=65536)
def _lookup_row(path: str, word: str) -> tuple | None:
    """按 (db 路径, 词形) 缓存点查结果，避免 suggest_level 对同一词反复开连接。"""
    try:
        con = sqlite3.connect(path)
    except (OSError, sqlite3.Error):
        return None
    try:
        return con.execute(
            "SELECT word, phonetic, translation, pos, tag, bnc, frq "
            "FROM stardict WHERE word = ?",
            (word,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()


def lookup(word: str) -> dict | None:
    """按词形（NOCASE）点查，返回 {word, phonetic, translation, pos, tag, bnc, frq} 或 None。"""
    row = _lookup_row(settings.ecdict_path, word)
    if row is None:
        return None
    cols = ("word", "phonetic", "translation", "pos", "tag", "bnc", "frq")
    return dict(zip(cols, row))


def scan_multiword(body: str) -> list[dict]:
    """扫描正文里的多词表达式（2..MAX_NGRAM 词），最长优先、不重叠。

    返回 [{text, translation, tag, kind, pos_first}]，已过滤：
    - 首词大写（专名短语，如 United States）；
    - 含 [地名] 的（纯地名噪声）。
    数字本就不被 _WORD_RE 匹配，天然跳过。
    """
    words = _WORD_RE.findall(body)
    n = len(words)
    if n < 2:
        return []
    con = _connect()
    if con is None:
        return []
    try:
        cur = con.cursor()

        def _look(word: str):
            return cur.execute(
                "SELECT translation, pos, tag FROM stardict WHERE word = ?", (word,)
            ).fetchone()

        results: list[dict] = []
        i = 0
        while i < n:
            # 专名短语起点跳过；虚词开头（"a chain"/"the last"/"in the sky"）也不是术语，跳过
            if words[i][0].isupper() or words[i].lower() in _FUNCTION_FIRST:
                i += 1
                continue
            best: dict | None = None
            for length in range(MAX_NGRAM, 1, -1):  # 最长优先
                if i + length > n:
                    continue
                text = " ".join(w.lower() for w in words[i : i + length])
                row = _look(text)
                if not (row and row[0]):  # 无词条或无释义
                    continue
                # 多词条无 pos，用「首词的单词条 pos」判别短语/术语
                first_row = _look(text.split()[0])
                pos_first = (first_row[1] if first_row else "") or ""
                best = {
                    "text": text,
                    "translation": row[0],
                    "tag": row[2] or "",
                    "kind": "phrase" if "v" in pos_first else "term",
                    "pos_first": pos_first,
                }
                break
            if best is None:
                i += 1
                continue
            if _NOISE_TAG in best["translation"]:
                i += 1
                continue
            results.append(best)
            i += len(best["text"].split())
        return results
    except sqlite3.Error:
        return []
    finally:
        con.close()
