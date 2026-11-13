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
    sess.band_known[0] = 3   # 0.75 → 猜测校正 (0.75-0.12)/0.88 = 0.7159 → 2000×0.7159
    sess.band_total[3] = 4
    sess.band_known[3] = 2   # 0.5  → (0.5-0.12)/0.88 = 0.4318 → 2000×0.4318
    assert vocab._estimate(sess) == pytest.approx(2000 * 0.63 / 0.88 + 2000 * 0.38 / 0.88)


def test_wilson_lower_bounds():
    """每段只有 5 题：用 Wilson 下界判断认识率是否显著高于蒙对。"""
    assert vocab._wilson_lower(0, 5) == 0.0
    assert vocab._wilson_lower(2, 5) == pytest.approx(0.118, abs=0.002)
    assert vocab._wilson_lower(3, 5) == pytest.approx(0.231, abs=0.002)
    assert vocab._wilson_lower(5, 5) == pytest.approx(0.566, abs=0.002)
    assert vocab._wilson_lower(0, 0) == 0.0


def test_estimate_zeroes_band_indistinguishable_from_guess():
    """2/5 与 12% 的有效蒙对率分不开（Wilson 下界 0.118），该段计 0。

    旧实现按点估计判断（0.4 > 0.25 就整段计入），会把两道蒙对记成 40% 认识。
    """
    sess = vocab.TestSession(id="x")
    sess.band_total[0] = 4
    sess.band_known[0] = 2   # 0.5 → 保留并校正
    sess.band_total[3] = 4
    sess.band_known[3] = 1   # 0.25 → 与蒙对分不开，清零
    sess.band_total[7] = 5
    sess.band_known[7] = 2   # 2/5 = 0.4 → 同样清零
    assert vocab._estimate(sess) == pytest.approx(2000 * 0.38 / 0.88)  # 863.6


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
    # 尖峰段(1.0) 与相邻低谷段(0.25/0.0) 合并成 (1+0+4)/12=5/12≈0.417；
    # 再做猜测校正：段 0 为 (0.5-0.12)/0.88，段 9 为 (5/12-0.12)/0.88，
    # 段 1、2 的表面认识率与蒙对分不开，计 0。
    expected = 2000 * (0.5 - 0.12) / 0.88 + 4000 * (5 / 12 - 0.12) / 0.88
    assert vocab._estimate(sess) == pytest.approx(expected)


# ---------- 出题 ----------

def test_question_has_four_options_with_correct():
    q = vocab._pick_in_band(0, set())
    assert q["word"]
    assert len(q["options"]) == 4
    assert vocab.NONE_OF_ABOVE in q["options"]
    assert 0 <= q["correct_index"] < 4
    assert q["options"][q["correct_index"]] == q["correct_gloss"]


def test_question_format_matches_eudic():
    """题面与欧路/CAT 对齐：正确释义只出现 75%，否则答案是「以上都不对」。"""
    random.seed(7)
    present = absent = 0
    for _ in range(200):
        q = vocab._pick_in_band(random.randrange(vocab.N_BANDS), set())
        assert len(q["options"]) == 4
        assert vocab.NONE_OF_ABOVE in q["options"]
        if q["correct_gloss"] == vocab.NONE_OF_ABOVE:
            absent += 1
            assert q["gloss"] not in q["options"]
        else:
            present += 1
            assert q["correct_gloss"] == q["gloss"]
            assert q["gloss"] in q["options"]
    assert present > 0 and absent > 0
    assert 0.6 < present / (present + absent) < 0.9  # 期望 0.75


def test_pick_in_band_respects_rank_range():
    for _ in range(20):
        q = vocab._pick_in_band(9, set())  # 末段 [21000, 25000]
        assert 21000 <= q["rank"] <= 25000


# ---------- 少儿不宜敏感词黑名单 ----------

def test_blacklist_loads_sensitive_words():
    bl = vocab._load_blacklist()
    assert "rape" in bl
    assert "penis" in bl
    assert "prostitute" in bl
    assert "sodomite" in bl


def test_candidates_exclude_blacklisted_words():
    """黑名单词不得进入抽题候选，正常词仍在候选里。"""
    lemmas = {c[1] for c in vocab._candidates()}
    for banned in ("rape", "penis", "prostitute", "whore", "sodomite", "condom"):
        assert banned not in lemmas
    assert "apple" in lemmas


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


def test_estimate_real_session_guess_corrected():
    """真实的一次 50 题（2026-11-13）：旧算法 16,500，校正后 ≈13,977。

    原始答对数为每段 5,5,5,4,4,5,5,2,2,0。15k 以上的 2/5、2/5 与蒙对分不开，
    计 0；其余段按 (r-0.12)/0.88 折算。结果是「认识多少词」的保守估计。
    """
    sess = vocab.TestSession(id="x")
    for band, (total, known) in enumerate(
        [(5, 5), (5, 5), (5, 5), (5, 4), (5, 4), (5, 5), (5, 5), (5, 2), (5, 2), (5, 0)]
    ):
        sess.band_total[band] = total
        sess.band_known[band] = known
    assert vocab._estimate(sess) == pytest.approx(13977.27, abs=0.5)
    assert vocab._result(sess)["vocab_size"] == 13980


def test_answer_log_records_algo(monkeypatch, tmp_path):
    """作答日志要带 algo，离线对比三套算法时不必再靠时间戳猜。"""
    import json

    from app.config import settings

    log = tmp_path / "vocab_sessions.jsonl"
    monkeypatch.setattr(settings, "vocab_log_path", str(log))
    sid, _, _ = vocab.start_test()
    sess = vocab.get_session(sid)
    vocab.submit_answer(sess, sess.current["correct_index"], False)
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert rec["algo"] == "classic"
    assert rec["response"] == "correct"


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
    # 阈值模型：rank <= V 认识，否则不认识。V=8000 正好落在段边界上，
    # 前 4 段全对（校正后仍是 1.0），第 5 段起全不认识，估值应恰好为 8000。
    V = 8000
    result, _ = _run_flow(
        lambda q: (q["correct_index"], False) if q["rank"] <= V else (None, True)
    )
    assert result["vocab_size"] == 8000


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
    # 猜测校正把均值压低、相对波动略增（旧实现 14%，现在约 18%）；
    # 这里仍在防「分叉到 2 倍」的回归，20% 足够区分。
    assert std / mean < 0.20
