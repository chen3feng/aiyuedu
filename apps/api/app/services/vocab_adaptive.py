"""自适应词汇量测试：二维贝叶斯 EAP（θ + α）。

算法参考 dict.eudic.net 的词汇量测试（逆向分析见
``docs/eudic-vocab-algorithm.md``），但把原版的 Elo 式增量更新换成了
**网格贝叶斯 EAP**，并把能力扩展为两个参数：

    p(know) = sigmoid(α × (θ - b) / 2500)

- **θ**：50% 认识阈值（分数尺度，0–25,000）
- **α**：个人区分度，相对基准斜率 ``1/2500`` 的倍数，1.0 与单参数模型相同

单参数模型假设所有人的「认识概率—词频」曲线斜率相同，对曲线平缓的用户会把
同一批答案读成明显更高的 θ；二维模型让数据同时决定水平与斜率，词汇量取曲线
下面积：

    词汇量 = Σ_level 1000 × sigmoid(α × (θ - b_level) / 2500)

- 答对：likelihood = c + (1 - c) * p，c 为有效猜测率
- 答错：likelihood = (1 - c) * (1 - p)
- 不认识：likelihood = (1 - p) ** 0.625（延续原版的软惩罚）

选词沿用原版的档位偏移与探顶启发式：连续答对 4 题后跳到更高档位探顶，两次
探顶之间至少间隔 8 题。题目为「3 个中文释义 + 以上都不对」，另有独立的
「不认识」按钮。2026-11f 起 ``adaptive2`` 合并进本算法，只作为旧名字保留在
路由别名与历史记录里。
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
from . import vocab_trend

# —— 拟合得到的算法常数（见 docs/eudic-vocab-algorithm.md §4）——
LEVEL_WIDTH = 1000          # 每个词频档约 1000 词
LEVEL_OFFSET = 100          # 档位难度偏移
SCALE = 2500                # logistic 基准斜率（分）
UNKNOWN_LIKELIHOOD_POWER = 0.625  # 「不认识」的软惩罚：似然取 (1-p)^0.625
# 有效猜测率：4 选 1 的 0.25 乘以「不会时仍选择猜」的比例（观测约 0.45–0.5）。
# 直接用 0.25 会把「不认识」的诚实作答也当成一定蒙对，导致系统性高估。
GUESS_RATE = 0.12
# 换题方差下限（分）：模型只反映「给定这些题」的答题噪声，词表内难度差异、
# 当天状态等会让不同次测试再波动约 1,000–1,300 分。先用保守下限，
# 题目级标定（#40）后可替换为实测方差。
FORM_SD = 1200
MAX_LEVEL = 24              # wordlist.csv 覆盖 0~24 档
MAX_SCORE = 25000           # 词库上限
CORRECT_PRESENT_RATE = 0.75 # 正确释义出现在 3 个选项中的概率
MIN_QUESTIONS = 20          # 线上「最少测满 20 题才能查看结果」
MAX_QUESTIONS = 80          # 50 题后可继续答，最多 80 题；更多样本让估计更稳
PROBE_QUESTIONS = 6         # 每次探顶最多 6 题
MAX_PROBES = 3              # 最多探顶 3 次，避免无限追高
PROBE_COOLDOWN = 8          # 两次探顶之间至少间隔 8 题
# 日志版本号：算法口径变化时递增，便于按版本回放与标定。
ALGO_VERSION = "2026-11f"

# —— 后验网格：θ 为 0~25000 分、步长 50（501 个点）；α 为相对斜率的 9 档 ——
GRID_STEP = 50
GRID = tuple(float(i * GRID_STEP) for i in range(MAX_SCORE // GRID_STEP + 1))
# 下界 0.25 避免曲线很平的用户把 α 顶在网格边界上。
ALPHA_GRID = (0.25, 0.35, 0.5, 0.65, 0.8, 1.0, 1.25, 1.6, 2.0)
N_ALPHA = len(ALPHA_GRID)
ALPHA_PRIOR_LOG_SD = 0.35       # log α 先验标准差：弱信息，数据可主导
# 弱信息先验：均值 1000、标准差 3000，截断在 [0, 25000]。
# 均值低是为了让前几题从高频词缓慢爬升，标准差大保证数据能主导估计。
PRIOR_MEAN = 1000.0
PRIOR_SD = 3000.0
# 历史起点先验的标准差下限。历史只提供起点：太紧（旧版同日 sd≈1,500）会让
# 短测试照抄旧分并逐次抬高；完全不用先验又会让首题答完后后验掉回默认均值
# （约 2,800），第二题直接跌到 2–3 档。4,000 足够宽，数据仍能很快主导。
HISTORY_PRIOR_MIN_SD = 4000.0
PROB_FLOOR = 1e-12          # 防止 log(0)

NONE_OF_ABOVE = "以上都不对"

RULES = (
    "每题给出 3 个中文释义，正确意思可能不在其中（此时选「以上都不对」）；"
    "认识就选正确意思，不认识请点「不认识」。诚实作答，测评更准。"
)
RESULT_MESSAGE = (
    "词汇量按双参数 IRT（θ + α）估计：不仅估计你的水平，还估计你的"
    "「认识概率—词频」曲线斜率，再对整条曲线积分得到词汇量。"
    "最少 20 题即可查看结果，继续答会更稳。"
)

# adaptive2 / eudic 都是旧名字：日志与历史统一写 adaptive。
_ALGO_ALIASES = {"adaptive2": "adaptive", "eudic": "adaptive"}


def canonical_algo(algo: str) -> str:
    """把旧算法名（adaptive2 / eudic）归一化为 adaptive。"""
    return _ALGO_ALIASES.get(algo, algo)


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
        # 统一用 vocab.pos_class 解析（兼容 "n.<美俚>…" 这类词性后无空格的释义）。
        levels[_level_of(rank)].append((rank, lemma, g, _classic.pos_class(g)))
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


def _question_from_word(word: tuple, rng: random.Random) -> dict:
    """把候选词 ``(rank, lemma, gloss, pos)`` 做成一道题。"""
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


def _make_question(level: int, rng: random.Random, avoid: set) -> dict:
    """生成一道与线上同构的题：3 个释义 + 以上都不对（「不认识」由前端按钮承担）。"""
    return _question_from_word(_pick_word(level, rng, avoid), rng)


def _prior_log_post(
    theta_mean: Optional[float] = None, theta_sd: Optional[float] = None
) -> list[float]:
    """(θ, α) 二维先验：θ ~ N(mean, sd²)，log α ~ N(0, 0.35²)。

    默认是 N(PRIOR_MEAN, PRIOR_SD)。有历史成绩时，``start_test`` 会传入一个
    以历史档位为均值、``sd ≥ HISTORY_PRIOR_MIN_SD`` 的宽先验：它只决定起点，
    数据很快就能把它拉开。
    """
    mean = PRIOR_MEAN if theta_mean is None else theta_mean
    sd = PRIOR_SD if theta_sd is None else max(300.0, theta_sd)
    out: list[float] = []
    for theta in GRID:
        t_prior = -0.5 * ((theta - mean) / sd) ** 2
        for alpha in ALPHA_GRID:
            a_prior = -0.5 * (math.log(alpha) / ALPHA_PRIOR_LOG_SD) ** 2
            out.append(t_prior + a_prior)
    return out


@dataclass
class AdaptiveSession:
    id: str
    rng: random.Random = field(default_factory=random.Random)
    score: float = 0.0          # θ 后验均值（50% 认识阈值）
    alpha: float = 1.0          # α 后验均值（相对基准斜率）
    se: float = 0.0             # θ 后验标准差
    alpha_se: float = 0.0
    total: int = 0
    correct: int = 0
    wrong: int = 0
    unknown: int = 0
    log_post: list = field(default_factory=_prior_log_post)  # (θ, α) 二维
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
    start_level: Optional[int] = None                # 历史成绩只决定起点
    last_ts: float = 0.0                             # 上一题作答时间（算 elapsed_ms）


_sessions: dict[str, AdaptiveSession] = {}


def get_session(sid: str) -> Optional[AdaptiveSession]:
    return _sessions.get(sid)


def _public(q: dict) -> dict:
    """下发给前端的题目（不含正确答案）。"""
    return {"word": q["word"], "options": q["options"], "level": q["level"]}


def _base_level(sess: AdaptiveSession) -> int:
    return max(0, min(MAX_LEVEL, int(round(sess.score / LEVEL_WIDTH))))


def _select_level(sess: AdaptiveSession) -> int:
    if sess.total == 0:
        if sess.start_level is not None:
            # 历史成绩只决定起点：首题从上次档位开始，后验用宽的历史先验。
            return sess.start_level
        # 无历史时用高频词热身（1~2 档），避免一上来就是生僻词
        return 1 + sess.rng.choice([0, 1])
    if sess.probe_remaining > 0:
        return sess.probe_level
    # 连续答对 4 题即可再次探顶，但两次探顶之间至少间隔 PROBE_COOLDOWN 题。
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


def _make_next(sess: AdaptiveSession) -> dict:
    q = _make_question(_select_level(sess), sess.rng, set(sess.recent[-20:]))
    sess.recent.append(q["word"])
    if len(sess.recent) > 40:
        sess.recent = sess.recent[-40:]
    return q


def _normalize_log_post(sess: AdaptiveSession) -> None:
    """把二维对数后验归一化，并整体平移使最大值为 0，避免数值下溢。"""
    peak = max(sess.log_post)
    weights = [math.exp(v - peak) for v in sess.log_post]
    log_z = math.log(sum(weights))
    sess.log_post = [v - peak - log_z for v in sess.log_post]


def _refresh_moments(sess: AdaptiveSession) -> None:
    """从二维后验计算 θ / α 的均值与标准差。"""
    weights = [math.exp(v) for v in sess.log_post]
    total = sum(weights)
    theta_mean = alpha_mean = 0.0
    for i, theta in enumerate(GRID):
        row = weights[i * N_ALPHA:(i + 1) * N_ALPHA]
        row_sum = sum(row)
        theta_mean += theta * row_sum
        for j, alpha in enumerate(ALPHA_GRID):
            alpha_mean += alpha * row[j]
    theta_mean /= total
    alpha_mean /= total
    var = 0.0
    alpha_var = 0.0
    for i, theta in enumerate(GRID):
        row = weights[i * N_ALPHA:(i + 1) * N_ALPHA]
        var += sum(row) * (theta - theta_mean) ** 2
        for j, alpha in enumerate(ALPHA_GRID):
            alpha_var += row[j] * (alpha - alpha_mean) ** 2
    sess.score = max(0.0, min(float(MAX_SCORE), theta_mean))
    sess.alpha = alpha_mean
    sess.se = math.sqrt(max(var / total, 0.0))
    sess.alpha_se = math.sqrt(max(alpha_var / total, 0.0))


def _update_score(sess: AdaptiveSession, q: dict, outcome: str) -> None:
    """按题目难度把本次作答乘进 (θ, α) 二维后验。

    由于后验是各题似然的乘积，最终结果与作答顺序无关。
    """
    difficulty = LEVEL_WIDTH * q["level"] + LEVEL_OFFSET
    power = UNKNOWN_LIKELIHOOD_POWER if outcome == "unknown" else 1.0
    lp = sess.log_post
    for i, theta in enumerate(GRID):
        base = i * N_ALPHA
        for j, alpha in enumerate(ALPHA_GRID):
            p = sigmoid(alpha * (theta - difficulty) / SCALE)
            if outcome == "correct":
                # 3PL：不会时仍可能蒙对，正确选项只提供部分证据。
                lik = GUESS_RATE + (1.0 - GUESS_RATE) * p
                lp[base + j] += math.log(max(lik, PROB_FLOOR))
            elif outcome == "unknown":
                # 明确表示不认识：按未掌握处理，保留原版的软惩罚。
                lp[base + j] += power * math.log(max(1.0 - p, PROB_FLOOR))
            else:
                # 猜错：未掌握且没有蒙对。
                lp[base + j] += math.log(
                    max((1.0 - GUESS_RATE) * (1.0 - p), PROB_FLOOR)
                )
    _normalize_log_post(sess)
    sess.total += 1
    _refresh_moments(sess)


def _know_prob(theta: float, alpha: float, difficulty: float) -> float:
    return sigmoid(alpha * (theta - difficulty) / SCALE)


def _vocab_area(theta: float, alpha: float) -> float:
    """曲线下面积：Σ 每档 1000 词 × 该档认识概率。"""
    total = 0.0
    for level in range(MAX_LEVEL + 1):
        total += LEVEL_WIDTH * _know_prob(
            theta, alpha, LEVEL_WIDTH * level + LEVEL_OFFSET
        )
    return total


def _vocab_interval(sess: AdaptiveSession) -> list:
    """词汇量（面积）的 95% 区间：对后验按面积加权取分位数。"""
    weights = [math.exp(v) for v in sess.log_post]
    pairs = []
    for i, theta in enumerate(GRID):
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


def _score_interval(sess: AdaptiveSession) -> list:
    """95% 估计区间：后验标准误 + 换题方差下限。

    后验只回答「给这些题时能力在哪」，不包含换一套题带来的难度抽样波动，
    所以用 FORM_SD 把区间放宽到接近实测的重测波动。
    """
    half = 1.96 * math.sqrt(sess.se ** 2 + FORM_SD ** 2)
    return [
        max(0, int(round(sess.score - half))),
        min(MAX_SCORE, int(round(sess.score + half))),
    ]


def _progress(sess: AdaptiveSession) -> dict:
    score = int(round(sess.score))
    return {
        "score": score if sess.total >= 1 else None,
        "vocab_size": (
            int(round(_vocab_area(sess.score, sess.alpha))) if sess.total else None
        ),
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


def _result(sess: AdaptiveSession) -> dict:
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


def _log_answer(sess: AdaptiveSession, q: dict, response: str) -> None:
    """追加一条评测记录（JSONL），供离线分析与题库标定。日志失败不影响评测。"""
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
            "algo": "adaptive",
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


def _record(sess: AdaptiveSession) -> None:
    """把完成的测评写进用户历史（幂等；匿名/题量不足不记）。"""
    if sess.recorded or not sess.user_id or sess.total < MIN_QUESTIONS:
        return
    sess.recorded = True
    result = _result(sess)
    vocab_tests.add(sess.user_id, {
        "ts": round(time.time(), 3),
        "algo": "adaptive",
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
    # 历史成绩只提供「起点」：首题档位 + 一个宽先验。旧版把上次 score 当作
    # sd≈1,500 的紧先验，短测试几乎照抄旧分；但若完全不用先验，首题答完后后验
    # 会掉回默认均值（约 2,800），第二题直接跌到 2–3 档。sd ≥ 4,000 时起点
    # 跟着历史走，数据仍能很快主导。
    prior = (
        vocab_trend.history_prior(user_id, "adaptive")
        if settings.vocab_history_prior
        else None
    )
    start_level = None
    log_post = None
    if prior:
        start_level = max(0, min(MAX_LEVEL, int(round(prior["mean"] / LEVEL_WIDTH))))
        mean = start_level * LEVEL_WIDTH + LEVEL_OFFSET
        sd = max(HISTORY_PRIOR_MIN_SD, prior["sd"])
        log_post = _prior_log_post(mean, sd)
    sess = AdaptiveSession(
        id=sid,
        user_id=user_id,
        start_level=start_level,
        log_post=log_post if log_post is not None else _prior_log_post(),
    )
    _sessions[sid] = sess
    sess.current = _make_next(sess)
    return sid, _public(sess.current), _progress(sess)


def submit_answer(sess: AdaptiveSession, choice: Optional[int], unknown: bool) -> dict:
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


def finish_test(sess: AdaptiveSession) -> dict:
    """用户主动结束测评，返回最终成绩（幂等，可重复调用）。"""
    sess.finished = True
    _record(sess)
    return _result(sess)
