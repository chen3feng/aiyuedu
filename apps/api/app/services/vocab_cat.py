"""词频题库 CAT（Computerized Adaptive Testing）。

与 ``vocab_adaptive`` 共用 4 选 1 + 「以上都不对」题型和贝叶斯 EAP 估计，
区别在选题：

- 难度使用单词的精确词频 rank（而不是 1000 词一档的档位）
- 每题从当前能力附近按 Fisher 信息量选题，不再用「档位 ±1 + 连对探顶」
- 题目参数可被 ``data/calibration/vocab_cat_items.json`` 覆盖；没有标定
  文件时以词频 rank 作为难度先验、区分度取统一的 1/2500

题库标定（2PL/MFI/SE 停止）的完整流程见 issue #40；当前版本先把
「精确 rank + 最大信息量选题」的结构跑通，等真实作答数据积累后替换参数。
"""
from __future__ import annotations

import bisect
import json
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..config import settings
from . import vocab_adaptive as _adaptive
from . import vocab_tests

MIN_QUESTIONS = 20
MAX_QUESTIONS = 80
RECENT_LIMIT = 40
CANDIDATE_WINDOW = 80      # 在当前能力 ±80 个 rank 内找题
TOP_K = 12                 # 从信息量最高的 K 题中加权随机，增加曝光多样性
DEFAULT_START = 1500.0     # 首题难度（高频词热身）
# 日志版本号：算法口径变化时递增，便于按版本回放与标定。
ALGO_VERSION = "2026-11"

RULES = (
    "每题给出 3 个中文释义，正确意思可能不在其中（此时选「以上都不对」）；"
    "认识就选正确意思，不认识请点「不认识」。系统会按词频精确选择最接近你"
    "当前水平的词，诚实作答测评更准。"
)
RESULT_MESSAGE = (
    "词频题库 CAT 按最大信息量选题，用贝叶斯 EAP 估计词汇量。最少 20 题即可"
    "查看结果，继续答到 80 题会更稳。"
)


def _pos_of(gloss: str) -> str:
    return gloss.split(" ", 1)[0] if " " in gloss else ""


