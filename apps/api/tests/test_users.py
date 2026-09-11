"""多用户档案服务与接口（主题偏好 / 词汇量）的单元测试。

运行：uv run --directory apps/api pytest -q
"""
import json

import pytest
from fastapi import HTTPException

from app.routers import users as users_router
from app.services import users


def test_default_profile_shape():
    assert users.default_profile() == {"topic_preferences": [], "vocab_size": None, "updated_at": 0.0}


def test_get_profile_returns_default_for_unknown_or_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(users.settings, "users_path", str(tmp_path / "u.json"))
    assert users.get_profile("nobody")["vocab_size"] is None
    assert users.get_profile("nobody")["topic_preferences"] == []
    assert users.get_profile(None)["vocab_size"] is None


def test_upsert_and_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(users.settings, "users_path", str(tmp_path / "u.json"))
    users.upsert_profile("u1", {"vocab_size": 4200, "topic_preferences": ["science", "history"]})
    p = users.get_profile("u1")
    assert p["vocab_size"] == 4200
    assert p["topic_preferences"] == ["science", "history"]
    assert p["updated_at"] > 0


def test_upsert_merges_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(users.settings, "users_path", str(tmp_path / "u.json"))
    users.upsert_profile("u1", {"vocab_size": 4200})
    users.upsert_profile("u1", {"topic_preferences": ["sports"]})
    p = users.get_profile("u1")
    assert p["vocab_size"] == 4200  # 未更新的字段保留
    assert p["topic_preferences"] == ["sports"]


def test_get_vocab_size(tmp_path, monkeypatch):
    monkeypatch.setattr(users.settings, "users_path", str(tmp_path / "u.json"))
    assert users.get_vocab_size("u1") is None
    users.upsert_profile("u1", {"vocab_size": 5000})
    assert users.get_vocab_size("u1") == 5000


def test_persists_to_disk(tmp_path, monkeypatch):
    path = tmp_path / "u.json"
    monkeypatch.setattr(users.settings, "users_path", str(path))
    users.upsert_profile("u1", {"vocab_size": 3600})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["u1"]["vocab_size"] == 3600


def test_router_get_me_defaults_to_anonymous():
    resp = users_router.get_me(None)
    assert resp["user_id"] == "anonymous"
    assert resp["vocab_size"] is None
    assert resp["topic_preferences"] == []


def test_router_put_me_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(users.settings, "users_path", str(tmp_path / "u.json"))
    payload = users_router.ProfileIn(topic_preferences=["science"], vocab_size=4200)
    resp = users_router.put_me(payload, user_id="u1")
    assert resp["user_id"] == "u1"
    assert resp["vocab_size"] == 4200
    assert resp["topic_preferences"] == ["science"]


def test_router_put_me_rejects_unknown_topic(tmp_path, monkeypatch):
    monkeypatch.setattr(users.settings, "users_path", str(tmp_path / "u.json"))
    payload = users_router.ProfileIn(topic_preferences=["bogus"])
    with pytest.raises(HTTPException):
        users_router.put_me(payload, user_id="u1")
