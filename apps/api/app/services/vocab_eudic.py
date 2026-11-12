"""欧路式自适应词汇量测试：Elo/IRT 单点估计。

复现自 dict.eudic.net 的词汇量测试（分析见 ``docs/eudic-vocab-algorithm.md``）：

    p = sigmoid((V - (1000 * level + 100)) / 2500)
    K = 2000 / (1 + n / 14) ** 1.5

    correct : V += K * (1 - p)
    wrong   : V -= K * p
    unknown : V -= 0.625 * K * p

题目为「3 个中文释义 + 以上都不对」，另有独立的「不认识」按钮（前端已有的
第五个操作）。约 75% 的题会把正确释义放进前三个选项，25% 的题三个释义全错、
正确答案是「以上都不对」。连续答对 4 题后进入「探顶」，跳到更高词频档位。

与 ``vocab.py``（固定分层抽样）保持相同的对外接口，供路由按开关切换。
"""
from __future__ import annotations

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
from . import vocab as _classic
from . import vocab_tests

# —— 拟合得到的算法常数（见 docs/eudic-vocab-algorithm.md §4）——
LEVEL_WIDTH = 1000          # 每个词频档约 1000 词
LEVEL_OFFSET = 100          # 档位难度偏移
SCALE = 2500                # logistic 斜率（分）
K0 = 2000                   # 初始步长（分）
TAU = 14                    # 步长衰减时间常数
GAIN_EXP = 1.5              # 步长衰减指数
UNKNOWN_FACTOR = 0.625      # 「不认识」相对「答错」的负向权重
MIN_DELTA = 0.01            # 置信区间相对宽度下限
MAX_LEVEL = 24              # wordlist.csv 覆盖 0~24 档
MAX_SCORE = 25000           # 词库上限
CORRECT_PRESENT_RATE = 0.75 # 正确释义出现在 3 个选项中的概率
MIN_QUESTIONS = 20          # 线上「最少测满 20 题才能查看结果」
MAX_QUESTIONS = 50          # 与现有 App 的题量上限保持一致

NONE_OF_ABOVE = "以上都不对"

RULES = (
    "每题给出 3 个中文释义，正确意思可能不在其中（此时选「以上都不对」）；"
    "认识就选正确意思，不认识请点「不认识」。诚实作答，测评更准。"
)
RESULT_MESSAGE = (
    "词汇量按自适应 Elo/IRT 估计：每答一题，根据当前分数与题目难度更新估计，"
    "连续答对会挑战更高词频档位。最少 20 题即可查看结果，继续答会更稳。"
)


