"""自适应词汇量测试（贝叶斯 EAP）的单元测试。

覆盖：
  - 档位映射与题目结构（3 释义 + 以上都不对）；
  - 分数更新公式（答对 / 答错 / 不认识）；
  - 连续答对后的探顶行为；
  - start → answer → finish 完整流程；
  - 路由层的算法开关（classic / adaptive）。

运行：uv run --directory apps/api pytest -q
"""
import random

import pytest
from fastapi import HTTPException

from app.routers import vocab as vocab_router
from app.services import vocab, vocab_adaptive as adaptive


# ---------- 档位与题目 ----------

@pytest.mark.parametrize(
    "rank,expected",
    [(1, 0), (1000, 0), (1001, 1), (2000, 1), (10000, 9), (24000, 23), (25000, 24)],
)
def test_level_of(rank, expected):
    assert adaptive._level_of(rank) == expected


def test_question_has_three_glosses_plus_none_of_above():
    rng = random.Random(7)
    for level in (0, 5, 12, 24):
        q = adaptive._make_question(level, rng, set())
        assert q["word"]
        assert len(q["options"]) == 4
        assert q["options"][3] == adaptive.NONE_OF_ABOVE
        assert 0 <= q["correct_index"] < 4
        assert q["options"][q["correct_index"]] == q["correct_gloss"]
        if q["correct_index"] == 3:
            assert q["correct_gloss"] == adaptive.NONE_OF_ABOVE
        else:
            assert q["correct_gloss"] != adaptive.NONE_OF_ABOVE


def test_correct_gloss_present_about_75_percent():
    rng = random.Random(11)
    present = sum(
        adaptive._make_question(10, rng, set())["correct_index"] != 3
        for _ in range(500)
    )
    assert 0.68 <= present / 500 <= 0.82


def test_question_level_matches_word_rank():
    rng = random.Random(3)
    q = adaptive._make_question(15, rng, set())
    assert q["level"] == adaptive._level_of(q["rank"])


def test_question_carries_real_gloss():
    """题目内部要保留词的真实含义，供「以上都不对」答后反馈使用。"""
    rng = random.Random(5)
    for _ in range(50):
        q = adaptive._make_question(10, rng, set())
        assert q["gloss"]
        if q["correct_index"] == 3:
            assert q["correct_gloss"] == adaptive.NONE_OF_ABOVE
            assert q["gloss"] != adaptive.NONE_OF_ABOVE
        else:
            assert q["correct_gloss"] == q["gloss"]


# ---------- 分数更新 ----------

def _apply(sess: adaptive.AdaptiveSession, items) -> None:
    for level, outcome in items:
        adaptive._update_score(sess, {"level": level}, outcome)


def test_posterior_score_is_order_invariant():
    """给定相同的题目与结果，最终得分不应受作答顺序影响。"""
    items = [
        (5, "correct"), (9, "wrong"), (2, "unknown"),
        (12, "correct"), (7, "unknown"), (3, "wrong"),
    ] * 5
    a = adaptive.AdaptiveSession(id="a")
    b = adaptive.AdaptiveSession(id="b")
    _apply(a, items)
    _apply(b, list(reversed(items)))
    assert a.score == pytest.approx(b.score, abs=1e-6)
    assert a.se == pytest.approx(b.se, abs=1e-6)
    assert adaptive._progress(a)["score_interval"] == adaptive._progress(b)["score_interval"]


def test_correct_raises_estimate_and_wrong_lowers_it():
    correct = adaptive.AdaptiveSession(id="c")
    wrong = adaptive.AdaptiveSession(id="w")
    unknown = adaptive.AdaptiveSession(id="u")
    _apply(correct, [(10, "correct")])
    _apply(wrong, [(10, "wrong")])
    _apply(unknown, [(10, "unknown")])
    assert correct.score > wrong.score
    # 「不认识」比答错扣得轻，但仍低于答对
    assert unknown.score > wrong.score
    assert correct.score > unknown.score


def test_score_never_negative():
    sess = adaptive.AdaptiveSession(id="x")
    for _ in range(5):
        adaptive._update_score(sess, {"level": 20}, "wrong")
    assert sess.score >= 0.0


def test_guessing_lowers_score_for_same_evidence(monkeypatch):
    """同样答对时，考虑「蒙对」会把证据打折，估计更低。"""
    def score(rate):
        monkeypatch.setattr(adaptive, "GUESS_RATE", rate)
        sess = adaptive.AdaptiveSession(id="x")
        _apply(sess, [(10, "correct")] * 3)
        return sess.score

    assert score(0.12) < score(0.0)


