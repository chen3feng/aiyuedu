"""词频题库 CAT 的单元测试。

覆盖：题库结构与选题、3PL 后验更新、顺序不变性、完整流程、路由开关。
运行：uv run --directory apps/api pytest tests/test_vocab_cat.py -q
"""
import pytest

from app.config import settings
from app.routers import vocab as vocab_router
from app.services import vocab_cat as cat
from app.services import vocab_tests


def _apply(sess: cat.CatSession, items) -> None:
    for b, a, outcome in items:
        cat._update_score(sess, {"b": b, "a": a}, outcome)


def test_bank_is_sorted_and_covers_all_levels():
    bank = cat._bank()
    assert len(bank) > 10000
    ranks = [it["rank"] for it in bank]
    assert ranks == sorted(ranks)
    levels = {(it["rank"] - 1) // 1000 for it in bank}
    assert levels >= set(range(0, 20))


def test_first_question_is_high_frequency():
    for seed in range(10):
        sid, question, _ = cat.start_test()
        sess = cat.get_session(sid)
        assert question["level"] in (0, 1, 2)
        assert 800 <= sess.current["rank"] <= 2200


def test_question_has_four_options_and_params():
    sid, question, _ = cat.start_test()
    sess = cat.get_session(sid)
    assert len(question["options"]) == 4
    assert question["options"][3] == "以上都不对"
    assert 0 <= sess.current["correct_index"] < 4
    assert sess.current["b"] > 0
    assert sess.current["a"] > 0


def test_selection_follows_ability():
    sess = cat.CatSession(id="x")
    sess.total = 1
    sess.score = 12000.0
    item = cat._pick_item(sess)
    assert 11000 <= item["b"] <= 13000


def test_posterior_score_is_order_invariant():
    items = [
        (3000, 1 / 2500, "correct"),
        (9000, 1 / 2500, "wrong"),
        (6000, 1 / 2500, "unknown"),
        (12000, 1 / 2500, "correct"),
    ] * 6
    a = cat.CatSession(id="a")
    b = cat.CatSession(id="b")
    _apply(a, items)
    _apply(b, list(reversed(items)))
    assert a.score == pytest.approx(b.score, abs=1e-6)
    assert a.se == pytest.approx(b.se, abs=1e-6)


def test_correct_raises_and_wrong_lowers():
    correct = cat.CatSession(id="c")
    wrong = cat.CatSession(id="w")
    _apply(correct, [(10000, 1 / 2500, "correct")])
    _apply(wrong, [(10000, 1 / 2500, "wrong")])
    assert correct.score > wrong.score


def _run_flow(respond):
    sid, _, _ = cat.start_test()
    sess = cat.get_session(sid)
    while not sess.finished:
        choice, unknown = respond(sess.current)
        ans = cat.submit_answer(sess, choice, unknown)
        if ans["finished"]:
            return ans["result"]
        assert ans["question"] is not None
    return cat.finish_test(sess)


def test_all_correct_flow_reaches_high_score():
    result = _run_flow(lambda q: (q["correct_index"], False))
    assert result["total"] == cat.MAX_QUESTIONS
    assert result["correct"] == cat.MAX_QUESTIONS
    assert result["score"] > 10000


def test_all_unknown_flow_scores_low():
    result = _run_flow(lambda q: (None, True))
    assert result["total"] == cat.MAX_QUESTIONS
    assert result["unknown"] == cat.MAX_QUESTIONS
    assert result["score"] < 1000


def test_router_start_cat_creates_cat_session():
    resp = vocab_router.start(vocab_router.StartIn(algo="cat"), user_id="")
    assert resp["algo"] == "cat"
    sid = resp["session_id"]
    assert cat.get_session(sid) is not None
    assert len(resp["question"]["options"]) == 4


def test_cat_result_records_algo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vocab_tests_path", str(tmp_path / "tests.json"))
    sid, _, _ = cat.start_test(user_id="u1")
    sess = cat.get_session(sid)
    cat.submit_answer(sess, sess.current["correct_index"], False)
    cat.finish_test(sess)
    items = vocab_tests.list_tests("u1")
    assert len(items) == 1
    assert items[0]["algo"] == "cat"


def test_answer_log_records_estimation_fields(tmp_path, monkeypatch):
    import json

    log = tmp_path / "vocab_sessions.jsonl"
    monkeypatch.setattr(settings, "vocab_log_path", str(log))
    sid, _, _ = cat.start_test(user_id="u1")
    sess = cat.get_session(sid)
    cat.submit_answer(sess, sess.current["correct_index"], False)
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert rec["algo"] == "cat"
    assert rec["algo_version"] == cat.ALGO_VERSION
    assert rec["user_id"] == "u1"
    assert rec["include_correct"] is True
    assert rec["elapsed_ms"] is None
    assert isinstance(rec["se"], int)
    assert rec["b"] > 0 and rec["a"] > 0
