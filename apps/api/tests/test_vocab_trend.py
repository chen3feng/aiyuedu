"""多次测试趋势与历史先验（issue #42）的测试。"""
import time

import pytest

from app.config import settings
from app.services import vocab_adaptive as adaptive
from app.services import vocab_adaptive2 as adaptive2
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


def test_adaptive_start_uses_history_prior(store):
    now = time.time()
    _add("u1", now - 86400, 12000, 12000)
    sid, _, _ = adaptive.start_test(user_id="u1")
    sess = adaptive.get_session(sid)
    adaptive._refresh_moments(sess)
    assert sess.score == pytest.approx(12000, abs=1500)


def test_adaptive2_start_uses_history_prior(store):
    now = time.time()
    _add("u1", now - 86400, 15000, 15000, algo="adaptive2")
    sid, _, _ = adaptive2.start_test(user_id="u1")
    sess = adaptive2.get_session(sid)
    adaptive2._refresh_moments(sess)
    assert sess.score == pytest.approx(15000, abs=2000)


def test_prior_can_be_disabled(store, monkeypatch):
    now = time.time()
    _add("u1", now - 86400, 20000, 20000)
    monkeypatch.setattr(settings, "vocab_history_prior", False)
    sid, _, _ = adaptive.start_test(user_id="u1")
    sess = adaptive.get_session(sid)
    adaptive._refresh_moments(sess)
    assert sess.score < 5000   # 回到默认先验（均值 1000）


def test_router_trend_endpoint(store):
    from app.routers import vocab as vocab_router

    now = time.time()
    _add("u1", now - 30 * 86400, 8000, 8000)
    _add("u1", now, 10000, 10000)
    resp = vocab_router.trend(user_id="u1")
    assert resp["n"] == 2
    assert resp["slope_per_month"] is not None
