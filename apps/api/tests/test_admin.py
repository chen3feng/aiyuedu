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

from app.services import admin, reading, topics


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


# ---------- AI 语境义 ----------

def test_parse_json_strips_fences_and_noise():
    assert admin._parse_json('```json\n{"a": "b"}\n```') == {"a": "b"}
    assert admin._parse_json('前缀 {"a": "b"} 后缀') == {"a": "b"}
    assert admin._parse_json("不是 json") == {}
    assert admin._parse_json("") == {}


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
    assert admin.get_article(article["id"]) is None
    assert admin.delete_article(article["id"]) is False


def test_router_list_topics_includes_article_count(isolated_data):
    from app.routers import admin as admin_router

    admin.create_article(_valid_article())
    resp = admin_router.list_topics()
    assert resp["items"][0]["key"] == "science"
    assert resp["items"][0]["article_count"] == 1