def sigmoid(x: float) -> float:
    x = max(-50.0, min(50.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def _level_of(rank: int) -> int:
    """词频 rank → 档位（每档 1000 词，0 起）。"""
    return min(MAX_LEVEL, max(0, (rank - 1) // LEVEL_WIDTH))


@lru_cache(maxsize=1)
def _by_level() -> list:
    """[(rank, lemma, gloss, pos)] 按档位分组，复用现有词表与黑名单过滤。"""
    levels: list[list] = [[] for _ in range(MAX_LEVEL + 1)]
    for rank, lemma, g in _classic._candidates():
        pos = g.split(" ", 1)[0] if " " in g else ""
        levels[_level_of(rank)].append((rank, lemma, g, pos))
    return levels


@lru_cache(maxsize=1)
def _all_words() -> list:
    return [w for pool in _by_level() for w in pool]


def _pick_word(level: int, rng: random.Random, avoid: set) -> tuple:
    pool = _by_level()[max(0, min(MAX_LEVEL, level))] or _all_words()
    for _ in range(40):
        w = rng.choice(pool)
        if w[1] not in avoid:
            return w
    return rng.choice(pool)


def _distractors(target: tuple, n: int, rng: random.Random) -> list:
    """取 n 个干扰释义：优先同档、同词性，避免与正确释义互相包含。"""
    level = _level_of(target[0])
    pools = [_by_level()[level]]
    for d in (1, -1, 2, -2):
        lv = level + d
        if 0 <= lv <= MAX_LEVEL:
            pools.append(_by_level()[lv])
    pools.append(_all_words())

    chosen: list[str] = []
    seen = {target[2]}
    for pool in pools:
        same_pos = [w for w in pool if w[3] == target[3] and w[2] not in seen]
        mixed = [w for w in pool if w[2] not in seen]
        for candidates in (same_pos, mixed):
            rng.shuffle(candidates)
            for w in candidates:
                if len(chosen) >= n:
                    break
                g = w[2]
                if not g or g in seen:
                    continue
                if g in target[2] or target[2] in g:
                    continue
                seen.add(g)
                chosen.append(g)
        if len(chosen) >= n:
            break
    while len(chosen) < n:
        g = rng.choice(_all_words())[2]
        if g not in seen:
            seen.add(g)
            chosen.append(g)
    return chosen[:n]


def _make_question(level: int, rng: random.Random, avoid: set) -> dict:
    """生成一道与线上同构的题：3 个释义 + 以上都不对（「不认识」由前端按钮承担）。"""
    word = _pick_word(level, rng, avoid)
    include_correct = rng.random() < CORRECT_PRESENT_RATE
    glosses = _distractors(word, 2 if include_correct else 3, rng)
    if include_correct:
        glosses.append(word[2])
    rng.shuffle(glosses)
    options = glosses + [NONE_OF_ABOVE]
    return {
        "word": word[1],
        "rank": word[0],
        "level": _level_of(word[0]),
        "options": options,
        "correct_index": glosses.index(word[2]) if include_correct else 3,
        "correct_gloss": word[2] if include_correct else NONE_OF_ABOVE,
        "gloss": word[2],  # 词的真实含义（「以上都不对」时用于答后反馈）
    }


@dataclass
class EudicSession:
    id: str
    rng: random.Random = field(default_factory=random.Random)
    score: float = 0.0
    total: int = 0
    correct: int = 0
    wrong: int = 0
    unknown: int = 0
    n_eff: float = 0.0
    last_delta: float = 1.0
    streak: int = 0
    probe_remaining: int = 0
    probe_level: int = 0
    probes_used: int = 0
    last_probe_failed: bool = False
    last_probe_end_n: int = 0
    current: Optional[dict] = None
    recent: list = field(default_factory=list)
    history: list = field(default_factory=list)
    finished: bool = False
    user_id: Optional[str] = None                    # 归属用户；结束时落一条历史
    recorded: bool = False                           # 历史只记一次


_sessions: dict[str, EudicSession] = {}


def get_session(sid: str) -> Optional[EudicSession]:
    return _sessions.get(sid)


def _public(q: dict) -> dict:
    """下发给前端的题目（不含正确答案）。"""
    return {"word": q["word"], "options": q["options"], "level": q["level"]}


def _base_level(sess: EudicSession) -> int:
    return max(0, min(MAX_LEVEL, int(round(sess.score / LEVEL_WIDTH))))


def _select_level(sess: EudicSession) -> int:
    if sess.total == 0:
        # 线上第一题固定在 3~4 档
        return 3 + sess.rng.choice([0, 1])
    if sess.probe_remaining > 0:
        return sess.probe_level
    can_probe = sess.probes_used == 0 or (
        sess.probes_used == 1
        and sess.last_probe_failed
        and sess.total - sess.last_probe_end_n <= 6
    )
    if sess.streak >= 4 and can_probe and sess.probes_used < 2:
        # 连续答对 4 题后探顶：跳到当前档位上方 3~4 档，最多 6 题。
        sess.probe_remaining = 6
        sess.probe_level = min(
            MAX_LEVEL, _base_level(sess) + 3 + sess.rng.choice([0, 1])
        )
        return sess.probe_level
    offset = sess.rng.choices([-1, 0, 1], weights=[0.25, 0.60, 0.15])[0]
    return max(0, min(MAX_LEVEL, _base_level(sess) + offset))


def _make_next(sess: EudicSession) -> dict:
    q = _make_question(_select_level(sess), sess.rng, set(sess.recent[-20:]))
    sess.recent.append(q["word"])
    if len(sess.recent) > 40:
        sess.recent = sess.recent[-40:]
    return q


def _update_score(sess: EudicSession, q: dict, outcome: str) -> None:
    n = sess.total + 1
    difficulty = LEVEL_WIDTH * q["level"] + LEVEL_OFFSET
    p = sigmoid((sess.score - difficulty) / SCALE)
    gain = K0 / (1.0 + n / TAU) ** GAIN_EXP
    if outcome == "correct":
        sess.score += gain * (1.0 - p)
    elif outcome == "unknown":
        sess.score -= UNKNOWN_FACTOR * gain * p
    else:
        sess.score -= gain * p
    sess.score = max(0.0, min(float(MAX_SCORE), sess.score))
    sess.total = n


def _update_uncertainty(sess: EudicSession, outcome: str) -> None:
    if outcome == "correct":
        sess.n_eff = 1.0 if sess.n_eff == 0.0 else sess.n_eff + 0.5
    else:
        sess.n_eff = max(1.0, sess.n_eff * 0.5)
    sess.last_delta = min(1.0, max(MIN_DELTA, 0.8 / (2.0 * sess.n_eff)))


def _progress(sess: EudicSession) -> dict:
    score = int(round(sess.score))
    lower = max(0, int(round(sess.score * (1.0 - sess.last_delta))))
    return {
        "score": score if sess.total >= 1 else None,
        "total": sess.total,
        "correct": sess.correct,
        "unknown": sess.unknown,
        "wrong": sess.wrong,
        "converged": sess.total >= MIN_QUESTIONS,
        "level": _base_level(sess),
        "score_interval": [lower, score],
    }


def _log_answer(sess: EudicSession, q: dict, response: str) -> None:
    """追加一条评测记录（JSONL），供离线分析。日志失败不影响评测。"""
    try:
        path = Path(settings.vocab_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": round(time.time(), 3),
            "session": sess.id,
            "algo": "eudic",
            "n": sess.total,
            "rank": q["rank"],
            "level": q["level"],
            "word": q["word"],
            "response": response,
            "score": int(round(sess.score)),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _result(sess: EudicSession) -> dict:
    score = int(round(sess.score))
    return {
        "vocab_size": int(round(sess.score / 10) * 10),
        "score": score,
        "total": sess.total,
        "correct": sess.correct,
        "unknown": sess.unknown,
        "wrong": sess.wrong,
        "ready": sess.total >= MIN_QUESTIONS,
        "score_interval": _progress(sess)["score_interval"],
        "message": RESULT_MESSAGE,
    }


def start_test(user_id: Optional[str] = None) -> tuple[str, dict, dict]:
    sid = uuid.uuid4().hex
    sess = EudicSession(id=sid, user_id=user_id)
    _sessions[sid] = sess
    sess.current = _make_next(sess)
    return sid, _public(sess.current), _progress(sess)


def submit_answer(sess: EudicSession, choice: Optional[int], unknown: bool) -> dict:
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

    # 探顶阶段：答对继续抬升，答错/不认识立即退出
    probe_ended = False
    probe_failed = False
    if sess.probe_remaining > 0:
        if outcome == "correct":
            sess.probe_level = min(
                MAX_LEVEL, sess.probe_level + sess.rng.choice([1, 1, 2])
            )
            sess.probe_remaining -= 1
            if sess.probe_remaining == 0:
                probe_ended = True
        else:
            sess.probe_remaining = 0
            probe_ended = True
            probe_failed = True

    sess.streak = sess.streak + 1 if outcome == "correct" else 0
    _update_score(sess, q, outcome)
    if probe_ended:
        sess.probes_used += 1
        sess.last_probe_failed = probe_failed
        sess.last_probe_end_n = sess.total
    _update_uncertainty(sess, outcome)
    sess.history.append(int(round(sess.score)))
    _log_answer(sess, q, outcome)

    feedback = {
        "response": outcome,
        "word": q["word"],
        # correct_gloss 用于前端高亮正确选项；word_gloss 是该词的真实含义。
        # 当正确选项是「以上都不对」时，前端用 word_gloss 展示真实释义。
        "correct_gloss": q["correct_gloss"],
        "word_gloss": q["gloss"],
    }
    progress = _progress(sess)

    if sess.total >= MAX_QUESTIONS:
        sess.finished = True
        _record(sess)
        return {"finished": True, "feedback": feedback, **progress, "result": _result(sess)}

    sess.current = _make_next(sess)
    return {
        "finished": False,
        "feedback": feedback,
        **progress,
        "question": _public(sess.current),
    }


def _record(sess: EudicSession) -> None:
    """把完成的测评写进用户历史（幂等；匿名/未作答不记）。"""
    if sess.recorded or not sess.user_id or sess.total == 0:
        return
    sess.recorded = True
    result = _result(sess)
    vocab_tests.add(sess.user_id, {
        "ts": round(time.time(), 3),
        "algo": "eudic",
        "score": result["score"],
        "vocab_size": result["vocab_size"],
        "total": result["total"],
        "correct": result["correct"],
        "wrong": result["wrong"],
        "unknown": result["unknown"],
    })


def finish_test(sess: EudicSession) -> dict:
    """用户主动结束测评，返回最终成绩（幂等，可重复调用）。"""
    sess.finished = True
    _record(sess)
    return _result(sess)
