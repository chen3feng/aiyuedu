"""词汇量评测服务（分层抽样 + 识别率×词频权重）的单元与回归测试。

覆盖：
  - 分段边界、估值公式（Σ 段宽 × 认识率）等纯函数；
  - 出题结构与频段约束；
  - start → answer → finish 完整流程（全对 / 全不认识 / 阈值模型）；
  - 「显示分单步不突变」回归测试（旧自适应算法曾剧烈跳动）；
  - 尖峰模型下的稳定性回归测试（旧算法曾出现 2 倍分叉）。

运行：uv run --directory apps/api pytest -q
"""
import random
import statistics

import pytest

from app.services import vocab


# ---------- 纯函数：分段与估值 ----------

def test_band_widths_sum_to_max_vocab():
    assert sum(vocab._band_width(i) for i in range(vocab.N_BANDS)) == vocab.MAX_VOCAB


@pytest.mark.parametrize(
    "rank,expected",
    [
        (0, 0), (1, 0), (1999, 0), (2000, 1), (4000, 2),
        (20999, 8), (21000, 9), (24999, 9), (25000, 9), (99999, 9),
    ],
)
def test_band_of(rank, expected):
    assert vocab._band_of(rank) == expected


def test_estimate_empty_session_is_zero():
    assert vocab._estimate(vocab.TestSession(id="x")) == 0.0


def test_estimate_single_known_band():
    sess = vocab.TestSession(id="x")
    sess.band_total[0] = 2
    sess.band_known[0] = 2
    assert vocab._estimate(sess) == 2000  # 段宽 2000 × 认识率 1.0


def test_estimate_proportion_weighted_sum():
    sess = vocab.TestSession(id="x")
    sess.band_total[0] = 4
    sess.band_known[0] = 3   # 认识率 0.75 → 2000 × 0.75 = 1500
    sess.band_total[3] = 4
    sess.band_known[3] = 2   # 认识率 0.5 → 2000 × 0.5 = 1000
    assert vocab._estimate(sess) == pytest.approx(2500.0)


def test_estimate_zeroes_below_guess_rate():
    """认识率 ≤ 25%（四选一纯猜命中率）的段视为无知识信号，计 0。"""
    sess = vocab.TestSession(id="x")
    sess.band_total[0] = 4
    sess.band_known[0] = 2   # 0.5 → 保留
    sess.band_total[3] = 4
    sess.band_known[3] = 1   # 0.25 → 猜测下限，清零
    assert vocab._estimate(sess) == pytest.approx(2000 * 0.5)  # 1000


def test_isotonic_output_is_non_increasing():
    out = vocab._isotonic_noninc([0.3, 0.9, 0.2], [5, 5, 5])
    assert all(out[i] >= out[i + 1] for i in range(len(out) - 1))


def test_estimate_flattens_spike():
    """尖峰（低段不认识、高段「蒙对」）应被单调平滑压低，不按表面认识率计分。

    对应真实场景：孩子把 rank≈24000 的 cerecloth 蒙对，若按表面 1.0 认识率，
    单题就 +4000×1.0 = 4000 分；单调平滑后应大幅回落。
    """
    sess = vocab.TestSession(id="x")
    sess.band_total[0] = 4
    sess.band_known[0] = 2   # 0.5
    sess.band_total[1] = 4
    sess.band_known[1] = 1   # 0.25
    sess.band_total[2] = 4
    sess.band_known[2] = 0   # 0.0
    sess.band_total[9] = 4
    sess.band_known[9] = 4   # 1.0 —— 尖峰：认识最难词却漏了常见词
    naive = 2000 * 0.5 + 2000 * 0.25 + 2000 * 0.0 + 4000 * 1.0  # 5500
    assert vocab._estimate(sess) < naive
    # 尖峰段(1.0) 与相邻低谷段(0.25/0.0) 合并成 (1+0+4)/12=5/12≈0.417，
    # 故 = 2000×0.5 + 2000×5/12 + 2000×5/12 + 4000×5/12 = 13000/3
    assert vocab._estimate(sess) == pytest.approx(13000 / 3)


# ---------- 出题 ----------

def test_question_has_four_options_with_correct():
    q = vocab._pick_in_band(0, set())
    assert q["word"]
    assert len(q["options"]) == 4
    assert 0 <= q["correct_index"] < 4
    assert q["options"][q["correct_index"]] == q["correct_gloss"]