def _load_overrides() -> dict:
    """读取可选的标定参数；文件不存在或格式错误时退化为词频先验。"""
    try:
        raw = json.loads(Path(settings.vocab_cat_items_path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, dict):
        return {}
    out: dict[str, tuple[float, float]] = {}
    for word, val in items.items():
        if not isinstance(word, str) or not isinstance(val, dict):
            continue
        try:
            b = float(val["b"])
            a = float(val.get("a", 1.0 / _adaptive.SCALE))
        except (KeyError, TypeError, ValueError):
            continue
        if b <= 0 or a <= 0:
            continue
        out[word] = (b, a)
    return out


@lru_cache(maxsize=1)
def _bank() -> list[dict]:
    """题库：每个词一份 {word, rank, gloss, pos, b, a}，按 rank 升序。"""
    overrides = _load_overrides()
    default_a = 1.0 / _adaptive.SCALE
    seen: set[str] = set()
    items: list[dict] = []
    for pool in _adaptive._by_level():
        for rank, lemma, gloss, _pos in pool:
            if lemma in seen:
                continue
            seen.add(lemma)
            b, a = overrides.get(lemma, (float(rank), default_a))
            items.append({
                "word": lemma,
                "rank": rank,
                "gloss": gloss,
                "pos": _pos_of(gloss),
                "b": b,
                "a": a,
            })
    items.sort(key=lambda it: it["rank"])
    return items


@lru_cache(maxsize=1)
def _ranks() -> list[int]:
    return [it["rank"] for it in _bank()]


def reload_bank() -> None:
    """管理/脚本更新标定文件后调用，清掉缓存。"""
    _bank.cache_clear()
    _ranks.cache_clear()


def _info(item: dict, theta: float) -> float:
    """3PL Fisher 信息量：a²(1-c)²p²(1-p)² / (P(1-P))。"""
    c = _adaptive.GUESS_RATE
    p = _adaptive.sigmoid(item["a"] * (theta - item["b"]))
    prob = c + (1.0 - c) * p
    if prob <= 0.0 or prob >= 1.0:
        return 0.0
    return (item["a"] * (1.0 - c) * p * (1.0 - p)) ** 2 / (prob * (1.0 - prob))


def _pick_item(sess: "CatSession") -> dict:
    theta = sess.score if sess.total else DEFAULT_START
    bank = _bank()
    ranks = _ranks()
    center = bisect.bisect_left(ranks, theta)
    lo = max(0, center - CANDIDATE_WINDOW)
    hi = min(len(bank), center + CANDIDATE_WINDOW)
    pool = [it for it in bank[lo:hi] if it["word"] not in sess.recent]
    if not pool:
        pool = [it for it in bank if it["word"] not in sess.recent] or bank

    scored = sorted(pool, key=lambda it: _info(it, theta), reverse=True)[:TOP_K]
    weights = [_info(it, theta) for it in scored]
    if sum(weights) <= 0.0:
        return sess.rng.choice(scored)
    return sess.rng.choices(scored, weights=weights)[0]


def _make_question(item: dict, rng: random.Random) -> dict:
    q = _adaptive._question_from_word(
        (item["rank"], item["word"], item["gloss"], item["pos"]), rng
    )
    # 下发给前端时 _public 会丢掉这两个字段，只用于服务端计分。
    q["b"] = item["b"]
    q["a"] = item["a"]
    return q


@dataclass
class CatSession:
    id: str
    rng: random.Random = field(default_factory=random.Random)
    score: float = 0.0
    total: int = 0
    correct: int = 0
    wrong: int = 0
    unknown: int = 0
    log_post: list = field(default_factory=_adaptive._prior_log_post)
    se: float = 0.0
    current: Optional[dict] = None
    recent: list = field(default_factory=list)
    history: list = field(default_factory=list)
    finished: bool = False
    user_id: Optional[str] = None
    recorded: bool = False
    last_ts: float = 0.0                             # 上一题作答时间（算 elapsed_ms）


_sessions: dict[str, CatSession] = {}


def get_session(sid: str) -> Optional[CatSession]:
    return _sessions.get(sid)


def _base_level(sess: CatSession) -> int:
    return max(0, min(_adaptive.MAX_LEVEL, int(round(sess.score / _adaptive.LEVEL_WIDTH))))


def _progress(sess: CatSession) -> dict:
    score = int(round(sess.score))
    return {
        "score": score if sess.total >= 1 else None,
        "total": sess.total,
        "correct": sess.correct,
        "unknown": sess.unknown,
        "wrong": sess.wrong,
        "converged": sess.total >= 50,
        "level": _base_level(sess),
        "score_interval": _adaptive._score_interval(sess),
    }


def _result(sess: CatSession) -> dict:
    score = int(round(sess.score)) if sess.total else 0
    return {
        "vocab_size": int(round(sess.score / 10) * 10) if sess.total else 0,
        "score": score,
        "total": sess.total,
        "correct": sess.correct,
        "unknown": sess.unknown,
        "wrong": sess.wrong,
        "ready": sess.total >= MIN_QUESTIONS,
        "score_interval": _progress(sess)["score_interval"],
        "message": RESULT_MESSAGE,
    }


def _log_answer(sess: CatSession, q: dict, response: str) -> None:
    """追加一条评测记录，供后续题库标定。日志失败不影响评测。"""
    try:
        path = Path(settings.vocab_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        elapsed_ms = (
            int(round((now - sess.last_ts) * 1000)) if sess.last_ts else None
        )
        sess.last_ts = now
        rec = {
            "ts": round(now, 3),
            "session": sess.id,
            "algo": "cat",
            "algo_version": ALGO_VERSION,
            "user_id": sess.user_id or "",
            "n": sess.total,
            "rank": q["rank"],
            "level": q["level"],
            "b": q["b"],
            "a": q["a"],
            "word": q["word"],
            "response": response,
            "include_correct": q["correct_index"] != 3,
            "elapsed_ms": elapsed_ms,
            "score": int(round(sess.score)),
            "se": int(round(sess.se)),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _record(sess: CatSession) -> None:
    if sess.recorded or not sess.user_id or sess.total == 0:
        return
    sess.recorded = True
    result = _result(sess)
    vocab_tests.add(sess.user_id, {
        "ts": round(time.time(), 3),
        "algo": "cat",
        "score": result["score"],
        "vocab_size": result["vocab_size"],
        "total": result["total"],
        "correct": result["correct"],
        "wrong": result["wrong"],
        "unknown": result["unknown"],
    })


def start_test(user_id: Optional[str] = None) -> tuple[str, dict, dict]:
    sid = uuid.uuid4().hex
    sess = CatSession(id=sid, user_id=user_id)
    _sessions[sid] = sess
    sess.current = _make_question(_pick_item(sess), sess.rng)
    sess.recent.append(sess.current["word"])
    return sid, _adaptive._public(sess.current), _progress(sess)


def _update_score(sess: CatSession, q: dict, outcome: str) -> None:
    """按题目自己的难度/区分度更新后验（与 adaptive 相同的 3PL 似然）。"""
    b = float(q["b"])
    a = float(q["a"])
    c = _adaptive.GUESS_RATE
    power = _adaptive.UNKNOWN_LIKELIHOOD_POWER
    lp = sess.log_post
    for i, theta in enumerate(_adaptive.GRID):
        p = _adaptive.sigmoid(a * (theta - b))
        if outcome == "correct":
            lik = c + (1.0 - c) * p
            lp[i] += math.log(max(lik, _adaptive.PROB_FLOOR))
        elif outcome == "unknown":
            lp[i] += power * math.log(max(1.0 - p, _adaptive.PROB_FLOOR))
        else:
            lp[i] += math.log(max((1.0 - c) * (1.0 - p), _adaptive.PROB_FLOOR))
    _adaptive._normalize_log_post(sess)
    sess.total += 1
    _adaptive._refresh_moments(sess)


def submit_answer(sess: CatSession, choice: Optional[int], unknown: bool) -> dict:
    q = sess.current
    if q is None:
        raise RuntimeError("测试已结束")

    if unknown:
        outcome = "unknown"
        sess.unknown += 1
    elif choice is not None and choice == q["correct_index"]:
        outcome = "correct"
        sess.correct += 1
    else:
        outcome = "wrong"
        sess.wrong += 1

    _update_score(sess, q, outcome)
    sess.history.append(int(round(sess.score)))
    _log_answer(sess, q, outcome)

    feedback = {
        "response": outcome,
        "word": q["word"],
        "correct_gloss": q["correct_gloss"],
        "word_gloss": q["gloss"],
    }
    progress = _progress(sess)

    if sess.total >= MAX_QUESTIONS:
        sess.finished = True
        _record(sess)
        return {"finished": True, "feedback": feedback, **progress, "result": _result(sess)}

    sess.current = _make_question(_pick_item(sess), sess.rng)
    sess.recent.append(sess.current["word"])
    if len(sess.recent) > RECENT_LIMIT:
        sess.recent = sess.recent[-RECENT_LIMIT:]
    return {
        "finished": False,
        "feedback": feedback,
        **progress,
        "question": _adaptive._public(sess.current),
    }


def finish_test(sess: CatSession) -> dict:
    sess.finished = True
    _record(sess)
    return _result(sess)
