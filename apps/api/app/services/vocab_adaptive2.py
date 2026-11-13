"""双参数自适应词汇量测试：水平 θ + 斜率 α（issue #41）。

单参数模型（``vocab_adaptive``）假设所有人的「认识概率—词频」曲线斜率相同，
只估计一个能力点 θ。现实中有人断崖式（α 大），有人平缓地部分认识很多词
（α 小）。本实现把能力扩展为两个参数：

    p(know) = sigmoid(α * (θ - b) / 2500)

- θ：50% 认识阈值（分数尺度，0–25,000）
- α：个人区分度（相对基准斜率 1/2500 的倍数，1.0 = 与单参数模型相同）

后验在 (θ, α) 的二维网格上用贝叶斯 EAP 估计；词汇量取曲线下面积：

    词汇量 = Σ_level 1000 × sigmoid(α * (θ - b_level) / 2500)

这比「单点阈值」更贴近「认识一部分词」的现实：α 小的人面积明显大于 θ，
α 大的人则相反。题型、猜测校正与选题启发式沿用 ``vocab_adaptive``。
"""
from __future__ import annotations

import json
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import settings
from . import vocab_adaptive as _adaptive
from . import vocab_tests
from . import vocab_trend

ALGO_VERSION = "2026-11"
NONE_OF_ABOVE = _adaptive.NONE_OF_ABOVE
GUESS_RATE = _adaptive.GUESS_RATE
UNKNOWN_LIKELIHOOD_POWER = _adaptive.UNKNOWN_LIKELIHOOD_POWER
LEVEL_WIDTH = _adaptive.LEVEL_WIDTH
LEVEL_OFFSET = _adaptive.LEVEL_OFFSET
MAX_LEVEL = _adaptive.MAX_LEVEL
MAX_SCORE = _adaptive.MAX_SCORE
SCALE = _adaptive.SCALE
MIN_QUESTIONS = _adaptive.MIN_QUESTIONS
MAX_QUESTIONS = _adaptive.MAX_QUESTIONS
PROBE_QUESTIONS = _adaptive.PROBE_QUESTIONS
MAX_PROBES = _adaptive.MAX_PROBES
PROBE_COOLDOWN = _adaptive.PROBE_COOLDOWN
CORRECT_PRESENT_RATE = _adaptive.CORRECT_PRESENT_RATE

# θ 网格沿用单参数模型（0–25,000，步长 50）
THETA_GRID = _adaptive.GRID
# α 网格：相对基准斜率的倍数。7 档足以区分「平缓 / 正常 / 断崖」。
ALPHA_GRID = (0.5, 0.65, 0.8, 1.0, 1.25, 1.6, 2.0)
ALPHA_PRIOR_LOG_SD = 0.35       # log α 先验标准差：弱信息，数据可主导
PROB_FLOOR = 1e-12

RULES = (
    "每题给出 3 个中文释义，正确意思可能不在其中（此时选「以上都不对」）；"
    "认识就选正确意思，不认识请点「不认识」。诚实作答，测评更准。"
)
RESULT_MESSAGE = (
    "词汇量按双参数 IRT（θ + α）估计：不仅估计你的水平，还估计你的"
    "「认识概率—词频」曲线斜率，再对整条曲线积分得到词汇量。"
    "最少 20 题即可查看结果，继续答会更稳。"
)


def _prior_log_post(
    theta_mean: Optional[float] = None, theta_sd: Optional[float] = None
) -> list[float]:
    """(θ, α) 二维先验：θ ~ N(mean, sd²)，log α ~ N(0, 0.35²)。

    传入 mean/sd 时用历史测试作弱先验（issue #42）。
    """
    mean = _adaptive.PRIOR_MEAN if theta_mean is None else theta_mean
    sd = _adaptive.PRIOR_SD if theta_sd is None else max(300.0, theta_sd)
    out: list[float] = []
    for theta in THETA_GRID:
        t_prior = -0.5 * ((theta - mean) / sd) ** 2
        for alpha in ALPHA_GRID:
            a_prior = -0.5 * (math.log(alpha) / ALPHA_PRIOR_LOG_SD) ** 2
            out.append(t_prior + a_prior)
    return out


N_ALPHA = len(ALPHA_GRID)


@dataclass
class Adaptive2Session:
    id: str
    rng: random.Random = field(default_factory=random.Random)
    score: float = 0.0          # θ 后验均值
    alpha: float = 1.0          # α 后验均值（相对基准斜率）
    se: float = 0.0             # θ 后验标准差
    alpha_se: float = 0.0
    total: int = 0
    correct: int = 0
    wrong: int = 0
    unknown: int = 0
    log_post: list = field(default_factory=_prior_log_post)
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
    user_id: Optional[str] = None
    recorded: bool = False
    last_ts: float = 0.0