def test_interval_has_between_form_floor():
    """换题方差下限保证区间不会随着答题增多收缩到不合理的小。"""
    sess = adaptive.AdaptiveSession(id="x")
    _apply(sess, [(5, "correct")] * 40)
    lo, hi = adaptive._progress(sess)["score_interval"]
    assert hi - lo >= int(2 * 1.96 * adaptive.FORM_SD) - 2


def test_interval_contains_estimate_and_narrows():
    sess = adaptive.AdaptiveSession(id="x")
    _apply(sess, [(5, "correct")])
    first = adaptive._progress(sess)["score_interval"]
    assert first[0] <= round(sess.score) <= first[1]

    # 继续在同难度题上作答，后验信息增加，区间应单调变窄
    _apply(sess, [(5, "correct")] * 15)
    later = adaptive._progress(sess)["score_interval"]
    assert (later[1] - later[0]) < (first[1] - first[0])
    assert later[0] <= round(sess.score) <= later[1]


# ---------- 自适应选题与探顶 ----------

def test_first_question_is_high_frequency_warmup():
    for seed in range(20):
        sess = adaptive.AdaptiveSession(id=str(seed), rng=random.Random(seed))
        sess.current = adaptive._make_next(sess)
        assert sess.current["level"] in (1, 2)


def test_probe_starts_after_four_correct():
    sess = adaptive.AdaptiveSession(id="x", rng=random.Random(1))
    sess.current = adaptive._make_next(sess)
    for _ in range(4):
        q = sess.current
        adaptive.submit_answer(sess, q["correct_index"], False)
    assert sess.streak == 4
    assert sess.probe_remaining == 6
    assert sess.current["level"] >= adaptive._base_level(sess) + 3


def test_probe_ends_on_wrong_answer():
    sess = adaptive.AdaptiveSession(id="x", rng=random.Random(2))
    sess.current = adaptive._make_next(sess)
    for _ in range(4):
        q = sess.current
        adaptive.submit_answer(sess, q["correct_index"], False)
    assert sess.probe_remaining == 6
    q = sess.current
    adaptive.submit_answer(sess, None, True)
    assert sess.probe_remaining == 0
    assert sess.probes_used == 1
    assert sess.last_probe_failed is True


def test_probe_can_retrigger_after_cooldown():
    """首次探顶结束后，后程再连对 4 题仍能探顶（旧实现 6 题后永久失去机会）。"""
    sess = adaptive.AdaptiveSession(id="x", rng=random.Random(2))
    sess.current = adaptive._make_next(sess)
    for _ in range(4):
        q = sess.current
        adaptive.submit_answer(sess, q["correct_index"], False)
    assert sess.probe_remaining == 6
    adaptive.submit_answer(sess, None, True)  # 第一次探顶失败
    assert sess.probes_used == 1

    end_n = sess.last_probe_end_n
    # 冷却期内继续作答，不触发新的探顶
    while sess.total < end_n + adaptive.PROBE_COOLDOWN:
        q = sess.current
        adaptive.submit_answer(sess, q["correct_index"], False)
    assert sess.probes_used == 1

    # 冷却结束后再连对 4 题 → 第二次探顶
    for _ in range(4):
        q = sess.current
        adaptive.submit_answer(sess, q["correct_index"], False)
    assert sess.probes_used == 1  # 探顶进行中，尚未结束
    assert sess.probe_remaining > 0


def test_probe_count_is_capped():
    sess = adaptive.AdaptiveSession(id="x", rng=random.Random(3))
    sess.current = adaptive._make_next(sess)
    for _ in range(200):
        if sess.finished:
            break
        q = sess.current
        adaptive.submit_answer(sess, q["correct_index"], False)
    assert sess.probes_used <= adaptive.MAX_PROBES


# ---------- 完整流程 ----------

def _run_flow(respond, max_questions=adaptive.MAX_QUESTIONS):
    sid, _, _ = adaptive.start_test()
    sess = adaptive.get_session(sid)
    while not sess.finished and sess.total < max_questions:
        choice, unknown = respond(sess.current)
        ans = adaptive.submit_answer(sess, choice, unknown)
        if ans["finished"]:
            return ans["result"]
    return adaptive.finish_test(sess)


def test_all_correct_flow_reaches_high_score():
    result = _run_flow(lambda q: (q["correct_index"], False))
    assert result["total"] == adaptive.MAX_QUESTIONS
    assert result["correct"] == adaptive.MAX_QUESTIONS
    assert result["score"] > 10000
    assert result["ready"] is True


def test_all_unknown_flow_scores_low():
    result = _run_flow(lambda q: (None, True))
    assert result["total"] == adaptive.MAX_QUESTIONS
    assert result["unknown"] == adaptive.MAX_QUESTIONS
    assert result["score"] < 1000


