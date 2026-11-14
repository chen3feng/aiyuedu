"""词频题库 CAT（Computerized Adaptive Testing）。

与 ``vocab_adaptive`` 共用 4 选 1 + 「以上都不对」题型，估计器则与
``vocab_adaptive2`` 相同（(θ, α) 二维贝叶斯 EAP），区别在选题：

- 难度使用单词的精确词频 rank（而不是 1000 词一档的档位）
- 每题从当前能力附近按 Fisher 信息量选题，不再用「档位 ±1 + 连对探顶」
- 每 5 题插一道远离当前 θ 的跨档锚题（2/6/10/14/18/22 档轮换）：窄带选题
  无法区分「陡曲线高 θ」与「平曲线中等 θ」，锚题提供跨档正确率来识别 α
- 题目参数可被 ``data/calibration/vocab_cat_items.json`` 覆盖；没有标定
  文件时以词频 rank 作为难度先验、区分度取统一的 1/2500

词汇量口径与 adaptive2 一致：``vocab_size`` 取 (θ, α) 曲线下面积，``score``
仍是 50% 认识阈值 θ。题库标定（2PL/MFI/SE 停止）的完整流程见 issue #40。
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
from . import vocab as _classic
from . import vocab_adaptive as _adaptive
from . import vocab_adaptive2 as _dual
from . import vocab_tests
from . import vocab_trend

MIN_QUESTIONS = 20
MAX_QUESTIONS = 80
# 后验标准误降到阈值以下就停止（不必答满 80 题）。实测 3PL 下约 55–65 题。
SE_STOP = 800.0
RECENT_LIMIT = 40
CANDIDATE_WINDOW = 80      # 在当前能力 ±80 个 rank 内找题
TOP_K = 12                 # 从信息量最高的 K 题中加权随机，增加曝光多样性
# 跨档锚题：每 5 题插一道远离当前 θ 的题，固定轮换 2/6/10/14/18/22 档。
# 没有锚题时，CAT 只在 θ ±80 rank 内采样，二维模型的 α 无法识别——同一
# 用户从 8/14/17 档起步会得到 13.8k/16.6k/18.1k（见 MAX_HISTORY_START_LEVEL）。
# 锚题提供跨档正确率，α 才能从窄带数据里解放出来。
ANCHOR_EVERY = 5
ANCHOR_LEVELS = (2, 6, 10, 14, 18, 22)
ANCHOR_WINDOW = 30         # 锚题档位 ±30 rank 内随机选词
DEFAULT_START = 1500.0     # 首题难度（高频词热身）
# 历史成绩给出的起点档位上限。CAT 只在当前 θ ±80 rank 内选题，起点越高，
# 整场就锁在越高频段，模型没有机会看到低频段；对「曲线很平」的用户，高分
# 档位的一串答对会被固定斜率解释成 θ 继续上移，形成 runaway。用同一历史
# 曲线模拟：起点 8/14/16/17 档分别得 13,800/16,600/17,500/18,100，而三场
# 真实 CAT 是 12,339/16,194/16,928；封顶到 8 档后与 classic/adaptive 的
# 13,900/14,100 对齐（2026-11d）。11e 的二维模型 + 锚题把同一曲线的 θ 提到
# 约 14,900、面积约 15,100（真值 θ≈16,300、面积≈15,000）；起点仍是主要偏差
# 来源，锚题不替代封顶。6k/18k/24k 真值用户均未变差（6k 段面积正偏约 +5%，
# 18k/24k 在 ±6% 内）。
MAX_HISTORY_START_LEVEL = 8
# 日志版本号：算法口径变化时递增，便于按版本回放与标定。
ALGO_VERSION = "2026-11e"

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
    """词性标记：统一走 vocab.pos_class（兼容词性后无空格的释义）。"""
    return _classic.pos_class(gloss)


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


def _info(item: dict, theta: float, alpha: float) -> float:
    """3PL Fisher 信息量：a²(1-c)²p²(1-p)² / (P(1-P))。

    ``a`` 是题目区分度 × 个人斜率 α：未标定词 a=α/2500，标定后
    a=α × a_item。
    """
    c = _adaptive.GUESS_RATE
    a = alpha * item["a"]
    p = _adaptive.sigmoid(a * (theta - item["b"]))
    prob = c + (1.0 - c) * p
    if prob <= 0.0 or prob >= 1.0:
        return 0.0
    return (a * (1.0 - c) * p * (1.0 - p)) ** 2 / (prob * (1.0 - prob))


def _anchor_level(sess: "CatSession") -> Optional[int]:
    """当前题是否为锚题；是则返回目标档位。第 5、10、15… 题轮换档位。"""
    if not sess.total or sess.total % ANCHOR_EVERY != ANCHOR_EVERY - 1:
        return None
    return ANCHOR_LEVELS[(sess.total // ANCHOR_EVERY) % len(ANCHOR_LEVELS)]


def _pick_anchor(sess: "CatSession", level: int) -> Optional[dict]:
    """在锚题档位附近随机选一道没做过的题；没有可用词时返回 None。"""
    center_score = level * _adaptive.LEVEL_WIDTH + _adaptive.LEVEL_OFFSET
    bank = _bank()
    ranks = _ranks()
    center = bisect.bisect_left(ranks, center_score)
    lo = max(0, center - ANCHOR_WINDOW)
    hi = min(len(bank), center + ANCHOR_WINDOW)
    pool = [it for it in bank[lo:hi] if it["word"] not in sess.recent]
    return sess.rng.choice(pool) if pool else None


def _pick_item(sess: "CatSession") -> tuple[dict, bool]:
    """选题：锚题轮换优先，否则在 θ 附近按 Fisher 信息量加权随机。

    返回 ``(item, is_anchor)``；``is_anchor`` 只在真的选中了锚题时为 True
    （锚题池为空时会退回普通选题）。
    """
    alpha = sess.alpha
    if sess.total:
        theta = sess.score
    elif sess.start_level is not None:
        theta = sess.start_level * _adaptive.LEVEL_WIDTH + _adaptive.LEVEL_OFFSET
    else:
        theta = DEFAULT_START

    anchor_level = _anchor_level(sess)
    if anchor_level is not None:
        anchor = _pick_anchor(sess, anchor_level)
        if anchor is not None:
            return anchor, True

    bank = _bank()
    ranks = _ranks()
    center = bisect.bisect_left(ranks, theta)
    lo = max(0, center - CANDIDATE_WINDOW)
    hi = min(len(bank), center + CANDIDATE_WINDOW)
    pool = [it for it in bank[lo:hi] if it["word"] not in sess.recent]
    if not pool:
        pool = [it for it in bank if it["word"] not in sess.recent] or bank

    scored = sorted(
        pool, key=lambda it: _info(it, theta, alpha), reverse=True
    )[:TOP_K]
    weights = [_info(it, theta, alpha) for it in scored]
    if sum(weights) <= 0.0:
        return sess.rng.choice(scored), False
    return sess.rng.choices(scored, weights=weights)[0], False


def _make_question(
    item: dict, rng: random.Random, anchor: bool = False
) -> dict:
    q = _adaptive._question_from_word(
        (item["rank"], item["word"], item["gloss"], item["pos"]), rng
    )
    # 下发给前端时 _public 会丢掉这些字段，只用于服务端计分与标定。
    q["b"] = item["b"]
    q["a"] = item["a"]
    q["anchor"] = anchor
    return q


@dataclass
class CatSession:
    id: str
    rng: random.Random = field(default_factory=random.Random)
    score: float = 0.0             # θ 后验均值（50% 认识阈值）
    alpha: float = 1.0             # α 后验均值（相对基准斜率）
    total: int = 0
    correct: int = 0
    wrong: int = 0
    unknown: int = 0
    log_post: list = field(default_factory=_dual._prior_log_post)  # (θ, α) 二维
    se: float = 0.0                # θ 后验标准差
    alpha_se: float = 0.0
    current: Optional[dict] = None
    recent: list = field(default_factory=list)
    history: list = field(default_factory=list)
    finished: bool = False
    user_id: Optional[str] = None
    recorded: bool = False
    start_level: Optional[int] = None                # 历史成绩只决定起点（首题档位 + 宽先验均值）
    last_ts: float = 0.0                             # 上一题作答时间（算 elapsed_ms）
    stop_reason: str = ""                            # "se" / "max" / "manual"


_sessions: dict[str, CatSession] = {}


def get_session(sid: str) -> Optional[CatSession]:
    return _sessions.get(sid)


def _base_level(sess: CatSession) -> int:
    return max(0, min(_adaptive.MAX_LEVEL, int(round(sess.score / _adaptive.LEVEL_WIDTH))))


def _progress(sess: CatSession) -> dict:
    score = int(round(sess.score))
    return {
        "score": score if sess.total >= 1 else None,
        "vocab_size": (
            int(round(_dual._vocab_area(sess.score, sess.alpha)))
            if sess.total else None
        ),
        "alpha": round(sess.alpha, 2),
        "total": sess.total,
        "correct": sess.correct,
        "unknown": sess.unknown,
        "wrong": sess.wrong,
        "converged": sess.total >= 50 or bool(sess.stop_reason),
        "level": _base_level(sess),
        "score_interval": _adaptive._score_interval(sess),
        "se": int(round(sess.se)),
        "stop_reason": sess.stop_reason or None,
    }


def _result(sess: CatSession) -> dict:
    score = int(round(sess.score)) if sess.total else 0
    area = _dual._vocab_area(sess.score, sess.alpha) if sess.total else 0.0
    return {
        "vocab_size": int(round(area / 10) * 10),
        "score": score,
        "alpha": round(sess.alpha, 2),
        "total": sess.total,
        "correct": sess.correct,
        "unknown": sess.unknown,
        "wrong": sess.wrong,
        "ready": sess.total >= MIN_QUESTIONS,
        "score_interval": _adaptive._score_interval(sess),
        "vocab_interval": _dual._vocab_interval(sess) if sess.total else [0, 0],
        "se": int(round(sess.se)),
        "stop_reason": sess.stop_reason or None,
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
            "anchor": bool(q.get("anchor")),
            "word": q["word"],
            "response": response,
            "include_correct": q["correct_index"] != 3,
            "elapsed_ms": elapsed_ms,
            "score": int(round(sess.score)),
            "alpha": round(sess.alpha, 2),
            "se": int(round(sess.se)),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _record(sess: CatSession) -> None:
    if sess.recorded or not sess.user_id or sess.total < MIN_QUESTIONS:
        return
    sess.recorded = True
    result = _result(sess)
    vocab_tests.add(sess.user_id, {
        "ts": round(time.time(), 3),
        "algo": "cat",
        "algo_version": ALGO_VERSION,
        "score": result["score"],
        "vocab_size": result["vocab_size"],
        "alpha": result["alpha"],
        "total": result["total"],
        "correct": result["correct"],
        "wrong": result["wrong"],
        "unknown": result["unknown"],
        "se": result["se"],
        "stop_reason": result["stop_reason"],
    })


def start_test(user_id: Optional[str] = None) -> tuple[str, dict, dict]:
    sid = uuid.uuid4().hex
    # 历史成绩只提供「起点」：首题难度 + 一个宽先验（见 adaptive.start_test）。
    # 但 CAT 的选题窗口只有 θ ±80 rank，起点过高会让整场锁在高频段，
    # 所以历史起点额外封顶到 MAX_HISTORY_START_LEVEL（见常量注释）。
    prior = (
        vocab_trend.history_prior(user_id, "cat")
        if settings.vocab_history_prior
        else None
    )
    start_level = None
    log_post = None
    if prior:
        start_level = max(
            0,
            min(
                _adaptive.MAX_LEVEL,
                MAX_HISTORY_START_LEVEL,
                int(round(prior["mean"] / _adaptive.LEVEL_WIDTH)),
            ),
        )
        mean = start_level * _adaptive.LEVEL_WIDTH + _adaptive.LEVEL_OFFSET
        sd = max(_adaptive.HISTORY_PRIOR_MIN_SD, prior["sd"])
        log_post = _dual._prior_log_post(mean, sd)
    sess = CatSession(
        id=sid,
        user_id=user_id,
        start_level=start_level,
        log_post=log_post if log_post is not None else _dual._prior_log_post(),
    )
    _sessions[sid] = sess
    item, is_anchor = _pick_item(sess)
    sess.current = _make_question(item, sess.rng, anchor=is_anchor)
    sess.recent.append(sess.current["word"])
    return sid, _adaptive._public(sess.current), _progress(sess)


def _update_score(sess: CatSession, q: dict, outcome: str) -> None:
    """按题目自己的难度/区分度把一次作答乘进 (θ, α) 二维后验。"""
    b = float(q["b"])
    a_item = float(q["a"])
    c = _adaptive.GUESS_RATE
    power = _adaptive.UNKNOWN_LIKELIHOOD_POWER
    lp = sess.log_post
    for i, theta in enumerate(_dual.THETA_GRID):
        base = i * _dual.N_ALPHA
        for j, alpha in enumerate(_dual.ALPHA_GRID):
            p = _adaptive.sigmoid(alpha * a_item * (theta - b))
            if outcome == "correct":
                lik = c + (1.0 - c) * p
                lp[base + j] += math.log(max(lik, _adaptive.PROB_FLOOR))
            elif outcome == "unknown":
                lp[base + j] += power * math.log(
                    max(1.0 - p, _adaptive.PROB_FLOOR)
                )
            else:
                lp[base + j] += math.log(
                    max((1.0 - c) * (1.0 - p), _adaptive.PROB_FLOOR)
                )
    _dual._normalize_log_post(sess)
    sess.total += 1
    _dual._refresh_moments(sess)


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
    # 停止规则：答满上限，或后验标准误已足够小（真 CAT 的 SE 停止）。
    if sess.total >= MAX_QUESTIONS:
        sess.stop_reason = "max"
    elif sess.total >= MIN_QUESTIONS and sess.se <= SE_STOP:
        sess.stop_reason = "se"
    progress = _progress(sess)
    if sess.stop_reason:
        sess.finished = True
        _record(sess)
        return {"finished": True, "feedback": feedback, **progress, "result": _result(sess)}

    item, is_anchor = _pick_item(sess)
    sess.current = _make_question(item, sess.rng, anchor=is_anchor)
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
    if not sess.stop_reason:
        sess.stop_reason = "manual"
    sess.finished = True
    _record(sess)
    return _result(sess)