_sessions: dict[str, Adaptive2Session] = {}


def get_session(sid: str) -> Optional[Adaptive2Session]:
    return _sessions.get(sid)


def _public(q: dict) -> dict:
    return _adaptive._public(q)


def _normalize_log_post(sess: Adaptive2Session) -> None:
    peak = max(sess.log_post)
    weights = [math.exp(v - peak) for v in sess.log_post]
    log_z = math.log(sum(weights))
    sess.log_post = [v - peak - log_z for v in sess.log_post]


def _refresh_moments(sess: Adaptive2Session) -> None:
    weights = [math.exp(v) for v in sess.log_post]
    n_theta = len(THETA_GRID)
    total = sum(weights)
    theta_mean = alpha_mean = 0.0
    for i, theta in enumerate(THETA_GRID):
        row = weights[i * N_ALPHA:(i + 1) * N_ALPHA]
        row_sum = sum(row)
        theta_mean += theta * row_sum
        for j, alpha in enumerate(ALPHA_GRID):
            alpha_mean += alpha * row[j]
    theta_mean /= total
    alpha_mean /= total
    var = 0.0
    alpha_var = 0.0
    for i, theta in enumerate(THETA_GRID):
        row = weights[i * N_ALPHA:(i + 1) * N_ALPHA]
        var += sum(row) * (theta - theta_mean) ** 2
        for j, alpha in enumerate(ALPHA_GRID):
            alpha_var += row[j] * (alpha - alpha_mean) ** 2
    sess.score = max(0.0, min(float(MAX_SCORE), theta_mean))
    sess.alpha = alpha_mean
    sess.se = math.sqrt(max(var / total, 0.0))
    sess.alpha_se = math.sqrt(max(alpha_var / total, 0.0))


def _update_score(sess: Adaptive2Session, q: dict, outcome: str) -> None:
    """把一次作答乘进 (θ, α) 二维后验。"""
    difficulty = LEVEL_WIDTH * q["level"] + LEVEL_OFFSET
    power = UNKNOWN_LIKELIHOOD_POWER if outcome == "unknown" else 1.0
    lp = sess.log_post
    for i, theta in enumerate(THETA_GRID):
        base = i * N_ALPHA
        for j, alpha in enumerate(ALPHA_GRID):
            p = _adaptive.sigmoid(alpha * (theta - difficulty) / SCALE)
            if outcome == "correct":
                lik = GUESS_RATE + (1.0 - GUESS_RATE) * p
                lp[base + j] += math.log(max(lik, PROB_FLOOR))
            elif outcome == "unknown":
                lp[base + j] += power * math.log(max(1.0 - p, PROB_FLOOR))
            else:
                lp[base + j] += math.log(
                    max((1.0 - GUESS_RATE) * (1.0 - p), PROB_FLOOR)
                )
    _normalize_log_post(sess)
    sess.total += 1
    _refresh_moments(sess)


def _know_prob(theta: float, alpha: float, difficulty: float) -> float:
    return _adaptive.sigmoid(alpha * (theta - difficulty) / SCALE)


def _vocab_area(theta: float, alpha: float) -> float:
    """曲线下面积：Σ 每档 1000 词 × 该档认识概率。"""
    total = 0.0
    for level in range(MAX_LEVEL + 1):
        total += LEVEL_WIDTH * _know_prob(
            theta, alpha, LEVEL_WIDTH * level + LEVEL_OFFSET
        )
    return total


def _vocab_interval(sess: Adaptive2Session) -> list:
    """词汇量（面积）的 95% 区间：对后验按面积加权取分位数。"""
    weights = [math.exp(v) for v in sess.log_post]
    pairs = []
    for i, theta in enumerate(THETA_GRID):
        base = i * N_ALPHA
        for j, alpha in enumerate(ALPHA_GRID):
            pairs.append((_vocab_area(theta, alpha), weights[base + j]))
    pairs.sort(key=lambda x: x[0])
    total = sum(w for _, w in pairs)
    target_lo, target_hi = total * 0.025, total * 0.975
    cum = 0.0
    lo = hi = pairs[0][0]
    for area, w in pairs:
        cum += w
        if cum <= target_lo:
            lo = area
        if cum <= target_hi:
            hi = area
    return [max(0, int(round(lo))), min(MAX_SCORE, int(round(hi)))]


def _base_level(sess: Adaptive2Session) -> int:
    return max(0, min(MAX_LEVEL, int(round(sess.score / LEVEL_WIDTH))))


