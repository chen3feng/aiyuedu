"""写作平台 service + router 的测试。

覆盖：
- split_sentences / count_words（含缩写、空行、引号）
- submit_essay 完整流程：mock ai.chat 返回有效 JSON → 报告合并 → 落盘
- AI 返回解析失败 → ai_used=False + reason 含原文片段
- AI RuntimeError → ai_used=False + reason 含错误
- 作文为空 → ValueError → router 翻译 422
- list_essays 按时间倒序
- get_essay / delete_essay 用户隔离
- router /writings/prompts 列题目

运行：uv run --directory apps/api pytest -q
"""
import json

import pytest

from app.services import prompts, writing
from app.routers import writing as writing_router


@pytest.fixture
def isolated_writings(tmp_path, monkeypatch):
    from app.config import settings

    path = tmp_path / "writings.json"
    monkeypatch.setattr(settings, "writings_path", str(path))
    return path


# ---------- 词数 ----------

def test_count_words_simple():
    assert writing.count_words("I walk in the fields.") == 5


def test_count_words_with_contractions():
    # can't / don't 不应被拆
    assert writing.count_words("I can't walk, don't run.") == 5


def test_count_words_empty():
    assert writing.count_words("") == 0
    assert writing.count_words("!!! ??? ...") == 0


# ---------- 题库 ----------

def test_list_prompts_returns_at_least_5():
    items = prompts.list_prompts()
    assert len(items) >= 5
    assert all("key" in p and "title_zh" in p and "target_words" in p for p in items)


def test_get_prompt_found_and_missing():
    p = prompts.get_prompt("autumn-fields")
    assert p is not None
    assert p["target_words"] >= 80
    assert prompts.get_prompt("nope") is None


# ---------- submit_essay ----------

def test_submit_essay_happy_path(isolated_writings, monkeypatch):
    """AI 返回有效 JSON → 报告合并 → 落盘 → 返回。"""
    fake_report = {
        "sentences": [
            {
                "index": 1,
                "original": "I walk in the fields.",
                "errors": [{"category": "tense", "explanation": "应用现在进行时", "fix": "I am walking"}],
                "corrected": "I am walking in the fields.",
                "polished": "I am walking through the fields.",
            }
        ],
        "summary_table": [
            {"category": "时态", "examples": ["I walk → I am walking"], "rule": "描述此刻正在发生的事用现在进行时"}
        ],
        "praise": "整体能逐句对应中文意思。",
    }
    monkeypatch.setattr(
        writing.ai, "chat",
        lambda *a, **k: json.dumps(fake_report, ensure_ascii=False),
    )
    essay = writing.submit_essay("u1", "autumn-fields", "I walk in the fields.")
    assert essay["prompt_key"] == "autumn-fields"
    assert essay["word_count"] == 5
    assert essay["ai_used"] is True
    assert essay["reason"] is None
    assert essay["report"]["praise"] == "整体能逐句对应中文意思。"
    # 落盘
    saved = json.loads(isolated_writings.read_text(encoding="utf-8"))
    assert "u1" in saved and essay["id"] in saved["u1"]


def test_submit_essay_ai_runtime_error(isolated_writings, monkeypatch):
    """AI 整体失败（RuntimeError）→ ai_used=False + reason 含错误。"""
    def boom(*a, **k):
        raise RuntimeError("AI 返回 401：Unauthorized")
    monkeypatch.setattr(writing.ai, "chat", boom)
    essay = writing.submit_essay("u1", "autumn-fields", "I walk in the fields.")
    assert essay["ai_used"] is False
    assert "401" in (essay["reason"] or "")
    assert essay["report"] == {"sentences": [], "summary_table": [], "praise": ""}
    # 作文仍落盘（前端可显示「批改失败，作文已保存」）
    assert essay["id"]


def test_submit_essay_ai_timeout_surfaces_reason(isolated_writings, monkeypatch):
    """AI 超时（httpx.TimeoutException 被 ai.chat 包成 RuntimeError）→ reason 可读。"""
    import httpx as _httpx
    def timeout(*a, **k):
        raise RuntimeError("AI 推理超时（>300s）：timed out")
    monkeypatch.setattr(writing.ai, "chat", timeout)
    essay = writing.submit_essay("u1", "autumn-fields", "I walk in the fields.")
    assert essay["ai_used"] is False
    assert "超时" in (essay["reason"] or "")


def test_submit_essay_ai_empty_content(isolated_writings, monkeypatch):
    """AI 返回空 → ai_used=False + reason 提示。"""
    monkeypatch.setattr(writing.ai, "chat", lambda *a, **k: "")
    essay = writing.submit_essay("u1", "autumn-fields", "Hello world.")
    assert essay["ai_used"] is False
    assert "空内容" in (essay["reason"] or "")


