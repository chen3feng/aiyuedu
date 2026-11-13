"""双参数自适应（θ + α）的单元测试（issue #41）。"""
import random

import pytest

from app.routers import vocab as vocab_router
from app.services import vocab_adaptive as adaptive
from app.services import vocab_adaptive2 as adaptive2


def _simulate(theta: float, alpha: float, n: int = 120, seed: int = 0):
    """按已知 (θ, α) 在 θ 附近的多个档位上生成作答。"""
    rng = random.Random(seed)
    sess = adaptive2.Adaptive2Session(id="x", rng=rng)
    base = int(theta // adaptive2.LEVEL_WIDTH)
    for _ in range(n):
        level = max(0, min(24, base + rng.choice([-4, -3, -2, -1, 0, 1, 2, 3, 4])))
        b = adaptive2.LEVEL_WIDTH * level + adaptive2.LEVEL_OFFSET
        p = adaptive.sigmoid(alpha * (theta - b) / adaptive2.SCALE)
        prob = adaptive2.GUESS_RATE + (1 - adaptive2.GUESS_RATE) * p
        r = rng.random()
        outcome = "correct" if r < prob else ("unknown" if r < prob + 0.08 else "wrong")
        adaptive2._update_score(
            sess, {"level": level, "rank": level * 1000 + 1, "correct_index": 0}, outcome
        )
    return sess


@pytest.mark.parametrize(
    "theta,alpha",
    [(5000, 0.5), (12000, 1.0), (18000, 1.6)],
)
def test_recovers_theta_and_alpha(theta, alpha):
    sess = _simulate(theta, alpha)
    assert abs(sess.score - theta) < 1500
    assert abs(sess.alpha - alpha) < 0.5


def test_flat_curve_has_larger_area_at_low_ability():
    """θ 较低时，曲线越平缓（α 小），词汇量面积越大。"""
    flat = adaptive2._vocab_area(3000, 0.5)
    steep = adaptive2._vocab_area(3000, 2.0)
    assert flat > steep


def test_vocab_interval_contains_point_estimate():
    sess = _simulate(10000, 1.0, n=60)
    lo, hi = adaptive2._vocab_interval(sess)
    area = adaptive2._vocab_area(sess.score, sess.alpha)
    assert lo <= area <= hi
    assert lo < hi


def test_progress_exposes_alpha_and_area():
    sess = adaptive2.Adaptive2Session(id="x")
    adaptive2._update_score(sess, {"level": 10, "rank": 10001, "correct_index": 0}, "correct")
    prog = adaptive2._progress(sess)
    assert prog["alpha"] > 0
    assert prog["vocab_size"] > 0
    assert prog["score"] is not None


def test_router_start_adaptive2_creates_session():
    resp = vocab_router.start(vocab_router.StartIn(algo="adaptive2"), user_id="")
    assert resp["algo"] == "adaptive2"
    sid = resp["session_id"]
    assert adaptive2.get_session(sid) is not None
    assert adaptive.get_session(sid) is None
    assert len(resp["question"]["options"]) == 4


def test_finish_is_idempotent_and_result_has_alpha():
    sid, _, _ = adaptive2.start_test()
    sess = adaptive2.get_session(sid)
    adaptive2.submit_answer(sess, sess.current["correct_index"], False)
    first = adaptive2.finish_test(sess)
    second = adaptive2.finish_test(sess)
    assert first == second
    assert "alpha" in first and "vocab_interval" in first