def _select_level(sess: Adaptive2Session) -> int:
    """选题：沿用 adaptive 的档位偏移 + 连对探顶启发式。"""
    if sess.total == 0:
        return 1 + sess.rng.choice([0, 1])
    if sess.probe_remaining > 0:
        return sess.probe_level
    can_probe = (
        sess.probes_used < MAX_PROBES
        and (sess.probes_used == 0 or sess.total - sess.last_probe_end_n >= PROBE_COOLDOWN)
    )
    if sess.streak >= 4 and can_probe:
        sess.probe_remaining = PROBE_QUESTIONS
        sess.probe_level = min(
            MAX_LEVEL, _base_level(sess) + 3 + sess.rng.choice([0, 1])
        )
        return sess.probe_level
    offset = sess.rng.choices([-1, 0, 1], weights=[0.25, 0.60, 0.15])[0]
    return max(0, min(MAX_LEVEL, _base_level(sess) + offset))


def _make_next(sess: Adaptive2Session) -> dict:
    q = _adaptive._make_question(_select_level(sess), sess.rng, set(sess.recent[-20:]))
    sess.recent.append(q["word"])
    if len(sess.recent) > 40:
        sess.recent = sess.recent[-40:]
    return q


def _score_interval(sess: Adaptive2Session) -> list:
    half = 1.96 * math.sqrt(sess.se ** 2 + _adaptive.FORM_SD ** 2)
    return [
        max(0, int(round(sess.score - half))),
        min(MAX_SCORE, int(round(sess.score + half))),
    ]


def _progress(sess: Adaptive2Session) -> dict:
    score = int(round(sess.score))
    return {
        "score": score if sess.total >= 1 else None,
        "vocab_size": int(round(_vocab_area(sess.score, sess.alpha))) if sess.total else None,
        "alpha": round(sess.alpha, 2),
        "total": sess.total,
        "correct": sess.correct,
        "unknown": sess.unknown,
        "wrong": sess.wrong,
        "converged": sess.total >= 50,
        "level": _base_level(sess),
        "score_interval": _score_interval(sess),
        "se": int(round(sess.se)),
    }


def _result(sess: Adaptive2Session) -> dict:
    score = int(round(sess.score)) if sess.total else 0
    area = _vocab_area(sess.score, sess.alpha) if sess.total else 0.0
    return {
        "vocab_size": int(round(area / 10) * 10),
        "score": score,
        "alpha": round(sess.alpha, 2),
        "total": sess.total,
        "correct": sess.correct,
        "unknown": sess.unknown,
        "wrong": sess.wrong,
        "ready": sess.total >= MIN_QUESTIONS,
        "score_interval": _score_interval(sess),
        "vocab_interval": _vocab_interval(sess) if sess.total else [0, 0],
        "se": int(round(sess.se)),
        "message": RESULT_MESSAGE,
    }


def _log_answer(sess: Adaptive2Session, q: dict, response: str) -> None:
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
            "algo": "adaptive2",
            "algo_version": ALGO_VERSION,
            "user_id": sess.user_id or "",
            "n": sess.total,
            "rank": q["rank"],
            "level": q["level"],
            "word": q["word"],
            "response": response,
            "include_correct": q["correct_index"] != 3,
            "elapsed_ms": elapsed_ms,
            "score": int(round(sess.score)),
            "alpha": round(sess.alpha, 3),
            "se": int(round(sess.se)),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _record(sess: Adaptive2Session) -> None:
    if sess.recorded or not sess.user_id or sess.total == 0:
        return
    sess.recorded = True
    result = _result(sess)
    vocab_tests.add(sess.user_id, {
        "ts": round(time.time(), 3),
        "algo": "adaptive2",
        "algo_version": ALGO_VERSION,
        "score": result["score"],
        "vocab_size": result["vocab_size"],
        "alpha": result["alpha"],
        "total": result["total"],
        "correct": result["correct"],
        "wrong": result["wrong"],
        "unknown": result["unknown"],
        "se": result["se"],
        "score_interval": result["score_interval"],
        "vocab_interval": result["vocab_interval"],
    })


def start_test(user_id: Optional[str] = None) -> tuple[str, dict, dict]:
    sid = uuid.uuid4().hex
    prior = (
        vocab_trend.history_prior(user_id, "adaptive2")
        if settings.vocab_history_prior
        else None
    )
    sess = Adaptive2Session(
        id=sid,
        user_id=user_id,
        log_post=(
            _prior_log_post(prior["mean"], prior["sd"])
            if prior
            else _prior_log_post()
        ),
    )
    _sessions[sid] = sess
    sess.current = _make_next(sess)
    return sid, _public(sess.current), _progress(sess)


def submit_answer(sess: Adaptive2Session, choice: Optional[int], unknown: bool) -> dict:
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

    sess.current = _make_next(sess)
    return {
        "finished": False,
        "feedback": feedback,
        **progress,
        "question": _public(sess.current),
    }


def finish_test(sess: Adaptive2Session) -> dict:
    sess.finished = True
    _record(sess)
    return _result(sess)
