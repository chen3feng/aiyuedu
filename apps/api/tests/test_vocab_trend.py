"""多次测试趋势与历史成绩用法（issue #42）的测试。"""
import time

import pytest

from app.config import settings
from app.services import vocab_adaptive as adaptive
from app.services import vocab_adaptive2 as adaptive2
from app.services import vocab_cat as cat
from app.services import vocab_tests
from app.services import vocab_trend


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "vocab_tests.json"
    monkeypatch.setattr(settings, "vocab_tests_path", str(path))
    return path


def _add(user_id, ts, score, vocab_size, algo="adaptive", se=700):
    vocab_tests.add(user_id, {
        "ts": ts,
        "algo": algo,
        "score": score,
        "vocab_size": vocab_size,
        "se": se,
        "total": 60,
        "correct": 40,
        "wrong": 10,
        "unknown": 10,
    })


def test_trend_detects_upward_change(store):
    now = time.time()
    for i in range(6):
        _add("u1", now - (60 - i * 12) * 86400, 8000 + i * 800, 8000 + i * 800)
    result = vocab_trend.trend("u1")
    assert result["algo"] == "adaptive"
    assert result["n"] == 6
    assert result["significant"] is True
    assert result["slope_per_month"] > 0
    assert result["ci"][0] > 0


def test_trend_flat_noise_not_significant(store):
    now = time.time()
    values = [10000, 10600, 9800, 10300, 9900, 10100]
    for i, v in enumerate(values):
        _add("u1", now - (60 - i * 12) * 86400, v, v)
    result = vocab_trend.trend("u1")
    assert result["significant"] is False
    assert result["ci"][0] <= 0 <= result["ci"][1]


def test_trend_requires_two_dates(store):
    now = time.time()
    _add("u1", now, 9000, 9000)
    result = vocab_trend.trend("u1")
    assert result["n"] == 1
    assert result["significant"] is False
    assert result["slope_per_month"] is None


def test_trend_uses_latest_algo(store):
    now = time.time()
    _add("u1", now - 20 * 86400, 8000, 8000, algo="cat")
    _add("u1", now - 10 * 86400, 9000, 9000, algo="cat")
    _add("u1", now, 12000, 12000, algo="adaptive2")
    result = vocab_trend.trend("u1")
    assert result["algo"] == "adaptive2"
    assert result["n"] == 1


def test_history_prior_uses_latest_score(store):
    now = time.time()
    _add("u1", now - 30 * 86400, 9000, 9000)
    _add("u1", now - 86400, 12000, 12000)
    prior = vocab_trend.history_prior("u1", "adaptive")
    assert prior is not None
    assert prior["mean"] == 12000
    assert prior["sd"] >= vocab_trend.BASE_SD


def test_history_prior_ignores_old_and_other_algo(store):
    now = time.time()
    _add("u1", now - 400 * 86400, 9000, 9000)
    assert vocab_trend.history_prior("u1", "adaptive") is None
    _add("u2", now, 9000, 9000, algo="cat")
    assert vocab_trend.history_prior("u2", "adaptive") is None


def test_adaptive_start_level_uses_history(store):
    """历史成绩只决定起点：首题档位 + 以历史为中心的宽先验。"""
    now = time.time()
    _add("u1", now - 86400, 12000, 12000)
    sid, question, _ = adaptive.start_test(user_id="u1")
    sess = adaptive.get_session(sid)
    assert sess.start_level == 12
    assert question["level"] == 12
    adaptive._refresh_moments(sess)
    # 先验跟着历史走（12 档 ≈ 12,100 分），但 sd ≥ 4,000，数据仍能很快主导。
    assert 11000 < sess.score < 13000
    assert sess.log_post == pytest.approx(
        adaptive._prior_log_post(12100, adaptive.HISTORY_PRIOR_MIN_SD)
    )


def test_adaptive_second_question_keeps_history_level(store):
    """首题答完后不应掉回默认均值档位（旧版历史只进首题，12 档会塌到 3 档）。"""
    now = time.time()
    _add("u1", now - 86400, 16000, 16000)
    sid, _, _ = adaptive.start_test(user_id="u1")
    sess = adaptive.get_session(sid)
    adaptive.submit_answer(sess, None, True)
    assert sess.current["level"] >= 9


