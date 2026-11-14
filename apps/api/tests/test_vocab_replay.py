"""离线回放脚本的测试：会话聚合、过滤与估计器回放。

运行：uv run --directory apps/api pytest -q
"""
import importlib.util
import json
from pathlib import Path

import pytest

from app.services import vocab

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay_vocab_algorithms.py"
_spec = importlib.util.spec_from_file_location("replay_vocab_algorithms", _SCRIPT)
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)


def _write_log(path: Path, rows: list[dict]) -> Path:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _rows(session: str, n: int, user: str = "", ts: float = 1000.0) -> list[dict]:
    return [
        {"session": session, "n": i + 1, "rank": 100 + i, "response": "unknown",
         "word": f"w{session}{i}", "user_id": user, "ts": ts + i, "algo": "classic"}
        for i in range(n)
    ]


def test_load_sessions_filters_and_sorts(tmp_path):
    log = _write_log(
        tmp_path / "log.jsonl",
        # 乱序写入，检查按 n 排序
        list(reversed(_rows("short", 10, user="u")))
        + list(reversed(_rows("real", 25, user="u")))
        + list(reversed(_rows("anon", 25, user="")))
        + list(reversed(_rows("old", 25, user="u", ts=100.0))),
    )

    sessions = replay.load_sessions(log, min_answers=20)
    # short 题量不足、anon 默认排除
    assert {s["session"] for s in sessions} == {"old", "real"}

    sessions = replay.load_sessions(log, min_answers=20, since=500.0)
    assert [s["session"] for s in sessions] == ["real"]

    sessions = replay.load_sessions(log, min_answers=20, include_anonymous=True, since=500.0)
    assert {s["session"] for s in sessions} == {"real", "anon"}

    real = next(s for s in sessions if s["session"] == "real")
    assert [rank for rank, _, _ in real["seq"]] == [100 + i for i in range(25)]
    assert all(resp == "unknown" for _, resp, _ in real["seq"])


def test_load_sessions_caps_answer_count(tmp_path):
    log = _write_log(tmp_path / "log.jsonl", _rows("long", 90, user="u"))
    sessions = replay.load_sessions(log, min_answers=20, max_answers=80)
    assert sessions[0]["seq"].__len__() == 80


def test_replay_classic_perfect_is_max():
    # 每段 5 题全对 → 每段认识率 1，猜测校正后仍是 1 → 25,000
    seq = []
    for i in range(vocab.N_BANDS):
        for _ in range(5):
            seq.append((vocab.BANDS[i] + 10, "correct", "w"))
    assert replay.replay_classic(seq) == pytest.approx(vocab.MAX_VOCAB, abs=1.0)


def test_replay_estimators_are_deterministic_and_in_range():
    seq = [(100 + i * 500, "correct" if i % 3 else "unknown", f"w{i}") for i in range(50)]
    first = replay.replay_session(seq)
    second = replay.replay_session(seq)
    assert first == second
    for algo in replay.ALGOS:
        assert 0 <= first[algo] <= vocab.MAX_VOCAB
    assert 0 < first["alpha2"] < 5


def test_replay_session_respects_algo_selection():
    seq = [(100, "correct", "w"), (200, "unknown", "w2")]
    out = replay.replay_session(seq, algos=("adaptive", "cat"))
    assert set(out) == {"adaptive", "cat"}


def test_parse_since_accepts_date_and_epoch():
    assert replay._parse_since("2026-11-14") > 1_700_000_000
    assert replay._parse_since("1794622993.897") == pytest.approx(1794622993.897)
