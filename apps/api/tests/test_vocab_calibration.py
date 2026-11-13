"""题库标定（issue #40）的清洗与拟合测试。"""
import math

from app.services import vocab_calibration as cal


def _rec(ts, response="correct", include_correct=True, rank=5000, word="abandon"):
    return {
        "ts": ts,
        "session": "s",
        "word": word,
        "rank": rank,
        "response": response,
        "include_correct": include_correct,
    }


def test_clean_sessions_drops_bulk_day_bots_and_short():
    day2 = 86400 * 2
    # 批量模拟日：一天 150 个 session
    bulk = {
        f"bulk{i}": [_rec(1000 + j, "correct") for j in range(30)]
        for i in range(150)
    }
    # 正常日：一个真人 session（有快有慢、答案多样）
    good = [
        _rec(day2 + j * 3, "correct" if j % 3 else "wrong", rank=500 + j * 100)
        for j in range(30)
    ]
    sessions = {
        **bulk,
        "good": good,
        "bot": [_rec(day2 + 3000 + j * 0.001) for j in range(30)],
        "short": [_rec(day2 + 4000 + j) for j in range(5)],
        "same": [_rec(day2 + 5000 + j, "correct") for j in range(30)],
    }
    kept, report = cal.clean_sessions(sessions)
    assert set(kept) == {"good"}
    assert report["bulk_day"] == 150
    assert report["bot_burst"] == 1
    assert report["too_short"] == 1
    assert report["single_response"] == 1


def test_observations_only_use_standard_format():
    sessions = {
        "s": [
            _rec(0, "correct", include_correct=True, word="a"),
            _rec(1, "wrong", include_correct=True, word="b"),
            _rec(2, "correct", include_correct=False, word="c"),
            _rec(3, "unknown", include_correct=True, word="d"),
        ]
    }
    obs = cal.observations(sessions)
    assert [o[1] for o in obs] == ["a", "b", "d"]
    assert [o[2] for o in obs] == [1, 0, 0]


def test_fit_recovers_synthetic_theta():
    """合成数据（真实 θ 已知）上，2PL 拟合的平均误差应在 1,000 分以内。"""
    obs, truth = cal.synthetic_observations(n_sessions=60, n_items=80, seed=3)
    params = cal.fit(obs, model="2pl", epochs=400)
    errs = [
        abs(params["theta"][sid] - truth["theta"][sid])
        for sid in truth["theta"]
        if sid in params["theta"]
    ]
    assert sum(errs) / len(errs) < 1000


def test_fit_1pl_also_works():
    obs, truth = cal.synthetic_observations(n_sessions=50, n_items=60, seed=5)
    params = cal.fit(obs, model="1pl", epochs=400)
    # 1PL 忽略了个体区分度差异，误差会比 2PL 大，但不应发散
    errs = [
        abs(params["theta"][sid] - truth["theta"][sid])
        for sid in truth["theta"]
        if sid in params["theta"]
    ]
    assert sum(errs) / len(errs) < 2500
    assert all(math.isfinite(t) for t in params["theta"].values())


def test_readiness_requires_enough_items():
    params = {
        "items": {
            f"w{i}": {"b": 1000.0 + i, "a": 0.0004, "n": 5}
            for i in range(500)
        }
    }
    report = cal.readiness(params, sessions=100, obs=5000)
    assert report["ready"] is False
    assert report["calibrated_items"] == 0


def test_log_likelihood_is_finite():
    obs, _ = cal.synthetic_observations(n_sessions=10, n_items=20, seed=1)
    params = cal.fit(obs, model="2pl", epochs=20)
    ll = cal.log_likelihood(obs, params)
    assert math.isfinite(ll) and ll < 0