def test_finish_is_idempotent():
    sid, _, _ = adaptive.start_test()
    sess = adaptive.get_session(sid)
    first = adaptive.finish_test(sess)
    second = adaptive.finish_test(sess)
    assert first == second


def test_feedback_exposes_real_gloss_when_answer_is_none_of_above():
    """正确答案是「以上都不对」时，反馈里仍要给出该词的真实含义。"""
    rng = random.Random(0)
    q = None
    for _ in range(300):
        q = adaptive._make_question(10, rng, set())
        if q["correct_index"] == 3:
            break
    assert q is not None and q["correct_index"] == 3

    sess = adaptive.AdaptiveSession(id="x", rng=rng)
    sess.current = q
    ans = adaptive.submit_answer(sess, 0, False)
    fb = ans["feedback"]
    assert fb["correct_gloss"] == adaptive.NONE_OF_ABOVE
    assert fb["word_gloss"] == q["gloss"]
    assert fb["word_gloss"] != adaptive.NONE_OF_ABOVE


def test_classic_feedback_also_has_word_gloss():
    """经典算法统一带 word_gloss，前端无需按算法分支。"""
    # 正确项可能是「以上都不对」（25%），那种情况下 word_gloss 是词的真实释义，
    # 与 correct_gloss 不同；这里取一道正确释义在选项里的题来断言相等。
    for _ in range(40):
        sid, _, _ = vocab.start_test()
        sess = vocab.get_session(sid)
        if sess.current["correct_index"] != 3:
            break
    ans = vocab.submit_answer(sess, sess.current["correct_index"], False)
    assert ans["feedback"]["word_gloss"] == ans["feedback"]["correct_gloss"]


# ---------- 路由开关 ----------

def test_answer_log_records_estimation_fields(monkeypatch, tmp_path):
    """日志要能支撑回放与标定：版本、题型、耗时、不确定度都要有。"""
    import json

    from app.config import settings

    log = tmp_path / "vocab_sessions.jsonl"
    monkeypatch.setattr(settings, "vocab_log_path", str(log))
    sid, _, _ = adaptive.start_test(user_id="u1")
    sess = adaptive.get_session(sid)
    q = sess.current
    adaptive.submit_answer(sess, q["correct_index"], False)
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert rec["algo"] == "adaptive"
    assert rec["algo_version"] == adaptive.ALGO_VERSION
    assert rec["user_id"] == "u1"
    assert rec["include_correct"] is (q["correct_index"] != 3)
    assert rec["elapsed_ms"] is None
    assert isinstance(rec["se"], int)


def test_router_start_adaptive_creates_adaptive_session():
    resp = vocab_router.start(vocab_router.StartIn(algo="adaptive"), user_id="")
    assert resp["algo"] == "adaptive"
    sid = resp["session_id"]
    sess = adaptive.get_session(sid)
    assert sess is not None
    assert vocab.get_session(sid) is None
    assert len(resp["question"]["options"]) == 4
    assert resp["question"]["options"][3] == adaptive.NONE_OF_ABOVE


def test_router_adaptive_logs_dual_engine_under_adaptive_name(monkeypatch, tmp_path):
    """adaptive 入口改用二维估计后，日志要保留 algo=adaptive 与 α 字段。"""
    import json

    from app.config import settings

    log = tmp_path / "vocab_sessions.jsonl"
    monkeypatch.setattr(settings, "vocab_log_path", str(log))
    resp = vocab_router.start(vocab_router.StartIn(algo="adaptive"), user_id="u1")
    sid = resp["session_id"]
    sess = adaptive.get_session(sid)
    q = sess.current
    vocab_router.answer(vocab_router.AnswerIn(
        session_id=sid, choice=q["correct_index"], unknown=False
    ))
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert rec["algo"] == "adaptive"
    assert rec["algo_version"] == adaptive.ALGO_VERSION
    assert "alpha" in rec


def test_router_answer_and_finish_dispatch_by_session():
    resp = vocab_router.start(vocab_router.StartIn(algo="adaptive"), user_id="")
    sid = resp["session_id"]
    ans = vocab_router.answer(vocab_router.AnswerIn(session_id=sid, choice=0, unknown=False))
    assert ans["feedback"]["response"] in {"correct", "wrong"}
    assert ans["score"] is not None
    fin = vocab_router.finish(vocab_router.FinishIn(session_id=sid))
    assert fin["finished"] is True
    assert "result" in fin