def test_submit_essay_ai_unparseable_json(isolated_writings, monkeypatch):
    """AI 返回非 JSON → ai_used=False + reason 含原文开头。"""
    monkeypatch.setattr(
        writing.ai, "chat",
        lambda *a, **k: "好的，我来帮你批改：\n这是一篇有趣的文章...",
    )
    essay = writing.submit_essay("u1", "autumn-fields", "Hello world.")
    assert essay["ai_used"] is False
    assert "无法解析" in (essay["reason"] or "")
    assert "好的" in (essay["reason"] or "")  # 原文片段


def test_submit_essay_ai_returns_garbage_inside_fence(isolated_writings, monkeypatch):
    """AI 把 JSON 包在 ```json``` 围栏里也能解析。"""
    payload = {"sentences": [], "summary_table": [], "praise": "不错"}
    fenced = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    monkeypatch.setattr(writing.ai, "chat", lambda *a, **k: fenced)
    essay = writing.submit_essay("u1", "autumn-fields", "Hello world.")
    assert essay["ai_used"] is True
    assert essay["report"]["praise"] == "不错"


def test_submit_essay_empty_body_raises(isolated_writings):
    with pytest.raises(ValueError, match="不能为空"):
        writing.submit_essay("u1", "autumn-fields", "")
    with pytest.raises(ValueError, match="不能为空"):
        writing.submit_essay("u1", "autumn-fields", "    \n\n  ")


def test_submit_essay_promptless_fallback(isolated_writings, monkeypatch):
    """prompt_key 为空 → 走自由写作；body_zh/title 留空仍工作。"""
    monkeypatch.setattr(writing.ai, "chat", lambda *a, **k: json.dumps(
        {"sentences": [], "summary_table": [], "praise": "加油"}, ensure_ascii=False))
    essay = writing.submit_essay("u1", None, "I am a student.")
    assert essay["prompt_key"] is None
    assert essay["ai_used"] is True


# ---------- list / get / delete ----------

def test_list_essays_sorted_by_time_desc(isolated_writings, monkeypatch):
    monkeypatch.setattr(writing.ai, "chat", lambda *a, **k: "{}")
    e1 = writing.submit_essay("u1", None, "First essay.")
    e2 = writing.submit_essay("u1", None, "Second essay.")
    e3 = writing.submit_essay("u1", None, "Third essay.")
    items = writing.list_essays("u1")
    assert [e["id"] for e in items] == [e3["id"], e2["id"], e1["id"]]


def test_list_essays_user_isolation(isolated_writings, monkeypatch):
    monkeypatch.setattr(writing.ai, "chat", lambda *a, **k: "{}")
    writing.submit_essay("u1", None, "User one.")
    writing.submit_essay("u2", None, "User two.")
    assert len(writing.list_essays("u1")) == 1
    assert len(writing.list_essays("u2")) == 1
    assert len(writing.list_essays("u3")) == 0  # 未见过的用户


def test_get_essay_user_isolation(isolated_writings, monkeypatch):
    monkeypatch.setattr(writing.ai, "chat", lambda *a, **k: "{}")
    e = writing.submit_essay("u1", None, "Hello.")
    assert writing.get_essay("u1", e["id"]) is not None
    assert writing.get_essay("u2", e["id"]) is None  # 别的用户取不到
    assert writing.get_essay("u1", "w-xxx") is None  # 不存在


def test_delete_essay(isolated_writings, monkeypatch):
    monkeypatch.setattr(writing.ai, "chat", lambda *a, **k: "{}")
    e = writing.submit_essay("u1", None, "Hello.")
    assert writing.delete_essay("u1", e["id"]) is True
    assert writing.get_essay("u1", e["id"]) is None
    # 再次删除 → False
    assert writing.delete_essay("u1", e["id"]) is False


# ---------- Router ----------

def test_router_list_prompts():
    resp = writing_router.list_prompts()
    assert "items" in resp
    assert len(resp["items"]) >= 5


def test_router_submit_value_error_returns_422():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        writing_router.submit(writing_router.SubmitIn(original=""), user_id="u1")
    assert exc.value.status_code == 422


def test_router_get_missing_returns_404():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        writing_router.get("w-bad", user_id="nobody")
    assert exc.value.status_code == 404


def test_router_delete_missing_returns_404():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        writing_router.delete("w-bad", user_id="nobody")
    assert exc.value.status_code == 404