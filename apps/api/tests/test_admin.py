"""后台管理系统（主题增删 + 文章 CRUD + 自动定级/提取生词）的测试。

覆盖：
  - 主题 add/delete/去重/非法 key/被引用删除 409；
  - suggest_level 落在合理区间并取整百；
  - build_glosses 产出「词族头 -> 中文释义」；
  - create_article 校验（缺正确项/缺主题/未知主题）与正常落库；
  - update_article / delete_article 往返。

运行：uv run --directory apps/api pytest -q
"""
import json

import pytest

from app.services import admin, ai, reading, topics
from tests.test_ai import _Resp


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    """主题与文章存储指向临时目录，隔离真实数据。"""
    from app.config import settings

    monkeypatch.setattr(settings, "topics_path", str(tmp_path / "topics.json"))
    monkeypatch.setattr(settings, "readings_path", str(tmp_path / "readings.json"))
    # 重置 reading 的 mtime 缓存，避免读到上一次测试的路径
    reading._readings_cache["mtime"] = None
    reading._readings_cache["data"] = None
    (tmp_path / "topics.json").write_text(
        json.dumps([{"key": "science", "label_zh": "科普"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "readings.json").write_text("[]", encoding="utf-8")
    return tmp_path


# ---------- 主题 ----------

def test_add_and_label_topic(isolated_data):
    topics.add_topic("space", "太空/宇宙")
    assert "space" in topics.get_topic_keys()
    assert topics.topic_label("space") == "太空/宇宙"


def test_add_duplicate_topic_raises(isolated_data):
    with pytest.raises(ValueError):
        topics.add_topic("science", "重复")


@pytest.mark.parametrize("bad", ["1bad", "Bad", "with_underscore", ""])
def test_add_invalid_topic_key_raises(isolated_data, bad):
    with pytest.raises(ValueError):
        topics.add_topic(bad, "非法")


def test_delete_topic(isolated_data):
    topics.add_topic("space", "太空")
    assert topics.delete_topic("space") is True
    assert topics.delete_topic("space") is False  # 已不存在


def test_delete_topic_in_use_returns_409(isolated_data):
    from fastapi import HTTPException

    from app.routers import admin as admin_router

    admin.create_article(_valid_article())
    with pytest.raises(HTTPException) as exc:
        admin_router.delete_topic("science")
    assert exc.value.status_code == 409


# ---------- 自动定级 / 提取生词 ----------

def test_suggest_level_in_range_and_rounded():
    body = "The solar system has eight planets and the sun is a star."
    r = reading.suggest_level(body)
    assert 500 <= r["level"] <= 20000
    assert r["level"] % 100 == 0
    assert 0.0 <= r["new_word_rate"] <= 1.0


def test_build_glosses_returns_lemma_to_gloss():
    g = reading.build_glosses("A dinosaur walked slowly.", 100)
    assert "dinosaur" in g
    assert g["dinosaur"]


def test_analyze_returns_level_and_glosses():
    r = admin.analyze("A dinosaur walked slowly.", 100)
    assert r["level"] == 100
    assert "dinosaur" in r["glosses"]
    assert r["glosses"]["dinosaur"]
    assert r["word_count"] >= 1
    assert 0.0 < r["new_word_rate"] <= 1.0


def test_analyze_dedupes_repeated_multiword(monkeypatch):
    # 同一多词短语在正文出现两次，scan_multiword 返回两条，analyze 只列一次
    def fake_scan(body):
        return [
            {"text": "odd number", "translation": "n. 奇数", "tag": "", "kind": "term", "pos_first": "n:100"},
            {"text": "odd number", "translation": "n. 奇数", "tag": "", "kind": "term", "pos_first": "n:100"},
        ]

    monkeypatch.setattr(admin.ecdict, "scan_multiword", fake_scan)
    r = admin.analyze("An odd number of bridges. An odd number of edges.", 100)
    assert [m["text"] for m in r["multiword"]] == ["odd number"]


# ---------- AI 语境义 ----------

def test_parse_json_strips_fences_and_noise():
    assert ai.parse_json_object('```json\n{"a": "b"}\n```') == {"a": "b"}
    assert ai.parse_json_object('前缀 {"a": "b"} 后缀') == {"a": "b"}
    assert (ai.parse_json_object("不是 json") or {}) == {}
    assert (ai.parse_json_object("") or {}) == {}


def test_generate_article_happy_path(monkeypatch):
    """AI 生成文章：返回 JSON 含 title_zh/title_en/topics/body，topic 过滤为合法 key。"""
    payload = json.dumps({
        "title_zh": "秋日田野",
        "title_en": "Autumn Fields",
        "topics": ["science", "history"],
        "body": "I walk in the fields...",
    }, ensure_ascii=False)
    monkeypatch.setattr(admin.ai, "chat", lambda *a, **k: payload)
    out = admin.generate_article(
        "秋日景色",
        "",
        2000,
        [{"key": "science", "label_zh": "科普"}, {"key": "history", "label_zh": "历史"}, {"key": "adventure", "label_zh": "冒险"}],
    )
    assert out["title_zh"] == "秋日田野"
    assert out["title_en"] == "Autumn Fields"
    assert out["topics"] == ["science", "history"]
    assert out["body"] == "I walk in the fields..."
    assert out["ai_used"] is True
    assert out["reason"] is None


def test_generate_article_filters_invalid_topics(monkeypatch):
    """AI 返回了不在可用列表中的 topic key，应被过滤掉。"""
    payload = json.dumps({
        "title_zh": "x", "title_en": "x",
        "topics": ["science", "bogus_topic", "history"],
        "body": "ok",
    }, ensure_ascii=False)
    monkeypatch.setattr(admin.ai, "chat", lambda *a, **k: payload)
    out = admin.generate_article(
        "outline", "", 2000,
        [{"key": "science", "label_zh": ""}, {"key": "history", "label_zh": ""}],
    )
    assert out["topics"] == ["science", "history"]  # bogus_topic 被过滤


def test_generate_article_handles_ai_runtime_error(monkeypatch):
    """AI 抛错时不应抛出，返回 ai_used=False + reason。"""
    def boom(*a, **k):
        raise RuntimeError("AI 返回 401：Unauthorized")
    monkeypatch.setattr(admin.ai, "chat", boom)
    out = admin.generate_article("outline", "", 2000, [])
    assert out["ai_used"] is False
    assert "401" in (out["reason"] or "")
    assert out["body"] == ""


def test_generate_article_handles_empty_content(monkeypatch):
    monkeypatch.setattr(admin.ai, "chat", lambda *a, **k: "")
    out = admin.generate_article("outline", "", 2000, [])
    assert out["ai_used"] is False
    assert "空内容" in (out["reason"] or "")


def test_generate_article_handles_unparseable_json(monkeypatch):
    monkeypatch.setattr(admin.ai, "chat", lambda *a, **k: "好的，我来帮你写：\n...")
    out = admin.generate_article("outline", "", 2000, [])
    assert out["ai_used"] is False
    assert "无法解析" in (out["reason"] or "")


def test_generate_article_empty_body_after_parse(monkeypatch):
    """AI 返回了合法 JSON 但 body 是空 → ai_used=False + reason 提示。"""
    monkeypatch.setattr(admin.ai, "chat", lambda *a, **k: json.dumps({
        "title_zh": "x", "title_en": "x", "topics": ["science"], "body": "",
    }))
    out = admin.generate_article("outline", "", 2000, [{"key": "science", "label_zh": ""}])
    assert out["ai_used"] is False
    assert "body" in (out["reason"] or "").lower() or "空" in (out["reason"] or "")
    body = "A dinosaur walked slowly."
    base = admin.analyze(body, 100)["glosses"]
    assert base  # 有生词
    lemma = next(iter(base))
    monkeypatch.setattr(
        admin.ai, "chat", lambda *a, **k: json.dumps({lemma: "AI义"}, ensure_ascii=False)
    )
    r = admin.ai_glosses(body, 100)
    assert r["glosses"][lemma] == "AI义"  # AI 覆盖
    assert set(r["glosses"]) == set(base)  # 其余保留词典义兜底
    assert r["multiword_glosses"] == {}
    assert r["ai_used"] is True
    assert r["reason"] is None


def test_ai_glosses_overrides_and_falls_back(monkeypatch):
    body = "A dinosaur walked slowly."
    base = admin.analyze(body, 100)["glosses"]
    assert base  # 有生词
    lemma = next(iter(base))
    monkeypatch.setattr(
        admin.ai, "chat", lambda *a, **k: json.dumps({lemma: "AI义"}, ensure_ascii=False)
    )
    r = admin.ai_glosses(body, 100)
    assert r["glosses"][lemma] == "AI义"  # AI 覆盖
    assert set(r["glosses"]) == set(base)  # 其余保留词典义兜底
    assert r["multiword_glosses"] == {}
    assert r["ai_used"] is True


def test_ai_glosses_preserves_existing_when_ai_partial(monkeypatch):
    """用户手工改过的词条，AI 只给出部分时应保留；AI 命中的按语境义覆盖。"""
    body = "A dinosaur walked slowly."
    base = admin.analyze(body, 100)["glosses"]
    assert base
    lemma = next(iter(base))
    # 用户把某个生词改成"自定义义"；AI 只返回部分
    existing = {lemma: "用户自改"}
    monkeypatch.setattr(
        admin.ai, "chat", lambda *a, **k: json.dumps({lemma: "AI义"}, ensure_ascii=False)
    )
    r = admin.ai_glosses(body, 100, existing_glosses=existing)
    assert r["glosses"][lemma] == "AI义"  # AI 覆盖用户


def test_ai_glosses_preserves_existing_when_ai_missing_key(monkeypatch):
    """AI 完全没返回该 key 时，保留用户词条（不退回词典义）。"""
    body = "A dinosaur and a kangaroo walked slowly beside a volcano."
    base = admin.analyze(body, 100)["glosses"]
    assert len(base) >= 2, f"需要 ≥2 个生词，实际 {list(base)}"
    lemma = next(iter(base))
    existing = {lemma: "用户自改"}
    other = next(k for k in base if k != lemma)
    monkeypatch.setattr(
        admin.ai, "chat", lambda *a, **k: json.dumps({other: "AI义"}, ensure_ascii=False)
    )
    r = admin.ai_glosses(body, 100, existing_glosses=existing)
    assert r["glosses"][lemma] == "用户自改"  # 用户词条保留，未被词典义冲掉
    assert r["glosses"][other] == "AI义"


def test_ai_glosses_preserves_existing_when_ai_empty(monkeypatch):
    """AI 返回空内容时不抛错，按"现有 + 词典兜底"返回，ai_used=False，reason 含原因。"""
    body = "A dinosaur walked slowly."
    base = admin.analyze(body, 100)["glosses"]
    assert base
    lemma = next(iter(base))
    existing = {lemma: "用户自改"}
    monkeypatch.setattr(admin.ai, "chat", lambda *a, **k: "")
    r = admin.ai_glosses(body, 100, existing_glosses=existing)
    assert r["ai_used"] is False
    assert r["glosses"][lemma] == "用户自改"  # 现有词条不丢
    # 其他生词仍补词典义
    assert all(r["glosses"][k] for k in base)
    assert r["reason"] is not None and "空内容" in r["reason"]


def test_ai_glosses_survives_ai_runtime_error(monkeypatch):
    """AI 整体抛 RuntimeError（如返回空、网络错）时，保留现有词条，不抛给前端。"""
    body = "A dinosaur walked slowly."
    base = admin.analyze(body, 100)["glosses"]
    lemma = next(iter(base))
    existing = {lemma: "用户自改"}

    def boom(*a, **k):
        raise RuntimeError("AI 返回 401：Unauthorized")

    monkeypatch.setattr(admin.ai, "chat", boom)
    r = admin.ai_glosses(body, 100, existing_glosses=existing)
    assert r["ai_used"] is False
    assert r["glosses"][lemma] == "用户自改"
    assert r["reason"] is not None and "401" in r["reason"]


def test_ai_glosses_reports_parse_error(monkeypatch):
    """AI 返回了内容但不是 JSON 时，reason 给出可读诊断（前端据此提示）。"""
    body = "A dinosaur walked slowly."
    base = admin.analyze(body, 100)["glosses"]
    lemma = next(iter(base))
    existing = {lemma: "用户自改"}
    # AI 给了散文式回答（合法 content，但非 JSON）
    garbage = "好的，我来为你解释：\n\n这是一个有趣的科学事实..."
    monkeypatch.setattr(admin.ai, "chat", lambda *a, **k: garbage)
    r = admin.ai_glosses(body, 100, existing_glosses=existing)
    assert r["ai_used"] is False
    assert r["glosses"][lemma] == "用户自改"  # 用户保留
    assert r["reason"] is not None and "无法解析" in r["reason"]


def test_ai_glosses_keeps_existing_keys_not_in_analyze(monkeypatch):
    """用户手工加的、analyze 没抽到的词条（如下面不超纲的词）应被保留。"""
    body = "A dinosaur walked slowly."
    monkeypatch.setattr(
        admin.ai, "chat", lambda *a, **k: json.dumps({}, ensure_ascii=False)
    )
    r = admin.ai_glosses(body, 100, existing_glosses={"custom": "用户加的"})
    assert r["glosses"]["custom"] == "用户加的"


# ---------- 文章 CRUD ----------

def _valid_article(**overrides) -> dict:
    data = {
        "title": "The Sun",
        "subtitle": "",
        "body": "The sun is a star. It is very hot.",
        "topics": ["science"],
        "target_level": None,
        "glosses": {},
        "full_glosses": {},
        "headwords": {},
        "quizzes": [
            {
                "type": "choice",
                "question": "What is the sun?",
                "options": [
                    {"text": "a star", "correct": True},
                    {"text": "a planet", "correct": False},
                    {"text": "a moon", "correct": False},
                    {"text": "a comet", "correct": False},
                ],
                "explanation_zh": "太阳是恒星",
                "explanation_en": "The sun is a star.",
            }
        ],
    }
    data.update(overrides)
    return data


def test_create_article_persists_and_auto_levels(isolated_data):
    article = admin.create_article(_valid_article())
    assert article["id"].startswith("r")
    assert article["target_level"] is not None  # 缺省自动定级
    assert reading.get_reading(article["id"]) is not None


def test_create_article_requires_correct_option(isolated_data):
    bad = _valid_article()
    bad["quizzes"][0]["options"] = [
        {"text": "a star", "correct": False},
        {"text": "a planet", "correct": False},
    ]
    with pytest.raises(ValueError):
        admin.create_article(bad)


def test_create_article_requires_topic(isolated_data):
    with pytest.raises(ValueError):
        admin.create_article(_valid_article(topics=[]))


def test_create_article_rejects_unknown_topic(isolated_data):
    with pytest.raises(ValueError):
        admin.create_article(_valid_article(topics=["nope"]))


def test_create_article_persists_skip(isolated_data):
    article = admin.create_article(_valid_article(skip=["ground"]))
    assert article["skip"] == ["ground"]
    assert reading.get_reading(article["id"])["skip"] == ["ground"]


def test_update_and_delete_article(isolated_data):
    article = admin.create_article(_valid_article())
    updated = admin.update_article(article["id"], _valid_article(title="Changed"))
    assert updated is not None
    assert updated["title"] == "Changed"
    assert admin.delete_article(article["id"]) is True
    assert reading.get_reading(article["id"]) is None
    assert admin.delete_article(article["id"]) is False


def test_get_article_edit_rebuilds_vocabulary_from_stored_glosses(isolated_data):
    article = admin.create_article(_valid_article(
        glosses={"dinosaur": "恐龙", "odd number": "奇数"},
        full_glosses={"dinosaur": "n. 恐龙"},
        headwords={"dinosaur": {"word": "dinosaur", "phonetic": "/ˈdaɪnə/"}},
    ))
    out = admin.get_article_edit(article["id"])
    assert out is not None
    by_lemma = {v["lemma"]: v for v in out["vocabulary"]}
    assert set(by_lemma) == {"dinosaur", "odd number"}  # 单词与短语键都回显
    assert by_lemma["dinosaur"]["word"] == "dinosaur"
    assert by_lemma["dinosaur"]["phonetic"] == "/ˈdaɪnə/"
    assert by_lemma["dinosaur"]["full_gloss"] == "n. 恐龙"
    assert out["word_count"] >= 1
    assert "new_word_rate" in out


def test_router_list_topics_includes_article_count(isolated_data):
    from app.routers import admin as admin_router

    admin.create_article(_valid_article())
    resp = admin_router.list_topics()
    assert resp["items"][0]["key"] == "science"
    assert resp["items"][0]["article_count"] == 1


# ---------- /api/ai/test ----------


def test_ai_test_endpoint_returns_ok_on_success(monkeypatch, tmp_path):
    """测试连接：AI 返回正常时 ok=True，content 即去空白后的回复。"""
    from app.config import settings
    from app.routers import admin as admin_router

    monkeypatch.setattr(settings, "ai_config_path", str(tmp_path / "ai.json"))
    admin.ai.add_provider("P", "https://x/v1", "k", "m")
    admin.ai.set_default("P")
    monkeypatch.setattr(
        admin.ai.httpx, "post",
        lambda *a, **k: _Resp(200, {"choices": [{"message": {"content": "pong"}}]}),
    )
    out = admin_router.test_ai(admin_router.AITestIn())
    assert out["ok"] is True
    assert out["content"] == "pong"


def test_ai_test_endpoint_returns_error_message(monkeypatch, tmp_path):
    """测试连接：AI 失败时 ok=False，error 含原始异常信息（前端可显示给用户）。"""
    from app.config import settings
    from app.routers import admin as admin_router

    monkeypatch.setattr(settings, "ai_config_path", str(tmp_path / "ai.json"))
    admin.ai.add_provider("P", "https://x/v1", "wrong-key", "m")
    admin.ai.set_default("P")
    monkeypatch.setattr(
        admin.ai.httpx, "post",
        lambda *a, **k: _Resp(401, {"error": {"message": "Invalid API key"}}),
    )
    out = admin_router.test_ai(admin_router.AITestIn())
    assert out["ok"] is False
    assert "401" in out["error"]
    assert "Invalid API key" in out["error"]


def test_ai_test_endpoint_targets_named_provider(monkeypatch, tmp_path):
    """传 name 时测试指定提供者；不传时测试默认。"""
    from app.config import settings
    from app.routers import admin as admin_router

    monkeypatch.setattr(settings, "ai_config_path", str(tmp_path / "ai.json"))
    admin.ai.add_provider("Default", "https://default/v1", "k", "m")
    admin.ai.add_provider("Alt", "https://alt/v1", "k", "m")
    admin.ai.set_default("Default")

    captured = {}

    def fake_post(url, **kw):
        captured.setdefault("calls", []).append(url)
        return _Resp(200, {"choices": [{"message": {"content": "pong"}}]})

    monkeypatch.setattr(admin.ai.httpx, "post", fake_post)

    # 不传 name → 默认
    out = admin_router.test_ai(admin_router.AITestIn())
    assert out["ok"] is True
    assert any("default" in u for u in captured["calls"])

    # 传 name → 指定
    out = admin_router.test_ai(admin_router.AITestIn(name="Alt"))
    assert out["ok"] is True
    assert any("alt" in u for u in captured["calls"])

    # 不存在的 name → error
    out = admin_router.test_ai(admin_router.AITestIn(name="Ghost"))
    assert out["ok"] is False
    assert "Ghost" in out["error"]