def test_adaptive2_start_level_uses_history(store):
    now = time.time()
    _add("u1", now - 86400, 15000, 15000, algo="adaptive2")
    sid, question, _ = adaptive2.start_test(user_id="u1")
    sess = adaptive2.get_session(sid)
    assert sess.start_level == 15
    assert question["level"] == 15
    adaptive2._refresh_moments(sess)
    assert 13500 < sess.score < 16500
    assert sess.log_post == pytest.approx(
        adaptive2._prior_log_post(15100, adaptive.HISTORY_PRIOR_MIN_SD)
    )


def test_adaptive2_second_question_keeps_history_level(store):
    now = time.time()
    _add("u1", now - 86400, 16000, 16000, algo="adaptive2")
    sid, _, _ = adaptive2.start_test(user_id="u1")
    sess = adaptive2.get_session(sid)
    adaptive2.submit_answer(sess, None, True)
    assert sess.current["level"] >= 9


def test_cat_start_level_is_capped(store):
    """CAT 历史起点封顶在 8 档，避免窄选题窗口锁死在高频段造成 runaway。"""
    now = time.time()
    _add("u1", now - 86400, 16000, 16000, algo="cat")
    sid, question, _ = cat.start_test(user_id="u1")
    sess = cat.get_session(sid)
    assert cat.MAX_HISTORY_START_LEVEL == 8
    assert sess.start_level == 8
    assert question["level"] == 8
    assert sess.log_post == pytest.approx(
        cat._dual._prior_log_post(8100, adaptive.HISTORY_PRIOR_MIN_SD)
    )
    cat.submit_answer(sess, None, True)
    assert 5000 <= sess.current["rank"] <= 11000


def test_cat_start_level_uses_lower_history(store):
    now = time.time()
    _add("u1", now - 86400, 5000, 5000, algo="cat")
    sid, question, _ = cat.start_test(user_id="u1")
    sess = cat.get_session(sid)
    assert sess.start_level == 5
    assert question["level"] == 5


def test_prior_can_be_disabled(store, monkeypatch):
    now = time.time()
    _add("u1", now - 86400, 20000, 20000)
    monkeypatch.setattr(settings, "vocab_history_prior", False)
    sid, question, _ = adaptive.start_test(user_id="u1")
    sess = adaptive.get_session(sid)
    assert sess.start_level is None
    assert question["level"] in (1, 2)   # 默认从 1–2 档起步
    adaptive._refresh_moments(sess)
    assert sess.score < 5000              # 默认先验（均值 1000）


def test_router_trend_endpoint(store):
    from app.routers import vocab as vocab_router

    now = time.time()
    _add("u1", now - 30 * 86400, 8000, 8000)
    _add("u1", now, 10000, 10000)
    resp = vocab_router.trend(user_id="u1")
    assert resp["n"] == 2
    assert resp["slope_per_month"] is not None


def _session(algo: str, total: int):
    from app.services import vocab as classic
    from app.services import vocab_cat as cat

    if algo == "classic":
        return classic.TestSession(id="s", user_id="u1", total=total)
    if algo == "adaptive":
        return adaptive.AdaptiveSession(id="s", user_id="u1", total=total)
    if algo == "adaptive2":
        return adaptive2.Adaptive2Session(id="s", user_id="u1", total=total)
    return cat.CatSession(id="s", user_id="u1", total=total)


@pytest.mark.parametrize("algo", ["classic", "adaptive", "adaptive2", "cat"])
def test_short_sessions_not_recorded(store, algo):
    """不足 20 题的测试不写入历史（否则短测试会把先验原样记成一次成绩）。"""
    from app.services import vocab as classic
    from app.services import vocab_cat as cat

    module = {
        "classic": classic,
        "adaptive": adaptive,
        "adaptive2": adaptive2,
        "cat": cat,
    }[algo]
    sess = _session(algo, total=19)
    module._record(sess)
    assert vocab_tests.count("u1") == 0
    assert sess.recorded is False


@pytest.mark.parametrize("algo", ["classic", "adaptive", "adaptive2", "cat"])
def test_full_sessions_recorded(store, algo):
    from app.services import vocab as classic
    from app.services import vocab_cat as cat

    module = {
        "classic": classic,
        "adaptive": adaptive,
        "adaptive2": adaptive2,
        "cat": cat,
    }[algo]
    sess = _session(algo, total=20)
    module._record(sess)
    records = vocab_tests.list_tests("u1")
    assert len(records) == 1
    assert records[0]["algo"] == algo
    assert records[0]["total"] == 20
    assert sess.recorded is True