def test_router_default_algo_is_adaptive():
    """classic 已从前端隐藏，服务端未指定 algo 时默认 adaptive。"""
    resp = vocab_router.start(None, user_id="")
    assert resp["algo"] == "adaptive"
    assert adaptive.get_session(resp["session_id"]) is not None


def test_router_accepts_classic_explicitly():
    """classic 仍可通过接口显式使用，用于基线与历史对照。"""
    resp = vocab_router.start(vocab_router.StartIn(algo="classic"), user_id="")
    assert resp["algo"] == "classic"
    assert vocab.get_session(resp["session_id"]) is not None


def test_router_default_algo_is_classic(monkeypatch):
    monkeypatch.setattr(vocab_router.settings, "vocab_algo", "classic")
    resp = vocab_router.start(None, user_id="")
    assert resp["algo"] == "classic"
    assert vocab.get_session(resp["session_id"]) is not None


def test_router_accepts_legacy_eudic_alias():
    """算法改名前的客户端/本地缓存仍会传 "eudic"，路由应归一化为 adaptive。"""
    resp = vocab_router.start(vocab_router.StartIn(algo="eudic"), user_id="")
    assert resp["algo"] == "adaptive"
    assert adaptive.get_session(resp["session_id"]) is not None


def test_router_rejects_unknown_algo():
    with pytest.raises(HTTPException) as exc:
        vocab_router.start(vocab_router.StartIn(algo="nope"))
    assert exc.value.status_code == 400


# ---------- 二维 (θ, α) 估计 ----------

def _simulate_2d(theta: float, alpha: float, n: int = 120, seed: int = 0):
    """按已知 (θ, α) 在 θ 附近的多个档位上生成作答。"""
    rng = random.Random(seed)
    sess = adaptive.AdaptiveSession(id="x", rng=rng)
    base = int(theta // adaptive.LEVEL_WIDTH)
    for _ in range(n):
        level = max(0, min(24, base + rng.choice([-4, -3, -2, -1, 0, 1, 2, 3, 4])))
        b = adaptive.LEVEL_WIDTH * level + adaptive.LEVEL_OFFSET
        p = adaptive.sigmoid(alpha * (theta - b) / adaptive.SCALE)
        prob = adaptive.GUESS_RATE + (1 - adaptive.GUESS_RATE) * p
        r = rng.random()
        outcome = "correct" if r < prob else ("unknown" if r < prob + 0.08 else "wrong")
        adaptive._update_score(
            sess,
            {"level": level, "rank": level * 1000 + 1, "correct_index": 0},
            outcome,
        )
    return sess


@pytest.mark.parametrize(
    "theta,alpha",
    [(5000, 0.5), (12000, 1.0), (18000, 1.6)],
)
def test_recovers_theta_and_alpha(theta, alpha):
    sess = _simulate_2d(theta, alpha)
    assert abs(sess.score - theta) < 1500
    assert abs(sess.alpha - alpha) < 0.5


def test_flat_curve_has_larger_area_at_low_ability():
    """θ 较低时，曲线越平缓（α 小），词汇量面积越大。"""
    flat = adaptive._vocab_area(3000, 0.5)
    steep = adaptive._vocab_area(3000, 2.0)
    assert flat > steep


def test_vocab_interval_contains_point_estimate():
    sess = _simulate_2d(10000, 1.0, n=60)
    lo, hi = adaptive._vocab_interval(sess)
    area = adaptive._vocab_area(sess.score, sess.alpha)
    assert lo <= area <= hi
    assert lo < hi


def test_progress_exposes_alpha_and_area():
    sess = adaptive.AdaptiveSession(id="x")
    adaptive._update_score(
        sess, {"level": 10, "rank": 10001, "correct_index": 0}, "correct"
    )
    prog = adaptive._progress(sess)
    assert prog["alpha"] > 0
    assert prog["vocab_size"] > 0
    assert prog["score"] is not None


def test_router_adaptive2_is_alias_of_adaptive():
    """adaptive2 已并入 adaptive：路由归一化，历史与日志都写 adaptive。"""
    resp = vocab_router.start(vocab_router.StartIn(algo="adaptive2"), user_id="")
    assert resp["algo"] == "adaptive"
    sess = adaptive.get_session(resp["session_id"])
    assert sess is not None
    assert len(resp["question"]["options"]) == 4


def test_finish_is_idempotent_and_result_has_alpha():
    sid, _, _ = adaptive.start_test()
    sess = adaptive.get_session(sid)
    adaptive.submit_answer(sess, sess.current["correct_index"], False)
    first = adaptive.finish_test(sess)
    second = adaptive.finish_test(sess)
    assert first == second
    assert "alpha" in first and "vocab_interval" in first
