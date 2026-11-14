"""可控仿真脚本的测试：真值计算与一次完整会话。

运行：uv run --directory apps/api pytest -q
"""
import importlib.util
from pathlib import Path

import pytest

from app.services import vocab

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "simulate_vocab_algorithms.py"
_spec = importlib.util.spec_from_file_location("simulate_vocab_algorithms", _SCRIPT)
sim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim)


def test_p_know_is_monotonic_in_theta_and_rank():
    assert sim.p_know(5000, 5000, 2500) == pytest.approx(0.5)
    assert sim.p_know(8000, 5000, 2500) > sim.p_know(5000, 5000, 2500)
    assert sim.p_know(5000, 5000, 2500) > sim.p_know(5000, 8000, 2500)


def test_area_truth_increases_with_theta():
    values = [sim.area_truth(t, 2500) for t in (3000, 9000, 15000, 21000)]
    assert values == sorted(values)
    assert all(0 < v < vocab.MAX_VOCAB for v in values)


def test_classic_truth_is_close_to_area_truth():
    # 两个真值口径不同，但数量级应一致（分段加权 vs 25 档面积）
    for theta in (6000, 12000, 18000):
        area = sim.area_truth(theta, 2500)
        classic = sim.classic_truth(theta, 2500)
        assert abs(area - classic) / area < 0.10


@pytest.mark.parametrize("alg", sim.ALGOS)
def test_run_session_returns_bounded_estimate(alg):
    import random

    est, questions = sim.run_session(alg, 12000, 2500, 0.48, random.Random(0))
    assert 0 <= est <= vocab.MAX_VOCAB
    assert 20 <= questions <= 80
    if alg == "classic":
        assert questions == 50


def test_simulate_reports_requested_algos():
    result = sim.simulate(12000, sessions=1, algos=("adaptive", "cat"),
                          scale=2500, guess_prop=0.48, seed=0)
    assert result["theta"] == 12000
    assert set(result["algos"]) == {"adaptive", "cat"}
    for s in result["algos"].values():
        assert s["questions"] > 0
        assert s["truth"] == 12000