def test_pick_in_band_respects_rank_range():
    for _ in range(20):
        q = vocab._pick_in_band(9, set())  # 末段 [21000, 25000]
        assert 21000 <= q["rank"] <= 25000


# ---------- 会话流程 ----------

def _run_flow(respond):
    """驱动一轮完整测评，返回 (result, 逐词显示分列表)。"""
    sid, _, _ = vocab.start_test()
    sess = vocab.get_session(sid)
    scores = []
    while not sess.finished:
        choice, unknown = respond(sess.current)
        ans = vocab.submit_answer(sess, choice, unknown)
        if ans["score"] is not None:
            scores.append(ans["score"])
    return vocab.finish_test(sess), scores


def test_start_test_returns_question_and_null_score():
    sid, question, progress = vocab.start_test()
    assert sid
    assert question["word"] and question["options"]
    assert progress["score"] is None  # 少于 3 词不显示分
    assert progress["total"] == 0


def test_full_flow_all_known_reaches_max():
    result, _ = _run_flow(lambda q: (q["correct_index"], False))
    assert result["vocab_size"] == vocab.MAX_VOCAB
    assert result["total"] == vocab.MAX_QUESTIONS
    assert result["correct"] == vocab.MAX_QUESTIONS


def test_full_flow_all_unknown_reaches_zero():
    result, _ = _run_flow(lambda q: (None, True))
    assert result["vocab_size"] == 0
    assert result["unknown"] == vocab.MAX_QUESTIONS


def test_full_flow_threshold_approximates_true_vocab():
    # 阈值模型：rank <= V 认识，否则不认识。比例口径会略高于 V（面积 ≈ 1.11·V），
    # 故用宽松区间验证「量级正确」，精确校准见 scripts/diagnose_vocab_bands.py。
    V = 8000
    result, _ = _run_flow(
        lambda q: (q["correct_index"], False) if q["rank"] <= V else (None, True)
    )
    assert 7000 <= result["vocab_size"] <= 11000


def test_score_never_jumps_more_than_max_step():
    # 乱选作答，显示分单次变动不得超过 SCORE_MAX_STEP（「突变」回归测试）
    _, scores = _run_flow(lambda q: (0, False))
    assert len(scores) >= 40  # 50 题里至少有 47 个显示分
    for a, b in zip(scores, scores[1:]):
        assert abs(b - a) <= vocab.SCORE_MAX_STEP


def test_ramp_fills_low_bands_first():
    """按词频从低到高逐段填满：整卷 50 题排成从易到难的单坡道。"""
    from collections import Counter

    sid, _, _ = vocab.start_test()
    sess = vocab.get_session(sid)
    order = []
    for _ in range(vocab.MAX_QUESTIONS):
        order.append(vocab._band_of(sess.current["rank"]))
        vocab.submit_answer(sess, None, True)
        if sess.finished:
            break
    assert order == sorted(order)  # 全局非降：由易到难
    assert Counter(order) == {i: vocab.ROUNDS for i in range(vocab.N_BANDS)}


# ---------- 稳定性回归（曾出现 2 倍分叉） ----------

def test_stability_on_spiky_profile():
    """尖峰模型（会认识生僻词、漏常见词）下，最终词汇量应稳定。

    旧的自适应阶梯 + logistic 在同一模型下会把结果分叉到 2 倍；
    分层抽样 + 比例累加应把相对标准差控制在 15% 以内。
    """
    rng = random.Random(42)
    profile = {}
    for rank, lemma, _ in vocab._candidates():
        p = 1.0 / (1.0 + (rank / 15000) ** 3.0)
        p = max(0.0, min(1.0, p + rng.gauss(0, 0.30)))
        profile[lemma] = rng.random() < p

    finals = []
    for seed in range(30):
        random.seed(seed)
        sid, _, _ = vocab.start_test()
        sess = vocab.get_session(sid)
        while not sess.finished:
            q = sess.current
            if profile[q["word"]]:
                choice, unknown = q["correct_index"], False
            else:
                choice, unknown = None, True
            vocab.submit_answer(sess, choice, unknown)
        finals.append(vocab.finish_test(sess)["vocab_size"])

    mean = statistics.mean(finals)
    std = statistics.stdev(finals)
    assert std / mean < 0.15  # 相对标准差 < 15%
